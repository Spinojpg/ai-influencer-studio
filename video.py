#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kratki lokalni video: AnimateDiff-Evolved + SD 1.5 (realno na RX 6600 8 GB)."""

from __future__ import annotations

import re
from pathlib import Path

from comfy_launch import (
    animatediff_models_dir,
    checkpoints_dir,
    list_files,
)
import image_gen

ANIMATEDIFF_NODES = {
    "ADE_AnimateDiffLoaderGen1",
    "ADE_LoadAnimateDiffModel",
    "ADE_ApplyAnimateDiffModelSimple",
    "ADE_ApplyAnimateDiffModel",
    "ADE_UseEvolvedSampling",
    "AnimateDiffLoader",
    "AnimateDiffModuleLoader",
    "AnimateDiffCombine",
}
SVD_NODES = {
    "SVD_img2vid_Conditioning",
    "ImageOnlyCheckpointLoader",
    "VideoLinearCFGGuidance",
}
VHS_NODES = {
    "VHS_VideoCombine",
    "VHS_LoadVideo",
}
NATIVE_NODES = {
    "CreateVideo",
    "SaveVideo",
}

MOTION_CANDIDATES = (
    "mm_sd_v15_v2.ckpt",
    "mm_sd_v15_v2.safetensors",
    "v3_sd15_mm.ckpt",
    "v3_sd15_mm.safetensors",
    "mm_sd_v15.ckpt",
)

REPOS = (
    {
        "id": "animatediff",
        "name": "ComfyUI-AnimateDiff-Evolved",
        "url": "https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved.git",
        "dir": "ComfyUI-AnimateDiff-Evolved",
    },
    {
        "id": "vhs",
        "name": "ComfyUI-VideoHelperSuite",
        "url": "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git",
        "dir": "ComfyUI-VideoHelperSuite",
    },
)

NOTES_HR = (
    "Na RX 6600 (8 GB, ZLUDA) realan je lokalni put AnimateDiff-Evolved uz SD 1.5 "
    "(npr. Realistic Vision) i motion modul mm_sd_v15_v2: 512×512, 16 sličica, 8 fps "
    "(oko 2 s). Na ovoj kartici to je obično 1–4 min po klipu. "
    "SVD-XT, LTX-Video i Wan2.1 1.3B nisu praktični na 8 GB (T5-XXL sam zauzme ~10 GB, "
    "ili je VRAM tijesan i spor s offloadom). AnimateDiff ne radi na SDXL; za video "
    "treba SD 1.5 model. Gumb „Instaliraj video podršku” skine čvorove i modele; "
    "zatim ponovo pokreni ComfyUI."
)


def _names(object_info: dict) -> set[str]:
    if not isinstance(object_info, dict):
        return set()
    data = object_info.get("data") if isinstance(object_info.get("data"), dict) else object_info
    return set(data.keys()) if isinstance(data, dict) else set()


def classify_nodes(object_info: dict) -> dict:
    names = _names(object_info)
    found_ad = sorted(names & ANIMATEDIFF_NODES)
    found_svd = sorted(names & SVD_NODES)
    found_vhs = sorted(names & VHS_NODES)
    found_native = sorted(names & NATIVE_NODES)
    if not found_ad:
        found_ad = sorted(n for n in names if "animatediff" in n.lower() or n.startswith("ADE_"))
    if not found_svd:
        found_svd = sorted(n for n in names if "img2vid" in n.lower() or n.startswith("SVD_"))
    if not found_vhs:
        found_vhs = sorted(n for n in names if n.startswith("VHS_"))
    ad_ok = bool(
        "ADE_AnimateDiffLoaderGen1" in names
        or (
            "ADE_LoadAnimateDiffModel" in names
            and "ADE_UseEvolvedSampling" in names
            and (
                "ADE_ApplyAnimateDiffModelSimple" in names
                or "ADE_ApplyAnimateDiffModel" in names
            )
        )
        or any("animatediff" in n.lower() for n in found_ad)
    )
    vhs_ok = "VHS_VideoCombine" in names or (
        "CreateVideo" in names and "SaveVideo" in names
    )
    motion = list_motion_models()
    missing = []
    if not ad_ok:
        missing.append(
            "Nema AnimateDiff-Evolved čvorova. Pritisni „Instaliraj video podršku” "
            "(git clone u C:\\ComfyUI-Zluda\\custom_nodes)."
        )
    elif not vhs_ok:
        missing.append(
            "AnimateDiff je tu, ali nema VHS_VideoCombine / SaveVideo za mp4. "
            "Instaliraj ComfyUI-VideoHelperSuite."
        )
    if ad_ok and not motion:
        missing.append(
            "Nema motion modula u models/animatediff_models (očekujem mm_sd_v15_v2.ckpt)."
        )
    ready = bool(ad_ok and vhs_ok and motion)
    return {
        "ready": ready,
        "animatediff": found_ad,
        "svd": found_svd,
        "vhs": found_vhs,
        "native": found_native,
        "ad_ok": ad_ok,
        "vhs_ok": vhs_ok,
        "motion_models": motion,
        "motion_model": pick_motion_model(motion),
        "sd15_models": list_sd15_models(),
        "message": " ".join(missing),
        "notes_hr": NOTES_HR,
        "path": "animatediff-sd15",
        "honest": (
            "LTX-Video / Wan2.1 / SVD-XT na 8 GB AMD nisu preporučeni — preveliki text encoder "
            "ili nestabilan VRAM na ZLUDA. AnimateDiff + SD 1.5 je najpouzdaniji lokalni put."
        ),
    }


def recommend_settings(vram_hint_gb: int = 8) -> dict:
    return {
        "width": 512,
        "height": 512,
        "frames": 16,
        "steps": 16,
        "fps": 8,
        "cfg": 7.0,
        "denoise": 0.7,
        "note": "Preporuka za 8 GB: 512×512, 16 sličica (2 s @ 8 fps), 16 koraka. 24 sličice (3 s) može zapeti na VRAM-u.",
    }


def list_motion_models() -> list[str]:
    names = list_files(animatediff_models_dir(), (".ckpt", ".safetensors", ".pt", ".pth"))
    # stari default: moduli i u custom_nodes/.../models
    extra = Path(animatediff_models_dir())
    return names


def pick_motion_model(names: list[str] | None = None) -> str:
    names = list(names if names is not None else list_motion_models())
    lower = {n.lower(): n for n in names}
    for cand in MOTION_CANDIDATES:
        if cand.lower() in lower:
            return lower[cand.lower()]
    for n in names:
        if "sd15" in n.lower() or "sd_v15" in n.lower() or "v15" in n.lower():
            return n
    return names[0] if names else ""


def list_sd15_models() -> list[str]:
    out = []
    for name in list_files(checkpoints_dir()):
        if image_gen.detect_model_arch(name) == "sd15":
            out.append(name)
    return out


def pick_sd15_model(preferred: str = "", available: list[str] | None = None) -> str:
    names = list(available if available is not None else list_sd15_models())
    if preferred and preferred in names:
        return preferred
    for n in names:
        if "realistic_vision" in n.lower() or "realisticvision" in n.lower():
            return n
    return names[0] if names else preferred


def node_spec(object_info: dict | None, class_type: str) -> dict:
    if not isinstance(object_info, dict):
        return {}
    data = object_info.get("data") if isinstance(object_info.get("data"), dict) else object_info
    node = (data or {}).get(class_type) or {}
    return node if isinstance(node, dict) else {}


def required_inputs(object_info: dict | None, class_type: str) -> dict:
    return ((node_spec(object_info, class_type).get("input") or {}).get("required") or {})


def default_for(spec) -> object | None:
    if isinstance(spec, list) and len(spec) > 1 and isinstance(spec[1], dict) and "default" in spec[1]:
        return spec[1]["default"]
    return None


def fill_required(object_info: dict | None, class_type: str, inputs: dict) -> dict:
    out = dict(inputs)
    for name, spec in required_inputs(object_info, class_type).items():
        if name in out:
            continue
        d = default_for(spec)
        if d is not None:
            out[name] = d
    return out


def pick_vhs_format(object_info: dict | None) -> tuple[str, str]:
    """Vrati (format, napomena). Preferiraj h264 mp4, inače gif."""
    spec = required_inputs(object_info, "VHS_VideoCombine").get("format")
    options = []
    if isinstance(spec, list) and spec and isinstance(spec[0], list):
        options = [str(x) for x in spec[0]]
    def find(*needles: str) -> str:
        for n in needles:
            for opt in options:
                if n in opt.lower():
                    return opt
        return ""
    mp4 = find("h264-mp4", "h264", "mpeg4", "mp4")
    if mp4:
        return mp4, ""
    gif = find("gif") or "image/gif"
    return gif, "ffmpeg / mp4 format nije dostupan — spremam GIF."


def _has(object_info: dict | None, class_type: str) -> bool:
    return class_type in _names(object_info or {})


def build_video_workflow(
    caps: dict,
    *,
    prompt: str,
    negative: str,
    model: str,
    width: int,
    height: int,
    frames: int,
    steps: int,
    seed: int,
    fps: int = 8,
    cfg: float | None = None,
    denoise: float = 1.0,
    init_image: str = "",
    motion_model: str = "",
    object_info: dict | None = None,
    prompt_chunks: list[str] | None = None,
) -> tuple[dict | None, str]:
    """Pravi AnimateDiff graf (Gen1, inače Gen2) + VHS_VideoCombine. (workflow, note/error)."""
    object_info = object_info or {}
    names = _names(object_info) or set(caps.get("animatediff") or []) | set(caps.get("vhs") or []) | set(caps.get("native") or [])
    # Ako je object_info prazan, vjeruj caps listama.
    def has(cls: str) -> bool:
        if names:
            return cls in names
        return _has(object_info, cls)

    ad_gen1 = has("ADE_AnimateDiffLoaderGen1")
    ad_gen2 = has("ADE_LoadAnimateDiffModel") and has("ADE_UseEvolvedSampling") and (
        has("ADE_ApplyAnimateDiffModelSimple") or has("ADE_ApplyAnimateDiffModel")
    )
    if not ad_gen1 and not ad_gen2:
        return None, caps.get("message") or (
            "Nedostaju AnimateDiff čvorovi. Pritisni „Instaliraj video podršku”, "
            "zatim ponovo pokreni ComfyUI."
        )

    motion = motion_model or caps.get("motion_model") or pick_motion_model(caps.get("motion_models"))
    if not motion:
        return None, (
            "Nema AnimateDiff motion modula (mm_sd_v15_v2). "
            "Pritisni „Instaliraj video podršku” da se preuzme u models/animatediff_models."
        )
    if image_gen.detect_model_arch(model) != "sd15":
        return None, (
            f"AnimateDiff na 8 GB radi sa SD 1.5, ne sa SDXL ({model}). "
            "Instaliraj Realistic Vision (gumb za video podršku to može skinuti) ili odaberi SD 1.5 model."
        )

    rec = recommend_settings(8)
    width = max(256, min(768, int(width) - int(width) % 8))
    height = max(256, min(768, int(height) - int(height) % 8))
    frames = max(8, min(24, int(frames)))
    steps = max(8, min(30, int(steps)))
    fps = max(4, min(16, int(fps)))
    cfg = float(rec["cfg"] if cfg is None else cfg)
    use_init = bool(init_image)
    if use_init:
        denoise = min(0.85, max(0.45, float(denoise if denoise < 1 else rec["denoise"])))
    else:
        denoise = 1.0

    wf: dict = {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": model}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
    }
    pos_ref = image_gen._encode_positive(wf, ["4", 1], prompt, prompt_chunks, object_info)

    # Motion on the base model
    if ad_gen1:
        wf["12"] = {
            "class_type": "ADE_AnimateDiffLoaderGen1",
            "inputs": fill_required(
                object_info,
                "ADE_AnimateDiffLoaderGen1",
                {"model": ["4", 0], "model_name": motion, "beta_schedule": "autoselect"},
            ),
        }
        model_ref: list = ["12", 0]
        note_path = "Gen1"
    else:
        wf["12"] = {
            "class_type": "ADE_LoadAnimateDiffModel",
            "inputs": fill_required(object_info, "ADE_LoadAnimateDiffModel", {"model_name": motion}),
        }
        apply_cls = "ADE_ApplyAnimateDiffModelSimple" if has("ADE_ApplyAnimateDiffModelSimple") else "ADE_ApplyAnimateDiffModel"
        apply_inputs = {"motion_model": ["12", 0]}
        if apply_cls == "ADE_ApplyAnimateDiffModel":
            apply_inputs["start_percent"] = 0.0
            apply_inputs["end_percent"] = 1.0
        wf["13"] = {"class_type": apply_cls, "inputs": fill_required(object_info, apply_cls, apply_inputs)}
        wf["14"] = {
            "class_type": "ADE_UseEvolvedSampling",
            "inputs": fill_required(
                object_info,
                "ADE_UseEvolvedSampling",
                {"model": ["4", 0], "beta_schedule": "autoselect", "m_models": ["13", 0]},
            ),
        }
        model_ref = ["14", 0]
        note_path = "Gen2"

    if use_init:
        wf["15"] = {"class_type": "LoadImage", "inputs": {"image": init_image}}
        if has("ImageScale") or not names:
            wf["16"] = {
                "class_type": "ImageScale",
                "inputs": {
                    "image": ["15", 0],
                    "upscale_method": "lanczos",
                    "width": width,
                    "height": height,
                    "crop": "center",
                },
            }
            img_ref: list = ["16", 0]
        else:
            img_ref = ["15", 0]
        wf["17"] = {"class_type": "VAEEncode", "inputs": {"pixels": img_ref, "vae": ["4", 2]}}
        wf["18"] = {"class_type": "RepeatLatentBatch", "inputs": {"samples": ["17", 0], "amount": frames}}
        latent_ref: list = ["18", 0]
    else:
        wf["5"] = {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": frames},
        }
        latent_ref = ["5", 0]

    wf["3"] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": int(seed),
            "steps": int(steps),
            "cfg": float(cfg),
            "sampler_name": "dpmpp_2m",
            "scheduler": "karras",
            "denoise": float(denoise),
            "model": model_ref,
            "positive": pos_ref,
            "negative": ["7", 0],
            "latent_image": latent_ref,
        },
    }
    wf["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}}

    note = (
        f"AnimateDiff {note_path}, {width}×{height}, {frames} sličica @ {fps} fps "
        f"({'img2vid, denoise '+str(denoise) if use_init else 'txt2vid'}). "
        "Na RX 6600 očekuj 1–4 min za 2 s klipa. Prvo paljenje može trajati dulje."
    )
    if has("VHS_VideoCombine") or (not names and caps.get("vhs")):
        fmt, fmt_note = pick_vhs_format(object_info) if names else ("video/h264-mp4", "")
        inputs = fill_required(
            object_info,
            "VHS_VideoCombine",
            {
                "images": ["8", 0],
                "frame_rate": fps,
                "loop_count": 0,
                "filename_prefix": "studio_vid",
                "format": fmt,
                "pingpong": False,
                "save_output": True,
            },
        )
        wf["21"] = {"class_type": "VHS_VideoCombine", "inputs": inputs}
        if fmt_note:
            note = note + " " + fmt_note
    elif has("CreateVideo") and has("SaveVideo"):
        wf["20"] = {"class_type": "CreateVideo", "inputs": fill_required(object_info, "CreateVideo", {"images": ["8", 0], "fps": fps})}
        wf["21"] = {"class_type": "SaveVideo", "inputs": fill_required(object_info, "SaveVideo", {"video": ["20", 0], "filename_prefix": "studio_vid"})}
        note = note + " VHS nije tu — koristim CreateVideo/SaveVideo."
    else:
        wf["9"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": "studio_vid", "images": ["8", 0]}}
        note = note + " Nema video combine čvora — spremam sličice. Instaliraj VideoHelperSuite za mp4."
    return wf, note
