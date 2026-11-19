#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.0.9: prompt poredak, Turbo LoRA, AnimateDiff workflow, UI."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import image_gen
import model_download
import video as video_mod

FAILED = 0

def check(cond, msg):
    global FAILED
    if cond:
        print("  OK ", msg)
    else:
        FAILED += 1
        print("  FAIL", msg)


def test_prompt_order():
    print("== prompt: scena prva, izgled drugi, kvaliteta na kraju ==")
    built = image_gen.build_positive_prompt(
        scene="lying on a bed, casual phone photo, messy sheets",
        appearance="portrait of a woman, long brown hair, green eyes, studio lighting, looking at camera",
        quality=True,
    )
    check(built["chunks"][0].startswith("adult woman") and "lying on a bed" in built["chunks"][0], f"head={built['chunks'][0]!r}")
    check(not built["appearance"].lower().startswith("portrait"), f"appearance={built['appearance']!r}")
    check(any(c.startswith("RAW photo") for c in built["chunks"]), f"quality in chunks={built['chunks']!r}")
    check(built["prompt"].index("lying on a bed") < built["prompt"].index("long brown hair"), "scena prije izgleda")
    check(built["prompt"].index("long brown hair") < built["prompt"].index("RAW photo"), "izgled prije kvalitete")
    # already has adult
    b2 = image_gen.build_positive_prompt(scene="adult woman sitting", appearance="brown hair", quality=False)
    check("adult woman sitting" in b2["chunks"][0] and b2["chunks"][0].lower().count("adult woman") == 1, f"no dup adult {b2['chunks'][0]!r}")
    check(b2["adult_term"] == "", "adult already present")
    long_app = ", ".join(["long brown hair, green eyes, detailed skin"] * 10)
    b3 = image_gen.build_positive_prompt(scene="on a bed taking a phone selfie", appearance=long_app, quality=True)
    check(b3["warn"] and b3["tokens"] > 75, f"warn tokens={b3['tokens']}")
    check(b3["chunks"][0].startswith("adult woman") and "on a bed" in b3["chunks"][0], "scena ostaje u prvom chunku i kad je ukupno dugo")
    check("portrait of" not in image_gen.strip_leading_portrait("a photorealistic portrait of a woman smiling").lower(), "strip portrait prefix")
    info = {"ConditioningConcat": {}, "LoraLoader": {}}
    wf = image_gen.build_workflow(
        prompt=b3["prompt"], negative="neg", model="m.safetensors",
        width=768, height=1152, batch=1, seed=1, steps=30, arch="sdxl",
        prompt_chunks=b3["chunks"], object_info=info,
    )
    concats = [n for n in wf.values() if n.get("class_type") == "ConditioningConcat"]
    check(len(concats) >= 1, f"ConditioningConcat x{len(concats)}")
    check(wf["6"]["inputs"]["text"].startswith("adult woman"), "prvi encode je scena")
    check(wf["3"]["inputs"]["positive"][0] != "6", "ksampler čita spojeni cond")


def test_turbo():
    print("== Turbo Hyper-SDXL 8 koraka ==")
    spec = image_gen.TURBO_SDXL
    check(spec["steps"] == 8 and spec["cfg"] == 5 and spec["sampler_name"] == "euler", "postavke")
    check(spec["scheduler"] == "sgm_uniform", "scheduler sgm_uniform")
    item = model_download.curated_by_id("hyper-sdxl-8step-cfg")
    check(item and item["filename"] == spec["lora_filename"] and item["kind"] == "lora", "curated lora")
    check(model_download.dest_dir_for("lora").name == "loras", "dest loras")
    wf = image_gen.build_workflow(
        prompt="a cafe", negative="neg", model="RealVisXL_V5.0_fp16.safetensors",
        width=768, height=1152, batch=1, seed=1, steps=30, arch="sdxl", turbo=True,
        object_info={"LoraLoader": {}},
    )
    check(wf["12"]["class_type"] == "LoraLoader", "LoraLoader")
    check(wf["12"]["inputs"]["lora_name"] == spec["lora_filename"], "lora name")
    check(wf["3"]["inputs"]["steps"] == 8 and wf["3"]["inputs"]["cfg"] == 5, "8 / cfg 5")
    check(wf["3"]["inputs"]["sampler_name"] == "euler" and wf["3"]["inputs"]["scheduler"] == "sgm_uniform", "euler+sgm")
    check("10" not in wf, "nema hires u turbo")


def test_video_workflow():
    print("== AnimateDiff workflow ==")
    rec = video_mod.recommend_settings(8)
    check(rec["width"] == 512 and rec["frames"] == 16 and rec["fps"] == 8, f"recommend {rec}")
    info = {
        "ADE_AnimateDiffLoaderGen1": {"input": {"required": {
            "model": ["MODEL"],
            "model_name": [["mm_sd_v15_v2.ckpt"]],
            "beta_schedule": [["autoselect"], {"default": "autoselect"}],
        }}},
        "VHS_VideoCombine": {"input": {"required": {
            "images": ["IMAGE"],
            "frame_rate": ["FLOAT", {"default": 8}],
            "loop_count": ["INT", {"default": 0}],
            "filename_prefix": ["STRING", {"default": "AnimateDiff"}],
            "format": [["image/gif", "video/h264-mp4"], {"default": "image/gif"}],
            "pingpong": ["BOOLEAN", {"default": False}],
            "save_output": ["BOOLEAN", {"default": True}],
        }}},
        "ConditioningConcat": {},
        "ImageScale": {},
        "RepeatLatentBatch": {},
        "LoadImage": {},
    }
    caps = video_mod.classify_nodes(info)
    caps["motion_model"] = "mm_sd_v15_v2.ckpt"
    caps["motion_models"] = ["mm_sd_v15_v2.ckpt"]
    # no AD -> not ready without motion on disk, but build uses caps motion
    wf, note = video_mod.build_video_workflow(
        caps, prompt="soft movement", negative="blur",
        model="Realistic_Vision_V5.1_fp16-no-ema.safetensors",
        width=512, height=512, frames=16, steps=16, seed=3, fps=8,
        object_info=info,
    )
    check(wf is not None, f"wf {note}")
    check(wf and wf["12"]["class_type"] == "ADE_AnimateDiffLoaderGen1", "Gen1 loader")
    check(wf and wf["5"]["inputs"]["batch_size"] == 16, "16 frames latent")
    check(wf and wf["21"]["class_type"] == "VHS_VideoCombine", "VHS combine")
    check(wf and "h264-mp4" in str(wf["21"]["inputs"].get("format")), f"mp4 format {wf['21']['inputs'].get('format') if wf else None}")
    # SDXL without SDXL motion module is rejected (does not send SD 1.5 module)
    bad, err = video_mod.build_video_workflow(
        caps, prompt="x", negative="n", model="RealVisXL_V5.0_fp16.safetensors",
        width=512, height=512, frames=16, steps=16, seed=1, object_info=info,
    )
    check(bad is None and "mm_sdxl_v10_beta" in (err or "") and "SDXL" in (err or ""), f"reject sdxl without module {err}")
    # img2vid
    w2, n2 = video_mod.build_video_workflow(
        caps, prompt="gentle motion", negative="n",
        model="Realistic_Vision_V5.1_fp16-no-ema.safetensors",
        width=512, height=512, frames=16, steps=16, seed=1, fps=8,
        init_image="last.png", object_info=info,
    )
    check(w2 and w2["15"]["class_type"] == "LoadImage", "LoadImage")
    check(w2 and w2["18"]["class_type"] == "RepeatLatentBatch" and w2["18"]["inputs"]["amount"] == 16, "repeat latent")
    check(w2 and 0.45 <= w2["3"]["inputs"]["denoise"] <= 0.85, f"img2vid denoise {w2['3']['inputs']['denoise'] if w2 else None}")
    # missing nodes
    empty, msg = video_mod.build_video_workflow(
        {"animatediff": [], "vhs": [], "message": "nema čvorova"},
        prompt="x", negative="n", model="rv.safetensors",
        width=512, height=512, frames=8, steps=16, seed=1, object_info={},
    )
    check(empty is None and msg, f"no nodes: {msg}")
    # Gen2 path
    info2 = {
        "ADE_LoadAnimateDiffModel": {"input": {"required": {"model_name": [["mm_sd_v15_v2.ckpt"]]}}},
        "ADE_ApplyAnimateDiffModelSimple": {"input": {"required": {"motion_model": ["MOTION_MODEL_ADE"]}}},
        "ADE_UseEvolvedSampling": {"input": {"required": {
            "model": ["MODEL"],
            "beta_schedule": [["autoselect"], {"default": "autoselect"}],
        }}},
        "VHS_VideoCombine": info["VHS_VideoCombine"],
    }
    caps2 = video_mod.classify_nodes(info2)
    caps2["motion_model"] = "mm_sd_v15_v2.ckpt"
    w3, n3 = video_mod.build_video_workflow(
        caps2, prompt="x", negative="n",
        model="Realistic_Vision_V5.1_fp16-no-ema.safetensors",
        width=512, height=512, frames=16, steps=16, seed=1, object_info=info2,
    )
    check(w3 and w3["12"]["class_type"] == "ADE_LoadAnimateDiffModel", "Gen2 load")
    check(w3 and w3["14"]["class_type"] == "ADE_UseEvolvedSampling", "Gen2 evolved")
    fmt, _ = video_mod.pick_vhs_format(info)
    check("mp4" in fmt.lower() or "h264" in fmt.lower(), f"pick format {fmt}")


def test_ui():
    print("== UI 1.0.9 ==")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    check('data-tab="video"' in html and 'id="tab-video"' in html, "kartica Video")
    check("Instaliraj video podršku" in html, "gumb instalacije")
    check("Turbo<br>8 koraka" in html or "Turbo" in html, "Turbo chip")
    check('id="tokenCount"' in html and "updateTokenCount" in html, "brojač tokena")
    check("Opis scene" in html, "label Opis scene")
    check('id="videoBox"' not in html, "stari video details uklonjen iz Slike")
    # advanced contains model, seed, negative
    adv = html[html.find("<details class=\"adv\">"):html.find('id="tab-video"')]
    check("id=\"model\"" in adv and "id=\"seed\"" in adv and "id=\"negative\"" in adv, "napredno: model/seed/negative")
    check("id=\"qualityPrefix\"" in adv and "id=\"hiresFix\"" in adv, "napredno: kvaliteta/hires")
    check("create-form" in html, "create-form class")
    py = (ROOT / "studio.py").read_text(encoding="utf-8")
    check("/api/video/install" in py and "build_positive_prompt" in py, "API install + novi prompt")
    check((ROOT / "video_install.py").is_file(), "video_install.py")


def main():
    test_prompt_order()
    test_turbo()
    test_video_workflow()
    test_ui()
    print()
    if FAILED:
        print(f"FAILED {FAILED}")
        return 1
    print("ALL OK")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
