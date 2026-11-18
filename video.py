#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Provjera ComfyUI čvorova i okvir za kratki video (AnimateDiff / SVD / native)."""

from __future__ import annotations

# Imena čvorova koja se javljaju u popularnim paketima. Točan skup ovisi o instalaciji.
ANIMATEDIFF_NODES = {
    "ADE_AnimateDiffLoaderGen1",
    "ADE_AnimateDiffLoaderV1Advanced",
    "ADE_LoadAnimateDiffModel",
    "ADE_AnimateDiffUniformContextOptions",
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


def classify_nodes(object_info: dict) -> dict:
    names = set()
    if isinstance(object_info, dict):
        names = set(object_info.keys())
    found_ad = sorted(names & ANIMATEDIFF_NODES)
    found_svd = sorted(names & SVD_NODES)
    found_vhs = sorted(names & VHS_NODES)
    found_native = sorted(names & NATIVE_NODES)
    # fuzzy fallback
    if not found_ad:
        found_ad = sorted(n for n in names if "animatediff" in n.lower() or n.startswith("ADE_"))
    if not found_svd:
        found_svd = sorted(n for n in names if "img2vid" in n.lower() or n.startswith("SVD_"))
    if not found_vhs:
        found_vhs = sorted(n for n in names if n.startswith("VHS_"))
    ready = bool(found_ad or found_svd or found_native)
    missing_hint = []
    if not found_ad and not found_svd and not found_native:
        missing_hint.append(
            "Nema prepoznatih video čvorova. Za SD 1.5 tipično treba "
            "ComfyUI-AnimateDiff-Evolved i ComfyUI-VideoHelperSuite, plus AnimateDiff model "
            "u models/animatediff_models (ili odgovarajućoj mapi)."
        )
    if found_ad and not found_vhs and "CreateVideo" not in found_native and "SaveVideo" not in found_native:
        missing_hint.append(
            "AnimateDiff izgleda dostupan, ali nema VHS_VideoCombine ni SaveVideo "
            "za spajanje sličica u klip. Instaliraj ComfyUI-VideoHelperSuite ili noviji ComfyUI s SaveVideo."
        )
    return {
        "ready": ready and not (
            found_ad and not found_vhs and "CreateVideo" not in names and "SaveVideo" not in names and not found_svd
        ),
        "animatediff": found_ad,
        "svd": found_svd,
        "vhs": found_vhs,
        "native": found_native,
        "message": " ".join(missing_hint),
        "notes_hr": (
            "Na RX 6600 (8 GB VRAM) realni su samo kratki, niske rezolucije klipovi "
            "(npr. 512×512, 8–16 sličica). Video zahtijeva dodatne custom nodeove i modele; "
            "bez njih Studio neće slati krivi workflow, nego će javiti što nedostaje."
        ),
    }


def recommend_settings(vram_hint_gb: int = 8) -> dict:
    if vram_hint_gb <= 8:
        return {
            "width": 512,
            "height": 512,
            "frames": 8,
            "steps": 16,
            "fps": 8,
            "note": "Preporuka za 8 GB: 512×512, 8 sličica, 16 koraka, 8 fps.",
        }
    return {
        "width": 512,
        "height": 768,
        "frames": 16,
        "steps": 20,
        "fps": 8,
        "note": "Više VRAM-a: možeš probati 16 sličica.",
    }


def build_video_workflow(caps: dict, *, prompt: str, negative: str, model: str,
                         width: int, height: int, frames: int, steps: int, seed: int) -> tuple[dict | None, str]:
    """Best-effort workflow. Vraća (workflow, error). Ako čvorovi nisu pouzdani, error."""
    ad = caps.get("animatediff") or []
    svd = caps.get("svd") or []
    vhs = caps.get("vhs") or []
    native = caps.get("native") or []

    if not ad and not svd and not native:
        return None, (
            "Nedostaju video čvorovi u ComfyUI-ju. Instaliraj npr. ComfyUI-AnimateDiff-Evolved "
            "i ComfyUI-VideoHelperSuite, preuzmi AnimateDiff model, pa ponovo pokreni ComfyUI. "
            "Detalji su u KRATKO_UPUTE.txt, odjeljak Video."
        )

    # Ne šaljemo nagađani AnimateDiff graf ako ne znamo točne inpute verzije paketa —
    # krivi inputi zbune korisnika više nego jasna poruka. Native SaveVideo+CreateVideo
    # od batcha slika je jedini relativno stabilan okvir, ali to NIJE pravi motion model.
    if ad:
        return None, (
            "Pronađeni su AnimateDiff čvorovi: "
            + ", ".join(ad[:8])
            + ". Studio zasad ne slaže automatski točan graf jer se ulazi razlikuju po verziji. "
            "Otvori ComfyUI, učitaj AnimateDiff workflow (512×512, 8 sličica na 8 GB), "
            "izvezi File → Export Workflow (API) i koristi ga tamo. "
            "Automatski video iz Studija bit će dodan kad se uskladi s tvojim paketom čvorova."
        )
    if svd:
        return None, (
            "Pronađeni su SVD / img2vid čvorovi: "
            + ", ".join(svd[:8])
            + ". Za img2vid treba SVD model i često VideoHelperSuite. "
            "Studio neće slati nepotpun graf. Složi workflow u ComfyUI-ju na niskoj rezoluciji (8 GB)."
        )
    if "CreateVideo" in native and "SaveVideo" in native:
        # Jednostavan batch txt2img -> CreateVideo (nije pravi motion, ali je funkcionalan okvir).
        frames = max(4, min(16, int(frames)))
        width = max(256, min(512, int(width) - int(width) % 8))
        height = max(256, min(512, int(height) - int(height) % 8))
        wf = {
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": model}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": width, "height": height, "batch_size": frames},
            },
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": int(seed),
                    "steps": int(steps),
                    "cfg": 5,
                    "sampler_name": "dpmpp_2m",
                    "scheduler": "karras",
                    "denoise": 1,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
            },
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "20": {
                "class_type": "CreateVideo",
                "inputs": {"images": ["8", 0], "fps": 8},
            },
            "21": {
                "class_type": "SaveVideo",
                "inputs": {"video": ["20", 0], "filename_prefix": "studio_vid"},
            },
        }
        return wf, (
            "Upozorenje: CreateVideo od batcha slika nije pravi motion model "
            "(sličice neće biti glatko animirane kao AnimateDiff). Na 8 GB ovo je samo pokus."
        )
    return None, caps.get("message") or "Video čvorovi nisu spremni."
