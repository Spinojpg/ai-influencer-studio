#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Txt2img workflow: SD 1.5 / SDXL, quality prefix, hires fix."""

from __future__ import annotations

import re
from pathlib import Path

from comfy_launch import list_files, loras_dir

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


TURBO_SDXL = {
    "id": "hyper-sdxl-8step-cfg",
    "lora_filename": "Hyper-SDXL-8steps-CFG-lora.safetensors",
    "steps": 8,
    "cfg": 5.0,
    "sampler_name": "euler",
    "scheduler": "sgm_uniform",
    "lora_strength": 1.0,
    "note": "Hyper-SDXL 8-steps CFG LoRA: 8 koraka, cfg 5, euler, sgm_uniform. Na RX 6600 očekuj ~3,5–4× brže od 30 koraka (npr. ~8,5 min → ~2–2,5 min). Kvaliteta je malo mekša od punog 30-koraka prolaza.",
}


def lora_available(name: str, folder: Path | None = None) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    folder = Path(folder) if folder is not None else loras_dir()
    if (folder / name).is_file():
        return True
    return name in set(list_files(folder))


def list_loras() -> list[str]:
    return list_files(loras_dir())


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
    """Zadržano radi starih testova; novi poredak ide preko build_positive_prompt (kvaliteta na kraj)."""
    text = (prompt or "").strip()
    if not enabled or not text:
        return text
    if text.lower().startswith(QUALITY_PREFIX.lower()):
        return text
    return f"{QUALITY_PREFIX}, {text}"


CLIP_TOKEN_WARN = 75
ADULT_TERM = "adult woman"
_PORTRAIT_PREFIX_RE = re.compile(
    r"(?is)^(a\s+)?((photorealistic|realistic|beautiful|stunning|detailed|close[- ]up)\s+)*"
    r"portraits?(\s+photo)?(\s+of(\s+an?)?|\s+shot)?\s*[,:]?\s*"
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?|[^\s\w]", re.UNICODE)


def estimate_clip_tokens(text: str) -> int:
    """Gruba procjena CLIP tokena (riječi + interpunkcija; start/end nisu uračunati)."""
    if not (text or "").strip():
        return 0
    return len(_TOKEN_RE.findall(text))


def strip_leading_portrait(text: str) -> str:
    """Makni vodeći 'portrait of' / 'a photorealistic portrait of' da scena ne postane samo portret."""
    t = (text or "").strip().strip(",")
    for _ in range(4):
        nxt = _PORTRAIT_PREFIX_RE.sub("", t, count=1).strip(" ,")
        if nxt == t:
            break
        t = nxt
    return t


def has_adult_term(text: str) -> bool:
    return bool(re.search(r"(?i)\badult\b", text or ""))


def build_positive_prompt(
    *,
    scene: str,
    appearance: str = "",
    quality: bool = True,
    adult_term: str = ADULT_TERM,
) -> dict:
    """
    Složi pozitivni prompt tako da CLIP vidi scenu.

    Poredak: (adult woman) + opis/scena, zatim izgled s profila, zatim quality tagovi.
    CLIP/SD 1.5 i prvi CLIP SDXL-a imaju ~77 tokena po komadu; višak ide u sljedeći
    chunk (ConditioningConcat) umjesto da scena padne iza dugog opisa izgleda.
    """
    scene = (scene or "").strip()
    appearance = strip_leading_portrait(appearance or "")
    quality_text = QUALITY_PREFIX if quality else ""

    head_parts: list[str] = []
    used_adult = ""
    if adult_term and not has_adult_term(f"{scene} {appearance}"):
        used_adult = adult_term
        head_parts.append(adult_term)
    if scene:
        head_parts.append(scene)
    head = ", ".join(head_parts)

    if estimate_clip_tokens(head) > CLIP_TOKEN_WARN and scene:
        kept = [used_adult] if used_adult else []
        budget = CLIP_TOKEN_WARN - estimate_clip_tokens(used_adult) - (1 if used_adult else 0)
        words = scene.split()
        acc: list[str] = []
        for w in words:
            trial = " ".join(acc + [w])
            if estimate_clip_tokens(trial) > max(8, budget):
                break
            acc.append(w)
        if acc:
            kept.append(" ".join(acc))
        head = ", ".join(p for p in kept if p)

    chunks: list[str] = []
    if head:
        chunks.append(head)
    if appearance:
        low_head = head.lower()
        if appearance.lower() not in low_head:
            chunks.append(appearance)
    if quality_text:
        chunks.append(quality_text)

    full = ", ".join(chunks)
    tokens = estimate_clip_tokens(full)
    return {
        "prompt": full,
        "chunks": chunks,
        "tokens": tokens,
        "head_tokens": estimate_clip_tokens(head),
        "warn": tokens > CLIP_TOKEN_WARN,
        "limit": CLIP_TOKEN_WARN,
        "scene": scene,
        "appearance": appearance,
        "quality": quality_text,
        "adult_term": used_adult,
    }


def _node_exists(object_info: dict | None, class_type: str) -> bool:
    if not isinstance(object_info, dict):
        return False
    if class_type in object_info:
        return True
    # ponekad je odgovor umotan
    data = object_info.get("data") if isinstance(object_info.get("data"), dict) else None
    return bool(data and class_type in data)



def _encode_positive(
    wf: dict,
    clip_ref: list,
    prompt: str,
    chunks: list[str] | None,
    object_info: dict | None,
) -> list:
    """CLIPTextEncode; ako ima više komada i ConditioningConcat, spoji ih (scena ostaje prva)."""
    parts = [c.strip() for c in (chunks or []) if isinstance(c, str) and c.strip()]
    if not parts:
        parts = [(prompt or "").strip() or ""]
    can_concat = _node_exists(object_info, "ConditioningConcat") and len(parts) > 1
    if not can_concat:
        wf["6"] = {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": ", ".join(parts), "clip": clip_ref},
        }
        return ["6", 0]
    ids: list[str] = []
    for i, text in enumerate(parts):
        nid = "6" if i == 0 else str(60 + i)
        wf[nid] = {"class_type": "CLIPTextEncode", "inputs": {"text": text, "clip": clip_ref}}
        ids.append(nid)
    current: list = [ids[0], 0]
    for i, nid in enumerate(ids[1:], start=1):
        cid = str(70 + i)
        wf[cid] = {
            "class_type": "ConditioningConcat",
            "inputs": {"conditioning_to": current, "conditioning_from": [nid, 0]},
        }
        current = [cid, 0]
    return current


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
    lora: str = "",
    lora_strength: float = 1.0,
    turbo: bool = False,
    prompt_chunks: list[str] | None = None,
) -> dict:
    if turbo:
        spec = TURBO_SDXL
        lora = lora or spec["lora_filename"]
        lora_strength = float(spec["lora_strength"] if lora_strength == 1.0 else lora_strength)
        steps = int(spec["steps"])
        cfg = float(spec["cfg"] if cfg is None else cfg)
        sampler_name = spec["sampler_name"]
        scheduler = spec["scheduler"]
        hires = False
        arch = "sdxl"
    if cfg is None:
        cfg = default_cfg(arch)
    width = max(256, min(1536, int(width) - (int(width) % 8)))
    height = max(256, min(1536, int(height) - (int(height) % 8)))
    model_ref: list = ["4", 0]
    clip_ref: list = ["4", 1]
    wf: dict = {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": model},
        },
    }
    if lora:
        wf["12"] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["4", 0],
                "clip": ["4", 1],
                "lora_name": lora,
                "strength_model": float(lora_strength),
                "strength_clip": float(lora_strength),
            },
        }
        model_ref = ["12", 0]
        clip_ref = ["12", 1]
    wf["5"] = {
        "class_type": "EmptyLatentImage",
        "inputs": {
            "width": width,
            "height": height,
            "batch_size": int(batch),
        },
    }
    wf["7"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": negative, "clip": clip_ref},
    }
    pos_ref = _encode_positive(wf, clip_ref, prompt, prompt_chunks, object_info)
    wf["3"] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": int(seed),
            "steps": int(steps),
            "cfg": float(cfg),
            "sampler_name": sampler_name,
            "scheduler": scheduler,
            "denoise": 1,
            "model": model_ref,
            "positive": pos_ref,
            "negative": ["7", 0],
            "latent_image": ["5", 0],
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
                "model": model_ref,
                "positive": pos_ref,
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
