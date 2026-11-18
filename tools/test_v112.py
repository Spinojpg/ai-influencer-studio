#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.0.12: aktivni model uz Generiraj i na karticama slika."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import image_gen

FAILED = 0


def check(cond, msg):
    global FAILED
    if cond:
        print("  OK ", msg)
    else:
        FAILED += 1
        print("  FAIL", msg)


def test_short_names():
    print("== kratka imena modela ==")
    cases = {
        "RealVisXL_V5.0_fp16.safetensors": "RealVisXL V5",
        "models/checkpoints/RealVisXL_V5.0_fp16.safetensors": "RealVisXL V5",
        "juggernautXL_ragnarok.safetensors": "Juggernaut XL",
        "Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors": "Juggernaut XL",
        "Realistic_Vision_V5.1_fp16-no-ema.safetensors": "Realistic Vision V5.1",
        "Realistic_Vision_V6.0_NV_B1_fp16.safetensors": "Realistic Vision V6",
        "": "",
    }
    for inp, exp in cases.items():
        got = image_gen.short_model_name(inp)
        check(got == exp, f"{inp!r} -> {got!r}")


def _slike_panel(html: str) -> str:
    m = re.search(r'id="tab-slike".*?id="tab-video"', html, re.S)
    return m.group(0) if m else ""


def test_ui():
    print("== Slike: model uz Generiraj, izvan Napredno ==")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    slike = _slike_panel(html)
    check('id="activeModelLine"' in slike, "activeModelLine u kartici Slike")
    check('id="activeModelName"' in slike, "activeModelName")
    check('id="activeTurboBadge"' in slike, "Turbo badge")
    pre, rest = slike.split('<details class="adv">', 1)
    adv = rest.split("</details>", 1)[0]
    check('id="activeModelLine"' in pre and 'id="go"' in pre, "linija i Generiraj su izvan Napredno")
    check('id="activeModelLine"' not in adv, "linija nije pod Napredno")
    # order: model line immediately before Generiraj
    i_line, i_go = pre.find('id="activeModelLine"'), pre.find('id="go"')
    check(0 <= i_line < i_go, "linija je tik uz / ispred gumba Generiraj")
    check("function shortModelName" in html, "shortModelName")
    check("function updateActiveModelLine" in html, "updateActiveModelLine")
    check("function cardCaption" in html, "cardCaption")
    check("turbo: !!(meta && meta.turbo)" in html or "turbo: !!(meta && meta.turbo)" in html.replace(" ", ""), "povijest/kartice čuvaju turbo")
    check("model: (meta && meta.model)" in html or "model: (meta && meta.model) || " in html, "povijest čuva model")
    # old entries: caption only adds model/turbo when present
    check("item.model_label || shortModelName(item.model || " in html, "caption koristi model samo ako postoji")
    check("if (item && item.turbo)" in html, "Turbo na kartici samo kad je turbo")
    check("updateActiveModelLine();" in html, "label se osvježava")


def test_caption_omit_old():
    print("== stare stavke bez modela samo seed ==")
    # Minimal port of cardCaption used to assert omit behavior, via the same short_model_name.
    def bits(item):
        out = []
        if item and item.get("seed") is not None and item.get("seed") != "":
            out.append("seed " + str(item["seed"]))
        label = (item or {}).get("model_label") or image_gen.short_model_name((item or {}).get("model") or "")
        if label:
            out.append(label)
        if item and item.get("turbo"):
            out.append("Turbo")
        return " · ".join(out)

    check(bits({"seed": 42, "url": "x.png"}) == "seed 42", "stara stavka: samo seed")
    check(bits({"seed": 7, "model": "RealVisXL_V5.0_fp16.safetensors"}) == "seed 7 · RealVisXL V5", "nova: seed + model")
    check(
        bits({"seed": 7, "model": "juggernautXL_ragnarok.safetensors", "turbo": True})
        == "seed 7 · Juggernaut XL · Turbo",
        "nova: seed + model + Turbo",
    )
    check(bits({"url": "x.png"}) == "", "bez seeda i modela: prazno")


def main():
    test_short_names()
    test_ui()
    test_caption_omit_old()
    print()
    if FAILED:
        print(f"FAILED {FAILED}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
