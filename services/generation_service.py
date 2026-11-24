# -*- coding: utf-8 -*-
"""Generiranje slika: predlošci sadržaja, opcije workflowa (sampler, highres, FreeU, VAE, LoRA stack,
IP-Adapter/InstantID, Face Detailer), trajni red čekanja, galerija s ocjenama, LoRA dataset i Character Sheet.

ComfyUI na 8 GB VRAM-a radi jedan posao odjednom — zato red čekanja šalje poslove JEDAN PO JEDAN.
Predlošci su isključivo editorial / lifestyle / moda / studio glamur / behind-the-scenes /
personalizirani portreti. Osobe su uvijek fiktivne odrasle osobe (to štiti image_gen: "adult woman"
na početku prompta i child/teen u negativnom promptu).
"""

from __future__ import annotations

import io
import json
import random
import shutil
import struct
import threading
import time
import urllib.parse
import zlib
from pathlib import Path

import character
import comfy_launch
import image_gen
import inbox

from . import hardware_service
from .common import clamp_float, clamp_int, conn, data_dir, jdump, jload, now, row_dict, slugify, truthy

SAMPLERS = (
    "dpmpp_2m_sde", "dpmpp_3m_sde", "dpmpp_2m", "dpmpp_sde", "euler", "euler_ancestral",
    "dpmpp_2m_sde_gpu", "dpmpp_3m_sde_gpu", "uni_pc", "ddim",
)
SCHEDULERS = ("karras", "exponential", "sgm_uniform", "normal", "simple", "beta")
DEFAULT_SAMPLER = "dpmpp_2m_sde"
DEFAULT_SCHEDULER = "karras"
DEFAULT_HIRES_SCALE = 1.45
DEFAULT_HIRES_DENOISE = 0.38
DEFAULT_HIRES_STEPS = 14
TIERS = ("public_teaser", "premium")
QUEUE_STATUSES = ("queued", "running", "done", "error", "cancelled")
STATUS_LABELS = {"queued": "Na čekanju", "running": "U tijeku", "done": "Gotovo", "error": "Greška", "cancelled": "Otkazano"}
JOB_TIMEOUT_S = 45 * 60

# ---------- zadani predlošci (strogo SFW) ----------

DEFAULT_TEMPLATES = [
    {
        "key": "teaser_lifestyle_cafe", "name": "Javni teaser · Lifestyle kafić", "tier": "public_teaser",
        "description": "Opušten lifestyle kadar za Instagram feed.",
        "prompt_prefix": "candid lifestyle photo, sitting at a sunny street cafe, holding a cup of coffee, casual chic outfit",
        "prompt_suffix": "natural daylight, shallow depth of field, 35mm photo, film grain",
        "size_preset": "ig_portrait", "sampler": "dpmpp_2m_sde", "scheduler": "karras", "steps": 30, "cfg": 5.0,
        "hires": 0, "freeu": 1, "face_detailer": 1,
    },
    {
        "key": "teaser_fashion_street", "name": "Javni teaser · Ulična moda", "tier": "public_teaser",
        "description": "Modni street style kadar u gradu.",
        "prompt_prefix": "street style fashion photo, full body, walking in an old town street, trendy autumn outfit, confident pose",
        "prompt_suffix": "golden hour light, editorial fashion photography, sharp focus",
        "size_preset": "ig_portrait", "sampler": "dpmpp_2m_sde", "scheduler": "karras", "steps": 30, "cfg": 5.0,
        "hires": 0, "freeu": 1, "face_detailer": 1,
    },
    {
        "key": "teaser_bts_story", "name": "Javni teaser · Behind the scenes (Story)", "tier": "public_teaser",
        "description": "Iza kulisa snimanja, vertikalno za Story/Reels.",
        "prompt_prefix": "behind the scenes photo at a photo studio, laughing, softbox lights and camera gear in background, casual outfit",
        "prompt_suffix": "candid moment, warm tones, smartphone photo look",
        "size_preset": "ig_story", "sampler": "dpmpp_2m_sde", "scheduler": "karras", "steps": 28, "cfg": 5.0,
        "hires": 0, "freeu": 1, "face_detailer": 1,
    },
    {
        "key": "premium_studio_glamour", "name": "Premium · Studio glamur portret", "tier": "premium",
        "description": "Elegantan studijski portret u večernjoj haljini (editorial, SFW).",
        "prompt_prefix": "elegant studio glamour portrait, elegant evening gown, tasteful jewelry, professional makeup, seated pose",
        "prompt_suffix": "beauty dish lighting, dark backdrop, high-end magazine editorial, 85mm lens",
        "size_preset": "ig_portrait", "sampler": "dpmpp_3m_sde", "scheduler": "exponential", "steps": 32, "cfg": 4.5,
        "hires": 1, "freeu": 1, "face_detailer": 1,
    },
    {
        "key": "premium_editorial_fashion", "name": "Premium · Modni editorial", "tier": "premium",
        "description": "Ekskluzivni modni editorial set za pretplatnike.",
        "prompt_prefix": "high fashion editorial photoshoot, designer blazer outfit, dramatic pose, minimalist set design",
        "prompt_suffix": "cinematic lighting, vogue style editorial, ultra detailed fabric texture",
        "size_preset": "ig_portrait", "sampler": "dpmpp_2m_sde", "scheduler": "karras", "steps": 32, "cfg": 5.0,
        "hires": 1, "freeu": 1, "face_detailer": 1,
    },
    {
        "key": "premium_travel_set", "name": "Premium · Putovanje (ekskluzivni set)", "tier": "premium",
        "description": "Putopisni lifestyle set s obale.",
        "prompt_prefix": "travel lifestyle photo on a sailboat on the Adriatic coast, linen summer dress, sun hat, smiling",
        "prompt_suffix": "bright summer light, turquoise sea, travel magazine photography",
        "size_preset": "ig_portrait", "sampler": "dpmpp_2m_sde", "scheduler": "karras", "steps": 30, "cfg": 5.0,
        "hires": 1, "freeu": 1, "face_detailer": 1,
    },
    {
        "key": "premium_custom_portrait", "name": "Premium · Personalizirani portret / shoutout", "tier": "premium",
        "description": "Personalizirani SFW portret za fana (npr. drži karticu s porukom).",
        "prompt_prefix": "personalized friendly portrait, holding a small handwritten greeting card, warm smile, cozy home interior",
        "prompt_suffix": "soft natural window light, authentic photo, sharp focus on face",
        "size_preset": "ig_portrait", "sampler": "dpmpp_2m_sde", "scheduler": "karras", "steps": 30, "cfg": 5.0,
        "hires": 0, "freeu": 1, "face_detailer": 1,
    },
]

CHARACTER_SHEET_SHOTS = [
    ("Front · neutralno", "front view head and shoulders portrait, neutral expression, looking straight at the camera, plain light grey studio background, soft even lighting"),
    ("3/4 · topao osmijeh", "three-quarter view portrait, warm genuine smile, soft window light, neutral background"),
    ("Profil", "side profile portrait facing left, calm expression, clean studio background, soft rim light"),
    ("Vani · candid", "natural candid photo outdoors in a park, walking, daylight, casual outfit, medium shot"),
]

_hooks: list = []
_cfg: dict = {
    "planner": None,         # fn(body) -> {ok, workflow, meta}
    "comfy_request": None,   # fn(path, data=None, timeout=15, method=None) -> (payload, headers, status)
    "job_status": None,      # fn(prompt_id) -> {status, progress, images, error}
    "comfy_up": None,        # fn() -> (bool, msg)
    "remember_job": None,
}
_worker: threading.Thread | None = None
_stop = threading.Event()
_wake = threading.Event()
_JOB_META: dict[str, dict] = {}


def configure(**kwargs) -> None:
    for k, v in kwargs.items():
        if k in _cfg:
            _cfg[k] = v


def register_done_hook(fn) -> None:
    if fn not in _hooks:
        _hooks.append(fn)


# ---------- shema ----------

def ensure_schema() -> None:
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS content_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT DEFAULT '',
                name TEXT NOT NULL,
                tier TEXT NOT NULL DEFAULT 'public_teaser',
                description TEXT DEFAULT '',
                prompt_prefix TEXT DEFAULT '',
                prompt_suffix TEXT DEFAULT '',
                negative TEXT DEFAULT '',
                size_preset TEXT DEFAULT 'ig_portrait',
                sampler TEXT DEFAULT 'dpmpp_2m_sde',
                scheduler TEXT DEFAULT 'karras',
                steps INTEGER DEFAULT 30,
                cfg REAL DEFAULT 5.0,
                hires INTEGER DEFAULT 0,
                hires_scale REAL DEFAULT 1.45,
                hires_denoise REAL DEFAULT 0.38,
                freeu INTEGER DEFAULT 1,
                face_detailer INTEGER DEFAULT 1,
                builtin INTEGER DEFAULT 0,
                uses INTEGER DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS generation_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL DEFAULT 'queued',
                kind TEXT NOT NULL DEFAULT 'image',
                label TEXT DEFAULT '',
                body_json TEXT NOT NULL DEFAULT '{}',
                meta_json TEXT DEFAULT '{}',
                prompt_id TEXT DEFAULT '',
                progress REAL DEFAULT 0,
                images_json TEXT DEFAULT '[]',
                error TEXT DEFAULT '',
                group_key TEXT DEFAULT '',
                persona_id INTEGER,
                template_id INTEGER,
                order_id INTEGER,
                attempts INTEGER DEFAULT 0,
                created_at REAL NOT NULL,
                started_at REAL,
                finished_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_gq_status ON generation_queue(status, id);
            CREATE TABLE IF NOT EXISTS gallery_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                subfolder TEXT DEFAULT '',
                type TEXT DEFAULT 'output',
                local_path TEXT DEFAULT '',
                persona_id INTEGER,
                prompt TEXT DEFAULT '',
                seed TEXT DEFAULT '',
                model TEXT DEFAULT '',
                template_id INTEGER,
                job_id INTEGER,
                prompt_id TEXT DEFAULT '',
                source TEXT DEFAULT 'generate',
                kind TEXT DEFAULT 'image',
                rating INTEGER DEFAULT 0,
                created_at REAL NOT NULL,
                UNIQUE(filename, subfolder, type)
            );
            CREATE INDEX IF NOT EXISTS idx_gallery_persona ON gallery_items(persona_id, created_at);
            """
        )
        for col, decl in (
            ("lora_stack", "TEXT DEFAULT '[]'"),
            ("ref_mode", "TEXT DEFAULT 'auto'"),
            ("instantid_weight", "TEXT DEFAULT '0.8'"),
            ("send_mode", "TEXT DEFAULT ''"),
            ("bio", "TEXT DEFAULT ''"),
        ):
            inbox._ensure_column(c, "profiles", col, decl)
        inbox.ensure_gallery_rating_schema(c)
        n = c.execute("SELECT COUNT(*) FROM content_templates WHERE builtin=1").fetchone()[0]
        if n == 0:
            t = now()
            for tpl in DEFAULT_TEMPLATES:
                c.execute(
                    """INSERT INTO content_templates(key,name,tier,description,prompt_prefix,prompt_suffix,negative,size_preset,
                    sampler,scheduler,steps,cfg,hires,hires_scale,hires_denoise,freeu,face_detailer,builtin,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)""",
                    (tpl["key"], tpl["name"], tpl["tier"], tpl["description"], tpl["prompt_prefix"], tpl["prompt_suffix"], "",
                     tpl["size_preset"], tpl["sampler"], tpl["scheduler"], tpl["steps"], tpl["cfg"], tpl["hires"],
                     DEFAULT_HIRES_SCALE, DEFAULT_HIRES_DENOISE, tpl["freeu"], tpl["face_detailer"], t, t),
                )
        # Poslovi koji su ostali "U tijeku" nakon gašenja Studija vraćaju se u red.
        c.execute("UPDATE generation_queue SET status='queued', prompt_id='', progress=0 WHERE status='running'")


# ---------- profil: LoRA stack i referentni način ----------

def profile_extras(pid: int | None) -> dict:
    if not pid:
        return {}
    try:
        with conn() as c:
            row = c.execute("SELECT * FROM profiles WHERE id=?", (int(pid),)).fetchone()
    except Exception:
        return {}
    if not row:
        return {}
    keys = set(row.keys())
    return {
        "lora_stack": jload(row["lora_stack"] if "lora_stack" in keys else "[]", []) or [],
        "ref_mode": (row["ref_mode"] if "ref_mode" in keys else "auto") or "auto",
        "instantid_weight": clamp_float(row["instantid_weight"] if "instantid_weight" in keys else 0.8, 0.0, 1.5, 0.8),
        "send_mode": (row["send_mode"] if "send_mode" in keys else "") or "",
        "bio": (row["bio"] if "bio" in keys else "") or "",
    }


def clean_lora_stack(raw) -> list[dict]:
    if isinstance(raw, str):
        raw = jload(raw, [])
    out = []
    for item in raw or []:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:300]
        if not name or image_gen.is_turbo_lora_file(name) or any(o["name"] == name for o in out):
            continue
        sm = clamp_float(item.get("strength_model", item.get("strength", 0.8)), -2.0, 2.0, 0.8)
        sc = clamp_float(item.get("strength_clip", sm), -2.0, 2.0, sm)
        out.append({"name": name, "strength_model": round(sm, 2), "strength_clip": round(sc, 2), "enabled": truthy(item.get("enabled"), True)})
        if len(out) >= image_gen.MAX_LORA_STACK:
            break
    return out


def save_profile_extras(pid: int, payload: dict) -> dict:
    sets: dict = {}
    if "lora_stack" in payload:
        sets["lora_stack"] = jdump(clean_lora_stack(payload.get("lora_stack")))
    if "ref_mode" in payload:
        mode = str(payload.get("ref_mode") or "auto").lower()
        sets["ref_mode"] = mode if mode in {"auto", "ipadapter", "instantid"} else "auto"
    if "instantid_weight" in payload:
        sets["instantid_weight"] = str(clamp_float(payload.get("instantid_weight"), 0.0, 1.5, 0.8))
    if "send_mode" in payload:
        mode = str(payload.get("send_mode") or "").lower()
        sets["send_mode"] = mode if mode in {"", "auto", "approve"} else ""
    if "bio" in payload:
        sets["bio"] = str(payload.get("bio") or "")[:2000]
    if sets:
        with conn() as c:
            c.execute(f"UPDATE profiles SET {', '.join(k + '=?' for k in sets)} WHERE id=?", [*sets.values(), int(pid)])
    return profile_extras(pid)


# ---------- predlošci ----------

TEMPLATE_FIELDS = ("name", "tier", "description", "prompt_prefix", "prompt_suffix", "negative", "size_preset", "sampler",
                   "scheduler", "steps", "cfg", "hires", "hires_scale", "hires_denoise", "freeu", "face_detailer")


def _tpl_row(row) -> dict:
    d = row_dict(row)
    for k in ("hires", "freeu", "face_detailer", "builtin"):
        d[k] = bool(d.get(k))
    d["tier_label"] = "Javni teaser" if d.get("tier") == "public_teaser" else "Premium"
    return d


def list_templates(tier: str = "") -> list[dict]:
    with conn() as c:
        if tier in TIERS:
            rows = c.execute("SELECT * FROM content_templates WHERE tier=? ORDER BY tier DESC, builtin DESC, name", (tier,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM content_templates ORDER BY tier DESC, builtin DESC, name").fetchall()
    return [_tpl_row(r) for r in rows]


def get_template(tid) -> dict | None:
    try:
        tid = int(tid)
    except (TypeError, ValueError):
        return None
    with conn() as c:
        row = c.execute("SELECT * FROM content_templates WHERE id=?", (tid,)).fetchone()
    return _tpl_row(row) if row else None


def _clean_template(payload: dict, base: dict | None = None) -> dict:
    b = dict(base or {})
    out = {}
    for k in TEMPLATE_FIELDS:
        v = payload.get(k, b.get(k))
        if k == "name":
            v = str(v or "").strip()[:120]
            if not v:
                raise ValueError("Predložak treba ime.")
        elif k == "tier":
            v = v if v in TIERS else "public_teaser"
        elif k in {"sampler"}:
            v = v if v in SAMPLERS else DEFAULT_SAMPLER
        elif k in {"scheduler"}:
            v = v if v in SCHEDULERS else DEFAULT_SCHEDULER
        elif k == "steps":
            v = clamp_int(v, 4, 60, 30)
        elif k == "cfg":
            v = clamp_float(v, 1.0, 12.0, 5.0)
        elif k == "hires_scale":
            v = clamp_float(v, 1.1, 2.0, DEFAULT_HIRES_SCALE)
        elif k == "hires_denoise":
            v = clamp_float(v, 0.1, 0.8, DEFAULT_HIRES_DENOISE)
        elif k in {"hires", "freeu", "face_detailer"}:
            v = 1 if truthy(v, False) else 0
        else:
            v = str(v or "")[:4000]
        out[k] = v
    return out


def create_template(payload: dict) -> dict:
    data = _clean_template(payload)
    t = now()
    with conn() as c:
        cols = ", ".join(data.keys())
        c.execute(f"INSERT INTO content_templates({cols}, builtin, created_at, updated_at) VALUES ({', '.join('?' * len(data))}, 0, ?, ?)",
                  [*data.values(), t, t])
        tid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    return get_template(tid)


def update_template(tid: int, payload: dict) -> dict:
    cur = get_template(tid)
    if not cur:
        raise KeyError("Predložak ne postoji.")
    data = _clean_template(payload, cur)
    with conn() as c:
        c.execute(f"UPDATE content_templates SET {', '.join(k + '=?' for k in data)}, updated_at=? WHERE id=?", [*data.values(), now(), int(tid)])
    return get_template(tid)


def duplicate_template(tid: int) -> dict:
    cur = get_template(tid)
    if not cur:
        raise KeyError("Predložak ne postoji.")
    payload = {k: cur.get(k) for k in TEMPLATE_FIELDS}
    payload["name"] = (cur["name"] + " (kopija)")[:120]
    return create_template(payload)


def delete_template(tid: int) -> None:
    with conn() as c:
        c.execute("DELETE FROM content_templates WHERE id=?", (int(tid),))


def apply_template(body: dict) -> dict:
    """Spoji predložak u tijelo zahtjeva. Eksplicitna polja iz tijela imaju prednost."""
    if body.get("template_applied"):
        return body
    tpl = get_template(body.get("template_id")) if body.get("template_id") not in (None, "") else None
    if not tpl:
        return body
    out = dict(body)
    out["template_applied"] = True
    scene = (body.get("prompt") or "").strip()
    parts = [tpl.get("prompt_prefix") or "", scene, tpl.get("prompt_suffix") or ""]
    out["prompt"] = ", ".join(p.strip().strip(",") for p in parts if p and p.strip())
    if not (body.get("negative") or "").strip() and tpl.get("negative"):
        out["negative"] = tpl["negative"]
    # Eksplicitna polja iz tijela imaju prednost; template_override=True (serija s više predložaka) daje prednost predlošku.
    override = truthy(body.get("template_override"), False)
    for key in ("size_preset", "sampler", "scheduler", "steps", "cfg", "hires", "hires_scale", "hires_denoise", "freeu", "face_detailer"):
        val = tpl.get(key)
        if val in (None, ""):
            continue
        if body.get(key) in (None, "") or override:
            out[key] = val
            if key == "face_detailer":
                out["face_detailer_optional"] = True
    if out.get("size_preset") and out.get("size_preset") != body.get("size_preset"):
        # predložak određuje format; izbaci stare dimenzije da resolve_canvas uzme preset
        for k in ("width", "height", "output_width", "output_height"):
            out.pop(k, None)
    out["template_tier"] = tpl.get("tier")
    try:
        with conn() as c:
            c.execute("UPDATE content_templates SET uses=uses+1 WHERE id=?", (int(tpl["id"]),))
    except Exception:
        pass
    return out


# ---------- opcije workflowa ----------

def resolve_sampling(body: dict, arch: str) -> tuple[str, str] | None:
    """(sampler, scheduler) iz tijela ako su poslani i valjani; inače None (koristi zadano za arhitekturu)."""
    s = str(body.get("sampler") or body.get("sampler_name") or "").strip()
    sch = str(body.get("scheduler") or "").strip()
    if not s and not sch:
        return None
    d_s, d_sch = image_gen.default_sampler(arch)
    return (s if s in SAMPLERS else d_s), (sch if sch in SCHEDULERS else d_sch)


def resolve_lora_stack(body: dict, profile: dict | None, arch: str) -> list[dict]:
    if arch == "krea2":
        return []
    if "loras" in body:
        stack = clean_lora_stack(body.get("loras"))
    elif "lora" in body or "user_lora" in body:
        stack = []  # stari klijent: samo jedna LoRA kroz postojeći put
    else:
        if profile and "lora_stack" in profile:
            stack = clean_lora_stack(profile.get("lora_stack"))
        else:
            stack = clean_lora_stack(profile_extras((profile or {}).get("id")).get("lora_stack") if profile else [])
    return [x for x in stack if x.get("enabled", True)]


def face_detailer_params(body: dict) -> dict | None:
    keys = {"fd_denoise": "denoise", "fd_guide_size": "guide_size", "fd_max_size": "max_size",
            "fd_bbox_threshold": "bbox_threshold", "fd_steps": "steps", "fd_feather": "feather"}
    out = {dst: body[src] for src, dst in keys.items() if body.get(src) not in (None, "")}
    return out or None


def resolve_ref_mode(body: dict, profile: dict | None) -> str:
    mode = str(body.get("ref_mode") or "").lower()
    if mode not in {"auto", "ipadapter", "instantid"}:
        if profile and profile.get("ref_mode"):
            mode = str(profile.get("ref_mode")).lower()
        else:
            mode = profile_extras((profile or {}).get("id")).get("ref_mode", "auto") if profile else "auto"
    return mode if mode in {"auto", "ipadapter", "instantid"} else "auto"


def safe_canvas(body: dict, arch: str, canvas: dict) -> dict:
    """8 GB siguran mod (samo kad ga klijent eksplicitno pošalje): niža bazna rezolucija + upscale na cilj.

    1.3.0: RX 6600 profil kvalitete može zadati dulju stranicu baze (rx_base_long, npr. 1024 za Turbo 1024)."""
    if not truthy(body.get("safe_mode"), False) or arch not in {"sdxl", "sd15"}:
        return canvas
    tw, th = int(canvas["output_width"]), int(canvas["output_height"])
    long_side = clamp_int(body.get("rx_base_long"), 0, 1536, 0) if arch == "sdxl" else 0
    if long_side:
        bw, bh = hardware_service.rx_base_for(arch, tw, th, long_side)
    else:
        bw, bh = hardware_service.safe_base_for(arch, tw, th)
    if (bw, bh) == (int(canvas["width"]), int(canvas["height"])) or bw * bh >= int(canvas["width"]) * int(canvas["height"]):
        return {**canvas, "safe_mode": False}
    return {**canvas, "width": bw, "height": bh, "output_width": tw, "output_height": th, "safe_mode": True}


# ---------- 1.3.0: RX 6600 profili kvalitete, 8 GB zaštita i SFW detail LoRA-e ----------
#
# Profili se primjenjuju samo kad klijent pošalje quality_profile (novo sučelje to radi). Popunjavaju SAMO
# polja koja nisu poslana — sve što korisnik ručno postavi u Naprednom ima prednost. Stari klijenti i API
# pozivi bez quality_profile rade točno kao prije.

RX_PROFILES = {
    "realism": {
        "label": "Realizam", "badge": "Preporučeno",
        "hint": "Manja baza (768×960) + brzi hires 1,33× (8 koraka, denoise 0,35). CFG 4,3 za prirodnu kožu i svjetlo.",
        "steps": 24, "cfg_sdxl": 4.3, "cfg_sd15": 5.0, "sampler": "dpmpp_2m_sde", "scheduler": "karras",
        "hires": True, "hires_scale": 1.33, "hires_denoise": 0.35, "hires_steps": 8, "base_long": 960,
        "natural": True, "turbo": False,
    },
    "fast": {
        "label": "Brzo", "badge": "",
        "hint": "Jedan prolaz, 20 koraka, baza do 1024 px. Dobar omjer brzine i kvalitete bez Turbo LoRA-e.",
        "steps": 20, "cfg_sdxl": 4.0, "cfg_sd15": 4.8, "sampler": "dpmpp_2m", "scheduler": "karras",
        "hires": False, "hires_scale": 1.33, "hires_denoise": 0.35, "hires_steps": 8, "base_long": 1024,
        "natural": True, "turbo": False,
    },
    "turbo": {
        "label": "Turbo 1024", "badge": "Najbrže",
        "hint": "Hyper-SDXL 8 koraka, CFG 2,2 (manje „prepečen” izgled), euler + sgm_uniform, baza 1024 px, bez hiresa.",
        "steps": 8, "cfg_sdxl": 2.2, "cfg_sd15": 2.2, "sampler": "euler", "scheduler": "sgm_uniform",
        "hires": False, "hires_scale": 1.25, "hires_denoise": 0.32, "hires_steps": 4, "base_long": 1024,
        "natural": True, "turbo": True,
    },
}
DEFAULT_RX_PROFILE = "realism"
UI_HIRES_SCALE = 1.33
UI_HIRES_DENOISE = 0.35
UI_HIRES_STEPS = 8

# 8 GB zaštita (RX 6600): granice koje sprječavaju OOM bez gašenja korisnikovih opcija bez razloga.
VRAM_GUARD = {
    "hires_max_mp": 1.35,          # najveća površina nakon hiresa (megapikseli)
    "hires_max_mp_instantid": 1.1,  # uz InstantID (ControlNet + InsightFace)
    "hires_min_scale": 1.15,
    "fd_max_denoise": 0.5,
    "fd_max_guide": 512,
    "fd_max_size": 768,
    "fd_max_steps": 12,
    "detail_max_weight": 0.6,
    "detail_max_turbo": 2,
}

# Kurirane SFW detail LoRA-e (iste datoteke kao u kartici Modeli → „Preporučene SDXL LoRA-e”).
DETAIL_LORA_PRESETS = [
    {"key": "skin", "label": "Prirodna koža", "lora": "ostris_photorealistic_slider_xl.safetensors", "weight": 0.5,
     "hint": "Photorealistic slider: prirodnija tekstura kože i izgled prave fotografije."},
    {"key": "detail", "label": "Fini detalji", "lora": "add_detail_xl.safetensors", "weight": 0.4,
     "hint": "Detail Tweaker XL: oštrije oči, kosa i tkanina. Preporuka 0,5–1,5 (pozitivno dodaje, negativno smanjuje detalje); 1-klik ostaje 0,4 da ne pretjera."},
    {"key": "light", "label": "Prirodni kontrast", "lora": "sdxl_offset_example_lora_1.0.safetensors", "weight": 0.35,
     "hint": "Offset noise (Stability AI): dublje sjene i manje „ravno” AI svjetlo."},
    {"key": "skin_realism", "label": "Realistična koža (Skin Realism)", "lora": "skin_realism_xl.safetensors", "weight": 0.5,
     "hint": "Skin Realism: prirodna tekstura kože i nesavršenosti. Preporuka 0,3–0,7 (zadano 0,5); izbjegavaj 1,0. U prompt možeš dodati okidač: Detailed natural skin and blemishes without-makeup and acne."},
]


def rx_profile(key) -> dict | None:
    return RX_PROFILES.get(str(key or "").strip().lower())


def _hires_cap(width: int, height: int, scale: float, max_mp: float, out_long: int = 0) -> float:
    area = max(1, int(width) * int(height))
    cap = (max_mp * 1_000_000 / area) ** 0.5
    if out_long:
        cap = min(cap, max(out_long / max(int(width), int(height)), 1.0) * 1.02)
    return round(min(scale, cap), 3)


def prepare_rx6600(body: dict, arch: str) -> tuple[dict, dict]:
    """Primijeni RX 6600 profil kvalitete (samo nepostavljena polja). Vraća (novo tijelo, rx_info)."""
    out = dict(body or {})
    prof = rx_profile(out.get("quality_profile"))
    info: dict = {"profile": "", "notes": [], "quality_text": None, "natural": False, "turbo_cfg": None}
    if not prof or arch not in {"sdxl", "sd15"}:
        return out, info
    key = str(out.get("quality_profile")).strip().lower()
    info["profile"] = key
    manual_cfg = out.get("cfg") not in (None, "")
    if prof["turbo"] and arch == "sdxl":
        out.setdefault("turbo", True)
        if not manual_cfg:
            info["turbo_cfg"] = float(prof["cfg_sdxl"])
    if out.get("steps") in (None, ""):
        out["steps"] = prof["steps"]
    if not manual_cfg and not prof["turbo"]:
        out["cfg"] = prof["cfg_sdxl"] if arch == "sdxl" else prof["cfg_sd15"]
    if not (out.get("sampler") or out.get("sampler_name")):
        out["sampler"] = prof["sampler"]
    if not out.get("scheduler"):
        out["scheduler"] = prof["scheduler"]
    if "hires" not in out:
        out["hires"] = bool(prof["hires"])
    for k in ("hires_scale", "hires_denoise", "hires_steps"):
        if out.get(k) in (None, ""):
            out[k] = prof[k]
    if arch == "sdxl" and out.get("rx_base_long") in (None, ""):
        out["rx_base_long"] = prof["base_long"]
    if prof["natural"]:
        info["natural"] = True
        info["quality_text"] = image_gen.NATURAL_QUALITY
    if truthy(out.get("face_detailer"), False) and out.get("fd_steps") in (None, ""):
        out["fd_steps"] = min(int(out.get("steps") or prof["steps"]), VRAM_GUARD["fd_max_steps"])
    return out, info


def natural_negative(negative: str, info: dict) -> str:
    """Zadani negativni prompt -> verzija protiv plastičnog izgleda. Korisnikov vlastiti tekst ostaje netaknut."""
    neg = (negative or "").strip()
    if info.get("natural") and (not neg or neg == image_gen.DEFAULT_NEGATIVE.strip()):
        return image_gen.NATURAL_NEGATIVE
    return negative


def vram_guard(settings: dict, *, arch: str, enabled: bool = True) -> tuple[dict, list[str]]:
    """8 GB zaštita za RX 6600. settings: width, height, output_width, output_height, batch, hires, hires_scale,
    instantid, face_detailer, vae_mode, fd (dict). Vraća (prilagođeno, poruke). Ne baca iznimke."""
    s = dict(settings)
    notes: list[str] = []
    if not enabled or arch not in {"sdxl", "sd15"}:
        return s, notes
    w, h = int(s.get("width") or 0), int(s.get("height") or 0)
    out_long = max(int(s.get("output_width") or w), int(s.get("output_height") or h))
    iid = bool(s.get("instantid"))
    fd = bool(s.get("face_detailer"))
    if arch == "sdxl" and s.get("hires") and iid and fd:
        s["hires"] = False
        notes.append("8 GB zaštita: Hires je isključen jer su uključeni i InstantID i Face Detailer (zajedno ne stanu u 8 GB).")
    if s.get("hires") and w and h:
        max_mp = VRAM_GUARD["hires_max_mp_instantid"] if iid else VRAM_GUARD["hires_max_mp"]
        if arch == "sd15":
            max_mp = 1.1
        req = float(s.get("hires_scale") or 1.5)
        capped = _hires_cap(w, h, req, max_mp, out_long)
        if capped < VRAM_GUARD["hires_min_scale"]:
            s["hires"] = False
            notes.append("8 GB zaštita: Hires preskočen jer je baza već blizu ciljne veličine.")
        elif capped < req - 1e-3:
            s["hires_scale"] = round(capped, 2)
            notes.append(f"8 GB zaštita: Hires skala smanjena na {capped:.2f}× (najviše ~{max_mp:.2f} MP).")
    if arch == "sdxl" and int(s.get("batch") or 1) > 1 and (s.get("hires") or iid):
        s["batch"] = 1
        notes.append("8 GB zaštita: uz Hires/InstantID na SDXL-u generira se 1 slika po pokretanju (za više koristi red čekanja).")
    if arch == "sdxl" and (s.get("hires") or iid) and str(s.get("vae_mode") or "standard") == "standard":
        s["vae_mode"] = "tiled"
        notes.append("8 GB zaštita: VAE dekodiranje prebačeno na „tiled” zbog veće slike.")
    fdp = dict(s.get("fd") or {})
    if fd and fdp:
        caps = (("denoise", VRAM_GUARD["fd_max_denoise"]), ("guide_size", VRAM_GUARD["fd_max_guide"]),
                ("max_size", VRAM_GUARD["fd_max_size"]), ("steps", VRAM_GUARD["fd_max_steps"]))
        changed = False
        for k, mx in caps:
            try:
                if k in fdp and float(fdp[k]) > mx:
                    fdp[k] = mx
                    changed = True
            except (TypeError, ValueError):
                fdp.pop(k, None)
        if changed:
            notes.append("8 GB zaštita: Face Detailer ograničen (denoise ≤ 0,5, guide ≤ 512, max ≤ 768) za prirodno lice bez OOM-a.")
        s["fd"] = fdp
    return s, notes


def add_detail_loras(stack: list[dict], body: dict, arch: str, *, turbo: bool = False, available=None) -> tuple[list[dict], list[str]]:
    """Brzi prekidači za kurirane SFW detail LoRA-e (body.detail_loras = ["skin", "detail", ...])."""
    keys = body.get("detail_loras")
    if isinstance(keys, str):
        keys = [k.strip() for k in keys.split(",") if k.strip()]
    if not keys or arch != "sdxl":
        return list(stack or []), ([] if not keys else ["Detail LoRA-e su za SDXL modele — preskočene."])
    available = available or image_gen.lora_available
    out = list(stack or [])
    notes: list[str] = []
    names = {x["name"] for x in out}
    limit = VRAM_GUARD["detail_max_turbo"] if turbo else len(DETAIL_LORA_PRESETS)
    used = 0
    for preset in DETAIL_LORA_PRESETS:
        if preset["key"] not in keys or used >= limit:
            continue
        name = preset["lora"]
        if name in names:
            used += 1
            continue
        if not available(name):
            notes.append(f"Detail LoRA „{preset['label']}” nije preuzeta (Modeli → Preporučene SDXL LoRA-e) — preskočena.")
            continue
        if len(out) >= image_gen.MAX_LORA_STACK:
            notes.append("LoRA stack je pun (najviše 5) — detail LoRA preskočena.")
            break
        wgt = min(float(preset["weight"]), VRAM_GUARD["detail_max_weight"]) * (0.8 if turbo else 1.0)
        out.append({"name": name, "strength_model": round(wgt, 2), "strength_clip": round(wgt, 2), "enabled": True, "detail": preset["key"]})
        names.add(name)
        used += 1
    return out, notes


def ui_options() -> dict:
    hw = hardware_service.generation_defaults()
    return {
        "samplers": list(SAMPLERS),
        "schedulers": list(SCHEDULERS),
        "defaults": {
            "sampler": DEFAULT_SAMPLER, "scheduler": DEFAULT_SCHEDULER, "steps": 30, "cfg_sdxl": 5.0, "cfg_sd15": 5.5,
            "hires_scale": UI_HIRES_SCALE, "hires_denoise": UI_HIRES_DENOISE, "hires_steps": UI_HIRES_STEPS,
            "quality_profile": DEFAULT_RX_PROFILE,
            "freeu": image_gen.FREEU_V2_SDXL, "face_detailer": {k: character.FACE_DETAILER_DEFAULTS[k] for k in ("denoise", "guide_size", "max_size", "bbox_threshold")},
            **hw,
        },
        "max_loras": image_gen.MAX_LORA_STACK,
        "quality_profiles": [{"key": k, **{f: v for f, v in p.items()}} for k, p in RX_PROFILES.items()],
        "detail_loras": [{**d, "available": _lora_ok(d["lora"])} for d in DETAIL_LORA_PRESETS],
        "vram_guard": dict(VRAM_GUARD),
    }


def _lora_ok(name: str) -> bool:
    try:
        return bool(image_gen.lora_available(name))
    except Exception:
        return False


def default_body_options() -> dict:
    """Za poslove koje slaže sam Studio (character sheet, custom narudžbe): optimalne 8 GB postavke."""
    hw = hardware_service.generation_defaults()
    return {
        "sampler": DEFAULT_SAMPLER, "scheduler": DEFAULT_SCHEDULER, "steps": 30,
        "vae_mode": hw["vae_mode"], "vae_tile": hw["vae_tile"], "safe_mode": hw["safe_mode"],
        "freeu": True, "hires": False,
    }


# ---------- red čekanja ----------

def _job_row(row) -> dict:
    d = row_dict(row)
    d["body"] = jload(d.pop("body_json", "{}"), {}) or {}
    d["meta"] = jload(d.pop("meta_json", "{}"), {}) or {}
    d["images"] = jload(d.pop("images_json", "[]"), []) or []
    d["status_label"] = STATUS_LABELS.get(d.get("status"), d.get("status"))
    for img in d["images"]:
        img.setdefault("url", view_url(img))
    return d


def enqueue(body: dict, *, label: str = "", kind: str = "image", group_key: str = "", order_id: int | None = None) -> dict:
    if not (body.get("prompt") or "").strip() and not body.get("template_id"):
        raise ValueError("Upiši opis slike.")
    pid = body.get("persona_id") or body.get("profile_id")
    try:
        pid = int(pid) if pid not in (None, "") else None
    except (TypeError, ValueError):
        pid = None
    tid = body.get("template_id")
    try:
        tid = int(tid) if tid not in (None, "") else None
    except (TypeError, ValueError):
        tid = None
    with conn() as c:
        c.execute(
            """INSERT INTO generation_queue(status, kind, label, body_json, group_key, persona_id, template_id, order_id, created_at)
            VALUES ('queued',?,?,?,?,?,?,?,?)""",
            (kind, (label or (body.get("prompt") or "")[:80]), jdump(body), group_key, pid, tid, order_id, now()),
        )
        jid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    _wake.set()
    return get_job(jid)


def enqueue_batch(body: dict, count: int = 1, *, seed_mode: str = "random", template_ids: list | None = None, label: str = "") -> list[dict]:
    """N slika (sekvencijalni ili nasumični seed) i/ili više predložaka odjednom."""
    count = clamp_int(count, 1, 50, 1)
    templates = [t for t in (template_ids or []) if t not in (None, "")] or [body.get("template_id")]
    try:
        base_seed = int(body.get("seed"))
    except (TypeError, ValueError):
        base_seed = -1
    if base_seed < 0:
        base_seed = random.randint(0, 2_000_000_000)
    group = f"batch-{int(time.time() * 1000)}"
    multi = len(templates) > 1
    jobs = []
    for tid in templates:
        for i in range(count):
            b = dict(body)
            if tid not in (None, ""):
                b["template_id"] = tid
                if multi or template_ids:
                    b["template_override"] = True  # izričito odabrani predlošci nose svoje postavke
            if seed_mode == "sequential":
                b["seed"] = base_seed + i
            elif seed_mode == "fixed":
                b["seed"] = base_seed
            else:
                b["seed"] = random.randint(0, 2_147_483_647)
            b["batch"] = 1
            tname = ""
            if tid not in (None, ""):
                tpl = get_template(tid)
                tname = (tpl or {}).get("name", "")
            jobs.append(enqueue(b, label=(label or tname or (body.get("prompt") or "")[:60]) + f" #{i + 1}", group_key=group))
    return jobs


def get_job(jid) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM generation_queue WHERE id=?", (int(jid),)).fetchone()
    return _job_row(row) if row else None


def list_queue(limit: int = 80, include_finished: bool = True) -> dict:
    with conn() as c:
        if include_finished:
            rows = c.execute(
                "SELECT * FROM generation_queue ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END, "
                "CASE WHEN status IN ('running','queued') THEN id END ASC, id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM generation_queue WHERE status IN ('queued','running') ORDER BY id LIMIT ?", (int(limit),)).fetchall()
        counts = {r[0]: r[1] for r in c.execute("SELECT status, COUNT(*) FROM generation_queue GROUP BY status").fetchall()}
    return {"ok": True, "jobs": [_job_row(r) for r in rows], "counts": {s: int(counts.get(s, 0)) for s in QUEUE_STATUSES},
            "labels": STATUS_LABELS, "worker": bool(_worker and _worker.is_alive())}


def cancel_job(jid: int) -> dict:
    job = get_job(jid)
    if not job:
        raise KeyError("Posao ne postoji.")
    if job["status"] in {"queued", "running"}:
        with conn() as c:
            c.execute("UPDATE generation_queue SET status='cancelled', finished_at=? WHERE id=?", (now(), int(jid)))
        if job["status"] == "running" and _cfg.get("comfy_request"):
            try:
                if job.get("prompt_id"):
                    _cfg["comfy_request"]("/queue", data={"delete": [job["prompt_id"]]}, timeout=5)
                _cfg["comfy_request"]("/interrupt", data={}, timeout=5)
            except Exception:
                pass
    return get_job(jid)


def retry_job(jid: int) -> dict:
    job = get_job(jid)
    if not job:
        raise KeyError("Posao ne postoji.")
    if job["status"] not in {"error", "cancelled"}:
        raise ValueError("Ponoviti se mogu samo poslovi s greškom ili otkazani.")
    with conn() as c:
        c.execute("UPDATE generation_queue SET status='queued', error='', progress=0, prompt_id='', finished_at=NULL WHERE id=?", (int(jid),))
    _wake.set()
    return get_job(jid)


def clear_finished() -> int:
    with conn() as c:
        cur = c.execute("DELETE FROM generation_queue WHERE status IN ('done','error','cancelled')")
        return cur.rowcount


def _set_job(jid: int, **fields) -> None:
    if "images" in fields:
        fields["images_json"] = jdump(fields.pop("images"))
    if "meta" in fields:
        fields["meta_json"] = jdump(fields.pop("meta"))
    with conn() as c:
        c.execute(f"UPDATE generation_queue SET {', '.join(k + '=?' for k in fields)} WHERE id=?", [*fields.values(), int(jid)])


def _claim_next() -> dict | None:
    with conn() as c:
        if c.execute("SELECT COUNT(*) FROM generation_queue WHERE status='running'").fetchone()[0]:
            return None
        row = c.execute("SELECT * FROM generation_queue WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if not row:
            return None
        c.execute("UPDATE generation_queue SET status='running', started_at=?, attempts=attempts+1, progress=0 WHERE id=?", (now(), row["id"]))
    return get_job(row["id"])


def gpu_busy_training() -> bool:
    """True dok LoRA trener radi: na RX 6600 (8 GB) generiranje i treniranje ne smiju ići istodobno."""
    try:
        from . import lora_trainer_service
        return lora_trainer_service.training_active()
    except Exception:
        return False


def _job_cancelled(jid: int) -> bool:
    with conn() as c:
        row = c.execute("SELECT status FROM generation_queue WHERE id=?", (int(jid),)).fetchone()
    return not row or row[0] == "cancelled"


class _JobEnded(Exception):
    pass


def process_next(*, poll_interval: float = 1.5, timeout_s: float = JOB_TIMEOUT_S, sleep=time.sleep) -> dict | None:
    """Obradi JEDAN posao iz reda (sinkrono). Vrati završni posao ili None ako red miruje."""
    planner, req, status_fn = _cfg.get("planner"), _cfg.get("comfy_request"), _cfg.get("job_status")
    if not (planner and req and status_fn):
        return None
    up = _cfg.get("comfy_up")
    if up:
        try:
            ok, _msg = up()
        except Exception:
            ok = False
        if not ok:
            return None
    if gpu_busy_training():
        return None  # LoRA treniranje drži GPU (8 GB) — poslovi čekaju u redu
    job = _claim_next()
    if not job:
        return None
    jid = job["id"]
    try:
        body = apply_template(dict(job["body"]))
        plan = planner(body)
        if not plan.get("ok"):
            _set_job(jid, status="error", error=str(plan.get("error") or "Neuspjelo slaganje workflowa."), finished_at=now())
            raise _JobEnded()
        payload, _h, _s = req("/prompt", data={"prompt": plan["workflow"], "client_id": "simple-studio"}, timeout=30)
        if not isinstance(payload, dict) or not payload.get("prompt_id") or payload.get("node_errors"):
            err = (payload or {}).get("error") if isinstance(payload, dict) else None
            _set_job(jid, status="error", error=f"ComfyUI nije prihvatio workflow: {err or (payload or {}).get('node_errors') if isinstance(payload, dict) else payload}"[:1500], finished_at=now())
            raise _JobEnded()
        prompt_id = str(payload["prompt_id"])
        meta = dict(plan.get("meta") or {})
        meta.pop("tokens", None)
        _set_job(jid, prompt_id=prompt_id, meta=meta)
        if _cfg.get("remember_job"):
            try:
                _cfg["remember_job"](prompt_id)
            except Exception:
                pass
        started = time.time()
        while True:
            if _job_cancelled(jid):
                try:
                    req("/queue", data={"delete": [prompt_id]}, timeout=5)
                    req("/interrupt", data={}, timeout=5)
                except Exception:
                    pass
                raise _JobEnded()
            st = status_fn(prompt_id) or {}
            status = st.get("status")
            prog = st.get("progress") or {}
            try:
                pct = 0.0 if prog.get("indeterminate") else float(prog.get("value") or 0) / float(prog.get("max") or 1)
            except (TypeError, ValueError, ZeroDivisionError):
                pct = 0.0
            if status == "done":
                images = [i for i in (st.get("images") or []) if not i.get("kind") or i.get("kind") in {"images"}]
                rec = record_images(images, meta, job_id=jid, prompt_id=prompt_id, persona_id=job.get("persona_id"),
                                    template_id=job.get("template_id"),
                                    source={"character_sheet": "character_shot"}.get(job.get("kind") or "", job.get("kind") or "queue"))
                _set_job(jid, status="done", progress=1.0, images=[{**i, "gallery_id": g} for i, g in zip(images, rec)], finished_at=now())
                break
            if status == "error":
                _set_job(jid, status="error", error=str(st.get("error") or "ComfyUI greška")[:1500], finished_at=now())
                break
            _set_job(jid, progress=round(max(0.0, min(0.99, pct)), 3))
            if time.time() - started > timeout_s:
                _set_job(jid, status="error", error="Isteklo vrijeme čekanja na ComfyUI.", finished_at=now())
                break
            sleep(poll_interval)
    except _JobEnded:
        pass  # greška ili otkazivanje već upisani; hookovi se ipak pozivaju
    except Exception as exc:
        _set_job(jid, status="error", error=f"{exc}"[:1500], finished_at=now())
    final = get_job(jid)
    for hook in list(_hooks):
        try:
            hook(final)
        except Exception:
            pass
    return final


def _worker_loop() -> None:
    while not _stop.is_set():
        try:
            job = process_next()
        except Exception:
            job = None
        if job is None:
            _wake.wait(3)
            _wake.clear()


def start_worker() -> None:
    global _worker
    if _worker and _worker.is_alive():
        return
    _stop.clear()
    _worker = threading.Thread(target=_worker_loop, name="generation-queue", daemon=True)
    _worker.start()


def stop_worker() -> None:
    _stop.set()
    _wake.set()


# ---------- galerija ----------

def view_url(img: dict) -> str:
    if img.get("gallery_id") and img.get("local"):
        return f"/api/gallery/file/{img['gallery_id']}"
    return "/api/view?" + urllib.parse.urlencode({"filename": img.get("filename") or "", "subfolder": img.get("subfolder") or "", "type": img.get("type") or "output"})


def remember_meta(prompt_id: str, meta: dict) -> None:
    _JOB_META[str(prompt_id)] = dict(meta or {})
    if len(_JOB_META) > 300:
        for k in list(_JOB_META)[:100]:
            _JOB_META.pop(k, None)


def record_prompt_images(prompt_id: str, images: list[dict]) -> dict:
    """Upiše gotove slike u galeriju; vraća {filename: gallery_id}."""
    if not images:
        return {}
    meta = _JOB_META.get(str(prompt_id)) or {}
    imgs = [i for i in images if not i.get("kind") and i.get("filename")]
    ids = record_images(imgs, meta, prompt_id=prompt_id, persona_id=meta.get("persona_id"),
                        template_id=meta.get("template_id"), source="generate")
    return {i["filename"]: gid for i, gid in zip(imgs, ids)}


def record_images(images: list[dict], meta: dict | None, *, job_id=None, prompt_id: str = "", persona_id=None, template_id=None,
                  source: str = "generate", local_path: str = "") -> list[int]:
    meta = meta or {}
    ids = []
    with conn() as c:
        for img in images or []:
            fn = img.get("filename")
            if not fn:
                continue
            c.execute(
                """INSERT OR IGNORE INTO gallery_items(filename, subfolder, type, local_path, persona_id, prompt, seed, model, template_id,
                job_id, prompt_id, source, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (fn, img.get("subfolder") or "", img.get("type") or "output", local_path or img.get("local_path") or "",
                 persona_id if persona_id not in ("",) else None, str(meta.get("prompt") or "")[:4000], str(meta.get("seed") if meta.get("seed") is not None else ""),
                 str(meta.get("model") or ""), template_id, job_id, prompt_id, source, now()),
            )
            row = c.execute("SELECT id FROM gallery_items WHERE filename=? AND subfolder=? AND type=?",
                            (fn, img.get("subfolder") or "", img.get("type") or "output")).fetchone()
            ids.append(int(row[0]))
    return ids


def _gallery_row(row) -> dict:
    d = row_dict(row)
    d["local"] = bool(d.get("local_path"))
    d["url"] = f"/api/gallery/file/{d['id']}" if d["local"] else view_url(d)
    d["rating_label"] = {1: "Dobra", -1: "Loša"}.get(int(d.get("rating") or 0), "")
    return d


def list_gallery(*, persona_id=None, rating=None, offset: int = 0, limit: int = 24, source: str = "") -> dict:
    where, args = [], []
    if persona_id not in (None, ""):
        where.append("persona_id=?")
        args.append(int(persona_id))
    if rating not in (None, ""):
        where.append("rating=?")
        args.append(int(rating))
    if source:
        where.append("source=?")
        args.append(source)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    limit = clamp_int(limit, 1, 200, 24)
    with conn() as c:
        total = c.execute(f"SELECT COUNT(*) FROM gallery_items {clause}", args).fetchone()[0]
        rows = c.execute(f"SELECT * FROM gallery_items {clause} ORDER BY id DESC LIMIT ? OFFSET ?", [*args, limit, max(0, int(offset))]).fetchall()
    items = [_gallery_row(r) for r in rows]
    return {"ok": True, "items": items, "total": int(total), "offset": int(offset), "limit": limit, "has_more": int(offset) + len(items) < int(total)}


def gallery_item(gid) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM gallery_items WHERE id=?", (int(gid),)).fetchone()
    return _gallery_row(row) if row else None


def find_gallery_item(filename: str, subfolder: str = "", type_: str = "output") -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM gallery_items WHERE filename=? AND subfolder=? AND type=?", (filename, subfolder or "", type_ or "output")).fetchone()
    return _gallery_row(row) if row else None


def rate_image(*, gallery_id=None, filename: str = "", subfolder: str = "", type_: str = "output", rating: int = 0, persona_id=None, prompt: str = "", seed="", model: str = "") -> dict:
    rating = 1 if int(rating or 0) > 0 else (-1 if int(rating or 0) < 0 else 0)
    item = gallery_item(gallery_id) if gallery_id else (find_gallery_item(filename, subfolder, type_) if filename else None)
    if not item:
        if not filename:
            raise KeyError("Slika nije pronađena u galeriji.")
        ids = record_images([{"filename": filename, "subfolder": subfolder, "type": type_}], {"prompt": prompt, "seed": seed, "model": model},
                            persona_id=persona_id, source="history")
        item = gallery_item(ids[0])
    with conn() as c:
        c.execute("UPDATE gallery_items SET rating=?, rated_at=? WHERE id=?", (rating, now(), item["id"]))
        if persona_id not in (None, "") and not item.get("persona_id"):
            c.execute("UPDATE gallery_items SET persona_id=? WHERE id=?", (int(persona_id), item["id"]))
    out = gallery_item(item["id"])
    # 1.3.0: ocjena izravno puni / čisti LoRA dataset osobe (Dobra -> dodaj, Loša/bez ocjene -> makni ako je došla iz galerije).
    try:
        from . import lora_trainer_service
        out["lora_sync"] = lora_trainer_service.sync_gallery_rating(out)
    except Exception as exc:  # ocjena se uvijek sprema, sinkronizacija je dodatak
        out["lora_sync"] = {"action": "error", "message": str(exc)[:300]}
    return out


def delete_gallery_item(gid: int) -> None:
    item = gallery_item(gid)
    with conn() as c:
        c.execute("DELETE FROM gallery_items WHERE id=?", (int(gid),))
    if item and item.get("local_path"):
        p = Path(item["local_path"])
        try:
            if p.is_file() and _inside(p, gallery_dir()):
                p.unlink()
        except OSError:
            pass


def gallery_dir() -> Path:
    d = data_dir() / "outputs" / "gallery"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def local_file_for(item: dict) -> Path | None:
    if item.get("local_path"):
        p = Path(item["local_path"])
        return p if p.is_file() else None
    base = comfy_launch.comfy_dir() / ("output" if (item.get("type") or "output") == "output" else item.get("type") or "output")
    p = base / (item.get("subfolder") or "") / (item.get("filename") or "")
    return p if p.is_file() else None


def read_item_bytes(item: dict) -> bytes:
    p = local_file_for(item)
    if p:
        return p.read_bytes()
    req = _cfg.get("comfy_request")
    if not req:
        raise RuntimeError("ComfyUI nije dostupan za čitanje slike.")
    qs = urllib.parse.urlencode({"filename": item.get("filename") or "", "subfolder": item.get("subfolder") or "", "type": item.get("type") or "output"})
    raw, _h, _s = req("/view?" + qs, timeout=30)
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        raise RuntimeError("Ne mogu dohvatiti sliku iz ComfyUI-ja.")
    return bytes(raw)


# ---------- LoRA dataset (Dobra) ----------

KOHYA_SDXL_8GB = {
    "pretrained_model_name_or_path": "C:/ComfyUI-Zluda/models/checkpoints/RealVisXL_V5.0_fp16.safetensors",
    "train_data_dir": "",
    "output_dir": "",
    "output_name": "",
    "resolution": "768,768",
    "enable_bucket": True,
    "min_bucket_reso": 512,
    "max_bucket_reso": 1024,
    "network_module": "networks.lora",
    "network_dim": 16,
    "network_alpha": 8,
    "network_train_unet_only": True,
    "cache_text_encoder_outputs": True,
    "cache_latents": True,
    "cache_latents_to_disk": True,
    "gradient_checkpointing": True,
    "mixed_precision": "fp16",
    "save_precision": "fp16",
    "optimizer_type": "Adafactor",
    "optimizer_args": ["scale_parameter=False", "relative_step=False", "warmup_init=False"],
    "learning_rate": 0.0001,
    "unet_lr": 0.0001,
    "lr_scheduler": "constant_with_warmup",
    "lr_warmup_steps": 100,
    "train_batch_size": 1,
    "max_train_epochs": 10,
    "save_every_n_epochs": 2,
    "seed": 42,
    "caption_extension": ".txt",
    "shuffle_caption": False,
    "keep_tokens": 1,
    "xformers": False,
    "sdpa": True,
    "max_data_loader_n_workers": 0,
    "noise_offset": 0.03,
}


def export_lora_dataset(persona_id: int, *, trigger: str = "", repeats: int = 10, include_unrated: bool = False) -> dict:
    prof = inbox.get_profile(int(persona_id))
    if not prof:
        raise KeyError("Osoba ne postoji.")
    slug = slugify(prof.get("name") or f"osoba{persona_id}")
    trig = slugify(trigger or prof.get("name") or slug).replace("_", "") or slug
    items = list_gallery(persona_id=persona_id, rating=1, limit=200)["items"]
    if not items:
        raise ValueError("Nema slika ocijenjenih kao „Dobra” za ovu osobu. Ocijeni barem 15–30 dobrih slika.")
    root = data_dir() / "lora_datasets" / slug
    img_dir = root / "img" / f"{clamp_int(repeats, 1, 50, 10)}_{trig} woman"
    if img_dir.parent.exists():
        shutil.rmtree(img_dir.parent, ignore_errors=True)
    img_dir.mkdir(parents=True, exist_ok=True)
    (root / "model").mkdir(parents=True, exist_ok=True)
    (root / "log").mkdir(parents=True, exist_ok=True)
    age = image_gen.extract_adult_age(prof.get("age_vibe") or "", prof.get("appearance_prompt") or "")
    adult = f"adult woman, {age}" if age else "adult woman"
    appearance = image_gen.sanitize_appearance(prof.get("appearance_prompt") or "")[:300]
    written, skipped = 0, []
    for i, it in enumerate(items, 1):
        try:
            data = read_item_bytes(it)
        except Exception as exc:
            skipped.append(f"{it.get('filename')}: {exc}")
            continue
        ext = Path(it.get("filename") or "x.png").suffix.lower() or ".png"
        name = f"{i:03d}_{slug}"
        (img_dir / (name + ext)).write_bytes(data)
        scene = image_gen.strip_leading_portrait((it.get("prompt") or "").split(", (")[0])[:300]
        caption = ", ".join(x for x in (trig, adult, appearance, scene) if x)
        (img_dir / (name + ".txt")).write_text(caption + "\n", encoding="utf-8")
        written += 1
    if not written:
        raise RuntimeError("Nijedna slika nije kopirana: " + "; ".join(skipped[:3]))
    kohya = dict(KOHYA_SDXL_8GB)
    kohya.update({"train_data_dir": str(root / "img"), "output_dir": str(root / "model"), "output_name": f"{trig}_sdxl_lora", "logging_dir": str(root / "log")})
    (root / "kohya_sdxl_lora_8gb.json").write_text(json.dumps(kohya, ensure_ascii=False, indent=2), encoding="utf-8")
    onetrainer = {
        "__note": "OneTrainer: učitaj preset 'SDXL LoRA' pa prepiši ova polja.",
        "model_type": "STABLE_DIFFUSION_XL_10_BASE",
        "training_method": "LORA",
        "base_model_name": kohya["pretrained_model_name_or_path"],
        "output_model_destination": str(root / "model" / f"{trig}_sdxl_lora.safetensors"),
        "resolution": "768",
        "batch_size": 1,
        "epochs": 10,
        "learning_rate": 0.0001,
        "lora_rank": 16,
        "lora_alpha": 8,
        "train_text_encoder": False,
        "gradient_checkpointing": "ON",
        "train_dtype": "FLOAT_16",
        "optimizer": {"optimizer": "ADAFACTOR"},
        "concepts": [{"name": trig, "path": str(img_dir), "repeats": clamp_int(repeats, 1, 50, 10), "text": {"prompt_source": "sample"}}],
    }
    (root / "onetrainer_sdxl_lora_8gb.json").write_text(json.dumps(onetrainer, ensure_ascii=False, indent=2), encoding="utf-8")
    guide = f"""LoRA dataset za {prof.get('name')} (fiktivna odrasla osoba)
==========================================

Slike: {written} (ocjena „Dobra”), mapa: {img_dir}
Okidač (trigger): {trig}
Opisi (.txt) su pored svake slike — prvi token je okidač, zatim "{adult}".

Kohya_ss (SDXL LoRA, 8 GB):
  1. U Kohya GUI: LoRA -> Training -> Configuration file -> Load -> kohya_sdxl_lora_8gb.json
  2. Provjeri putanju do SDXL checkpointa (pretrained_model_name_or_path).
  3. Train. Gotova LoRA ide u: {root / 'model'}
OneTrainer: preset "SDXL LoRA", pa vrijednosti iz onetrainer_sdxl_lora_8gb.json.

Savjeti za RX 6600 (8 GB):
  - rezolucija 768, batch 1, gradient checkpointing, cache latents i text encoder outputs,
    samo UNet (network_train_unet_only), Adafactor, fp16 (RDNA2 nema bf16).
  - Trening na AMD-u pod Windowsom ide preko ZLUDA-e ili na Linuxu s ROCm-om; ako je presporo,
    isti dataset možeš trenirati na iznajmljenom GPU-u.
  - 15–30 raznolikih slika (kadrovi, svjetlo, odjeća) daje stabilnije lice od 100 sličnih.
  - Gotovu .safetensors datoteku kopiraj u C:\\ComfyUI-Zluda\\models\\loras i dodaj je osobi u LoRA stack.
"""
    (root / "UPUTE.txt").write_text(guide, encoding="utf-8")
    return {"ok": True, "folder": str(root), "images": written, "skipped": skipped, "trigger": trig,
            "files": ["kohya_sdxl_lora_8gb.json", "onetrainer_sdxl_lora_8gb.json", "UPUTE.txt"]}


# ---------- Character Sheet ----------

def queue_character_sheet(persona_id: int, body: dict | None = None) -> dict:
    prof = inbox.get_profile(int(persona_id))
    if not prof:
        raise KeyError("Osoba ne postoji.")
    body = dict(body or {})
    seed = body.get("seed")
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        seed = -1
    if seed < 0:
        stored = prof.get("locked_seed")
        try:
            seed = int(stored) if stored not in (None, "") and int(stored) >= 0 else random.randint(0, 2_000_000_000)
        except (TypeError, ValueError):
            seed = random.randint(0, 2_000_000_000)
    group = f"cs-{int(persona_id)}-{int(time.time() * 1000)}"
    jobs = []
    base = {**default_body_options(), "size_preset": "ig_square", "batch": 1}
    base.update({k: v for k, v in body.items() if k not in {"prompt", "seed", "template_id"}})
    if prof.get("preferred_model") and not base.get("model"):
        base["model"] = prof["preferred_model"]
    for i, (label, shot) in enumerate(CHARACTER_SHEET_SHOTS):
        b = dict(base)
        b.update({"prompt": shot, "persona_id": int(persona_id), "seed": seed, "lock_seed": True})
        b.pop("template_id", None)
        jobs.append(enqueue(b, label=f"Character sheet · {prof['name']} · {label}", kind="character_sheet", group_key=group))
    return {"ok": True, "group": group, "seed": seed, "jobs": jobs}


def _on_character_sheet_done(job: dict) -> None:
    if not job or job.get("kind") != "character_sheet" or not job.get("group_key"):
        return
    with conn() as c:
        rows = c.execute("SELECT * FROM generation_queue WHERE group_key=? ORDER BY id", (job["group_key"],)).fetchall()
    jobs = [_job_row(r) for r in rows]
    if any(j["status"] in {"queued", "running"} for j in jobs):
        return
    shots = []
    for (label, _p), j in zip(CHARACTER_SHEET_SHOTS, jobs):
        img = (j.get("images") or [None])[0]
        data = None
        if img and j["status"] == "done":
            try:
                data = read_item_bytes(img)
            except Exception:
                data = None
        shots.append((label, data))
    if not any(d for _l, d in shots):
        return
    prof = inbox.get_profile(job.get("persona_id")) or {}
    title = f"{prof.get('name') or 'Osoba'} · Character sheet · seed {(job.get('body') or {}).get('seed', '')}"
    png = stitch_contact_sheet(shots, title=title)
    fname = f"charsheet_{slugify(prof.get('name') or 'osoba')}_{int(time.time())}.png"
    path = gallery_dir() / fname
    path.write_bytes(png)
    record_images([{"filename": fname, "subfolder": "gallery", "type": "local"}], {"prompt": title, "seed": (job.get("body") or {}).get("seed")},
                  persona_id=job.get("persona_id"), source="character_sheet", local_path=str(path))


register_done_hook(_on_character_sheet_done)


def pil_available() -> bool:
    try:
        import PIL  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except Exception:
        return False


def stitch_contact_sheet(shots: list[tuple[str, bytes | None]], *, title: str = "", cell: int = 512, use_pil: bool | None = None) -> bytes:
    """2×2 kontakt list s oznakama. Pillow ako postoji, inače čisti Python PNG (bez teksta, s trakama)."""
    if use_pil is None:
        use_pil = pil_available()
    if use_pil:
        return _stitch_pil(shots, title=title, cell=cell)
    return _stitch_pure(shots, cell=min(cell, 384))


def _stitch_pil(shots, *, title: str, cell: int) -> bytes:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    pad, head, label_h = 16, 48, 34
    W = pad * 3 + cell * 2
    H = head + pad * 3 + (cell + label_h) * 2
    sheet = Image.new("RGB", (W, H), (22, 25, 32))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=20)
        font_s = ImageFont.load_default(size=16)
    except TypeError:  # stari Pillow
        font = font_s = ImageFont.load_default()
    draw.text((pad, 14), title[:90], fill=(228, 181, 106), font=font)
    for i, (label, data) in enumerate(shots[:4]):
        x = pad + (i % 2) * (cell + pad)
        y = head + pad + (i // 2) * (cell + label_h + pad)
        if data:
            try:
                im = Image.open(io.BytesIO(data)).convert("RGB")
                im = ImageOps.fit(im, (cell, cell), method=Image.LANCZOS, centering=(0.5, 0.35))
                sheet.paste(im, (x, y))
            except Exception:
                draw.rectangle([x, y, x + cell, y + cell], fill=(50, 30, 30))
        else:
            draw.rectangle([x, y, x + cell, y + cell], fill=(50, 30, 30))
            draw.text((x + 12, y + cell // 2), "Nije generirano", fill=(224, 122, 122), font=font_s)
        draw.rectangle([x, y + cell, x + cell, y + cell + label_h], fill=(30, 35, 45))
        draw.text((x + 10, y + cell + 8), f"{i + 1}. {label}", fill=(243, 239, 230), font=font_s)
    out = io.BytesIO()
    sheet.save(out, format="PNG", optimize=True)
    return out.getvalue()


# --- čisti Python PNG (rezerva bez Pillowa) ---

def _png_decode(data: bytes) -> tuple[int, int, list[bytearray]]:
    """Dekodiraj 8-bitni RGB/RGBA (ComfyUI SaveImage), bez interlace. Vrati (w, h, redovi RGB)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("nije PNG")
    pos, idat, w = 8, [], 0
    h = ctype = depth = interlace = 0
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b"IHDR":
            w, h, depth, ctype, _c, _f, interlace = struct.unpack(">IIBBBBB", chunk)
        elif typ == b"IDAT":
            idat.append(chunk)
        elif typ == b"IEND":
            break
    if depth != 8 or ctype not in (2, 6) or interlace:
        raise ValueError("nepodržan PNG format")
    bpp = 3 if ctype == 2 else 4
    raw = zlib.decompress(b"".join(idat))
    stride = w * bpp
    rows: list[bytearray] = []
    prev = bytearray(stride)
    i = 0
    for _y in range(h):
        f = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        if f == 1:
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 255
        elif f == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif f == 3:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 255
        elif f == 4:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 255
        rows.append(line)
        prev = line
    if bpp == 4:
        rows = [bytearray(b for k in range(0, len(r), 4) for b in r[k:k + 3]) for r in rows]
    return w, h, rows


def _png_encode(w: int, h: int, rows: list[bytearray]) -> bytes:
    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def _stitch_pure(shots, *, cell: int) -> bytes:
    pad, bar = 12, 10
    colors = [(228, 181, 106), (125, 206, 160), (217, 137, 122), (120, 150, 210)]
    W = pad * 3 + cell * 2
    H = pad * 3 + (cell + bar) * 2
    bg = bytes((22, 25, 32))
    canvas = [bytearray(bg * W) for _ in range(H)]
    for i, (_label, data) in enumerate(shots[:4]):
        ox = pad + (i % 2) * (cell + pad)
        oy = pad + (i // 2) * (cell + bar + pad)
        tile = None
        if data:
            try:
                w, h, rows = _png_decode(data)
                side = min(w, h)
                x0, y0 = (w - side) // 2, max(0, int((h - side) * 0.35))
                tile = []
                for ty in range(cell):
                    sy = y0 + ty * side // cell
                    src = rows[sy]
                    line = bytearray(cell * 3)
                    for tx in range(cell):
                        sx = (x0 + tx * side // cell) * 3
                        line[tx * 3:tx * 3 + 3] = src[sx:sx + 3]
                    tile.append(line)
            except Exception:
                tile = None
        for ty in range(cell):
            row = canvas[oy + ty]
            row[ox * 3:(ox + cell) * 3] = tile[ty] if tile else bytes((50, 30, 30)) * cell
        col = bytes(colors[i % 4])
        for ty in range(bar):
            canvas[oy + cell + ty][ox * 3:(ox + cell) * 3] = col * cell
    return _png_encode(W, H, canvas)
