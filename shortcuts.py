#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Desktop i Start Menu prečaci + osvježavanje Windowseve ikone nakon updatea."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


SHORTCUT_NAME = "AI Influencer Studio.lnk"


def _log(log, msg: str) -> None:
    if log is None:
        return
    try:
        log(msg)
    except Exception:
        pass


def icon_path_for(app_dir: Path, icon_path: Path | None = None) -> Path:
    return Path(icon_path) if icon_path is not None else Path(app_dir) / "app.ico"


def create_shortcuts_script(app_dir: Path) -> Path | None:
    app_dir = Path(app_dir)
    ps1 = app_dir / "tools" / "create-shortcuts.ps1"
    vbs = app_dir / "tools" / "create-shortcuts.vbs"
    if ps1.is_file():
        return ps1
    if vbs.is_file():
        return vbs
    return None


def run_create_shortcuts(app_dir: Path, icon_path: Path | None = None, *, log=None) -> dict:
    """Pokreni create-shortcuts.ps1 (ili .vbs). Na Linuxu se preskače."""
    app_dir = Path(app_dir)
    icon = icon_path_for(app_dir, icon_path)
    script = create_shortcuts_script(app_dir)
    if os.name != "nt":
        return {"ok": False, "skipped": "not-windows", "script": str(script) if script else ""}
    if script is None:
        _log(log, "Nema tools/create-shortcuts.ps1 ni .vbs")
        return {"ok": False, "error": "nema skripte za prečace"}
    try:
        if script.suffix.lower() == ".ps1":
            cmd = [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-AppDir",
                str(app_dir),
                "-IconPath",
                str(icon),
            ]
        else:
            cmd = ["cscript", "//nologo", str(script), str(app_dir), str(icon)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        _log(log, f"create-shortcuts rc={proc.returncode} {out[:500]}")
        return {"ok": proc.returncode == 0, "returncode": proc.returncode, "output": out, "script": str(script)}
    except Exception as exc:
        _log(log, f"create-shortcuts: {exc}")
        return {"ok": False, "error": str(exc), "script": str(script)}


def flush_windows_icon_cache(paths: list[Path] | None = None, *, log=None) -> dict:
    """SHChangeNotify + ie4uinit -show da Windows ne drži staru ikonu iz cachea."""
    if os.name != "nt":
        return {"ok": False, "skipped": "not-windows"}
    notes = []
    try:
        import ctypes
        from ctypes import wintypes

        shell32 = ctypes.windll.shell32
        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNE_UPDATEITEM = 0x00002000
        SHCNF_IDLIST = 0x0000
        SHCNF_PATHW = 0x0005
        SHCNF_FLUSH = 0x1000
        shell32.SHChangeNotify.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        for p in paths or []:
            try:
                buf = ctypes.create_unicode_buffer(str(Path(p)))
                shell32.SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_PATHW | SHCNF_FLUSH, buf, None)
                notes.append(f"updateitem:{p}")
            except Exception as exc:
                notes.append(f"updateitem-fail:{exc}")
        shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST | SHCNF_FLUSH, None, None)
        notes.append("assocchanged")
    except Exception as exc:
        notes.append(f"shchangenotify:{exc}")
        _log(log, f"SHChangeNotify: {exc}")

    ie = Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32" / "ie4uinit.exe"
    if ie.is_file():
        try:
            proc = subprocess.run([str(ie), "-show"], capture_output=True, text=True, timeout=20)
            notes.append(f"ie4uinit:{proc.returncode}")
            _log(log, f"ie4uinit -show rc={proc.returncode}")
        except Exception as exc:
            notes.append(f"ie4uinit:{exc}")
            _log(log, f"ie4uinit: {exc}")
    else:
        notes.append("ie4uinit-missing")
    return {"ok": True, "notes": notes}


def shortcut_destinations() -> list[Path]:
    dest = []
    home = Path.home()
    desktop = Path(os.environ.get("USERPROFILE") or home) / "Desktop"
    # Windows SpecialFolders — best-effort on this helper
    for key in ("USERPROFILE",):
        root = os.environ.get(key)
        if root:
            d = Path(root) / "Desktop"
            if d not in dest:
                dest.append(d)
    appdata = os.environ.get("APPDATA")
    start = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" if appdata else None
    paths = []
    for folder in dest + ([start] if start else []):
        if folder is None:
            continue
        paths.append(folder / SHORTCUT_NAME)
    return paths


def refresh_app_shortcuts(app_dir: Path, icon_path: Path | None = None, *, log=None) -> dict:
    """Nakon updatea: ponovo napiši prečace (nova ikona) i isprazni cache ikona."""
    app_dir = Path(app_dir)
    icon = icon_path_for(app_dir, icon_path)
    created = run_create_shortcuts(app_dir, icon, log=log)
    watch = [icon, *shortcut_destinations()]
    flushed = flush_windows_icon_cache(watch, log=log)
    _log(log, f"prečaci osvježeni created={created.get('ok')} flushed={flushed.get('ok')}")
    return {"ok": True, "created": created, "flushed": flushed, "icon": str(icon)}


if __name__ == "__main__":
    app = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
    print(refresh_app_shortcuts(app))
