#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Instalacija čvorova za IP-Adapter i opcijski Face Detailer (git + pip + modeli)."""

from __future__ import annotations

import threading
from pathlib import Path

import applog
import character
import comfy_launch
import model_download
import video_install

LOG_NAME = "character.log"

_lock = threading.RLock()
_state: dict = {
    "status": "idle",  # idle|running|done|error
    "kind": "",
    "step": "",
    "message": "",
    "error": "",
    "percent": 0,
    "log": [],
    "restart_required": False,
    "done_steps": [],
}
_thread: threading.Thread | None = None
_cancel = threading.Event()


def snapshot() -> dict:
    with _lock:
        out = dict(_state)
        out["log"] = list(_state.get("log") or [])
        out["done_steps"] = list(_state.get("done_steps") or [])
        return out


def _set(**kwargs) -> None:
    with _lock:
        _state.update(kwargs)
        msg = kwargs.get("message")
        if msg:
            lines = list(_state.get("log") or [])
            lines.append(str(msg))
            _state["log"] = lines[-80:]


def _log(msg: str) -> None:
    _set(message=msg)
    try:
        applog.get_logger("character").info(msg)
    except Exception:
        try:
            print(msg)
        except Exception:
            pass


def current_status(object_info: dict | None = None) -> dict:
    caps = character.capabilities(object_info)
    snap = snapshot()
    return {
        "ok": True,
        "install": snap,
        "capabilities": caps,
        "git": bool(video_install.find_git()),
        "venv_python": str(comfy_launch.venv_python()),
        "custom_nodes": str(comfy_launch.custom_nodes_dir()),
    }


def start_install(kind: str = "ipadapter") -> dict:
    global _thread
    kind = (kind or "ipadapter").strip().lower()
    if kind in {"ipa", "ip-adapter", "ip_adapter", "refs", "reference"}:
        kind = "ipadapter"
    if kind in {"face", "facedetailer", "detailer", "impact"}:
        kind = "face_detailer"
    if kind not in {"ipadapter", "face_detailer"}:
        raise ValueError("Nepoznata instalacija. Koristi ipadapter ili face_detailer.")
    with _lock:
        if _state.get("status") == "running":
            raise RuntimeError("Instalacija je već u tijeku.")
        _cancel.clear()
        label = "IP-Adapter Plus Face" if kind == "ipadapter" else "Face Detailer"
        _set(
            status="running",
            kind=kind,
            step="start",
            message=f"Pokrećem instalaciju: {label}…",
            error="",
            percent=1,
            log=[],
            restart_required=False,
            done_steps=[],
        )
    t = threading.Thread(target=_run, args=(kind,), name="character-install", daemon=True)
    _thread = t
    t.start()
    return snapshot()


def _mark(step_id: str) -> None:
    with _lock:
        done = list(_state.get("done_steps") or [])
        if step_id not in done:
            done.append(step_id)
        _state["done_steps"] = done


def _clone_repo(git: str, url: str, dirname: str) -> None:
    dest = comfy_launch.custom_nodes_dir() / dirname
    video_install._clone_or_pull(git, url, dest)
    req = dest / "requirements.txt"
    try:
        video_install._pip_requirements(req)
    except RuntimeError as exc:
        # Face Detailer (i ponekad IP-Adapter) može pasti na pip/Windows/AMD.
        _log(f"pip za {dirname} nije uspio: {exc}")
        raise
    _mark(dirname)


def _download_curated(cid: str, percent: int) -> None:
    item = model_download.curated_by_id(cid)
    if not item:
        raise RuntimeError(f"Nedostaje predloženi paket {cid}.")
    _set(step=f"download:{cid}", percent=percent)
    files = item.get("files") if item.get("kind") == "bundle" else None
    if files:
        n = len(files)
        for i, part in enumerate(files):
            if _cancel.is_set():
                raise RuntimeError("Instalacija je prekinuta.")
            dest_dir = model_download.dest_dir_for(part.get("kind") or item.get("kind"))
            dest_dir.mkdir(parents=True, exist_ok=True)
            _set(percent=min(99, percent + int((i / max(1, n)) * 20)))
            video_install._wait_download(part["url"], part["filename"], dest_dir)
            _mark(part["filename"])
        return
    dest_dir = model_download.dest_dir_for(item.get("kind"))
    dest_dir.mkdir(parents=True, exist_ok=True)
    video_install._wait_download(item["url"], item["filename"], dest_dir)
    _mark(item["filename"])


def _run(kind: str) -> None:
    try:
        applog.setup(video_install.inbox_data_dir(), "character")
    except Exception:
        pass
    try:
        git = video_install.find_git()
        if not git:
            raise RuntimeError(
                "Git nije pronađen. Instaliraj Git for Windows i ponovo pokreni, "
                "ili kloniraj ručno u C:\\ComfyUI-Zluda\\custom_nodes."
            )
        nodes = comfy_launch.custom_nodes_dir()
        nodes.mkdir(parents=True, exist_ok=True)

        if kind == "ipadapter":
            _log("Instalacija IP-Adapter Plus Face (čvor cubiq + CLIP Vision + Plus Face modeli).")
            _set(step="clone:ipadapter", percent=10)
            _clone_repo(git, character.IPADAPTER_NODE_URL, character.IPADAPTER_NODE_DIR)
            _download_curated("ipadapter-plus-face", 45)
            _set(
                status="done",
                step="done",
                percent=100,
                restart_required=True,
                error="",
                message=(
                    "IP-Adapter je instaliran. Ponovo pokreni ComfyUI (zatvori Studio i upali prečac) "
                    "da se čvor učita, zatim u profilu osobe dodaj 1–3 referentne slike lica."
                ),
            )
        else:
            _log("Instalacija Face Detailera (Impact Pack + Subpack + face_yolov8m.pt).")
            _set(step="clone:impact", percent=10)
            try:
                _clone_repo(git, character.IMPACT_PACK_URL, character.IMPACT_PACK_DIR)
            except Exception as exc:
                raise RuntimeError(
                    "Instalacija Impact Packa nije uspjela, pa Face Detailer ostaje nedostupan. "
                    f"Razlog: {exc}"
                ) from exc
            _set(step="clone:subpack", percent=35)
            try:
                _clone_repo(git, character.IMPACT_SUBPACK_URL, character.IMPACT_SUBPACK_DIR)
            except Exception as exc:
                raise RuntimeError(
                    "Impact-Subpack (detektor lica) nije se instalirao. Face Detailer ostaje skriven. "
                    f"Razlog: {exc}"
                ) from exc
            try:
                _download_curated("face-yolov8m", 70)
            except Exception as exc:
                raise RuntimeError(
                    "Čvorovi su možda instalirani, ali preuzimanje face_yolov8m.pt nije uspjelo. "
                    f"Razlog: {exc}"
                ) from exc
            _set(
                status="done",
                step="done",
                percent=100,
                restart_required=True,
                error="",
                message=(
                    "Face Detailer je instaliran. Ponovo pokreni ComfyUI da se čvorovi učitaju. "
                    "Na RX 6600 (8 GB) ostavi opciju isključenom osim kad baš želiš dodatni prolaz po licu."
                ),
            )
        _log(_state["message"])
    except Exception as exc:
        _set(
            status="error",
            error=str(exc)[:800],
            message="Instalacija nije uspjela.",
            percent=int(_state.get("percent") or 0),
        )
        _log(f"GREŠKA: {exc}")
