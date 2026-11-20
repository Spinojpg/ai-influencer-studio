# -*- coding: utf-8 -*-
"""Inbox + CRM: memorija po fanu, detekcija interesa, AI chat (lokalni Ollama / LM Studio, xAI Grok ili
OpenAI-kompatibilan API, uz pravila kao rezervu), custom narudžbe, pretplatnici i analitika.

Način slanja: "Nacrt za odobrenje" je zadan, a "Automatsko slanje odmah" se uključuje jednim klikom
globalno, po kanalu ili po influenceru (prednost: influencer > kanal > globalno).
Ugrađeni promptovi su SFW: persona je fiktivna odrasla osoba, ponude su pretplata, editorial setovi i
personalizirani SFW portreti/shoutouti, a plaćanje ide isključivo preko službene platforme.
"""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

import inbox

from . import generation_service
from .common import HttpError, clamp_float, conn, data_dir, env, http_request, jdump, jload, now, redact, row_dict

PLATFORMS = ("simulate", "instagram", "instagram_comment", "facebook_comment", "telegram", "premium")
PLATFORM_LABELS = {"simulate": "Simulacija", "instagram": "Instagram DM", "instagram_comment": "Instagram komentari",
                   "facebook_comment": "Facebook komentari", "telegram": "Telegram", "premium": "Premium platforma"}
SEND_CHANNELS = ("simulate", "instagram", "telegram", "premium", "instagram_comment", "facebook_comment")
TIERS = ("free", "subscriber", "vip")
INTEREST_LEVELS = ("low", "medium", "high", "custom_request", "subscriber")
INTEREST_LABELS = {"low": "Nizak", "medium": "Srednji", "high": "Visok", "custom_request": "Custom zahtjev", "subscriber": "Pretplatnik"}
ORDER_STATUSES = ("pending", "generating", "ready", "delivered", "paid", "cancelled")
ORDER_LABELS = {"pending": "Na čekanju", "generating": "Generira se", "ready": "Spremno", "delivered": "Isporučeno", "paid": "Plaćeno", "cancelled": "Otkazano"}
LLM_BACKENDS = ("auto", "ollama", "openai_compat", "xai", "rules")
DEFAULT_OLLAMA = "http://127.0.0.1:11434"

_http = http_request
_REACH: dict[str, tuple[float, bool]] = {}


def set_http(fn) -> None:
    global _http
    _http = fn or http_request
    _REACH.clear()


# ---------- shema ----------

def ensure_schema() -> None:
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS crm_contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                external_user_id TEXT NOT NULL,
                thread_id INTEGER,
                display_name TEXT DEFAULT '',
                handle TEXT DEFAULT '',
                tier TEXT DEFAULT 'free',
                tags_json TEXT DEFAULT '[]',
                preferences TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                interest TEXT DEFAULT 'low',
                interest_score REAL DEFAULT 0,
                suggested_action TEXT DEFAULT '',
                total_spent REAL DEFAULT 0,
                messages_in INTEGER DEFAULT 0,
                notes TEXT DEFAULT '',
                unread INTEGER DEFAULT 0,
                last_seen REAL DEFAULT 0,
                created_at REAL NOT NULL,
                UNIQUE(profile_id, platform, external_user_id)
            );
            CREATE TABLE IF NOT EXISTS crm_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_id INTEGER NOT NULL,
                kind TEXT NOT NULL DEFAULT 'fact',
                content TEXT NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY(contact_id) REFERENCES crm_contacts(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_mem_contact ON crm_memory(contact_id, created_at);
            CREATE TABLE IF NOT EXISTS crm_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_id INTEGER,
                profile_id INTEGER,
                description TEXT DEFAULT '',
                prompt TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                price REAL DEFAULT 0,
                currency TEXT DEFAULT 'EUR',
                job_id INTEGER,
                gallery_id INTEGER,
                image_json TEXT DEFAULT '{}',
                channel TEXT DEFAULT '',
                delivery_json TEXT DEFAULT '{}',
                error TEXT DEFAULT '',
                source_message_id INTEGER,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                delivered_at REAL,
                paid_at REAL
            );
            CREATE TABLE IF NOT EXISTS crm_purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_id INTEGER,
                profile_id INTEGER,
                kind TEXT DEFAULT 'custom',
                amount REAL DEFAULT 0,
                currency TEXT DEFAULT 'EUR',
                channel TEXT DEFAULT '',
                content_type TEXT DEFAULT '',
                template_id INTEGER,
                order_id INTEGER,
                note TEXT DEFAULT '',
                created_at REAL NOT NULL
            );
            """
        )
        for key, val in (("llm_backend", "auto"), ("crm_llm_analysis", "0"), ("ollama_model", ""), ("openai_compat_model", "")):
            c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (key, val))


# ---------- način slanja (globalno / kanal / influencer) ----------

def channel_send_modes() -> dict:
    return {ch: (inbox.get_setting(f"send_mode_{ch}", "") or "") for ch in SEND_CHANNELS}


def set_send_mode(scope: str, mode: str, *, platform: str = "", profile_id=None) -> dict:
    mode = (mode or "").lower()
    if scope == "global":
        if mode not in {"auto", "approve"}:
            raise ValueError("Globalni način je 'auto' ili 'approve'.")
        inbox.set_setting("send_mode", mode)
    elif scope == "channel":
        if platform not in SEND_CHANNELS:
            raise ValueError("Nepoznat kanal.")
        if mode not in {"", "auto", "approve", "inherit"}:
            raise ValueError("Način kanala je 'auto', 'approve' ili prazno (kao globalno).")
        inbox.set_setting(f"send_mode_{platform}", "" if mode == "inherit" else mode)
    elif scope == "profile":
        if not profile_id:
            raise ValueError("Nedostaje influencer.")
        generation_service.save_profile_extras(int(profile_id), {"send_mode": "" if mode == "inherit" else mode})
    else:
        raise ValueError("Opseg je global, channel ili profile.")
    return send_mode_state()


def effective_send_mode(profile_id, platform: str) -> tuple[str, str]:
    """(mode, izvor) — influencer > kanal > globalno."""
    pm = (generation_service.profile_extras(profile_id).get("send_mode") if profile_id else "") or ""
    if pm in {"auto", "approve"}:
        return pm, "influencer"
    cm = inbox.get_setting(f"send_mode_{platform}", "") or ""
    if cm in {"auto", "approve"}:
        return cm, "kanal"
    gm = inbox.get_setting("send_mode", "approve") or "approve"
    return (gm if gm in {"auto", "approve"} else "approve"), "globalno"


def send_mode_state() -> dict:
    profiles = []
    for p in inbox.list_profiles():
        profiles.append({"id": p["id"], "name": p["name"], "send_mode": generation_service.profile_extras(p["id"]).get("send_mode", "")})
    return {"global": inbox.get_setting("send_mode", "approve") or "approve", "channels": channel_send_modes(),
            "profiles": profiles, "labels": PLATFORM_LABELS}


# ---------- kontakti i memorija ----------

def _contact_row(row) -> dict:
    d = row_dict(row)
    d["tags"] = jload(d.pop("tags_json", "[]"), []) or []
    d["interest_label"] = INTEREST_LABELS.get(d.get("interest"), d.get("interest"))
    d["platform_label"] = PLATFORM_LABELS.get(d.get("platform"), d.get("platform"))
    return d


def get_or_create_contact(profile_id: int, platform: str, external_user_id: str, *, display_name: str = "", thread_id=None) -> dict:
    with conn() as c:
        row = c.execute("SELECT * FROM crm_contacts WHERE profile_id=? AND platform=? AND external_user_id=?",
                        (int(profile_id), platform, str(external_user_id))).fetchone()
        if not row:
            t = now()
            c.execute("""INSERT INTO crm_contacts(profile_id, platform, external_user_id, thread_id, display_name, handle, created_at, last_seen)
                         VALUES (?,?,?,?,?,?,?,?)""", (int(profile_id), platform, str(external_user_id), thread_id, display_name or "", display_name or "", t, t))
            row = c.execute("SELECT * FROM crm_contacts WHERE id=last_insert_rowid()").fetchone()
        elif thread_id and not row["thread_id"]:
            c.execute("UPDATE crm_contacts SET thread_id=? WHERE id=?", (thread_id, row["id"]))
            row = c.execute("SELECT * FROM crm_contacts WHERE id=?", (row["id"],)).fetchone()
    return _contact_row(row)


def contact_for_thread(thread_id) -> dict | None:
    if not thread_id:
        return None
    with conn() as c:
        row = c.execute("SELECT * FROM crm_contacts WHERE thread_id=?", (int(thread_id),)).fetchone()
    if row:
        return _contact_row(row)
    th = inbox.get_thread(int(thread_id))
    if not th:
        return None
    return get_or_create_contact(th["profile_id"], th["platform"], th["external_user_id"], display_name=th.get("display_name") or "", thread_id=th["id"])


def get_contact(cid) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM crm_contacts WHERE id=?", (int(cid),)).fetchone()
    return _contact_row(row) if row else None


def memory_for(cid: int, limit: int = 30) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM crm_memory WHERE contact_id=? ORDER BY id DESC LIMIT ?", (int(cid), int(limit))).fetchall()
    return [row_dict(r) for r in rows]


def add_memory(cid: int, content: str, kind: str = "fact") -> None:
    content = (content or "").strip()[:500]
    if not content:
        return
    with conn() as c:
        dup = c.execute("SELECT id FROM crm_memory WHERE contact_id=? AND content=?", (int(cid), content)).fetchone()
        if not dup:
            c.execute("INSERT INTO crm_memory(contact_id, kind, content, created_at) VALUES (?,?,?,?)", (int(cid), kind, content, now()))


def update_contact(cid: int, payload: dict) -> dict:
    sets = {}
    if "tier" in payload:
        if payload["tier"] not in TIERS:
            raise ValueError("Razina je free, subscriber ili vip.")
        sets["tier"] = payload["tier"]
    for k in ("notes", "preferences", "summary", "display_name", "handle"):
        if k in payload:
            sets[k] = str(payload.get(k) or "")[:2000]
    if "tags" in payload:
        tags = payload["tags"] if isinstance(payload["tags"], list) else str(payload["tags"]).split(",")
        sets["tags_json"] = jdump([t.strip()[:40] for t in tags if str(t).strip()][:20])
    if "unread" in payload:
        sets["unread"] = 1 if payload["unread"] else 0
    if sets:
        with conn() as c:
            c.execute(f"UPDATE crm_contacts SET {', '.join(k + '=?' for k in sets)} WHERE id=?", [*sets.values(), int(cid)])
    if payload.get("memory"):
        add_memory(cid, str(payload["memory"]), "note")
    return contact_detail(cid)


def list_contacts(*, tier: str = "", profile_id=None, interest: str = "", q: str = "", limit: int = 200) -> list[dict]:
    where, args = [], []
    if tier in TIERS:
        where.append("tier=?")
        args.append(tier)
    if profile_id not in (None, ""):
        where.append("profile_id=?")
        args.append(int(profile_id))
    if interest in INTEREST_LEVELS:
        where.append("interest=?")
        args.append(interest)
    if q:
        where.append("(display_name LIKE ? OR handle LIKE ? OR notes LIKE ?)")
        args += [f"%{q}%"] * 3
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with conn() as c:
        rows = c.execute(f"SELECT * FROM crm_contacts {clause} ORDER BY last_seen DESC LIMIT ?", [*args, int(limit)]).fetchall()
    return [_contact_row(r) for r in rows]


def contact_detail(cid: int) -> dict:
    ct = get_contact(cid)
    if not ct:
        raise KeyError("Kontakt ne postoji.")
    with conn() as c:
        purchases = [row_dict(r) for r in c.execute("SELECT * FROM crm_purchases WHERE contact_id=? ORDER BY id DESC", (int(cid),)).fetchall()]
    ct["memory"] = memory_for(cid)
    ct["purchases"] = purchases
    ct["orders"] = list_orders(contact_id=cid)
    return ct


# ---------- detekcija interesa i izvlačenje memorije ----------

SIGNALS = {
    "subscription": (r"pretplat", r"subscri", r"premium", r"\bvip\b", r"ekskluziv", r"exclusive", r"\bpaket", r"članstv", r"membership"),
    "custom": (r"custom", r"po narudžb", r"po narudzb", r"personaliz", r"posvet", r"shout ?out", r"rođendan", r"rodjendan", r"birthday",
               r"napravi(š|s)? mi", r"can you make", r"slik[au] za mene", r"fotk[au] za mene", r"just for me", r"samo za mene", r"s mojim imenom", r"with my name"),
    "purchase": (r"cijen", r"koliko košta", r"koliko kosta", r"\bprice\b", r"how much", r"platiti", r"plati(m|t)", r"kupi(ti|m)", r"\bbuy\b", r"\bpay\b", r"\btip\b", r"donir"),
    "engagement": (r"obožavam", r"obozavam", r"\blove\b", r"prekrasn", r"predivn", r"beautiful", r"gorgeous", r"još slik", r"jos slik", r"more pics", r"more photos", r"najbolj", r"\bfan\b", r"❤|😍|🔥"),
    "question": (r"\?",),
}
WEIGHTS = {"subscription": 3, "custom": 4, "purchase": 3, "engagement": 1, "question": 0.5}


def detect_interest(text: str, *, history: list[str] | None = None, tier: str = "free") -> dict:
    low = (text or "").lower()
    signals: dict[str, int] = {}
    for name, pats in SIGNALS.items():
        n = sum(1 for p in pats if re.search(p, low))
        if n:
            signals[name] = n
    score = sum(WEIGHTS[k] * min(v, 2) for k, v in signals.items())
    for old in (history or [])[-6:]:
        ol = (old or "").lower()
        if any(re.search(p, ol) for p in SIGNALS["subscription"] + SIGNALS["purchase"]):
            score += 1
        if any(re.search(p, ol) for p in SIGNALS["engagement"]):
            score += 0.5
    if tier in {"subscriber", "vip"}:
        level = "subscriber"
    elif signals.get("custom"):
        level = "custom_request"
    elif score >= 5:
        level = "high"
    elif score >= 2:
        level = "medium"
    else:
        level = "low"
    action, offer = suggest_action(level, signals)
    return {"level": level, "label": INTEREST_LABELS[level], "score": round(float(score), 2), "signals": signals,
            "suggested_action": action, "offer": offer}


def suggest_action(level: str, signals: dict | None = None) -> tuple[str, str]:
    if level == "custom_request":
        return ("Kreiraj custom narudžbu i pošalji ponudu s cijenom.", "Personalizirani SFW portret / shoutout po narudžbi")
    if level == "subscriber":
        return ("Zahvali se i ponudi VIP set ili personalizirani portret.", "VIP editorial set ili custom portret")
    if level == "high":
        return ("Fan je spreman: pošalji link na premium pretplatu (službena platforma).", "Premium pretplata (ekskluzivni editorial i lifestyle setovi)")
    if level == "medium":
        return ("Nastavi topao razgovor, podijeli javni teaser i usput spomeni premium.", "Javni teaser + najava premium sadržaja")
    return ("Odgovori prijateljski i postavi pitanje da razgovor teče.", "")


_NAME_RE = re.compile(r"(?:zovem se|ja sam|my name is|i'?m|i am|ime mi je)\s+([A-ZČĆŠŽĐ][\wčćšžđ]{1,20})", re.I)
_FROM_RE = re.compile(r"(?:\biz\s+([A-ZČĆŠŽĐ][\wčćšžđ]{2,25})|i'?m from\s+([A-Z][\w]{2,25}))")
_LIKE_RE = re.compile(r"(?:volim|obožavam|obozavam|i love|i like|sviđa mi se|svida mi se)\s+([^.,!?\n]{3,60})", re.I)
_AGE_RE = re.compile(r"(?:imam|i'?m|i am)\s+(\d{2})\s*(?:godin|years)", re.I)
_BDAY_RE = re.compile(r"(?:rođendan|rodjendan|birthday)[^.!?\n]{0,40}", re.I)


def extract_memory(text: str) -> list[tuple[str, str]]:
    out = []
    t = text or ""
    m = _NAME_RE.search(t)
    if m and m.group(1).lower() not in {"tvoj", "tvoja", "fan", "here", "so", "very", "not", "just", "a", "the"}:
        out.append(("fact", f"Ime: {m.group(1)}"))
    m = _FROM_RE.search(t)
    if m:
        out.append(("fact", f"Lokacija: {m.group(1) or m.group(2)}"))
    for m in _LIKE_RE.finditer(t):
        out.append(("preference", f"Voli: {m.group(1).strip()}"))
    m = _AGE_RE.search(t)
    if m:
        out.append(("fact", f"Dob: {m.group(1)}"))
    m = _BDAY_RE.search(t)
    if m:
        out.append(("fact", "Spomenuo rođendan: " + m.group(0).strip()[:60]))
    return out


def on_incoming(profile_id: int, thread: dict, text: str, *, display_name: str = "") -> dict:
    ct = get_or_create_contact(profile_id, thread["platform"], thread["external_user_id"], display_name=display_name or thread.get("display_name") or "", thread_id=thread["id"])
    for kind, content in extract_memory(text):
        add_memory(ct["id"], content, kind)
    hist = [m["body"] for m in inbox.thread_messages(thread["id"]) if m.get("direction") == "in"][:-1]
    info = detect_interest(text, history=hist, tier=ct.get("tier") or "free")
    if _setting_on("crm_llm_analysis"):
        try:
            llm = llm_interest(text)
            if llm and llm in INTEREST_LEVELS and INTEREST_LEVELS.index(llm) > INTEREST_LEVELS.index(info["level"]) and info["level"] != "subscriber":
                info["level"] = llm
                info["label"] = INTEREST_LABELS[llm]
                info["suggested_action"], info["offer"] = suggest_action(llm, info["signals"])
                info["llm"] = True
        except Exception:
            pass
    prefs = [m["content"].split(": ", 1)[-1] for m in memory_for(ct["id"]) if m["kind"] == "preference"][:8]
    summary = _rolling_summary(hist + [text], ct)
    with conn() as c:
        c.execute(
            """UPDATE crm_contacts SET interest=?, interest_score=?, suggested_action=?, preferences=?, summary=?,
            messages_in=messages_in+1, unread=1, last_seen=?, display_name=COALESCE(NULLIF(?, ''), display_name) WHERE id=?""",
            (info["level"], info["score"], info["suggested_action"] + ((" Ponuda: " + info["offer"]) if info["offer"] else ""),
             ", ".join(prefs), summary, now(), display_name or "", ct["id"]),
        )
    out = get_contact(ct["id"])
    out["interest_info"] = info
    return out


def _rolling_summary(fan_texts: list[str], ct: dict) -> str:
    recent = [t.strip().replace("\n", " ")[:90] for t in fan_texts[-4:] if t and t.strip()]
    facts = [m["content"] for m in memory_for(ct["id"]) if m["kind"] == "fact"][:4]
    base = f"{len(fan_texts)} poruka. " + ("; ".join(facts) + ". " if facts else "")
    return (base + "Zadnje teme: " + " | ".join(recent))[:900]


def _setting_on(key: str) -> bool:
    return (inbox.get_setting(key, "0") or "0") == "1"


# ---------- LLM ----------

def ollama_base() -> str:
    return (env("OLLAMA_BASE_URL") or DEFAULT_OLLAMA).rstrip("/").removesuffix("/v1")


def _reachable(url: str, ttl: float = 60) -> bool:
    hit = _REACH.get(url)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    ok = False
    try:
        r = _http("GET", url, timeout=1.5)
        ok = bool(r) and int(r.get("status") or 0) < 500
    except Exception:
        ok = False
    _REACH[url] = (time.time(), ok)
    return ok


def ollama_model() -> str:
    m = (inbox.get_setting("ollama_model", "") or env("OLLAMA_MODEL")).strip()
    if m:
        return m
    try:
        r = _http("GET", ollama_base() + "/api/tags", timeout=3)
        models = ((r or {}).get("json") or {}).get("models") or []
        if models:
            return str(models[0].get("name") or models[0].get("model") or "")
    except Exception:
        pass
    return "llama3.1:8b"


def compat_base() -> str:
    return (env("OPENAI_COMPAT_BASE_URL") or "").rstrip("/")


def resolve_backend() -> str:
    b = (inbox.get_setting("llm_backend", "auto") or "auto").lower()
    if b != "auto":
        return b if b in LLM_BACKENDS else "rules"
    if _reachable(ollama_base() + "/api/tags"):
        return "ollama"
    if compat_base() and _reachable(compat_base() + "/models"):
        return "openai_compat"
    if inbox.xai_configured():
        return "xai"
    return "rules"


def _openai_chat(base: str, model: str, messages: list[dict], key: str = "", timeout: float = 120) -> str:
    headers = {"Authorization": "Bearer " + key} if key else {}
    try:
        r = _http("POST", base.rstrip("/") + "/chat/completions", json_body={"model": model, "messages": messages, "temperature": 0.8, "stream": False},
                  headers=headers, timeout=timeout)
    except HttpError as exc:
        raise RuntimeError(redact(str(exc), key)) from None
    j = (r or {}).get("json") or {}
    choices = j.get("choices") or []
    if choices and (choices[0].get("message") or {}).get("content"):
        return str(choices[0]["message"]["content"]).strip()
    msg = (j.get("message") or {}).get("content")  # Ollama /api/chat
    if msg:
        return str(msg).strip()
    raise RuntimeError("LLM nije vratio odgovor.")


def chat(messages: list[dict], *, backend: str | None = None) -> tuple[str, str]:
    b = backend or resolve_backend()
    if b == "ollama":
        try:
            return _openai_chat(ollama_base() + "/v1", ollama_model(), messages), "ollama"
        except Exception:
            r = _http("POST", ollama_base() + "/api/chat", json_body={"model": ollama_model(), "messages": messages, "stream": False}, timeout=120)
            msg = (((r or {}).get("json") or {}).get("message") or {}).get("content")
            if not msg:
                raise RuntimeError("Ollama nije vratio odgovor.")
            return str(msg).strip(), "ollama"
    if b == "openai_compat":
        model = (inbox.get_setting("openai_compat_model", "") or env("OPENAI_COMPAT_MODEL") or "local-model").strip()
        return _openai_chat(compat_base() or "http://127.0.0.1:1234/v1", model, messages, env("OPENAI_COMPAT_API_KEY")), "openai_compat"
    if b == "xai":
        return inbox.call_grok(messages), "xai"
    raise RuntimeError("rules")


def llm_interest(text: str) -> str:
    prompt = [{"role": "system", "content": "Klasificiraj namjeru fana u jednu riječ: low, medium, high, custom_request. high = želi pretplatu/kupnju; custom_request = traži personaliziranu sliku/shoutout. Vrati samo riječ."},
              {"role": "user", "content": text[:800]}]
    out, _b = chat(prompt)
    word = re.sub(r"[^a-z_]", "", out.strip().lower().split()[0] if out.strip() else "")
    return word


def build_crm_system_prompt(profile: dict, contact: dict | None, interest: dict | None = None) -> str:
    base = inbox.build_system_prompt(profile)
    extras = generation_service.profile_extras(profile.get("id"))
    lines = []
    if extras.get("bio"):
        lines.append(f"Bio persone: {extras['bio']}")
    if contact:
        mem = memory_for(contact["id"], 12)
        facts = "; ".join(m["content"] for m in mem) or "još ništa"
        lines.append(f"Fan: {contact.get('display_name') or 'fan'} (razina: {contact.get('tier') or 'free'}). Zapamćeno: {facts}.")
        if contact.get("summary"):
            lines.append(f"Sažetak dosadašnjeg razgovora: {contact['summary']}")
    if interest and interest.get("offer"):
        lines.append(f"Signal interesa: {interest.get('label')}. Ako prirodno paše, spomeni: {interest['offer']}.")
    guide = """
ANGAŽMAN (vrijedi uz pravila iznad):
- Budi topla i osobna, koristi ono što znaš o fanu (ime, interesi) i postavi kratko pitanje da razgovor teče.
- Ponude (premium pretplata, ekskluzivni editorial/lifestyle setovi, personalizirani SFW portret ili shoutout) spominji
  postupno i samo kad fan pokaže interes — bez pritiska, najviše jednom u par poruka.
- Plaćanje i pretplata idu isključivo preko službene platforme ili linka; nikad ne traži kartice, lozinke ni uplate u chatu.
- Sadržaj je uvijek SFW (moda, lifestyle, putovanja, studio portreti, behind the scenes). Eksplicitne zahtjeve pristojno odbij
  i ponudi SFW alternativu."""
    return base + ("\n\n" + "\n".join(lines) if lines else "") + "\n" + guide


def rule_reply(profile: dict, fan_text: str, contact: dict | None = None, interest: dict | None = None) -> str:
    name = ""
    if contact:
        for m in memory_for(contact["id"], 20):
            if m["content"].startswith("Ime: "):
                name = m["content"][5:]
                break
        name = name or (contact.get("display_name") or "")
        if name.lower().startswith(("sim-", "fan")):
            name = ""
    hi = f"Hej {name}! " if name else "Hej! "
    low = (fan_text or "").lower()
    level = (interest or {}).get("level") or "low"
    if re.search(r"jesi li (stvarn|prav|čovjek|covjek|ai|bot)|are you (real|human|ai|a bot)", low):
        return hi + "Iskreno — ja sam AI persona, digitalni lik, ne stvarna osoba. Ali drago mi je da pišeš 😊 Što te dovelo ovdje?"
    if level == "custom_request":
        return hi + "Uh, to zvuči kao super ideja za personalizirani portret! 📸 Napiši mi malo više što bi htio (stil, mjesto, poruka), pa ti javim detalje i cijenu preko službene platforme."
    if level == "subscriber":
        return hi + "Hvala ti što si uz mene, to mi stvarno puno znači 💛 Pripremam novi ekskluzivni set — što bi volio vidjeti sljedeće?"
    if level == "high":
        return hi + "Drago mi je da ti se sviđa! Ekskluzivne editorial i lifestyle setove objavljujem za pretplatnike na službenoj platformi — link ti mogu poslati. Koji ti je stil najdraži?"
    if re.search(r"\b(bok|hej|hello|hi|pozdrav|ćao|cao|zdravo)\b", low):
        return hi + "Kako si danas? 😊"
    if level == "medium":
        return hi + "Hvala ti puno! 🥰 Uskoro stiže novi set na profilu, a ono najbolje čuvam za premium. Što ti se najviše svidjelo dosad?"
    return hi + "Hvala na poruci! 😊 Reci mi nešto o sebi — što te zanima?"


def generate_reply(profile: dict, history: list[dict], fan_text: str, *, contact: dict | None = None, thread_id=None) -> dict:
    """Vrati {text, backend, fallback}. Nikad ne baca grešku — u najgorem slučaju odgovori pravilima."""
    if contact is None and thread_id:
        contact = contact_for_thread(thread_id)
    hist_in = [m.get("body") or "" for m in history if m.get("direction") == "in"]
    interest = detect_interest(fan_text, history=hist_in[:-1], tier=(contact or {}).get("tier") or "free")
    msgs = [{"role": "system", "content": build_crm_system_prompt(profile, contact, interest)}]
    for item in history[-inbox.HISTORY_LIMIT:]:
        body = (item.get("body") or "").strip()
        if body and item.get("status") in {"received", "sent"}:
            msgs.append({"role": "user" if item.get("direction") == "in" else "assistant", "content": body})
    if msgs[-1].get("role") != "user" or msgs[-1].get("content") != fan_text:
        msgs.append({"role": "user", "content": fan_text})
    backend = resolve_backend()
    if backend != "rules":
        try:
            text, used = chat(msgs, backend=backend)
            if text:
                return {"text": text, "backend": used, "fallback": False}
        except Exception as exc:
            return {"text": rule_reply(profile, fan_text, contact, interest), "backend": "rules", "fallback": True, "error": str(exc)[:300]}
    return {"text": rule_reply(profile, fan_text, contact, interest), "backend": "rules", "fallback": backend != "rules"}


def llm_status() -> dict:
    b = (inbox.get_setting("llm_backend", "auto") or "auto")
    return {"setting": b, "active": resolve_backend(), "ollama_url": ollama_base(), "ollama_model": inbox.get_setting("ollama_model", "") or env("OLLAMA_MODEL"),
            "compat_url": compat_base(), "compat_model": inbox.get_setting("openai_compat_model", "") or env("OPENAI_COMPAT_MODEL"),
            "xai": inbox.xai_configured(), "analysis": _setting_on("crm_llm_analysis"), "options": list(LLM_BACKENDS)}


def save_llm_settings(payload: dict) -> dict:
    if "llm_backend" in payload:
        if payload["llm_backend"] not in LLM_BACKENDS:
            raise ValueError("Nepoznat LLM backend.")
        inbox.set_setting("llm_backend", payload["llm_backend"])
    for k in ("ollama_model", "openai_compat_model"):
        if k in payload:
            inbox.set_setting(k, str(payload.get(k) or "")[:120])
    if "crm_llm_analysis" in payload:
        inbox.set_setting("crm_llm_analysis", "1" if payload["crm_llm_analysis"] in (True, 1, "1", "true", "on") else "0")
    _REACH.clear()
    return llm_status()


# ---------- custom narudžbe ----------

ORDER_PROMPT_PREFIX = "personalized editorial portrait photo"
ORDER_PROMPT_SUFFIX = "tasteful, friendly, natural light, high quality photography"


def _order_row(row) -> dict:
    d = row_dict(row)
    d["image"] = jload(d.pop("image_json", "{}"), {}) or {}
    d["delivery"] = jload(d.pop("delivery_json", "{}"), {}) or {}
    d["status_label"] = ORDER_LABELS.get(d.get("status"), d.get("status"))
    if d.get("gallery_id"):
        item = generation_service.gallery_item(d["gallery_id"])
        d["image_url"] = (item or {}).get("url") or ""
    else:
        d["image_url"] = d["image"].get("url") or ""
    ct = get_contact(d["contact_id"]) if d.get("contact_id") else None
    d["contact_name"] = (ct or {}).get("display_name") or ""
    d["platform"] = (ct or {}).get("platform") or ""
    return d


def compose_order_prompt(description: str) -> str:
    desc = re.sub(r"\s+", " ", (description or "").strip())[:400]
    return ", ".join(x for x in (ORDER_PROMPT_PREFIX, desc, ORDER_PROMPT_SUFFIX) if x)


def create_order(*, contact_id=None, profile_id=None, description: str = "", price=None, source_message_id=None, thread_id=None) -> dict:
    if not contact_id and thread_id:
        ct = contact_for_thread(thread_id)
        contact_id = (ct or {}).get("id")
        profile_id = profile_id or (ct or {}).get("profile_id")
    if contact_id and not profile_id:
        profile_id = (get_contact(contact_id) or {}).get("profile_id")
    if not profile_id:
        profile_id = inbox.active_profile_id()
    if source_message_id and not description:
        msg = inbox.get_message(int(source_message_id))
        description = (msg or {}).get("body") or ""
    description = (description or "").strip()
    if not description:
        raise ValueError("Opiši što fan želi (npr. portret s porukom za rođendan).")
    t = now()
    with conn() as c:
        c.execute("""INSERT INTO crm_orders(contact_id, profile_id, description, prompt, status, price, source_message_id, created_at, updated_at)
                     VALUES (?,?,?,?, 'pending', ?, ?, ?, ?)""",
                  (contact_id, profile_id, description[:2000], compose_order_prompt(description), clamp_float(price, 0, 100000, 0) if price not in (None, "") else 0,
                   source_message_id, t, t))
        oid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    return get_order(oid)


def get_order(oid) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM crm_orders WHERE id=?", (int(oid),)).fetchone()
    return _order_row(row) if row else None


def list_orders(*, status: str = "", contact_id=None, limit: int = 200) -> list[dict]:
    where, args = [], []
    if status in ORDER_STATUSES:
        where.append("status=?")
        args.append(status)
    if contact_id:
        where.append("contact_id=?")
        args.append(int(contact_id))
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with conn() as c:
        rows = c.execute(f"SELECT * FROM crm_orders {clause} ORDER BY id DESC LIMIT ?", [*args, int(limit)]).fetchall()
    return [_order_row(r) for r in rows]


def _set_order(oid: int, **fields) -> None:
    for k in ("image", "delivery"):
        if k in fields:
            fields[k + "_json"] = jdump(fields.pop(k))
    fields["updated_at"] = now()
    with conn() as c:
        c.execute(f"UPDATE crm_orders SET {', '.join(k + '=?' for k in fields)} WHERE id=?", [*fields.values(), int(oid)])


def update_order(oid: int, payload: dict) -> dict:
    o = get_order(oid)
    if not o:
        raise KeyError("Narudžba ne postoji.")
    sets = {}
    if "price" in payload:
        sets["price"] = clamp_float(payload.get("price"), 0, 100000, 0)
    if "currency" in payload:
        sets["currency"] = str(payload.get("currency") or "EUR")[:8].upper()
    if "prompt" in payload:
        sets["prompt"] = str(payload.get("prompt") or "")[:3000]
    if "description" in payload:
        sets["description"] = str(payload.get("description") or "")[:2000]
    if payload.get("status") == "cancelled":
        sets["status"] = "cancelled"
    if sets:
        _set_order(oid, **sets)
    return get_order(oid)


def generate_order(oid: int, overrides: dict | None = None) -> dict:
    o = get_order(oid)
    if not o:
        raise KeyError("Narudžba ne postoji.")
    if o["status"] in {"delivered", "paid", "cancelled"}:
        raise ValueError("Ova narudžba je već zatvorena.")
    body = {**generation_service.default_body_options(), "prompt": o["prompt"] or compose_order_prompt(o["description"]),
            "persona_id": o["profile_id"], "size_preset": "ig_portrait", "batch": 1, "face_detailer": False}
    tpl = next((t for t in generation_service.list_templates("premium") if t.get("key") == "premium_custom_portrait"), None)
    if tpl:
        body["face_detailer"] = bool(tpl.get("face_detailer"))
        body["face_detailer_optional"] = True  # bez Impact Packa narudžba se generira bez Face Detailera
    body.update(overrides or {})
    job = generation_service.enqueue(body, label=f"Custom narudžba #{oid}", kind="order", order_id=int(oid))
    _set_order(oid, status="generating", job_id=job["id"], error="")
    return get_order(oid)


def _on_job_done(job: dict) -> None:
    if not job or not job.get("order_id"):
        return
    oid = int(job["order_id"])
    if job["status"] == "done" and job.get("images"):
        img = job["images"][0]
        _set_order(oid, status="ready", gallery_id=img.get("gallery_id"), image={k: img.get(k) for k in ("filename", "subfolder", "type", "url")}, error="")
    elif job["status"] in {"error", "cancelled"}:
        _set_order(oid, status="pending", error=job.get("error") or "Generiranje nije uspjelo.")


generation_service.register_done_hook(_on_job_done)


def deliver_order(oid: int, channel: str = "auto", message: str = "") -> dict:
    o = get_order(oid)
    if not o:
        raise KeyError("Narudžba ne postoji.")
    if o["status"] not in {"ready", "delivered"}:
        raise ValueError("Narudžba još nema gotovu sliku.")
    item = generation_service.gallery_item(o["gallery_id"]) if o.get("gallery_id") else None
    data = generation_service.read_item_bytes(item or o["image"])
    filename = (item or o["image"]).get("filename") or f"narudzba_{oid}.png"
    ct = get_contact(o["contact_id"]) if o.get("contact_id") else None
    from . import posting_service
    if channel == "auto":
        channel = "telegram" if (ct or {}).get("platform") == "telegram" else ("premium_api" if env("PREMIUM_API_URL") else "local")
    caption = message or (f"Tvoj personalizirani portret je spreman 💛" + (f" Cijena: {o['price']:.2f} {o['currency']} (plaćanje preko službene platforme)." if o.get("price") else ""))
    if channel == "telegram":
        if not ct or ct.get("platform") != "telegram":
            raise ValueError("Telegram isporuka radi samo za fanove s Telegrama.")
        res = posting_service.telegram_send(ct["external_user_id"], caption, data, filename)
    elif channel == "premium_api":
        res = posting_service.publish_premium({"id": f"order-{oid}", "persona_id": o["profile_id"], "post_type": "premium", "caption": caption,
                                               "price": o.get("price"), "tier": "custom", "hashtags": ""}, data=data, filename=filename)
        res["recipient"] = (ct or {}).get("external_user_id")
    elif channel == "local":
        folder = data_dir() / "exports" / "orders"
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"narudzba_{oid}_{Path(filename).name}"
        dest.write_bytes(data)
        res = {"ok": True, "path": str(dest)}
    else:
        raise ValueError("Kanal isporuke je telegram, premium_api ili local.")
    _set_order(oid, status="delivered", channel=channel, delivery=res, delivered_at=now())
    return get_order(oid)


def mark_order_paid(oid: int, amount=None) -> dict:
    o = get_order(oid)
    if not o:
        raise KeyError("Narudžba ne postoji.")
    if o["status"] == "paid":
        return o
    amt = clamp_float(amount if amount not in (None, "") else o.get("price"), 0, 100000, 0)
    ct = get_contact(o["contact_id"]) if o.get("contact_id") else None
    record_purchase(contact_id=o.get("contact_id"), profile_id=o.get("profile_id"), kind="custom", amount=amt, currency=o.get("currency") or "EUR",
                    channel=o.get("channel") or (ct or {}).get("platform") or "", content_type="premium", order_id=oid)
    _set_order(oid, status="paid", paid_at=now(), price=amt)
    return get_order(oid)


# ---------- kupnje, pretplate, analitika ----------

def record_purchase(*, contact_id=None, profile_id=None, kind: str = "custom", amount=0, currency: str = "EUR", channel: str = "",
                    content_type: str = "", template_id=None, order_id=None, note: str = "") -> dict:
    kind = kind if kind in {"subscription", "custom", "ppv", "tip"} else "custom"
    amt = clamp_float(amount, 0, 1_000_000, 0)
    with conn() as c:
        c.execute("""INSERT INTO crm_purchases(contact_id, profile_id, kind, amount, currency, channel, content_type, template_id, order_id, note, created_at)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                  (contact_id, profile_id, kind, amt, (currency or "EUR")[:8], channel or "", content_type or ("premium" if kind != "tip" else ""), template_id, order_id, note[:500], now()))
        pid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        if contact_id:
            c.execute("UPDATE crm_contacts SET total_spent=total_spent+? WHERE id=?", (amt, int(contact_id)))
            if kind == "subscription":
                c.execute("UPDATE crm_contacts SET tier=CASE WHEN tier='vip' THEN 'vip' ELSE 'subscriber' END, interest='subscriber' WHERE id=?", (int(contact_id),))
    return {"id": pid, "amount": amt, "kind": kind}


def analytics(profile_id=None) -> dict:
    f, args = ("WHERE profile_id=?", [int(profile_id)]) if profile_id not in (None, "") else ("", [])
    with conn() as c:
        contacts = c.execute(f"SELECT COUNT(*) FROM crm_contacts {f}", args).fetchone()[0]
        interested = c.execute(f"SELECT COUNT(*) FROM crm_contacts {f + (' AND' if f else 'WHERE')} interest IN ('medium','high','custom_request')", args).fetchone()[0]
        subs = c.execute(f"SELECT COUNT(*) FROM crm_contacts {f + (' AND' if f else 'WHERE')} tier IN ('subscriber','vip')", args).fetchone()[0]
        buyers = c.execute(f"SELECT COUNT(DISTINCT contact_id) FROM crm_purchases {f + (' AND' if f else 'WHERE')} contact_id IS NOT NULL", args).fetchone()[0]
        revenue = c.execute(f"SELECT COALESCE(SUM(amount),0) FROM crm_purchases {f}", args).fetchone()[0]
        by_channel = [row_dict(r) for r in c.execute(f"SELECT channel, COUNT(*) AS n, COALESCE(SUM(amount),0) AS revenue FROM crm_purchases {f} GROUP BY channel ORDER BY revenue DESC", args).fetchall()]
        by_kind = [row_dict(r) for r in c.execute(f"SELECT kind, COUNT(*) AS n, COALESCE(SUM(amount),0) AS revenue FROM crm_purchases {f} GROUP BY kind ORDER BY revenue DESC", args).fetchall()]
        by_type = [row_dict(r) for r in c.execute(f"SELECT content_type, COUNT(*) AS n, COALESCE(SUM(amount),0) AS revenue FROM crm_purchases {f} GROUP BY content_type ORDER BY revenue DESC", args).fetchall()]
        pf = "WHERE p.profile_id=?" if args else ""
        top_tpl = [row_dict(r) for r in c.execute(
            f"""SELECT t.id, t.name, t.tier, t.uses, COUNT(p.id) AS sales, COALESCE(SUM(p.amount),0) AS revenue
                FROM content_templates t LEFT JOIN crm_purchases p ON p.template_id=t.id {pf.replace('WHERE', 'AND') if pf else ''}
                GROUP BY t.id ORDER BY revenue DESC, t.uses DESC LIMIT 5""", args).fetchall()]
        posts = [row_dict(r) for r in c.execute("SELECT post_type, status, COUNT(*) AS n FROM scheduled_posts GROUP BY post_type, status").fetchall()] if _has_table(c, "scheduled_posts") else []
        orders_open = c.execute("SELECT COUNT(*) FROM crm_orders WHERE status IN ('pending','generating','ready')").fetchone()[0]
        unread = c.execute(f"SELECT COUNT(*) FROM crm_contacts {f + (' AND' if f else 'WHERE')} unread=1", args).fetchone()[0]
    conv = round(100.0 * buyers / contacts, 1) if contacts else 0.0
    return {"ok": True, "total_contacts": contacts, "interested_leads": interested, "active_subscribers": subs, "buyers": buyers,
            "conversion_rate": conv, "total_revenue": round(float(revenue), 2), "by_channel": by_channel, "by_kind": by_kind,
            "by_content_type": by_type, "top_templates": top_tpl, "posts": posts, "open_orders": orders_open, "unread": unread}


def _has_table(c, name: str) -> bool:
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


# ---------- webhook i Meta sinkronizacija ----------

def handle_webhook(payload: dict, headers: dict | None = None) -> dict:
    secret = env("CRM_WEBHOOK_SECRET")
    if secret:
        got = ""
        for k, v in (headers or {}).items():
            if k.lower() in {"x-studio-secret", "x-webhook-secret"}:
                got = v
        if got != secret:
            raise PermissionError("Neispravan webhook tajni ključ.")
    event = str(payload.get("event") or payload.get("type") or "message").lower()
    pid = payload.get("profile_id") or payload.get("persona_id")
    if not pid and payload.get("persona"):
        pid = next((p["id"] for p in inbox.list_profiles() if p["name"].lower() == str(payload["persona"]).lower()), None)
    pid = int(pid) if pid else (inbox.active_profile_id() or 0)
    platform = str(payload.get("platform") or "premium")[:30]
    if platform not in PLATFORMS:
        platform = "premium"
    user = str(payload.get("user_id") or payload.get("fan_id") or payload.get("external_user_id") or "").strip()
    name = str(payload.get("name") or payload.get("display_name") or user)[:80]
    if not user:
        raise ValueError("Nedostaje user_id fana.")
    if event in {"message", "comment", "dm"}:
        text = str(payload.get("text") or payload.get("message") or "").strip()
        res = inbox.handle_incoming(pid, platform, user, text, display_name=name, external_id=str(payload.get("message_id") or ""))
        return {"ok": True, "event": "message", **{k: res.get(k) for k in ("thread_id", "draft_id", "auto_sent", "duplicate")}}
    if event in {"purchase", "subscription", "subscribe", "tip", "ppv"}:
        ct = get_or_create_contact(pid, platform, user, display_name=name)
        kind = "subscription" if event in {"subscription", "subscribe"} else (event if event in {"tip", "ppv"} else str(payload.get("kind") or "custom"))
        rec = record_purchase(contact_id=ct["id"], profile_id=pid, kind=kind, amount=payload.get("amount") or 0, currency=str(payload.get("currency") or "EUR"),
                              channel=platform, content_type=str(payload.get("content_type") or "premium"), template_id=payload.get("template_id"))
        return {"ok": True, "event": event, "purchase": rec, "contact_id": ct["id"]}
    raise ValueError("Nepoznat događaj (message, purchase, subscription, tip).")


def sync_meta(profile_id=None, *, max_posts: int = 5) -> dict:
    token = env("META_ACCESS_TOKEN") or env("IG_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("Za sinkronizaciju upiši META_ACCESS_TOKEN u Postavkama.")
    pid = int(profile_id or inbox.mapped_profile_id("instagram") or inbox.active_profile_id() or 0)
    v = env("GRAPH_API_VERSION") or inbox.GRAPH_VERSION
    new = 0
    errors = []
    ig, page = env("META_IG_USER_ID"), env("META_FB_PAGE_ID")
    jobs = []
    if ig:
        jobs.append(("instagram_comment", f"https://graph.facebook.com/{v}/{ig}/media",
                     {"fields": "id,caption,comments.limit(25){id,text,username,from,timestamp}", "limit": max_posts}, ig))
    if page:
        jobs.append(("facebook_comment", f"https://graph.facebook.com/{v}/{page}/posts",
                     {"fields": "id,message,comments.limit(25){id,message,from,created_time}", "limit": max_posts}, page))
    for platform, url, params, own in jobs:
        try:
            r = _http("GET", url, params={**params, "access_token": token}, timeout=30)
        except HttpError as exc:
            errors.append(redact(str(exc), token))
            continue
        for media in ((r or {}).get("json") or {}).get("data") or []:
            for cm in ((media.get("comments") or {}).get("data") or []):
                frm = cm.get("from") or {}
                if str(frm.get("id") or "") == own:
                    continue
                text = cm.get("text") or cm.get("message") or ""
                user = cm.get("username") or frm.get("username") or frm.get("name") or frm.get("id") or "fan"
                if not text.strip():
                    continue
                try:
                    res = inbox.handle_incoming(pid, platform, str(user), text, display_name=str(user), external_id=str(cm.get("id") or ""))
                    if not res.get("duplicate"):
                        new += 1
                except Exception as exc:
                    errors.append(str(exc)[:200])
    return {"ok": not errors or bool(new), "new": new, "errors": errors[:5]}


def latest_inbound_external_id(platform: str, external_user_id: str) -> str:
    with conn() as c:
        row = c.execute(
            """SELECT m.external_id FROM messages m JOIN threads t ON t.id=m.thread_id
               WHERE t.platform=? AND t.external_user_id=? AND m.direction='in' AND m.external_id<>'' ORDER BY m.id DESC LIMIT 1""",
            (platform, str(external_user_id)),
        ).fetchone()
    return row[0] if row else ""


def dashboard() -> dict:
    a = analytics()
    return {k: a[k] for k in ("total_contacts", "interested_leads", "active_subscribers", "total_revenue", "conversion_rate", "open_orders", "unread")}
