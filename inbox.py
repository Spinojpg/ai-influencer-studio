#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Profile, poruke fanova, Grok API i platformski adapteri (stdlib)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "studio.db"
PROFILES_JSON = DATA_DIR / "profiles.json"
ENV_PATH = DATA_DIR / ".env"
_PATHS_READY = False


def install_root() -> Path:
    if os.environ.get("STUDIO_INSTALL_ROOT"):
        return Path(os.environ["STUDIO_INSTALL_ROOT"]).expanduser()
    local = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    if local:
        return Path(local) / "AIInfluencerStudio"
    return Path.home() / "AIInfluencerStudio"


def infer_data_dir(app_dir: Path) -> Path:
    app_dir = Path(app_dir).resolve()
    # Instalirana kopija: .../AIInfluencerStudio/app  ->  .../AIInfluencerStudio/data
    if app_dir.name.lower() == "app" and app_dir.parent.name == "AIInfluencerStudio":
        return app_dir.parent / "data"
    inst = install_root()
    try:
        if (inst / "app").exists() and (inst / "app").resolve() == app_dir:
            return inst / "data"
    except OSError:
        pass
    return app_dir / "data"


def _copy_file_if_missing(src: Path, dest: Path) -> None:
    if not src.is_file():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copy2(src, dest)


def migrate_legacy_data(app_dir: Path, data_dir: Path) -> None:
    """Preseli stare podatke pored aplikacije u DATA_DIR, bez prepisivanja."""
    app_dir = Path(app_dir).resolve()
    data_dir = Path(data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    old_data = app_dir / "data"
    if old_data.is_dir() and old_data.resolve() != data_dir:
        for src in old_data.rglob("*"):
            if not src.is_file():
                continue
            rel = src.relative_to(old_data)
            dest = data_dir / rel
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
    for name in (".env", "persona.json", "profiles.json", "studio.db", "update.json"):
        _copy_file_if_missing(app_dir / name, data_dir / name)
    # Stari .env pored aplikacije — ključevi ostaju izvan mape koju update prepisuje.
    _copy_file_if_missing(app_dir / ".env", data_dir / ".env")


def configure_paths(app_dir: Path | None = None, data_dir: Path | None = None) -> Path:
    """Postavi ROOT/DATA_DIR. STUDIO_APP_DIR i STUDIO_DATA_DIR imaju prednost."""
    global ROOT, DATA_DIR, DB_PATH, PROFILES_JSON, ENV_PATH, _PATHS_READY
    ROOT = Path(app_dir or os.environ.get("STUDIO_APP_DIR") or Path(__file__).resolve().parent).resolve()
    if data_dir is not None:
        DATA_DIR = Path(data_dir).expanduser().resolve()
    elif os.environ.get("STUDIO_DATA_DIR"):
        DATA_DIR = Path(os.environ["STUDIO_DATA_DIR"]).expanduser().resolve()
    else:
        DATA_DIR = infer_data_dir(ROOT).resolve()
    migrate_legacy_data(ROOT, DATA_DIR)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "profiles").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "outputs").mkdir(parents=True, exist_ok=True)
    DB_PATH = DATA_DIR / "studio.db"
    PROFILES_JSON = DATA_DIR / "profiles.json"
    ENV_PATH = DATA_DIR / ".env"
    _PATHS_READY = True
    return DATA_DIR

DEFAULT_GROK_MODEL = "grok-4"
DEFAULT_XAI_BASE = "https://api.x.ai/v1"
GRAPH_VERSION = "v22.0"
HISTORY_LIMIT = 24

_lock = threading.RLock()
_telegram_stop = threading.Event()
_telegram_thread: threading.Thread | None = None


def _redact(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return value[:3] + "…" + value[-2:]


def load_dotenv(path: Path | None = None) -> None:
    """Učitaj .env u os.environ, bez prepisivanja već postavljenih varijabli."""
    if path is None:
        path = ENV_PATH
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in {"'", '"'}:
            val = val[1:-1]
        if key and key not in os.environ:
            os.environ[key] = val


def secret(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def xai_configured() -> bool:
    return bool(secret("XAI_API_KEY"))


def xai_base() -> str:
    return (secret("XAI_API_BASE") or DEFAULT_XAI_BASE).rstrip("/")


def grok_model_name() -> str:
    with _lock:
        row = db().execute("SELECT value FROM settings WHERE key=?", ("grok_model",)).fetchone()
    if row and row[0].strip():
        return row[0].strip()
    return secret("XAI_MODEL") or DEFAULT_GROK_MODEL


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "profiles").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "outputs").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "uploads").mkdir(parents=True, exist_ok=True)


def db() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    names = {r[1] for r in rows}
    if column not in names:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_db() -> None:
    if not _PATHS_READY:
        configure_paths()
    ensure_dirs()
    load_dotenv(ENV_PATH)
    # Stari .env pored aplikacije, bez prepisivanja već učitanih vrijednosti.
    load_dotenv(ROOT / ".env")
    with _lock:
        conn = db()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                appearance_prompt TEXT DEFAULT '',
                negative_prompt TEXT DEFAULT '',
                preferred_model TEXT DEFAULT '',
                style TEXT DEFAULT '',
                age_vibe TEXT DEFAULT '',
                writing_style TEXT DEFAULT 'short',
                slang TEXT DEFAULT 'light',
                emoji_use TEXT DEFAULT 'light',
                language TEXT DEFAULT 'HR',
                topics_avoid TEXT DEFAULT '',
                examples_json TEXT DEFAULT '[]',
                reference_image TEXT DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                external_user_id TEXT NOT NULL,
                display_name TEXT DEFAULT '',
                paused INTEGER DEFAULT 0,
                last_message_at REAL DEFAULT 0,
                UNIQUE(profile_id, platform, external_user_id),
                FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER NOT NULL,
                profile_id INTEGER NOT NULL,
                direction TEXT NOT NULL,
                body TEXT NOT NULL,
                status TEXT NOT NULL,
                reply_to INTEGER,
                external_id TEXT DEFAULT '',
                created_at REAL NOT NULL,
                sent_at REAL,
                error TEXT DEFAULT '',
                FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_msg_thread ON messages(thread_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_msg_status ON messages(status);
            """
        )
        _ensure_column(conn, "profiles", "model_type", "TEXT DEFAULT 'auto'")
        defaults = {
            "active_profile_id": "",
            "send_mode": "approve",
            "rate_limit_per_hour": "20",
            "quiet_hours_start": "",
            "quiet_hours_end": "",
            "grok_model": secret("XAI_MODEL") or DEFAULT_GROK_MODEL,
            "instagram_profile_id": "",
            "telegram_profile_id": "",
            "telegram_enabled": "0",
            "disable_cudnn": "1",
            "quality_prefix": "1",
            "hires_fix": "0",
            "browser": "brave",
        }
        for key, val in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
                (key, val),
            )
        count = conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
        if count == 0:
            now = time.time()
            conn.execute(
                """
                INSERT INTO profiles(
                    name, appearance_prompt, negative_prompt, preferred_model,
                    style, age_vibe, writing_style, slang, emoji_use, language,
                    topics_avoid, examples_json, reference_image, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "Primjer",
                    "portrait of a young woman, shoulder-length brown hair, green eyes, "
                    "natural makeup, photorealistic, soft daylight",
                    "",
                    "Realistic_Vision_V6.0_NV_B1_fp16.safetensors",
                    "prijateljska, vedra, malo stidljiva, ne pretjeruje s hvalom",
                    "srednje 20-e, opušten gradski vibe",
                    "short",
                    "light",
                    "light",
                    "HR",
                    "politika, uvredljivi komentari, tuđi izgled na ružan način",
                    json.dumps(
                        [
                            {
                                "fan": "Hej, odkud si?",
                                "reply": "Hej! Iz Zagreba, a ti? ☀️",
                            },
                            {
                                "fan": "Jesi li stvarna??",
                                "reply": "Haha, dobra vjera — ja sam AI persona, digitalni lik, "
                                "ne stvarna osoba. Al' možemo se i dalje normalno čuti :)",
                            },
                        ],
                        ensure_ascii=False,
                    ),
                    "",
                    now,
                    now,
                ),
            )
            pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "UPDATE settings SET value=? WHERE key='active_profile_id' AND (value='' OR value IS NULL)",
                (str(pid),),
            )
        conn.commit()
        conn.close()
    export_profiles_json()


def get_setting(key: str, default: str = "") -> str:
    with _lock:
        conn = db()
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        conn.close()
    return row[0] if row else default


def set_setting(key: str, value: str) -> None:
    with _lock:
        conn = db()
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        conn.commit()
        conn.close()


def _row_profile(row: sqlite3.Row) -> dict:
    examples = []
    try:
        examples = json.loads(row["examples_json"] or "[]")
    except json.JSONDecodeError:
        examples = []
    if not isinstance(examples, list):
        examples = []
    return {
        "id": row["id"],
        "name": row["name"],
        "appearance_prompt": row["appearance_prompt"] or "",
        "negative_prompt": row["negative_prompt"] or "",
        "preferred_model": row["preferred_model"] or "",
        "model_type": (row["model_type"] if "model_type" in row.keys() else "auto") or "auto",
        "style": row["style"] or "",
        "age_vibe": row["age_vibe"] or "",
        "writing_style": row["writing_style"] or "short",
        "slang": row["slang"] or "light",
        "emoji_use": row["emoji_use"] or "light",
        "language": row["language"] or "HR",
        "topics_avoid": row["topics_avoid"] or "",
        "examples": examples,
        "reference_image": row["reference_image"] or "",
        "has_reference": bool(row["reference_image"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_profiles() -> list[dict]:
    with _lock:
        conn = db()
        rows = conn.execute("SELECT * FROM profiles ORDER BY id").fetchall()
        conn.close()
    return [_row_profile(r) for r in rows]


def get_profile(pid: int | None) -> dict | None:
    if not pid:
        return None
    with _lock:
        conn = db()
        row = conn.execute("SELECT * FROM profiles WHERE id=?", (int(pid),)).fetchone()
        conn.close()
    return _row_profile(row) if row else None


def active_profile_id() -> int | None:
    raw = get_setting("active_profile_id")
    try:
        pid = int(raw)
    except (TypeError, ValueError):
        pid = 0
    if get_profile(pid):
        return pid
    profiles = list_profiles()
    if not profiles:
        return None
    set_setting("active_profile_id", str(profiles[0]["id"]))
    return profiles[0]["id"]


def export_profiles_json() -> None:
    ensure_dirs()
    data = {"active_profile_id": active_profile_id(), "profiles": list_profiles()}
    tmp = PROFILES_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(PROFILES_JSON)


def _clean_examples(raw) -> list[dict]:
    out = []
    if not isinstance(raw, list):
        return out
    for item in raw[:40]:
        if not isinstance(item, dict):
            continue
        fan = str(item.get("fan") or item.get("message") or "").strip()
        reply = str(item.get("reply") or item.get("odgovor") or "").strip()
        if fan or reply:
            out.append({"fan": fan, "reply": reply})
    return out


def upsert_profile(payload: dict, pid: int | None = None) -> dict:
    name = (payload.get("name") or "").strip()
    if not name:
        raise ValueError("Ime profila je obavezno.")
    fields = {
        "name": name[:80],
        "appearance_prompt": str(payload.get("appearance_prompt") or "")[:4000],
        "negative_prompt": str(payload.get("negative_prompt") or "")[:4000],
        "preferred_model": str(payload.get("preferred_model") or "")[:300],
        "model_type": (str(payload.get("model_type") or "auto").strip().lower() or "auto")[:16],
        "style": str(payload.get("style") or "")[:2000],
        "age_vibe": str(payload.get("age_vibe") or "")[:500],
        "writing_style": (payload.get("writing_style") or "short")[:20],
        "slang": (payload.get("slang") or "light")[:20],
        "emoji_use": (payload.get("emoji_use") or "light")[:20],
        "language": (payload.get("language") or "HR")[:8],
        "topics_avoid": str(payload.get("topics_avoid") or "")[:2000],
        "examples_json": json.dumps(_clean_examples(payload.get("examples")), ensure_ascii=False),
        "updated_at": time.time(),
    }
    now = time.time()
    with _lock:
        conn = db()
        if pid:
            row = conn.execute("SELECT id FROM profiles WHERE id=?", (int(pid),)).fetchone()
            if not row:
                conn.close()
                raise KeyError("Profil ne postoji.")
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE profiles SET {sets} WHERE id=?", [*fields.values(), int(pid)])
            new_id = int(pid)
        else:
            conn.execute(
                """
                INSERT INTO profiles(
                    name, appearance_prompt, negative_prompt, preferred_model, model_type,
                    style, age_vibe, writing_style, slang, emoji_use, language,
                    topics_avoid, examples_json, reference_image, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    fields["name"],
                    fields["appearance_prompt"],
                    fields["negative_prompt"],
                    fields["preferred_model"],
                    fields["model_type"],
                    fields["style"],
                    fields["age_vibe"],
                    fields["writing_style"],
                    fields["slang"],
                    fields["emoji_use"],
                    fields["language"],
                    fields["topics_avoid"],
                    fields["examples_json"],
                    "",
                    now,
                    fields["updated_at"],
                ),
            )
            new_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            if not get_setting("active_profile_id"):
                conn.execute(
                    "UPDATE settings SET value=? WHERE key='active_profile_id'",
                    (str(new_id),),
                )
        conn.commit()
        conn.close()
    export_profiles_json()
    return get_profile(new_id)


def delete_profile(pid: int) -> None:
    with _lock:
        conn = db()
        n = conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
        if n <= 1:
            conn.close()
            raise ValueError("Ne možeš obrisati zadnji profil. Napravi novi pa onda obriši ovaj.")
        conn.execute("DELETE FROM profiles WHERE id=?", (int(pid),))
        conn.commit()
        conn.close()
    if active_profile_id() == int(pid) or get_setting("active_profile_id") == str(pid):
        rest = list_profiles()
        set_setting("active_profile_id", str(rest[0]["id"]) if rest else "")
    export_profiles_json()


def save_reference_image(pid: int, data: bytes, ext: str = "jpg") -> str:
    prof = get_profile(pid)
    if not prof:
        raise KeyError("Profil ne postoji.")
    ext = re.sub(r"[^a-z0-9]", "", (ext or "jpg").lower()) or "jpg"
    if ext not in {"jpg", "jpeg", "png", "webp"}:
        ext = "jpg"
    folder = DATA_DIR / "profiles" / str(int(pid))
    folder.mkdir(parents=True, exist_ok=True)
    rel = f"profiles/{int(pid)}/reference.{ext}"
    dest = DATA_DIR / rel
    dest.write_bytes(data)
    with _lock:
        conn = db()
        conn.execute(
            "UPDATE profiles SET reference_image=?, updated_at=? WHERE id=?",
            (rel, time.time(), int(pid)),
        )
        conn.commit()
        conn.close()
    export_profiles_json()
    return rel


def reference_image_path(pid: int) -> Path | None:
    prof = get_profile(pid)
    if not prof or not prof.get("reference_image"):
        return None
    path = DATA_DIR / prof["reference_image"]
    if not path.is_file():
        return None
    try:
        path.resolve().relative_to(DATA_DIR.resolve())
    except ValueError:
        return None
    return path


# ---------- system prompt & Grok ----------

WRITING_LABELS = {
    "short": "kratke poruke, par rečenica, kao na chatu",
    "medium": "srednje duge poruke, prirodan ritam",
    "long": "duže, opširnije poruke kad tema to traži",
}
SLANG_LABELS = {
    "none": "bez slenga, uredniji jezik",
    "light": "malo razgovornog slenga, prirodno",
    "heavy": "opušten, kolokvijalan jezik, više slenga",
}
EMOJI_LABELS = {
    "none": "bez emojiija",
    "light": "poneki emoji, ne u svakoj rečenici",
    "lots": "slobodno više emojiija, ali ne pretjerano umjetno",
}


def build_system_prompt(profile: dict) -> str:
    lang = (profile.get("language") or "HR").upper()
    lang_line = {
        "HR": "Piši na hrvatskom, prirodno, kao stvarna osoba na chatu.",
        "EN": "Write in natural English, like a real person texting.",
        "MIX": "Odgovaraj na jeziku na kojem fan piše (hrvatski ili engleski).",
    }.get(lang, "Piši na hrvatskom, prirodno, kao stvarna osoba na chatu.")

    examples = profile.get("examples") or []
    ex_lines = []
    for i, pair in enumerate(examples, 1):
        if not isinstance(pair, dict):
            continue
        fan = (pair.get("fan") or "").strip()
        reply = (pair.get("reply") or "").strip()
        if fan or reply:
            ex_lines.append(f"{i}. Fan: {fan}\n   Ti: {reply}")
    examples_block = "\n".join(ex_lines) if ex_lines else "(nema spremljenih primjera)"

    name = profile.get("name") or "Persona"
    return f"""Ti predstavljaš AI personu / digitalnog influencera po imenu {name}.
Odgovaraš fanovima u njezinu/njegovu stilu, kratko i uvjerljivo, kao privatna poruka.

Ime: {name}
Osobnost / stil: {profile.get("style") or "prijateljska, opuštena"}
Dob / vibe: {profile.get("age_vibe") or "nije posebno navedeno"}
Duljina poruka: {WRITING_LABELS.get(profile.get("writing_style") or "short", WRITING_LABELS["short"])}
Slang: {SLANG_LABELS.get(profile.get("slang") or "light", SLANG_LABELS["light"])}
Emoji: {EMOJI_LABELS.get(profile.get("emoji_use") or "light", EMOJI_LABELS["light"])}
Jezik: {lang_line}
Teme koje izbjegavaš: {profile.get("topics_avoid") or "nema dodatnih, osim pravila ispod"}

Primjeri kako odgovaraš (fan -> tvoj idealni odgovor):
{examples_block}

PRAVILA — vrijede uvijek i jača su od stila persode:
1. Ako te fan iskreno pita jesi li stvarna osoba, čovjek, AI ili bot, odgovori iskreno: ti si AI persona / digitalni lik, ne stvarna osoba. Reci to u stilu persode, bez laži i bez izbjegavanja pitanja.
2. Nikakav seksualni, intimni ili romantično-seksualni sadržaj s bilo kim tko izgleda, kaže ili bi mogao biti maloljetan (ispod 18). Ako postoji i najmanja sumnja, odmah prekini taj ton, postavi granicu i nemoj nastaviti seksualnu temu.
3. Nikad ne traži novac, uplatu, donaciju, broj kartice, lozinke ni bilo kakve podatke za plaćanje.
4. Nemoj navoditi fana na sumnjive vanjske sheme, lažne nagrade, „javi se na drugi app da zaradiš”, phishing ili bilo kakvu prijevaru izvan platforme.

Piši samo tekst odgovora, bez navodnika i bez prefiksa poput „Odgovor:”."""


def _http_json(url: str, data=None, headers=None, timeout: float = 90, method: str | None = None):
    body = None
    hdrs = {"Accept": "application/json", "User-Agent": "AI-Influencer-Studio/1.0"}
    if headers:
        hdrs.update(headers)
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return None, resp.status
            try:
                return json.loads(raw.decode("utf-8")), resp.status
            except json.JSONDecodeError:
                return {"raw": raw.decode("utf-8", errors="replace")[:2000]}, resp.status
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"Mrežna greška: {reason}") from None


def call_grok(messages: list[dict], model: str | None = None) -> str:
    key = secret("XAI_API_KEY")
    if not key:
        raise RuntimeError(
            "Nema XAI_API_KEY. Uredi .env (kopiraj .env.example) i upiši ključ s https://console.x.ai"
        )
    model = (model or grok_model_name()).strip() or DEFAULT_GROK_MODEL
    url = xai_base() + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.85,
        "stream": False,
    }
    headers = {"Authorization": "Bearer " + key}
    try:
        data, _status = _http_json(url, data=payload, headers=headers, timeout=120)
    except RuntimeError as exc:
        # Ne uključuj ključ u poruku.
        text = str(exc)
        if key and key in text:
            text = text.replace(key, _redact(key))
        raise RuntimeError(text) from None
    if not isinstance(data, dict):
        raise RuntimeError("Neočekivani odgovor od xAI API-ja.")
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("xAI API nije vratio odgovor (prazan choices).")
    msg = (choices[0].get("message") or {}).get("content")
    if not msg:
        raise RuntimeError("xAI API je vratio prazan sadržaj.")
    return str(msg).strip()


def generate_reply(profile: dict, thread_messages: list[dict], fan_text: str) -> str:
    sys_prompt = build_system_prompt(profile)
    history: list[dict] = [{"role": "system", "content": sys_prompt}]
    for item in thread_messages[-HISTORY_LIMIT:]:
        role = "user" if item.get("direction") == "in" else "assistant"
        body = (item.get("body") or "").strip()
        if body and item.get("status") in {"received", "sent", "draft"}:
            # drafts from earlier turns that were sent appear as assistant
            if item.get("status") == "draft":
                continue
            history.append({"role": role, "content": body})
    # Ensure the latest fan message is last (it may already be in thread_messages).
    if not history or history[-1].get("role") != "user" or history[-1].get("content") != fan_text:
        history.append({"role": "user", "content": fan_text})
    return call_grok(history)


# ---------- threads & drafts ----------

def _thread_row(row: sqlite3.Row, pending: int = 0) -> dict:
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "platform": row["platform"],
        "external_user_id": row["external_user_id"],
        "display_name": row["display_name"] or row["external_user_id"],
        "paused": bool(row["paused"]),
        "last_message_at": row["last_message_at"],
        "pending_drafts": pending,
    }


def list_threads(profile_id: int) -> list[dict]:
    with _lock:
        conn = db()
        rows = conn.execute(
            """
            SELECT t.*,
                (SELECT COUNT(*) FROM messages m
                 WHERE m.thread_id=t.id AND m.direction='out' AND m.status='draft') AS pending
            FROM threads t
            WHERE t.profile_id=?
            ORDER BY t.last_message_at DESC, t.id DESC
            """,
            (int(profile_id),),
        ).fetchall()
        conn.close()
    return [_thread_row(r, int(r["pending"])) for r in rows]


def get_or_create_thread(profile_id: int, platform: str, external_user_id: str, display_name: str = "") -> dict:
    platform = (platform or "simulate").strip()[:40]
    external_user_id = (external_user_id or "fan").strip()[:200] or "fan"
    display_name = (display_name or "").strip()[:200]
    with _lock:
        conn = db()
        row = conn.execute(
            "SELECT * FROM threads WHERE profile_id=? AND platform=? AND external_user_id=?",
            (int(profile_id), platform, external_user_id),
        ).fetchone()
        if row:
            if display_name and display_name != (row["display_name"] or ""):
                conn.execute("UPDATE threads SET display_name=? WHERE id=?", (display_name, row["id"]))
                conn.commit()
                row = conn.execute("SELECT * FROM threads WHERE id=?", (row["id"],)).fetchone()
            conn.close()
            return _thread_row(row)
        conn.execute(
            """
            INSERT INTO threads(profile_id, platform, external_user_id, display_name, paused, last_message_at)
            VALUES (?,?,?,?,0,?)
            """,
            (int(profile_id), platform, external_user_id, display_name or external_user_id, time.time()),
        )
        tid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        row = conn.execute("SELECT * FROM threads WHERE id=?", (tid,)).fetchone()
        conn.close()
    return _thread_row(row)


def thread_messages(thread_id: int) -> list[dict]:
    with _lock:
        conn = db()
        rows = conn.execute(
            "SELECT * FROM messages WHERE thread_id=? ORDER BY created_at ASC, id ASC",
            (int(thread_id),),
        ).fetchall()
        conn.close()
    return [dict(r) for r in rows]


def get_thread(thread_id: int) -> dict | None:
    with _lock:
        conn = db()
        row = conn.execute("SELECT * FROM threads WHERE id=?", (int(thread_id),)).fetchone()
        pending = 0
        if row:
            pending = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE thread_id=? AND direction='out' AND status='draft'",
                (int(thread_id),),
            ).fetchone()[0]
        conn.close()
    if not row:
        return None
    data = _thread_row(row, pending)
    data["messages"] = thread_messages(thread_id)
    return data


def _insert_message(conn, **kwargs) -> int:
    now = kwargs.get("created_at") or time.time()
    conn.execute(
        """
        INSERT INTO messages(thread_id, profile_id, direction, body, status, reply_to, external_id, created_at, sent_at, error)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            kwargs["thread_id"],
            kwargs["profile_id"],
            kwargs["direction"],
            kwargs["body"],
            kwargs["status"],
            kwargs.get("reply_to"),
            kwargs.get("external_id") or "",
            now,
            kwargs.get("sent_at"),
            kwargs.get("error") or "",
        ),
    )
    mid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.execute("UPDATE threads SET last_message_at=? WHERE id=?", (now, kwargs["thread_id"]))
    return mid


def get_message(mid: int) -> dict | None:
    with _lock:
        conn = db()
        row = conn.execute("SELECT * FROM messages WHERE id=?", (int(mid),)).fetchone()
        conn.close()
    return dict(row) if row else None


def pending_drafts_count(profile_id: int | None = None) -> int:
    with _lock:
        conn = db()
        if profile_id:
            n = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE profile_id=? AND direction='out' AND status='draft'",
                (int(profile_id),),
            ).fetchone()[0]
        else:
            n = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE direction='out' AND status='draft'"
            ).fetchone()[0]
        conn.close()
    return int(n)


def sent_in_last_hour(profile_id: int) -> int:
    cutoff = time.time() - 3600
    with _lock:
        conn = db()
        n = conn.execute(
            """
            SELECT COUNT(*) FROM messages
            WHERE profile_id=? AND direction='out' AND status='sent' AND COALESCE(sent_at, created_at) >= ?
            """,
            (int(profile_id), cutoff),
        ).fetchone()[0]
        conn.close()
    return int(n)


def _parse_hhmm(value: str) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})$", value)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return h * 60 + mi


def in_quiet_hours() -> bool:
    start = _parse_hhmm(get_setting("quiet_hours_start"))
    end = _parse_hhmm(get_setting("quiet_hours_end"))
    if start is None or end is None:
        return False
    now = time.localtime()
    cur = now.tm_hour * 60 + now.tm_min
    if start == end:
        return False
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end


def can_auto_send(profile_id: int, thread: dict) -> tuple[bool, str]:
    if get_setting("send_mode") != "auto":
        return False, "Način je 'Odobravam svaku poruku'."
    if thread.get("paused"):
        return False, "Ovaj razgovor je pauziran."
    if in_quiet_hours():
        return False, "Sada su tihi sati — nacrt je spremljen za odobrenje."
    try:
        limit = int(get_setting("rate_limit_per_hour") or "20")
    except ValueError:
        limit = 20
    if limit < 1:
        return False, "Limit odgovora na sat je 0 — svi odgovori čekaju odobrenje."
    used = sent_in_last_hour(profile_id)
    if used >= limit:
        return False, f"Dosegnut je limit od {limit} odgovora na sat. Nacrt čeka odobrenje."
    return True, ""


def handle_incoming(
    profile_id: int,
    platform: str,
    external_user_id: str,
    text: str,
    display_name: str = "",
    external_id: str = "",
) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("Poruka je prazna.")
    profile = get_profile(profile_id)
    if not profile:
        raise KeyError("Profil ne postoji.")
    thread = get_or_create_thread(profile_id, platform, external_user_id, display_name)
    with _lock:
        conn = db()
        if external_id:
            dup = conn.execute(
                "SELECT id FROM messages WHERE thread_id=? AND external_id=? AND direction='in'",
                (thread["id"], external_id),
            ).fetchone()
            if dup:
                conn.close()
                return {"ok": True, "duplicate": True, "thread_id": thread["id"], "message_id": dup["id"]}
        in_id = _insert_message(
            conn,
            thread_id=thread["id"],
            profile_id=profile_id,
            direction="in",
            body=text,
            status="received",
            external_id=external_id,
        )
        conn.commit()
        conn.close()

    history = thread_messages(thread["id"])
    error = ""
    draft_body = ""
    try:
        draft_body = generate_reply(profile, history, text)
    except Exception as exc:
        error = str(exc)
        draft_body = ""

    with _lock:
        conn = db()
        draft_id = _insert_message(
            conn,
            thread_id=thread["id"],
            profile_id=profile_id,
            direction="out",
            body=draft_body or "",
            status="draft" if draft_body else "failed",
            reply_to=in_id,
            error=error,
        )
        conn.commit()
        conn.close()

    auto_ok, auto_reason = can_auto_send(profile_id, thread)
    sent = False
    send_error = ""
    if draft_body and auto_ok:
        try:
            send_draft(draft_id)
            sent = True
        except Exception as exc:
            send_error = str(exc)

    return {
        "ok": True,
        "thread_id": thread["id"],
        "message_id": in_id,
        "draft_id": draft_id,
        "draft": draft_body,
        "error": error,
        "auto_sent": sent,
        "auto_reason": auto_reason,
        "send_error": send_error,
    }


def edit_draft(draft_id: int, body: str) -> dict:
    body = (body or "").strip()
    if not body:
        raise ValueError("Nacrt ne može biti prazan.")
    msg = get_message(draft_id)
    if not msg or msg["direction"] != "out" or msg["status"] not in {"draft", "failed"}:
        raise KeyError("Nacrt nije pronađen ili je već obrađen.")
    with _lock:
        conn = db()
        conn.execute(
            "UPDATE messages SET body=?, status='draft', error='' WHERE id=?",
            (body, int(draft_id)),
        )
        conn.commit()
        conn.close()
    return get_message(draft_id)


def discard_draft(draft_id: int) -> dict:
    msg = get_message(draft_id)
    if not msg or msg["direction"] != "out" or msg["status"] not in {"draft", "failed"}:
        raise KeyError("Nacrt nije pronađen ili je već obrađen.")
    with _lock:
        conn = db()
        conn.execute("UPDATE messages SET status='discarded' WHERE id=?", (int(draft_id),))
        conn.commit()
        conn.close()
    return get_message(draft_id)


def regenerate_draft(draft_id: int) -> dict:
    msg = get_message(draft_id)
    if not msg or msg["direction"] != "out":
        raise KeyError("Nacrt nije pronađen.")
    if msg["status"] not in {"draft", "failed"}:
        raise ValueError("Može se ponovno generirati samo nacrt koji čeka odobrenje.")
    profile = get_profile(msg["profile_id"])
    if not profile:
        raise KeyError("Profil ne postoji.")
    fan_text = ""
    if msg.get("reply_to"):
        src = get_message(int(msg["reply_to"]))
        if src:
            fan_text = src["body"]
    if not fan_text:
        # zadnja ulazna u threadu
        for item in reversed(thread_messages(msg["thread_id"])):
            if item["direction"] == "in":
                fan_text = item["body"]
                break
    if not fan_text:
        raise ValueError("Nema poruke fana na koju bih odgovorio.")
    history = [m for m in thread_messages(msg["thread_id"]) if m["id"] != msg["id"]]
    try:
        body = generate_reply(profile, history, fan_text)
        with _lock:
            conn = db()
            conn.execute(
                "UPDATE messages SET body=?, status='draft', error='' WHERE id=?",
                (body, int(draft_id)),
            )
            conn.commit()
            conn.close()
    except Exception as exc:
        with _lock:
            conn = db()
            conn.execute(
                "UPDATE messages SET status='failed', error=? WHERE id=?",
                (str(exc), int(draft_id)),
            )
            conn.commit()
            conn.close()
        raise
    return get_message(draft_id)


def set_thread_paused(thread_id: int, paused: bool) -> dict:
    with _lock:
        conn = db()
        conn.execute("UPDATE threads SET paused=? WHERE id=?", (1 if paused else 0, int(thread_id)))
        conn.commit()
        conn.close()
    data = get_thread(thread_id)
    if not data:
        raise KeyError("Razgovor ne postoji.")
    return data


def send_draft(draft_id: int) -> dict:
    msg = get_message(draft_id)
    if not msg or msg["direction"] != "out":
        raise KeyError("Nacrt nije pronađen.")
    if msg["status"] == "sent":
        return msg
    if msg["status"] not in {"draft", "failed"}:
        raise ValueError("Ova poruka se ne može poslati.")
    body = (msg["body"] or "").strip()
    if not body:
        raise ValueError("Nacrt je prazan. Uredi ga ili generiraj ponovo.")
    thread = get_thread(msg["thread_id"])
    if not thread:
        raise KeyError("Razgovor ne postoji.")
    adapter = get_adapter(thread["platform"])
    try:
        adapter.send(thread["external_user_id"], body)
    except Exception as exc:
        with _lock:
            conn = db()
            conn.execute(
                "UPDATE messages SET status='failed', error=? WHERE id=?",
                (str(exc), int(draft_id)),
            )
            conn.commit()
            conn.close()
        raise RuntimeError(str(exc)) from None
    now = time.time()
    with _lock:
        conn = db()
        conn.execute(
            "UPDATE messages SET status='sent', sent_at=?, error='' WHERE id=?",
            (now, int(draft_id)),
        )
        conn.execute("UPDATE threads SET last_message_at=? WHERE id=?", (now, thread["id"]))
        conn.commit()
        conn.close()
    return get_message(draft_id)


# ---------- platform adapters ----------

class AdapterError(RuntimeError):
    pass


class PlatformAdapter:
    name = "base"

    def is_configured(self) -> bool:
        return False

    def send(self, external_user_id: str, text: str) -> dict:
        raise AdapterError("Adapter nije implementiran.")


class SimulateAdapter(PlatformAdapter):
    name = "simulate"

    def is_configured(self) -> bool:
        return True

    def send(self, external_user_id: str, text: str) -> dict:
        # Lokalna simulacija — ništa se ne šalje van.
        return {"ok": True, "platform": "simulate", "to": external_user_id, "dry_run": True}


class InstagramAdapter(PlatformAdapter):
    name = "instagram"

    def is_configured(self) -> bool:
        return bool(secret("IG_ACCESS_TOKEN"))

    def send(self, external_user_id: str, text: str) -> dict:
        token = secret("IG_ACCESS_TOKEN")
        if not token:
            raise AdapterError(
                "Instagram nije podešen. U .env upiši IG_ACCESS_TOKEN i vidi PORUKE_UPUTE.txt."
            )
        version = secret("GRAPH_API_VERSION") or GRAPH_VERSION
        url = f"https://graph.facebook.com/{version}/me/messages"
        payload = {
            "recipient": {"id": external_user_id},
            "message": {"text": text},
            "access_token": token,
        }
        try:
            data, status = _http_json(url, data=payload, timeout=30)
        except RuntimeError as exc:
            msg = str(exc)
            tok = token
            if tok and tok in msg:
                msg = msg.replace(tok, _redact(tok))
            raise AdapterError(f"Instagram slanje nije uspjelo: {msg}") from None
        return {"ok": True, "platform": "instagram", "status": status, "response": data}


class TelegramAdapter(PlatformAdapter):
    name = "telegram"

    def is_configured(self) -> bool:
        return bool(secret("TELEGRAM_BOT_TOKEN"))

    def _token(self) -> str:
        token = secret("TELEGRAM_BOT_TOKEN")
        if not token:
            raise AdapterError("Telegram nije podešen. U .env upiši TELEGRAM_BOT_TOKEN.")
        return token

    def api(self, method: str, payload: dict | None = None, timeout: float = 35) -> dict:
        token = self._token()
        url = f"https://api.telegram.org/bot{token}/{method}"
        try:
            data, _status = _http_json(url, data=payload or {}, timeout=timeout)
        except RuntimeError as exc:
            msg = str(exc)
            if token in msg:
                msg = msg.replace(token, _redact(token))
            raise AdapterError(f"Telegram {method} nije uspio: {msg}") from None
        if isinstance(data, dict) and data.get("ok") is False:
            raise AdapterError(data.get("description") or "Telegram API greška.")
        return data if isinstance(data, dict) else {"result": data}

    def send(self, external_user_id: str, text: str) -> dict:
        data = self.api("sendMessage", {"chat_id": external_user_id, "text": text}, timeout=30)
        return {"ok": True, "platform": "telegram", "response": data}


ADAPTERS = {
    "simulate": SimulateAdapter(),
    "instagram": InstagramAdapter(),
    "telegram": TelegramAdapter(),
}


def get_adapter(platform: str) -> PlatformAdapter:
    return ADAPTERS.get(platform) or ADAPTERS["simulate"]


def platform_status() -> dict:
    ig = ADAPTERS["instagram"]
    tg = ADAPTERS["telegram"]
    return {
        "instagram": {
            "configured": ig.is_configured(),
            "verify_token_set": bool(secret("IG_VERIFY_TOKEN")),
            "app_secret_set": bool(secret("IG_APP_SECRET")),
        },
        "telegram": {
            "configured": tg.is_configured(),
            "enabled": get_setting("telegram_enabled") == "1",
        },
        "simulate": {"configured": True},
    }


def mapped_profile_id(platform: str) -> int | None:
    key = "instagram_profile_id" if platform == "instagram" else (
        "telegram_profile_id" if platform == "telegram" else "active_profile_id"
    )
    raw = get_setting(key) or get_setting("active_profile_id")
    try:
        pid = int(raw)
    except (TypeError, ValueError):
        return active_profile_id()
    return pid if get_profile(pid) else active_profile_id()


def verify_instagram_webhook(mode: str, token: str, challenge: str) -> tuple[bool, str]:
    expected = secret("IG_VERIFY_TOKEN")
    if mode == "subscribe" and expected and token == expected:
        return True, challenge
    return False, "Neispravan verify token."


def check_instagram_signature(raw_body: bytes, header: str) -> bool:
    secret_val = secret("IG_APP_SECRET")
    if not secret_val:
        return False
    if not header or not header.startswith("sha256="):
        return False
    digest = hmac.new(secret_val.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[7:], digest)


def ingest_instagram_payload(payload: dict) -> list[dict]:
    """Izvuci tekstualne poruke iz Meta Instagram webhook tijela."""
    results = []
    if not isinstance(payload, dict):
        return results
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        messaging = entry.get("messaging") or entry.get("standby") or []
        for ev in messaging:
            if not isinstance(ev, dict):
                continue
            if ev.get("message", {}).get("is_echo"):
                continue
            msg = ev.get("message") or {}
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            sender = (ev.get("sender") or {}).get("id") or ""
            mid = msg.get("mid") or ""
            if sender:
                results.append({"sender": str(sender), "text": text, "mid": str(mid)})
        for change in entry.get("changes") or []:
            value = (change or {}).get("value") or {}
            if (change or {}).get("field") not in {None, "messages", "message"} and not value.get("message"):
                continue
            messages = value.get("messages") or []
            if isinstance(value.get("message"), dict):
                messages = messages + [value["message"]]
            sender = (value.get("sender") or value.get("from") or {}).get("id") or ""
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                text = (msg.get("text") or "").strip()
                mid = msg.get("mid") or msg.get("id") or ""
                sid = sender or (msg.get("from") or {}).get("id") or ""
                if text and sid:
                    results.append({"sender": str(sid), "text": text, "mid": str(mid)})
    return results


def process_instagram_webhook(payload: dict) -> dict:
    pid = mapped_profile_id("instagram")
    if not pid:
        raise RuntimeError("Nema aktivnog profila za Instagram.")
    items = ingest_instagram_payload(payload)
    handled = []
    for item in items:
        handled.append(
            handle_incoming(
                pid,
                "instagram",
                item["sender"],
                item["text"],
                display_name=item["sender"],
                external_id=item.get("mid") or "",
            )
        )
    return {"ok": True, "count": len(handled), "results": handled}


# ---------- Telegram long poll ----------

def telegram_loop(stop_event: threading.Event) -> None:
    adapter = ADAPTERS["telegram"]
    offset = 0
    while not stop_event.is_set():
        if get_setting("telegram_enabled") != "1" or not adapter.is_configured():
            if stop_event.wait(2):
                break
            continue
        try:
            data = adapter.api(
                "getUpdates",
                {"offset": offset, "timeout": 20, "allowed_updates": ["message"]},
                timeout=35,
            )
        except Exception:
            if stop_event.wait(5):
                break
            continue
        for upd in data.get("result") or []:
            offset = max(offset, int(upd.get("update_id") or 0) + 1)
            message = upd.get("message") or upd.get("edited_message") or {}
            text = (message.get("text") or "").strip()
            chat = message.get("chat") or {}
            chat_id = chat.get("id")
            if not text or chat_id is None:
                continue
            name = chat.get("first_name") or chat.get("username") or str(chat_id)
            pid = mapped_profile_id("telegram")
            if not pid:
                continue
            try:
                handle_incoming(pid, "telegram", str(chat_id), text, display_name=str(name), external_id=str(message.get("message_id") or ""))
            except Exception:
                continue


def start_telegram_worker() -> None:
    global _telegram_thread
    if _telegram_thread and _telegram_thread.is_alive():
        return
    _telegram_stop.clear()
    _telegram_thread = threading.Thread(target=telegram_loop, args=(_telegram_stop,), name="telegram-poll", daemon=True)
    _telegram_thread.start()


def stop_telegram_worker() -> None:
    _telegram_stop.set()


def public_settings() -> dict:
    return {
        "send_mode": get_setting("send_mode") or "approve",
        "rate_limit_per_hour": int(get_setting("rate_limit_per_hour") or "20" or "20"),
        "quiet_hours_start": get_setting("quiet_hours_start") or "",
        "quiet_hours_end": get_setting("quiet_hours_end") or "",
        "grok_model": grok_model_name(),
        "instagram_profile_id": get_setting("instagram_profile_id") or "",
        "telegram_profile_id": get_setting("telegram_profile_id") or "",
        "telegram_enabled": get_setting("telegram_enabled") == "1",
        "disable_cudnn": get_setting("disable_cudnn", "1") != "0",
        "quality_prefix": get_setting("quality_prefix", "1") != "0",
        "hires_fix": get_setting("hires_fix", "0") == "1",
        "browser": (get_setting("browser", "brave") or "brave").strip().lower() or "brave",
        "xai_configured": xai_configured(),
        "xai_base": xai_base(),
        "in_quiet_hours": in_quiet_hours(),
        "platforms": platform_status(),
    }


def update_settings(payload: dict) -> dict:
    allowed = {
        "send_mode",
        "rate_limit_per_hour",
        "quiet_hours_start",
        "quiet_hours_end",
        "grok_model",
        "instagram_profile_id",
        "telegram_profile_id",
        "telegram_enabled",
        "active_profile_id",
        "disable_cudnn",
        "quality_prefix",
        "hires_fix",
        "browser",
    }
    if "send_mode" in payload:
        mode = payload["send_mode"]
        if mode not in {"approve", "auto"}:
            raise ValueError("Način mora biti 'approve' ili 'auto'.")
    if "rate_limit_per_hour" in payload:
        try:
            n = int(payload["rate_limit_per_hour"])
        except (TypeError, ValueError):
            raise ValueError("Limit na sat mora biti broj.") from None
        if n < 0 or n > 500:
            raise ValueError("Limit na sat mora biti između 0 i 500.")
        payload = {**payload, "rate_limit_per_hour": str(n)}
    if "quiet_hours_start" in payload and payload["quiet_hours_start"]:
        if _parse_hhmm(str(payload["quiet_hours_start"])) is None:
            raise ValueError("Tihi sati (početak) moraju biti u obliku HH:MM.")
    if "quiet_hours_end" in payload and payload["quiet_hours_end"]:
        if _parse_hhmm(str(payload["quiet_hours_end"])) is None:
            raise ValueError("Tihi sati (kraj) moraju biti u obliku HH:MM.")
    if "telegram_enabled" in payload:
        payload = {**payload, "telegram_enabled": "1" if payload["telegram_enabled"] in {True, "1", 1, "true"} else "0"}
    if "browser" in payload:
        raw = str(payload.get("browser") or "").strip().lower()
        if raw not in {"brave", "edge", "chrome", "default"}:
            raise ValueError("Preglednik mora biti brave, edge, chrome ili default.")
        payload = {**payload, "browser": raw}
    for flag in ("disable_cudnn", "quality_prefix", "hires_fix"):
        if flag in payload:
            payload = {**payload, flag: "1" if payload[flag] in {True, "1", 1, "true", "on"} else "0"}
    for key in allowed:
        if key in payload and payload[key] is not None:
            set_setting(key, str(payload[key]))
    if payload.get("telegram_enabled") in {"1", True, 1, "true"}:
        start_telegram_worker()
    return public_settings()


def app_state() -> dict:
    pid = active_profile_id()
    return {
        "ok": True,
        "active_profile_id": pid,
        "active_profile": get_profile(pid) if pid else None,
        "profiles": list_profiles(),
        "pending_drafts": pending_drafts_count(pid) if pid else 0,
        "settings": public_settings(),
    }
