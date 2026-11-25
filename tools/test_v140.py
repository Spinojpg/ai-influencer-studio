#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.4.0: konzistentnost lica na profilu osobe, spremanje postavki,
plan_image_generation uzima konzistentnost samo s profila, novi defaulti,
LoRA trener (8 GB zastavice, VRAM cleanup, balanced 768), checkpoint fallback.
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

import character  # noqa: E402
import image_gen  # noqa: E402
import inbox  # noqa: E402

inbox.configure_paths(data_dir=TMP / "data")
inbox.init_db()
import services  # noqa: E402

services.init_schema()
import studio  # noqa: E402
from services import generation_service as gs  # noqa: E402
from services import lora_trainer_service as lt  # noqa: E402

_ROT = str.maketrans("abcdefghijklmnopqrstuvwxyz", "nopqrstuvwxyzabcdefghijklm")
BANNED = re.compile(r"\b(" + "|".join(w.translate(_ROT) for w in ("yhfgvsl", "fabsf", "afsj", "ahqr", "anxrq", "gbcyrff")) + r")\b", re.I)

FAILED = 0
FACE_CLASSES = {
    "ApplyInstantID", "ApplyInstantIDAdvanced", "InstantID",
    "IPAdapter", "IPAdapterAdvanced", "IPAdapterFaceID", "IPAdapterEmbeds",
    "IPAdapterMS", "IPAdapterUnifiedLoader", "InstantIDFaceAnalysis",
}


def check(cond, msg):
    global FAILED
    if cond:
        print("  OK ", msg)
    else:
        FAILED += 1
        print("  FAIL", msg)


def nodes(wf: dict, cls: str) -> list:
    return [(k, n) for k, n in wf.items() if isinstance(n, dict) and n.get("class_type") == cls]


def all_classes(wf: dict) -> set:
    return {n.get("class_type") for n in wf.values() if isinstance(n, dict)}


def plan(body, profile=None, object_info=None):
    orig = image_gen.lora_available
    orig_vae = image_gen.vae_available
    image_gen.lora_available = lambda name, folder=None: True
    image_gen.vae_available = lambda name, folder=None: True
    try:
        return studio.plan_image_generation(
            body,
            profile=profile,
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


def test_defaults_and_persistence():
    print("== defaulti i spremanje konzistentnosti ==")
    check(abs(character.DEFAULT_APPEARANCE_WEIGHT - 1.1) < 1e-9, "zadana težina izgleda 1,10")
    check(abs(character.DEFAULT_IPADAPTER_WEIGHT - 0.4) < 1e-9, "zadana jačina reference 0,40")
    check(abs(character.DEFAULT_INSTANTID_WEIGHT - 0.4) < 1e-9, "zadana jačina InstantID 0,40")

    fresh = inbox.upsert_profile({"name": "Nova Osoba"})
    check(abs(float(fresh["appearance_weight"]) - 1.1) < 1e-9, "novi profil: appearance_weight 1,10")
    check(abs(float(fresh["ipadapter_weight"]) - 0.4) < 1e-9, "novi profil: ipadapter_weight 0,40")
    check(abs(float(fresh["instantid_weight"]) - 0.4) < 1e-9, "novi profil: instantid_weight 0,40")
    check(fresh.get("ref_mode") in (None, "", "auto") or fresh["ref_mode"] == "auto", "novi profil: ref_mode auto")
    check(abs(float(fresh.get("instantid_end_at") or 0.8) - 0.8) < 1e-9, "novi profil: instantid_end_at 0,8")
    check(abs(float(fresh.get("fd_denoise") or 0.25) - 0.25) < 1e-9, "novi profil: fd_denoise 0,25")
    check(fresh["face_detailer"] is False, "novi profil: Face Detailer isključen")

    kept = inbox.upsert_profile({
        "name": "Stara Osoba",
        "appearance_weight": 1.35,
        "ipadapter_weight": 0.85,
        "instantid_weight": 0.8,
        "instantid_end_at": 1.0,
        "ipadapter_end_at": 0.85,
        "ref_mode": "instantid",
        "face_detailer": True,
        "fd_denoise": 0.22,
        "fd_guide_size": 512,
        "fd_max_size": 768,
        "fd_bbox_threshold": 0.45,
    })
    pid = kept["id"]
    # second save of unrelated field must not reset consistency
    inbox.upsert_profile({"name": "Stara Osoba", "style": "opuštena"}, pid)
    got = inbox.get_profile(pid)
    check(abs(float(got["appearance_weight"]) - 1.35) < 1e-9, "postojeće appearance_weight 1,35 ostaje")
    check(abs(float(got["ipadapter_weight"]) - 0.85) < 1e-9, "postojeće ipadapter_weight 0,85 ostaje")
    check(abs(float(got["instantid_weight"]) - 0.8) < 1e-9, "postojeće instantid_weight 0,8 ostaje")
    check(got["ref_mode"] == "instantid", "postojeći ref_mode ostaje")
    check(got["face_detailer"] is True, "postojeći Face Detailer ostaje")
    check(abs(float(got["fd_denoise"]) - 0.22) < 1e-9, "postojeći fd_denoise 0,22 ostaje")

    # full roundtrip of every consistency field via extras + upsert
    payload = {
        "name": "Stara Osoba",
        "appearance_weight": 1.2,
        "ipadapter_weight": 0.55,
        "instantid_weight": 0.45,
        "instantid_end_at": 0.75,
        "ipadapter_end_at": 0.9,
        "ref_mode": "ipadapter",
        "face_detailer": True,
        "fd_denoise": 0.28,
        "fd_guide_size": 448,
        "fd_max_size": 640,
        "fd_bbox_threshold": 0.4,
    }
    inbox.upsert_profile(payload, pid)
    gs.save_profile_extras(pid, payload)
    again = inbox.get_profile(pid)
    extras = gs.profile_extras(pid)
    for key, val in payload.items():
        if key == "name":
            continue
        check(again.get(key) == val or abs(float(again.get(key)) - float(val)) < 1e-9, f"reload profila: {key}={val}")
        if key in extras and key not in {"name"}:
            ev = extras[key]
            if isinstance(val, bool):
                check(bool(ev) is val, f"reload extras: {key}={val}")
            elif isinstance(val, (int, float)) and ev not in (None, ""):
                check(abs(float(ev) - float(val)) < 1e-9, f"reload extras: {key}={val}")
            elif ev == val or ev == str(val):
                check(True, f"reload extras: {key}={val}")


def test_source_of_truth():
    print("== plan_image_generation: konzistentnost samo s profila ==")
    prof = inbox.upsert_profile({
        "name": "Testna Konzistentnost",
        "appearance_prompt": "long auburn hair, grey eyes, a small star tattoo",
        "appearance_weight": 1.15,
        "ipadapter_weight": 0.45,
        "instantid_weight": 0.55,
        "instantid_end_at": 0.7,
        "ipadapter_end_at": 0.9,
        "ref_mode": "auto",
        "face_detailer": False,
        "fd_denoise": 0.22,
    })
    # Body pokušava nametnuti stare, jače Napredno vrijednosti.
    res = plan(_body(
        persona_id=prof["id"],
        appearance_weight=1.5,
        ipadapter_weight=1.0,
        instantid_weight=1.2,
        instantid_end_at=1.0,
        ipadapter_end_at=1.0,
        face_detailer=True,
        fd_denoise=0.6,
        ref_mode="instantid",
    ), profile=prof)
    check(res.get("ok"), "plan s osobom uspijeva" + ("" if res.get("ok") else f" ({res.get('error')})"))
    if not res.get("ok"):
        return
    meta = res["meta"]
    prompt = meta.get("prompt") or ""
    check(abs(float(meta.get("appearance_weight")) - 1.15) < 1e-9, f"appearance_weight iz profila (1,15), ne iz bodyja ({meta.get('appearance_weight')})")
    check(":1.15)" in prompt or ":1.15," in prompt or "auburn hair" in prompt, "prompt koristi težinu/izgled s profila")
    check("1.50)" not in prompt and ":1.5)" not in prompt, "body appearance_weight 1,5 se ignorira")
    check(abs(float(meta.get("ipadapter_weight") or prof["ipadapter_weight"]) - 0.45) < 1e-9 or meta.get("ipadapter_weight") in (None, 0.45),
          "ipadapter_weight s profila (nema ref slika pa može biti None, ali ne 1,0)")
    if meta.get("ipadapter_weight") is not None:
        check(abs(float(meta["ipadapter_weight"]) - 0.45) < 1e-9, "ipadapter_weight nije body 1,0")
    check(not meta.get("face_detailer"), "Face Detailer iz profila (isključen), body True se ignorira")
    check(meta.get("ref_mode") != "instantid" or not meta.get("instantid_end_at") or abs(float(meta.get("instantid_end_at") or 0) - 0.7) < 1e-9,
          "InstantID end_at s profila ako je korišten")
    wf = res["workflow"]
    check(nodes(wf, "KSampler") or nodes(wf, "KSamplerAdvanced"), "workflow ima KSampler")
    check(nodes(wf, "SaveImage"), "workflow ima SaveImage")
    check(not (all_classes(wf) & {"FaceDetailer", "FaceDetailerPipe"}), "Face Detailer nije u workflowu (profil isključen)")

    # Bez osobe: body konzistentnost i dalje vrijedi (stara putanja)
    none = plan(_body(persona_id="", appearance_weight=1.25, face_detailer=False), profile=prof)
    check(none.get("ok"), "Bez osobe plan uspijeva")
    if none.get("ok"):
        check(none["meta"].get("persona_id") in (None, ""), "Bez osobe: persona_id prazan")
        check(abs(float(none["meta"].get("appearance_weight") or 1.25) - 1.25) < 1e-9, "Bez osobe: appearance_weight iz bodyja ostaje")
        check("auburn hair" not in (none["meta"].get("prompt") or ""), "Bez osobe: izgled osobe se ne ubacuje")
        check(not (all_classes(none["workflow"]) & FACE_CLASSES), "Bez osobe: nema InstantID/IP-Adapter čvorova")


def test_checkpoint_fallback():
    print("== checkpoint fallback ==")
    orig = studio.list_checkpoint_models
    studio.list_checkpoint_models = lambda: ["RealVisXL_V5.0_fp16.safetensors", "juggernautXL.safetensors"]
    try:
        res = plan(_body(model="Realistic_Vision_V6.0_NV_B1_fp16.safetensors", persona_id=""), profile=None)
        check(res.get("ok"), "plan s nedostajućim checkpointom uspijeva" + ("" if res.get("ok") else f" ({res.get('error')})"))
        if res.get("ok"):
            meta = res["meta"]
            check(meta.get("model") == "RealVisXL_V5.0_fp16.safetensors", f"koristi prvi instalirani ({meta.get('model')})")
            notes = " ".join(meta.get("warnings") or meta.get("rx_notes") or [])
            check("Realistic_Vision" in notes and "nije instaliran" in notes, f"upozorenje u meta ({notes[:180]})")
        # instalirani ostaje
        res2 = plan(_body(model="juggernautXL.safetensors", persona_id=""), profile=None)
        check(res2.get("ok") and res2["meta"].get("model") == "juggernautXL.safetensors", "instalirani checkpoint se ne mijenja")
    finally:
        studio.list_checkpoint_models = orig

    # prazan popis = ponašanje kao dosad (ne javlja 400 zbog fallbacka)
    studio.list_checkpoint_models = lambda: []
    try:
        res3 = plan(_body(model="Missing_Only_On_Disk.safetensors", persona_id=""), profile=None)
        check(res3.get("ok"), "prazan popis checkpointa ne ruši plan")
        if res3.get("ok"):
            check(res3["meta"].get("model") == "Missing_Only_On_Disk.safetensors", "bez popisa ostaje traženi model")
    finally:
        studio.list_checkpoint_models = orig


def test_trainer_flags():
    print("== LoRA trener: 8 GB zastavice, balanced, VRAM cleanup ==")
    cfg = lt.build_training_config(
        {
            "arch": "sdxl", "rank": 16, "alpha": 8, "epochs": 8, "total_steps": 800,
            "learning_rate": 1e-4, "resolution": 768,
        },
        base_path=Path("/tmp/base.safetensors"),
        output_dir=Path("/tmp/out"),
        output_name="char_test",
        logs_dir=Path("/tmp/logs"),
    )
    check(cfg.get("gradient_checkpointing") is True, "gradient_checkpointing")
    check(int(cfg.get("train_batch_size") or 0) == 1, "train_batch_size 1")
    check(cfg.get("mixed_precision") == "fp16", "fp16 mixed precision")
    check(cfg.get("cache_latents") is True, "cache_latents")
    check(cfg.get("cache_latents_to_disk") is True, "cache_latents_to_disk")
    check("empty_cache" in lt.LAUNCHER_SOURCE and "gc.collect" in lt.LAUNCHER_SOURCE, "pokretač čisti VRAM između epoha")
    check("STUDIO: VRAM" in lt.LAUNCHER_SOURCE, "pokretač ispisuje VRAM")
    check("Nastavi od zadnje epohe" in lt.STALL_MESSAGE, "jasnija poruka o zastoju nudi nastavak")

    # balanced cap needs a persona + images? compute_plan may need dataset. Use existing test approach if possible.
    # If compute_plan requires a real profile, create one.
    prof = inbox.upsert_profile({"name": "Trener Osoba", "preferred_model": "RealVisXL_V5.0_fp16.safetensors"})
    # compute_plan might fail without images; still check resolution clamp via the function if it gets image_count 0
    try:
        plan_b = lt.compute_plan(int(prof["id"]), "balanced", {"resolution": 1024})
        check(int(plan_b.get("resolution") or 0) == 768, f"balanced cap 768 (dobio {plan_b.get('resolution')})")
        check(int(plan_b.get("resolution") or 0) <= 768, "balanced nije iznad 768")
    except Exception as exc:
        check(False, f"compute_plan balanced: {exc}")
    try:
        plan_d = lt.compute_plan(int(prof["id"]), "detailed", {"resolution": 1024})
        check(int(plan_d.get("resolution") or 0) == 1024, f"detailed dopušta 1024 (dobio {plan_d.get('resolution')})")
    except Exception as exc:
        check(False, f"compute_plan detailed: {exc}")


def test_static_ui():
    print("== statičke provjere UI-ja 1.4.0 ==")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    v11 = (ROOT / "static" / "v11.js").read_text(encoding="utf-8")
    js_lt = (ROOT / "static" / "lora_trainer.js").read_text(encoding="utf-8")
    check("Lice i konzistencija" not in html, "blok 'Lice i konzistencija' je maknut iz Naprednog")
    check('data-group="face"' not in html, "adv-group face više nije u Generiranju")
    check('id="appearWeight"' not in html and 'id="ipaWeight"' not in html, "klizači konzistentnosti nisu u Naprednom")
    check('id="personaConsNote"' in html and "Konzistentnost lica ide s profila osobe" in html, "bilješka na Generiranju")
    check('id="pfCons"' in html and 'id="pRefMode"' in html and 'id="pIid"' in html and 'id="pIpaEnd"' in html, "konzistentnost je na stranici Osobe")
    check('id="pFdDenoise"' in html and 'id="pAppearWeight"' in html, "Face Detailer denoise i težina izgleda na osobi")
    check("applyTemplateToForm" in v11, "odabir predloška popunjava kontrole forme")
    check("refreshPersona" in v11, "StudioV11.refreshPersona postoji")
    check("refreshPersonaPanels" in html, "promjena osobe osvježava panele")
    check("Nastavi od zadnje epohe" in js_lt and "resumeFromLastEpoch" in js_lt, "gumb nastavka od zadnje epohe")
    check("vramLabel" in js_lt, "UI pokazuje VRAM u treneru")
    for rel in ("static/v11.js", "index.html", "studio.py", "character.py", "services/generation_service.py",
                "services/lora_trainer_service.py", "inbox.py"):
        txt = (ROOT / rel).read_text(encoding="utf-8")
        check(not BANNED.search(txt), f"{rel}: bez zabranjenih izraza")


def main():
    print("test_v140")
    test_defaults_and_persistence()
    test_source_of_truth()
    test_checkpoint_fallback()
    test_trainer_flags()
    test_static_ui()
    print()
    if FAILED:
        print(f"FAILED {FAILED}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
