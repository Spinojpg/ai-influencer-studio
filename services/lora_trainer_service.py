# -*- coding: utf-8 -*-
"""Character LoRA trener za RX 6600 (8 GB) + ComfyUI-Zluda.

Tijek: 15–40 slika osobe -> automatska priprema (EXIF, RGB, kvadratni rez, .txt opisi, Kohya mape + TOML)
-> kohya-ss/sd-scripts (sdxl_train_network.py / train_network.py) sa sigurnim 8 GB postavkama
-> praćenje napretka i temperature GPU-a (upozorenje 80 °C, kritično 88 °C, auto-stop 92 °C)
-> gotova .safetensors ide u ComfyUI models/loras i automatski se postavlja kao LoRA osobe (jačina 0.8 + okidač).

Svaka osoba ima vlastitu mapu <DATA_DIR>/lora_training/persona_<id>/{raw,prepared,output,logs}, vlastiti
jedinstveni okidač (chr_<ime>) i vlastite LoRA verzije. Istodobno radi najviše JEDNO treniranje.

Opisi su kratki i SFW: okidač + "adult woman" (+ dob ako je navedena) + izgled iz profila + kadar i svjetlo.
Osobe su uvijek fiktivne odrasle osobe. Korisnikove vlastite opise ne filtriramo.

Testni / napredni hookovi:
  STUDIO_LORA_TRAINER_CMD   zamjenska naredba treniranja (npr. lažni trener u testovima); dobiva
                            --config_file i --dataset_config (ili {config}/{dataset}/{output} u naredbi)
  STUDIO_LORA_TEMP_INTERVAL interval čitanja temperature u sekundama (zadano 5)
  STUDIO_SD_SCRIPTS_REF     verzija kohya-ss/sd-scripts za instalaciju (zadano SD_SCRIPTS_REF)
"""

from __future__ import annotations

import collections
import hashlib
import io
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

import comfy_launch
import image_gen
import inbox

from . import hardware_service
from .common import HttpError, clamp_float, clamp_int, conn, data_dir, http_request, jdump, jload, now, row_dict, slugify, truthy

# ---------- konstante ----------

SD_SCRIPTS_REF = "v0.13.1"
SD_SCRIPTS_ZIP_URL = "https://github.com/kohya-ss/sd-scripts/archive/refs/tags/{ref}.zip"

STATUSES = ("queued", "preparing", "caching", "training", "completed", "failed", "canceled", "paused_overheat")
ACTIVE_STATUSES = ("queued", "preparing", "caching", "training")
STATUS_LABELS = {
    "queued": "Na čekanju", "preparing": "Pripremam slike", "caching": "Učitavam model i spremam latente",
    "training": "Treniram", "completed": "Gotovo", "failed": "Greška", "canceled": "Zaustavljeno",
    "paused_overheat": "Zaustavljeno zbog topline",
}

IDEAL_MIN, IDEAL_MAX = 15, 40
HARD_MIN, HARD_MAX = 5, 60
MIN_SIDE = 256
RAW_MAX_SIDE = 2048
THUMB_SIDE = 256
UPLOAD_MAX_BYTES = 25_000_000

DEFAULT_RESOLUTION = {"sdxl": 768, "sd15": 512}
ALLOWED_RESOLUTIONS = {"sdxl": (768, 1024), "sd15": (512, 768)}
RANKS = (8, 16, 32)

# Grube procjene za RX 6600 + ZLUDA (sekundi po koraku, batch 1, gradient checkpointing).
SEC_PER_STEP = {"sdxl": {768: 2.6, 1024: 4.6}, "sd15": {512: 0.9, 768: 1.9}}
CACHE_OVERHEAD_S = {"sdxl": 240, "sd15": 90}

PRESETS = {
    "fast": {
        "label": "Brzi test", "hint": "Brza provjera dataseta, otprilike 15–25 min na RX 6600.",
        "epochs": 4, "target_steps": {"sdxl": 400, "sd15": 700}, "lr": 2e-4,
    },
    "balanced": {
        "label": "Preporučeno za RX 6600", "hint": "Dobra sličnost lica, sigurno za 8 GB VRAM-a.",
        "epochs": 8, "target_steps": {"sdxl": 1000, "sd15": 1500}, "lr": 1e-4,
    },
    "detailed": {
        "label": "Detaljnije", "hint": "Više koraka i epoha za finije detalje; traje dulje.",
        "epochs": 10, "target_steps": {"sdxl": 1600, "sd15": 2400}, "lr": 1e-4,
    },
}
DEFAULT_PRESET = "balanced"

TEMP_DEFAULTS = {"lora_temp_warn": "80", "lora_temp_critical": "88", "lora_temp_stop": "92", "lora_temp_autostop": "1"}

# Paketi koje NIKAD ne instaliramo na AMD/ZLUDA (CUDA-only ili nepotrebno teški). torch ostaje ComfyUI-jev.
SKIP_PACKAGES = {"bitsandbytes", "xformers", "tensorboard", "tensorboardx", "opencv-python", "opencv-python-headless",
                 "numpy", "torch", "torchvision", "torchaudio", "schedulefree", "pytorch-optimizer",
                 "prodigy-plus-schedule-free", "prodigyopt", "sentencepiece"}
FALLBACK_REQUIREMENTS = ["accelerate", "transformers", "diffusers", "safetensors", "toml", "voluptuous", "imagesize",
                         "einops", "ftfy", "huggingface-hub", "rich", "lion-pytorch"]

_jobs_lock = threading.Lock()
_procs: dict = {}
_cancel: dict = {}
_threads: dict = {}
_install: dict = {"running": False, "step": "", "progress": 0.0, "log": [], "error": "", "done": False, "started_at": None}
_install_lock = threading.Lock()
_torch_probe: dict = {"running": False, "result": None, "at": 0.0}
_cfg: dict = {}


def configure(**kwargs) -> None:
    """Testovi / studio.py: comfy_url, runner_cmd (lista), temp_interval."""
    _cfg.update(kwargs)


# ---------- shema ----------

def ensure_schema() -> None:
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS lora_training_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                lora_name TEXT DEFAULT '',
                trigger_word TEXT DEFAULT '',
                base_model TEXT DEFAULT '',
                arch TEXT DEFAULT '',
                preset TEXT DEFAULT 'balanced',
                image_count INTEGER DEFAULT 0,
                total_steps INTEGER DEFAULT 0,
                current_step INTEGER DEFAULT 0,
                current_epoch INTEGER DEFAULT 0,
                total_epochs INTEGER DEFAULT 0,
                progress_pct REAL DEFAULT 0,
                loss REAL,
                eta_seconds REAL,
                gpu_temp_c REAL,
                gpu_temp_peak_c REAL,
                gpu_temp_status TEXT DEFAULT 'unavailable',
                gpu_warning_message TEXT DEFAULT '',
                output_path TEXT DEFAULT '',
                error_message TEXT DEFAULT '',
                log_tail TEXT DEFAULT '',
                config_json TEXT DEFAULT '{}',
                created_at REAL NOT NULL,
                started_at REAL,
                finished_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_lora_jobs_profile ON lora_training_jobs(profile_id, id);
            CREATE TABLE IF NOT EXISTS persona_trained_loras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                lora_filename TEXT NOT NULL,
                trigger_word TEXT DEFAULT '',
                strength REAL DEFAULT 0.8,
                base_model TEXT DEFAULT '',
                arch TEXT DEFAULT '',
                job_id INTEGER,
                is_active INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_trained_loras_profile ON persona_trained_loras(profile_id, id);
            CREATE TABLE IF NOT EXISTS lora_dataset_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                original_name TEXT DEFAULT '',
                sha1 TEXT DEFAULT '',
                source TEXT DEFAULT 'upload',
                source_ref TEXT DEFAULT '',
                width INTEGER DEFAULT 0,
                height INTEGER DEFAULT 0,
                brightness REAL DEFAULT 128,
                caption_custom TEXT DEFAULT '',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_lora_ds_profile ON lora_dataset_images(profile_id, id);
            """
        )
        # Postojeća shema profila ostaje; dodaje se samo okidač trenirane LoRA-e.
        inbox._ensure_column(c, "profiles", "lora_trigger", "TEXT DEFAULT ''")
        for key, val in TEMP_DEFAULTS.items():
            c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (key, val))
        # Treniranje ne preživi gašenje Studija (proces se ugasi s njim).
        marks = ",".join("?" * len(ACTIVE_STATUSES))
        c.execute(
            f"UPDATE lora_training_jobs SET status='failed', finished_at=?, error_message=? WHERE status IN ({marks})",
            (now(), "Studio je zatvoren tijekom treniranja. Pokreni treniranje ponovno.", *ACTIVE_STATUSES),
        )


# ---------- putanje ----------

def trainer_root() -> Path:
    return data_dir() / "trainer"


def sd_scripts_dir() -> Path:
    return trainer_root() / "sd-scripts"


def trainer_venv_dir() -> Path:
    return trainer_root() / "venv"


def persona_root(pid: int) -> Path:
    return data_dir() / "lora_training" / f"persona_{int(pid)}"


def persona_dirs(pid: int) -> dict:
    root = persona_root(pid)
    out = {"root": root, "raw": root / "raw", "thumbs": root / "raw" / "thumbs", "prepared": root / "prepared",
           "output": root / "output", "logs": root / "logs"}
    for k, p in out.items():
        if k != "root":
            p.mkdir(parents=True, exist_ok=True)
    return out


def loras_target_dir() -> tuple:
    """(mapa, u_comfyui). ComfyUI models/loras ako ComfyUI mapa postoji, inače <DATA_DIR>/trained_loras."""
    try:
        if comfy_launch.comfy_dir().is_dir() or (os.environ.get("COMFYUI_LORAS_DIR") or "").strip():
            d = comfy_launch.loras_dir()
            d.mkdir(parents=True, exist_ok=True)
            return d, True
    except OSError:
        pass
    d = data_dir() / "trained_loras"
    d.mkdir(parents=True, exist_ok=True)
    return d, False


# ---------- postavke temperature ----------

def temp_settings() -> dict:
    s = {k: inbox.get_setting(k, v) for k, v in TEMP_DEFAULTS.items()}
    return {
        "warn_c": clamp_float(s["lora_temp_warn"], 50, 110, 80.0),
        "critical_c": clamp_float(s["lora_temp_critical"], 55, 115, 88.0),
        "stop_c": clamp_float(s["lora_temp_stop"], 60, 120, 92.0),
        "autostop": truthy(s["lora_temp_autostop"], True),
    }


def save_temp_settings(payload: dict) -> dict:
    cur = temp_settings()
    warn = clamp_float(payload.get("warn_c", cur["warn_c"]), 50, 110, cur["warn_c"])
    crit = clamp_float(payload.get("critical_c", cur["critical_c"]), 55, 115, cur["critical_c"])
    stop = clamp_float(payload.get("stop_c", cur["stop_c"]), 60, 120, cur["stop_c"])
    if not (warn < crit <= stop):
        raise ValueError("Pragovi moraju biti redom: upozorenje < kritično ≤ auto-stop.")
    inbox.set_setting("lora_temp_warn", str(warn))
    inbox.set_setting("lora_temp_critical", str(crit))
    inbox.set_setting("lora_temp_stop", str(stop))
    if "autostop" in payload:
        inbox.set_setting("lora_temp_autostop", "1" if truthy(payload.get("autostop"), True) else "0")
    return temp_settings()


def classify_temp(temp_c, th: dict | None = None) -> tuple:
    """(status, poruka) za temperaturu: ok / warn / critical / unavailable."""
    th = th or temp_settings()
    if temp_c is None:
        return "unavailable", "Senzor temperature nedostupan"
    t = float(temp_c)
    if t >= th["critical_c"]:
        return "critical", f"GPU je prevruć ({t:.0f}°C)! Provjeri ventilatore odmah. Kod {th['stop_c']:.0f}°C treniranje se automatski zaustavlja."
    if t >= th["warn_c"]:
        return "warn", f"GPU temperatura je visoka ({t:.0f}°C). Provjeri ventilatore i protok zraka."
    return "ok", ""


# ---------- okidač ----------

def _ascii_slug(text: str) -> str:
    return slugify(text or "", fallback="").replace("_", "")[:20]


def ensure_trigger(pid: int) -> str:
    prof = inbox.get_profile(int(pid))
    if not prof:
        raise KeyError("Osoba ne postoji.")
    cur = (prof.get("lora_trigger") or "").strip()
    if cur:
        return cur
    base = "chr_" + (_ascii_slug(prof.get("name") or "") or f"osoba{pid}")
    with conn() as c:
        taken = {str(r[0] or "").lower() for r in c.execute("SELECT lora_trigger FROM profiles WHERE id<>?", (int(pid),)).fetchall()}
        trig = base if base.lower() not in taken else f"{base}{int(pid)}"
        n = 2
        while trig.lower() in taken:
            trig = f"{base}{int(pid)}x{n}"
            n += 1
        c.execute("UPDATE profiles SET lora_trigger=? WHERE id=?", (trig, int(pid)))
    try:
        inbox.export_profiles_json()
    except Exception:
        pass
    return trig


# ---------- opisi (captions) ----------

_TRAIT_RE = re.compile(
    r"(?i)\b(hair|eyes?|eyebrows|freckles?|skin|complexion|lips|makeup|tattoos?|piercings?|glasses|bangs|fringe|ponytail|"
    r"braids?|curly|wavy|straight|blonde?|brunette|redhead|ginger|bob|dimples?|beauty mark|mole)\b"
)
_TRAIT_SKIP_RE = re.compile(r"(?i)\b(adult|woman|girl|years?\s*old|portrait|photo|photograph|camera|lighting|light|background|realistic|masterpiece|quality|\d{2})\b")


def adult_tag(prof) -> str:
    prof = prof or {}
    age = image_gen.extract_adult_age(str(prof.get("age_vibe") or ""), str(prof.get("appearance_prompt") or ""))
    return f"adult woman, {age} years old" if age else "adult woman"


def persona_traits(prof, limit: int = 4) -> list:
    text = image_gen.sanitize_appearance(str((prof or {}).get("appearance_prompt") or ""), drop_conflicts=True)
    out: list = []
    for seg in re.split(r"[,;\n]+", text):
        seg = re.sub(r":\s*[\d.]+\s*\)?\s*$", "", seg.strip())
        seg = re.sub(r"[()\[\]{}]", " ", seg)
        seg = re.sub(r"\s+", " ", seg).strip(" .")
        if not seg or len(seg) > 60 or not _TRAIT_RE.search(seg) or _TRAIT_SKIP_RE.search(seg):
            continue
        if seg.lower() not in (x.lower() for x in out):
            out.append(seg)
        if len(out) >= limit:
            break
    return out


def framing_tag(width: int, height: int) -> str:
    if not width or not height:
        return "portrait"
    ratio = float(height) / float(width)
    if ratio >= 1.15:
        return "portrait"
    if ratio <= 0.87:
        return "wide shot"
    return "close-up"


def lighting_tag(brightness) -> str:
    b = float(brightness if brightness is not None else 128)
    if b >= 170:
        return "bright lighting"
    if b <= 70:
        return "low light"
    return "soft natural lighting"


def build_caption(prof, trigger: str, width: int, height: int, brightness) -> str:
    parts = [trigger, adult_tag(prof), *persona_traits(prof), framing_tag(width, height), lighting_tag(brightness)]
    seen, out = set(), []
    for p in parts:
        p = (p or "").strip()
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return ", ".join(out)


def effective_caption(row: dict, prof, trigger: str) -> str:
    custom = (row.get("caption_custom") or "").strip()
    if custom:
        if not re.search(r"(?i)(^|[\s,])" + re.escape(trigger) + r"($|[\s,])", custom):
            custom = f"{trigger}, {custom}"
        return custom
    return build_caption(prof, trigger, int(row.get("width") or 0), int(row.get("height") or 0), float(row.get("brightness") or 128))


# ---------- slike ----------

def pil_ok() -> bool:
    try:
        from PIL import Image, ImageOps  # noqa: F401
        return True
    except Exception:
        return False


def _need_pil():
    try:
        from PIL import Image, ImageOps, ImageStat
        return Image, ImageOps, ImageStat
    except Exception:
        raise RuntimeError("Za pripremu slika treba Pillow (u ComfyUI venvu: python -m pip install pillow).") from None


def load_image_rgb(data: bytes, name: str = "slika"):
    """EXIF rotacija + RGB. Baca ValueError s hrvatskom porukom za oštećene ili premale slike."""
    Image, ImageOps, _ = _need_pil()
    label = Path(name or "slika").name[:80]
    if not data or len(data) < 32:
        raise ValueError(f"„{label}” je prazna datoteka.")
    if len(data) > UPLOAD_MAX_BYTES:
        raise ValueError(f"„{label}” je prevelika (više od 25 MB).")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        raise ValueError(f"„{label}” nije ispravna slika ili je oštećena (podržano: JPG, PNG, WEBP).") from None
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if min(w, h) < MIN_SIDE:
        raise ValueError(f"„{label}” je premala ({w}×{h}). Treba barem {MIN_SIDE} px po kraćoj strani.")
    return img


def _brightness(img) -> float:
    _, _, ImageStat = _need_pil()
    small = img.copy()
    small.thumbnail((128, 128))
    return round(float(ImageStat.Stat(small.convert("L")).mean[0]), 1)


def square_crop_box(w: int, h: int) -> tuple:
    """Kvadratni rez: portret čuva gornju trećinu (lice), pejzaž ide po sredini."""
    side = min(w, h)
    if h > w:
        top = int(round((h - side) * 0.2))
        return 0, top, side, top + side
    left = (w - side) // 2
    return left, 0, left + side, side


def _thumb(img) -> bytes:
    Image, _, _ = _need_pil()
    t = img.crop(square_crop_box(*img.size)).resize((THUMB_SIDE, THUMB_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    t.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _ds_row(row) -> dict:
    d = row_dict(row)
    d["url"] = f"/api/lora-trainer/dataset/{d['profile_id']}/file/{d['id']}"
    d["thumb_url"] = d["url"] + "?thumb=1"
    return d


def dataset_rows(pid: int) -> list:
    with conn() as c:
        rows = c.execute("SELECT * FROM lora_dataset_images WHERE profile_id=? ORDER BY id", (int(pid),)).fetchall()
    return [_ds_row(r) for r in rows]


def count_guidance(n: int) -> dict:
    if n < HARD_MIN:
        return {"level": "blocked", "color": "bad", "can_train": False,
                "message": f"Premalo slika za treniranje (najmanje {HARD_MIN}). Preporuka je {IDEAL_MIN}–{IDEAL_MAX}."}
    if n < IDEAL_MIN:
        return {"level": "low", "color": "warn", "can_train": True, "message": f"Premalo slika, preporuka je {IDEAL_MIN}–{IDEAL_MAX}."}
    if n <= IDEAL_MAX:
        return {"level": "ideal", "color": "ok", "can_train": True, "message": "Idealno"}
    if n <= HARD_MAX:
        return {"level": "high", "color": "warn", "can_train": True, "message": f"Previše slika, preporuka je do {IDEAL_MAX}."}
    return {"level": "blocked", "color": "bad", "can_train": False,
            "message": f"Previše slika za treniranje (najviše {HARD_MAX}). Obriši višak, preporuka je do {IDEAL_MAX}."}


def dataset_state(pid: int) -> dict:
    if not inbox.get_profile(int(pid)):
        raise KeyError("Osoba ne postoji.")
    trig = ensure_trigger(pid)
    prof = inbox.get_profile(int(pid))
    items = []
    for r in dataset_rows(pid):
        r["caption"] = effective_caption(r, prof, trig)
        r["caption_auto"] = build_caption(prof, trig, int(r.get("width") or 0), int(r.get("height") or 0), float(r.get("brightness") or 128))
        items.append(r)
    return {"ok": True, "profile_id": int(pid), "trigger": trig, "count": len(items), "items": items,
            "guidance": count_guidance(len(items)), "ideal": [IDEAL_MIN, IDEAL_MAX], "limits": [HARD_MIN, HARD_MAX]}


def add_images(pid: int, files: list, *, source: str = "upload", source_refs: list | None = None) -> dict:
    """Dodaj slike u dataset osobe. files: [(bytes, ime)]. Vrati {added, skipped, dataset}."""
    if not inbox.get_profile(int(pid)):
        raise KeyError("Osoba ne postoji.")
    Image, _, _ = _need_pil()
    dirs = persona_dirs(pid)
    with conn() as c:
        existing = {r[0] for r in c.execute("SELECT sha1 FROM lora_dataset_images WHERE profile_id=?", (int(pid),)).fetchall()}
        count = c.execute("SELECT COUNT(*) FROM lora_dataset_images WHERE profile_id=?", (int(pid),)).fetchone()[0]
    added, skipped = [], []
    for i, (data, name) in enumerate(files):
        label = Path(name or f"slika_{i + 1}").name[:80]
        ref = (source_refs[i] if source_refs and i < len(source_refs) else "") or ""
        digest = hashlib.sha1(data or b"").hexdigest()
        if digest in existing:
            skipped.append({"name": label, "reason": "Ova slika je već u datasetu."})
            continue
        if count >= HARD_MAX:
            skipped.append({"name": label, "reason": f"Dataset već ima {HARD_MAX} slika (najviše)."})
            continue
        try:
            img = load_image_rgb(data, label)
        except (ValueError, RuntimeError) as exc:
            skipped.append({"name": label, "reason": str(exc)})
            continue
        w, h = img.size
        bright = _brightness(img)
        stored = img
        if max(w, h) > RAW_MAX_SIDE:
            stored = img.copy()
            stored.thumbnail((RAW_MAX_SIDE, RAW_MAX_SIDE), Image.LANCZOS)
        fname = f"img_{int(time.time() * 1000)}_{digest[:8]}.jpg"
        stored.save(dirs["raw"] / fname, "JPEG", quality=95)
        (dirs["thumbs"] / fname).write_bytes(_thumb(img))
        with conn() as c:
            c.execute(
                "INSERT INTO lora_dataset_images(profile_id, filename, original_name, sha1, source, source_ref, width, height, brightness, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (int(pid), fname, label, digest, source, ref, w, h, bright, now()),
            )
        existing.add(digest)
        count += 1
        added.append({"name": label, "file": fname, "width": w, "height": h})
    return {"ok": True, "added": added, "skipped": skipped, "dataset": dataset_state(pid)}


def import_from_persona(pid: int, sources: list | None = None) -> dict:
    """1 klik: referentne slike osobe + slike iz galerije ocijenjene „Dobra”."""
    prof = inbox.get_profile(int(pid))
    if not prof:
        raise KeyError("Osoba ne postoji.")
    sources = [s for s in (sources or ["refs", "good"]) if s in {"refs", "good"}] or ["refs", "good"]
    groups: dict = {"ref": ([], []), "gallery": ([], [])}
    if "refs" in sources:
        for item in prof.get("reference_items") or []:
            rel = item.get("path") or ""
            p = inbox._safe_rel(rel) if rel else None
            if not (p and p.is_file()):
                p = inbox._safe_rel(item.get("thumb") or "") if item.get("thumb") else None
            if p and p.is_file():
                groups["ref"][0].append((p.read_bytes(), p.name))
                groups["ref"][1].append("ref:" + rel)
    if "good" in sources:
        from . import generation_service
        for it in generation_service.list_gallery(persona_id=pid, rating=1, limit=200)["items"]:
            try:
                groups["gallery"][0].append((generation_service.read_item_bytes(it), it.get("filename") or f"galerija_{it['id']}.png"))
                groups["gallery"][1].append(f"gallery:{it['id']}")
            except Exception:
                continue
    if not groups["ref"][0] and not groups["gallery"][0]:
        raise ValueError("Ova osoba još nema referentnih slika ni slika ocijenjenih kao „Dobra” u galeriji.")
    added, skipped = [], []
    for kind, (files, refs) in groups.items():
        if files:
            res = add_images(pid, files, source=kind, source_refs=refs)
            added += res["added"]
            skipped += res["skipped"]
    return {"ok": True, "added": added, "skipped": skipped, "dataset": dataset_state(pid)}


def _ds_get(pid: int, img_id: int) -> dict:
    with conn() as c:
        row = c.execute("SELECT * FROM lora_dataset_images WHERE id=? AND profile_id=?", (int(img_id), int(pid))).fetchone()
    if not row:
        raise KeyError("Slika nije u datasetu.")
    return _ds_row(row)


def image_file(pid: int, img_id: int, thumb: bool = False):
    row = _ds_get(pid, img_id)
    dirs = persona_dirs(pid)
    p = (dirs["thumbs"] if thumb else dirs["raw"]) / Path(row["filename"]).name
    return p if p.is_file() else None


def _unlink_ds_files(pid: int, fname: str) -> None:
    dirs = persona_dirs(pid)
    for p in (dirs["raw"] / Path(fname).name, dirs["thumbs"] / Path(fname).name):
        try:
            p.unlink()
        except OSError:
            pass


def _guard_not_training(pid: int) -> None:
    a = active_job()
    if a and int(a["profile_id"]) == int(pid):
        raise RuntimeError("Treniranje ove osobe je u tijeku. Pričekaj ili ga zaustavi prije mijenjanja slika.")


def delete_image(pid: int, img_id: int) -> dict:
    _guard_not_training(pid)
    row = _ds_get(pid, img_id)
    with conn() as c:
        c.execute("DELETE FROM lora_dataset_images WHERE id=?", (int(img_id),))
    _unlink_ds_files(pid, row["filename"])
    return dataset_state(pid)


def clear_dataset(pid: int) -> dict:
    _guard_not_training(pid)
    for r in dataset_rows(pid):
        _unlink_ds_files(pid, r["filename"])
    with conn() as c:
        c.execute("DELETE FROM lora_dataset_images WHERE profile_id=?", (int(pid),))
    return dataset_state(pid)


def set_caption(pid: int, img_id: int, caption: str) -> dict:
    _ds_get(pid, img_id)
    text = re.sub(r"\s+", " ", str(caption or "")).strip()[:600]
    with conn() as c:
        c.execute("UPDATE lora_dataset_images SET caption_custom=? WHERE id=?", (text, int(img_id)))
    return dataset_state(pid)


# ---------- priprema za Kohya ----------

def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)


def to_toml(flat: dict) -> str:
    return "".join(f"{k} = {_toml_value(v)}\n" for k, v in flat.items() if v is not None)


def _posix(p) -> str:
    return str(p).replace("\\", "/")


def prepare_dataset(pid: int, *, resolution: int, trigger: str, repeats: int) -> dict:
    """raw -> prepared/img/<repeats>_<trigger>/NNN.png + .txt i prepared/dataset.toml (Kohya)."""
    Image, _, _ = _need_pil()
    prof = inbox.get_profile(int(pid))
    rows = dataset_rows(pid)
    if not rows:
        raise ValueError("Dataset je prazan.")
    dirs = persona_dirs(pid)
    prep = dirs["prepared"]
    if prep.exists():
        shutil.rmtree(prep, ignore_errors=True)
    img_dir = prep / "img" / f"{int(repeats)}_{trigger}"
    img_dir.mkdir(parents=True, exist_ok=True)
    written, skipped = 0, []
    for r in rows:
        src = dirs["raw"] / Path(r["filename"]).name
        try:
            with Image.open(src) as im:
                im.load()
                img = im.convert("RGB")
        except Exception:
            skipped.append(r.get("original_name") or r["filename"])
            continue
        out = img.crop(square_crop_box(*img.size)).resize((int(resolution), int(resolution)), Image.LANCZOS)
        written += 1
        stem = f"{written:03d}_{trigger}"
        out.save(img_dir / f"{stem}.png", "PNG")
        (img_dir / f"{stem}.txt").write_text(effective_caption(r, prof, trigger) + "\n", encoding="utf-8")
    if written < HARD_MIN:
        raise ValueError(f"Nakon pripreme ostalo je samo {written} ispravnih slika (treba barem {HARD_MIN}).")
    ds_toml = prep / "dataset.toml"
    ds_toml.write_text(
        "[general]\n"
        'caption_extension = ".txt"\n'
        "shuffle_caption = false\n"
        "keep_tokens = 1\n"
        "enable_bucket = false\n\n"
        "[[datasets]]\n"
        f"resolution = {int(resolution)}\n"
        "batch_size = 1\n\n"
        "  [[datasets.subsets]]\n"
        f"  image_dir = {_toml_value(_posix(img_dir))}\n"
        f"  num_repeats = {int(repeats)}\n",
        encoding="utf-8",
    )
    return {"img_dir": img_dir, "dataset_toml": ds_toml, "images": written, "skipped": skipped}


# ---------- bazni model i plan ----------

def list_base_checkpoints() -> list:
    out = []
    try:
        names = comfy_launch.list_files_recursive(comfy_launch.checkpoints_dir())
    except Exception:
        names = []
    for n in names:
        if not str(n).lower().endswith((".safetensors", ".ckpt")):
            continue
        arch = image_gen.detect_model_arch(n)
        if arch in {"sdxl", "sd15"}:
            out.append({"name": n, "arch": arch})
    return out


def resolve_base_model(prof: dict, override: str = "") -> tuple:
    """(ime, arch). Prednost: odabir u Napredno -> preferirani model osobe -> prvi SDXL u models/checkpoints."""
    name = (override or "").strip()
    type_override = ""
    if not name:
        name = (prof.get("preferred_model") or "").strip()
        type_override = prof.get("model_type") or ""
    if not name:
        cks = list_base_checkpoints()
        sdxl = [c for c in cks if c["arch"] == "sdxl"]
        name = (sdxl or cks or [{"name": ""}])[0]["name"]
    if not name:
        raise ValueError("Nije pronađen nijedan SDXL ili SD 1.5 model u ComfyUI models/checkpoints. Preuzmi model u kartici Modeli.")
    arch = image_gen.detect_model_arch(name, type_override if type_override not in ("", "auto") else "")
    if arch == "krea2":
        raise ValueError("Krea 2 model se ne može koristiti za treniranje character LoRA-e. "
                         "Odaberi SDXL ili SD 1.5 model (npr. RealVisXL ili Realistic Vision) u Napredno ili u profilu osobe.")
    return name, arch


def checkpoint_path(name: str) -> Path:
    parts = [p for p in str(name).replace("\\", "/").split("/") if p and p not in (".", "..")]
    return comfy_launch.checkpoints_dir().joinpath(*parts)


def compute_plan(pid: int, preset: str = DEFAULT_PRESET, advanced: dict | None = None) -> dict:
    prof = inbox.get_profile(int(pid))
    if not prof:
        raise KeyError("Osoba ne postoji.")
    adv = dict(advanced or {})
    preset = preset if preset in PRESETS else DEFAULT_PRESET
    p = PRESETS[preset]
    base, arch = resolve_base_model(prof, str(adv.get("base_model") or ""))
    n = len(dataset_rows(pid))
    res = clamp_int(adv.get("resolution"), 256, 2048, DEFAULT_RESOLUTION[arch])
    if res not in ALLOWED_RESOLUTIONS[arch]:
        res = DEFAULT_RESOLUTION[arch]
    rank = clamp_int(adv.get("rank") or adv.get("network_dim"), 4, 64, 16)
    if rank not in RANKS:
        rank = 16
    epochs = clamp_int(adv.get("epochs"), 1, 30, p["epochs"])
    target = clamp_int(adv.get("steps"), 100, 6000, p["target_steps"][arch])
    repeats = max(1, min(100, math.ceil(target / max(1, n * epochs)))) if n else 1
    total = n * repeats * epochs
    lr = clamp_float(adv.get("learning_rate"), 1e-6, 1e-2, p["lr"])
    sps = SEC_PER_STEP[arch].get(res) or SEC_PER_STEP[arch][DEFAULT_RESOLUTION[arch]]
    eta = int(total * sps + CACHE_OVERHEAD_S[arch])
    th = temp_settings()
    if adv.get("temp_stop") not in (None, ""):
        th["stop_c"] = clamp_float(adv.get("temp_stop"), 60, 120, th["stop_c"])
        th["critical_c"] = min(th["critical_c"], th["stop_c"])
        th["warn_c"] = min(th["warn_c"], th["critical_c"] - 1)
    if "autostop" in adv:
        th["autostop"] = truthy(adv.get("autostop"), True)
    warnings = []
    if arch == "sdxl" and res > 768:
        warnings.append("1024 px na 8 GB VRAM-a je na rubu; ako javi „out of memory”, vrati na 768.")
    if not th["autostop"]:
        warnings.append("Auto-stop zbog temperature je isključen.")
    return {
        "profile_id": int(pid), "preset": preset, "preset_label": p["label"], "base_model": base, "arch": arch,
        "resolution": res, "rank": rank, "alpha": max(1, rank // 2), "epochs": epochs, "repeats": repeats,
        "image_count": n, "total_steps": total, "learning_rate": lr, "eta_seconds": eta,
        "temp": th, "warnings": warnings, "guidance": count_guidance(n),
    }


def build_training_config(plan: dict, *, base_path, output_dir, output_name: str, logs_dir) -> dict:
    """Sigurne 8 GB (RX 6600 + ZLUDA) postavke za kohya-ss/sd-scripts --config_file.

    Nikad xformers ni bitsandbytes (ne rade na AMD/ZLUDA): SDPA + Adafactor, fp16, batch 1,
    gradient checkpointing, latente (i za SDXL izlazi text encodera) keširani na disk.
    """
    arch = plan["arch"]
    lr = float(plan["learning_rate"])
    cfg = {
        "pretrained_model_name_or_path": _posix(base_path),
        "output_dir": _posix(output_dir),
        "output_name": output_name,
        "save_model_as": "safetensors",
        "save_precision": "fp16",
        "network_module": "networks.lora",
        "network_dim": int(plan["rank"]),
        "network_alpha": int(plan["alpha"]),
        "resolution": f"{plan['resolution']},{plan['resolution']}",
        "max_train_epochs": int(plan["epochs"]),
        "train_batch_size": 1,
        "gradient_checkpointing": True,
        "mixed_precision": "fp16",
        "cache_latents": True,
        "cache_latents_to_disk": True,
        "optimizer_type": "Adafactor",
        "optimizer_args": ["scale_parameter=False", "relative_step=False", "warmup_init=False"],
        "learning_rate": lr,
        "unet_lr": lr,
        "lr_scheduler": "constant_with_warmup",
        "lr_warmup_steps": max(10, int(plan["total_steps"] * 0.05)),
        "sdpa": True,
        "xformers": False,
        "no_half_vae": True,
        "max_data_loader_n_workers": 0,
        "seed": 42,
        "noise_offset": 0.03,
        "logging_dir": _posix(logs_dir),
        "tokenizer_cache_dir": _posix(trainer_root() / "tokenizers"),
    }
    if arch == "sdxl":
        cfg.update({"network_train_unet_only": True, "cache_text_encoder_outputs": True, "cache_text_encoder_outputs_to_disk": True})
    else:
        cfg.update({"network_train_unet_only": False, "text_encoder_lr": lr / 2, "clip_skip": 1})
    return cfg


# ---------- Python / sd-scripts okruženje ----------

def comfy_python() -> tuple:
    """(python, izvor). ComfyUI venv -> python_embeded -> venv/bin/python -> Python Studija."""
    root = comfy_launch.comfy_dir()
    for rel, label in ((("venv", "Scripts", "python.exe"), "ComfyUI venv"), (("python_embeded", "python.exe"), "ComfyUI python_embeded"),
                       (("venv", "bin", "python"), "ComfyUI venv"), ((".venv", "Scripts", "python.exe"), "ComfyUI .venv"),
                       ((".venv", "bin", "python"), "ComfyUI .venv")):
        p = root.joinpath(*rel)
        if p.is_file():
            return p, label
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").is_file():
        exe = exe.with_name("python.exe")
    return exe, "Python Studija"


def trainer_python():
    v = trainer_venv_dir()
    for rel in (("Scripts", "python.exe"), ("bin", "python")):
        p = v.joinpath(*rel)
        if p.is_file():
            return p
    return None


def backend_ready() -> bool:
    d = sd_scripts_dir()
    return ((d / "sdxl_train_network.py").is_file() and (d / "train_network.py").is_file() and trainer_python() is not None
            and (trainer_root() / ".studio_ready").is_file())


def _override_cmd():
    if _cfg.get("runner_cmd"):
        return list(_cfg["runner_cmd"])
    raw = (os.environ.get("STUDIO_LORA_TRAINER_CMD") or "").strip()
    if not raw:
        return None
    return shlex.split(raw, posix=(os.name != "nt"))


def _no_window() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if sys.platform == "win32" else 0


def _probe_torch_now(py) -> dict:
    code = ("import json\n"
            "try:\n"
            "    import torch\n"
            "    ok = torch.cuda.is_available()\n"
            "    name = torch.cuda.get_device_name(0) if ok else ''\n"
            "    print('TORCH=' + json.dumps({'ok': True, 'version': torch.__version__, 'cuda': ok, 'device': name, 'zluda': '[ZLUDA]' in name}))\n"
            "except Exception as e:\n"
            "    print('TORCH=' + json.dumps({'ok': False, 'error': str(e)[:300]}))\n")
    env = dict(os.environ, TORCH_BACKENDS_CUDNN_ENABLED="0", PYTHONUTF8="1")
    try:
        r = subprocess.run([str(py), "-c", code], capture_output=True, text=True, timeout=180, env=env, creationflags=_no_window())
        line = [ln for ln in (r.stdout or "").splitlines() if ln.startswith("TORCH=")]
        if line:
            return json.loads(line[-1][6:])
        return {"ok": False, "error": ((r.stderr or r.stdout or "").strip()[-300:] or f"izlaz {r.returncode}")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


def torch_status(refresh: bool = False) -> dict:
    """PyTorch provjera ide u pozadini (ZLUDA zna trebati 10+ s); vraća zadnji poznati rezultat."""
    st = _torch_probe
    if (refresh or st["result"] is None) and not st["running"]:
        py = trainer_python() or comfy_python()[0]
        if py and Path(py).is_file() and _override_cmd() is None:
            st["running"] = True

            def work():
                try:
                    st["result"] = _probe_torch_now(py)
                    st["at"] = time.time()
                finally:
                    st["running"] = False

            threading.Thread(target=work, daemon=True, name="lora-torch-probe").start()
    res = dict(st["result"] or {})
    res["checking"] = st["running"]
    return res


def status(refresh: bool = False) -> dict:
    cdir = comfy_launch.comfy_dir()
    py, py_src = comfy_python()
    cks = list_base_checkpoints()
    temp = hardware_service.read_gpu_temperature()
    t_status, t_msg = classify_temp(temp.get("temp_c") if temp.get("available") else None)
    override = _override_cmd() is not None
    ready = backend_ready()
    lt, in_comfy = loras_target_dir()
    return {
        "ok": True,
        "ready": ready or override,
        "backend_installed": ready,
        "override_cmd": override,
        "comfy_dir": str(cdir), "comfy_dir_exists": cdir.is_dir(),
        "python": str(py) if py else "", "python_source": py_src, "python_exists": bool(py and Path(py).is_file()),
        "trainer_python": str(trainer_python() or ""),
        "torch": torch_status(refresh),
        "sd_scripts_dir": str(sd_scripts_dir()), "sd_scripts_ref": os.environ.get("STUDIO_SD_SCRIPTS_REF") or SD_SCRIPTS_REF,
        "checkpoints": cks,
        "has_sdxl": any(c["arch"] == "sdxl" for c in cks), "has_sd15": any(c["arch"] == "sd15" for c in cks),
        "gpu_temp": {**temp, "status": t_status, "message": t_msg},
        "temp_settings": temp_settings(),
        "loras_dir": str(lt), "loras_in_comfy": in_comfy,
        "pil": pil_ok(),
        "presets": [{"id": k, "label": v["label"], "hint": v["hint"]} for k, v in PRESETS.items()],
        "default_preset": DEFAULT_PRESET,
        "resolutions": {k: list(v) for k, v in ALLOWED_RESOLUTIONS.items()}, "ranks": list(RANKS),
        "install": install_state(),
        "active_job": active_job(),
    }


# ---------- instalacija sd-scripts (1 klik) ----------

def install_state() -> dict:
    with _install_lock:
        st = dict(_install)
        st["log"] = list(_install["log"][-80:])
    return st


def _ilog(msg: str, *, step: str | None = None, progress: float | None = None) -> None:
    with _install_lock:
        for line in str(msg).splitlines() or [""]:
            line = line.rstrip()
            if line:
                _install["log"].append(line[:400])
        _install["log"] = _install["log"][-400:]
        if step is not None:
            _install["step"] = step
        if progress is not None:
            _install["progress"] = float(progress)
    try:
        trainer_root().mkdir(parents=True, exist_ok=True)
        with open(trainer_root() / "install.log", "a", encoding="utf-8") as fh:
            fh.write(str(msg).rstrip() + "\n")
    except OSError:
        pass


def parse_requirements(text: str) -> list:
    """requirements.txt iz sd-scripts -> lista za pip, bez bitsandbytes/xformers/tensorboard/torch/numpy i bez '-e .'."""
    out = []
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        spec, _, marker = line.partition(";")
        spec = spec.strip()
        if marker and "arm64" in marker.lower() and "==" in marker:
            continue  # paket samo za Windows na ARM64
        name = re.split(r"[<>=!~\[ ]", spec, maxsplit=1)[0].strip().lower()
        if not name or name in SKIP_PACKAGES:
            continue
        out.append(re.sub(r"\[[^\]]*\]", "", spec))  # diffusers[torch] -> diffusers (torch ostaje ComfyUI-jev)
    return out


def _run_logged(argv: list, *, cwd=None, timeout: float = 3600) -> int:
    _ilog("$ " + " ".join(str(a) for a in argv))
    env = dict(os.environ, PYTHONUTF8="1", PIP_DISABLE_PIP_VERSION_CHECK="1", TORCH_BACKENDS_CUDNN_ENABLED="0")
    proc = subprocess.Popen([str(a) for a in argv], cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env=env, creationflags=_no_window())
    started = time.time()
    assert proc.stdout is not None
    for raw in iter(proc.stdout.readline, b""):
        _ilog(raw.decode("utf-8", errors="replace"))
        if time.time() - started > timeout:
            proc.kill()
            _ilog("Isteklo vrijeme.")
            return -1
    return proc.wait()


def _download_sd_scripts(ref: str) -> None:
    dest = sd_scripts_dir()
    tmp_zip = trainer_root() / "sd-scripts.zip"
    url = SD_SCRIPTS_ZIP_URL.format(ref=ref)
    _ilog(f"Preuzimam kohya-ss/sd-scripts {ref}…", step="download", progress=0.05)
    req = urllib.request.Request(url, headers={"User-Agent": "AI-Influencer-Studio"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(tmp_zip, "wb") as fh:
        shutil.copyfileobj(resp, fh)
    extract = trainer_root() / "sd-scripts.tmp"
    shutil.rmtree(extract, ignore_errors=True)
    with zipfile.ZipFile(tmp_zip) as zf:
        root_resolved = str(extract.resolve())
        for member in zf.namelist():
            if not str((extract / member).resolve()).startswith(root_resolved):
                raise RuntimeError("Neispravna zip arhiva.")
        zf.extractall(extract)
    inner = [p for p in extract.iterdir() if p.is_dir()]
    if len(inner) != 1 or not (inner[0] / "train_network.py").is_file():
        raise RuntimeError("Preuzeta arhiva nema train_network.py.")
    shutil.rmtree(dest, ignore_errors=True)
    shutil.move(str(inner[0]), str(dest))
    shutil.rmtree(extract, ignore_errors=True)
    tmp_zip.unlink(missing_ok=True)
    (trainer_root() / "sd-scripts.ref").write_text(ref, encoding="utf-8")
    _ilog("sd-scripts raspakiran u " + str(dest), progress=0.2)


def _site_packages(py) -> list:
    try:
        r = subprocess.run([str(py), "-c", "import json, site; print(json.dumps([p for p in site.getsitepackages() if 'site-packages' in p]))"],
                           capture_output=True, text=True, timeout=60, creationflags=_no_window())
        return [p for p in json.loads((r.stdout or "[]").strip().splitlines()[-1]) if Path(p).is_dir()]
    except Exception:
        return []


def _install_worker() -> None:
    try:
        trainer_root().mkdir(parents=True, exist_ok=True)
        (trainer_root() / ".studio_ready").unlink(missing_ok=True)
        py, src = comfy_python()
        if not py or not Path(py).is_file():
            raise RuntimeError("Nije pronađen Python (očekujem C:\\ComfyUI-Zluda\\venv\\Scripts\\python.exe).")
        _ilog(f"Python: {py} ({src})", step="python", progress=0.02)
        ref = os.environ.get("STUDIO_SD_SCRIPTS_REF") or SD_SCRIPTS_REF
        ref_file = trainer_root() / "sd-scripts.ref"
        have = (sd_scripts_dir() / "train_network.py").is_file() and ref_file.is_file() and ref_file.read_text(encoding="utf-8").strip() == ref
        if have:
            _ilog("sd-scripts je već preuzet.", progress=0.2)
        else:
            _download_sd_scripts(ref)
        # Zaseban venv: paketi ComfyUI-ja se NE diraju. torch (ZLUDA build) se vidi preko .pth na ComfyUI site-packages.
        if trainer_python() is None:
            _ilog("Stvaram zasebno Python okruženje za trener…", step="venv", progress=0.25)
            if _run_logged([py, "-m", "venv", trainer_venv_dir()]) != 0 or trainer_python() is None:
                raise RuntimeError("Ne mogu stvoriti venv za trener (python -m venv nije uspio).")
        tpy = trainer_python()
        sites, tsites = _site_packages(py), _site_packages(tpy)
        if sites and tsites:
            (Path(tsites[0]) / "studio_comfy_packages.pth").write_text("\n".join(sites) + "\n", encoding="utf-8")
            _ilog("Trener koristi PyTorch iz ComfyUI-ja (ZLUDA): " + ", ".join(sites))
        else:
            _ilog("UPOZORENJE: nisam našao ComfyUI site-packages; PyTorch možda neće biti dostupan treneru.")
        req_file = sd_scripts_dir() / "requirements.txt"
        reqs = parse_requirements(req_file.read_text(encoding="utf-8")) if req_file.is_file() else list(FALLBACK_REQUIREMENTS)
        if not any(r.lower().startswith("lion-pytorch") for r in reqs):
            reqs.append("lion-pytorch")
        _ilog("Instaliram pakete (bez bitsandbytes i xformers, oni ne rade na AMD/ZLUDA): " + ", ".join(reqs), step="pip", progress=0.35)
        if _run_logged([tpy, "-m", "pip", "install", "--upgrade-strategy", "only-if-needed", *reqs]) != 0:
            raise RuntimeError("pip install nije uspio. Pogledaj log (internet, disk, verzija Pythona).")
        (trainer_root() / "launch_trainer.py").write_text(LAUNCHER_SOURCE, encoding="utf-8")
        _ilog("Provjeravam PyTorch u treneru…", step="check", progress=0.9)
        t = _probe_torch_now(tpy)
        _torch_probe.update(result=t, at=time.time())
        if not t.get("ok"):
            raise RuntimeError("PyTorch nije dostupan u treneru: " + str(t.get("error") or ""))
        _ilog(f"PyTorch {t.get('version')} · GPU: {t.get('device') or 'nije pronađen'}")
        (trainer_root() / ".studio_ready").write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
        with _install_lock:
            _install.update(done=True, step="done", progress=1.0, error="")
        _ilog("Okruženje za treniranje je spremno.")
    except Exception as exc:
        with _install_lock:
            _install.update(error=str(exc)[:600], done=False)
        _ilog("GREŠKA: " + str(exc))
    finally:
        with _install_lock:
            _install["running"] = False


def install_backend() -> dict:
    with _install_lock:
        if _install["running"]:
            return {"ok": True, "started": False, "install": dict(_install, log=list(_install["log"][-80:]))}
        _install.update(running=True, step="start", progress=0.0, log=[], error="", done=False, started_at=now())
    threading.Thread(target=_install_worker, daemon=True, name="lora-install").start()
    return {"ok": True, "started": True, "install": install_state()}


# Pokretač: sigurne ZLUDA postavke (bez cuDNN-a, SDPA samo "math" kernel) pa sd-scripts skripta.
LAUNCHER_SOURCE = r'''# -*- coding: utf-8 -*-
"""AI Influencer Studio: pokretač kohya-ss/sd-scripts za AMD (ZLUDA)."""
import os, runpy, sys
os.environ.setdefault("TORCH_BACKENDS_CUDNN_ENABLED", "0")
try:
    import torch
    torch.backends.cudnn.enabled = False
    name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else ""
    if "[ZLUDA]" in name or os.environ.get("STUDIO_ZLUDA") == "1":
        try:
            torch.backends.cuda.enable_flash_sdp(False)
            torch.backends.cuda.enable_mem_efficient_sdp(False)
            torch.backends.cuda.enable_math_sdp(True)
        except Exception:
            pass
    print("STUDIO: GPU", name or "nije pronađen", flush=True)
except Exception as exc:
    print("STUDIO: torch upozorenje:", exc, flush=True)
script = os.path.abspath(sys.argv[1])
sys.argv = sys.argv[1:]
sys.path.insert(0, os.path.dirname(script))
os.chdir(os.path.dirname(script))
runpy.run_path(script, run_name="__main__")
'''


# ---------- ComfyUI VRAM ----------

def comfy_url() -> str:
    return (_cfg.get("comfy_url") or os.environ.get("COMFYUI_URL") or "http://127.0.0.1:8188").rstrip("/")


def free_comfy_vram() -> tuple:
    """Best-effort: ComfyUI /free istovari modele da RX 6600 ima punih 8 GB za trening."""
    try:
        http_request("POST", comfy_url() + "/free", json_body={"unload_models": True, "free_memory": True}, timeout=8)
        return True, "ComfyUI je istovario modele (VRAM oslobođen za treniranje)."
    except HttpError as exc:
        return False, f"ComfyUI /free nije uspio ({exc}); nastavljam."
    except Exception as exc:
        return False, f"ComfyUI nije dostupan ({exc}); nastavljam."


# ---------- poslovi ----------

def _job_row(row) -> dict:
    d = row_dict(row)
    d["config"] = jload(d.pop("config_json", "{}"), {}) or {}
    d["status_label"] = STATUS_LABELS.get(d.get("status") or "", d.get("status") or "")
    d["active"] = d.get("status") in ACTIVE_STATUSES
    started = d.get("started_at")
    end = d.get("finished_at") or (now() if d["active"] else None)
    d["elapsed_seconds"] = int(end - started) if started and end else 0
    d["log_lines"] = [ln for ln in (d.get("log_tail") or "").splitlines() if ln][-40:]
    d["lora_filename"] = Path(d.get("output_path") or "").name if d.get("output_path") else ""
    d["profile_name"] = ((inbox.get_profile(d.get("profile_id")) or {}).get("name") or "") if d.get("profile_id") else ""
    return d


def get_job(jid: int):
    with conn() as c:
        row = c.execute("SELECT * FROM lora_training_jobs WHERE id=?", (int(jid),)).fetchone()
    return _job_row(row) if row else None


def list_jobs(profile_id=None, limit: int = 20) -> list:
    with conn() as c:
        if profile_id not in (None, ""):
            rows = c.execute("SELECT * FROM lora_training_jobs WHERE profile_id=? ORDER BY id DESC LIMIT ?", (int(profile_id), int(limit))).fetchall()
        else:
            rows = c.execute("SELECT * FROM lora_training_jobs ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    return [_job_row(r) for r in rows]


def active_job():
    marks = ",".join("?" * len(ACTIVE_STATUSES))
    with conn() as c:
        row = c.execute(f"SELECT * FROM lora_training_jobs WHERE status IN ({marks}) ORDER BY id LIMIT 1", ACTIVE_STATUSES).fetchone()
    return _job_row(row) if row else None


def training_active() -> bool:
    """Za red čekanja / generiranje: dok trening traje, GPU (8 GB) je zauzet."""
    try:
        return active_job() is not None
    except Exception:
        return False


def _set_job(jid: int, **fields) -> None:
    if "config" in fields:
        fields["config_json"] = jdump(fields.pop("config"))
    if not fields:
        return
    with conn() as c:
        c.execute(f"UPDATE lora_training_jobs SET {', '.join(k + '=?' for k in fields)} WHERE id=?", [*fields.values(), int(jid)])


class TrainerBusy(RuntimeError):
    pass


def _next_lora_filename(pid: int, prof: dict) -> str:
    slug = slugify(prof.get("name") or "", fallback=f"osoba{pid}")[:30] or f"osoba{pid}"
    target, _ = loras_target_dir()
    with conn() as c:
        used = {str(r[0]).lower() for r in c.execute("SELECT lora_filename FROM persona_trained_loras").fetchall()}
        used |= {str(r[0]).lower() for r in c.execute("SELECT lora_name FROM lora_training_jobs").fetchall()}
        n = c.execute("SELECT COUNT(*) FROM persona_trained_loras WHERE profile_id=?", (int(pid),)).fetchone()[0] + 1
    while True:
        name = f"char_{slug}_v{n}.safetensors"
        if name.lower() not in used and not (target / name).exists():
            return name
        n += 1


def start_training(pid: int, preset: str = DEFAULT_PRESET, advanced: dict | None = None) -> dict:
    prof = inbox.get_profile(int(pid))
    if not prof:
        raise KeyError("Osoba ne postoji.")
    with _jobs_lock:
        cur = active_job()
        if cur:
            who = cur.get("profile_name") or f"#{cur['profile_id']}"
            raise TrainerBusy(f"Treniranje već traje ({who}). Na 8 GB VRAM-a ide samo jedno odjednom — pričekaj da završi ili ga zaustavi.")
        plan = compute_plan(pid, preset, advanced)
        g = plan["guidance"]
        if not g["can_train"]:
            raise ValueError(g["message"])
        if _override_cmd() is None and not backend_ready():
            raise RuntimeError("Okruženje za treniranje još nije pripremljeno. Klikni „Pripremi okruženje za treniranje”.")
        if not pil_ok():
            raise RuntimeError("Za pripremu slika treba Pillow (u ComfyUI venvu: python -m pip install pillow).")
        base_path = checkpoint_path(plan["base_model"])
        if not base_path.is_file():
            raise ValueError(f"Bazni model „{plan['base_model']}” nije pronađen u {comfy_launch.checkpoints_dir()}.")
        trig = ensure_trigger(pid)
        lora_file = _next_lora_filename(pid, prof)
        cfg = {"plan": plan, "trigger": trig, "lora_filename": lora_file, "base_path": str(base_path)}
        with conn() as c:
            c.execute(
                "INSERT INTO lora_training_jobs(profile_id, status, lora_name, trigger_word, base_model, arch, preset, image_count, total_steps, "
                "total_epochs, eta_seconds, gpu_temp_status, config_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (int(pid), "queued", lora_file, trig, plan["base_model"], plan["arch"], plan["preset"], plan["image_count"],
                 plan["total_steps"], plan["epochs"], plan["eta_seconds"], "unavailable", jdump(cfg), now()),
            )
            jid = int(c.execute("SELECT last_insert_rowid()").fetchone()[0])
        _cancel.pop(jid, None)
        t = threading.Thread(target=_run_job, args=(jid,), daemon=True, name=f"lora-train-{jid}")
        _threads[jid] = t
        t.start()
    return get_job(jid)


def cancel_job(jid: int, wait: float = 20) -> dict:
    job = get_job(jid)
    if not job:
        raise KeyError("Posao treniranja ne postoji.")
    if job["status"] not in ACTIVE_STATUSES:
        return job
    _cancel[int(jid)] = "user"
    proc = _procs.get(int(jid))
    if proc is not None:
        kill_process_tree(proc)
    t = _threads.get(int(jid))
    if t is not None:
        t.join(timeout=wait)
    elif get_job(jid)["status"] in ACTIVE_STATUSES:
        _set_job(jid, status="canceled", finished_at=now(), error_message="Zaustavio korisnik.")
    return get_job(jid)


def kill_process_tree(proc) -> None:
    """Windows: taskkill /F /T /PID. POSIX: SIGTERM cijeloj grupi procesa, pa SIGKILL."""
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=30, creationflags=_no_window())
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def stop_all() -> None:
    """Gašenje Studija: prekini treniranje (inače bi proces ostao bez nadzora temperature)."""
    for jid, proc in list(_procs.items()):
        _cancel[jid] = "shutdown"
        kill_process_tree(proc)


# ---------- praćenje izlaza sd-scripts ----------

_STEP_RE = re.compile(r"steps:\s*(\d+)%\|[^|]*\|\s*(\d+)/(\d+)\s*\[([\d:]+)<([\d:?]+)")
_STEP_LOOSE_RE = re.compile(r"steps:\s*(?:\d+%\|[^|]*\|\s*)?(\d+)/(\d+)")
_LOSS_RE = re.compile(r"avr_loss=([-+\d.eE]+|nan)")
_EPOCH_RE = re.compile(r"^\s*epoch\s+(\d+)\s*/\s*(\d+)", re.I)
_OOM_RE = re.compile(r"(?i)out of memory|DefaultCPUAllocator: not enough memory")


def _hms(text: str):
    if not text or "?" in text:
        return None
    sec = 0
    for p in text.split(":"):
        if not p.isdigit():
            return None
        sec = sec * 60 + int(p)
    return sec


def parse_progress_line(line: str) -> dict:
    """Iz jedne linije sd-scripts/tqdm izlaza: korak, ukupno, epoha, loss, preostalo vrijeme, caching, OOM."""
    out: dict = {}
    m = _STEP_RE.search(line)
    if m:
        out.update(step=int(m.group(2)), total=int(m.group(3)), remaining=_hms(m.group(5)))
    else:
        m2 = _STEP_LOOSE_RE.search(line)
        if m2:
            out.update(step=int(m2.group(1)), total=int(m2.group(2)))
    ml = _LOSS_RE.search(line)
    if ml:
        try:
            v = float(ml.group(1))
            if v == v:
                out["loss"] = v
        except ValueError:
            pass
    me = _EPOCH_RE.search(line)
    if me:
        out.update(epoch=int(me.group(1)), epochs=int(me.group(2)))
    low = line.lower()
    if "caching latents" in low or "caching text encoder" in low or "cache latents" in low:
        out["caching"] = True
    if _OOM_RE.search(line):
        out["oom"] = True
    return out


def _temp_interval() -> float:
    if _cfg.get("temp_interval"):
        return float(_cfg["temp_interval"])
    try:
        return max(0.05, float(os.environ.get("STUDIO_LORA_TEMP_INTERVAL") or 5))
    except ValueError:
        return 5.0


def _build_command(cfg_path, ds_path, output_file, arch: str) -> list:
    override = _override_cmd()
    if override:
        if any("{config}" in a or "{dataset}" in a for a in override):
            return [a.replace("{config}", str(cfg_path)).replace("{dataset}", str(ds_path)).replace("{output}", str(output_file)) for a in override]
        return [*override, "--config_file", str(cfg_path), "--dataset_config", str(ds_path)]
    script = sd_scripts_dir() / ("sdxl_train_network.py" if arch == "sdxl" else "train_network.py")
    return [str(trainer_python()), str(trainer_root() / "launch_trainer.py"), str(script), "--config_file", str(cfg_path), "--dataset_config", str(ds_path)]


def training_env(extra: dict | None = None) -> dict:
    """ComfyUI/ZLUDA okruženje + obavezne sigurne varijable za RX 6600."""
    try:
        env = hardware_service.process_env(dict(os.environ))
    except Exception:
        env = dict(os.environ)
    env.update({
        "TORCH_BACKENDS_CUDNN_ENABLED": "0",
        "PYTORCH_CUDA_ALLOC_CONF": "max_split_size_mb:128",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
    })
    try:
        if hardware_service.effective_backend() == "zluda":
            env["STUDIO_ZLUDA"] = "1"
    except Exception:
        pass
    env.update(extra or {})
    return env


class _Stop(Exception):
    pass


def _run_job(jid: int) -> None:
    job = get_job(jid) or {}
    pid = int(job.get("profile_id") or 0)
    cfgd = job.get("config") or {}
    plan = cfgd.get("plan") or {}
    trig = cfgd.get("trigger") or job.get("trigger_word") or ""
    lora_file = cfgd.get("lora_filename") or job.get("lora_name") or "lora.safetensors"
    dirs = persona_dirs(pid)
    log_path = dirs["logs"] / f"job_{jid}.log"
    tail: collections.deque = collections.deque(maxlen=60)
    th = dict(plan.get("temp") or temp_settings())
    state = {"step": 0, "total": int(plan.get("total_steps") or 0), "epoch": 0, "epochs": int(plan.get("epochs") or 0), "loss": None,
             "remaining": None, "oom": False, "status": "preparing", "peak": None, "train_started": None, "last_write": 0.0,
             "overheat": False}
    lock = threading.Lock()

    def log(msg: str) -> None:
        for line in str(msg).replace("\r", "\n").splitlines():
            line = line.rstrip()
            if not line:
                continue
            tail.append(line[:300])
            try:
                with open(log_path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                pass

    def flush(force: bool = False, **extra) -> None:
        with lock:
            if not force and time.time() - state["last_write"] < 0.5:
                return
            state["last_write"] = time.time()
            total = max(1, int(state["total"] or 1))
            pct = round(min(100.0, 100.0 * state["step"] / total), 1)
            eta = state["remaining"]
            if eta is None and state["step"] and state["train_started"]:
                per = (time.time() - state["train_started"]) / max(1, state["step"])
                eta = int(per * max(0, total - state["step"]))
            fields = {"status": state["status"], "current_step": int(state["step"]), "total_steps": int(state["total"] or 0),
                      "current_epoch": int(state["epoch"]), "total_epochs": int(state["epochs"] or 0), "progress_pct": pct,
                      "log_tail": "\n".join(tail)}
            if state["loss"] is not None:
                fields["loss"] = round(float(state["loss"]), 5)
            if eta is not None:
                fields["eta_seconds"] = int(eta)
            fields.update(extra)
            _set_job(jid, **fields)

    def handle_line(line: str) -> None:
        if not line.strip():
            return
        info = parse_progress_line(line)
        if "step" in info:
            if state["status"] != "training":
                state["status"] = "training"
                state["train_started"] = time.time()
            state["step"] = info["step"]
            if info.get("total"):
                state["total"] = info["total"]
            if info.get("remaining") is not None:
                state["remaining"] = info["remaining"]
            if tail and tail[-1].lstrip().startswith("steps:"):
                tail.pop()
            tail.append(line.strip()[:300])
        else:
            log(line)
        if "loss" in info:
            state["loss"] = info["loss"]
        if "epoch" in info:
            state["epoch"], state["epochs"] = info["epoch"], info["epochs"]
        if info.get("oom"):
            state["oom"] = True
        flush()

    try:
        _set_job(jid, status="preparing", started_at=now())
        log(f"Osoba #{pid}, okidač {trig}, bazni model {plan.get('base_model')} ({plan.get('arch')}), profil {plan.get('preset')}.")
        prep = prepare_dataset(pid, resolution=int(plan["resolution"]), trigger=trig, repeats=int(plan["repeats"]))
        log(f"Pripremljeno {prep['images']} slika ({plan['resolution']}×{plan['resolution']}) u {prep['img_dir']}.")
        if prep["skipped"]:
            log("Preskočeno: " + ", ".join(prep["skipped"][:10]))
        state["total"] = prep["images"] * int(plan["repeats"]) * int(plan["epochs"])
        out_dir = dirs["output"] / f"job_{jid}"
        out_dir.mkdir(parents=True, exist_ok=True)
        output_name = Path(lora_file).stem
        output_file = out_dir / f"{output_name}.safetensors"
        train_cfg = build_training_config(plan, base_path=Path(cfgd.get("base_path") or checkpoint_path(plan["base_model"])),
                                          output_dir=out_dir, output_name=output_name, logs_dir=dirs["logs"])
        cfg_path = dirs["prepared"] / "training_config.toml"
        cfg_path.write_text(to_toml(train_cfg), encoding="utf-8")
        cfgd.update(training=train_cfg, dataset_toml=str(prep["dataset_toml"]), config_toml=str(cfg_path))
        _set_job(jid, config=cfgd)
        if _cancel.get(jid):
            raise _Stop()
        ok, msg = free_comfy_vram()
        log(msg)
        cfgd["comfy_freed"] = ok
        _set_job(jid, config=cfgd)
        cmd = _build_command(cfg_path, prep["dataset_toml"], output_file, plan["arch"])
        env = training_env({"STUDIO_LORA_OUTPUT_FILE": str(output_file), "STUDIO_LORA_TOTAL_STEPS": str(state["total"]),
                            "STUDIO_LORA_EPOCHS": str(plan["epochs"]), "STUDIO_LORA_CONFIG": str(cfg_path),
                            "STUDIO_LORA_DATASET": str(prep["dataset_toml"])})
        log("Pokrećem: " + " ".join(cmd))
        state["status"] = "caching"
        flush(True)
        popen_kw: dict = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "env": env,
                          "cwd": str(sd_scripts_dir() if sd_scripts_dir().is_dir() else dirs["root"])}
        if sys.platform == "win32":
            popen_kw["creationflags"] = _no_window() | int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        else:
            popen_kw["start_new_session"] = True
        if _cancel.get(jid):
            raise _Stop()
        proc = subprocess.Popen(cmd, **popen_kw)
        _procs[jid] = proc

        def reader():
            buf = b""
            stream = proc.stdout
            while stream is not None:
                chunk = stream.read1(4096) if hasattr(stream, "read1") else stream.read(1)
                if not chunk:
                    break
                buf += chunk
                parts = re.split(rb"[\r\n]", buf)
                buf = parts.pop()
                for raw in parts:
                    handle_line(raw.decode("utf-8", errors="replace"))
            if buf:
                handle_line(buf.decode("utf-8", errors="replace"))

        rt = threading.Thread(target=reader, daemon=True, name=f"lora-read-{jid}")
        rt.start()
        interval = _temp_interval()
        next_temp = 0.0
        while proc.poll() is None:
            if time.time() >= next_temp:
                next_temp = time.time() + interval
                _check_temp(jid, state, th, log, proc)
            time.sleep(min(0.2, interval))
        rt.join(timeout=10)
        code = proc.returncode
        _procs.pop(jid, None)
        log(f"[izlaz procesa: {code}]")
        reason = _cancel.get(jid)
        if state["overheat"]:
            state["status"] = "paused_overheat"
            flush(True, finished_at=now(), error_message=(
                f"Treniranje je automatski zaustavljeno jer je GPU dosegao {state['peak']:.0f}°C (granica {th['stop_c']:.0f}°C). "
                "Tvoj RX 6600 je zaštićen. Pusti ga da se ohladi, provjeri ventilatore i prašinu, pa pokreni treniranje ponovno."))
            return
        if reason:
            state["status"] = "canceled"
            flush(True, finished_at=now(), error_message="Zaustavio korisnik." if reason == "user" else "Studio se gasi; treniranje je prekinuto.")
            return
        if code == 0 and output_file.is_file() and output_file.stat().st_size > 0:
            final = finalize_lora(jid, pid, output_file, lora_file, trig, plan)
            log(f"Gotovo: {final.name} je dodana osobi (jačina 0.8, okidač {trig}).")
            state.update(status="completed", step=max(state["step"], state["total"]), remaining=0)
            flush(True, finished_at=now(), output_path=str(final), progress_pct=100.0, eta_seconds=0)
            return
        if state["oom"]:
            msg = ("Nestalo je VRAM-a (out of memory). Zatvori druge programe koji koriste GPU, ostavi rezoluciju 768 (SDXL) / 512 (SD 1.5) "
                   "i probaj profil „Brzi test” ili manji rank u Napredno.")
        elif code == 0:
            msg = "Treniranje je završilo, ali .safetensors datoteka nije nastala ili je prazna."
        else:
            last = [ln for ln in tail if ln.strip() and not ln.startswith("[izlaz")][-3:]
            msg = f"Treniranje je prekinuto greškom (izlaz {code}). " + " | ".join(last)[-500:]
        state["status"] = "failed"
        flush(True, finished_at=now(), error_message=msg)
    except _Stop:
        state["status"] = "canceled"
        flush(True, finished_at=now(), error_message="Zaustavio korisnik.")
    except Exception as exc:
        log("GREŠKA: " + str(exc))
        state["status"] = "failed"
        flush(True, finished_at=now(), error_message=str(exc)[:800])
    finally:
        _procs.pop(jid, None)
        _cancel.pop(jid, None)
        _threads.pop(jid, None)


def _check_temp(jid: int, state: dict, th: dict, log, proc) -> None:
    try:
        reading = hardware_service.read_gpu_temperature()
    except Exception:
        reading = {"available": False, "temp_c": None}
    t = reading.get("temp_c") if reading.get("available") else None
    st, msg = classify_temp(t, th)
    fields = {"gpu_temp_c": t, "gpu_temp_status": st, "gpu_warning_message": msg}
    if t is not None:
        state["peak"] = max(state["peak"] or t, t)
        fields["gpu_temp_peak_c"] = state["peak"]
        if st in ("warn", "critical") and state.get("last_temp_status") != st:
            log(f"TEMPERATURA: {msg}")
    state["last_temp_status"] = st
    if t is not None and th.get("autostop", True) and t >= th["stop_c"] and proc is not None and not state["overheat"]:
        state["overheat"] = True
        fields["gpu_temp_status"] = "critical"
        fields["gpu_warning_message"] = f"GPU je dosegao {t:.0f}°C — treniranje se automatski zaustavlja da zaštiti RX 6600."
        log(f"AUTO-STOP: GPU {t:.0f}°C ≥ {th['stop_c']:.0f}°C")
        _set_job(jid, **fields)
        kill_process_tree(proc)
        return
    _set_job(jid, **fields)


# ---------- gotova LoRA -> profil osobe ----------

def finalize_lora(jid: int, pid: int, output_file, lora_file: str, trigger: str, plan: dict) -> Path:
    target_dir, _ = loras_target_dir()
    final = target_dir / lora_file
    tmp = final.with_name(final.name + ".tmp")
    shutil.copy2(output_file, tmp)
    os.replace(tmp, final)
    with conn() as c:
        c.execute(
            "INSERT INTO persona_trained_loras(profile_id, lora_filename, trigger_word, strength, base_model, arch, job_id, is_active, created_at) "
            "VALUES (?,?,?,?,?,?,?,0,?)",
            (int(pid), lora_file, trigger, 0.8, plan.get("base_model") or "", plan.get("arch") or "", int(jid), now()),
        )
        lid = int(c.execute("SELECT last_insert_rowid()").fetchone()[0])
    _apply_to_profile(pid, lid)
    return final


def list_trained(pid: int) -> list:
    target_dir, _ = loras_target_dir()
    with conn() as c:
        rows = c.execute("SELECT * FROM persona_trained_loras WHERE profile_id=? ORDER BY id DESC", (int(pid),)).fetchall()
    out = []
    for r in rows:
        d = row_dict(r)
        d["exists"] = (target_dir / d["lora_filename"]).is_file() or image_gen.lora_available(d["lora_filename"])
        d["is_active"] = bool(d.get("is_active"))
        out.append(d)
    return out


def _apply_to_profile(pid: int, lora_id: int) -> dict:
    """Aktivna trenirana LoRA -> preferred_lora (jačina 0.8) + okidač osobe. Druge LoRA-e u stacku ostaju."""
    with conn() as c:
        row = c.execute("SELECT * FROM persona_trained_loras WHERE id=? AND profile_id=?", (int(lora_id), int(pid))).fetchone()
        if not row:
            raise KeyError("Ta LoRA ne pripada ovoj osobi.")
        mine = {str(r[0]).lower() for r in c.execute("SELECT lora_filename FROM persona_trained_loras WHERE profile_id=?", (int(pid),)).fetchall()}
        prow = c.execute("SELECT * FROM profiles WHERE id=?", (int(pid),)).fetchone()
        stack = jload(prow["lora_stack"] if prow is not None and "lora_stack" in prow.keys() else "[]", []) or []
        # Starije verzije iste osobe izbaci iz stacka da se LoRA ne primijeni dvaput; ostale LoRA-e ostaju.
        stack = [x for x in stack if isinstance(x, dict) and image_gen.lora_key(str(x.get("name") or "")).split("/")[-1] not in mine]
        c.execute("UPDATE persona_trained_loras SET is_active=CASE WHEN id=? THEN 1 ELSE 0 END WHERE profile_id=?", (int(lora_id), int(pid)))
        sets = {"preferred_lora": row["lora_filename"], "preferred_lora_strength": str(float(row["strength"] or 0.8)),
                "lora_trigger": row["trigger_word"] or "", "updated_at": now()}
        if prow is not None and "lora_stack" in prow.keys():
            sets["lora_stack"] = jdump(stack)
        c.execute(f"UPDATE profiles SET {', '.join(k + '=?' for k in sets)} WHERE id=?", [*sets.values(), int(pid)])
    try:
        inbox.export_profiles_json()
    except Exception:
        pass
    return inbox.get_profile(int(pid))


def activate_lora(pid: int, lora_id=None, lora_filename: str = "") -> dict:
    if not inbox.get_profile(int(pid)):
        raise KeyError("Osoba ne postoji.")
    if not lora_id and lora_filename:
        with conn() as c:
            row = c.execute("SELECT id FROM persona_trained_loras WHERE profile_id=? AND lora_filename=?", (int(pid), lora_filename)).fetchone()
        if not row:
            raise KeyError("Ta LoRA nije trenirana za ovu osobu.")
        lora_id = row[0]
    if not lora_id:
        raise ValueError("Odaberi LoRA verziju.")
    prof = _apply_to_profile(pid, int(lora_id))
    return {"ok": True, "profile": prof, "loras": list_trained(pid)}


# ---------- generiranje: okidač osobe ----------

def trigger_for_generation(prof, body: dict, arch: str) -> str:
    """Okidač ako generiranje stvarno koristi treniranu LoRA-u te osobe (samo SDXL / SD 1.5).

    Gleda LoRA-u iz zahtjeva (ili preferiranu LoRA-u osobe ako je zahtjev ne šalje) i LoRA stack.
    """
    if not prof or not prof.get("id") or arch not in {"sdxl", "sd15"}:
        return ""
    try:
        with conn() as c:
            rows = c.execute("SELECT lora_filename, trigger_word FROM persona_trained_loras WHERE profile_id=? ORDER BY id DESC",
                             (int(prof["id"]),)).fetchall()
    except Exception:
        return ""
    trained = {image_gen.lora_key(r[0]).split("/")[-1]: (r[1] or "") for r in rows}
    if not trained:
        return ""
    used: list = []
    if "lora" in body or "user_lora" in body:
        used.append(str(body.get("lora") or body.get("user_lora") or ""))
    else:
        used.append(str(prof.get("preferred_lora") or ""))
    stack = body.get("loras") if isinstance(body.get("loras"), list) else (prof.get("lora_stack") or [])
    for item in stack or []:
        if isinstance(item, dict) and truthy(item.get("enabled"), True):
            used.append(str(item.get("name") or ""))
    for name in used:
        key = image_gen.lora_key(name).split("/")[-1]
        if key and key in trained:
            return trained[key] or (prof.get("lora_trigger") or "")
    return ""


def apply_trigger(scene: str, trigger: str) -> str:
    scene = (scene or "").strip()
    if not trigger:
        return scene
    if re.search(r"(?i)(^|[^a-z0-9_])" + re.escape(trigger) + r"($|[^a-z0-9_])", scene):
        return scene
    return f"{trigger}, {scene}" if scene else trigger


# ---------- pregled osoba (korak 1) ----------

def personas_overview() -> list:
    with conn() as c:
        counts = {r[0]: r[1] for r in c.execute("SELECT profile_id, COUNT(*) FROM lora_dataset_images GROUP BY profile_id").fetchall()}
        trained = {r[0]: r[1] for r in c.execute("SELECT profile_id, COUNT(*) FROM persona_trained_loras GROUP BY profile_id").fetchall()}
        active = {r["profile_id"]: row_dict(r) for r in c.execute("SELECT * FROM persona_trained_loras WHERE is_active=1").fetchall()}
    out = []
    for p in inbox.list_profiles():
        a = active.get(p["id"]) or {}
        out.append({"id": p["id"], "name": p["name"], "trigger": p.get("lora_trigger") or "", "preferred_lora": p.get("preferred_lora") or "",
                    "preferred_model": p.get("preferred_model") or "", "dataset_count": int(counts.get(p["id"], 0)),
                    "trained_count": int(trained.get(p["id"], 0)), "active_lora": a.get("lora_filename") or "",
                    "active_lora_in_use": bool(a) and (p.get("preferred_lora") or "") == a.get("lora_filename")})
    return out
