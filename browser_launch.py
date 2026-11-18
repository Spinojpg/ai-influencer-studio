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


def find_browser(kind: str, environ: dict | None = None) -> Path | None:
    """Vrati putanju exe-a ili None. kind: brave/edge/chrome."""
    kind = normalize_browser(kind)
    if kind == "default":
        return None
    for path in candidate_paths(kind, environ):
        if path.is_file():
            return path
    for exe_name in _APP_PATHS.get(kind, ()):
        found = registry_app_path(exe_name)
        if found is not None:
            return found
    which_names = {
        "brave": ("brave.exe", "brave"),
        "edge": ("msedge.exe", "msedge"),
        "chrome": ("chrome.exe", "google-chrome", "chrome"),
    }.get(kind, ())
    return which_browser_exe(which_names)


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
    *,
    maximized: bool = True,
) -> list[str]:
    url = url if "://" in url else "http://" + url
    args = [
        f"--user-data-dir={str(Path(profile_dir).resolve())}",
        "--new-window",
    ]
    if placement:
        x, y, w, h = placement
        args.append(f"--window-position={int(x)},{int(y)}")
        args.append(f"--window-size={int(w)},{int(h)}")
    if maximized:
        args.append("--start-maximized")
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


def open_studio_window(
    url: str,
    data_dir: Path,
    *,
    preference: str = DEFAULT_BROWSER,
    work_area: tuple[int, int, int, int] | None | object = ...,
    popen=subprocess.Popen,
    log=print,
) -> dict:
    """
    Otvori Studio u app načinu. Zadano Brave, vlastiti profil u data/browser-profile,
    prozor na primarnom monitoru. Ako Brave nije tu, Edge pa Chrome pa zadani preglednik.
    """
    url = url if "://" in url else "http://" + url
    pref = normalize_browser(preference)
    profile = browser_profile_dir(data_dir)
    if work_area is ...:
        work_area = primary_work_area()
    placement = window_placement(work_area if isinstance(work_area, tuple) else None)
    args = build_app_args(url, profile, placement, maximized=True)

    if pref != "default":
        for kind in preference_order(pref):
            exe = find_browser(kind)
            if exe is None:
                continue
            cmd = [str(exe), *args]
            try:
                popen(cmd, close_fds=True)
                log(
                    f"Otvaram {exe.name} ({kind}) u app načinu na primarnom monitoru: {url}"
                    + (f" @ {placement}" if placement else "")
                )
                return {
                    "ok": True,
                    "browser": kind,
                    "exe": str(exe),
                    "cmd": cmd,
                    "placement": placement,
                    "profile": str(profile),
                }
            except OSError as exc:
                log(f"Nisam mogao pokrenuti {exe}: {exc}")
                continue

    try:
        import webbrowser

        webbrowser.open(url)
        log("Otvaram zadani preglednik:", url)
        return {"ok": True, "browser": "default", "exe": "", "cmd": [], "placement": placement, "profile": str(profile)}
    except Exception as exc:
        log("Ne mogu otvoriti preglednik:", exc)
        return {"ok": False, "browser": "default", "error": str(exc), "profile": str(profile)}
