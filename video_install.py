#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Jedan klik: custom nodeovi (git + pip) i modeli za AnimateDiff video."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import applog
import comfy_launch
import model_download
import video as video_mod

LOG_NAME = "video.log"

_lock = threading.RLock()
_state: dict = {
    "status": "idle",  # idle|running|done|error
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
        applog.get_logger("video").info(msg)
    except Exception:
        try:
            print(msg)
        except Exception:
            pass


def start_install(*, include_sd15: bool = True) -> dict:
    global _thread
    with _lock:
        if _state.get("status") == "running":
            raise RuntimeError("Instalacija je već u tijeku.")
        _cancel.clear()
        _set(
            status="running",
            step="start",
            message="Pokrećem instalaciju video podrške…",
            error="",
            percent=1,
            log=[],
            restart_required=False,
            done_steps=[],
        )
    t = threading.Thread(target=_run, args=(include_sd15,), name="video-install", daemon=True)
    _thread = t
    t.start()
    return snapshot()


def current_status(object_info: dict | None = None) -> dict:
    caps = video_mod.classify_nodes(object_info or {})
    installed = {
        r["id"]: (comfy_launch.custom_nodes_dir() / r["dir"]).is_dir()
        for r in video_mod.REPOS
    }
    snap = snapshot()
    return {
        "install": snap,
        "nodes_on_disk": installed,
        "capabilities": caps,
        "git": bool(find_git()),
        "venv_python": str(comfy_launch.venv_python()),
        "custom_nodes": str(comfy_launch.custom_nodes_dir()),
    }


def find_git() -> str:
    exe = shutil.which("git")
    if exe:
        return exe
    for cand in (
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
        r"C:\Program Files\Git\bin\git.exe",
    ):
        if Path(cand).is_file():
            return cand
    return ""


def _run_cmd(argv: list[str], *, cwd: Path | None = None, timeout: int = 600) -> tuple[int, str]:
    flags = 0
    if os.name == "nt":
        flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    proc = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
        env=env,
        creationflags=flags,
    )
    out = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()
    return proc.returncode, out[-4000:]


def _clone_or_pull(git: str, url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if (dest / ".git").is_dir():
        _log(f"Ažuriram {dest.name} (git pull)…")
        code, out = _run_cmd([git, "-C", str(dest), "pull", "--ff-only"], timeout=300)
        if code != 0:
            _log(f"git pull za {dest.name} nije uspio ({out[-400:]}). Koristim postojeću kopiju.")
        return
    if dest.is_dir() and any(dest.iterdir()):
        _log(f"{dest.name} već postoji (nije git klon) — preskačem.")
        return
    _log(f"Kloniram {url} u {dest}…")
    if dest.is_dir():
        dest.rmdir()
    code, out = _run_cmd([git, "clone", "--depth", "1", url, str(dest)], timeout=600)
    if code != 0:
        raise RuntimeError(f"git clone {dest.name} nije uspio: {out[-800:] or 'nema izlaza'}")


def _pip_requirements(req: Path) -> None:
    if not req.is_file():
        _log(f"Nema {req} — preskačem pip.")
        return
    py = comfy_launch.venv_python()
    if not Path(py).is_file():
        raise RuntimeError(f"Nema ComfyUI venv Pythona: {py}")
    _log(f"pip install -r {req} u {py}…")
    code, out = _run_cmd([str(py), "-m", "pip", "install", "-r", str(req)], timeout=900)
    if code != 0:
        raise RuntimeError(f"pip nije uspio za {req.parent.name}: {out[-800:]}")
    _log(f"pip za {req.parent.name} je gotov.")


def _wait_download(url: str, filename: str, dest_dir: Path) -> None:
    # Ako datoteka već postoji, preskoči.
    dest = dest_dir / filename
    if dest.is_file() and dest.stat().st_size > 1024 * 1024:
        _log(f"{filename} već postoji ({dest.stat().st_size} B) — preskačem.")
        return
    # Pričekaj ako je nešto drugo već na preuzimanju.
    for _ in range(600):
        snap = model_download.snapshot()
        if snap.get("status") != "running":
            break
        time.sleep(1)
        if _cancel.is_set():
            raise RuntimeError("Instalacija je prekinuta.")
    info = model_download.start_download(url, filename, dest_dir=dest_dir)
    _log(f"Preuzimam {filename}…")
    while True:
        if _cancel.is_set():
            raise RuntimeError("Instalacija je prekinuta.")
        snap = model_download.snapshot()
        if snap.get("status") == "running":
            pct = int(snap.get("percent") or 0)
            _set(percent=min(99, max(int(_state.get("percent") or 0), 50 + pct // 3)), message=snap.get("message") or f"Preuzimam {filename}…")
            time.sleep(0.4)
            continue
        if snap.get("status") == "done":
            _log(f"Spremljeno: {filename}")
            return
        raise RuntimeError(snap.get("error") or f"Preuzimanje {filename} nije uspjelo.")


def _run(include_sd15: bool) -> None:
    try:
        applog.setup(inbox_data_dir(), "video")
    except Exception:
        pass
    try:
        _log("Instalacija video podrške (AnimateDiff-Evolved + VideoHelperSuite + mm_sd_v15_v2).")
        git = find_git()
        if not git:
            raise RuntimeError(
                "Git nije pronađen. Instaliraj Git for Windows i ponovo pokreni, "
                "ili kloniraj ručno u C:\\ComfyUI-Zluda\\custom_nodes."
            )
        nodes = comfy_launch.custom_nodes_dir()
        nodes.mkdir(parents=True, exist_ok=True)
        n = len(video_mod.REPOS)
        for i, repo in enumerate(video_mod.REPOS):
            if _cancel.is_set():
                raise RuntimeError("Instalacija je prekinuta.")
            _set(step=f"clone:{repo['id']}", percent=10 + i * 15)
            dest = nodes / repo["dir"]
            _clone_or_pull(git, repo["url"], dest)
            _pip_requirements(dest / "requirements.txt")
            with _lock:
                done = list(_state.get("done_steps") or [])
                done.append(repo["id"])
                _state["done_steps"] = done

        # Motion module
        _set(step="motion", percent=55)
        item = model_download.curated_by_id("mm-sd15-v2")
        if item:
            _wait_download(item["url"], item["filename"], model_download.dest_dir_for("animatediff"))
        if include_sd15 and not video_mod.list_sd15_models():
            _set(step="sd15", percent=80)
            _log("Nema SD 1.5 checkpointa — preuzimam Realistic Vision V5.1 (potreban za AnimateDiff).")
            rv = model_download.curated_by_id("realistic-vision-v51")
            if rv:
                _wait_download(rv["url"], rv["filename"], model_download.dest_dir_for("checkpoint"))
        elif include_sd15:
            _log("SD 1.5 model je već tu: " + ", ".join(video_mod.list_sd15_models()[:4]))

        _set(
            status="done",
            step="done",
            percent=100,
            restart_required=True,
            error="",
            message=(
                "Video podrška je instalirana. Ponovo pokreni ComfyUI (zatvori Studio i upali prečac) "
                "da se novi čvorovi učitaju, zatim generiraj klip od 2 s."
            ),
        )
        _log(_state["message"])
    except Exception as exc:
        _set(status="error", error=str(exc)[:800], message="Instalacija nije uspjela.", percent=int(_state.get("percent") or 0))
        _log(f"GREŠKA: {exc}")


def inbox_data_dir() -> Path:
    try:
        import inbox
        return Path(inbox.DATA_DIR)
    except Exception:
        return Path(os.environ.get("STUDIO_DATA_DIR") or ".") / "data"
