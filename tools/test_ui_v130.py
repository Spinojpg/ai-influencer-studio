#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UI testovi za 1.3.0 (Playwright, PW_PYTHON): widescreen glass raspored bez horizontalnog prelijevanja (1728×928 i 1280×800),
grupirano Napredno (5 glass kartica) s ? objašnjenjima, RX 6600 profili, Dobra/Loša na slikama + filtar galerije,
živi GPU bar tijekom generiranja, Početna s KPI karticama, pojednostavljeni LoRA trener. Bez page/console grešaka.

Snimke zaslona: postavi UI_V130_SHOTS=/putanja (npr. /workspace) — inače idu u privremenu mapu."""

from __future__ import annotations

import io
import json
import os
import random
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILED = 0


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


def portrait_png(seed: int, size=(816, 1020)) -> bytes:
    """Mekani apstraktni „portret” (gradijent + silueta) — samo za izgled galerije u testu."""
    from PIL import Image, ImageDraw, ImageFilter
    rnd = random.Random(seed)
    w, h = size
    palettes = [((246, 196, 160), (120, 70, 90)), ((170, 200, 240), (60, 50, 110)), ((250, 214, 170), (150, 90, 60)),
                ((200, 170, 240), (70, 40, 120)), ((180, 230, 210), (40, 90, 100)), ((255, 190, 200), (110, 50, 80))]
    top, bot = palettes[seed % len(palettes)]
    im = Image.new("RGB", size)
    px = im.load()
    for y in range(h):
        t = y / h
        row = tuple(int(top[i] * (1 - t) + bot[i] * t) for i in range(3))
        for x in range(w):
            px[x, y] = row
    d = ImageDraw.Draw(im)
    cx = w // 2 + rnd.randint(-60, 60)
    skin = (rnd.randint(200, 235), rnd.randint(160, 190), rnd.randint(140, 165))
    hair = (rnd.randint(40, 120), rnd.randint(25, 80), rnd.randint(20, 60))
    d.ellipse([cx - 175, int(h * 0.20), cx + 175, int(h * 0.62)], fill=hair)
    d.ellipse([cx - 120, int(h * 0.26), cx + 120, int(h * 0.56)], fill=skin)
    d.rounded_rectangle([cx - 260, int(h * 0.66), cx + 260, h + 80], radius=180, fill=tuple(max(0, c - 40) for c in bot))
    d.rectangle([cx - 50, int(h * 0.54), cx + 50, int(h * 0.70)], fill=skin)
    im = im.filter(ImageFilter.GaussianBlur(10))
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


SEED_SCRIPT = r"""
import json, os, sys, time, sqlite3
from pathlib import Path
root, data_dir, spec = sys.argv[1], Path(sys.argv[2]), json.loads(sys.argv[3])
sys.path.insert(0, root)
os.environ["STUDIO_DATA_DIR"] = str(data_dir)
import inbox
inbox.configure_paths(data_dir=data_dir)
import services
services.init_schema()
from services import generation_service as gs, crm_service as crm
from services.common import conn
now = time.time()
gids = []
for it in spec["images"]:
    ids = gs.record_images([{"filename": it["name"], "subfolder": "", "type": "output"}], {"prompt": it["prompt"], "seed": it["seed"],
                           "model": "RealVisXL_V5.0_fp16.safetensors"}, persona_id=it["pid"], local_path=it["path"])
    gid = ids[0]
    gids.append(gid)
    with conn() as c:
        c.execute("UPDATE gallery_items SET created_at=? WHERE id=?", (now - it["age_days"] * 86400 - 600, gid))
for gid, r in spec["ratings"]:
    gs.rate_image(gallery_id=gids[gid], rating=r)
for i, (days, amount) in enumerate(spec["purchases"]):
    p = crm.record_purchase(profile_id=spec["pids"][i % len(spec["pids"])], kind=["subscription", "tip", "ppv", "custom"][i % 4], amount=amount, channel="simulate")
    with conn() as c:
        c.execute("UPDATE crm_purchases SET created_at=? WHERE id=?", (now - days * 86400 - 900, p["id"]))
print(json.dumps({"gids": gids}))
"""


BROWSER_SCRIPT = r"""
import json, sys, time
from playwright.sync_api import sync_playwright
url, exe, shots = sys.argv[1], sys.argv[2] or None, sys.argv[3]
cfg = json.loads(sys.argv[4])
ids, gids = cfg["ids"], cfg["gids"]
out = {"errors": [], "console": []}
OVERFLOW = '() => ({sw: document.documentElement.scrollWidth, iw: window.innerWidth, bw: document.body.scrollWidth})'
job = {"state": "running", "polls": 0}

def fake_generate(route):
    route.fulfill(status=200, content_type="application/json", body=json.dumps({
        "ok": True, "prompt_id": "ui-test-1", "seed": 424242, "prompt": "morning coffee on a sunny balcony", "width": 1080, "height": 1350,
        "model": "RealVisXL_V5.0_fp16.safetensors", "steps": 24, "turbo": False, "quality_profile": "realism",
        "rx_notes": ["8 GB zaštita: VAE dekodiranje prebačeno na „tiled” zbog veće slike."]}))

def fake_job(route):
    job["polls"] += 1
    imgs = [{"filename": "res_%d.png" % i, "subfolder": "", "type": "output", "gallery_id": cfg["result_gids"][i],
             "url": "/api/gallery/file/%d" % cfg["result_gids"][i]} for i in range(len(cfg["result_gids"]))]
    if job["state"] == "running":
        body = {"status": "running", "progress": {"value": 6, "max": 12}, "elapsed_s": 41, "images": imgs, "hint": "Hires prolaz u tijeku."}
    else:
        body = {"status": "done", "elapsed_s": 96, "images": imgs}
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

with sync_playwright() as p:
    kw = {"args": ["--no-sandbox", "--force-color-profile=srgb"]}
    if exe:
        kw["executable_path"] = exe
    b = p.chromium.launch(**kw)
    ctx = b.new_context(viewport={"width": 1728, "height": 928}, device_scale_factor=1)
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: out["errors"].append(str(e)))
    pg.on("console", lambda m: out["console"].append(m.text) if m.type == "error" else None)
    pg.route("**/api/generate", fake_generate)
    pg.route("**/api/job/**", fake_job)
    pg.goto(url)
    pg.wait_for_function('() => document.querySelectorAll("#personaPicker [data-pid]").length >= 3', timeout=20000)
    pg.wait_for_function('() => !!document.getElementById("v11Sampler") && !!document.getElementById("v11DetailLoras")', timeout=20000)
    pg.wait_for_timeout(900)

    # --- raspored i glass stil (1728×928) ---
    out["ov_1728"] = pg.evaluate(OVERFLOW)
    out["layout"] = pg.evaluate('''() => {
        const r = (s) => { const e = document.querySelector(s); if (!e) return null; const b = e.getBoundingClientRect(); return {l: b.left, r: b.right, t: b.top, b: b.bottom, w: b.width, h: b.height}; };
        const cs = getComputedStyle(document.querySelector("#form"));
        return { wrap: r(".wrap"), comp: r("#form"), stage: r("#tab-slike .stage"), go: r("#go"), prompt: r("#prompt"), picker: r("#personaPicker"),
                 blur: cs.backdropFilter || cs.webkitBackdropFilter || "", radius: parseFloat(cs.borderTopLeftRadius), bodyBg: getComputedStyle(document.body).backgroundImage,
                 navPill: getComputedStyle(document.querySelector(".tabs button.on")).borderRadius, navBg: getComputedStyle(document.querySelector(".tabs button.on")).backgroundImage,
                 font: getComputedStyle(document.body).fontFamily };
    }''')
    out["adv_closed"] = not pg.evaluate('() => document.querySelector("#tab-slike details.adv").open')
    out["quality_btns"] = pg.evaluate('() => Array.from(document.querySelectorAll("#quality button")).map(b => [b.dataset.profile, b.classList.contains("on")])')
    out["first_profile"] = pg.evaluate('() => ({s: document.getElementById("v11Sampler").value, h: document.getElementById("hiresFix").checked, hs: document.getElementById("v11HiresScale").value, hint: document.getElementById("qualityProfileHint").innerText})')

    # --- Napredno: 5 glass kartica + ? objašnjenja ---
    pg.click("#tab-slike details.adv > summary")
    pg.wait_for_timeout(500)
    out["adv"] = pg.evaluate('''() => {
        const groups = Array.from(document.querySelectorAll("#tab-slike .adv-grid > .adv-group"));
        const vis = groups.filter(g => g.offsetParent !== null);
        const rects = vis.map(g => g.getBoundingClientRect());
        const wrap = document.querySelector(".wrap").getBoundingClientRect(), comp = document.getElementById("form").getBoundingClientRect();
        const stage = document.querySelector("#tab-slike .stage").getBoundingClientRect();
        const order = vis.slice().sort((a, b) => { const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect(); return Math.abs(ra.top - rb.top) > 20 ? ra.top - rb.top : ra.left - rb.left; }).map(g => g.dataset.group);
        const tips = Array.from(document.querySelectorAll("#tab-slike .tip")).filter(t => t.offsetParent !== null);
        const g0 = getComputedStyle(vis[0]);
        return { n: vis.length, groups: vis.map(g => g.dataset.group), order: order, cols: new Set(rects.map(r => Math.round(r.left))).size,
                 titles: vis.map(g => (g.querySelector(".adv-group-title") || {}).textContent || ""),
                 compW: comp.width, wrapW: wrap.width, stageBelow: stage.top >= comp.bottom - 2, tips: tips.length,
                 tipsNoText: tips.filter(t => (t.dataset.tip || "").length < 25).length, cardBlur: g0.backdropFilter || g0.webkitBackdropFilter || "",
                 cardRadius: parseFloat(g0.borderTopLeftRadius) };
    }''')
    out["ov_adv_1728"] = pg.evaluate(OVERFLOW)
    tip = pg.locator("#tab-slike .adv-grid .tip").first
    tip.hover()
    pg.wait_for_timeout(200)
    out["tip_hover"] = pg.evaluate('() => { const p = document.getElementById("tipPop"); return p && !p.hidden ? p.textContent : ""; }')
    pg.keyboard.press("Escape")
    pg.mouse.move(5, 5)
    pg.wait_for_timeout(150)
    before = pg.evaluate('() => document.getElementById("hiresFix").checked')
    pg.click('#tab-slike [data-group="format"] label.check .tip')
    pg.wait_for_timeout(150)
    out["tip_in_label"] = {"same": before == pg.evaluate('() => document.getElementById("hiresFix").checked'),
                           "shown": pg.evaluate('() => !document.getElementById("tipPop").hidden')}
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(100)
    out["tip_escape"] = pg.evaluate('() => document.getElementById("tipPop").hidden')
    pg.evaluate('() => { const el = document.querySelector("#tab-slike details.adv"); window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 128); }')
    pg.wait_for_timeout(500)
    pg.screenshot(path=shots + "/ui_v130_advanced.png")

    # --- profili kvalitete ---
    pg.click('#quality button[data-profile="turbo"]')
    pg.wait_for_timeout(250)
    ex = pg.evaluate('() => window.StudioV11.genExtras()')
    out["turbo"] = {"sampler": pg.input_value("#v11Sampler"), "sched": pg.input_value("#v11Scheduler"), "hires": pg.evaluate('() => document.getElementById("hiresFix").checked'),
                    "profile": ex.get("quality_profile"), "steps": pg.evaluate('() => window.StudioCore.payload().steps')}
    pg.click('#quality button[data-profile="realism"]')
    pg.wait_for_timeout(250)
    pg.check('#v11DetailLoras input[value="skin"]')
    ex = pg.evaluate('() => window.StudioV11.genExtras()')
    out["realism"] = {"sampler": ex.get("sampler"), "sched": ex.get("scheduler"), "hires": pg.evaluate('() => document.getElementById("hiresFix").checked'),
                      "hs": ex.get("hires_scale"), "hd": ex.get("hires_denoise"), "hst": ex.get("hires_steps"), "profile": ex.get("quality_profile"),
                      "detail": ex.get("detail_loras"), "guard": ex.get("vram_guard"), "steps": pg.evaluate('() => window.StudioCore.payload().steps'), "cfg": ex.get("cfg")}
    pg.uncheck('#v11DetailLoras input[value="skin"]')
    pg.click("#tab-slike details.adv > summary")
    pg.wait_for_timeout(300)
    pg.evaluate("() => window.scrollTo(0, 0)")

    # --- generiranje (lažni ComfyUI odgovor) + GPU bar + Dobra/Loša ---
    pg.route("**/api/status", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "message": "ComfyUI je spojen"})))
    pg.click('#personaPicker [data-pid="%s"]' % ids[0])
    pg.fill("#prompt", "morning coffee on a sunny balcony, soft window light, phone snapshot")
    pg.click("#go")
    try:
        pg.wait_for_function('() => !document.getElementById("gpuLive").hidden && document.getElementById("gpuLive").innerText.includes("%")', timeout=15000)
    except Exception:
        print(json.dumps(pg.evaluate('() => ({prog: document.getElementById("progWrap").hidden, go: document.getElementById("go").disabled, txt: document.getElementById("progText").textContent, err: document.getElementById("err").textContent, gl: document.getElementById("gpuLive").outerHTML.slice(0,300)})')), file=sys.stderr)
        print("Error dbg " + json.dumps(out["errors"] + out["console"]), file=sys.stderr)
        raise
    pg.wait_for_function('() => document.querySelectorAll("#results figure.shot .rate-btn").length >= 4', timeout=15000)
    pg.wait_for_timeout(600)
    out["gpu"] = pg.evaluate('''() => { const g = document.getElementById("gpuLive"); const t = g.querySelector(".gl-temp");
        return { text: g.innerText, temp: t ? t.className : "", usage: !!g.querySelector(".gl-usage .gl-track i"), vram: !!g.querySelector(".gl-vram .gl-track i"), step: (g.querySelector(".gl-step") || {}).textContent || "" }; }''')
    pg.click("#results figure.shot:nth-child(1) .rate-btn.good")
    pg.wait_for_function('() => document.querySelector("#results figure.shot:nth-child(1) .rate-btn.good").classList.contains("on")', timeout=10000)
    pg.click("#results figure.shot:nth-child(2) .rate-btn.bad")
    pg.wait_for_function('() => document.querySelector("#results figure.shot:nth-child(2) .rate-btn.bad").classList.contains("on")', timeout=10000)
    pg.wait_for_timeout(400)
    out["rated"] = pg.evaluate('() => Array.from(document.querySelectorAll("#results figure.shot")).map(f => [f.dataset.gid, (f.querySelector(".rate-btn.on") || {}).dataset ? (f.querySelector(".rate-btn.on") || {dataset: {}}).dataset.rate || "" : ""])')
    out["toast"] = pg.evaluate('() => (document.querySelector(".toast") || {}).textContent || ""')
    out["rx_hint"] = pg.evaluate('() => document.getElementById("qualityProfileHint").innerText')
    pg.mouse.move(5, 5)
    pg.evaluate("() => window.scrollTo(0, 0)")
    pg.wait_for_timeout(2600)
    pg.screenshot(path=shots + "/ui_v130_generate.png")
    job["state"] = "done"
    pg.wait_for_function('() => !document.getElementById("go").disabled', timeout=15000)
    pg.wait_for_timeout(3500)
    out["gpu_after"] = pg.evaluate('() => document.getElementById("gpuLive").hidden')
    # boje temperature
    pg.evaluate('() => window.StudioUI130.renderGpu({gpu_usage_pct: 99, temp_c: 93, temp_status: "critical", vram_used_mb: 7900, vram_total_mb: 8176})')
    out["gpu_critical"] = pg.evaluate('() => document.querySelector("#gpuLive .gl-temp").className')

    # --- galerija: filtar Sve / Dobra / Loša ---
    pg.click("#v11GalMore") if pg.is_visible("#v11GalMore") else None
    def gal(f):
        pg.click('#v11GalChips button[data-f="%s"]' % f)
        pg.wait_for_timeout(700)
        return pg.evaluate('() => ({n: document.querySelectorAll("#v11Gallery figure.shot").length, good: document.querySelectorAll("#v11Gallery figure.rated-good").length, bad: document.querySelectorAll("#v11Gallery figure.rated-bad").length, sel: document.getElementById("v11GalFilter").value, btns: document.querySelectorAll("#v11Gallery .rate-btn").length})')
    out["gal_good"], out["gal_bad"], out["gal_all"] = gal("1"), gal("-1"), gal("")
    out["lightbox_btns"] = pg.evaluate('() => !!document.getElementById("lbGood") && !!document.getElementById("lbBad")')

    # --- Početna ---
    pg.click('.tabs button[data-tab="pregled"]')
    pg.wait_for_function('() => document.querySelectorAll("#v13HomeKpis .kpi-card").length === 4', timeout=15000)
    pg.wait_for_timeout(700)
    out["home"] = pg.evaluate('''() => ({ cards: Array.from(document.querySelectorAll("#v13HomeKpis .kpi-card")).map(c => c.querySelector(".kpi-eyebrow").textContent),
        sparks: document.querySelectorAll("#v13HomeKpis svg.kpi-spark").length, rings: document.querySelectorAll("#v13HomeKpis svg.kpi-ring").length,
        tab: document.querySelector('.tabs button[data-tab="pregled"]').textContent,
        tops: Array.from(document.querySelectorAll("#v13HomeKpis .kpi-card")).map(c => Math.round(c.getBoundingClientRect().top)) })''')
    out["ov_home"] = pg.evaluate(OVERFLOW)
    pg.evaluate("() => { window.scrollTo(0, 0); document.querySelectorAll('.toast').forEach(t => t.style.visibility = 'hidden'); }")
    pg.wait_for_timeout(300)
    pg.screenshot(path=shots + "/ui_v130_home.png")

    # --- LoRA trener ---
    pg.click('.tabs button[data-tab="influenceri"]')
    pg.wait_for_function('() => document.querySelectorAll("#personaCards .persona-card").length >= 3', timeout=15000)
    pg.click('#personaCards [data-pid="%s"] .pcard-actions [data-act="lora"]' % ids[0])
    pg.wait_for_function('() => { const r = document.getElementById("ltReady"); return r && r.textContent.trim() !== "—"; }', timeout=15000)
    pg.wait_for_timeout(800)
    out["lt"] = pg.evaluate('''() => ({ ready: document.getElementById("ltReady").textContent, readyCls: document.getElementById("ltReady").className,
        good: document.getElementById("ltGood").innerText, sync: document.getElementById("ltAutoSync").checked,
        presets: Array.from(document.querySelectorAll("#ltPresets .lt-preset b")).map(b => b.textContent),
        on: (document.querySelector("#ltPresets .lt-preset.on") || {dataset: {}}).dataset.preset, start: document.getElementById("ltStart").textContent,
        advOpen: document.getElementById("ltAdv").open, cols: new Set(Array.from(document.querySelectorAll(".lt-steps > .lt-step")).map(s => Math.round(s.getBoundingClientRect().top))).size,
        importBtn: document.getElementById("ltImportGood").textContent })''')
    pg.click('#ltPresets [data-preset="fast"]')
    pg.wait_for_timeout(300)
    out["lt_fast"] = pg.evaluate('() => (document.querySelector("#ltPresets .lt-preset.on") || {dataset: {}}).dataset.preset')
    pg.click('#ltPresets [data-preset="balanced"]')
    pg.wait_for_timeout(300)
    d = pg.evaluate('async () => (await fetch("/api/gpu-live")).json()')
    pg.evaluate('(d) => { const el = document.getElementById("ltGpu"); el.hidden = false; window.StudioUI130.renderGpu(d); document.getElementById("gpuLive").hidden = true; }', d)
    pg.evaluate('() => { const el = document.getElementById("loraTrainer"); window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 140); }')
    pg.wait_for_timeout(400)
    out["ov_lora"] = pg.evaluate(OVERFLOW)
    pg.evaluate("() => document.querySelectorAll('.toast').forEach(t => t.style.visibility = 'hidden')")
    pg.screenshot(path=shots + "/ui_v130_lora.png")

    # --- sve kartice bez prelijevanja ---
    out["tabs_1728"] = {}
    for t in ["pregled", "slike", "influenceri", "video", "kalendar", "poruke", "modeli", "postavke"]:
        pg.click('.tabs button[data-tab="%s"]' % t)
        pg.wait_for_timeout(500)
        o = pg.evaluate(OVERFLOW)
        pg.evaluate("() => window.scrollTo(0, 0)")
        pg.screenshot(path=shots + "/tabs/" + t + ".png")
        out["tabs_1728"][t] = [o["sw"] <= o["iw"], pg.evaluate('(t) => { const el = document.getElementById("tab-" + t); const r = el.getBoundingClientRect(); return Math.round(r.width); }', t)]
    ctx.close()

    # --- 1280×800 ---
    ctx2 = b.new_context(viewport={"width": 1280, "height": 800})
    pg2 = ctx2.new_page()
    pg2.on("pageerror", lambda e: out["errors"].append(str(e)))
    pg2.on("console", lambda m: out["console"].append(m.text) if m.type == "error" else None)
    pg2.goto(url)
    pg2.wait_for_function('() => !!document.getElementById("v11Sampler")', timeout=20000)
    pg2.wait_for_timeout(700)
    out["ov_1280"] = pg2.evaluate(OVERFLOW)
    out["layout_1280"] = pg2.evaluate('() => { const c = document.getElementById("form").getBoundingClientRect(), s = document.querySelector("#tab-slike .stage").getBoundingClientRect(); return {twoCol: s.left > c.right - 2, compW: c.width, stageW: s.width}; }')
    pg2.click("#tab-slike details.adv > summary")
    pg2.wait_for_timeout(400)
    out["ov_1280_adv"] = pg2.evaluate(OVERFLOW)
    out["adv_1280_cols"] = pg2.evaluate('() => new Set(Array.from(document.querySelectorAll("#tab-slike .adv-grid > .adv-group")).map(g => Math.round(g.getBoundingClientRect().left))).size')
    out["tabs_1280"] = {}
    for t in ["pregled", "slike", "influenceri", "video", "kalendar", "poruke", "modeli", "postavke"]:
        pg2.click('.tabs button[data-tab="%s"]' % t)
        pg2.wait_for_timeout(450)
        o = pg2.evaluate(OVERFLOW)
        out["tabs_1280"][t] = o["sw"] <= o["iw"]
    ctx2.close()
    b.close()
print(json.dumps(out, ensure_ascii=False))
"""


def test_ui():
    print("== Playwright UI 1.3.0 (1728×928 i 1280×800) ==")
    py = os.environ.get("PW_PYTHON") or sys.executable
    if subprocess.run([py, "-c", "import playwright"], capture_output=True).returncode != 0:
        print("  SKIP playwright nije instaliran (postavi PW_PYTHON)")
        return
    shots_env = os.environ.get("UI_V130_SHOTS", "").strip()
    with tempfile.TemporaryDirectory() as td:
        shots = shots_env or str(Path(td) / "shots")
        Path(shots).mkdir(parents=True, exist_ok=True)
        (Path(shots) / "tabs").mkdir(exist_ok=True)
        data_dir = Path(td) / "data"
        data_dir.mkdir()
        port = free_port()
        env = dict(os.environ, STUDIO_DATA_DIR=str(data_dir), STUDIO_PORT=str(port), STUDIO_NO_BROWSER="1", COMFYUI_URL="http://127.0.0.1:9",
                   STUDIO_MOCK_GPU="AMD Radeon RX 6600|8", STUDIO_GPU_USAGE="87", STUDIO_GPU_TEMP="68", STUDIO_GPU_VRAM_USED_MB="6840",
                   STUDIO_GPU_VRAM_TOTAL_MB="8176")
        for k in ("XAI_API_KEY", "OLLAMA_BASE_URL"):
            env.pop(k, None)
        proc = subprocess.Popen([sys.executable, str(ROOT / "studio.py")], cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(200):
                try:
                    http("GET", base + "/api/state")
                    break
                except Exception:
                    time.sleep(0.1)
            people = [("Luna Kovač", "26, adult woman, long auburn hair, green eyes", "26", "char_luna_v1.safetensors"),
                      ("Mia Horvat", "24, adult woman, platinum blonde bob", "24", ""),
                      ("Ivana Babić", "29, adult woman, dark straight hair", "29", "")]
            code, st = http("GET", base + "/api/profiles")
            existing = st.get("profiles") or []
            ids = []
            for i, (name, appear, age, lora) in enumerate(people):
                payload = {"name": name, "appearance_prompt": appear, "age_vibe": age}
                if lora:
                    payload.update({"preferred_lora": lora, "preferred_lora_strength": 0.8})
                if i < len(existing):
                    pid = existing[i]["id"]
                    http("PUT", base + f"/api/profiles/{pid}", payload)
                else:
                    code, r = http("POST", base + "/api/profiles", payload)
                    pid = (r.get("profile") or {}).get("id")
                ids.append(pid)
            http("POST", base + "/api/profiles/select", {"id": ids[0]})
            img_dir = data_dir / "seed_images"
            img_dir.mkdir()
            images = []
            prompts = ["morning coffee on a balcony", "city walk at golden hour", "studio portrait, soft light", "beach sunset, linen dress",
                       "cozy cafe, reading", "rooftop at dusk", "park picnic", "bookstore browsing", "gallery opening", "street style, autumn"]
            for i in range(12):
                pth = img_dir / f"seed_{i}.png"
                pth.write_bytes(portrait_png(i))
                images.append({"name": f"seed_{i}.png", "path": str(pth), "pid": ids[i % 2 if i < 10 else 0], "prompt": prompts[i % len(prompts)],
                               "seed": 1000 + i, "age_days": [0, 0, 0, 1, 1, 2, 3, 4, 6, 8, 10, 13][i]})
            spec = {"images": images, "ratings": [[0, 1], [2, 1], [4, 1], [6, 1], [3, -1], [5, -1]], "pids": ids,
                    "purchases": [[d, a] for d, a in ((0, 49.0), (0, 19.99), (1, 29.99), (1, 9.99), (2, 39.0), (3, 14.99), (4, 24.99), (5, 9.99),
                                                       (6, 19.99), (8, 12.0), (9, 9.99), (10, 7.5), (11, 9.99), (12, 5.0), (13, 4.99))]}
            r = subprocess.run([sys.executable, "-c", SEED_SCRIPT, str(ROOT), str(data_dir), json.dumps(spec)], capture_output=True, text=True, cwd=str(ROOT), timeout=120)
            check(r.returncode == 0, "seed podaci (galerija, ocjene, kupnje): " + r.stderr[-400:])
            gids = json.loads(r.stdout.strip().splitlines()[-1])["gids"] if r.returncode == 0 else []
            for k, cap in enumerate(["Nova kolekcija ☕", "Iza kulisa 📸", "Vikend u gradu"]):
                http("POST", base + "/api/posts", {"caption": cap, "channels": ["telegram"], "status": "scheduled",
                                                   "scheduled_at": time.strftime("%Y-%m-%dT%H:%M", time.localtime(time.time() + 3600 * (5 + 20 * k)))})
            exe = os.environ.get("PW_CHROME") or shutil.which("google-chrome") or shutil.which("chromium") or ""
            cfg = {"ids": [str(i) for i in ids], "gids": gids, "result_gids": gids[8:12]}
            r = subprocess.run([py, "-c", BROWSER_SCRIPT, base + "/", exe, shots, json.dumps(cfg)], capture_output=True, text=True, timeout=420)
            if r.returncode != 0:
                check(False, "browser pokrenut: " + "\n".join(l for l in r.stderr.splitlines() if "<string>" in l or "Error" in l or l.startswith("{"))[-1500:])
                return
            info = json.loads(r.stdout.strip().splitlines()[-1])
            code, ds = http("GET", base + f"/api/lora-trainer/dataset/{ids[0]}")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()

        L = info["layout"]
        check(info["ov_1728"]["sw"] <= info["ov_1728"]["iw"], f"1728: bez horizontalnog prelijevanja {info['ov_1728']}")
        check(L["wrap"]["w"] >= 1728 * 0.94, f"1728: puna širina (.wrap {L['wrap']['w']:.0f}px)")
        check(L["stage"]["l"] > L["comp"]["r"] - 2 and L["stage"]["w"] > L["comp"]["w"], "Generiranje: dva stupca (hero lijevo, rezultati desno, širi)")
        check(all(L[k]["b"] <= 928 and L[k]["t"] >= 0 for k in ("go", "prompt", "picker")), "Osoba, scena i Generiraj vidljivi bez skrolanja (1728×928)")
        check("blur" in L["blur"] and L["radius"] >= 18, f"glass kartice (blur {L['blur']!r}, radius {L['radius']})")
        check("gradient" in L["bodyBg"], "tamno-ljubičasta gradijentna pozadina")
        check(L["navPill"] not in ("0px", "") and "gradient" in L["navBg"], "plutajuća navigacija s pill aktivnim stanjem")
        check(info["adv_closed"], "Napredno zatvoreno po zadanom")
        check(info["quality_btns"] == [["realism", True], ["fast", False], ["turbo", False]], f"profili: Realizam zadan {info['quality_btns']}")
        fp = info["first_profile"]
        check(fp["s"] == "dpmpp_2m_sde" and fp["h"] is True and abs(float(fp["hs"]) - 1.33) < 1e-6 and fp["hint"], f"prvo pokretanje primijeni Realizam {fp}")
        A = info["adv"]
        check(A["n"] == 5 and sorted(A["groups"]) == ["face", "format", "lora", "misc", "model"], f"Napredno: 5 grupa {A['groups']}")
        check(A["order"] == ["model", "format", "face", "lora", "misc"], f"vizualni redoslijed Model → Format → Lice → LoRA → Prompt {A['order']}")
        check(A["cols"] >= 3, f"1728: grupe u mreži ({A['cols']} stupca)")
        check(A["compW"] >= A["wrapW"] * 0.94 and A["stageBelow"], f"otvoreno Napredno se širi na punu širinu, rezultati ispod ({A['compW']:.0f}/{A['wrapW']:.0f}, {A['stageBelow']})")
        check(A["tips"] >= 25 and A["tipsNoText"] == 0, f"? objašnjenja uz opcije ({A['tips']})")
        check("blur" in A["cardBlur"] and A["cardRadius"] >= 18, "grupe su glass pod-kartice")
        check(info["ov_adv_1728"]["sw"] <= info["ov_adv_1728"]["iw"], "otvoreno Napredno bez prelijevanja")
        check(len(info["tip_hover"]) > 30, f"hover na ? prikazuje objašnjenje ({info['tip_hover'][:50]!r})")
        check(info["tip_in_label"]["same"] and info["tip_in_label"]["shown"], "klik na ? u labeli ne mijenja kvačicu, a prikaže objašnjenje")
        check(info["tip_escape"], "Escape zatvara objašnjenje")
        T = info["turbo"]
        check(T["sampler"] == "euler" and T["sched"] == "sgm_uniform" and T["hires"] is False and T["profile"] == "turbo" and T["steps"] == 8, f"Turbo profil {T}")
        R = info["realism"]
        check(R["sampler"] == "dpmpp_2m_sde" and R["hires"] is True and abs(R["hs"] - 1.33) < 1e-6 and abs(R["hd"] - 0.35) < 1e-6 and R["hst"] == 8, f"Realizam profil {R}")
        check(R["profile"] == "realism" and R["detail"] == ["skin"] and R["guard"] is True and R["steps"] == 24 and R.get("cfg") is None,
              "genExtras: quality_profile, detail_loras, vram_guard; CFG auto")
        G = info["gpu"]
        check("87 %" in G["text"] and "68 °C" in G["text"] and "6.7 / 8.0 GB" in G["text"], f"GPU bar: opterećenje, temperatura, VRAM ({G['text']!r})")
        check("ok" in G["temp"] and G["usage"] and G["vram"], "GPU bar: boja temperature i trake")
        check("Korak 6 / 12" in G["step"], f"GPU bar: trenutni korak ({G['step']!r})")
        check(info["gpu_after"] is True, "GPU bar se skriva kad generiranje završi")
        check("critical" in info["gpu_critical"], "kritična temperatura -> coral")
        rated = dict(info["rated"])
        check(rated.get(str(cfg["result_gids"][0])) == "1" and rated.get(str(cfg["result_gids"][1])) == "-1", f"Dobra/Loša na rezultatima {info['rated']}")
        check("dobra" in info["toast"].lower() or "loša" in info["toast"].lower(), f"toast s rezultatom sinkronizacije ({info['toast']!r})")
        check("8 GB zaštita" in info["rx_hint"], "poruke 8 GB zaštite iz meta prikazane uz profil")
        gg, gb, ga = info["gal_good"], info["gal_bad"], info["gal_all"]
        check(gg["n"] >= 5 and gg["good"] == gg["n"] and gg["sel"] == "1", f"filtar Dobra ({gg})")
        check(gb["n"] >= 3 and gb["bad"] == gb["n"] and gb["sel"] == "-1", f"filtar Loša ({gb})")
        check(ga["n"] >= 12 and ga["btns"] == ga["n"] * 2 and ga["sel"] == "", f"filtar Sve + gumbi na svakoj kartici ({ga})")
        check(info["lightbox_btns"], "lightbox Dobra/Loša i dalje postoji")
        H = info["home"]
        check(H["cards"] == ["Prihodi", "Slike", "Aktivne osobe", "Zakazano"] and H["sparks"] == 2 and H["rings"] == 2, f"Početna KPI kartice {H}")
        check(len(set(H["tops"])) == 1 and H["tab"] == "Početna", "Početna: 4 kartice u redu na 1728, kartica se zove Početna")
        lt = info["lt"]
        check(lt["presets"] == ["Brzo", "Preporučeno", "Detaljno"] and lt["on"] == "balanced" and info["lt_fast"] == "fast", f"trener: pill profili {lt['presets']}")
        check("Dobra" in lt["good"] and lt["sync"] is True and lt["start"] == "Pokreni treniranje" and lt["advOpen"] is False, f"trener: Dobra brojač, auto-sync, jedan gumb ({lt['good']!r})")
        check(lt["cols"] == 1, "trener: 3 kompaktna stupca u jednom redu (1728)")
        check(lt["readyCls"].split()[-1] in {"ok", "warn", "bad"} and lt["ready"], f"trener: pill spremnosti ({lt['ready']!r})")
        check(ds.get("good_in_dataset", 0) >= 1, f"Dobra iz UI-ja je u datasetu osobe ({ds.get('good_in_dataset')})")
        for k in ("ov_home", "ov_lora"):
            check(info[k]["sw"] <= info[k]["iw"], f"{k}: bez prelijevanja")
        for t, (ok, w) in info["tabs_1728"].items():
            check(ok and w >= 1728 * 0.9, f"1728 · {t}: puna širina ({w}px), bez prelijevanja")
        check(info["ov_1280"]["sw"] <= info["ov_1280"]["iw"] and info["ov_1280_adv"]["sw"] <= info["ov_1280_adv"]["iw"], "1280: bez prelijevanja (i s otvorenim Napredno)")
        check(info["layout_1280"]["twoCol"], f"1280: dva stupca {info['layout_1280']}")
        check(info["adv_1280_cols"] >= 2, f"1280: Napredno u {info['adv_1280_cols']} stupca")
        for t, ok in info["tabs_1280"].items():
            check(ok, f"1280 · {t}: bez prelijevanja")
        check(not info["errors"], f"nema page grešaka: {info['errors'][:3]}")
        real_console = [c for c in info["console"] if "Failed to load resource" not in c]
        check(not real_console, f"nema console grešaka: {real_console[:3]}")
        for n in ("home", "generate", "advanced", "lora"):
            p = Path(shots) / f"ui_v130_{n}.png"
            check(p.is_file() and p.stat().st_size > 20000, f"snimka {p.name}")


def main():
    print("test_ui_v130")
    test_ui()
    print()
    if FAILED:
        print(f"FAILED {FAILED}")
        return 1
    print("Svi UI testovi 1.3.0 su prošli.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
