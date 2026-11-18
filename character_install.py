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
import node_install
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
    "warnings": [],
    "repair": False,
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


RESTART_MARKER = "comfy_restart_required"


def restart_marker_path() -> Path:
    return Path(video_install.inbox_data_dir()) / RESTART_MARKER


def mark_restart_required(reason: str = "") -> None:
    try:
        p = restart_marker_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(reason or "custom nodes", encoding="utf-8")
    except OSError:
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
        "custom_nodes": str(node_install.effective_custom_nodes_dir()),
        "restart_pending": restart_marker_path().is_file(),
    }


def _normalize_kind(kind: str) -> str:
    kind = (kind or "ipadapter").strip().lower()
    if kind in {"ipa", "ip-adapter", "ip_adapter", "refs", "reference"}:
        kind = "ipadapter"
    if kind in {"face", "facedetailer", "detailer", "impact"}:
        kind = "face_detailer"
    if kind not in {"ipadapter", "face_detailer"}:
        raise ValueError("Nepoznata instalacija. Koristi ipadapter ili face_detailer.")
    return kind


def start_install(kind: str = "ipadapter", *, repair: bool = False) -> dict:
    global _thread
    kind = _normalize_kind(kind)
    with _lock:
        if _state.get("status") == "running":
            raise RuntimeError("Instalacija je već u tijeku.")
        _cancel.clear()
        label = "IP-Adapter Plus Face" if kind == "ipadapter" else "Face Detailer"
        _set(
            status="running",
            kind=kind,
            step="start",
            message=(f"Popravljam: {label} (provjera mape + Python paketi)…" if repair else f"Pokrećem instalaciju: {label}…"),
            error="",
            percent=1,
            log=[],
            restart_required=False,
            done_steps=[],
            warnings=[],
            repair=bool(repair),
        )
    t = threading.Thread(target=_run, args=(kind,), name="character-install", daemon=True)
    _thread = t
    t.start()
    return snapshot()


def start_repair(kind: str = "ipadapter") -> dict:
    return start_install(kind, repair=True)


def _mark(step_id: str) -> None:
    with _lock:
        done = list(_state.get("done_steps") or [])
        if step_id not in done:
            done.append(step_id)
        _state["done_steps"] = done


def _warn(msg: str) -> None:
    with _lock:
        w = list(_state.get("warnings") or [])
        w.append(msg)
        _state["warnings"] = w[-10:]
    _log("UPOZORENJE: " + msg)


def _clone_repo(git: str, url: str, dirname: str, *, run_install_py: bool = False) -> None:
    """Čvor u stvarnu custom_nodes mapu + Python paketi u ComfyUI venv (bez diranja torcha)."""
    nodes = node_install.effective_custom_nodes_dir()
    state = node_install.ensure_node(url, dirname, git=git or "", nodes_dir=nodes, log=_log)
    dest = Path(state["path"])
    py = comfy_launch.venv_python()
    if not Path(py).is_file():
        _warn(f"Nema ComfyUI venv Pythona ({py}) — preskačem Python pakete za {dirname}.")
    else:
        try:
            failed = node_install.install_requirements(dest, py, log=_log)
        except Exception as exc:
            failed = [str(exc)[:200]]
        if failed:
            _warn(f"{dirname}: neki Python paketi nisu instalirani ({', '.join(failed)[:300]}).")
        if run_install_py and not node_install.run_install_script(dest, py, log=_log):
            _warn(f"{dirname}: install.py nije uspio (vidi data\\logs\\character.log).")
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
            _log("Git nije pronađen — čvorove preuzimam kao zip s GitHuba.")
        nodes = node_install.effective_custom_nodes_dir()
        nodes.mkdir(parents=True, exist_ok=True)
        _log(f"ComfyUI custom_nodes: {nodes}")

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
                    "da se čvor učita, zatim u profilu osobe dodaj 4–8 jasnih referentnih slika lica."
                ),
            )
        else:
            _log("Instalacija Face Detailera (Impact Pack + Subpack + face_yolov8m.pt).")
            _set(step="clone:impact", percent=10)
            try:
                _clone_repo(git, character.IMPACT_PACK_URL, character.IMPACT_PACK_DIR, run_install_py=True)
            except Exception as exc:
                raise RuntimeError(
                    "Instalacija Impact Packa nije uspjela, pa Face Detailer ostaje nedostupan. "
                    f"Razlog: {exc}"
                ) from exc
            _set(step="clone:subpack", percent=35)
            try:
                _clone_repo(git, character.IMPACT_SUBPACK_URL, character.IMPACT_SUBPACK_DIR, run_install_py=True)
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
        mark_restart_required(kind)
        warns = list(_state.get("warnings") or [])
        if warns:
            _set(message=_state["message"] + " Upozorenja: " + " ".join(warns)[:500])
        _log(_state["message"])
    except Exception as exc:
        _set(
            status="error",
            error=str(exc)[:800],
            message="Instalacija nije uspjela.",
            percent=int(_state.get("percent") or 0),
        )
        _log(f"GREŠKA: {exc}")
