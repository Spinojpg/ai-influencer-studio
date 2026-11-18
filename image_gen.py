#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Txt2img workflow: SD 1.5 / SDXL, quality prefix, hires fix."""

from __future__ import annotations

import re

QUALITY_PREFIX = "RAW photo, best quality, highly detailed skin"
DEFAULT_NEGATIVE = (
    "(worst quality, low quality:1.4), deformed, bad anatomy, bad hands, "
    "extra fingers, blurry, cartoon, child, teen"
)

SD15_PRESETS = [
    {"id": "portrait", "label": "Portret", "width": 512, "height": 768},
    {"id": "square", "label": "Kvadrat", "width": 512, "height": 512},
    {"id": "landscape", "label": "Pejzaž", "width": 768, "height": 512},
]
SDXL_PRESETS = [
    {"id": "portrait", "label": "Portret", "width": 768, "height": 1152},
    {"id": "portrait_hd", "label": "Portret HD", "width": 832, "height": 1216},
    {"id": "square", "label": "Kvadrat", "width": 1024, "height": 1024},
    {"id": "landscape", "label": "Pejzaž", "width": 1216, "height": 832},
]

LOWVRAM_NOTE = (
    "Na 8 GB VRAM-a (RX 6600) zadani SDXL portret je 768×1152 (832×1216 je Portret HD). "
    "Pokretač dodaje --use-split-cross-attention radi brzine. U postavkama možeš uključiti "
    "Low VRAM (--lowvram). SD 1.5 je i dalje sigurniji izbor; SDXL i hires fix mogu zapeti na memoriji. "
    "Hires fix je po zadanom samo za SD 1.5."
)


def detect_model_arch(name: str, override: str = "") -> str:
    """Vrati 'sdxl' ili 'sd15'. Realistic Vision ostaje SD 1.5 (ne 'realvis')."""
    o = (override or "").strip().lower().replace(" ", "")
    o = o.replace("1.5", "15")
    if o in {"sdxl", "xl"}:
        return "sdxl"
    if o in {"sd15", "sd1.5", "15", "sd1", "sd14"}:
        return "sd15"
    n = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    if "realistic_vision" in n or n.startswith("realisticvision"):
        return "sd15"
    if "sdxl" in n or "sd_xl" in n:
        return "sdxl"
    if "juggernaut" in n:
        return "sdxl"
    if "realvis" in n:
        return "sdxl"
    if re.search(r"(^|_)xl(\d*)($|_)", n):
        return "sdxl"
    return "sd15"


def presets_for(arch: str) -> list[dict]:
    return list(SDXL_PRESETS if arch == "sdxl" else SD15_PRESETS)


def default_cfg(arch: str) -> float:
    return 5.0 if arch == "sdxl" else 5.5


def apply_quality_prefix(prompt: str, enabled: bool = True) -> str:
    text = (prompt or "").strip()
    if not enabled or not text:
        return text
    if text.lower().startswith(QUALITY_PREFIX.lower()):
        return text
    return f"{QUALITY_PREFIX}, {text}"


def _node_exists(object_info: dict | None, class_type: str) -> bool:
    if not isinstance(object_info, dict):
        return False
    if class_type in object_info:
        return True
    # ponekad je odgovor umotan
    data = object_info.get("data") if isinstance(object_info.get("data"), dict) else None
    return bool(data and class_type in data)


def build_workflow(
    *,
    prompt: str,
    negative: str,
    model: str,
    width: int,
    height: int,
    batch: int,
    seed: int,
    steps: int,
    cfg: float | None = None,
    sampler_name: str = "dpmpp_2m",
    scheduler: str = "karras",
    arch: str = "sd15",
    hires: bool = False,
    object_info: dict | None = None,
) -> dict:
    if cfg is None:
        cfg = default_cfg(arch)
    width = max(256, min(1536, int(width) - (int(width) % 8)))
    height = max(256, min(1536, int(height) - (int(height) % 8)))
    wf: dict = {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": model},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {
                "width": width,
                "height": height,
                "batch_size": int(batch),
            },
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative, "clip": ["4", 1]},
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": int(seed),
                "steps": int(steps),
                "cfg": float(cfg),
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": 1,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
    }
    latent_from = ["3", 0]
    if hires:
        if object_info is None or _node_exists(object_info, "LatentUpscaleBy"):
            wf["10"] = {
                "class_type": "LatentUpscaleBy",
                "inputs": {
                    "samples": ["3", 0],
                    "upscale_method": "bilinear",
                    "scale_by": 1.5,
                },
            }
        else:
            up_w = max(256, min(2048, int(width * 1.5) - (int(width * 1.5) % 8)))
            up_h = max(256, min(2048, int(height * 1.5) - (int(height * 1.5) % 8)))
            wf["10"] = {
                "class_type": "LatentUpscale",
                "inputs": {
                    "samples": ["3", 0],
                    "upscale_method": "bilinear",
                    "width": up_w,
                    "height": up_h,
                    "crop": "disabled",
                },
            }
        wf["11"] = {
            "class_type": "KSampler",
            "inputs": {
                "seed": int(seed) + 1,
                "steps": max(8, int(steps) // 2 * 2 or int(steps)),
                "cfg": float(cfg),
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": 0.4,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["10", 0],
            },
        }
        latent_from = ["11", 0]
    # Face-detailer: samo ako su čvorovi stvarno tu; inače tiho preskoči.
    # Namjerno ne pogađamo složene ulaze Impact Packa.
    _ = object_info and _node_exists(object_info, "FaceDetailer")
    wf["8"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": latent_from, "vae": ["4", 2]},
    }
    wf["9"] = {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "studio", "images": ["8", 0]},
    }
    return wf
