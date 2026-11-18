#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.0.7: preset opcije profila i system prompt."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import inbox  # noqa: E402

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if cond:
        print("  OK ", msg)
    else:
        print("  FAIL", msg)
        failures.append(msg)


def ids(kind: str) -> set[str]:
    return {o["id"] for o in inbox.PROFILE_OPTIONS[kind]}


def test_presets_present() -> None:
    print("== preset opcije ==")
    w = ids("writing_style")
    for need in ("very_short", "short", "one_two", "medium", "longer_serious", "adapt_fan"):
        check(need in w, f"duljina {need}")
    labels = {o["id"]: o["label"] for o in inbox.PROFILE_OPTIONS["writing_style"]}
    check("par riječi" in labels["very_short"], "label vrlo kratko")
    check("1 rečenica" in labels["short"], "label kratko")
    check("3–4" in labels["medium"] or "3-4" in labels["medium"], "label srednje 3-4")
    s = ids("slang")
    for need in ("none", "light", "moderate", "lots", "dalmatian", "zagreb", "en_internet", "genz"):
        check(need in s, f"slang {need}")
    e = ids("emoji_use")
    for need in ("never", "rare", "one_per", "often", "end_only", "set"):
        check(need in e, f"emoji {need}")
    lang = ids("language")
    for need in ("HR", "EN", "DE", "IT", "ES", "SR_BS", "follow_fan", "HR_EN"):
        check(need in lang, f"jezik {need}")
    pub = inbox.profile_options_public()
    check("prompt" not in json.dumps(pub), "javni options nemaju prompt tekst")


def test_aliases_and_custom() -> None:
    print("== aliasi i prilagođeno ==")
    check(inbox.canonicalize_profile_choice("writing_style", "long") == "longer_serious", "long -> longer_serious")
    check(inbox.canonicalize_profile_choice("slang", "heavy") == "lots", "heavy -> lots")
    check(inbox.canonicalize_profile_choice("emoji_use", "none") == "never", "none -> never")
    check(inbox.canonicalize_profile_choice("emoji_use", "light") == "rare", "light -> rare")
    check(inbox.canonicalize_profile_choice("emoji_use", "lots") == "often", "lots -> often")
    check(inbox.canonicalize_profile_choice("language", "MIX") == "follow_fan", "MIX -> follow_fan")
    check(inbox.canonicalize_profile_choice("emoji_use", "set:😍😘") == "set", "set:… -> set")
    check(inbox.canonicalize_profile_choice("slang", "govori kao pjesnik") == "custom", "slobodan tekst je custom")
    check(inbox.field_prompt_text("slang", "govori kao pjesnik") == "govori kao pjesnik", "custom ide u prompt kako jest")
    check(inbox.canonicalize_profile_choice("writing_style", "short") == "short", "staro short ostaje short")


def test_prompt() -> None:
    print("== build_system_prompt ==")
    p = inbox.build_system_prompt(
        {
            "name": "Luna",
            "writing_style": "very_short",
            "slang": "dalmatian",
            "emoji_use": "set:😍😘",
            "language": "DE",
            "examples": [{"fan": "hej što radiš", "reply": "Evo, pijem kavu"}],
        }
    )
    check("par riječi" in p, "prompt ima vrlo kratko")
    check("dalmatinsk" in p.lower(), "prompt ima dalmatinski")
    check("😍😘" in p, "prompt ima odabrani set")
    check("Deutsch" in p or "njemačk" in p.lower(), "prompt ima njemački")
    check("Fan: hej što radiš" in p, "primjer Fan:")
    check("Luna: Evo, pijem kavu" in p, "primjer Luna:")
    check("format Fan:" in p, "uputa o formatu primjera")

    old = inbox.build_system_prompt(
        {
            "name": "Luna",
            "writing_style": "short",
            "slang": "light",
            "emoji_use": "light",
            "language": "MIX",
        }
    )
    check("jedna rečenica" in old or "kratke poruke" in old, "staro short i dalje radi")
    check("malo razgovornog slenga" in old, "staro light slang")
    check("rijetko" in old, "staro light emoji -> rijetko")
    check("jeziku na kojem fan piše" in old, "staro MIX -> prati jezik fana")

    custom = inbox.build_system_prompt({"writing_style": "samo haiku", "language": "francuski, vrlo formalno"})
    check("samo haiku" in custom, "custom duljina u promptu")
    check("francuski, vrlo formalno" in custom, "custom jezik u promptu")


def test_upsert_long_values() -> None:
    print("== upsert ne skraćuje nove vrijednosti ==")
    with tempfile.TemporaryDirectory() as td:
        data = Path(td) / "data"
        data.mkdir()
        os.environ["STUDIO_DATA_DIR"] = str(data)
        os.environ["STUDIO_APP_DIR"] = str(ROOT)
        inbox.configure_paths(ROOT)
        inbox.init_db()
        long_lang = "hrvatski s ponešto francuskog, vrlo formalno"
        long_em = "set:😍😘✨🔥💯"
        prof = inbox.upsert_profile(
            {
                "name": "Test",
                "writing_style": "adapt_fan",
                "slang": "zagreb",
                "emoji_use": long_em,
                "language": long_lang,
            }
        )
        check(prof["language"] == long_lang, "jezik nije odsječen")
        check(prof["emoji_use"] == long_em, "emoji set nije odsječen")
        check(prof["writing_style"] == "adapt_fan", "adapt_fan spremljen")
        again = inbox.get_profile(prof["id"])
        check(again and again["language"] == long_lang, "nakon čitanja jezik ostaje")


def test_html() -> None:
    print("== index.html ==")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    check("Primjeri poruka" in html, "naslov Primjeri poruka")
    check("Fan:" in html and "Luna:" in html, "hint Fan: / Luna:")
    check("pWriteChips" in html and "pSlangChips" in html, "chip kontejneri")
    check("Prilagođeno" in html, "opcija Prilagođeno")
    check("Dalmatinski" in html and "Zagrebački" in html, "slang dijalekti u JS/HTML")
    check("referentn" in html.lower() or "Referentna slika" in html, "referentna slika ostaje")


def main() -> int:
    test_presets_present()
    test_aliases_and_custom()
    test_prompt()
    test_upsert_long_values()
    test_html()
    print()
    if failures:
        print("NEUSPJEH", len(failures))
        for f in failures:
            print(" -", f)
        return 1
    print("SVI TESTOVI v1.0.7 PROŠLI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
