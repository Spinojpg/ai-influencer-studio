#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.0.11: Juggernaut XL, poredak scene u /api/generate, regresija 500."""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import image_gen
import model_download
import studio

FAILED = 0


def check(cond, msg):
    global FAILED
    if cond:
        print("  OK ", msg)
    else:
        FAILED += 1
        print("  FAIL", msg)


def clip_texts(wf: dict, *, skip_negative: bool = True) -> dict[str, str]:
    out = {}
    for nid, node in (wf or {}).items():
        if not isinstance(node, dict) or node.get("class_type") != "CLIPTextEncode":
            continue
        text = str((node.get("inputs") or {}).get("text") or "")
        if skip_negative and nid == "7":
            continue
        out[str(nid)] = text
    return out


def long_appearance() -> str:
    fluff = (
        "portrait of a beautiful young woman, looking at the camera, studio lighting, "
        "professional portrait, clean background, headshot, smiling at the camera, "
        "standing pose, softbox lighting, sharp focus"
    )
    ident = "long wavy chestnut brown hair, bright green eyes, light freckles, natural makeup, hoop earrings"
    return (fluff + ", ") * 6 + ident


def test_juggernaut():
    print("== Juggernaut XL Ragnarok u predloženim modelima ==")
    item = model_download.curated_by_id("juggernaut-xl-ragnarok")
    check(item is not None, "curated id postoji")
    if not item:
        return
    check(item["arch"] == "sdxl" and item["kind"] == "checkpoint", "SDXL checkpoint")
    check(item["filename"] == "juggernautXL_ragnarok.safetensors", f"filename={item.get('filename')}")
    url = item["url"]
    check(url.startswith("https://huggingface.co/Kandoo/Juggernaut-XL-Ragnarok/"), f"url={url}")
    check(int(item.get("size_bytes") or 0) == 7105350162, f"size={item.get('size_bytes')}")
    rec = item.get("recommended") or {}
    check(rec.get("cfg") == 5.0 and rec.get("steps") == 30, f"recommended {rec}")
    check(rec.get("sampler_name") == "dpmpp_2m" and rec.get("scheduler") == "karras", "dpmpp_2m karras")
    check(item.get("turbo_compatible") is True, "Turbo LoRA compatible")
    check("lustify" not in json.dumps(model_download.CURATED).lower(), "nema Lustify u popisu")
    check(
        image_gen.detect_model_arch(item["filename"]) == "sdxl",
        "detect_model_arch(juggernautXL_ragnarok) = sdxl",
    )
    # HEAD: javni URL se mora razriješiti (200 / redirect na octet-stream)
    try:
        req = urllib.request.Request(
            url,
            method="HEAD",
            headers={"User-Agent": "AI-Influencer-Studio/1.0.11"},
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            length = int(resp.headers.get("Content-Length") or 0)
            ctype = (resp.headers.get("Content-Type") or "").lower()
        check(code in {200, 302, 301, 307, 308}, f"HEAD status={code}")
        check(length == 7105350162 or length == 0, f"HEAD Content-Length={length}")
        check("text/html" not in ctype, f"HEAD Content-Type={ctype}")
    except Exception as exc:
        check(False, f"HEAD nije uspio: {exc}")


def test_generate_prompt_order():
    print("== /api/generate: scena prva u CLIPTextEncode, dugi izgled odvojen ==")
    appearance = long_appearance()
    scene = "lying on a bed, casual phone photo, messy sheets, holding a phone"
    # Prazan object_info: prije 1.0.11 se sve spojilo u jedan encode i izgled je potisnuo scenu.
    result = studio.plan_image_generation(
        {
            "prompt": scene,
            "persona": appearance,
            "model": "RealVisXL_V5.0_fp16.safetensors",
            "model_type": "sdxl",
            "width": 768,
            "height": 1152,
            "steps": 30,
            "cfg": 5,
            "seed": 42,
            "quality_prefix": True,
            "turbo": False,
        },
        profile={"appearance_prompt": appearance, "preferred_model": "RealVisXL_V5.0_fp16.safetensors"},
        object_info={},
    )
    check(result.get("ok") is True, f"plan ok: {result.get('error')}")
    wf = result.get("workflow") or {}
    texts = clip_texts(wf)
    first = texts.get("6") or ""
    check("lying on a bed" in first, f"scena u node 6: {first!r}")
    check("casual phone photo" in first, "phone photo u prvom encodeu")
    check(first.lower().startswith("adult woman") or first.lower().startswith("(adult"), f"adult na početku: {first!r}")
    check("portrait of" not in first.lower(), f"nema 'portrait of' u prvom encodeu: {first!r}")
    # Dugi izgled ne smije biti u istom 77-token prozoru kao scena.
    check("chestnut brown hair" not in first.lower(), f"izgled nije u node 6: {first!r}")
    later = " ".join(v for k, v in texts.items() if k != "6")
    check("chestnut brown hair" in later.lower(), f"izgled u kasnijem encodeu: {later!r}")
    check("looking at the camera" not in later.lower() and "studio lighting" not in later.lower(),
          f"studio/kamera tropi maknuti iz izgleda: {later!r}")
    check("portrait of" not in later.lower(), f"nema 'portrait of' ni u kasnijem encodeu: {later!r}")
    check("standing pose" not in later.lower(), f"nema standing pose u izgledu: {later!r}")
    concats = [n for n in wf.values() if isinstance(n, dict) and n.get("class_type") == "ConditioningConcat"]
    check(len(concats) >= 1, f"ConditioningConcat i bez object_info, x{len(concats)}")
    pos = (wf.get("3") or {}).get("inputs", {}).get("positive")
    check(pos and pos[0] != "6", f"KSampler.positive je spojeni cond {pos}")
    # Scena je i dalje ispred izgleda u spojenom promptu
    prompt = (result.get("meta") or {}).get("prompt") or ""
    check(prompt.index("lying on a bed") < prompt.index("chestnut brown hair"), "meta prompt: scena prije izgleda")

    # I s katalogom čvorova (uključujući ConditioningConcat) isti poredak
    result2 = studio.plan_image_generation(
        {
            "prompt": scene,
            "persona": appearance,
            "model": "juggernautXL_ragnarok.safetensors",
            "seed": 7,
            "quality_prefix": True,
        },
        object_info={"CLIPTextEncode": {}, "KSampler": {}, "ConditioningConcat": {}, "LoraLoader": {}},
    )
    check(result2.get("ok") is True, "plan s object_info")
    check((result2.get("meta") or {}).get("arch") == "sdxl", f"arch={ (result2.get('meta') or {}).get('arch') }")
    first2 = clip_texts(result2.get("workflow") or {}).get("6") or ""
    check("lying on a bed" in first2 and "chestnut brown hair" not in first2.lower(), f"node 6 s katalogom: {first2!r}")


def test_generate_workflow_regression():
    print("== regresija 1.0.9/1.0.10: /api/generate gradi workflow (sampler_name, turbo) ==")
    # Točno argumenti koji su u 1.0.9 bacili TypeError: sampler_name
    wf = studio.build_workflow(
        prompt="lying on a bed",
        negative="blurry",
        model="RealVisXL_V5.0_fp16.safetensors",
        width=768,
        height=1152,
        batch=1,
        seed=1,
        steps=30,
        cfg=5.0,
        sampler_name="dpmpp_2m",
        scheduler="karras",
        arch="sdxl",
        hires=False,
        object_info={},
        lora="",
        lora_strength=1.0,
        turbo=False,
        prompt_chunks=["adult woman, (lying on a bed:1.3)", "brown hair"],
    )
    check(wf["3"]["inputs"]["sampler_name"] == "dpmpp_2m", "passthrough sampler_name")
    check(wf["3"]["inputs"]["scheduler"] == "karras", "scheduler")
    check(wf["5"]["inputs"]["width"] == 768, "latent 768")
    check("lying on a bed" in wf["6"]["inputs"]["text"], "scena u encodeu")

    orig = image_gen.lora_available
    image_gen.lora_available = lambda name, folder=None: True
    try:
        turbo = studio.plan_image_generation(
            {
                "prompt": "sitting in a cafe by the window",
                "persona": "portrait of a woman, long brown hair, green eyes, looking at the camera",
                "model": "RealVisXL_V5.0_fp16.safetensors",
                "turbo": True,
                "quality_prefix": True,
                "hires": True,
                "seed": 99,
                "steps": 30,
            },
            object_info={},
        )
    finally:
        image_gen.lora_available = orig
    check(turbo.get("ok") is True, f"turbo plan: {turbo.get('error')}")
    tw = turbo.get("workflow") or {}
    tm = turbo.get("meta") or {}
    check(tm.get("turbo") is True and tm.get("steps") == 8 and tm.get("hires") is False, f"turbo meta {tm}")
    check(tw["3"]["inputs"]["sampler_name"] == "euler", f"turbo sampler {tw.get('3', {}).get('inputs')}")
    check(tw["3"]["inputs"]["scheduler"] == "sgm_uniform", "turbo scheduler")
    check(tw["12"]["class_type"] == "LoraLoader", "turbo LoraLoader")
    check("sitting in a cafe" in tw["6"]["inputs"]["text"], f"turbo scena: {tw['6']['inputs']['text']!r}")
    check("looking at the camera" not in tw["6"]["inputs"]["text"].lower(), "kamera trop nije u prvom encodeu")


def test_presets():
    print("== SDXL zadani portret 768×1152 ==")
    check(image_gen.presets_for("sdxl")[0]["width"] == 768, "768")
    check(image_gen.presets_for("sdxl")[0]["height"] == 1152, "1152")


def main():
    test_juggernaut()
    test_generate_prompt_order()
    test_generate_workflow_regression()
    test_presets()
    print()
    if FAILED:
        print(f"FAILED {FAILED}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
