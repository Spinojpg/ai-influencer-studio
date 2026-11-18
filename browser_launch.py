#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pronađi preglednik i otvori Studio u app prozoru na primarnom monitoru."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

ALLOWED_BROWSERS = ("brave", "edge", "chrome", "default")
DEFAULT_BROWSER = "brave"

_BRAVE_REL = Path("BraveSoftware") / "Brave-Browser" / "Application" / "brave.exe"
_EDGE_REL = Path("Microsoft") / "Edge" / "Application" / "msedge.exe"
_CHROME_REL = Path("Google") / "Chrome" / "Application" / "chrome.exe"

# Registry App Paths (Windows).
_APP_PATHS = {
    "brave": ("brave.exe",),
    "edge": ("msedge.exe",),
    "chrome": ("chrome.exe",),
}


def normalize_browser(raw: str | None, default: str = DEFAULT_BROWSER) -> str:
    v = (raw or "").strip().lower()
    if v in ALLOWED_BROWSERS:
        return v
    return default if default in ALLOWED_BROWSERS else DEFAULT_BROWSER


def _env_dirs(environ: dict | None = None) -> list[Path]:
    env = environ if environ is not None else os.environ
    out: list[Path] = []
    for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        raw = (env.get(key) or "").strip()
        if raw:
            out.append(Path(raw))
    return out


def candidate_paths(kind: str, environ: dict | None = None) -> list[Path]:
    kind = normalize_browser(kind)
    rels = {
        "brave": [_BRAVE_REL],
        "edge": [_EDGE_REL],
        "chrome": [_CHROME_REL],
        "default": [],
    }.get(kind, [])
    paths: list[Path] = []
    for base in _env_dirs(environ):
        for rel in rels:
            paths.append(base / rel)
    return paths


def registry_app_path(exe_name: str) -> Path | None:
    """Pročitaj HKCU/HKLM App Paths\\<exe>. Na ne-Windowsu vrati None."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    subkeys = (
        rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}",
        rf"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}",
    )
    roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    for root in roots:
        for sub in subkeys:
            try:
                with winreg.OpenKey(root, sub) as key:
                    val, _ = winreg.QueryValueEx(key, "")
            except OSError:
                continue
            if not val:
                continue
            path = Path(str(val).strip().strip('"'))
            if path.is_file():
                return path
    return None


def which_browser_exe(names: Iterable[str]) -> Path | None:
    for name in names:
        found = shutil.which(name)
        if found:
            path = Path(found)
            if path.is_file():
                return path
    return None


def is_browser_exe(path: Path) -> bool:
    """Odbaci prazne ili ne-.exe datoteke (kriv put iz which/registry)."""
    try:
        if not path.is_file():
            return False
        if sys.platform == "win32" and path.suffix.lower() != ".exe":
            return False
        if path.stat().st_size < 1024:
            return False
        return True
    except OSError:
        return False


def find_browser(kind: str, environ: dict | None = None) -> Path | None:
    """Vrati putanju exe-a ili None. kind: brave/edge/chrome."""
    kind = normalize_browser(kind)
    if kind == "default":
        return None
    seen: set[Path] = set()
    candidates: list[Path] = []
    for path in candidate_paths(kind, environ):
        candidates.append(path)
    for exe_name in _APP_PATHS.get(kind, ()):
        found = registry_app_path(exe_name)
        if found is not None:
            candidates.append(found)
    which_names = {
        "brave": ("brave.exe", "brave"),
        "edge": ("msedge.exe", "msedge"),
        "chrome": ("chrome.exe", "google-chrome", "chrome"),
    }.get(kind, ())
    wh = which_browser_exe(which_names)
    if wh is not None:
        candidates.append(wh)
    for path in candidates:
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key in seen:
            continue
        seen.add(key)
        if is_browser_exe(path):
            return path
    return None



def browser_profile_dir(data_dir: Path) -> Path:
    path = Path(data_dir) / "browser-profile"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def primary_work_area() -> tuple[int, int, int, int] | None:
    """
    Radna površina primarnog monitora (Display 1): (x, y, width, height).
    Na ne-Windowsu vrati None.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return None

    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    MONITOR_DEFAULTTOPRIMARY = 1
    user32 = ctypes.windll.user32
    user32.MonitorFromPoint.argtypes = [POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL

    monitor = user32.MonitorFromPoint(POINT(0, 0), MONITOR_DEFAULTTOPRIMARY)
    if not monitor:
        return None
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    left, top = int(info.rcWork.left), int(info.rcWork.top)
    width = int(info.rcWork.right - info.rcWork.left)
    height = int(info.rcWork.bottom - info.rcWork.top)
    if width <= 0 or height <= 0:
        return None
    return left, top, width, height


def window_placement(
    work: tuple[int, int, int, int] | None,
    *,
    fraction: float = 0.9,
) -> tuple[int, int, int, int] | None:
    """90 % radne površine, centrirano na primarnom monitoru."""
    if not work:
        return None
    x, y, w, h = work
    frac = min(1.0, max(0.5, float(fraction)))
    ww = max(800, int(w * frac))
    hh = max(600, int(h * frac))
    ww = min(ww, w)
    hh = min(hh, h)
    wx = x + (w - ww) // 2
    wy = y + (h - hh) // 2
    return wx, wy, ww, hh


def build_app_args(
    url: str,
    profile_dir: Path,
    placement: tuple[int, int, int, int] | None = None,
) -> list[str]:
    """Zastavice za Chromium --app. Bez --start-maximized (smetalo je s pozicijom)."""
    url = url if "://" in url else "http://" + url
    args = [
        f"--user-data-dir={str(Path(profile_dir).resolve())}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
    ]
    if placement:
        x, y, w, h = placement
        args.append(f"--window-position={int(x)},{int(y)}")
        args.append(f"--window-size={int(w)},{int(h)}")
    args.append(f"--app={url}")
    return args


def preference_order(preference: str) -> list[str]:
    pref = normalize_browser(preference)
    if pref == "default":
        return []
    fallback = [k for k in ("brave", "edge", "chrome") if k != pref]
    if pref in {"brave", "edge", "chrome"}:
        return [pref] + fallback
    return ["brave", "edge", "chrome"]


def format_cmd(cmd: list[str]) -> str:
    if sys.platform == "win32":
        try:
            return subprocess.list2cmdline(cmd)
        except Exception:
            pass
    parts = []
    for a in cmd:
        if any(ch in a for ch in ' \t"'):
            parts.append('"' + a.replace('"', '\\"') + '"')
        else:
            parts.append(a)
    return " ".join(parts)


def gui_popen_kwargs() -> dict:
    """Zastavice za GUI proces iz pythonw: odvojeni process group, bez nasljeđivanja None stdio."""
    kwargs: dict = {
        "close_fds": True,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        flags = int(getattr(subprocess, "DETACHED_PROCESS", 0x00000008))
        flags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
        # Ne koristiti CREATE_NO_WINDOW — sakrio bi preglednik.
        kwargs["creationflags"] = flags
    return kwargs


def wait_briefly(proc, seconds: float) -> int | None:
    """Vrati returncode ako proces izađe unutar seconds, inače None (još radi)."""
    wait = getattr(proc, "wait", None)
    if callable(wait) and seconds and seconds > 0:
        try:
            return wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            return None
        except TypeError:
            pass
    poll = getattr(proc, "poll", None)
    if callable(poll):
        return poll()
    return None


def spawn_gui(cmd: list[str], *, popen=subprocess.Popen, settle_s: float = 3.0, log=print) -> dict:
    kwargs = gui_popen_kwargs()
    rendered = format_cmd(cmd)
    log(f"Pokrećem preglednik: {rendered}")
    log(f"  Popen kwargs: close_fds={kwargs.get('close_fds')} creationflags={kwargs.get('creationflags')}")
    try:
        proc = popen(cmd, **kwargs)
    except Exception as exc:
        log(f"  Popen nije uspio: {type(exc).__name__}: {exc}")
        return {"ok": False, "error": str(exc), "cmd": cmd, "rendered": rendered}
    pid = getattr(proc, "pid", None)
    log(f"  PID {pid}, čekam {settle_s:.1f}s je li ostao živ")
    code = wait_briefly(proc, settle_s)
    if code is not None:
        log(f"  Proces je izašao unutar {settle_s:.1f}s, returncode={code}")
        return {
            "ok": False,
            "exited": True,
            "returncode": code,
            "cmd": cmd,
            "rendered": rendered,
            "pid": pid,
        }
    log(f"  Proces još radi (PID {pid})")
    return {"ok": True, "proc": proc, "cmd": cmd, "rendered": rendered, "pid": pid}


def open_default_browser(url: str, *, log=print) -> dict:
    try:
        import webbrowser

        ok = bool(webbrowser.open(url))
        log(f"webbrowser.open({url}) -> {ok}")
        if ok:
            return {"ok": True, "browser": "default", "method": "webbrowser.open"}
    except Exception as exc:
        log(f"webbrowser.open nije uspio: {type(exc).__name__}: {exc}")
    if sys.platform == "win32":
        try:
            os.startfile(url)  # type: ignore[attr-defined]
            log(f"os.startfile({url}) OK")
            return {"ok": True, "browser": "default", "method": "os.startfile"}
        except Exception as exc:
            log(f"os.startfile nije uspio: {type(exc).__name__}: {exc}")
    return {"ok": False, "browser": "default", "error": "niti webbrowser.open niti startfile"}


def open_studio_window(
    url: str,
    data_dir: Path,
    *,
    preference: str = DEFAULT_BROWSER,
    work_area: tuple[int, int, int, int] | None | object = ...,
    popen=subprocess.Popen,
    log=print,
    settle_s: float = 3.0,
) -> dict:
    """
    Otvori Studio u app načinu. Zadano Brave, vlastiti profil u data/browser-profile,
    prozor na primarnom monitoru. Ako Popen padne ili proces izađe unutar settle_s,
    ide Edge, pa Chrome, pa webbrowser.open / os.startfile.
    """
    url = url if "://" in url else "http://" + url
    pref = normalize_browser(preference)
    profile = browser_profile_dir(data_dir)
    if work_area is ...:
        work_area = primary_work_area()
    placement = window_placement(work_area if isinstance(work_area, tuple) else None)
    args = build_app_args(url, profile, placement)
    attempts: list[dict] = []

    if pref != "default":
        for kind in preference_order(pref):
            exe = find_browser(kind)
            if exe is None:
                log(f"Nema instalacije za {kind}, preskačem.")
                attempts.append({"browser": kind, "ok": False, "error": "nije pronađen"})
                continue
            cmd = [str(exe), *args]
            log(f"Pokušaj {kind}: {exe}")
            result = spawn_gui(cmd, popen=popen, settle_s=settle_s, log=log)
            attempts.append({"browser": kind, "exe": str(exe), **{k: result[k] for k in result if k != "proc"}})
            if result.get("ok"):
                log(
                    f"Otvoren {exe.name} ({kind}) u app načinu: {url}"
                    + (f" @ {placement}" if placement else "")
                )
                return {
                    "ok": True,
                    "browser": kind,
                    "exe": str(exe),
                    "cmd": cmd,
                    "placement": placement,
                    "profile": str(profile),
                    "pid": result.get("pid"),
                    "proc": result.get("proc"),
                    "attempts": attempts,
                }
            log(f"{kind} nije ostao pokrenut — sljedeći u lancu.")

    log("Lanac Chromium preglednika nije uspio, otvaram zadani preglednik.")
    fallback = open_default_browser(url, log=log)
    attempts.append(fallback)
    return {
        "ok": bool(fallback.get("ok")),
        "browser": "default",
        "exe": "",
        "cmd": [],
        "placement": placement,
        "profile": str(profile),
        "attempts": attempts,
        "error": fallback.get("error"),
    }
