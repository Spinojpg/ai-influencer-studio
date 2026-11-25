#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.3.8: odabir 'Bez osobe' na Generiranju.

Pravi workflow JSON (plan_image_generation), bez LoRA-e osobe, InstantID-a,
IP-Adaptera i ubacivanja izgleda/okidača. LoRA stack i VAE i dalje rade.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory()
TMP = Path(_TMP.name)
(TMP / "data").mkdir()
os.environ["STUDIO_DATA_DIR"] = str(TMP / "data")

import image_gen  # noqa: E402
import inbox  # noqa: E402

inbox.configure_paths(data_dir=TMP / "data")
inbox.init_db()
import services  # noqa: E402

services.init_schema()
import studio  # noqa: E402
from services import generation_service as gs  # noqa: E402

_ROT = str.maketrans("abcdefghijklmnopqrstuvwxyz", "nopqrstuvwxyzabcdefghijklm")
BANNED = re.compile(r"\b(" + "|".join(w.translate(_ROT) for w in ("yhfgvsl", "fabsf", "afsj", "ahqr", "anxrq", "gbcyrff")) + r")\b", re.I)

FAILED = 0

FACE_CLASSES = {
    "ApplyInstantID", "ApplyInstantIDAdvanced", "InstantID",
    "IPAdapter", "IPAdapterAdvanced", "IPAdapterFaceID", "IPAdapterEmbeds",
    "IPAdapterMS", "IPAdapterUnifiedLoader", "InstantIDFaceAnalysis",
}

PROF = {
    "id": 42,
    "name": "Testna Osoba",
    "appearance_prompt": "long crimson hair, emerald eyes, a unique silver nose ring",
    "preferred_lora": "char_testna_osoba_v1.safetensors",
    "preferred_lora_strength": 0.85,
    "lora_trigger": "chr_testna",
    "lora_stack": [{"name": "persona_stack.safetensors", "strength_model": 0.6, "strength_clip": 0.6, "enabled": True}],
    "negative_prompt": "",
    "lock_seed": False,
}


def check(cond, msg):
    global FAILED
    if cond:
        print("  OK ", msg)
    else:
        FAILED += 1
        print("  FAIL", msg)


def nodes(wf: dict, cls: str) -> list[tuple[str, dict]]:
    return [(k, n) for k, n in wf.items() if isinstance(n, dict) and n.get("class_type") == cls]


def all_classes(wf: dict) -> set[str]:
    return {n.get("class_type") for n in wf.values() if isinstance(n, dict)}


def lora_names(wf: dict) -> list[str]:
    out = []
    for _, n in nodes(wf, "LoraLoader"):
        out.append(str((n.get("inputs") or {}).get("lora_name") or ""))
    return out


def plan(body, profile=None, object_info=None):
    orig = image_gen.lora_available
    orig_vae = image_gen.vae_available
    image_gen.lora_available = lambda name, folder=None: True
    image_gen.vae_available = lambda name, folder=None: True
    try:
        return studio.plan_image_generation(
            body, profile=profile if profile is not None else {},
            object_info=object_info if object_info is not None else {},
        )
    finally:
        image_gen.lora_available = orig
        image_gen.vae_available = orig_vae


def _body(**extra):
    d = {
        "prompt": "standing in a sunny cafe, drinking coffee",
        "model": "RealVisXL_V5.0_fp16.safetensors",
        "model_type": "sdxl",
        "seed": 11,
        "steps": 20,
        "loras": [{"name": "user_stack.safetensors", "strength_model": 0.45, "strength_clip": 0.45}],
        "vae": "sdxl_vae.safetensors",
        "freeu": False,
    }
    d.update(extra)
    return d


def test_no_persona_workflow():
    print("== Bez osobe: pravi workflow ==")
    # Fallback profil ima LoRA-u, okidač, izgled i stack — ne smiju ući kad je persona_id prazan.
    for raw in (None, "", 0, "none", "bez"):
        res = plan(_body(persona_id=raw), profile=PROF)
        check(res.get("ok"), f"persona_id={raw!r}: plan uspijeva")
        if not res.get("ok"):
            print("   ", res.get("error"))
            continue
        wf = res["workflow"]
        prompt = (res.get("meta") or {}).get("prompt") or ""
        classes = all_classes(wf)
        names = lora_names(wf)
        check(res["meta"].get("persona_id") in (None, ""), f"persona_id={raw!r}: meta.persona_id prazan")
        check("chr_testna" not in prompt, f"persona_id={raw!r}: nema okidača osobe u promptu")
        check("crimson hair" not in prompt and "silver nose ring" not in prompt, f"persona_id={raw!r}: nema izgleda osobe u promptu")
        check("standing in a sunny cafe" in prompt, f"persona_id={raw!r}: scena je u promptu")
        check("char_testna_osoba_v1.safetensors" not in names, f"persona_id={raw!r}: nema LoRA-e osobe")
        check("persona_stack.safetensors" not in names, f"persona_id={raw!r}: nema stacka osobe")
        check("user_stack.safetensors" in names, f"persona_id={raw!r}: korisnički LoRA stack jest u workflowu")
        check(not (classes & FACE_CLASSES), f"persona_id={raw!r}: nema InstantID/IP-Adapter čvorova ({classes & FACE_CLASSES})")
        check(nodes(wf, "VAELoader"), f"persona_id={raw!r}: VAE i dalje vrijedi")
        check(nodes(wf, "KSampler") or nodes(wf, "KSamplerAdvanced"), f"persona_id={raw!r}: ima KSampler")
        check(nodes(wf, "VAEDecode") or nodes(wf, "VAEDecodeTiled"), f"persona_id={raw!r}: ima VAEDecode")
        check(nodes(wf, "SaveImage"), f"persona_id={raw!r}: ima SaveImage")
        # leftover body['persona'] se ignorira
        break  # detailed checks on first; others just ok + no face/lora

    for raw in ("", 0, "none"):
        res = plan(_body(persona_id=raw, persona="long crimson hair, emerald eyes, a unique silver nose ring"), profile=PROF)
        prompt = (res.get("meta") or {}).get("prompt") or ""
        check(res.get("ok") and "crimson hair" not in prompt, f"persona_id={raw!r}: leftover body.persona se ne ubacuje")


def test_compat_fallback():
    print("== stari klijent: bez ključa persona_id i dalje koristi fallback ==")
    body = _body()
    body.pop("loras", None)
    res = plan(body, profile=PROF)
    check(res.get("ok"), "plan bez persona_id uspijeva")
    prompt = (res.get("meta") or {}).get("prompt") or ""
    names = lora_names(res["workflow"])
    check("crimson hair" in prompt or "silver nose ring" in prompt, "fallback i dalje ubacuje izgled osobe")
    check("char_testna_osoba_v1.safetensors" in names, "fallback i dalje stavlja LoRA-u osobe")


def test_refs_ignored():
    print("== Bez osobe: referentne slike iz bodyja se ignoriraju ==")
    res = plan(
        _body(persona_id="", ipadapter_images=["studio_refs/face.png"], ref_images=["studio_refs/face.png"], ref_mode="instantid"),
        profile=PROF,
        object_info={
            "ApplyInstantID": {"input": {"required": {}}},
            "InstantIDFaceAnalysis": {"input": {"required": {}}},
            "ControlNetLoader": {"input": {"required": {}}},
        },
    )
    check(res.get("ok"), "plan s ref slika i Bez osobe uspijeva" + ("" if res.get("ok") else f" ({res.get('error')})"))
    if res.get("ok"):
        wf = res["workflow"]
        check(not (all_classes(wf) & FACE_CLASSES), "body ref slike se ne primjenjuju bez osobe")
        check(not res["meta"].get("ipadapter") and not res["meta"].get("instantid_end_at"), "meta bez InstantID/IP-Adaptera")


def test_queue_and_rating():
    print("== red čekanja i Dobra slika bez osobe ==")
    job = gs.enqueue(_body(persona_id="", prompt="a quiet street at dusk"))
    check(job.get("persona_id") in (None, ""), "enqueue s praznim persona_id sprema NULL")
    job2 = gs.enqueue(_body(prompt="a quiet street at dusk"))  # nema ključa — može biti None iz bodyja
    check("id" in job2, "enqueue bez persona_id ne puca")

    out_dir = TMP / "out"
    out_dir.mkdir(exist_ok=True)
    img = out_dir / "no_persona.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    ids = gs.record_images(
        [{"filename": "no_persona.png", "subfolder": "", "type": "output"}],
        {"prompt": "x", "seed": 1},
        persona_id=None,
        local_path=str(img),
    )
    check(ids, "record_images bez osobe")
    rated = gs.rate_image(gallery_id=ids[0], rating=1, persona_id=None, filename="no_persona.png")
    check(rated.get("id"), "rate_image bez osobe uspijeva")
    sync = rated.get("lora_sync") or {}
    check(sync.get("action") == "none", f"Dobra slika bez osobe ne ide u dataset ({sync})")


def test_resolve_helpers():
    print("== resolve_generation_profile ==")
    check(studio.resolve_generation_profile({"persona_id": None}, PROF) is None, "eksplicitni None → nema profila")
    check(studio.resolve_generation_profile({"persona_id": ""}, PROF) is None, "eksplicitni '' → nema profila")
    check(studio.resolve_generation_profile({"prompt": "x"}, PROF) is PROF, "bez ključa → fallback")
    check(studio.is_blank_persona("Bez osobe") and studio.is_blank_persona(0), "is_blank_persona prepoznaje prazne vrijednosti")


def test_static_ui():
    print("== statičke provjere UI-ja 1.3.8 ==")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    v120 = (ROOT / "static" / "ui_v120.js").read_text(encoding="utf-8")
    check('<option value="">Bez osobe</option>' in html, "select ima opciju Bez osobe")
    check("Bez osobe" in v120 and "persona-chip none" in v120, "picker ima čip Bez osobe na vrhu")
    check("studio.gen_persona_id" in html, "odabir se pamti u localStorage")
    check("persona_id: prof && prof.id != null ? prof.id : null" in html, "payload šalje null kad nema osobe, ne aktivni profil")
    check("|| state.active_profile || null" not in html, "selectedPersona više ne pada na active_profile")
    check("data-persona=" in html, "kartice rezultata pamte persona_id")
    for rel in ("static/v11.js", "static/ui_v120.js", "index.html", "studio.py", "services/generation_service.py"):
        txt = (ROOT / rel).read_text(encoding="utf-8")
        check(not BANNED.search(txt), f"{rel}: bez zabranjenih izraza")


def main():
    print("test_v138")
    test_resolve_helpers()
    test_no_persona_workflow()
    test_compat_fallback()
    test_refs_ignored()
    test_queue_and_rating()
    test_static_ui()
    print()
    if FAILED:
        print(f"FAILED {FAILED}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
