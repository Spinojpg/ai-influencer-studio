#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Preuzimanje checkpointa (paralelni Range ili jedna veza, stream + resume)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from comfy_launch import (
    animatediff_models_dir,
    checkpoints_dir,
    clip_vision_dir,
    diffusion_models_dir,
    ipadapter_dir,
    loras_dir,
    text_encoders_dir,
    ultralytics_bbox_dir,
    vae_dir,
)

# Provjereno curl -I (18. 11. 2026.): javni URL, 302 na CDN, HTTP 200,
# accept-ranges: bytes, Content-Length 6938065488, bez prijave.
# (SG161222/RealVisXL_V5.0_fp16 repo vraća 401; ovaj, iz RealVisXL_V5.0, radi.)
CURATED = [
    {
        "id": "realvisxl-v5-fp16",
        "name": "RealVisXL V5.0 (fp16)",
        "filename": "RealVisXL_V5.0_fp16.safetensors",
        "url": "https://huggingface.co/SG161222/RealVisXL_V5.0/resolve/main/RealVisXL_V5.0_fp16.safetensors",
        "arch": "sdxl",
        "kind": "checkpoint",
        "size_bytes": 6938065488,
        "note": "Fotorealistični SDXL s Hugging Facea, bez prijave. Oko 6,5 GB. Resume je podržan.",
    },
    {
        "id": "juggernaut-xl-ragnarok",
        "name": "Juggernaut XL Ragnarok (fp16)",
        "filename": "juggernautXL_ragnarok.safetensors",
        "url": "https://huggingface.co/Kandoo/Juggernaut-XL-Ragnarok/resolve/main/juggernautXL_ragnarok.safetensors",
        "arch": "sdxl",
        "kind": "checkpoint",
        "turbo_compatible": True,
        "size_bytes": 7105350162,
        "recommended": {
            "cfg": 5.0,
            "steps": 30,
            "sampler_name": "dpmpp_2m",
            "scheduler": "karras",
        },
        "note": "Svestrani fotorealistični SDXL (najnoviji Ragnarok, autor Kandoo / RunDiffusion) s Hugging Facea, bez prijave. Oko 6,6 GB. Preporuka: 30 koraka, cfg 5, dpmpp_2m karras. Radi i s Turbo LoRA (8 koraka).",
    },
    {
        "id": "krea2-turbo-fp8",
        "name": "Krea 2 Turbo (FP8)",
        "filename": "krea2_turbo_fp8_scaled.safetensors",
        "url": "https://huggingface.co/Comfy-Org/Krea-2/resolve/main/diffusion_models/krea2_turbo_fp8_scaled.safetensors",
        "arch": "krea2",
        "kind": "bundle",
        "turbo": True,
        "size_bytes": 18638004998,
        "files": [
            {
                "filename": "krea2_turbo_fp8_scaled.safetensors",
                "url": "https://huggingface.co/Comfy-Org/Krea-2/resolve/main/diffusion_models/krea2_turbo_fp8_scaled.safetensors",
                "kind": "diffusion",
                "size_bytes": 13141730784,
            },
            {
                "filename": "qwen3vl_4b_fp8_scaled.safetensors",
                "url": "https://huggingface.co/Comfy-Org/Krea-2/resolve/main/text_encoders/qwen3vl_4b_fp8_scaled.safetensors",
                "kind": "text_encoder",
                "size_bytes": 5242467968,
            },
            {
                "filename": "qwen_image_vae.safetensors",
                "url": "https://huggingface.co/Comfy-Org/Krea-2/resolve/main/vae/qwen_image_vae.safetensors",
                "kind": "vae",
                "size_bytes": 253806246,
            },
        ],
        "recommended": {
            "cfg": 1.0,
            "steps": 8,
            "sampler_name": "euler",
            "scheduler": "simple",
        },
        "note": "Službeni Comfy-Org paket: diffusion model (13,1 GB) + Qwen3-VL text encoder (5,24 GB) + Qwen Image VAE (254 MB). Ukupno oko 18,6 GB, javni Hugging Face URL, resume je podržan. Datoteke idu u models/diffusion_models, text_encoders i vae. Postavke: 8 koraka, cfg 1, euler/simple. Na RX 6600 (8 GB) vjerojatno nije izvedivo — fp8 se na RDNA2/ZLUDA često pretvara u fp16 (~26 GB samo za UNET).",
    },
    {
        "id": "hyper-sdxl-8step-cfg",
        "name": "Hyper-SDXL Turbo (8 koraka, CFG)",
        "filename": "Hyper-SDXL-8steps-CFG-lora.safetensors",
        "url": "https://huggingface.co/ByteDance/Hyper-SD/resolve/main/Hyper-SDXL-8steps-CFG-lora.safetensors",
        "arch": "sdxl",
        "kind": "lora",
        "turbo": True,
        "size_bytes": 787359648,
        "note": "LoRA za način Turbo: 8 koraka, cfg 5, euler + sgm_uniform. Na RX 6600 (~17 s/korak) slika padne s ~8–9 min na ~2–2,5 min. Radi uz RealVisXL i druge SDXL modele. Ne miješaj s hires fixom.",
    },
    {
        "id": "realistic-vision-v51",
        "name": "Realistic Vision V5.1 (fp16, SD 1.5)",
        "filename": "Realistic_Vision_V5.1_fp16-no-ema.safetensors",
        "url": "https://huggingface.co/SG161222/Realistic_Vision_V5.1_noVAE/resolve/main/Realistic_Vision_V5.1_fp16-no-ema.safetensors",
        "arch": "sd15",
        "kind": "checkpoint",
        "size_bytes": 2132625894,
        "note": "SD 1.5 checkpoint, preporučen za video na 8 GB (AnimateDiff uz mm_sd_v15_v2). Oko 2 GB. Koristi se i za slike 512×768.",
    },
    {
        "id": "ipadapter-plus-face",
        "name": "IP-Adapter Plus Face (konzistentno lice)",
        "filename": "ip-adapter-plus-face_sdxl_vit-h.safetensors",
        "url": "https://huggingface.co/h94/IP-Adapter/resolve/main/sdxl_models/ip-adapter-plus-face_sdxl_vit-h.safetensors",
        "arch": "sdxl",
        "kind": "bundle",
        "size_bytes": 3473974248,
        "files": [
            {
                "filename": "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
                "url": "https://huggingface.co/h94/IP-Adapter/resolve/main/models/image_encoder/model.safetensors",
                "kind": "clip_vision",
                "size_bytes": 2528373448,
            },
            {
                "filename": "ip-adapter-plus-face_sdxl_vit-h.safetensors",
                "url": "https://huggingface.co/h94/IP-Adapter/resolve/main/sdxl_models/ip-adapter-plus-face_sdxl_vit-h.safetensors",
                "kind": "ipadapter",
                "size_bytes": 847517512,
            },
            {
                "filename": "ip-adapter-plus-face_sd15.safetensors",
                "url": "https://huggingface.co/h94/IP-Adapter/resolve/main/models/ip-adapter-plus-face_sd15.safetensors",
                "kind": "ipadapter",
                "size_bytes": 98183288,
            },
        ],
        "note": "Paket za konzistentno lice (IP-Adapter Plus Face, bez InsightFace). CLIP Vision ViT-H (2,35 GB) ide u models/clip_vision, a Plus Face modeli za SDXL (808 MB) i SD 1.5 (94 MB) u models/ipadapter. Javni Hugging Face (h94/IP-Adapter), resume je podržan. Ukupno oko 3,2 GB. Radi uz SDXL i SD 1.5, ne uz Krea 2. Treba i čvor ComfyUI_IPAdapter_plus (gumb Instaliraj na ovoj kartici). Na RX 6600 preporučena jačina je 0,8.",
    },
    {
        "id": "face-yolov8m",
        "name": "Face Detailer (YOLOv8m lice)",
        "filename": "face_yolov8m.pt",
        "url": "https://huggingface.co/Bingsu/adetailer/resolve/main/face_yolov8m.pt",
        "arch": "sdxl",
        "kind": "ultralytics_bbox",
        "size_bytes": 52026019,
        "note": "Detektor lica za opcijski Face Detailer (Impact Pack). Oko 50 MB, ide u models/ultralytics/bbox. Na 8 GB VRAM-a ostaje isključen po zadanom. Treba i čvorove ComfyUI-Impact-Pack i Impact-Subpack.",
    },
    {
        "id": "mm-sd15-v2",
        "name": "AnimateDiff motion modul (SD 1.5 v2)",
        "filename": "mm_sd_v15_v2.ckpt",
        "url": "https://huggingface.co/guoyww/animatediff/resolve/main/mm_sd_v15_v2.ckpt",
        "arch": "sd15",
        "kind": "animatediff",
        "size_bytes": 1817888431,
        "note": "Motion modul za kratke SD 1.5 klipove (AnimateDiff-Evolved). Oko 1,7 GB, ide u models/animatediff_models.",
    },
    {
        "id": "mm-sdxl-v10-beta",
        "name": "AnimateDiff motion modul (SDXL v1.0 beta)",
        "filename": "mm_sdxl_v10_beta.ckpt",
        "url": "https://huggingface.co/guoyww/animatediff/resolve/main/mm_sdxl_v10_beta.ckpt",
        "arch": "sdxl",
        "kind": "animatediff",
        "size_bytes": 950143538,
        "note": "Motion modul za kratke SDXL klipove (guoyww AnimateDiff, mm_sdxl_v10_beta). Oko 906 MB, javni Hugging Face URL, resume je podržan. Ide u models/animatediff_models. Na RX 6600 (8 GB) je težak — Studio koristi 512×512 i manje sličica; out of memory je moguć.",
    },
    {
        "id": "hsxl-temporal-f16",
        "name": "Hotshot-XL temporal layers (SDXL, fp16)",
        "filename": "hsxl_temporal_layers.f16.safetensors",
        "url": "https://huggingface.co/hotshotco/Hotshot-XL/resolve/main/hsxl_temporal_layers.f16.safetensors",
        "arch": "sdxl",
        "kind": "animatediff",
        "size_bytes": 474694696,
        "note": "Zamjenski SDXL motion modul (Hotshot-XL). Oko 453 MB, ide u models/animatediff_models. Studio za SDXL prednost daje mm_sdxl_v10_beta; ovaj je manji rezervni izbor. Na 8 GB također može biti tijesan.",
    },    {
        "id": "lora-photorealistic-slider-xl",
        "name": "Photorealistic Slider SDXL (ostris)",
        "filename": "ostris_photorealistic_slider_xl.safetensors",
        "url": "https://huggingface.co/ostris/photorealistic-slider-sdxl-lora/resolve/main/sdxl_photorealistic_slider_v1-0.safetensors",
        "arch": "sdxl",
        "kind": "lora",
        "group": "Preporučene SDXL LoRA-e (realizam i detalji)",
        "category": "Realizam kože i fotografije",
        "recommended_weight": 0.6,
        "size_bytes": 24179004,
        "note": "Slider za fotorealizam (ostris, javni Hugging Face). Pozitivna jačina 0,4–0,8 daje prirodniju kožu i izgled prave fotografije; negativna ide prema ilustraciji. Oko 23 MB.",
    },
    {
        "id": "lora-extremely-detailed-xl",
        "name": "Extremely Detailed slider SDXL (ntc-ai)",
        "filename": "ntc_extremely_detailed_xl.safetensors",
        "url": "https://huggingface.co/ntc-ai/SDXL-LoRA-slider.extremely-detailed/resolve/main/extremely%20detailed.safetensors",
        "arch": "sdxl",
        "kind": "lora",
        "group": "Preporučene SDXL LoRA-e (realizam i detalji)",
        "category": "Detalji i tekstura kože",
        "recommended_weight": 0.5,
        "size_bytes": 8789076,
        "note": "Slider za fine detalje i teksturu (ntc-ai, MIT licenca). Preporučeno 0,3–0,8; uz Face Detailer pazi da ne pretjeraš. Oko 8 MB.",
    },
    {
        "id": "lora-cinematic-lighting-xl",
        "name": "Cinematic Lighting slider SDXL (ntc-ai)",
        "filename": "ntc_cinematic_lighting_xl.safetensors",
        "url": "https://huggingface.co/ntc-ai/SDXL-LoRA-slider.cinematic-lighting/resolve/main/cinematic%20lighting.safetensors",
        "arch": "sdxl",
        "kind": "lora",
        "group": "Preporučene SDXL LoRA-e (realizam i detalji)",
        "category": "Svjetlo",
        "recommended_weight": 0.6,
        "size_bytes": 8789076,
        "note": "Filmsko svjetlo i kontrast (ntc-ai, MIT licenca). Dobro za editorial i studio glamour; preporučeno 0,4–1,0. Oko 8 MB.",
    },
    {
        "id": "lora-offset-noise-xl",
        "name": "SDXL Offset Noise LoRA (Stability AI)",
        "filename": "sdxl_offset_example_lora_1.0.safetensors",
        "url": "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_offset_example-lora_1.0.safetensors",
        "arch": "sdxl",
        "kind": "lora",
        "group": "Preporučene SDXL LoRA-e (realizam i detalji)",
        "category": "Svjetlo i kontrast",
        "recommended_weight": 0.4,
        "size_bytes": 49553604,
        "note": "Službena Stability AI offset-noise LoRA (openrail++): dublje sjene i bogatiji kontrast. Preporučeno 0,3–0,6. Oko 47 MB.",
    },
    {
        "id": "lora-nice-hands-xl",
        "name": "Nice Hands slider SDXL (ntc-ai)",
        "filename": "ntc_nice_hands_xl.safetensors",
        "url": "https://huggingface.co/ntc-ai/SDXL-LoRA-slider.nice-hands/resolve/main/nice%20hands.safetensors",
        "arch": "sdxl",
        "kind": "lora",
        "group": "Preporučene SDXL LoRA-e (realizam i detalji)",
        "category": "Anatomija (ruke)",
        "recommended_weight": 0.6,
        "size_bytes": 8789076,
        "note": "Slider za urednije ruke i prste (ntc-ai, MIT licenca). Preporučeno 0,4–1,0. Oko 8 MB.",
    },
    {
        "id": "lora-detail-tweaker-xl",
        "name": "Detail Tweaker XL",
        "filename": "add_detail_xl.safetensors",
        "url": "https://huggingface.co/AiWise/Detail-Tweaker-XL_v1/resolve/main/add-detail-xl.safetensors",
        "arch": "sdxl",
        "kind": "lora",
        "group": "Preporučene SDXL LoRA-e (realizam i detalji)",
        "category": "Detalji i stabilnost lica",
        "recommended_weight": 0.5,
        "size_bytes": 228452344,
        "sha256": "0D9BD1B873A7863E128B4672E3E245838858F71469A3CEC58123C16C06F83BD7",
        "note": "Slider za detalje (Detail Tweaker XL v1.0, creativeml-openrail-m). Pozitivna jačina povećava detalje, negativna ih smanjuje. Preporuka: počni od 0,5–1,5 (autor predlaže 1,5 pa prilagodi; raspon do ±3). Oko 218 MB, s Hugging Facea, bez prijave.",
    },
    {
        "id": "lora-skin-realism-xl",
        "name": "Realistična koža (Skin Realism)",
        "filename": "skin_realism_xl.safetensors",
        "url": "https://civitai.com/api/download/models/340833?fileId=270833",
        "arch": "sdxl",
        "kind": "lora",
        "group": "Preporučene SDXL LoRA-e (realizam i detalji)",
        "category": "Realizam kože i fotografije",
        "recommended_weight": 0.5,
        "size_bytes": 228459148,
        "sha256": "275FAB00CB4458DD916BA760C5C37E339D0D5DB5F3E245838858F71469A3CEC1",
        "note": "Prirodna tekstura kože i nesavršenosti (Skin Realism REWORKED, SDXL). Preporučena jačina 0,3–0,7 (zadano 0,5); izbjegavaj 1,0 jer deformira lice. Okidač: Detailed natural skin and blemishes without-makeup and acne. Oko 218 MB, s Civitaija. Ako preuzimanje zatraži prijavu, upiši CIVITAI_TOKEN u data\\.env.",
    },
]


def dest_dir_for(kind: str | None = None) -> Path:
    kind = (kind or "checkpoint").strip().lower()
    if kind in {"lora", "loras"}:
        return loras_dir()
    if kind in {"animatediff", "motion", "animatediff_models"}:
        return animatediff_models_dir()
    if kind in {"diffusion", "diffusion_models", "unet", "diffusion_model"}:
        return diffusion_models_dir()
    if kind in {"text_encoder", "text_encoders", "clip", "clip_name"}:
        return text_encoders_dir()
    if kind in {"vae"}:
        return vae_dir()
    if kind in {"clip_vision", "clip-vision", "clipvision"}:
        return clip_vision_dir()
    if kind in {"ipadapter", "ip_adapter", "ip-adapter"}:
        return ipadapter_dir()
    if kind in {"ultralytics", "ultralytics_bbox", "ultralytics-bbox", "yolo", "yolo_bbox"}:
        return ultralytics_bbox_dir()
    return checkpoints_dir()


CURATED_LORA_GROUP = "Preporučene SDXL LoRA-e (realizam i detalji)"


def curated_by_id(cid: str) -> dict | None:
    cid = (cid or "").strip()
    return next((c for c in CURATED if c["id"] == cid), None)

_UA = "AI-Influencer-Studio/1.1.0"
_lock = threading.RLock()
_state: dict = {
    "status": "idle",  # idle|running|done|error
    "filename": "",
    "url": "",
    "bytes": 0,
    "total": 0,
    "percent": 0,
    "message": "",
    "error": "",
    "path": "",
    "resumed": False,
    "speed": 0,
    "speed_label": "",
    "connections": 0,
}
_thread: threading.Thread | None = None
_cancel = threading.Event()



_TOKEN_QUERY_RE = re.compile(r"([?&](?:token|key)=)[^&\s#]+", re.I)


def _is_civitai_url(url: str) -> bool:
    host = (urllib.parse.urlparse(url or "").hostname or "").lower()
    return host == "civitai.com" or host.endswith(".civitai.com")


def _data_env_file() -> Path | None:
    data = (os.environ.get("STUDIO_DATA_DIR") or "").strip()
    candidates = []
    if data:
        candidates.append(Path(data) / ".env")
    candidates.append(Path(__file__).resolve().parent / "data" / ".env")
    for path in candidates:
        if path.is_file():
            return path
    return None


def civitai_token() -> str:
    """Pročitaj CIVITAI_TOKEN iz okruženja ili data/.env. Vrijednost se nikad ne ispisuje."""
    tok = (os.environ.get("CIVITAI_TOKEN") or "").strip()
    if tok:
        return tok
    path = _data_env_file()
    if path is None:
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in {"'", '"'}:
            val = val[1:-1]
        if key == "CIVITAI_TOKEN" and val:
            return val
    return ""


def redact_secret_url(text: str) -> str:
    """Makni token/key iz URL-a i teksta grešaka, da se nikad ne pojave u logu ili snapshotu."""
    if not text:
        return text
    return _TOKEN_QUERY_RE.sub(r"\1", str(text))


def with_civitai_token(url: str) -> str:
    """Na Civitai URL dodaj ?token= iz CIVITAI_TOKEN, ako postoji i ako već nije u URL-u."""
    url = (url or "").strip()
    if not url or not _is_civitai_url(url):
        return url
    token = civitai_token()
    if not token:
        return url
    parsed = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if any(k.lower() == "token" for k, _ in q):
        return url
    q.append(("token", token))
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(q)))


def download_error_message(exc: BaseException, url: str = "") -> str:
    """Kratka poruka za korisnika, bez tajni. Civitai 401/403 upućuje na CIVITAI_TOKEN."""
    code = getattr(exc, "code", None)
    target = url or str(getattr(exc, "url", "") or "")
    if code in {401, 403} and (not target or _is_civitai_url(target)):
        return (
            "Civitai je zatražio prijavu za preuzimanje. Upiši CIVITAI_TOKEN u data\\.env "
            "(API ključ s https://civitai.com/user/account) i pokušaj ponovno."
        )
    return redact_secret_url(str(exc))[:500]


def snapshot() -> dict:
    with _lock:
        out = dict(_state)
    if out.get("url"):
        out["url"] = redact_secret_url(out["url"])
    if out.get("error"):
        out["error"] = redact_secret_url(out["error"])
    if out.get("message"):
        out["message"] = redact_secret_url(out["message"])
    return out


def _set(**kwargs) -> None:
    if "url" in kwargs and kwargs["url"]:
        kwargs = dict(kwargs)
        kwargs["url"] = redact_secret_url(kwargs["url"])
    if "error" in kwargs and kwargs["error"]:
        kwargs = dict(kwargs)
        kwargs["error"] = redact_secret_url(str(kwargs["error"]))
    if "message" in kwargs and kwargs["message"]:
        kwargs = dict(kwargs)
        kwargs["message"] = redact_secret_url(str(kwargs["message"]))
    with _lock:
        _state.update(kwargs)


def safe_filename(name: str) -> str:
    name = os.path.basename(name.replace("\\", "/")).strip()
    name = re.sub(r"[^\w.\- ()\[\]]+", "_", name, flags=re.UNICODE)
    name = name.strip("._ ")
    return name or "model.safetensors"


def filename_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path
    name = safe_filename(urllib.parse.unquote(os.path.basename(path)))
    return name


def validate_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise ValueError("Upiši ili zalijepi URL datoteke.")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL mora počinjati s http:// ili https://.")
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        # dozvoli u testovima preko STUDIO_ALLOW_LOCAL_DOWNLOAD=1
        if os.environ.get("STUDIO_ALLOW_LOCAL_DOWNLOAD") != "1":
            raise ValueError("Lokalni URL nije dopušten.")
    return url


def validate_filename(name: str) -> str:
    name = safe_filename(name)
    lower = name.lower()
    if not (lower.endswith(".safetensors") or lower.endswith(".ckpt") or lower.endswith(".pt") or lower.endswith(".pth")):
        raise ValueError("Datoteka mora biti .safetensors ili .ckpt.")
    return name



def curated_files(item: dict) -> list[dict]:
    files = item.get("files") if isinstance(item, dict) else None
    if files:
        return [dict(f) for f in files if isinstance(f, dict)]
    if not isinstance(item, dict):
        return []
    if item.get("url") and item.get("filename"):
        return [{
            "filename": item["filename"],
            "url": item["url"],
            "kind": item.get("kind") or "checkpoint",
            "size_bytes": item.get("size_bytes") or 0,
            "sha256": (item.get("sha256") or item.get("sha") or "").strip(),
        }]
    return []


def start_curated(item: dict) -> dict:
    """Preuzmi jedan predloženi model ili cijeli paket (više mapa)."""
    files = curated_files(item)
    if not files:
        raise ValueError("Predloženi model nema URL ni datoteke.")
    if len(files) == 1 and (item.get("kind") or "checkpoint") != "bundle":
        f = files[0]
        return start_download(f["url"], f.get("filename"), dest_dir=dest_dir_for(f.get("kind") or item.get("kind")))
    return start_bundle(files, label=item.get("name") or item.get("id") or "paket")


def start_bundle(files: list[dict], label: str = "paket") -> dict:
    global _thread
    jobs = []
    total = 0
    for f in files:
        url = validate_url(f.get("url") or "")
        name = validate_filename(f.get("filename") or filename_from_url(url))
        dest = dest_dir_for(f.get("kind")) / name
        size = int(f.get("size_bytes") or 0)
        total += size
        jobs.append({"url": url, "dest": dest, "size": size, "sha256": (f.get("sha256") or f.get("sha") or "").strip(), "filename": name, "kind": f.get("kind") or ""})
    if not jobs:
        raise ValueError("Paket nema datoteka za preuzimanje.")
    with _lock:
        if _state.get("status") == "running":
            raise RuntimeError("Preuzimanje je već u tijeku.")
        _cancel.clear()
        first = jobs[0]
        _set(
            status="running",
            filename=first["filename"],
            url=first["url"],
            bytes=0,
            total=total,
            percent=0,
            message=f"Paket {label}: 1/{len(jobs)} {first['filename']}",
            error="",
            path=str(first["dest"]),
            resumed=False,
            speed=0,
            speed_label="",
            connections=0,
            bundle=label,
            file_index=1,
            file_count=len(jobs),
        )
    t = threading.Thread(target=_run_bundle, args=(jobs, label, total), name="model-dl", daemon=True)
    _thread = t
    t.start()
    return snapshot()


def start_download(url: str, filename: str | None = None, dest_dir: Path | None = None) -> dict:
    global _thread
    url = validate_url(url)
    name = validate_filename(filename or filename_from_url(url))
    dest_dir = Path(dest_dir) if dest_dir is not None else checkpoints_dir()
    with _lock:
        if _state.get("status") == "running":
            raise RuntimeError("Preuzimanje je već u tijeku.")
        _cancel.clear()
        _set(
            status="running",
            filename=name,
            url=url,
            bytes=0,
            total=0,
            percent=0,
            message="Pokrećem preuzimanje…",
            error="",
            path=str(dest_dir / name),
            resumed=False,
            speed=0,
            speed_label="",
            connections=0,
        )
    t = threading.Thread(target=_run, args=(url, dest_dir / name), name="model-dl", daemon=True)
    _thread = t
    t.start()
    return snapshot()


def _run(url: str, dest: Path) -> None:
    try:
        written, resumed, total = _download_one(url, dest)
        if _cancel.is_set():
            _set(status="error", error="Preuzimanje je prekinuto.", message="Prekinuto.", speed=0, speed_label="")
            return
        if _state.get("status") == "error":
            return
        _set(
            status="done",
            bytes=written,
            total=total or written,
            percent=100,
            path=str(dest),
            resumed=resumed,
            speed=0,
            speed_label="",
            message=f"Spremljeno: {dest.name}",
            error="",
        )
    except Exception as exc:
        _set(status="error", error=download_error_message(exc), message="Preuzimanje nije uspjelo.", speed=0, speed_label="")


def _run_bundle(jobs: list[dict], label: str, grand_total: int) -> None:
    already = 0
    n = len(jobs)
    any_resume = False
    try:
        for i, job in enumerate(jobs):
            dest: Path = job["dest"]
            expected = int(job.get("size") or 0)
            if dest.is_file() and expected and dest.stat().st_size == expected:
                already += expected or dest.stat().st_size
                pct = int(already * 100 / grand_total) if grand_total else 0
                _set(
                    file_index=i + 1,
                    file_count=n,
                    filename=job["filename"],
                    url=job["url"],
                    path=str(dest),
                    bytes=already,
                    total=grand_total,
                    percent=min(100, pct),
                    message=f"Paket {label}: {i+1}/{n} već postoji ({dest.name})",
                )
                continue
            _set(
                file_index=i + 1,
                file_count=n,
                filename=job["filename"],
                url=job["url"],
                path=str(dest),
                message=f"Paket {label}: {i+1}/{n} {job['filename']}",
            )
            written, resumed, known_total = _download_one(
                job["url"],
                dest,
                already_bytes=already,
                grand_total=grand_total,
                label=f"{i+1}/{n}",
                expected_size=expected,
                expected_sha=job.get("sha256") or "",
            )
            any_resume = any_resume or resumed
            if _cancel.is_set():
                _set(status="error", error="Preuzimanje je prekinuto.", message="Prekinuto.")
                return
            already += written
            if expected and written < expected and not (dest.is_file() and dest.stat().st_size == expected):
                # _download_one already set error if incomplete
                if _state.get("status") == "error":
                    return
        _set(
            status="done",
            bytes=already,
            total=grand_total or already,
            percent=100,
            filename=jobs[-1]["filename"],
            path=str(jobs[-1]["dest"]),
            resumed=any_resume,
            message=f"Paket spremljen: {label} ({n} datoteke)",
            error="",
        )
    except Exception as exc:
        _set(status="error", error=download_error_message(exc), message="Preuzimanje paketa nije uspjelo.")


PARALLEL_CONNECTIONS = 8
CHUNK_SIZE = 32 * 1024 * 1024
CHUNK_SIZE_LARGE = 64 * 1024 * 1024
LARGE_FILE = 4 * 1024 * 1024 * 1024
READ_BUFFER = 8 * 1024 * 1024
PROBE_TIMEOUT = 30
FETCH_TIMEOUT = 60


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        n = int(raw)
        return n if n > 0 else default
    except ValueError:
        return default


def _chunk_size_for(total: int) -> int:
    override = _env_int("STUDIO_DL_CHUNK", 0)
    if override:
        return override
    if total >= LARGE_FILE:
        return CHUNK_SIZE_LARGE
    return CHUNK_SIZE


def _connection_count(total: int, chunk_size: int) -> int:
    override = _env_int("STUDIO_DL_CONNECTIONS", 0)
    n = override or PARALLEL_CONNECTIONS
    chunks = max(1, (total + chunk_size - 1) // chunk_size)
    return max(1, min(n, chunks))


def _request(url: str, headers: dict, timeout: int = FETCH_TIMEOUT):
    req = urllib.request.Request(with_civitai_token(url), headers=headers, method="GET")
    return urllib.request.urlopen(req, timeout=timeout)


def _base_headers(extra: dict | None = None) -> dict:
    headers = {"User-Agent": _UA, "Accept-Encoding": "identity"}
    if extra:
        headers.update(extra)
    return headers


def _parse_content_range(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    # bytes start-end/total
    text = value.strip()
    if not text.lower().startswith("bytes"):
        return None
    text = text[5:].strip()
    if "/" not in text:
        return None
    span, total_s = text.split("/", 1)
    try:
        total = int(total_s) if total_s != "*" else 0
    except ValueError:
        total = 0
    if "-" not in span:
        return None
    a, b = span.split("-", 1)
    try:
        start, end = int(a), int(b)
    except ValueError:
        return None
    return start, end, total


def probe_download(url: str) -> dict:
    """Otkrij konačni URL (nakon HF/CDN preusmjeravanja), veličinu i podršku za Range."""
    info = {"url": url, "final_url": url, "total": 0, "accept_ranges": False, "etag": ""}
    # 1) HEAD
    try:
        req = urllib.request.Request(with_civitai_token(url), headers=_base_headers(), method="HEAD")
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as resp:
            info["final_url"] = resp.geturl() or url
            info["etag"] = (resp.headers.get("ETag") or "").strip()
            ar = (resp.headers.get("Accept-Ranges") or "").lower()
            length = resp.headers.get("Content-Length")
            if length and str(length).isdigit():
                info["total"] = int(length)
            if "bytes" in ar:
                info["accept_ranges"] = True
            status = getattr(resp, "status", 200) or 200
            if status >= 400:
                raise RuntimeError(f"HTTP {status}")
    except Exception:
        pass
    # 2) Range 0-0 — pouzdanije na Hugging Face / CDN
    try:
        with _request(info["final_url"] or url, _base_headers({"Range": "bytes=0-0"}), timeout=PROBE_TIMEOUT) as resp:
            info["final_url"] = resp.geturl() or info["final_url"] or url
            info["etag"] = info["etag"] or (resp.headers.get("ETag") or "").strip()
            status = getattr(resp, "status", 200) or 200
            cr = _parse_content_range(resp.headers.get("Content-Range"))
            ar = (resp.headers.get("Accept-Ranges") or "").lower()
            if status == 206 or cr:
                info["accept_ranges"] = True
                if cr and cr[2]:
                    info["total"] = cr[2]
            elif "bytes" in ar:
                info["accept_ranges"] = True
            if not info["total"]:
                length = resp.headers.get("Content-Length")
                if status == 206 and cr and cr[2]:
                    info["total"] = cr[2]
                elif length and str(length).isdigit() and status == 200:
                    # Server je možda vratio cijelu datoteku na 0-0; ne vjeruj Content-Length=1
                    n = int(length)
                    if n > 1:
                        info["total"] = n
            # potroši tijelo (1 bajt ili, u najgorem slučaju, više)
            try:
                resp.read(READ_BUFFER)
            except Exception:
                pass
    except Exception:
        if info["final_url"] != url:
            # već imamo nešto iz HEAD
            return info
    return info


def _map_path(tmp: Path) -> Path:
    return Path(str(tmp) + ".map")


def _load_chunk_map(tmp: Path) -> dict:
    path = _map_path(tmp)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_chunk_map(tmp: Path, data: dict) -> None:
    path = _map_path(tmp)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    path.write_text(payload, encoding="utf-8")


def _clear_chunk_map(tmp: Path) -> None:
    path = _map_path(tmp)
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def _done_bytes(ranges: list) -> int:
    total = 0
    for item in ranges or []:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        a, b = int(item[0]), int(item[1])
        if b >= a:
            total += b - a + 1
    return total


def _merge_ranges(ranges: list) -> list[list[int]]:
    items = sorted(
        ([int(a), int(b)] for a, b in (r for r in ranges if isinstance(r, (list, tuple)) and len(r) == 2)),
        key=lambda x: x[0],
    )
    out: list[list[int]] = []
    for a, b in items:
        if b < a:
            continue
        if not out or a > out[-1][1] + 1:
            out.append([a, b])
        else:
            out[-1][1] = max(out[-1][1], b)
    return out


def _missing_ranges(total: int, done: list, chunk_size: int) -> list[tuple[int, int]]:
    covered = _merge_ranges(done)
    missing: list[tuple[int, int]] = []
    pos = 0
    idx = 0
    while pos < total:
        if idx < len(covered) and covered[idx][1] < pos:
            idx += 1
            continue
        if idx < len(covered) and covered[idx][0] <= pos <= covered[idx][1]:
            pos = covered[idx][1] + 1
            idx += 1
            continue
        end_limit = total - 1
        if idx < len(covered) and covered[idx][0] > pos:
            end_limit = covered[idx][0] - 1
        end = min(pos + chunk_size - 1, end_limit)
        missing.append((pos, end))
        pos = end + 1
    return missing


def _fmt_speed(bps: float) -> str:
    if bps >= 1024 ** 2:
        return f"{bps / 1024**2:.1f} MB/s"
    if bps >= 1024:
        return f"{bps / 1024:.0f} KB/s"
    if bps > 0:
        return f"{bps:.0f} B/s"
    return "0 B/s"


def _progress_message(written: int, total: int, speed: float, label: str = "", extra: str = "") -> str:
    pct = int(written * 100 / total) if total else 0
    msg = "Preuzeto " + _fmt(written)
    if total:
        msg += f" / {_fmt(total)} ({pct} %)"
    if speed > 0:
        msg += f" · {_fmt_speed(speed)}"
    if extra:
        msg += f" · {extra}"
    if label:
        msg += f" · {label}"
    return msg


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(READ_BUFFER)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _verify_download(path: Path, expected_size: int = 0, expected_sha: str = "") -> None:
    size = path.stat().st_size
    if expected_size and size != int(expected_size):
        raise RuntimeError(f"Veličina datoteke ne odgovara ({size} / {expected_size} bajtova).")
    if expected_sha:
        got = _sha256_file(path)
        want = expected_sha.strip().lower().removeprefix("sha256:")
        if got != want:
            raise RuntimeError("sha256 potpis se ne podudara.")


def _preallocate(tmp: Path, total: int) -> None:
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with tmp.open("ab+") as fh:
        current = fh.seek(0, os.SEEK_END)
        if current < total:
            fh.truncate(total)
        elif current > total:
            fh.truncate(total)


def _download_one(
    url: str,
    dest: Path,
    *,
    already_bytes: int = 0,
    grand_total: int = 0,
    label: str = "",
    expected_size: int = 0,
    expected_sha: str = "",
    connections: int | None = None,
    chunk_size: int | None = None,
) -> tuple[int, bool, int]:
    """Preuzmi jednu datoteku (paralelni Range ili jedna veza, s nastavkom).

    Vraća (veličina datoteke, resumed, file_total). Ne postavlja status=done.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    probe = probe_download(url)
    final_url = probe.get("final_url") or url
    file_total = int(probe.get("total") or expected_size or 0)
    accept = bool(probe.get("accept_ranges"))
    use_chunk = int(chunk_size) if chunk_size else _chunk_size_for(file_total or expected_size or 0)
    can_parallel = bool(accept and file_total and file_total > use_chunk)
    if connections is not None:
        can_parallel = bool(accept and file_total and file_total > 0 and max(1, connections) > 1 and file_total > use_chunk)
    # Ako je datoteka veća od jednog dijela, paralelno; inače jedna veza.
    if can_parallel:
        try:
            return _download_parallel(
                url,
                final_url,
                dest,
                tmp,
                file_total,
                already_bytes=already_bytes,
                grand_total=grand_total,
                label=label,
                expected_size=expected_size,
                expected_sha=expected_sha,
                connections=connections,
                chunk_size=use_chunk,
                etag=probe.get("etag") or "",
            )
        except _FallbackSingle as exc:
            _set(message="Poslužitelj ne podržava paralelni Range, prelazim na jednu vezu…" + (f" ({label})" if label else ""))
            # ako je fallback svjestan razloga, nastavi jednom vezom
            _ = exc
    return _download_single(
        url,
        final_url,
        dest,
        tmp,
        already_bytes=already_bytes,
        grand_total=grand_total,
        label=label,
        expected_size=expected_size or file_total,
        expected_sha=expected_sha,
        known_total=file_total,
    )


class _FallbackSingle(Exception):
    """Signal da paralelni način nije moguć i treba jedna veza."""


def _download_single(
    url: str,
    final_url: str,
    dest: Path,
    tmp: Path,
    *,
    already_bytes: int = 0,
    grand_total: int = 0,
    label: str = "",
    expected_size: int = 0,
    expected_sha: str = "",
    known_total: int = 0,
) -> tuple[int, bool, int]:
    _clear_chunk_map(tmp)
    existing = tmp.stat().st_size if tmp.is_file() else 0
    # Ako je stara .part prethodno prealocirana na punu veličinu, ne možemo je nastaviti kao prefiks.
    if existing and known_total and existing == known_total:
        # možda je datoteka već cijela u .part
        existing = known_total
    headers = _base_headers()
    resumed = False
    target_url = final_url or url
    if existing > 0 and not (known_total and existing == known_total):
        # prefiksni nastavak samo ako .part nije prealociran (veličina < total ili total nepoznat)
        if not known_total or existing < known_total:
            headers["Range"] = f"bytes={existing}-"
            resumed = True
            _set(resumed=True, message="Nastavljam preuzimanje…" + (f" ({label})" if label else ""), connections=1)
    started_at = time.time()
    started_bytes = existing if resumed else 0
    try:
        resp_cm = _request(target_url, headers)
    except Exception:
        if target_url != url:
            resp_cm = _request(url, headers)
        else:
            raise
    with resp_cm as resp:
        status = getattr(resp, "status", 200) or 200
        length = resp.headers.get("Content-Length")
        if status == 206 and length is not None:
            file_total = existing + int(length)
            mode = "ab"
            started = existing
        elif status == 206:
            cr = _parse_content_range(resp.headers.get("Content-Range"))
            file_total = cr[2] if cr and cr[2] else (existing + int(length or 0))
            mode = "ab"
            started = existing
        elif status == 200:
            file_total = int(length) if length is not None else (known_total or 0)
            mode = "wb"
            started = 0
            started_bytes = 0
            if existing:
                existing = 0
                resumed = False
                _set(resumed=False)
        else:
            raise RuntimeError(f"HTTP {status} pri preuzimanju.")
        written = started
        last_t = time.time()
        display_total = grand_total or (already_bytes + (file_total or expected_size))
        _set(connections=1, resumed=resumed, total=display_total or file_total)
        with tmp.open(mode) as out:
            while not _cancel.is_set():
                chunk = resp.read(READ_BUFFER)
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)
                now = time.time()
                if now - last_t >= 0.25 or (file_total and written == file_total):
                    overall = already_bytes + written
                    if not grand_total and file_total:
                        display_total = already_bytes + file_total
                    elapsed = max(0.001, now - started_at)
                    speed = (written - started_bytes) / elapsed
                    pct = int(overall * 100 / display_total) if display_total else 0
                    _set(
                        bytes=overall,
                        total=display_total,
                        percent=min(100, pct),
                        speed=speed,
                        speed_label=_fmt_speed(speed),
                        connections=1,
                        message=_progress_message(overall, display_total, speed, label),
                    )
                    last_t = now
        if _cancel.is_set():
            return written, resumed, file_total or known_total
        if file_total and written < file_total:
            _set(
                status="error",
                error=f"Datoteka je nepotpuna ({written} / {file_total} bajtova).",
                message="Preuzimanje nije dovršeno.",
                bytes=already_bytes + written,
                speed=0,
                speed_label="",
            )
            return written, resumed, file_total
        try:
            _verify_download(tmp, expected_size or file_total or 0, expected_sha)
        except Exception as exc:
            _set(status="error", error=download_error_message(exc), message="Provjera datoteke nije uspjela.", speed=0, speed_label="")
            return written, resumed, file_total or written
        tmp.replace(dest)
        _clear_chunk_map(tmp)
        return written, resumed, file_total or written


def _download_parallel(
    url: str,
    final_url: str,
    dest: Path,
    tmp: Path,
    file_total: int,
    *,
    already_bytes: int = 0,
    grand_total: int = 0,
    label: str = "",
    expected_size: int = 0,
    expected_sha: str = "",
    connections: int | None = None,
    chunk_size: int = CHUNK_SIZE,
    etag: str = "",
) -> tuple[int, bool, int]:
    n_conn = connections or _connection_count(file_total, chunk_size)
    cmap = _load_chunk_map(tmp)
    done = list(cmap.get("done") or [])
    resumed = False
    existing = tmp.stat().st_size if tmp.is_file() else 0

    # Stari .part bez mape: tretiraj kao kontinuirani prefiks.
    if existing and not done:
        if existing < file_total:
            done = [[0, existing - 1]]
            resumed = True
        elif existing == file_total:
            # moglo je biti prealocirano bez mape — kreni ispočetka ako nema mape
            done = []
        elif existing > file_total:
            tmp.unlink()
            existing = 0
            done = []

    if cmap.get("total") and int(cmap["total"]) != file_total:
        done = []
    if done:
        resumed = True

    _preallocate(tmp, file_total)
    missing = _missing_ranges(file_total, done, chunk_size)
    if not missing:
        try:
            _verify_download(tmp, expected_size or file_total, expected_sha)
        except Exception as exc:
            _set(status="error", error=download_error_message(exc), message="Provjera datoteke nije uspjela.", speed=0, speed_label="")
            return _done_bytes(done), resumed, file_total
        tmp.replace(dest)
        _clear_chunk_map(tmp)
        return file_total, resumed, file_total

    map_lock = threading.Lock()
    write_lock = threading.Lock()
    done_lock = threading.Lock()
    error_holder: list[Exception] = []
    fallback = {"flag": False}
    started_at = time.time()
    completed_at_start = _done_bytes(done)
    written_holder = {"n": completed_at_start}
    last_progress = {"t": 0.0}
    target_holder = {"url": final_url or url}

    def persist():
        _save_chunk_map(tmp, {"url": url, "final_url": target_holder["url"], "total": file_total, "chunk_size": chunk_size, "etag": etag, "done": _merge_ranges(done)})

    persist()
    display_total = grand_total or (already_bytes + file_total)
    _set(
        resumed=resumed,
        connections=min(n_conn, len(missing)),
        bytes=already_bytes + completed_at_start,
        total=display_total,
        message="Nastavljam preuzimanje…" if resumed else "Pokrećem paralelno preuzimanje…" + (f" ({label})" if label else ""),
    )

    def bump(n: int) -> None:
        now = time.time()
        with done_lock:
            written_holder["n"] += n
            cur = written_holder["n"]
            show = (now - last_progress["t"] >= 0.25) or cur >= file_total
            if show:
                last_progress["t"] = now
        if show:
            elapsed = max(0.001, now - started_at)
            speed = (cur - completed_at_start) / elapsed
            overall = already_bytes + cur
            pct = int(overall * 100 / display_total) if display_total else 0
            extra = f"{min(n_conn, len(missing))} veza"
            _set(
                bytes=overall,
                total=display_total,
                percent=min(100, pct),
                speed=speed,
                speed_label=_fmt_speed(speed),
                connections=min(n_conn, len(missing)),
                resumed=resumed,
                message=_progress_message(overall, display_total, speed, label, extra),
            )

    def fetch_range(start: int, end: int, resume_url: str) -> tuple[int, bytes]:
        headers = _base_headers({"Range": f"bytes={start}-{end}"})
        try:
            resp = _request(resume_url, headers)
        except Exception:
            if resume_url != url:
                resp = _request(url, headers)
            else:
                raise
        with resp:
            status = getattr(resp, "status", 200) or 200
            if status == 200 and start > 0:
                # Poslužitelj je ignorirao Range.
                try:
                    resp.read(16)
                except Exception:
                    pass
                raise _FallbackSingle("no-range")
            if status not in {200, 206}:
                raise RuntimeError(f"HTTP {status} za raspon {start}-{end}.")
            if status == 200 and start == 0 and file_total > (end - start + 1) * 2:
                # Vratio je cijelu datoteku umjesto raspona.
                raise _FallbackSingle("full-body")
            wanted = end - start + 1
            chunks: list[bytes] = []
            got = 0
            while got < wanted and not _cancel.is_set():
                piece = resp.read(min(READ_BUFFER, wanted - got))
                if not piece:
                    break
                chunks.append(piece)
                got += len(piece)
                bump(len(piece))
            if got != wanted and not _cancel.is_set():
                # ispravi progress za nepotpuni dio (ponovit ćemo ga)
                bump(-got)
                raise RuntimeError(f"Raspon {start}-{end} je nepotpun ({got} / {wanted}).")
            if _cancel.is_set():
                bump(-got)
                return start, b""
            return start, b"".join(chunks)

    def worker(start: int, end: int) -> None:
        if _cancel.is_set() or error_holder or fallback["flag"]:
            return
        try:
            off, data = fetch_range(start, end, target_holder["url"])
            if _cancel.is_set() or not data:
                return
            with write_lock:
                with tmp.open("r+b") as fh:
                    fh.seek(off)
                    fh.write(data)
                    fh.flush()
            with map_lock:
                done.append([start, start + len(data) - 1])
                persist()
        except _FallbackSingle as exc:
            fallback["flag"] = True
            error_holder.append(exc)
        except Exception as exc:
            error_holder.append(exc)

    try:
        with ThreadPoolExecutor(max_workers=n_conn, thread_name_prefix="model-dl") as pool:
            futs = [pool.submit(worker, s, e) for s, e in missing]
            for fut in as_completed(futs):
                if _cancel.is_set() or fallback["flag"]:
                    # ostali taskovi će vidjeti zastavice
                    pass
                try:
                    fut.result()
                except Exception as exc:
                    error_holder.append(exc)
                if fallback["flag"]:
                    break
    finally:
        persist()

    if fallback["flag"]:
        # ostavi .part prefiks ako imamo kontinuirani početak, inače mapu
        raise _FallbackSingle("range-rejected")
    if _cancel.is_set():
        return written_holder["n"], resumed, file_total
    if error_holder and not fallback["flag"]:
        err = error_holder[0]
        _set(status="error", error=download_error_message(err), message="Preuzimanje nije uspjelo.", speed=0, speed_label="")
        return written_holder["n"], resumed, file_total

    got = _done_bytes(done)
    if got < file_total:
        _set(
            status="error",
            error=f"Datoteka je nepotpuna ({got} / {file_total} bajtova).",
            message="Preuzimanje nije dovršeno.",
            bytes=already_bytes + got,
            speed=0,
            speed_label="",
        )
        return got, resumed, file_total
    try:
        _verify_download(tmp, expected_size or file_total, expected_sha)
    except Exception as exc:
        _set(status="error", error=download_error_message(exc), message="Provjera datoteke nije uspjela.", speed=0, speed_label="")
        return got, resumed, file_total
    tmp.replace(dest)
    _clear_chunk_map(tmp)
    return file_total, resumed, file_total


def _fmt(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024**3:.2f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024**2:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"
