#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Txt2img workflow: SD 1.5 / SDXL / Krea 2, quality prefix, hires fix."""

from __future__ import annotations

import re
from pathlib import Path

from comfy_launch import COMFY_LORA_SUFFIXES, list_files, list_files_recursive, loras_dir

QUALITY_PREFIX = "RAW photo, best quality, highly detailed skin"
DEFAULT_NEGATIVE = (
    "(worst quality, low quality:1.4), deformed, bad anatomy, bad hands, "
    "extra fingers, blurry, cartoon, child, teen"
)
# 1.3.0: "prirodna fotografija" (manje plastičnog AI izgleda). Koristi se samo uz RX 6600 profile kvalitete
# i samo kad korisnik nije sam upisao negativni prompt (njegov tekst se nikad ne mijenja ni ne filtrira).
NATURAL_QUALITY = "candid photo, natural skin texture, visible pores, soft natural light, subtle film grain, 35mm photograph"
NATURAL_NEGATIVE = (
    DEFAULT_NEGATIVE + ", plastic skin, airbrushed, overly smooth skin, waxy skin, doll-like, cgi, 3d render, "
    "oversaturated, overexposed, hdr"
)

SD15_PRESETS = [
    {"id": "portrait", "label": "Portret", "width": 512, "height": 768},
    {"id": "square", "label": "Kvadrat", "width": 512, "height": 512},
    {"id": "landscape", "label": "Pejzaž", "width": 768, "height": 512},
    {"id": "ig_portrait", "label": "IG Portret 4:5", "width": 512, "height": 640, "output_width": 1080, "output_height": 1350},
    {"id": "ig_square", "label": "IG Kvadrat 1:1", "width": 512, "height": 512, "output_width": 1080, "output_height": 1080},
    {"id": "ig_story", "label": "IG Story/Reels 9:16", "width": 432, "height": 768, "output_width": 1080, "output_height": 1920},
]
SDXL_PRESETS = [
    {"id": "portrait", "label": "Portret", "width": 768, "height": 1152},
    {"id": "portrait_hd", "label": "Portret HD", "width": 832, "height": 1216},
    {"id": "square", "label": "Kvadrat", "width": 1024, "height": 1024},
    {"id": "landscape", "label": "Pejzaž", "width": 1216, "height": 832},
    {"id": "ig_portrait", "label": "IG Portret 4:5", "width": 896, "height": 1120, "output_width": 1080, "output_height": 1350},
    {"id": "ig_square", "label": "IG Kvadrat 1:1", "width": 1024, "height": 1024, "output_width": 1080, "output_height": 1080},
    {"id": "ig_story", "label": "IG Story/Reels 9:16", "width": 768, "height": 1368, "output_width": 1080, "output_height": 1920},
]

KREA2_PRESETS = [
    {"id": "square", "label": "Kvadrat", "width": 1024, "height": 1024},
    {"id": "portrait", "label": "Portret", "width": 832, "height": 1216},
    {"id": "landscape", "label": "Pejzaž", "width": 1216, "height": 832},
    {"id": "ig_portrait", "label": "IG Portret 4:5", "width": 896, "height": 1120, "output_width": 1080, "output_height": 1350},
    {"id": "ig_square", "label": "IG Kvadrat 1:1", "width": 1024, "height": 1024, "output_width": 1080, "output_height": 1080},
    {"id": "ig_story", "label": "IG Story/Reels 9:16", "width": 768, "height": 1368, "output_width": 1080, "output_height": 1920},
]
KREA2_TURBO = {
    "steps": 8,
    "cfg": 1.0,
    "sampler_name": "euler",
    "scheduler": "simple",
    "note": "Krea 2 Turbo: 8 koraka, cfg 1, euler + simple. Bez Hyper-SDXL LoRA i bez hires fixa.",
}
KREA2_UNET = "krea2_turbo_fp8_scaled.safetensors"
KREA2_CLIP = "qwen3vl_4b_fp8_scaled.safetensors"
KREA2_VAE = "qwen_image_vae.safetensors"
KREA2_CLIP_TYPE = "krea2"
# Službeni ComfyUI predložak (image_krea2_turbo_t2i) koristi EmptyLatentImage 1024×1024,
# ne EmptySD3LatentImage ni EmptyHunyuanLatent — iako model interno koristi Wan21 latent format.
KREA2_LATENT_NODE = "EmptyLatentImage"


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


def lora_key(name: str) -> str:
    """Usporedivi ključ LoRA imena: / umjesto \\, mala slova."""
    return (name or "").strip().replace("\\", "/").strip("/").lower()


def _lora_path(folder: Path, name: str) -> Path:
    parts = [p for p in (name or "").replace("\\", "/").split("/") if p and p not in (".", "..")]
    return Path(folder).joinpath(*parts) if parts else Path(folder)


def lora_available(name: str, folder: Path | None = None) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    folder = Path(folder) if folder is not None else loras_dir()
    if _lora_path(folder, name).is_file():
        return True
    key = lora_key(name)
    return any(lora_key(n) == key for n in list_files_recursive(folder))


def list_loras() -> list[str]:
    """Sve LoRA datoteke u models/loras, uključujući podmape (isti izvor kao kartica Modeli)."""
    return list_files_recursive(loras_dir())


def merge_lora_names(comfy_names: list[str] | None, fs_names: list[str] | None) -> list[str]:
    """Spoji popis iz ComfyUI-ja i s diska; za iste datoteke zadrži ComfyUI zapis imena."""
    merged: dict[str, str] = {}
    for name in comfy_names or []:
        if name and lora_key(name) not in merged:
            merged[lora_key(name)] = str(name)
    for name in fs_names or []:
        if name and lora_key(name) not in merged:
            merged[lora_key(name)] = str(name)
    return sorted(merged.values(), key=lambda n: lora_key(n))


def is_turbo_lora_file(name: str) -> bool:
    """Interna Hyper-SDXL Turbo LoRA — ne ide u korisnički izbornik."""
    base = (name or "").replace("\\", "/").split("/")[-1].strip().lower()
    return bool(base) and base == TURBO_SDXL["lora_filename"].lower()


def read_safetensors_metadata(path: Path | str) -> dict:
    """Pročitaj __metadata__ iz zaglavlja safetensors datoteke (bez učitavanja težina)."""
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        with p.open("rb") as fh:
            header_len = int.from_bytes(fh.read(8), "little")
            if header_len <= 2 or header_len > 16 * 1024 * 1024:
                return {}
            raw = fh.read(header_len)
        import json as _json
        header = _json.loads(raw.decode("utf-8"))
        meta = header.get("__metadata__") if isinstance(header, dict) else None
        return dict(meta) if isinstance(meta, dict) else {}
    except Exception:
        return {}


def detect_lora_arch(name: str, metadata: dict | None = None) -> str:
    """Vrati 'sdxl', 'sd15' ili 'unknown' iz imena i/ili safetensors metapodataka."""
    texts: list[str] = []
    meta = metadata if isinstance(metadata, dict) else {}
    for key in (
        "ss_base_model_version",
        "ss_sd_model_name",
        "ss_base_model_name",
        "modelspec.architecture",
        "modelspec.title",
        "ss_network_module",
    ):
        val = meta.get(key)
        if val:
            texts.append(str(val))
    nested = meta.get("modelspec")
    if isinstance(nested, dict):
        for val in nested.values():
            if val:
                texts.append(str(val))
    blob = " ".join(texts).lower()
    if blob:
        if any(s in blob for s in ("sdxl", "stable-diffusion-xl", "sd_xl", "sd-xl", "pony")):
            return "sdxl"
        if any(s in blob for s in ("flux", "sd3", "stable-diffusion-3", "hunyuan", "wan21", "krea")):
            return "unknown"
        if re.search(r"sd[\s_-]*v?2|stable-diffusion-v2", blob):
            return "unknown"
        if (
            re.search(r"sd[\s_-]*v?1([._-]?5)?", blob)
            or "stable-diffusion-v1" in blob
            or "sd_v1" in blob
        ):
            return "sd15"

    n = re.sub(r"[^a-z0-9]+", "_", (name or "").replace("\\", "/").split("/")[-1].lower()).strip("_")
    if "sdxl" in n or "sd_xl" in n or "hypersdxl" in n or "hyper_sdxl" in n:
        return "sdxl"
    if re.search(r"(^|_)xl(\d*)($|_)", n):
        return "sdxl"
    if re.search(r"sd[_\-]?1[_\-]?5", n) or "sd15" in n or re.search(r"(^|_)1[_\-]?5($|_)", n):
        return "sd15"
    return "unknown"


def classify_loras(names: list[str] | None, metadata_fn=None, comfy_names: list[str] | None = None) -> list[dict]:
    """Popis korisničkih LoRA-a (bez interne Turbo datoteke) s arhitekturom i grupom.

    Ništa se ne skriva: nepoznata ili možda nekompatibilna arhitektura samo mijenja grupu.
    """
    out: list[dict] = []
    comfy_keys = {lora_key(n) for n in (comfy_names or [])}
    seen: set[str] = set()
    for name in names or []:
        if not name or is_turbo_lora_file(name):
            continue
        key = lora_key(name)
        if key in seen:
            continue
        seen.add(key)
        meta: dict = {}
        arch = detect_lora_arch(name)
        if arch == "unknown":
            if callable(metadata_fn):
                try:
                    meta = metadata_fn(name) or {}
                except Exception:
                    meta = {}
            if not meta:
                meta = read_safetensors_metadata(_lora_path(loras_dir(), str(name)))
            if meta:
                arch = detect_lora_arch(name, meta)
        group = "SDXL" if arch == "sdxl" else ("SD 1.5" if arch == "sd15" else "Ostalo")
        suffix = Path(str(name)).suffix.lower()
        out.append({
            "name": name,
            "arch": arch,
            "group": group,
            "supported": suffix in COMFY_LORA_SUFFIXES,
            "in_comfy": (key in comfy_keys) if comfy_names is not None else None,
        })
    return out


def loras_for_arch(entries: list[dict] | None, model_arch: str) -> list[dict]:
    """Sve korisničke LoRA-e za model: prvo kompatibilne, zatim Ostalo / možda nekompatibilno.

    Ništa se ne skriva (1.0.19). Krea 2 nema LoRA izbornik.
    """
    arch = (model_arch or "").strip().lower()
    if arch in {"krea2", "krea", "krea_2"}:
        return []
    first: list[dict] = []
    rest: list[dict] = []
    for item in entries or []:
        a = (item.get("arch") or "unknown").strip().lower()
        row = dict(item)
        row["compatible"] = bool(a == arch and item.get("supported", True) is not False)
        (first if row["compatible"] else rest).append(row)
    return first + rest


def detect_model_arch(name: str, override: str = "") -> str:
    """Vrati 'sdxl' ili 'sd15'. Realistic Vision ostaje SD 1.5 (ne 'realvis')."""
    o = (override or "").strip().lower().replace(" ", "")
    o = o.replace("1.5", "15")
    if o in {"krea2", "krea", "krea_2"}:
        return "krea2"
    if o in {"sdxl", "xl"}:
        return "sdxl"
    if o in {"sd15", "sd1.5", "15", "sd1", "sd14"}:
        return "sd15"
    n = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    if "krea2" in n or n.startswith("krea_2"):
        return "krea2"
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



_MODEL_JUNK = {
    "fp16", "fp32", "bf16", "fp8", "ema", "noema", "pruned", "bakedvae",
    "safetensors", "checkpoint", "byrundiffusion", "rundiffusion", "by",
    "nv", "b1",
}


def short_model_name(filename: str) -> str:
    """Kratko ime za prikaz (npr. RealVisXL V5, Juggernaut XL)."""
    raw = (filename or "").replace("\\", "/").split("/")[-1]
    stem = re.sub(r"\.(safetensors|ckpt|pt|pth|bin)$", "", raw, flags=re.I).strip()
    if not stem:
        return ""
    s = re.sub(r"(?i)realvisxl", "realvisxl", stem)
    s = re.sub(r"(?i)juggernaut[\s_\-]*xl", "juggernautxl", s)
    s = re.sub(r"(?i)realistic[\s_\-]*vision", "realisticvision", s)
    s = re.sub(r"[\s_\-]+", " ", s)
    lower = re.sub(r"\s+", " ", s).strip().lower()

    m = re.search(r"realvisxl\s*v?\s*(\d+(?:\.\d+)?)?", lower)
    if m:
        ver = (m.group(1) or "").removesuffix(".0")
        return "RealVisXL" + (f" V{ver}" if ver else "")

    if "krea2" in lower.replace(" ", "") or re.search(r"\bkrea\s*2\b", lower):
        return "Krea 2 Turbo"

    if "juggernaut" in lower:
        if "ragnarok" in lower or "xl" in lower.split() or "juggernautxl" in lower.replace(" ", ""):
            return "Juggernaut XL"
        if re.search(r"\bxiii\b", lower):
            return "Juggernaut XIII"
        if re.search(r"\bxi\b", lower):
            return "Juggernaut XI"
        if re.search(r"\bx\b", lower) or re.search(r"\bv\s*10\b", lower):
            return "Juggernaut X"
        return "Juggernaut XL"

    m = re.search(r"realisticvision\s*v?\s*(\d+(?:\.\d+)?)?", lower)
    if m:
        ver = (m.group(1) or "").removesuffix(".0")
        return "Realistic Vision" + (f" V{ver}" if ver else "")

    tokens = [tok for tok in lower.split() if tok not in _MODEL_JUNK]
    out = []
    for tok in tokens:
        if tok in {"sdxl", "sd", "xl", "vae"}:
            out.append(tok.upper())
        elif re.fullmatch(r"v\d+(?:\.\d+)?", tok):
            ver = tok[1:].removesuffix(".0")
            out.append("V" + ver)
        else:
            out.append(tok[:1].upper() + tok[1:])
    return " ".join(out) or stem


def presets_for(arch: str) -> list[dict]:
    if arch == "krea2":
        return list(KREA2_PRESETS)
    return list(SDXL_PRESETS if arch == "sdxl" else SD15_PRESETS)


def align_dim(value: int, *, lo: int = 256, hi: int = 2048, multiple: int = 8) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = lo
    n = n - (n % multiple)
    return max(lo, min(hi, n))


def _preset_by_id(arch: str, preset_id: str) -> dict | None:
    want = (preset_id or "").strip().lower()
    if not want:
        return None
    for pr in presets_for(arch):
        if (pr.get("id") or "").lower() == want:
            return dict(pr)
    return None


def resolve_canvas(
    arch: str,
    width,
    height,
    *,
    output_width=None,
    output_height=None,
    preset_id: str = "",
    dim_max: int | None = None,
) -> dict:
    """Odredi veličinu generiranja i (ako treba) izlaz za Instagram.

    IG formati se računaju na manjem, VRAM-sigurnom platnu (višekratnik 8),
    a zatim se slika povećava na točne IG piksele (1080×1350 / 1080×1080 / 1080×1920).
    Ako klijent pošalje već te IG dimenzije kao width/height, mapiraju se natrag
    na sigurno platno da se ne generira 1080×1920 izravno na 8 GB.
    """
    hi = 2048 if (arch or "") == "krea2" else 1536
    if dim_max is not None:
        hi = int(dim_max)
    presets = presets_for(arch)
    chosen = _preset_by_id(arch, preset_id)

    def _as_int(val):
        try:
            if val is None or val == "":
                return None
            return int(val)
        except (TypeError, ValueError):
            return None

    ow_in, oh_in = _as_int(output_width), _as_int(output_height)
    w_in, h_in = _as_int(width), _as_int(height)

    if chosen is None and ow_in and oh_in:
        for pr in presets:
            if pr.get("output_width") == ow_in and pr.get("output_height") == oh_in:
                chosen = dict(pr)
                break
    if chosen is None and w_in and h_in:
        # Točne IG dimenzije poslane kao width/height.
        for pr in presets:
            if pr.get("output_width") == w_in and pr.get("output_height") == h_in:
                chosen = dict(pr)
                break
        if chosen is None:
            for pr in presets:
                if pr.get("width") == w_in and pr.get("height") == h_in and pr.get("output_width"):
                    chosen = dict(pr)
                    break

    if chosen:
        gen_w = align_dim(chosen["width"], hi=hi)
        gen_h = align_dim(chosen["height"], hi=hi)
        out_w = int(chosen.get("output_width") or gen_w)
        out_h = int(chosen.get("output_height") or gen_h)
        if ow_in and oh_in:
            out_w, out_h = ow_in, oh_in
        return {
            "width": gen_w,
            "height": gen_h,
            "output_width": out_w,
            "output_height": out_h,
            "preset_id": chosen.get("id") or "",
            "label": chosen.get("label") or "",
            "upscale": (out_w, out_h) != (gen_w, gen_h),
        }

    defaults = presets[0]
    gen_w = align_dim(w_in if w_in is not None else defaults["width"], hi=hi)
    gen_h = align_dim(h_in if h_in is not None else defaults["height"], hi=hi)
    if ow_in and oh_in and (ow_in, oh_in) != (gen_w, gen_h):
        out_w = max(64, min(4096, ow_in))
        out_h = max(64, min(4096, oh_in))
        return {
            "width": gen_w,
            "height": gen_h,
            "output_width": out_w,
            "output_height": out_h,
            "preset_id": "",
            "label": "",
            "upscale": True,
        }
    return {
        "width": gen_w,
        "height": gen_h,
        "output_width": gen_w,
        "output_height": gen_h,
        "preset_id": "",
        "label": "",
        "upscale": False,
    }


def apply_output_scale(wf: dict, image_ref: list, output_width: int, output_height: int, node_id: str = "92") -> list:
    """ImageScale (lanczos) na točne izlazne piksele, inače vrati isti ref."""
    if not output_width or not output_height:
        return image_ref
    if image_ref is None:
        return image_ref
    wf[node_id] = {
        "class_type": "ImageScale",
        "inputs": {
            "image": image_ref,
            "upscale_method": "lanczos",
            "width": int(output_width),
            "height": int(output_height),
            "crop": "disabled",
        },
    }
    return [node_id, 0]


def default_cfg(arch: str) -> float:
    if arch == "krea2":
        return float(KREA2_TURBO["cfg"])
    return 5.0 if arch == "sdxl" else 5.5


def default_sampler(arch: str) -> tuple[str, str]:
    if arch == "krea2":
        return KREA2_TURBO["sampler_name"], KREA2_TURBO["scheduler"]
    return "dpmpp_2m_sde", "karras"


def default_steps(arch: str) -> int:
    if arch == "krea2":
        return int(KREA2_TURBO["steps"])
    return 30


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
SCENE_WEIGHT = 1.3
_PORTRAIT_PREFIX_RE = re.compile(
    r"(?is)^(a\s+)?((photorealistic|realistic|beautiful|stunning|detailed|close[- ]up)\s+)*"
    r"portraits?(\s+photo)?(\s+of(\s+an?)?|\s+shot)?\s*[,:]?\s*"
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?|[^\s\w]", re.UNICODE)
# Generički studio/pozni tropi iz opisa izgleda koji preglasaju scenu (leži na krevetu, itd.).
_APPEARANCE_CONFLICT_RE = re.compile(
    r"(?i)(?:^|,)\s*(?:"
    r"looking(?:\s+directly)?\s+at\s+(?:the\s+)?camera|"
    r"looking\s+into\s+(?:the\s+)?camera|"
    r"staring\s+at\s+(?:the\s+)?camera|"
    r"facing\s+(?:the\s+)?camera|"
    r"smiling\s+at\s+(?:the\s+)?camera|"
    r"studio\s+(?:lighting|lights|portrait|photo|shot|background)|"
    r"softbox(?:\s+lighting)?|"
    r"headshot|(?:close[- ]up|closeup)\s+(?:portrait|face|shot|photo)|"
    r"professional\s+(?:studio\s+)?portrait|"
    r"standing\s+pose|"
    r"(?:clean|white|neutral|plain)\s+background"
    r")\s*(?=,|$)"
)
_EMBEDDED_PORTRAIT_RE = re.compile(
    r"(?is)(?:^|,)\s*(?:a\s+)?(?:(?:photorealistic|realistic|beautiful|stunning|detailed|close[- ]up)\s+)*"
    r"portraits?(?:\s+photo)?(?:\s+of(?:\s+an?)?|\s+shot)?\s*[,:]?\s*"
)


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


def emphasize_scene(scene: str, weight: float = SCENE_WEIGHT) -> str:
    """Stavi scenu u (tekst:1.3) da CLIP/model jače prati opis, osim ako već ima težinu."""
    scene = (scene or "").strip()
    if not scene:
        return ""
    if re.match(r"^\(.*:\s*[\d.]+\s*\)$", scene):
        return scene
    return f"({scene}:{weight:g})"


def sanitize_appearance(text: str, *, drop_conflicts: bool = True) -> str:
    """Makni 'portrait of' (i na početku i u sredini) i, uz scenu, studio/pozne trope."""
    t = strip_leading_portrait(text or "")
    if drop_conflicts and t:
        prev = None
        while prev != t:
            prev = t
            t = _EMBEDDED_PORTRAIT_RE.sub(",", t)
            t = _APPEARANCE_CONFLICT_RE.sub(",", t)
        t = re.sub(r"\s*,\s*", ", ", t)
        t = re.sub(r"(?:,\s*){2,}", ", ", t)
        t = re.sub(r"\s+", " ", t)
        t = t.strip(" ,")
    return t


VISUAL_APPEARANCE_FIELDS = (
    "appearance_prompt",
    "looks",
    "hair",
    "eyes",
    "body",
    "tattoos",
    "distinguishing_marks",
)


def appearance_from_profile(profile: dict | None, extra: str = "") -> str:
    """Sastavi izgled iz polja profila (što postoji) plus privremeni dodatak."""
    parts: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        text = sanitize_appearance(raw or "", drop_conflicts=False)
        if not text:
            return
        key = re.sub(r"\s+", " ", text).strip().lower()
        if not key or key in seen:
            return
        for prev in parts:
            if key in prev.lower():
                return
        seen.add(key)
        parts.append(text)

    if isinstance(profile, dict):
        for field in VISUAL_APPEARANCE_FIELDS:
            add(str(profile.get(field) or ""))
    add(extra or "")
    return ", ".join(parts)


def extract_adult_age(*texts: str) -> int | None:
    """Nađi eksplicitnu dob 21–99 (persone su uvijek odrasle)."""
    blob = " ".join(str(t) for t in texts if t)
    for match in re.finditer(r"\b(2[1-9]|[3-9]\d)\b", blob):
        return int(match.group(1))
    return None


def adult_term_for_profile(
    profile: dict | None,
    *,
    appearance: str = "",
    scene: str = "",
    adult_term: str = ADULT_TERM,
) -> str:
    """'adult woman' ili 'adult woman, 26' ako je dob jasno navedena."""
    texts = [appearance, scene]
    if isinstance(profile, dict):
        for key in ("age_vibe", "age", "appearance_prompt"):
            texts.append(str(profile.get(key) or ""))
    age = extract_adult_age(*texts)
    if age:
        return f"{adult_term}, {age}"
    return adult_term


def build_positive_prompt(
    *,
    scene: str,
    appearance: str = "",
    quality: bool = True,
    adult_term: str = ADULT_TERM,
    appearance_weight: float = 1.3,
    quality_text: str | None = None,
) -> dict:
    """
    Složi pozitivni prompt tako da CLIP vidi scenu.

    Poredak: (adult woman) + opis/scena, zatim izgled s profila, zatim quality tagovi.
    CLIP/SD 1.5 i prvi CLIP SDXL-a imaju ~77 tokena po komadu; višak ide u sljedeći
    chunk (ConditioningConcat) umjesto da scena padne iza dugog opisa izgleda.
    """
    scene = (scene or "").strip()
    appearance = sanitize_appearance(appearance or "", drop_conflicts=bool(scene))
    quality_text = ((quality_text or QUALITY_PREFIX) if quality else "").strip()

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

    # Prvi chunk ostaje samo adult + scena (naglašena), izgled ide u sljedeći
    # da ne potisne scenu unutar prvih 77 CLIP tokena.
    if scene and scene in head:
        head = head.replace(scene, emphasize_scene(scene), 1)

    chunks: list[str] = []
    if head:
        chunks.append(head)
    if appearance:
        low_head = head.lower()
        if appearance.lower() not in low_head:
            try:
                from character import emphasize_text, clamp_appearance_weight
                weighted = emphasize_text(appearance, clamp_appearance_weight(appearance_weight))
            except Exception:
                weighted = appearance
            chunks.append(weighted)
    if quality_text:
        # Kratki odjek scene na kraju da model ne "zaboravi" pozu kad izgled predug.
        if scene:
            chunks.append(f"{quality_text}, {scene}")
        else:
            chunks.append(quality_text)
    elif scene and (appearance or (used_adult and scene not in (used_adult or ""))):
        chunks.append(scene)

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
        "appearance_weight": appearance_weight,
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


def _object_info_catalog(object_info: dict | None) -> dict | None:
    if not isinstance(object_info, dict) or not object_info:
        return None
    known = (
        "CLIPTextEncode", "KSampler", "CheckpointLoaderSimple", "ConditioningConcat",
        "CLIPLoader", "UNETLoader", "VAELoader", "EmptyLatentImage",
        "ConditioningZeroOut", "VAEDecode", "SaveImage",
    )
    if any(k in object_info for k in known):
        return object_info
    data = object_info.get("data")
    if isinstance(data, dict) and data:
        return data
    # ComfyUI /object_info: vrijednosti imaju shemu "input"
    for v in object_info.values():
        if isinstance(v, dict) and isinstance(v.get("input"), dict):
            return object_info
    return None


def _should_concat(object_info: dict | None, parts: list[str]) -> bool:
    """ConditioningConcat je ugrađeni ComfyUI čvor.

    Koristi ga kad ima više komada, osim ako object_info izričito nabraja čvorove
    i među njima nema ConditioningConcat. Prazan/None object_info (cache još
    nije spreman) više ne spaja sve u jedan CLIPTextEncode — to je točno kako
    dug izgled s profila potisne scenu unutar prvih 77 tokena.
    """
    if len(parts) <= 1:
        return False
    catalog = _object_info_catalog(object_info)
    if catalog is None:
        return True
    return "ConditioningConcat" in catalog



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
    can_concat = _should_concat(object_info, parts)
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



def cliploader_types(object_info: dict | None) -> list[str]:
    """Popis CLIPLoader type vrijednosti iz /object_info (npr. krea2)."""
    catalog = _object_info_catalog(object_info)
    if not catalog:
        return []
    node = catalog.get("CLIPLoader") or {}
    if not isinstance(node, dict):
        return []
    required = ((node.get("input") or {}).get("required") or {})
    typ = required.get("type") or required.get("clip_type")
    opts: list = []
    if isinstance(typ, list) and typ:
        first = typ[0]
        opts = list(first) if isinstance(first, list) else list(typ)
    return [str(x) for x in opts if x is not None]


def cliploader_has_type(object_info: dict | None, wanted: str) -> bool | None:
    """True/False ako katalog ima CLIPLoader; None ako nema dovoljno podataka."""
    types = cliploader_types(object_info)
    catalog = _object_info_catalog(object_info)
    if not types:
        if catalog and "CLIPLoader" in catalog:
            return False
        return None
    want = (wanted or "").strip().lower()
    return any(str(t).strip().lower() == want for t in types)


def krea2_support_error(object_info: dict | None) -> str | None:
    """Hrvatska poruka ako CLIPLoader nema tip krea2 (stariji ComfyUI)."""
    ok = cliploader_has_type(object_info, KREA2_CLIP_TYPE)
    if ok is False:
        types = ", ".join(cliploader_types(object_info)[:12]) or "(prazan popis)"
        return (
            "Ova verzija ComfyUI-ja nema CLIPLoader tip 'krea2' "
            f"(dostupno: {types}). Ažuriraj ComfyUI na 0.45.0 ili noviji "
            "(Krea 2 podrška), zatim ponovo pokreni ComfyUI i Studio."
        )
    return None


def build_krea2_workflow(
    *,
    prompt: str,
    model: str,
    width: int,
    height: int,
    batch: int,
    seed: int,
    steps: int | None = None,
    cfg: float | None = None,
    sampler_name: str | None = None,
    scheduler: str | None = None,
    object_info: dict | None = None,
    clip_name: str | None = None,
    vae_name: str | None = None,
    weight_dtype: str = "default",
    output_width: int | None = None,
    output_height: int | None = None,
) -> dict:
    """Krea 2 Turbo: UNETLoader + CLIPLoader(type=krea2) + VAELoader, bez CheckpointLoaderSimple.

    Službeni Comfy-Org predložak koristi EmptyLatentImage (1024² zadano) i
    ConditioningZeroOut za negativ (cfg=1).
    """
    spec = KREA2_TURBO
    width = max(256, min(2048, int(width) - (int(width) % 8)))
    height = max(256, min(2048, int(height) - (int(height) % 8)))
    # Turbo checkpoint je destiliran na 8 koraka / cfg 1 / euler / simple.
    steps = int(spec["steps"])
    cfg = float(spec["cfg"])
    sampler_name = spec["sampler_name"]
    scheduler = spec["scheduler"]
    unet_name = (model or KREA2_UNET).replace("\\", "/").split("/")[-1]
    clip_name = (clip_name or KREA2_CLIP).replace("\\", "/").split("/")[-1]
    vae_name = (vae_name or KREA2_VAE).replace("\\", "/").split("/")[-1]

    clip_inputs: dict = {"clip_name": clip_name, "type": KREA2_CLIP_TYPE}
    # Treći widget u službenom predlošku je 'default' (device).
    catalog = _object_info_catalog(object_info) or {}
    clip_node = catalog.get("CLIPLoader") if isinstance(catalog, dict) else None
    clip_req = ((clip_node or {}).get("input") or {}).get("required") or {}
    clip_opt = ((clip_node or {}).get("input") or {}).get("optional") or {}
    if "device" in clip_req or "device" in clip_opt or not catalog:
        clip_inputs["device"] = "default"

    unet_inputs: dict = {"unet_name": unet_name}
    unet_node = catalog.get("UNETLoader") if isinstance(catalog, dict) else None
    unet_req = ((unet_node or {}).get("input") or {}).get("required") or {}
    if "weight_dtype" in unet_req or not catalog:
        unet_inputs["weight_dtype"] = weight_dtype or "default"

    wf: dict = {
        "10": {"class_type": "UNETLoader", "inputs": unet_inputs},
        "11": {"class_type": "CLIPLoader", "inputs": clip_inputs},
        "12": {"class_type": "VAELoader", "inputs": {"vae_name": vae_name}},
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt or "", "clip": ["11", 0]},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": int(batch)},
        },
    }
    # cfg=1: službeni predložak ide na ConditioningZeroOut; fallback je prazan negativni encode.
    if (not catalog) or _node_exists(object_info, "ConditioningZeroOut"):
        wf["13"] = {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["6", 0]}}
        neg_ref: list = ["13", 0]
    else:
        wf["7"] = {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "", "clip": ["11", 0]},
        }
        neg_ref = ["7", 0]
    wf["3"] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": int(seed),
            "steps": int(steps),
            "cfg": float(cfg),
            "sampler_name": sampler_name,
            "scheduler": scheduler,
            "denoise": 1,
            "model": ["10", 0],
            "positive": ["6", 0],
            "negative": neg_ref,
            "latent_image": ["5", 0],
        },
    }
    wf["8"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["3", 0], "vae": ["12", 0]},
    }
    image_from = ["8", 0]
    if output_width and output_height and (int(output_width), int(output_height)) != (int(width), int(height)):
        image_from = apply_output_scale(wf, image_from, int(output_width), int(output_height))
    wf["9"] = {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "studio_krea2", "images": image_from},
    }
    return wf


LORA_NODE_IDS = ("12", "22", "23", "24", "25", "26", "27")
MAX_LORA_STACK = 5
# FreeU_V2 (core ComfyUI). SDXL vrijednosti preporučene za SDXL, SD 1.5 iz FreeU repozitorija.
FREEU_V2_SDXL = {"b1": 1.3, "b2": 1.4, "s1": 0.9, "s2": 0.2}
FREEU_V2_SD15 = {"b1": 1.5, "b2": 1.6, "s1": 0.9, "s2": 0.2}
INSTANTID_NODES = ("InstantIDModelLoader", "InstantIDFaceAnalysis", "ApplyInstantID")
INSTANTID_MODEL = "ip-adapter.bin"
INSTANTID_CONTROLNET = "instantid/diffusion_pytorch_model.safetensors"


def normalize_lora_stack(loras) -> list[tuple[str, float, float]]:
    """[{name, strength_model, strength_clip, enabled}] -> [(name, sm, sc)] (najviše 5, bez duplikata)."""
    out: list[tuple[str, float, float]] = []
    seen: set[str] = set()
    for item in loras or []:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("lora_name") or "").strip()
        if not name or name in seen or is_turbo_lora_file(name):
            continue
        en = item.get("enabled", True)
        if en in (False, 0, "0", "false", "off"):
            continue
        def _f(v, d):
            try:
                return max(-2.0, min(2.0, float(v)))
            except (TypeError, ValueError):
                return d
        sm = _f(item.get("strength_model", item.get("strength", 0.8)), 0.8)
        sc = _f(item.get("strength_clip", item.get("strength", sm)), sm)
        seen.add(name)
        out.append((name, sm, sc))
        if len(out) >= MAX_LORA_STACK:
            break
    return out


def _input_names(object_info: dict | None, class_type: str) -> set[str] | None:
    cat = _object_info_catalog(object_info) or {}
    node = cat.get(class_type) if isinstance(cat, dict) else None
    if not isinstance(node, dict):
        return None
    inp = node.get("input") or {}
    names = set((inp.get("required") or {}).keys()) | set((inp.get("optional") or {}).keys())
    return names or None


def vae_decode_tiled_node(samples: list, vae: list, *, tile_size: int = 512, object_info: dict | None = None) -> dict:
    """VAEDecodeTiled za 8 GB VRAM-a. Novi ComfyUI traži i overlap/temporal_*, stari samo tile_size."""
    tile = max(256, min(1024, int(tile_size or 512)))
    tile -= tile % 64
    inputs = {"samples": samples, "vae": vae, "tile_size": tile, "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}
    names = _input_names(object_info, "VAEDecodeTiled")
    if names:
        inputs = {k: v for k, v in inputs.items() if k in names or k in {"samples", "vae"}}
    return {"class_type": "VAEDecodeTiled", "inputs": inputs}


def _option_list(object_info: dict | None, class_type: str, field: str) -> list[str]:
    cat = _object_info_catalog(object_info) or {}
    node = cat.get(class_type) if isinstance(cat, dict) else None
    req = (((node or {}).get("input") or {}).get("required") or {}) if isinstance(node, dict) else {}
    typ = req.get(field)
    if isinstance(typ, list) and typ and isinstance(typ[0], list):
        return [str(x) for x in typ[0]]
    return []


def instantid_available(object_info: dict | None) -> bool:
    return all(_node_exists(object_info, n) for n in INSTANTID_NODES)


def apply_instantid(wf: dict, model_ref: list, pos_ref: list, neg_ref: list, image: str, *, weight: float = 0.8, object_info: dict | None = None):
    """cubiq ComfyUI_InstantID: loader + FaceAnalysis (CPU, bez CUDA na AMD-u) + ControlNet + ApplyInstantID."""
    ids = _option_list(object_info, "InstantIDModelLoader", "instantid_file")
    model_file = next((x for x in ids if "ip-adapter" in x.lower() or "instantid" in x.lower()), ids[0] if ids else INSTANTID_MODEL)
    cns = _option_list(object_info, "ControlNetLoader", "control_net_name")
    cn_file = next((x for x in cns if "instantid" in x.lower().replace("\\", "/")), INSTANTID_CONTROLNET)
    providers = _option_list(object_info, "InstantIDFaceAnalysis", "provider")
    provider = "CPU" if (not providers or "CPU" in providers) else providers[0]
    w = max(0.0, min(1.5, float(weight if weight not in (None, "") else 0.8)))
    wf["40"] = {"class_type": "InstantIDModelLoader", "inputs": {"instantid_file": model_file}}
    wf["41"] = {"class_type": "InstantIDFaceAnalysis", "inputs": {"provider": provider}}
    wf["42"] = {"class_type": "ControlNetLoader", "inputs": {"control_net_name": cn_file}}
    wf["43"] = {"class_type": "LoadImage", "inputs": {"image": str(image).replace("\\", "/")}}
    wf["44"] = {
        "class_type": "ApplyInstantID",
        "inputs": {
            "instantid": ["40", 0],
            "insightface": ["41", 0],
            "control_net": ["42", 0],
            "image": ["43", 0],
            "model": model_ref,
            "positive": pos_ref,
            "negative": neg_ref,
            "weight": w,
            "start_at": 0.0,
            "end_at": 1.0,
        },
    }
    return ["44", 0], ["44", 1], ["44", 2]


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
    user_lora: str = "",
    user_lora_strength: float | None = None,
    ipadapter_images: list[str] | None = None,
    ipadapter_weight: float = 0.8,
    face_detailer: bool = False,
    output_width: int | None = None,
    output_height: int | None = None,
    loras: list | None = None,
    hires_scale: float | None = None,
    hires_denoise: float | None = None,
    hires_steps: int | None = None,
    freeu: bool = False,
    freeu_params: dict | None = None,
    vae_mode: str = "standard",
    vae_tile_size: int = 512,
    instantid_image: str = "",
    instantid_weight: float = 0.8,
    face_detailer_params: dict | None = None,
) -> dict:
    if (arch or "").lower() in {"krea2", "krea"} or detect_model_arch(model, arch) == "krea2":
        return build_krea2_workflow(
            prompt=prompt,
            model=model,
            width=width,
            height=height,
            batch=batch,
            seed=seed,
            steps=steps,
            cfg=cfg,
            sampler_name=sampler_name,
            scheduler=scheduler,
            object_info=object_info,
            output_width=output_width,
            output_height=output_height,
        )
    stack: list[tuple[str, float]] = []
    user = (user_lora or "").strip()
    legacy = (lora or "").strip()
    if user_lora_strength is None:
        u_strength = float(lora_strength) if (user or (legacy and not is_turbo_lora_file(legacy))) else 0.8
    else:
        u_strength = float(user_lora_strength)
    u_strength = max(0.0, min(1.5, u_strength))
    if not user and legacy and not is_turbo_lora_file(legacy):
        user = legacy
    # 1.1.0: višestruki LoRA stack (do 5), svaki s vlastitom jačinom za model i CLIP.
    multi = normalize_lora_stack(loras)
    multi_names = {m[0] for m in multi}
    if multi:
        for m in multi:
            stack.append(m)
        if user and user in multi_names:
            user = ""
    if turbo:
        spec = TURBO_SDXL
        steps = int(spec["steps"])
        cfg = float(spec["cfg"] if cfg is None else cfg)
        sampler_name = spec["sampler_name"]
        scheduler = spec["scheduler"]
        hires = False
        arch = "sdxl"
        if user and not is_turbo_lora_file(user):
            stack.append((user, u_strength))
        stack.append((spec["lora_filename"], float(spec["lora_strength"])))
    elif user:
        stack.append((user, u_strength))
    elif legacy:
        stack.append((legacy, max(0.0, min(1.5, float(lora_strength)))))
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
    lora_ids = LORA_NODE_IDS
    prev_model: list = ["4", 0]
    prev_clip: list = ["4", 1]
    for i, entry in enumerate(stack):
        if len(entry) == 3:
            lora_name, strength, strength_clip = entry
        else:
            lora_name, strength = entry
            strength_clip = strength
        nid = lora_ids[i] if i < len(lora_ids) else str(300 + i)
        wf[nid] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": prev_model,
                "clip": prev_clip,
                "lora_name": lora_name,
                "strength_model": float(strength),
                "strength_clip": float(strength_clip),
            },
        }
        prev_model = [nid, 0]
        prev_clip = [nid, 1]
    if stack:
        model_ref = prev_model
        clip_ref = prev_clip
    refs = [n for n in (ipadapter_images or []) if str(n).strip()]
    if refs:
        from character import apply_ipadapter_to_workflow
        model_ref = apply_ipadapter_to_workflow(
            wf,
            model_ref,
            refs,
            weight=ipadapter_weight,
            object_info=object_info,
        )
    if freeu and (not object_info or _node_exists(object_info, "FreeU_V2")):
        fp = dict(FREEU_V2_SDXL if arch == "sdxl" else FREEU_V2_SD15)
        fp.update({k: float(v) for k, v in (freeu_params or {}).items() if k in fp and v not in (None, "")})
        wf["30"] = {"class_type": "FreeU_V2", "inputs": {"model": model_ref, **fp}}
        model_ref = ["30", 0]
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
    neg_ref: list = ["7", 0]
    fd_pos_ref, fd_neg_ref = pos_ref, neg_ref
    if instantid_image and str(instantid_image).strip():
        model_ref, pos_ref, neg_ref = apply_instantid(
            wf, model_ref, pos_ref, neg_ref, str(instantid_image), weight=instantid_weight, object_info=object_info
        )
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
            "negative": neg_ref,
            "latent_image": ["5", 0],
        },
    }
    latent_from = ["3", 0]
    if hires:
        h_scale = 1.5 if hires_scale in (None, "") else max(1.1, min(2.0, float(hires_scale)))
        h_denoise = 0.4 if hires_denoise in (None, "") else max(0.1, min(0.8, float(hires_denoise)))
        if object_info is None or _node_exists(object_info, "LatentUpscaleBy"):
            wf["10"] = {
                "class_type": "LatentUpscaleBy",
                "inputs": {
                    "samples": ["3", 0],
                    "upscale_method": "bilinear",
                    "scale_by": h_scale,
                },
            }
        else:
            up_w = max(256, min(2048, int(width * h_scale) - (int(width * h_scale) % 8)))
            up_h = max(256, min(2048, int(height * h_scale) - (int(height * h_scale) % 8)))
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
                "steps": (max(8, int(steps) // 2 * 2 or int(steps)) if hires_steps in (None, "") else max(4, min(40, int(hires_steps)))),
                "cfg": float(cfg),
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": h_denoise,
                "model": model_ref,
                "positive": pos_ref,
                "negative": neg_ref,
                "latent_image": ["10", 0],
            },
        }
        latent_from = ["11", 0]
    if (vae_mode or "standard") in {"tiled", "cpu"} and (not object_info or _node_exists(object_info, "VAEDecodeTiled")):
        wf["8"] = vae_decode_tiled_node(latent_from, ["4", 2], tile_size=vae_tile_size, object_info=object_info)
    else:
        wf["8"] = {
            "class_type": "VAEDecode",
            "inputs": {"samples": latent_from, "vae": ["4", 2]},
        }
    image_from = ["8", 0]
    if face_detailer:
        from character import apply_face_detailer
        image_from = apply_face_detailer(
            wf,
            image_ref=["8", 0],
            model_ref=model_ref,
            clip_ref=clip_ref,
            vae_ref=["4", 2],
            positive_ref=fd_pos_ref,
            negative_ref=fd_neg_ref,
            seed=int(seed),
            steps=int(steps),
            cfg=float(cfg),
            sampler_name=sampler_name,
            scheduler=scheduler,
            object_info=object_info,
            params=face_detailer_params,
        )
    if output_width and output_height and (int(output_width), int(output_height)) != (int(width), int(height)):
        image_from = apply_output_scale(wf, image_from, int(output_width), int(output_height))
    wf["9"] = {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "studio", "images": image_from},
    }
    return wf
