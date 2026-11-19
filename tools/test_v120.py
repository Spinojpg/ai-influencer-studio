#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.0.20: SDXL AnimateDiff motion modul i odabir prema arhitekturi."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILED = 0


def check(cond, msg):
    global FAILED
    if cond:
        print("  OK ", msg)
    else:
        FAILED += 1
        print("  FAIL", msg)


def test_catalog():
    print("== Katalog motion modula ==")
    import model_download
    import video as video_mod

    item = model_download.curated_by_id("mm-sdxl-v10-beta")
    check(item is not None, "mm-sdxl-v10-beta je u katalogu")
    check(item and item["filename"] == "mm_sdxl_v10_beta.ckpt", "filename mm_sdxl_v10_beta.ckpt")
    check(
        item and item["url"] == "https://huggingface.co/guoyww/animatediff/resolve/main/mm_sdxl_v10_beta.ckpt",
        "javni Hugging Face URL",
    )
    check(item and item.get("size_bytes") == 950143538, f"veličina 950143538 ({(item or {}).get('size_bytes')})")
    check(item and item.get("kind") == "animatediff" and item.get("arch") == "sdxl", "kind animatediff / arch sdxl")
    dest = model_download.dest_dir_for(item.get("kind") if item else "animatediff")
    check(dest.name == "animatediff_models", f"odredište {dest}")

    hs = model_download.curated_by_id("hsxl-temporal-f16")
    check(hs is not None and hs["filename"] == "hsxl_temporal_layers.f16.safetensors", "Hotshot-XL u katalogu")
    check(hs and hs.get("size_bytes") == 474694696, "Hotshot-XL veličina")

    sd15 = model_download.curated_by_id("mm-sd15-v2")
    check(sd15 and sd15["filename"] == "mm_sd_v15_v2.ckpt", "SD 1.5 modul i dalje u katalogu")
    check(video_mod.DOWNLOAD_ID_SDXL == "mm-sdxl-v10-beta", "download id")


def test_pick_motion():
    print("== Odabir motion modula ==")
    import video as video_mod

    names = ["mm_sd_v15_v2.ckpt", "mm_sdxl_v10_beta.ckpt", "hsxl_temporal_layers.f16.safetensors"]
    check(video_mod.pick_motion_model(names, "sd15") == "mm_sd_v15_v2.ckpt", "SD 1.5 -> v15_v2")
    check(video_mod.pick_motion_model(names, "sdxl") == "mm_sdxl_v10_beta.ckpt", "SDXL preferira mm_sdxl_v10_beta")
    only_hs = ["mm_sd_v15_v2.ckpt", "hsxl_temporal_layers.f16.safetensors"]
    check(video_mod.pick_motion_model(only_hs, "sdxl") == "hsxl_temporal_layers.f16.safetensors", "SDXL pad na Hotshot-XL")
    only_v15 = ["mm_sd_v15_v2.ckpt"]
    check(video_mod.pick_motion_model(only_v15, "sdxl") == "", "SDXL bez SDXL modula ne uzima v15")
    check(video_mod.pick_motion_model(names, "sdxl") != video_mod.pick_motion_model(names, "sd15"), "arhitekture se ne miješaju")
    check(video_mod.motion_arch("mm_sdxl_v10_beta.ckpt") == "sdxl", "motion_arch sdxl")
    check(video_mod.motion_arch("mm_sd_v15_v2.ckpt") == "sd15", "motion_arch sd15")

    rec15 = video_mod.recommend_settings(8)
    check(rec15["width"] == 512 and rec15["frames"] == 16 and rec15["fps"] == 8, f"sd15 default {rec15}")
    recxl = video_mod.recommend_settings(8, "sdxl")
    check(recxl["width"] <= 768 and recxl["height"] <= 768, f"sdxl rez {recxl['width']}x{recxl['height']}")
    check(recxl["frames"] <= 16, f"sdxl frames {recxl['frames']}")
    check("8 GB" in recxl["note"] or "8 GB" in recxl["note"].replace(" ", ""), f"sdxl note 8 GB: {recxl['note'][:80]}")


def _info():
    return {
        "ADE_AnimateDiffLoaderGen1": {"input": {"required": {
            "model": ["MODEL"],
            "model_name": [["mm_sd_v15_v2.ckpt", "mm_sdxl_v10_beta.ckpt"]],
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


def test_workflow_selection():
    print("== Workflow bira pravi modul ==")
    import video as video_mod

    info = _info()
    caps = video_mod.classify_nodes(info)
    caps["motion_models"] = ["mm_sd_v15_v2.ckpt", "mm_sdxl_v10_beta.ckpt"]
    caps["motion_by_arch"] = {
        "sd15": "mm_sd_v15_v2.ckpt",
        "sdxl": "mm_sdxl_v10_beta.ckpt",
    }
    caps["motion_model"] = "mm_sd_v15_v2.ckpt"

    wf15, note15 = video_mod.build_video_workflow(
        caps, prompt="soft movement", negative="blur",
        model="Realistic_Vision_V5.1_fp16-no-ema.safetensors",
        width=512, height=512, frames=16, steps=16, seed=3, fps=8,
        object_info=info,
    )
    check(wf15 is not None, f"sd15 wf {note15}")
    check(wf15 and wf15["12"]["inputs"]["model_name"] == "mm_sd_v15_v2.ckpt", "sd15 koristi v15 modul")
    check(wf15 and wf15["12"]["inputs"].get("beta_schedule") == "autoselect", "sd15 beta_schedule autoselect")

    wfx, notex = video_mod.build_video_workflow(
        caps, prompt="soft movement", negative="blur",
        model="RealVisXL_V5.0_fp16.safetensors",
        width=1024, height=1024, frames=24, steps=30, seed=3, fps=8,
        object_info=info, model_type="sdxl",
    )
    check(wfx is not None, f"sdxl wf {notex}")
    check(wfx and wfx["12"]["inputs"]["model_name"] == "mm_sdxl_v10_beta.ckpt", "sdxl koristi sdxl modul")
    check(wfx and wfx["12"]["inputs"].get("beta_schedule") == "autoselect", "sdxl beta_schedule autoselect")
    check(wfx and wfx["5"]["inputs"]["width"] <= 768 and wfx["5"]["inputs"]["height"] <= 768, "sdxl rez omeđena za 8 GB")
    check(wfx and wfx["5"]["inputs"]["batch_size"] <= 16, f"sdxl frames omeđeni {wfx['5']['inputs']['batch_size'] if wfx else None}")
    check(wfx and "8 GB" in (notex or ""), f"sdxl note spominje 8 GB: {notex}")

    # Krivo proslijeđen SD 1.5 modul uz SDXL checkpoint se zanemaruje
    wfx2, _ = video_mod.build_video_workflow(
        caps, prompt="x", negative="n",
        model="juggernautXL_ragnarok.safetensors",
        width=512, height=512, frames=12, steps=12, seed=1,
        motion_model="mm_sd_v15_v2.ckpt",
        object_info=info,
    )
    check(wfx2 and wfx2["12"]["inputs"]["model_name"] == "mm_sdxl_v10_beta.ckpt", "ignorira krivi v15 modul uz SDXL")

    caps_only15 = dict(caps)
    caps_only15["motion_models"] = ["mm_sd_v15_v2.ckpt"]
    caps_only15["motion_by_arch"] = {"sd15": "mm_sd_v15_v2.ckpt", "sdxl": ""}
    caps_only15["motion_model"] = "mm_sd_v15_v2.ckpt"
    bad, err = video_mod.build_video_workflow(
        caps_only15, prompt="x", negative="n",
        model="RealVisXL_V5.0_fp16.safetensors",
        width=512, height=512, frames=12, steps=12, seed=1,
        object_info=info,
    )
    check(bad is None, "bez sdxl modula nema workflowa")
    check(err and "mm_sdxl_v10_beta" in err, f"poruka nudi preuzimanje: {err}")
    check("Preuzmi" in (err or "") or "Modeli" in (err or ""), "poruka usmjerava na preuzimanje")

    krea, kmsg = video_mod.build_video_workflow(
        caps, prompt="x", negative="n",
        model="krea2_turbo_fp8_scaled.safetensors",
        width=512, height=512, frames=8, steps=8, seed=1,
        object_info=info, model_type="krea2",
    )
    check(krea is None and "Krea 2" in (kmsg or ""), f"krea2 odbijen {kmsg}")

    check("mm_sdxl" in video_mod.missing_motion_message("sdxl"), "missing sdxl message")
    check(video_mod.download_id_for_arch("sdxl") == "mm-sdxl-v10-beta", "download_id sdxl")
    check(video_mod.download_id_for_arch("sd15") == "mm-sd15-v2", "download_id sd15")


def test_ui_and_api():
    print("== UI i API ==")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    py = (ROOT / "studio.py").read_text(encoding="utf-8")
    check('id="downloadMotion"' in html, "gumb Preuzmi motion modul")
    check("mm-sdxl-v10-beta" in html, "UI zna curated id")
    check("SDXL video je težak na 8 GB" in html, "upozorenje 8 GB u UI")
    check("updateVideoForArch" in html and "motion_by_arch" in html, "UI bira modul prema arhitekturi")
    check("need_motion" in py and "download_id" in py, "API vraća download_id kad modul nedostaje")
    check("detect_video_model_arch" in py, "API koristi video arch")
    # ne spominjemo zabranjene modele
    blob = html + py + (ROOT / "video.py").read_text(encoding="utf-8") + (ROOT / "model_download.py").read_text(encoding="utf-8")
    check("lustify" not in blob.lower() and "snofs" not in blob.lower(), "nema zabranjenih modela u kodu")


def main():
    test_catalog()
    test_pick_motion()
    test_workflow_selection()
    test_ui_and_api()
    print()
    if FAILED:
        print(f"FAILED {FAILED}")
        return 1
    print("Svi testovi 1.0.20 su prošli.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
