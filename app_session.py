#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sesija aplikacije: heartbeat prozora, gašenje Studija i ComfyUI stabla koje smo mi pokrenuli."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HEARTBEAT_NAME = "heartbeat.json"
COMFY_PID_NAME = "comfy.pid"
STUDIO_PID_NAME = "studio.pid"


def _pid_path(data_dir: Path, name: str) -> Path:
    return Path(data_dir) / name


def write_pid(data_dir: Path, name: str, pid: int) -> None:
    path = _pid_path(data_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(int(pid)), encoding="utf-8")


def read_pid(data_dir: Path, name: str) -> int:
    path = _pid_path(data_dir, name)
    if not path.is_file():
        return 0
    try:
        return int(path.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return 0


def clear_pid(data_dir: Path, name: str) -> None:
    path = _pid_path(data_dir, name)
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def write_comfy_pid(data_dir: Path, pid: int) -> None:
    write_pid(data_dir, COMFY_PID_NAME, pid)


def read_comfy_pid(data_dir: Path) -> int:
    return read_pid(data_dir, COMFY_PID_NAME)


def clear_comfy_pid(data_dir: Path) -> None:
    clear_pid(data_dir, COMFY_PID_NAME)


def touch_heartbeat(data_dir: Path, *, bye: bool = False, ts: float | None = None) -> dict:
    path = Path(data_dir) / HEARTBEAT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    prev = read_heartbeat(data_dir) or {}
    data = {
        "ts": float(ts if ts is not None else time.time()),
        "bye": bool(bye or prev.get("bye")),
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def read_heartbeat(data_dir: Path) -> dict | None:
    path = Path(data_dir) / HEARTBEAT_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def clear_heartbeat(data_dir: Path) -> None:
    path = Path(data_dir) / HEARTBEAT_NAME
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def kill_process_tree(pid: int, log=print) -> bool:
    """taskkill /T /F /PID na Windowsu; SIGTERM drugdje. Ne dira PID 0."""
    pid = int(pid or 0)
    if pid <= 0:
        return False
    if pid == os.getpid():
        log("Odbijam ugasiti vlastiti PID.")
        return False
    log(f"Gasim stablo procesa PID {pid}")
    if sys.platform == "win32":
        try:
            r = subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            out = ((r.stdout or "") + " " + (r.stderr or "")).strip()
            log(f"taskkill /T /F /PID {pid} -> {r.returncode} {out}")
            return r.returncode == 0
        except Exception as exc:
            log(f"taskkill nije uspio: {exc}")
            return False
    try:
        os.kill(pid, signal.SIGTERM)
        log(f"SIGTERM poslan {pid}")
        return True
    except OSError as exc:
        log(f"kill {pid} nije uspio: {exc}")
        return False


def request_studio_shutdown(studio_url: str, log=print) -> bool:
    url = (studio_url or "http://127.0.0.1:7860/").rstrip("/") + "/api/shutdown"
    try:
        req = urllib.request.Request(url, data=b"{}", method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=3) as resp:
            log(f"Studio /api/shutdown -> {resp.status}")
            return 200 <= resp.status < 500
    except Exception as exc:
        log(f"Studio /api/shutdown nije uspio: {exc}")
        return False


def shutdown_session(
    data_dir: Path,
    *,
    studio_proc=None,
    studio_url: str = "http://127.0.0.1:7860/",
    we_started_comfy: bool = False,
    comfy_pid: int = 0,
    stop_studio: bool = True,
    log=print,
    kill=kill_process_tree,
    request_shutdown=request_studio_shutdown,
) -> None:
    """Ugasi Studio. ComfyUI stablo samo ako smo ga mi pokrenuli."""
    log("Gasim sesiju aplikacije...")
    if stop_studio:
        request_shutdown(studio_url, log=log)
        if studio_proc is not None:
            poll = getattr(studio_proc, "poll", None)
            still = True if not callable(poll) else poll() is None
            if still:
                term = getattr(studio_proc, "terminate", None)
                if callable(term):
                    try:
                        term()
                    except Exception:
                        pass
                wait = getattr(studio_proc, "wait", None)
                if callable(wait):
                    try:
                        wait(timeout=4)
                    except Exception:
                        pass
            poll2 = getattr(studio_proc, "poll", None)
            if callable(poll2) and poll2() is None:
                spid = getattr(studio_proc, "pid", 0) or 0
                kill(spid, log=log)
        spid = read_pid(data_dir, STUDIO_PID_NAME)
        if spid and spid != os.getpid():
            kill(spid, log=log)
        clear_pid(data_dir, STUDIO_PID_NAME)
    if we_started_comfy:
        pid = int(comfy_pid or 0) or read_comfy_pid(data_dir)
        if pid:
            log(f"Gasim ComfyUI stablo koje je pokrenuo launcher (PID {pid})")
            kill(pid, log=log)
        else:
            log("we_started_comfy ali nema PID-a — ne diram tuđi ComfyUI.")
        clear_comfy_pid(data_dir)
    else:
        log("ComfyUI nisam ja pokrenuo — ne gasim ga.")
    clear_heartbeat(data_dir)
    log("Sesija je ugašena.")


def wait_for_app_close(
    data_dir: Path,
    browser_proc=None,
    *,
    stale_s: float = 20.0,
    poll_s: float = 1.0,
    now_fn=time.time,
    sleep_fn=time.sleep,
    log=print,
) -> str:
    """
    Čeka zatvaranje prozora: izlazak procesa preglednika (vlastiti profil)
    ili prestanak heartbeat-a (~5s ping, 20s tišina) ili goodbye s pagehide.
    """
    log("Cekam zatvaranje prozora (proces preglednika i heartbeat)...")
    while True:
        if browser_proc is not None:
            poll = getattr(browser_proc, "poll", None)
            if callable(poll):
                code = poll()
                if code is not None:
                    log(f"Preglednik je izasao, returncode={code}")
                    return "browser_exit"
        hb = read_heartbeat(data_dir)
        if hb:
            if hb.get("bye"):
                log("Stranica je javila zatvaranje (goodbye).")
                return "goodbye"
            try:
                ts = float(hb.get("ts") or 0)
            except (TypeError, ValueError):
                ts = 0.0
            if ts and now_fn() - ts >= stale_s:
                log(f"Nema heartbeat {stale_s:.0f}s — smatram da je prozor zatvoren.")
                return "heartbeat_stale"
        sleep_fn(poll_s)
