#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sintaksna provjera inline <script> blokova u index.html i static/*.js preko `node --check`.

Jedna greška u navodnicima (1.0.16) srušila je cijeli UI. make_release.sh ovo
pokreće prije pakiranja, pa se takav paket više ne može objaviti.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inline_scripts(html: str) -> list[str]:
    out = []
    for attrs, body in re.findall(r"<script([^>]*)>(.*?)</script>", html, re.S | re.I):
        if "src=" in attrs.lower() or not body.strip():
            continue
        if "type=" in attrs.lower() and "javascript" not in attrs.lower() and "module" not in attrs.lower():
            continue
        out.append(body)
    return out


def static_scripts(html: str, base: Path) -> list[Path]:
    """static/*.js iz mape i svi lokalni <script src="/static/..."> (nedostajuća datoteka = greška)."""
    found = {p.resolve() for p in sorted((base / "static").glob("*.js"))}
    for src in re.findall(r"<script[^>]*\ssrc=[\"']/?(static/[^\"'?#]+)", html, re.I):
        found.add((base / src).resolve())
    return sorted(found)


def check(path: Path | None = None) -> list[str]:
    """Vrati listu grešaka (prazna = OK). Baca RuntimeError ako nema node-a."""
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node nije instaliran")
    index = path or ROOT / "index.html"
    html = index.read_text(encoding="utf-8")
    errors = []
    for js in static_scripts(html, index.parent):
        if not js.is_file():
            errors.append(f"{js.name}: datoteka ne postoji (referencirana u index.html)")
            continue
        r = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
        if r.returncode != 0:
            errors.append(f"{js.name}: {(r.stderr or r.stdout).strip()}")
    for i, body in enumerate(inline_scripts(html)):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
            fh.write(body)
            tmp = fh.name
        try:
            r = subprocess.run([node, "--check", tmp], capture_output=True, text=True)
            if r.returncode != 0:
                errors.append(f"script #{i}: {(r.stderr or r.stdout).strip()}")
        finally:
            Path(tmp).unlink(missing_ok=True)
    return errors


def main() -> int:
    try:
        errs = check()
    except RuntimeError as exc:
        print("UI JS provjera:", exc)
        return 2
    if errs:
        print("UI JS SINTAKSNA GREŠKA:\n" + "\n".join(errs))
        return 1
    print("UI JS OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
