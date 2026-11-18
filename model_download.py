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

from comfy_launch import checkpoints_dir

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
        "size_bytes": 6938065488,
        "note": "Fotorealistični SDXL s Hugging Facea, bez prijave. Oko 6,5 GB. Resume je podržan.",
    }
]

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


def _fmt(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024**3:.2f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024**2:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"
