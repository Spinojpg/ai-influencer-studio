#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.0.17: UI se mora učitati sa starim (1.0.15) podacima.

1.0.16 je imao sintaksnu grešku u inline JS-u (krivi navodnik u gumbima
referentnih slika) pa se cijela skripta nije izvršila: prazna Osoba/Influencer,
"v…", vječni "Provjeravam ComfyUI…", stari formati. Ovaj test:
  1. `node --check` nad svim inline skriptama (obavezno ako je node dostupan),
  2. pokreće studio.py nad kopijom podataka iz 1.0.15 i zove sve API-je s učitavanja,
  3. ako je dostupan Playwright + Chrome, učita UI i traži JS greške.
Za korak 3: PW_PYTHON=/put/do/pythona-s-playwrightom (zadano: trenutni python).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import check_ui_js  # noqa: E402

FAILED = 0
FIXTURE = ROOT / "tools" / "fixtures" / "v115_data"

LOAD_ENDPOINTS = [
    "/api/state",
    "/api/status",
    "/api/models",
    "/api/settings",
    "/api/video/capabilities",
    "/api/character/install",
    "/api/models/download",
    "/api/models/installed?selected=",
    "/api/inbox/threads?profile_id=2",
]

BROWSER_SCRIPT = r"""
import json, sys
from playwright.sync_api import sync_playwright
url = sys.argv[1]
exe = sys.argv[2] or None
with sync_playwright() as p:
    kw = {"args": ["--no-sandbox"]}
    if exe:
        kw["executable_path"] = exe
    b = p.chromium.launch(**kw)
    pg = b.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(url)
    pg.wait_for_timeout(3000)
    info = pg.evaluate('''() => ({
      ver: (document.getElementById("appVersionLabel") || {}).textContent || "",
      osoba: [...document.querySelectorAll("#osoba option")].map(o => o.textContent),
      infl: [...document.querySelectorAll("#activeProfile option")].map(o => o.textContent),
      body: document.body.innerText
    })''')
    info["errors"] = errs
    b.close()
print(json.dumps(info, ensure_ascii=False))
"""


def check(cond, msg):
    global FAILED
    if cond:
        print("  OK ", msg)
    else:
        FAILED += 1
        print("  FAIL", msg)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def get(url: str):
    with urllib.request.urlopen(url, timeout=15) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def test_js_syntax():
    print("== UI JS sintaksa ==")
    try:
        errs = check_ui_js.check()
    except RuntimeError as exc:
        print("  SKIP", exc)
        return
    check(not errs, "node --check prolazi za sve inline skripte" + ("" if not errs else ": " + errs[0][:300]))


def test_server_with_old_data(data_dir: Path):
    print("== server sa starim 1.0.15 podacima ==")
    shutil.copytree(FIXTURE, data_dir)
    port = free_port()
    env = dict(os.environ, STUDIO_DATA_DIR=str(data_dir), STUDIO_PORT=str(port), STUDIO_NO_BROWSER="1",
               COMFYUI_URL="http://127.0.0.1:9")
    proc = subprocess.Popen([sys.executable, str(ROOT / "studio.py")], cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                get(base + "/api/state")
                break
            except Exception:
                time.sleep(0.1)
        for ep in LOAD_ENDPOINTS:
            try:
                code, body = get(base + ep)
                check(code == 200 and isinstance(body, dict), f"{ep} -> 200 JSON")
            except Exception as exc:
                check(False, f"{ep} -> {exc}")
        _, st = get(base + "/api/state")
        names = [p.get("name") for p in st.get("profiles") or []]
        check("Luna Marić" in names, f"stari profili vidljivi: {names}")
        luna = next((p for p in st.get("profiles") or [] if p.get("name") == "Luna Marić"), {})
        check(isinstance(luna.get("reference_images", []), list), "reference_images je lista za stari profil")
        check(bool(st.get("version")), "state.version postoji")
        test_browser(base + "/")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def test_browser(url: str):
    print("== headless UI ==")
    py = os.environ.get("PW_PYTHON") or sys.executable
    probe = subprocess.run([py, "-c", "import playwright"], capture_output=True)
    if probe.returncode != 0:
        print("  SKIP playwright nije instaliran (postavi PW_PYTHON)")
        return
    exe = os.environ.get("PW_CHROME") or shutil.which("google-chrome") or shutil.which("chromium") or ""
    r = subprocess.run([py, "-c", BROWSER_SCRIPT, url, exe], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        check(False, "browser pokrenut: " + r.stderr[-400:])
        return
    info = json.loads(r.stdout.strip().splitlines()[-1])
    check(not info["errors"], f"nema JS grešaka: {info['errors'][:2]}")
    check(info["ver"].startswith("v1."), f"oznaka verzije popunjena ({info['ver']})")
    check("Luna Marić" in info["osoba"], f"Osoba popunjena: {info['osoba']}")
    check("Luna Marić" in info["infl"], f"Influencer popunjen: {info['infl']}")
    check("Provjeravam ComfyUI" not in info["body"], "status ComfyUI nije zapeo na 'Provjeravam'")
    check("IG Portret" in info["body"], "IG formati prikazani")


def main():
    print("test_v117")
    test_js_syntax()
    with tempfile.TemporaryDirectory() as td:
        test_server_with_old_data(Path(td) / "data")
    print("FAILED" if FAILED else "ALL OK", FAILED)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
