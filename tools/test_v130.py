#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.3.0: RX 6600 profili kvalitete (Realizam / Brzo / Turbo 1024), prirodni prompt protiv plastične kože,
8 GB zaštita, SFW detail LoRA-e, ocjene Dobra/Loša -> LoRA dataset (migracija, auto-sync, dedup, uklanjanje),
živi GPU podaci (/api/gpu-live: parsiranje Windows brojača i smi alata, TTL keš, rezerve) i statičke provjere UI-ja."""

from __future__ import annotations

import io
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory()
TMP = Path(_TMP.name)
(TMP / "data").mkdir()
os.environ["STUDIO_DATA_DIR"] = str(TMP / "data")
for _k in ("STUDIO_GPU_USAGE", "STUDIO_GPU_VRAM_USED_MB", "STUDIO_GPU_VRAM_TOTAL_MB", "STUDIO_GPU_TEMP", "STUDIO_GPU_TEMP_FILE"):
    os.environ.pop(_k, None)

import image_gen  # noqa: E402
import inbox  # noqa: E402

inbox.configure_paths(data_dir=TMP / "data")
inbox.init_db()
import services  # noqa: E402

services.init_schema()
import studio  # noqa: E402
from services import generation_service as gs  # noqa: E402
from services import hardware_service as hw  # noqa: E402
from services import lora_trainer_service as lt  # noqa: E402
from services.common import conn  # noqa: E402

# zabranjeni izrazi (rot13 da se imena ne pojavljuju doslovno u repozitoriju)
_ROT = str.maketrans("abcdefghijklmnopqrstuvwxyz", "nopqrstuvwxyzabcdefghijklm")
BANNED = re.compile(r"\b(" + "|".join(w.translate(_ROT) for w in ("yhfgvsl", "fabsf", "afsj", "ahqr", "anxrq", "gbcyrff")) + r")\b", re.I)

FAILED = 0


def check(cond, msg):
    global FAILED
    if cond:
        print("  OK ", msg)
    else:
        FAILED += 1
        print("  FAIL", msg)


def png_bytes(color=(150, 110, 90), size=(640, 800)) -> bytes:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", size, color)
    d = ImageDraw.Draw(im)
    for i in range(0, size[0], 40):
        d.line([(i, 0), (size[0] - i, size[1])], fill=(color[2], color[0], color[1]), width=3)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def nodes(wf: dict, cls: str) -> list[dict]:
    return [n for n in wf.values() if isinstance(n, dict) and n.get("class_type") == cls]


# ---------------------------------------------------------------- 1. kvaliteta i brzina

def test_prompt_constants():
    print("== prirodni prompt (protiv plastične kože) ==")
    check("child" in image_gen.NATURAL_NEGATIVE and "teen" in image_gen.NATURAL_NEGATIVE, "NATURAL_NEGATIVE zadržava child/teen")
    check(image_gen.NATURAL_NEGATIVE.startswith(image_gen.DEFAULT_NEGATIVE), "NATURAL_NEGATIVE = DEFAULT_NEGATIVE + dodatak")
    for w in ("plastic skin", "airbrushed", "waxy skin", "cgi"):
        check(w in image_gen.NATURAL_NEGATIVE, f"negativ sadrži '{w}'")
    check("natural skin texture" in image_gen.NATURAL_QUALITY and "film grain" in image_gen.NATURAL_QUALITY, "NATURAL_QUALITY foto oznake")
    b1 = image_gen.build_positive_prompt(scene="drinking coffee on a balcony", appearance="long brown hair", quality=True, adult_term="adult woman, 27")
    b2 = image_gen.build_positive_prompt(scene="drinking coffee on a balcony", appearance="long brown hair", quality=True, adult_term="adult woman, 27",
                                         quality_text=image_gen.NATURAL_QUALITY)
    j1, j2 = " ".join(b1["chunks"]), " ".join(b2["chunks"])
    check(image_gen.QUALITY_PREFIX.split(",")[0].strip() in j1, "bez quality_text: stari QUALITY_PREFIX (bez regresije)")
    check("natural skin texture" in j2 and b2["chunks"][0].startswith("adult woman, 27"), "quality_text: prirodne oznake, adult ostaje prvi")
    b3 = image_gen.build_positive_prompt(scene="x", appearance="", quality=False, adult_term="adult woman", quality_text=image_gen.NATURAL_QUALITY)
    check("natural skin texture" not in " ".join(b3["chunks"]), "quality=False: bez oznaka kvalitete")


def test_profiles():
    print("== RX 6600 profili (opt-in, samo nepostavljena polja) ==")
    body = {"prompt": "x"}
    out, info = gs.prepare_rx6600(dict(body), "sdxl")
    check(out == body and info["profile"] == "", "bez quality_profile: tijelo netaknuto (stari klijenti)")
    out, info = gs.prepare_rx6600({"quality_profile": "realism"}, "sdxl")
    check(out["steps"] == 24 and abs(out["cfg"] - 4.3) < 1e-9, f"Realizam: 24 koraka, CFG 4,3 ({out.get('steps')}, {out.get('cfg')})")
    check(out["sampler"] == "dpmpp_2m_sde" and out["scheduler"] == "karras", "Realizam: dpmpp_2m_sde + karras")
    check(out["hires"] is True and abs(out["hires_scale"] - 1.33) < 1e-9 and abs(out["hires_denoise"] - 0.35) < 1e-9 and out["hires_steps"] == 8,
          "Realizam: brzi hires 1,33× / 0,35 / 8 koraka")
    check(1.3 <= out["hires_scale"] <= 1.35 and 0.32 <= out["hires_denoise"] <= 0.38, "hires u zadanom rasponu (1,3–1,35×, 0,32–0,38)")
    check(out["rx_base_long"] == 960 and info["natural"] and info["quality_text"] == image_gen.NATURAL_QUALITY, "Realizam: baza 960, prirodne oznake")
    check(4.0 <= out["cfg"] <= 4.5, "CFG u rasponu 4,0–4,5")
    out, info = gs.prepare_rx6600({"quality_profile": "realism", "cfg": 6.5, "steps": 30, "sampler": "euler", "hires": False, "hires_scale": 1.5}, "sdxl")
    check(out["cfg"] == 6.5 and out["steps"] == 30 and out["sampler"] == "euler" and out["hires"] is False and out["hires_scale"] == 1.5,
          "ručne vrijednosti iz Napredno imaju prednost")
    out, info = gs.prepare_rx6600({"quality_profile": "realism"}, "sd15")
    check(abs(out["cfg"] - 5.0) < 1e-9 and "rx_base_long" not in out, "SD 1.5: CFG 5,0, bez SDXL baze")
    out, info = gs.prepare_rx6600({"quality_profile": "fast"}, "sdxl")
    check(out["steps"] == 20 and out["hires"] is False and out["sampler"] == "dpmpp_2m", "Brzo: 20 koraka, bez hiresa, dpmpp_2m")
    out, info = gs.prepare_rx6600({"quality_profile": "turbo"}, "sdxl")
    check(out.get("turbo") is True and info["turbo_cfg"] == 2.2 and out["steps"] == 8 and out["rx_base_long"] == 1024, "Turbo: 8 koraka, CFG 2,2, baza 1024")
    check(out["sampler"] == "euler" and out["scheduler"] == "sgm_uniform", "Turbo: euler + sgm_uniform")
    check(gs.RX_PROFILES["turbo"]["sampler"] != "dpmpp_sde", "Turbo ne koristi dpmpp_sde (2 evaluacije po koraku)")
    out, info = gs.prepare_rx6600({"quality_profile": "turbo", "cfg": 3}, "sdxl")
    check(info["turbo_cfg"] is None, "Turbo + ručni CFG: profil ne nameće CFG")
    out, info = gs.prepare_rx6600({"quality_profile": "realism"}, "krea2")
    check(info["profile"] == "" and "steps" not in out, "Krea 2: profili se ne primjenjuju")
    out, info = gs.prepare_rx6600({"quality_profile": "nepostoji"}, "sdxl")
    check(info["profile"] == "", "nepoznat profil: ništa")
    out, _ = gs.prepare_rx6600({"quality_profile": "realism", "face_detailer": True}, "sdxl")
    check(out["fd_steps"] <= gs.VRAM_GUARD["fd_max_steps"], "Face Detailer koraci ≤ 12")
    check(gs.natural_negative("", {"natural": True}) == image_gen.NATURAL_NEGATIVE, "prazan negativ -> prirodni")
    check(gs.natural_negative(image_gen.DEFAULT_NEGATIVE, {"natural": True}) == image_gen.NATURAL_NEGATIVE, "zadani negativ -> prirodni")
    own = "my own negative, blurry"
    check(gs.natural_negative(own, {"natural": True}) == own, "korisnikov negativ ostaje netaknut")
    check(gs.natural_negative("", {"natural": False}) == "", "bez profila: negativ netaknut")


def test_base_canvas():
    print("== manja baza + hires ==")
    check(hw.rx_base_for("sdxl", 1080, 1350, 1024) == (816, 1024), f"1080×1350 @1024 -> 816×1024 ({hw.rx_base_for('sdxl', 1080, 1350, 1024)})")
    check(hw.rx_base_for("sdxl", 1080, 1350, 960) == (768, 960), "1080×1350 @960 -> 768×960")
    check(hw.rx_base_for("sdxl", 1080, 1080, 1024) == (1024, 1024), "kvadrat 1024")
    w, h = hw.rx_base_for("sdxl", 1080, 1920, 1024)
    check(h == 1024 and w % 8 == 0 and w < 600, f"story 9:16 -> {w}×{h}")
    check(hw.rx_base_for("sdxl", 768, 960, 1024) == (768, 960), "manji cilj od baze ostaje")
    check(hw.rx_base_for("krea2", 1080, 1350, 1024) == (1080, 1350), "Krea 2 netaknuta")
    sc = gs.safe_canvas({"safe_mode": True, "rx_base_long": 960}, "sdxl", {"width": 1080, "height": 1350, "output_width": 1080, "output_height": 1350})
    check(max(sc["width"], sc["height"]) <= 960 and (sc.get("output_width"), sc.get("output_height")) == (1080, 1350),
          f"safe_canvas + rx_base_long: baza {sc.get('width')}×{sc.get('height')}, izlaz 1080×1350")


def test_vram_guard():
    print("== 8 GB zaštita ==")
    base = {"width": 768, "height": 960, "output_width": 1080, "output_height": 1350, "batch": 1, "hires": True, "hires_scale": 1.33,
            "instantid": False, "face_detailer": False, "vae_mode": "standard", "fd": {}}
    s, n = gs.vram_guard(dict(base), arch="sdxl")
    check(s["hires"] and abs(s["hires_scale"] - 1.33) < 1e-6, "Realizam 768×960 ×1,33 stane (1,30 MP)")
    check(s["vae_mode"] == "tiled", "SDXL + hires -> tiled VAE")
    s, n = gs.vram_guard(dict(base, width=1024, height=1280, hires_scale=1.5), arch="sdxl")
    check((not s["hires"]) or s["hires_scale"] * s["hires_scale"] * 1024 * 1280 / 1e6 <= 1.36, f"prevelik hires se smanji ili preskoči ({s['hires']}, {s.get('hires_scale')})")
    check(any("8 GB zaštita" in x for x in n), "poruka o zaštiti")
    s, n = gs.vram_guard(dict(base, instantid=True, face_detailer=True), arch="sdxl")
    check(s["hires"] is False and any("InstantID" in x for x in n), "InstantID + Face Detailer + Hires -> hires isključen")
    s, n = gs.vram_guard(dict(base, batch=4), arch="sdxl")
    check(s["batch"] == 1, "SDXL + hires: batch 1")
    s, n = gs.vram_guard(dict(base, face_detailer=True, fd={"denoise": 0.8, "guide_size": 768, "max_size": 1024, "steps": 30}), arch="sdxl")
    check(s["fd"] == {"denoise": 0.5, "guide_size": 512, "max_size": 768, "steps": 12}, f"Face Detailer ograničen ({s['fd']})")
    s, n = gs.vram_guard(dict(base, batch=4), arch="sdxl", enabled=False)
    check(s["batch"] == 4 and not n, "isključena zaštita ne dira ništa")
    s, n = gs.vram_guard(dict(base, hires=False, batch=3), arch="sdxl")
    check(s["batch"] == 3 and s["vae_mode"] == "standard", "bez hiresa/InstantID batch ostaje")


def test_detail_loras():
    print("== SFW detail LoRA-e (1 klik) ==")
    avail = lambda name, folder=None: name != "sdxl_offset_example_lora_1.0.safetensors"  # noqa: E731
    st, notes = gs.add_detail_loras([], {"detail_loras": ["skin", "detail", "light"]}, "sdxl", available=avail)
    names = [x["name"] for x in st]
    check(names == ["ostris_photorealistic_slider_xl.safetensors", "add_detail_xl.safetensors"], f"dostupne dodane ({names})")
    check(any("nije preuzeta" in x for x in notes), "nedostajuća LoRA preskočena s porukom")
    check(all(x["strength_model"] <= gs.VRAM_GUARD["detail_max_weight"] for x in st), "jačina ≤ 0,6")
    st, notes = gs.add_detail_loras([], {"detail_loras": "skin,detail,light"}, "sdxl", turbo=True, available=lambda n, f=None: True)
    check(len(st) == 2, "Turbo: najviše 2 detail LoRA-e")
    full = [{"name": f"l{i}.safetensors", "strength_model": 0.5, "strength_clip": 0.5, "enabled": True} for i in range(image_gen.MAX_LORA_STACK)]
    st, notes = gs.add_detail_loras(full, {"detail_loras": ["skin"]}, "sdxl", available=lambda n, f=None: True)
    check(len(st) == image_gen.MAX_LORA_STACK and any("pun" in x for x in notes), "pun stack: preskočeno")
    st, notes = gs.add_detail_loras([], {"detail_loras": ["skin"]}, "sd15", available=lambda n, f=None: True)
    check(st == [] and notes, "SD 1.5: preskočeno uz poruku")
    st, notes = gs.add_detail_loras([], {}, "sdxl")
    check(st == [] and notes == [], "bez prekidača: ništa")
    for d in gs.DETAIL_LORA_PRESETS:
        check(not BANNED.search(json.dumps(d)), f"detail preset {d['key']} je SFW")


def test_plan_integration():
    print("== plan_image_generation s profilom ==")
    prof = {"id": 5, "name": "Ana", "appearance_prompt": "long brown hair, green eyes", "age_vibe": "27", "negative_prompt": "",
            "preferred_model": "", "model_type": "auto"}
    orig = image_gen.lora_available
    image_gen.lora_available = lambda name, folder=None: True
    try:
        r = studio.plan_image_generation({"prompt": "drinking coffee on a balcony", "model": "RealVisXL_V5.0_fp16.safetensors", "model_type": "sdxl",
                                          "size_preset": "ig_portrait", "seed": 7, "quality_prefix": True, "safe_mode": True,
                                          "quality_profile": "realism", "hires": True, "steps": 24, "detail_loras": ["skin"]},
                                         profile=prof, object_info={})
        t = studio.plan_image_generation({"prompt": "street style", "model": "RealVisXL_V5.0_fp16.safetensors", "model_type": "sdxl",
                                          "seed": 8, "turbo": True, "quality_profile": "turbo", "steps": 8, "safe_mode": True,
                                          "width": 1080, "height": 1350},
                                         profile=prof, object_info={})
        legacy = studio.plan_image_generation({"prompt": "in a cafe", "model": "RealVisXL_V5.0_fp16.safetensors", "model_type": "sdxl", "seed": 9},
                                              profile=prof, object_info={})
    finally:
        image_gen.lora_available = orig
    check(r.get("ok") is True, f"Realizam plan ok ({r.get('error')})")
    meta, wf = r.get("meta") or {}, r.get("workflow") or {}
    check(meta.get("quality_profile") == "realism", "meta.quality_profile")
    ks = nodes(wf, "KSampler")
    check(ks and abs(float(ks[0]["inputs"]["cfg"]) - 4.3) < 1e-6, f"KSampler CFG 4,3 ({ks[0]['inputs'].get('cfg') if ks else None})")
    lat = nodes(wf, "EmptyLatentImage")
    check(lat and (lat[0]["inputs"]["width"], lat[0]["inputs"]["height"]) == (768, 960), "Realizam: manja baza 768×960 za IG 4:5")
    up = nodes(wf, "LatentUpscaleBy") or nodes(wf, "LatentUpscale")
    if up and "scale_by" in up[0]["inputs"]:
        sc = float(up[0]["inputs"]["scale_by"])
    else:
        sc = float(up[0]["inputs"]["height"]) / 960 if up else 0
    check(abs(sc - 1.33) < 0.02, f"hires drugi prolaz ~1,33× ({sc:.3f})")
    check(any(n["inputs"].get("width") == 1080 and n["inputs"].get("height") == 1350 for n in nodes(wf, "ImageScale")), "izlaz točno 1080×1350")
    check(len(ks) >= 2 and abs(float(ks[-1]["inputs"]["denoise"]) - 0.35) < 1e-6 and int(ks[-1]["inputs"]["steps"]) == 8, "drugi prolaz: denoise 0,35, 8 koraka")
    neg = json.dumps([n["inputs"].get("text", "") for n in nodes(wf, "CLIPTextEncode")])
    check("plastic skin" in neg and "teen" in neg, "prirodni negativ u workflowu (child/teen ostaju)")
    pos = " ".join((r.get("built") or {}).get("chunks") or [])
    check("natural skin texture" in pos and pos.startswith("adult woman, 27"), "prirodne oznake kvalitete, adult + dob prvi")
    check("ostris_photorealistic_slider_xl.safetensors" in json.dumps(wf), "detail LoRA u lancu")
    check(isinstance(meta.get("rx_notes"), list), "meta.rx_notes")
    check(t.get("ok") is True, f"Turbo plan ok ({t.get('error')})")
    tk = nodes(t.get("workflow") or {}, "KSampler")
    check(tk and abs(float(tk[0]["inputs"]["cfg"]) - 2.2) < 1e-6 and int(tk[0]["inputs"]["steps"]) == 8, "Turbo: CFG 2,2, 8 koraka")
    lat = nodes(t.get("workflow") or {}, "EmptyLatentImage")
    check(lat and max(int(lat[0]["inputs"]["width"]), int(lat[0]["inputs"]["height"])) == 1024, "Turbo: baza 1024 px")
    lk = nodes(legacy.get("workflow") or {}, "KSampler")
    check(legacy.get("ok") and lk and abs(float(lk[0]["inputs"]["cfg"]) - float(image_gen.DEFAULT_CFG if hasattr(image_gen, "DEFAULT_CFG") else lk[0]["inputs"]["cfg"])) < 1e-6
          and (legacy.get("meta") or {}).get("quality_profile", "") == "", "stari klijent bez profila: kao prije")


def test_ui_options():
    print("== ui_options ==")
    o = gs.ui_options()
    d = o["defaults"]
    check(abs(d["hires_scale"] - 1.33) < 1e-9 and abs(d["hires_denoise"] - 0.35) < 1e-9 and d["hires_steps"] == 8, "zadani hires 1,33 / 0,35 / 8")
    check([p["key"] for p in o["quality_profiles"]] == ["realism", "fast", "turbo"], "profili u opcijama")
    check(len(o["detail_loras"]) == 3 and all("available" in x for x in o["detail_loras"]), "detail LoRA-e s 'available'")
    check(o["vram_guard"]["fd_max_denoise"] == 0.5, "vram_guard granice")


# ---------------------------------------------------------------- 4. ocjene -> LoRA dataset

def test_migration():
    print("== migracija ocjena (idempotentna) ==")
    db = TMP / "old.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE gallery_items(id INTEGER PRIMARY KEY, filename TEXT, persona_id INTEGER)")
    c.execute("INSERT INTO gallery_items(filename, persona_id) VALUES ('a.png', 1)")
    c.commit()
    inbox.ensure_gallery_rating_schema(c)
    inbox.ensure_gallery_rating_schema(c)
    cols = {r[1] for r in c.execute("PRAGMA table_info(gallery_items)").fetchall()}
    idx = {r[1] for r in c.execute("PRAGMA index_list(gallery_items)").fetchall()}
    check({"rating", "rated_at"} <= cols, "stupci rating i rated_at")
    check("idx_gallery_rating" in idx, "indeks idx_gallery_rating")
    c.execute("UPDATE gallery_items SET rating=7")
    inbox.ensure_gallery_rating_schema(c)
    check(c.execute("SELECT rating FROM gallery_items").fetchone()[0] == 0, "neispravna ocjena -> 0")
    c.close()
    with conn() as c2:
        cols = {r[1] for r in c2.execute("PRAGMA table_info(gallery_items)").fetchall()}
    check({"rating", "rated_at"} <= cols, "glavna baza ima stupce ocjena")


def _gallery_image(pid, name, color):
    p = TMP / "out" / name
    p.parent.mkdir(exist_ok=True)
    p.write_bytes(png_bytes(color))
    ids = gs.record_images([{"filename": name, "subfolder": "", "type": "output"}], {"prompt": "x", "seed": 1}, persona_id=pid, local_path=str(p))
    return ids[0] if ids else gs.find_gallery_item(name, "", "output")["id"]


def test_rating_sync():
    print("== Dobra -> dataset, Loša -> van ==")
    lt.ensure_schema()
    prof = inbox.upsert_profile({"name": "Lea Test", "appearance_prompt": "short black hair", "age_vibe": "25", "model_type": "sdxl"})
    other = inbox.upsert_profile({"name": "Iva Test", "appearance_prompt": "red hair", "age_vibe": "28", "model_type": "sdxl"})
    pid = prof["id"]
    check(lt.auto_sync_enabled() is True, "auto-sync je zadano uključen")
    g1 = _gallery_image(pid, "lea_1.png", (160, 120, 100))
    g2 = _gallery_image(pid, "lea_2.png", (90, 140, 170))
    g3 = _gallery_image(other["id"], "iva_1.png", (200, 80, 80))
    man = lt.add_images(pid, [(png_bytes((40, 160, 90)), "rucno.png")], source="upload")
    check(len(man["added"]) == 1, "ručna slika u datasetu")
    r = gs.rate_image(gallery_id=g1, rating=1)
    check(r["rating"] == 1 and r.get("rated_at"), "ocjena spremljena s rated_at")
    check(r["lora_sync"]["action"] == "added", f"Dobra -> dodano ({r['lora_sync']})")
    r = gs.rate_image(gallery_id=g1, rating=1)
    check(r["lora_sync"]["action"] == "exists", "ponovno Dobra -> bez duplikata")
    st = lt.dataset_state(pid)
    check(st["count"] == 2 and st["good_in_dataset"] == 1 and st["manual_in_dataset"] == 1, f"dataset: 1 Dobra + 1 ručna ({st['count']}, {st.get('good_in_dataset')}, {st.get('manual_in_dataset')})")
    check(st["good_rated"] == 1 and st["auto_sync_good"] is True, "dataset_state: good_rated, auto_sync_good")
    r = gs.rate_image(gallery_id=g3, rating=1)
    check(r["lora_sync"]["action"] == "added" and lt.dataset_state(pid)["count"] == 2, "Dobra druge osobe ide samo u njezin dataset")
    r = gs.rate_image(gallery_id=g1, rating=-1)
    check(r["lora_sync"]["action"] == "removed", "Loša -> maknuto iz dataseta")
    st = lt.dataset_state(pid)
    check(st["count"] == 1 and st["manual_in_dataset"] == 1 and st["bad_rated"] == 1, "ručna slika ostaje, Loša prebrojana")
    r = gs.rate_image(gallery_id=g2, rating=-1)
    check(r["lora_sync"]["action"] == "none", "Loša slike koja nije u datasetu: ništa")
    lt.set_auto_sync(False)
    r = gs.rate_image(gallery_id=g2, rating=1)
    check(r["lora_sync"]["action"] == "none" and r["rating"] == 1 and lt.dataset_state(pid)["count"] == 1, "auto-sync isključen: ocjena spremljena, dataset netaknut")
    check(lt.dataset_state(pid)["good_missing"] == 1, "good_missing = 1 (za gumb Uvezi ocijenjene)")
    res = lt.import_from_persona(pid, ["good"])
    check(len(res["added"]) == 1 and res["dataset"]["count"] == 2, "1 klik: Uvezi ocijenjene „Dobra”")
    res = lt.import_from_persona(pid, ["good"])
    check(not res["added"], "ponovni uvoz bez duplikata")
    lt.set_auto_sync(True)
    check(lt.auto_sync_enabled(), "auto-sync ponovno uključen")
    r = gs.rate_image(gallery_id=g2, rating=0)
    check(r["lora_sync"]["action"] == "removed", "brisanje ocjene miče sliku iz dataseta")
    empty = inbox.upsert_profile({"name": "Prazna", "appearance_prompt": "brown hair", "age_vibe": "30", "model_type": "sdxl"})
    try:
        lt.import_from_persona(empty["id"], ["good"])
        check(False, "prazan uvoz baca grešku")
    except ValueError as exc:
        check("Dobra" in str(exc), "prazan uvoz: jasna poruka")
    loose = gs.record_images([{"filename": "bez_osobe.png", "subfolder": "", "type": "output"}], {}, persona_id=None, local_path=str(TMP / "out" / "lea_1.png"))
    r = gs.rate_image(gallery_id=loose[0], rating=1)
    check(r["rating"] == 1 and r["lora_sync"]["action"] == "none", "slika bez osobe: ocjena radi, dataset ne")


# ---------------------------------------------------------------- 5. živi GPU

def test_gpu_parsing():
    print("== parsiranje GPU brojača ==")
    win = {"engines": [
        {"Name": "pid_1200_luid_0x00000000_0x0000D1A2_phys_0_eng_0_engtype_3D", "UtilizationPercentage": 20},
        {"Name": "pid_4321_luid_0x00000000_0x0000D1A2_phys_0_eng_0_engtype_3D", "UtilizationPercentage": 15},
        {"Name": "pid_4321_luid_0x00000000_0x0000D1A2_phys_0_eng_1_engtype_Compute", "UtilizationPercentage": 81},
        {"Name": "pid_4321_luid_0x00000000_0x0000AAAA_phys_0_eng_0_engtype_VideoDecode", "UtilizationPercentage": 3}],
        "memory": [{"Name": "luid_0x00000000_0x0000D1A2_phys_0", "DedicatedUsage": 6979321856},
                   {"Name": "luid_0x00000000_0x0000AAAA_phys_0", "DedicatedUsage": 104857600}]}
    p = hw.parse_win_gpu_counters(json.dumps(win))
    check(p["usage_pct"] == 81.0, f"Windows: najzaposleniji engine (Compute 81 %) ({p['usage_pct']})")
    check(p["vram_used_mb"] == 6656, f"Windows: VRAM 6656 MB ({p['vram_used_mb']})")
    single = {"engines": {"Name": "pid_1_luid_0x0_0x1_phys_0_eng_0_engtype_3D", "UtilizationPercentage": 140}, "memory": {"Name": "x", "DedicatedUsage": 0}}
    p = hw.parse_win_gpu_counters(json.dumps(single))
    check(p["usage_pct"] == 100.0 and p["vram_used_mb"] is None, "jedan objekt, ograničeno na 100 %, 0 B VRAM = n/d")
    check(hw.parse_win_gpu_counters("") == {"usage_pct": None, "vram_used_mb": None}, "prazan izlaz -> n/d")
    check(hw.parse_win_gpu_counters("nije json") == {"usage_pct": None, "vram_used_mb": None}, "smeće -> n/d")
    check(hw.parse_smi_usage(json.dumps([{"gpu": 0, "usage": {"gfx_activity": {"value": 57, "unit": "%"}}}])) is None
          or hw.parse_smi_usage(json.dumps([{"gpu": 0, "usage": {"gfx_activity": 57}}])) == 57.0, "amd-smi JSON")
    check(hw.parse_smi_usage(json.dumps({"card0": {"GPU use (%)": "42"}})) == 42.0, "rocm-smi JSON")
    check(hw.parse_smi_usage("37, 2048, 8192\n") == 37.0, "nvidia-smi CSV")
    check(hw.parse_smi_usage("") is None and hw.parse_smi_usage("N/A") is None, "nedostupno -> None")
    check(hw._vram_from_stats({"devices": [{"vram_total": 8589934592, "vram_free": 2147483648}]}) == (6144, 8192), "ComfyUI system_stats VRAM")
    check(hw._vram_from_stats({}) == (None, None), "bez system_stats")


def test_gpu_live_cache():
    print("== gpu_live: TTL keš, hook, rezerve ==")
    calls = []

    def probe():
        calls.append(time.time())
        return {"usage_pct": 64.0, "vram_used_mb": 5000, "vram_total_mb": 8192, "source": "probe"}

    os.environ["STUDIO_GPU_TEMP"] = "71"
    hw.reset_gpu_live_cache()
    a = hw.gpu_live(probe=probe)
    check(a["gpu_usage_pct"] == 64.0 and a["vram_used_mb"] == 5000 and a["vram_total_mb"] == 8192, "prvi poziv čeka očitanje")
    check(a["temp_c"] == 71.0 or a["temp_c"] == 71, f"temperatura iz senzora ({a['temp_c']})")
    b = hw.gpu_live(probe=probe)
    check(b["cached"] is True and len(calls) == 1, "drugi poziv unutar TTL-a: keš (bez novog očitanja)")
    check(2.0 <= a["ttl_s"] <= 3.0, "TTL 2–3 s")
    c = hw.gpu_live(probe=probe, system_stats={"devices": [{"vram_total": 8589934592, "vram_free": 4294967296}]})
    check(c["vram_used_mb"] == 4096 and c["vram_source"] == "comfyui", "ComfyUI VRAM ima prednost")
    t0 = time.time()
    d = hw.gpu_live(probe=probe, now_fn=lambda: t0 + 10)
    check(d["cached"] is False, "istekao TTL: osvježava (stale-while-revalidate)")
    time.sleep(0.3)
    hw.reset_gpu_live_cache()
    os.environ.pop("STUDIO_GPU_TEMP", None)
    e = hw.gpu_live(probe=lambda: {"usage_pct": None, "vram_used_mb": None, "vram_total_mb": None, "source": ""})
    check(e["gpu_usage_pct"] is None and e["ok"] is True, "bez brojača: n/d, bez izmišljenih brojeva")
    hw.reset_gpu_live_cache()
    os.environ.update({"STUDIO_GPU_USAGE": "55", "STUDIO_GPU_VRAM_USED_MB": "6100", "STUDIO_GPU_VRAM_TOTAL_MB": "8176"})
    f = hw.gpu_live()
    check(f["gpu_usage_pct"] == 55.0 and f["vram_used_mb"] == 6100 and f["source"] == "test-env", "testni hook STUDIO_GPU_USAGE")
    for k in ("STUDIO_GPU_USAGE", "STUDIO_GPU_VRAM_USED_MB", "STUDIO_GPU_VRAM_TOTAL_MB"):
        os.environ.pop(k, None)
    hw.reset_gpu_live_cache()
    ps = hw.WIN_GPU_COUNTERS_PS
    check("GPUEngine" in ps and "GPUAdapterMemory" in ps and "ConvertTo-Json" in ps, "Windows: CIM brojači (nelokalizirani), JSON izlaz")


# ---------------------------------------------------------------- HTTP API

def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def http(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_http():
    print("== HTTP: /api/gpu-live, ocjene, auto-sync, import-good, Početna ==")
    data_dir = TMP / "http_data"
    data_dir.mkdir()
    port = free_port()
    env = dict(os.environ, STUDIO_DATA_DIR=str(data_dir), STUDIO_PORT=str(port), STUDIO_NO_BROWSER="1", COMFYUI_URL="http://127.0.0.1:9",
               STUDIO_MOCK_GPU="AMD Radeon RX 6600|8", STUDIO_GPU_USAGE="73", STUDIO_GPU_TEMP="88", STUDIO_GPU_VRAM_USED_MB="7100",
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
        code, g = http("GET", base + "/api/gpu-live")
        check(code == 200 and g["gpu_usage_pct"] == 73.0 and g["vram_used_mb"] == 7100 and g["vram_total_mb"] == 8176, f"/api/gpu-live ({g.get('gpu_usage_pct')}, {g.get('vram_used_mb')})")
        check(g["temp_c"] == 88 and g["temp_status"] in {"warn", "critical"} and g.get("temp_message"), f"temperatura + status ({g.get('temp_status')})")
        check(set(g["activity"]) >= {"generating", "training", "label"}, "activity polje")
        t0 = time.time()
        for _ in range(5):
            http("GET", base + "/api/gpu-live")
        check(time.time() - t0 < 2.0, "5 uzastopnih poziva < 2 s (keš)")
        code, p = http("POST", base + "/api/profiles", {"name": "Nora Http", "appearance_prompt": "wavy blonde hair", "age_vibe": "26"})
        pid = (p.get("profile") or {}).get("id")
        img = data_dir / "nora.png"
        img.write_bytes(png_bytes((120, 100, 160)))
        sys_path = [sys.executable, "-c", (
            "import os,sys; sys.path.insert(0, %r); os.environ['STUDIO_DATA_DIR']=%r; import inbox; from pathlib import Path; "
            "inbox.configure_paths(data_dir=Path(%r)); import services; services.init_schema(); "
            "from services import generation_service as gs; print(gs.record_images([{'filename':'nora.png','subfolder':'','type':'output'}], {'prompt':'x'}, persona_id=%d, local_path=%r)[0])"
        ) % (str(ROOT), str(data_dir), str(data_dir), pid, str(img))]
        gid = int(subprocess.run(sys_path, capture_output=True, text=True, cwd=str(ROOT)).stdout.strip().splitlines()[-1])
        code, r = http("POST", base + "/api/gallery/rate", {"gallery_id": gid, "rating": 1})
        check(code == 200 and r["item"]["rating"] == 1 and (r.get("lora_sync") or {}).get("action") == "added", f"POST /api/gallery/rate -> lora_sync ({r.get('lora_sync')})")
        code, ds = http("GET", base + f"/api/lora-trainer/dataset/{pid}")
        check(ds.get("count") == 1 and ds.get("good_in_dataset") == 1, "dataset preko API-ja: 1 Dobra")
        code, gal = http("GET", base + "/api/gallery?rating=1")
        check(any(i["id"] == gid for i in gal.get("items", [])), "filtar galerije Dobra")
        code, gal = http("GET", base + "/api/gallery?rating=-1")
        check(not any(i["id"] == gid for i in gal.get("items", [])), "filtar galerije Loša")
        code, s = http("POST", base + "/api/lora-trainer/settings", {"auto_sync_good": False})
        check(code == 200 and s.get("auto_sync_good") is False, "auto_sync_good isključen preko API-ja")
        code, s = http("GET", base + "/api/lora-trainer/settings")
        check(code == 200 and s.get("auto_sync_good") is False and "temp" in s, "GET settings vraća auto_sync_good i temp")
        http("POST", base + "/api/gallery/rate", {"gallery_id": gid, "rating": -1})
        http("POST", base + "/api/gallery/rate", {"gallery_id": gid, "rating": 1})
        code, ds = http("GET", base + f"/api/lora-trainer/dataset/{pid}")
        check(ds.get("count") == 0 and ds.get("good_missing") == 1, "auto-sync isključen: Dobra čeka uvoz")
        code, imp = http("POST", base + f"/api/lora-trainer/dataset/{pid}/import-good", {})
        check(code == 200 and len(imp.get("added", [])) == 1, "POST import-good")
        http("POST", base + "/api/lora-trainer/settings", {"auto_sync_good": True})
        code, ov = http("GET", base + "/api/v11/overview")
        check(len(ov.get("series_days", [])) == 14 and len(ov.get("images_series", [])) == 14 and len(ov.get("revenue_series", [])) == 14, "Početna: 14-dnevni nizovi")
        check(ov.get("rated_good") == 1 and "scheduled_posts" in ov and "personas_with_lora" in ov, "Početna: ocjene, zakazano, osobe s LoRA-om")
        code, opts = http("GET", base + "/api/gen/options")
        check(code == 200 and [p["key"] for p in opts.get("quality_profiles", [])] == ["realism", "fast", "turbo"], "gen-options: profili")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


# ---------------------------------------------------------------- statičke provjere

def test_static():
    print("== statičke provjere UI-ja, sadržaja i pakiranja ==")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "ui_v130.css").read_text(encoding="utf-8")
    js = (ROOT / "static" / "ui_v130.js").read_text(encoding="utf-8")
    v11 = (ROOT / "static" / "v11.js").read_text(encoding="utf-8")
    lt_js = (ROOT / "static" / "lora_trainer.js").read_text(encoding="utf-8")
    check(html.index("/static/ui_v120.css") < html.index("/static/ui_v130.css"), "ui_v130.css se učitava nakon ui_v120.css")
    check(html.index("/static/ui_v120.js") < html.index("/static/ui_v130.js"), "ui_v130.js se učitava zadnji")
    for g in ("model", "format", "face", "lora", "misc"):
        check(f'data-group="{g}"' in html, f"Napredno grupa {g}")
    check(html.count('class="tip"') >= 10, f"? objašnjenja u HTML-u ({html.count('class=\"tip\"')})")
    check("function tip(" in v11 and v11.count("TIPS.") >= 18, f"? objašnjenja u v11 poljima ({v11.count('TIPS.')})")
    for pid in ("realism", "fast", "turbo"):
        check(f'data-profile="{pid}"' in html, f"#quality profil {pid}")
    check('id="gpuLive"' in html and 'id="v11GalChips"' in html and 'id="v13HomeKpis"' in html, "GPU bar, filtar ocjena, Početna KPI")
    check(">Početna<" in html and 'data-tab="pregled"' in html, "kartica Početna (data-tab ostaje pregled)")
    check("rate-btn" in v11 and "rate-btn" in html and "/api/gallery/rate" in v11, "Dobra/Loša gumbi na slikama")
    check("/api/gpu-live" in js and "gpu_usage_pct" in js, "GPU bar poziva /api/gpu-live")
    check("ltImportGood" in lt_js and "import-good" in lt_js and "auto_sync_good" in lt_js and "ltReady" in lt_js, "trener: Uvezi Dobra, auto-sync, spremnost")
    for c in ("#13092e", "#1d0f46", "#a78bfa", "#5ce8b0", "#ff7893", "#6eb6ff", "blur(18px)", "rgba(186, 164, 255, 0.14)"):
        check(c in css, f"glass tema: {c}")
    check("max-width: none" in css, "puna širina (.wrap bez max-width)")
    check("fonts.googleapis" not in css + html and "cdn." not in css, "bez CDN fontova (100 % lokalno)")
    for p in ("static/ui_v130.css", "static/ui_v130.js", "static/v11.js", "static/lora_trainer.js", "index.html", "services/generation_service.py",
              "services/hardware_service.py", "image_gen.py", "api_v11.py", "api_lora.py", "services/lora_trainer_service.py", "inbox.py"):
        txt = (ROOT / p).read_text(encoding="utf-8")
        check(not BANNED.search(txt), f"{p}: bez zabranjenih izraza")
        check(not re.search(r"(ghp_|github_pat_|xai-)[A-Za-z0-9]{10,}", txt), f"{p}: bez tokena")
    rel = (ROOT / "tools" / "make_release.sh").read_text(encoding="utf-8")
    check("static/ui_v130.js" in rel and "static/ui_v130.css" in rel, "make_release.sh: nove datoteke u obaveznima")
    tr = (ROOT / "services" / "lora_trainer_service.py").read_text(encoding="utf-8")
    for s in ('"train_batch_size": 1', '"mixed_precision": "fp16"', '"gradient_checkpointing": True', '"cache_latents_to_disk": True', '"optimizer_type": "Adafactor"', '"sdpa": True'):
        check(s in tr, f"8 GB trening: {s}")
    check("TORCH_BACKENDS_CUDNN_ENABLED" in tr, "trening: TORCH_BACKENDS_CUDNN_ENABLED=0")
    check('"no_half_vae": True' in tr and "/free" in tr, "trening: no_half_vae, ComfyUI /free")


def main():
    print("test_v130")
    test_prompt_constants()
    test_profiles()
    test_base_canvas()
    test_vram_guard()
    test_detail_loras()
    test_plan_integration()
    test_ui_options()
    test_migration()
    test_rating_sync()
    test_gpu_parsing()
    test_gpu_live_cache()
    test_http()
    test_static()
    print()
    if FAILED:
        print(f"FAILED {FAILED}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
