#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.2.0 sučelje: jednostavan ekran Generiranje (osoba + scena + Generiraj),
sve tehničke postavke u zatvorenom „Napredno”, preglednije kartice osoba i LoRA trener.

Statičke provjere HTML/CSS/JS uvijek; UI provjere preko Playwrighta (PW_PYTHON=/put/do/pythona-s-playwrightom).
"""

from __future__ import annotations

import codecs
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAILED = 0
# zabranjeni nazivi modela (rot13, da se ne pojavljuju doslovno u kodu)
BANNED_WORDS = [codecs.decode(w, "rot13") for w in ("yhfgvsl", "fabsf")]

ADVANCED_IDS = ["model", "lora", "loraStrength", "appearExtra", "appearWeight", "batch", "seed", "negative",
                "qualityPrefix", "hiresFix", "ipaWeight", "faceDetailer", "v11GenBox", "v11Gen"]
# ID-jevi koje stari kod i testovi koriste – moraju ostati
KEEP_IDS = ["form", "osoba", "appearSummary", "appearText", "appearMeta", "appearExtra", "prompt", "tokenRow", "tokenCount",
            "tokenWarn", "styleChips", "sizes", "sizeHint", "quality", "turboHint", "kreaHint", "activeModelLine",
            "activeModelName", "activeTurboBadge", "go", "firstRunHint", "err", "model", "loraField", "lora", "loraRefresh",
            "loraStrengthRow", "loraStrength", "loraStrengthVal", "loraHint", "appearWeightField", "appearWeight",
            "appearWeightVal", "ipaField", "ipaWeight", "ipaWeightVal", "ipaHint", "ipaInstallRow", "installIpaAdv",
            "repairIpaAdv", "faceDetailerField", "faceDetailer", "faceHint", "faceInstallRow", "installFaceAdv",
            "repairFaceAdv", "batch", "qualityPrefix", "hiresFix", "hiresHint", "archHint", "seed", "randSeed", "seedHint",
            "negative", "v11HwQuick", "v11GenBox", "v11Gen", "progWrap", "results", "history", "v11Queue", "v11Gallery",
            "v11GalFilter", "v11GalMore", "profileList", "newProfile", "profileForm", "pId", "pName", "pAppear", "pNeg",
            "pModel", "pLoraField", "pLora", "pLoraStrength", "pModelType", "pStyle", "pVibe", "pWriteChips",
            "pSlangChips", "pEmojiChips", "pLangChips", "pAvoid", "pExamples", "addExample", "pAppearWeight", "pRefHint",
            "pRefDrop", "pRefList", "pRef", "pIpaWeight", "pFaceDetailer", "pLockSeed", "pLockedSeed", "pRandSeed",
            "delProfile", "pOk", "pErr", "v11Persona", "loraTrainer", "activeProfile", "status", "grokStatus",
            "checkUpdate", "appVersionLabel"]


def check(cond, msg):
    global FAILED
    if cond:
        print("  OK ", msg)
    else:
        FAILED += 1
        print("  FAIL", msg)


def _panel(html: str, tab: str, nxt: str) -> str:
    m = re.search(r'id="tab-%s".*?id="tab-%s"' % (tab, nxt), html, re.S)
    return m.group(0) if m else ""


def test_static():
    print("== statičke provjere (HTML/CSS/JS) ==")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "ui_v120.css").read_text(encoding="utf-8")
    js = (ROOT / "static" / "ui_v120.js").read_text(encoding="utf-8")
    check('/static/ui_v120.css' in html and '/static/ui_v120.js' in html, "index.html učitava ui_v120.css i ui_v120.js")
    check(html.index("/static/ui_v120.css") > html.index("/static/lora_trainer.css"), "ui_v120.css se učitava zadnji (nadjačava stare stilove)")
    missing = [i for i in KEEP_IDS if f'id="{i}"' not in html]
    check(not missing, f"svi stari ID-jevi su na mjestu {missing[:5]}")
    dup = sorted({i for i in re.findall(r'\sid="([^"]+)"', html) if len(re.findall(r'\sid="%s"' % re.escape(i), html)) > 1})
    check(not dup, f"nema dupliciranih ID-jeva {dup[:5]}")

    slike = _panel(html, "slike", "video")
    check(bool(slike), "kartica Generiranje postoji")
    pre, rest = slike.split('<details class="adv">', 1)
    for i in ("personaPicker", "osoba", "prompt", "sizes", "go"):
        check(f'id="{i}"' in pre, f"#{i} je na glavnom ekranu (izvan Napredno)")
    for i in ADVANCED_IDS:
        check(f'id="{i}"' in rest and f'id="{i}"' not in pre, f"#{i} je unutar „Napredno”")
    check(re.search(r'<details class="adv">\s*<summary><span class="adv-title">Napredno</span>', slike) is not None, "sažetak se zove „Napredno”")
    check('<details class="adv" open' not in slike, "„Napredno” je po zadanom zatvoreno")
    check(slike.count('class="adv-group"') >= 2 and "Model i stil" in slike and "Dosljednost i detalji" in slike, "napredne postavke su grupirane")

    osobe = _panel(html, "influenceri", "pregled")
    for i in ("personaCards", "profileList", "profileForm", "newProfile", "v11Persona", "loraTrainer"):
        check(f'id="{i}"' in osobe, f"Osobe: #{i}")
    tech = osobe[osobe.find('id="pfTech"'):osobe.find('id="pfChat"')]
    check(all(f'id="{i}"' in tech for i in ("pModel", "pLora", "pNeg", "pModelType", "pIpaWeight", "pLockSeed")), "tehničke postavke osobe su u sklopivom dijelu")
    basic = osobe[:osobe.find('id="pfTech"')]
    check(all(f'id="{i}"' in basic for i in ("pName", "pVibe", "pAppear", "pRef")), "osnovna polja (ime, dob, izgled, slike) su na vrhu")

    check("--bg0: #0b0d12" in css and "#7c8cff" in css, "nove boje (tamna podloga, indigo naglasak)")
    check("[hidden] { display: none !important; }" in css, "atribut hidden uvijek skriva element")
    check("window.StudioUI120" in js and "selectPersonaForGeneration" in js and "StudioLoraTrainer" in js, "ui_v120.js koristi postojeće API-je jezgre")
    for f in ("index.html", "static/ui_v120.css", "static/ui_v120.js", "DOKUMENTACIJA.md", "CHANGELOG.md"):
        t = (ROOT / f).read_text(encoding="utf-8").lower()
        check(not any(w in t for w in BANNED_WORDS), f"{f}: bez zabranjenih naziva")


# ------------------------------------------------------------------ server + UI

def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def http(method, url, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:
            return exc.code, {}


def tiny_png(rgb=(180, 120, 140), size=64) -> str:
    import base64
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode()


BROWSER_SCRIPT = r"""
import json, sys
from playwright.sync_api import sync_playwright
url, exe = sys.argv[1], sys.argv[2] or None
ids = json.loads(sys.argv[3])
ADV = ["model", "seed", "negative", "ipaWeight", "hiresFix", "appearExtra", "v11Sampler", "v11Cfg", "v11Freeu", "v11Tpl"]
tabs = ["pregled", "slike", "influenceri", "video", "kalendar", "poruke", "modeli", "postavke"]
out = {}
with sync_playwright() as p:
    kw = {"args": ["--no-sandbox"]}
    if exe:
        kw["executable_path"] = exe
    b = p.chromium.launch(**kw)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    errs, cons = [], []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: cons.append(m.text) if m.type == "error" else None)
    pg.goto(url)
    pg.wait_for_function('() => document.querySelectorAll("#personaPicker [data-pid]").length >= 3', timeout=20000)
    pg.wait_for_function('() => !!document.getElementById("v11Sampler")', timeout=20000)
    pg.wait_for_timeout(600)
    def in_view(sel):
        return pg.evaluate('(s) => { const e = document.querySelector(s); if (!e) return false; const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.top >= 0 && r.bottom <= window.innerHeight; }', sel)
    out["hero_in_view"] = {s: in_view(s) for s in ("#personaPicker", "#prompt", "#go")}
    out["chips"] = pg.evaluate('() => Array.from(document.querySelectorAll("#personaPicker [data-pid]")).map(b => [b.dataset.pid, b.classList.contains("on"), b.classList.contains("has-lora")])')
    out["adv_open"] = pg.evaluate('() => document.querySelector("#tab-slike details.adv").open')
    out["adv_hidden"] = {i: not pg.is_visible("#" + i) for i in ADV}
    out["adv_summary"] = pg.inner_text("#advSummary")
    out["status_pill"] = pg.inner_text("#personaStatus")
    # odabir osobe klikom na avatar
    pg.click('#personaPicker [data-pid="%s"]' % ids[1])
    pg.wait_for_timeout(400)
    out["picked"] = [pg.evaluate('() => document.getElementById("osoba").value'), pg.evaluate('(id) => document.querySelector("#personaPicker [data-pid=\\"" + id + "\\"]").classList.contains("on")', str(ids[1]))]
    # Napredno
    pg.click("#tab-slike details.adv > summary")
    pg.wait_for_timeout(500)
    out["adv_open_after"] = pg.evaluate('() => document.querySelector("#tab-slike details.adv").open')
    out["adv_visible"] = {i: pg.is_visible("#" + i) for i in ADV}
    opts = pg.evaluate('() => Array.from(document.getElementById("v11Sampler").options).map(o => o.value)')
    target = next((o for o in opts if o != "dpmpp_2m_sde"), opts[0])
    pg.select_option("#v11Sampler", target)
    pg.click("#v11Freeu")
    pg.fill("#seed", "1234")
    pg.click('#batch button[data-n="2"]')
    pg.wait_for_timeout(300)
    ex = pg.evaluate('() => window.StudioV11.genExtras()')
    out["interactive"] = {"sampler": ex.get("sampler"), "target": target, "freeu": ex.get("freeu"), "seed": pg.input_value("#seed"),
                          "batch": pg.evaluate('() => document.querySelector("#batch button.on").dataset.n')}
    pg.click("#tab-slike details.adv > summary")
    pg.wait_for_timeout(300)
    out["adv_closed_again"] = not pg.evaluate('() => document.querySelector("#tab-slike details.adv").open') and not pg.is_visible("#v11Sampler")
    # Osobe
    pg.click('.tabs button[data-tab="influenceri"]')
    pg.wait_for_function('() => document.querySelectorAll("#personaCards .persona-card").length >= 3', timeout=15000)
    pg.wait_for_timeout(700)
    out["cards"] = pg.evaluate('''() => Array.from(document.querySelectorAll("#personaCards .persona-card")).map(c => ({
        id: c.dataset.pid, name: c.querySelector(".pcard-name").textContent, lora: !!c.querySelector(".pill-ok"),
        acts: Array.from(c.querySelectorAll(".pcard-actions [data-act]")).map(b => b.dataset.act),
        w: c.getBoundingClientRect().width }))''')
    out["legacy_list_hidden"] = not pg.is_visible("#profileList")
    out["tech_closed"] = not pg.is_visible("#pModel") and pg.is_visible("#pName") and pg.is_visible("#pAppear")
    pg.click('#personaCards [data-pid="%s"] .pcard-actions [data-act="edit"]' % ids[2])
    pg.wait_for_timeout(600)
    out["edit_name"] = pg.input_value("#pName")
    out["edit_title"] = pg.inner_text("#pEditTitle")
    pg.click('#personaCards [data-pid="%s"] .pcard-actions [data-act="lora"]' % ids[0])
    pg.wait_for_timeout(1200)
    out["trainer_visible"] = pg.evaluate('() => { const e = document.getElementById("loraTrainer"); return !!e && e.offsetHeight > 100; }')
    out["trainer_persona"] = pg.evaluate('() => (document.getElementById("ltPersona") || {}).value || ""')
    pg.click('#personaCards [data-pid="%s"] .pcard-actions [data-act="gen"]' % ids[2])
    pg.wait_for_timeout(700)
    out["gen_from_card"] = [pg.evaluate('() => document.getElementById("tab-slike").classList.contains("on")'), pg.evaluate('() => document.getElementById("osoba").value')]
    out["tabs"] = {}
    for t in tabs:
        pg.click('.tabs button[data-tab="%s"]' % t)
        pg.wait_for_timeout(700)
        out["tabs"][t] = pg.evaluate('(t) => { const el = document.getElementById("tab-" + t); return !!el && el.classList.contains("on") && el.offsetHeight > 0 && el.innerText.length > 20; }', t)
    out["errors"] = errs
    out["console"] = cons
    b.close()
print(json.dumps(out, ensure_ascii=False))
"""


def test_ui():
    print("== server + headless UI (1440×900) ==")
    py = os.environ.get("PW_PYTHON") or sys.executable
    if subprocess.run([py, "-c", "import playwright"], capture_output=True).returncode != 0:
        print("  SKIP playwright nije instaliran (postavi PW_PYTHON)")
        return
    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td) / "data"
        data_dir.mkdir()
        port = free_port()
        env = dict(os.environ, STUDIO_DATA_DIR=str(data_dir), STUDIO_PORT=str(port), STUDIO_NO_BROWSER="1",
                   COMFYUI_URL="http://127.0.0.1:9", STUDIO_MOCK_GPU="AMD Radeon RX 6600|8")
        for k in ("XAI_API_KEY", "OLLAMA_BASE_URL"):
            env.pop(k, None)
        proc = subprocess.Popen([sys.executable, str(ROOT / "studio.py")], cwd=str(ROOT), env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(200):
                try:
                    http("GET", base + "/api/state")
                    break
                except Exception:
                    time.sleep(0.1)
            people = [("Luna Kovač", "26, adult woman, long auburn hair, green eyes", "26"),
                      ("Mia Horvat", "24, adult woman, platinum blonde bob", "24"),
                      ("Ivana Babić", "29, adult woman, dark straight hair", "29")]
            code, st = http("GET", base + "/api/profiles")
            existing = st.get("profiles") or []
            ids = []
            for i, (name, appear, age) in enumerate(people):
                payload = {"name": name, "appearance_prompt": appear, "age_vibe": age}
                if i < len(existing):
                    pid = existing[i]["id"]
                    http("PUT", base + f"/api/profiles/{pid}", payload)
                else:
                    code, r = http("POST", base + "/api/profiles", payload)
                    pid = (r.get("profile") or {}).get("id")
                ids.append(pid)
            http("PUT", base + f"/api/profiles/{ids[0]}", {"name": people[0][0], "appearance_prompt": people[0][1], "age_vibe": "26",
                                                         "preferred_lora": "char_luna_v1.safetensors", "preferred_lora_strength": 0.8})
            code, up = http("POST", base + f"/api/profiles/{ids[0]}/refs", {"images": [tiny_png((200, 120, 140)), tiny_png((90, 120, 200))]})
            check(code == 200 and all(ids), f"testne osobe: {ids}")
            http("POST", base + "/api/profiles/select", {"id": ids[0]})
            exe = os.environ.get("PW_CHROME") or shutil.which("google-chrome") or shutil.which("chromium") or ""
            r = subprocess.run([py, "-c", BROWSER_SCRIPT, base + "/", exe, json.dumps([str(i) for i in ids])],
                               capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                check(False, "browser pokrenut: " + r.stderr[-800:])
                return
            info = json.loads(r.stdout.strip().splitlines()[-1])
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()

    hv = info["hero_in_view"]
    check(all(hv.values()), f"odabir osobe, opis scene i Generiraj vidljivi odmah na 1440×900 {hv}")
    chips = info["chips"]
    check(len(chips) == 3 and sum(1 for c in chips if c[1]) == 1, f"avatar za svaku osobu, jedna odabrana {chips}")
    check(any(c[2] for c in chips if c[0] == str(ids[0])), "oznaka LoRA na osobi s LoRA-om")
    check("LoRA aktivna" in info["status_pill"], f"status odabrane osobe: {info['status_pill']!r}")
    check(info["adv_open"] is False, "„Napredno” je zatvoreno pri otvaranju")
    check(all(info["adv_hidden"].values()), f"tehničke postavke skrivene po zadanom {[k for k, v in info['adv_hidden'].items() if not v]}")
    check(bool(info["adv_summary"].strip()), f"sažetak u zatvorenom Napredno: {info['adv_summary']!r}")
    check(info["picked"] == [str(ids[1]), True], f"klik na avatar mijenja osobu {info['picked']}")
    check(info["adv_open_after"] and all(info["adv_visible"].values()), f"klik na Napredno otkriva sve {[k for k, v in info['adv_visible'].items() if not v]}")
    it = info["interactive"]
    check(it["sampler"] == it["target"] and it["freeu"] is False and it["seed"] == "1234" and it["batch"] == "2", f"napredne kontrole rade {it}")
    check(info["adv_closed_again"], "Napredno se ponovno zatvara")
    cards = info["cards"]
    check(len(cards) == 3 and all(c["acts"] == ["gen", "edit", "lora"] for c in cards), "kartice osoba s brzim akcijama Generiraj / Uredi / LoRA trener")
    check(cards and cards[0]["lora"] and not cards[1]["lora"], "oznaka LoRA aktivna na kartici")
    check(all(c["w"] >= 280 for c in cards), "kartice su dovoljno široke")
    check(info["legacy_list_hidden"], "stari popis profila skriven (ostaje u DOM-u)")
    check(info["tech_closed"], "tehničke postavke osobe sklopljene, osnovna polja vidljiva")
    check(info["edit_name"] == people[2][0] and people[2][0] in info["edit_title"], f"Uredi učitava profil {info['edit_name']!r}")
    check(info["trainer_visible"] and info["trainer_persona"] == str(ids[0]), f"LoRA trener s kartice {info['trainer_persona']}")
    check(info["gen_from_card"] == [True, str(ids[2])], f"Generiraj s kartice otvara Generiranje s tom osobom {info['gen_from_card']}")
    for t, ok in info["tabs"].items():
        check(ok, f"kartica {t} se prikazuje")
    check(not info["errors"], f"nema page grešaka: {info['errors'][:3]}")
    real_console = [c for c in info["console"] if "Failed to load resource" not in c]
    check(not real_console, f"nema console grešaka: {real_console[:3]}")


def main():
    print("test_ui_v120")
    test_static()
    test_ui()
    print()
    if FAILED:
        print(f"FAILED {FAILED}")
        return 1
    print("Svi UI testovi 1.2.0 su prošli.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
