#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Preuzimanje checkpointa (stream + resume) u ComfyUI models/checkpoints."""

from __future__ import annotations

import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
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
        "note": "SD 1.5 checkpoint za video (AnimateDiff ne radi na SDXL). Oko 2 GB. Koristi se i za slike 512×768.",
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
        "note": "Motion modul za kratke klipove (AnimateDiff-Evolved). Oko 1,7 GB, ide u models/animatediff_models.",
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


def curated_by_id(cid: str) -> dict | None:
    cid = (cid or "").strip()
    return next((c for c in CURATED if c["id"] == cid), None)

_UA = "AI-Influencer-Studio/1.0.2"
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
}
_thread: threading.Thread | None = None
_cancel = threading.Event()


def snapshot() -> dict:
    with _lock:
        return dict(_state)


def _set(**kwargs) -> None:
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
        jobs.append({"url": url, "dest": dest, "size": size, "filename": name, "kind": f.get("kind") or ""})
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
        )
    t = threading.Thread(target=_run, args=(url, dest_dir / name), name="model-dl", daemon=True)
    _thread = t
    t.start()
    return snapshot()


def _run(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    existing = tmp.stat().st_size if tmp.is_file() else 0
    headers = {"User-Agent": _UA}
    if existing > 0:
        headers["Range"] = f"bytes={existing}-"
        _set(resumed=True, bytes=existing, message="Nastavljam preuzimanje…")
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status = getattr(resp, "status", 200) or 200
            length = resp.headers.get("Content-Length")
            if status == 206 and length is not None:
                total = existing + int(length)
                mode = "ab"
                started = existing
            elif status == 200:
                total = int(length) if length is not None else 0
                mode = "wb"
                started = 0
                if existing:
                    # Poslužitelj je ignorirao Range — kreni ispočetka.
                    existing = 0
                    _set(resumed=False)
            else:
                raise RuntimeError(f"HTTP {status} pri preuzimanju.")
            _set(total=total, bytes=started)
            written = started
            last_t = time.time()
            with tmp.open(mode) as out:
                while not _cancel.is_set():
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    written += len(chunk)
                    now = time.time()
                    if now - last_t >= 0.25 or written == total:
                        pct = int(written * 100 / total) if total else 0
                        _set(
                            bytes=written,
                            total=total,
                            percent=min(100, pct),
                            message=f"Preuzeto {_fmt(written)}"
                            + (f" / {_fmt(total)}" if total else "")
                            + (f" ({pct} %)" if total else ""),
                        )
                        last_t = now
            if _cancel.is_set():
                _set(status="error", error="Preuzimanje je prekinuto.", message="Prekinuto.")
                return
            if total and written < total:
                _set(
                    status="error",
                    error=f"Datoteka je nepotpuna ({written} / {total} bajtova).",
                    message="Preuzimanje nije dovršeno.",
                    bytes=written,
                )
                return
            tmp.replace(dest)
            _set(
                status="done",
                bytes=written,
                total=total or written,
                percent=100,
                path=str(dest),
                message=f"Spremljeno: {dest.name}",
                error="",
            )
    except Exception as exc:
        _set(status="error", error=str(exc)[:500], message="Preuzimanje nije uspjelo.")



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
        _set(status="error", error=str(exc)[:500], message="Preuzimanje paketa nije uspjelo.")


def _download_one(url: str, dest: Path, *, already_bytes: int = 0, grand_total: int = 0, label: str = "") -> tuple[int, bool, int]:
    """Preuzmi jednu datoteku s resume. Vraća (bytes_written, resumed, file_total). Ne postavlja done."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    existing = tmp.stat().st_size if tmp.is_file() else 0
    headers = {"User-Agent": _UA}
    resumed = False
    if existing > 0:
        headers["Range"] = f"bytes={existing}-"
        resumed = True
        _set(resumed=True, message="Nastavljam preuzimanje…" + (f" ({label})" if label else ""))
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
        status = getattr(resp, "status", 200) or 200
        length = resp.headers.get("Content-Length")
        if status == 206 and length is not None:
            file_total = existing + int(length)
            mode = "ab"
            started = existing
        elif status == 200:
            file_total = int(length) if length is not None else 0
            mode = "wb"
            started = 0
            if existing:
                existing = 0
                resumed = False
                _set(resumed=False)
        else:
            raise RuntimeError(f"HTTP {status} pri preuzimanju.")
        written = started
        last_t = time.time()
        display_total = grand_total or (already_bytes + file_total)
        with tmp.open(mode) as out:
            while not _cancel.is_set():
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)
                now = time.time()
                if now - last_t >= 0.25 or (file_total and written == file_total):
                    overall = already_bytes + written
                    if not grand_total and file_total:
                        display_total = already_bytes + file_total
                    pct = int(overall * 100 / display_total) if display_total else 0
                    _set(
                        bytes=overall,
                        total=display_total,
                        percent=min(100, pct),
                        message=f"Preuzeto {_fmt(overall)}"
                        + (f" / {_fmt(display_total)}" if display_total else "")
                        + (f" ({pct} %)" if display_total else "")
                        + (f" · {label}" if label else ""),
                    )
                    last_t = now
        if _cancel.is_set():
            return written, resumed, file_total
        if file_total and written < file_total:
            _set(
                status="error",
                error=f"Datoteka je nepotpuna ({written} / {file_total} bajtova).",
                message="Preuzimanje nije dovršeno.",
                bytes=already_bytes + written,
            )
            return written, resumed, file_total
        tmp.replace(dest)
        return written, resumed, file_total or written


def _fmt(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024**3:.2f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024**2:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"
