#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Txt2img workflow: SD 1.5 / SDXL / Krea 2, quality prefix, hires fix."""

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

KREA2_PRESETS = [
    {"id": "square", "label": "Kvadrat", "width": 1024, "height": 1024},
    {"id": "portrait", "label": "Portret", "width": 832, "height": 1216},
    {"id": "landscape", "label": "Pejzaž", "width": 1216, "height": 832},
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


def classify_loras(names: list[str] | None, metadata_fn=None) -> list[dict]:
    """Popis korisničkih LoRA-a (bez interne Turbo datoteke) s arhitekturom i grupom."""
    out: list[dict] = []
    for name in names or []:
        if not name or is_turbo_lora_file(name):
            continue
        meta: dict = {}
        arch = detect_lora_arch(name)
        if arch == "unknown":
            if callable(metadata_fn):
                try:
                    meta = metadata_fn(name) or {}
                except Exception:
                    meta = {}
            if not meta:
                folder = loras_dir()
                meta = read_safetensors_metadata(folder / Path(str(name).replace("\\", "/")).name)
            if meta:
                arch = detect_lora_arch(name, meta)
        group = "SDXL" if arch == "sdxl" else ("SD 1.5" if arch == "sd15" else "Ostalo")
        out.append({"name": name, "arch": arch, "group": group})
    return out


def loras_for_arch(entries: list[dict] | None, model_arch: str) -> list[dict]:
    """LoRA-e kompatibilne s modelom; 'unknown' (Ostalo) ide uz svaki SD model. Krea 2: prazno."""
    arch = (model_arch or "").strip().lower()
    if arch in {"krea2", "krea", "krea_2"}:
        return []
    out: list[dict] = []
    for item in entries or []:
        a = (item.get("arch") or "unknown").strip().lower()
        if a in {"unknown", "", "ostalo"} or a == arch:
            out.append(item)
    return out


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


def default_cfg(arch: str) -> float:
    if arch == "krea2":
        return float(KREA2_TURBO["cfg"])
    return 5.0 if arch == "sdxl" else 5.5


def default_sampler(arch: str) -> tuple[str, str]:
    if arch == "krea2":
        return KREA2_TURBO["sampler_name"], KREA2_TURBO["scheduler"]
    return "dpmpp_2m", "karras"


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
) -> dict:
    """
    Složi pozitivni prompt tako da CLIP vidi scenu.

    Poredak: (adult woman) + opis/scena, zatim izgled s profila, zatim quality tagovi.
    CLIP/SD 1.5 i prvi CLIP SDXL-a imaju ~77 tokena po komadu; višak ide u sljedeći
    chunk (ConditioningConcat) umjesto da scena padne iza dugog opisa izgleda.
    """
    scene = (scene or "").strip()
    appearance = sanitize_appearance(appearance or "", drop_conflicts=bool(scene))
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
            chunks.append(appearance)
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
    wf["9"] = {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "studio_krea2", "images": ["8", 0]},
    }
    return wf


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
    lora_ids = ("12", "22", "23", "24")
    prev_model: list = ["4", 0]
    prev_clip: list = ["4", 1]
    for i, (lora_name, strength) in enumerate(stack):
        nid = lora_ids[i] if i < len(lora_ids) else str(20 + i)
        wf[nid] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": prev_model,
                "clip": prev_clip,
                "lora_name": lora_name,
                "strength_model": float(strength),
                "strength_clip": float(strength),
            },
        }
        prev_model = [nid, 0]
        prev_clip = [nid, 1]
    if stack:
        model_ref = prev_model
        clip_ref = prev_clip
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
