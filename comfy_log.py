#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Čitanje data/logs/comfyui.log: koje je custom nodeove ComfyUI učitao, a koje nije i zašto (1.0.19)."""

from __future__ import annotations

import re
from pathlib import Path, PureWindowsPath, PurePosixPath

MAX_READ = 3 * 1024 * 1024

IMPORT_HEADER = "Import times for custom nodes"
IMPORT_LINE_RE = re.compile(r"^\s*[\d.]+\s+seconds(?P<failed>\s*\(IMPORT FAILED\))?:\s*(?P<path>.+?)\s*$")
CANNOT_IMPORT_RE = re.compile(r"Cannot import\s+(?P<path>.+?)\s+module for custom nodes:\s*(?P<err>.*)$")
ERROR_LINE_RE = re.compile(r"^\s*(?P<exc>[A-Za-z_][\w.]*(?:Error|Exception|Exit)):\s*(?P<msg>.*)$")
NO_MODULE_RE = re.compile(r"No module named ['\"]?(?P<mod>[\w.\-]+)['\"]?")
BANNER_RE = re.compile(r"^=====\s|pokrecem\s")


def _pure(path: str):
    path = path.strip().strip('"')
    return PureWindowsPath(path) if ("\\" in path or re.match(r"^[A-Za-z]:", path)) else PurePosixPath(path)


def read_tail(path: Path | str, limit: int = MAX_READ) -> str:
    p = Path(path)
    if not p.is_file():
        return ""
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            if size > limit:
                fh.seek(size - limit)
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def last_startup_segment(text: str) -> tuple[list[str], bool]:
    """Linije zadnjeg pokretanja ComfyUI-ja. Drugi element: je li nađen popis 'Import times'."""
    lines = (text or "").splitlines()
    headers = [i for i, ln in enumerate(lines) if IMPORT_HEADER in ln]
    if not headers:
        banners = [i for i, ln in enumerate(lines) if BANNER_RE.search(ln)]
        start = banners[-1] if banners else 0
        return lines[start:], False
    last = headers[-1]
    start = headers[-2] + 1 if len(headers) > 1 else 0
    banners = [i for i in range(start, last) if BANNER_RE.search(lines[i])]
    if banners:
        start = banners[-1]
    end = last + 1
    while end < len(lines) and IMPORT_LINE_RE.match(lines[end]):
        end += 1
    return lines[start:end], True


def parse(text: str) -> dict:
    seg, has_list = last_startup_segment(text)
    loaded: list[str] = []
    failed: dict[str, dict] = {}
    dirs: list[str] = []
    paths: dict[str, str] = {}
    for i, ln in enumerate(seg):
        m = IMPORT_LINE_RE.match(ln)
        if m and has_list:
            pp = _pure(m.group("path"))
            name = pp.name
            parent = str(pp.parent)
            if parent not in dirs:
                dirs.append(parent)
            paths[name] = str(pp)
            if m.group("failed"):
                failed.setdefault(name, {"error": "", "module": "", "trace": []})
            else:
                loaded.append(name)
            continue
        m = CANNOT_IMPORT_RE.search(ln)
        if m:
            pp = _pure(m.group("path"))
            name = pp.name
            err = m.group("err").strip()
            trace = []
            j = i - 1
            while j >= 0 and not seg[j].strip():
                j -= 1
            while j >= 0 and len(trace) < 40 and seg[j].strip() and IMPORT_HEADER not in seg[j]:
                trace.insert(0, seg[j])
                j -= 1
            # zadnja linija s greškom iz tracebacka je obično preciznija
            for t in reversed(trace):
                em = ERROR_LINE_RE.match(t)
                if em:
                    err = f"{em.group('exc')}: {em.group('msg')}".strip()
                    break
            mod = ""
            nm = NO_MODULE_RE.search(err) or NO_MODULE_RE.search(m.group("err"))
            if nm:
                mod = nm.group("mod")
            failed[name] = {"error": err, "module": mod, "trace": trace[-12:]}
    return {
        "found": bool(seg),
        "has_import_list": has_list,
        "loaded": loaded,
        "failed": failed,
        "custom_nodes_dirs": dirs,
        "paths": paths,
    }


def parse_file(path: Path | str) -> dict:
    return parse(read_tail(path))


def comfy_custom_nodes_dir(info: dict) -> str:
    """custom_nodes mapa koju je ComfyUI stvarno skenirao (iz 'Import times')."""
    dirs = [d for d in (info or {}).get("custom_nodes_dirs") or [] if d and d != "."]
    for d in dirs:
        if _pure(d).name.lower() == "custom_nodes":
            return d
    return dirs[0] if dirs else ""


def _same_dir(a: str, b: str) -> bool:
    na = str(a or "").replace("\\", "/").rstrip("/").lower()
    nb = str(b or "").replace("\\", "/").rstrip("/").lower()
    return bool(na) and na == nb


def diagnose(dirname: str, info: dict | None, state: dict | None = None, label: str = "") -> str:
    """Hrvatsko objašnjenje zašto ComfyUI nije učitao čvor (ili '' ako nema što reći)."""
    info = info or {}
    state = state or {}
    label = label or dirname
    if state and state.get("exists") and not state.get("valid"):
        return (
            f"Mapa {label} postoji, ali je nepotpuna (nema __init__.py) u {state.get('path')}. "
            "Klikni „Popravi” da se ponovno preuzme."
        )
    if state and not state.get("exists"):
        return (
            f"Čvor {label} nije na disku u {state.get('custom_nodes') or 'custom_nodes'}. "
            "Klikni „Popravi” ili ponovno instaliraj."
        )
    if not info.get("found"):
        return ""
    failed = info.get("failed") or {}
    hit = None
    for name, data in failed.items():
        if name.lower() == dirname.lower():
            hit = data
            break
    if hit is not None:
        if hit.get("module"):
            return (
                f"ComfyUI nije učitao {label}: nedostaje Python paket „{hit['module']}”. "
                "Klikni „Popravi” (instalira pakete u ComfyUI venv, torch ostaje isti), zatim zatvori i ponovo pokreni Studio."
            )
        err = (hit.get("error") or "nepoznata greška").strip()
        return (
            f"ComfyUI nije učitao {label}. Greška: {err[:300]}. "
            "Klikni „Popravi”, zatim zatvori i ponovo pokreni Studio. Detalji su u data\\logs\\comfyui.log."
        )
    if info.get("has_import_list"):
        loaded = [n.lower() for n in info.get("loaded") or []]
        if dirname.lower() in loaded:
            return ""
        seen_dir = comfy_custom_nodes_dir(info)
        ours = state.get("custom_nodes") if state else ""
        if seen_dir and ours and not _same_dir(seen_dir, ours):
            return (
                f"ComfyUI učitava čvorove iz {seen_dir}, a {label} je u {ours}. "
                "Klikni „Popravi” da ga Studio instalira u pravu mapu, zatim ponovo pokreni Studio."
            )
        return (
            f"Pri zadnjem pokretanju ComfyUI uopće nije vidio {label} (nema ga na popisu čvorova). "
            "Vjerojatno je ComfyUI pokrenut prije instalacije. Zatvori Studio (i ComfyUI prozor ako je otvoren) i pokreni ponovo."
        )
    return ""
