# -*- coding: utf-8 -*-
"""Objavljivanje i kalendar: Instagram/Facebook (Meta Graph API), Telegram (Bot API) i generički
Premium API / webhook za pretplatničku platformu.

Tajne se čitaju iz data/.env (META_ACCESS_TOKEN, META_IG_USER_ID, META_FB_PAGE_ID, PUBLIC_MEDIA_BASE_URL,
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PREMIUM_API_URL, PREMIUM_API_KEY, PREMIUM_AUTH_HEADER, PREMIUM_SEND_MODE).
Scheduler nikad ne ruši Studio: nedostatak postavki se zapiše kao greška posta.
"""

from __future__ import annotations

import base64
import secrets as pysecrets
import threading
import time
from datetime import datetime
from pathlib import Path

import inbox

from . import generation_service
from .common import HttpError, clamp_float, conn, env, http_request, jdump, jload, now, redact, row_dict

CHANNELS = ("instagram", "facebook", "telegram", "premium_api")
CHANNEL_LABELS = {"instagram": "Instagram", "facebook": "Facebook", "telegram": "Telegram", "premium_api": "Premium API"}
POST_TYPES = ("public_teaser", "premium")
STATUSES = ("draft", "scheduled", "publishing", "published", "error")
STATUS_LABELS = {"draft": "Nacrt", "scheduled": "Zakazano", "publishing": "Objavljujem", "published": "Objavljeno", "error": "Greška"}
GRAPH_BASE = "https://graph.facebook.com"
TICK_S = 30

_http = http_request  # zamjenjivo u testovima
_thread: threading.Thread | None = None
_stop = threading.Event()


def set_http(fn) -> None:
    global _http
    _http = fn or http_request


def graph_version() -> str:
    return env("GRAPH_API_VERSION") or inbox.GRAPH_VERSION


# ---------- shema ----------

def ensure_schema() -> None:
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                persona_id INTEGER,
                gallery_id INTEGER,
                media_path TEXT DEFAULT '',
                media_url TEXT DEFAULT '',
                media_token TEXT DEFAULT '',
                channels_json TEXT DEFAULT '[]',
                post_type TEXT DEFAULT 'public_teaser',
                caption TEXT DEFAULT '',
                hashtags TEXT DEFAULT '',
                price REAL,
                tier TEXT DEFAULT '',
                scheduled_at REAL,
                status TEXT DEFAULT 'draft',
                results_json TEXT DEFAULT '{}',
                error TEXT DEFAULT '',
                template_id INTEGER,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                published_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_posts_due ON scheduled_posts(status, scheduled_at);
            """
        )
        c.execute("UPDATE scheduled_posts SET status='scheduled' WHERE status='publishing'")


# ---------- konfiguracija ----------

def channel_status() -> dict:
    return {
        "instagram": {
            "configured": bool(env("META_ACCESS_TOKEN") and env("META_IG_USER_ID")),
            "public_url": bool(env("PUBLIC_MEDIA_BASE_URL")),
            "missing": [k for k in ("META_ACCESS_TOKEN", "META_IG_USER_ID", "PUBLIC_MEDIA_BASE_URL") if not env(k)],
        },
        "facebook": {"configured": bool(env("META_ACCESS_TOKEN") and env("META_FB_PAGE_ID")),
                     "missing": [k for k in ("META_ACCESS_TOKEN", "META_FB_PAGE_ID") if not env(k)]},
        "telegram": {"configured": bool(env("TELEGRAM_BOT_TOKEN") and env("TELEGRAM_CHAT_ID")),
                     "missing": [k for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if not env(k)]},
        "premium_api": {"configured": bool(env("PREMIUM_API_URL")), "missing": [k for k in ("PREMIUM_API_URL",) if not env(k)]},
    }


# ---------- CRUD ----------

def _post_row(row) -> dict:
    d = row_dict(row)
    d["channels"] = jload(d.pop("channels_json", "[]"), []) or []
    d["results"] = jload(d.pop("results_json", "{}"), {}) or {}
    d["status_label"] = STATUS_LABELS.get(d.get("status"), d.get("status"))
    d["post_type_label"] = "Javni teaser" if d.get("post_type") == "public_teaser" else "Premium"
    d.pop("media_token", None)
    if d.get("gallery_id"):
        item = generation_service.gallery_item(d["gallery_id"])
        d["media_preview"] = (item or {}).get("url") or ""
    elif d.get("media_path"):
        d["media_preview"] = f"/api/posts/{d['id']}/media"
    else:
        d["media_preview"] = d.get("media_url") or ""
    if d.get("scheduled_at"):
        d["scheduled_local"] = datetime.fromtimestamp(float(d["scheduled_at"])).strftime("%Y-%m-%dT%H:%M")
    return d


def _parse_when(value) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).timestamp()
        except ValueError:
            continue
    try:
        return float(s)
    except ValueError:
        raise ValueError("Neispravan datum i vrijeme objave.") from None


def _clean(payload: dict, cur: dict | None = None) -> dict:
    cur = cur or {}
    out = {}
    if "persona_id" in payload or not cur:
        try:
            out["persona_id"] = int(payload.get("persona_id")) if payload.get("persona_id") not in (None, "") else None
        except (TypeError, ValueError):
            out["persona_id"] = None
    if "gallery_id" in payload:
        out["gallery_id"] = int(payload["gallery_id"]) if payload.get("gallery_id") not in (None, "") else None
    if "media_url" in payload:
        url = str(payload.get("media_url") or "").strip()
        if url and not url.startswith(("https://", "http://")):
            raise ValueError("Vanjski URL slike mora počinjati s https://")
        out["media_url"] = url[:1000]
    if "channels" in payload or not cur:
        ch = [c for c in (payload.get("channels") or []) if c in CHANNELS]
        out["channels_json"] = jdump(ch)
    if "post_type" in payload or not cur:
        out["post_type"] = payload.get("post_type") if payload.get("post_type") in POST_TYPES else "public_teaser"
    for k, lim in (("caption", 2200), ("hashtags", 600), ("tier", 80)):
        if k in payload:
            out[k] = str(payload.get(k) or "")[:lim]
    if "price" in payload:
        out["price"] = clamp_float(payload.get("price"), 0, 100000, 0) if payload.get("price") not in (None, "") else None
    if "template_id" in payload:
        out["template_id"] = int(payload["template_id"]) if payload.get("template_id") not in (None, "") else None
    if "scheduled_at" in payload:
        out["scheduled_at"] = _parse_when(payload.get("scheduled_at"))
    if "status" in payload:
        st = payload.get("status")
        if st not in {"draft", "scheduled"}:
            raise ValueError("Status može biti samo nacrt ili zakazano.")
        out["status"] = st
    st = out.get("status", cur.get("status", "draft"))
    if st == "scheduled":
        when = out.get("scheduled_at", cur.get("scheduled_at"))
        chans = jload(out.get("channels_json"), None) if "channels_json" in out else cur.get("channels")
        if not when:
            raise ValueError("Za zakazivanje odaberi datum i vrijeme.")
        if not chans:
            raise ValueError("Odaberi barem jedan kanal.")
    return out


def create_post(payload: dict) -> dict:
    data = _clean(payload)
    data.setdefault("status", "draft")
    t = now()
    data["media_token"] = pysecrets.token_urlsafe(18)
    with conn() as c:
        cols = ", ".join(data)
        c.execute(f"INSERT INTO scheduled_posts({cols}, created_at, updated_at) VALUES ({', '.join('?' * len(data))}, ?, ?)", [*data.values(), t, t])
        pid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    return get_post(pid)


def attach_upload(post_id: int, data: bytes, ext: str = "png") -> dict:
    ext = (ext or "png").lower().strip(".")
    if ext not in {"png", "jpg", "jpeg", "webp"}:
        raise ValueError("Podržane su PNG, JPG i WEBP slike.")
    folder = Path(inbox.DATA_DIR) / "uploads" / "posts"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"post_{int(post_id)}_{int(time.time())}.{ext}"
    path.write_bytes(data)
    with conn() as c:
        c.execute("UPDATE scheduled_posts SET media_path=?, gallery_id=NULL, updated_at=? WHERE id=?", (str(path), now(), int(post_id)))
    return get_post(post_id)


def get_post(pid) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM scheduled_posts WHERE id=?", (int(pid),)).fetchone()
    return _post_row(row) if row else None


def _raw_post(pid) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM scheduled_posts WHERE id=?", (int(pid),)).fetchone()
    if not row:
        return None
    d = row_dict(row)
    d["channels"] = jload(d.get("channels_json"), []) or []
    return d


def update_post(pid: int, payload: dict) -> dict:
    cur = get_post(pid)
    if not cur:
        raise KeyError("Objava ne postoji.")
    if cur["status"] in {"published", "publishing"} and payload.get("status") != "draft":
        raise ValueError("Objavljena objava se ne može mijenjati. Dupliciraj je.")
    data = _clean(payload, cur)
    if data:
        with conn() as c:
            c.execute(f"UPDATE scheduled_posts SET {', '.join(k + '=?' for k in data)}, updated_at=? WHERE id=?", [*data.values(), now(), int(pid)])
    return get_post(pid)


def delete_post(pid: int) -> None:
    with conn() as c:
        c.execute("DELETE FROM scheduled_posts WHERE id=?", (int(pid),))


def list_posts(*, month: str = "", status: str = "", limit: int = 300) -> dict:
    where, args = [], []
    if month:
        try:
            start = datetime.strptime(month + "-01", "%Y-%m-%d")
        except ValueError:
            raise ValueError("Mjesec mora biti u obliku GGGG-MM.") from None
        end = datetime(start.year + (start.month == 12), (start.month % 12) + 1, 1)
        where.append("(scheduled_at >= ? AND scheduled_at < ?)")
        args += [start.timestamp(), end.timestamp()]
    if status in STATUSES:
        where.append("status=?")
        args.append(status)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with conn() as c:
        rows = c.execute(f"SELECT * FROM scheduled_posts {clause} ORDER BY COALESCE(scheduled_at, created_at) LIMIT ?", [*args, int(limit)]).fetchall()
        up = c.execute("SELECT * FROM scheduled_posts WHERE status IN ('scheduled','draft','error') ORDER BY COALESCE(scheduled_at, 9e18) LIMIT 30").fetchall()
    return {"ok": True, "posts": [_post_row(r) for r in rows], "upcoming": [_post_row(r) for r in up],
            "channels": channel_status(), "labels": STATUS_LABELS}


def posts_today() -> int:
    d = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    with conn() as c:
        return int(c.execute("SELECT COUNT(*) FROM scheduled_posts WHERE scheduled_at>=? AND scheduled_at<? AND status IN ('scheduled','published')", (d, d + 86400)).fetchone()[0])


# ---------- mediji ----------

def media_bytes(post: dict) -> tuple[bytes, str]:
    if post.get("media_path"):
        p = Path(post["media_path"])
        if not p.is_file():
            raise RuntimeError("Datoteka slike za objavu više ne postoji.")
        return p.read_bytes(), p.name
    if post.get("gallery_id"):
        item = generation_service.gallery_item(post["gallery_id"])
        if not item:
            raise RuntimeError("Slika iz galerije više ne postoji.")
        return generation_service.read_item_bytes(item), item.get("filename") or "slika.png"
    if post.get("media_url"):
        raise RuntimeError("Objava koristi vanjski URL slike; on se šalje izravno, bez preuzimanja.")
    raise RuntimeError("Objava nema sliku.")


def public_media_url(post: dict) -> str:
    """URL koji Meta (Instagram) mora moći preuzeti. Vanjski URL ili PUBLIC_MEDIA_BASE_URL + /public/media/<id>/<token>."""
    if post.get("media_url"):
        return post["media_url"]
    base = env("PUBLIC_MEDIA_BASE_URL").rstrip("/")
    if not base or not (post.get("media_path") or post.get("gallery_id")):
        return ""
    return f"{base}/public/media/{int(post['id'])}/{post.get('media_token') or ''}"


def full_caption(post: dict) -> str:
    cap = (post.get("caption") or "").strip()
    tags = (post.get("hashtags") or "").strip()
    if tags:
        tags = " ".join(t if t.startswith("#") else "#" + t for t in tags.replace(",", " ").split() if t.strip("#"))
    return (cap + ("\n\n" + tags if tags else "")).strip()


# ---------- konektori (payload builderi + slanje) ----------

def instagram_payloads(post: dict) -> dict:
    ig = env("META_IG_USER_ID")
    url = public_media_url(post)
    v = graph_version()
    return {
        "container": {"url": f"{GRAPH_BASE}/{v}/{ig}/media", "form": {"image_url": url, "caption": full_caption(post)}},
        "publish": {"url": f"{GRAPH_BASE}/{v}/{ig}/media_publish", "form": {"creation_id": "<container_id>"}},
    }


def publish_instagram(post: dict) -> dict:
    token, ig = env("META_ACCESS_TOKEN"), env("META_IG_USER_ID")
    if not token or not ig:
        raise RuntimeError("Instagram nije podešen: u Postavkama upiši META_ACCESS_TOKEN i META_IG_USER_ID.")
    if not (post.get("media_url") or post.get("media_path") or post.get("gallery_id")):
        raise RuntimeError("Instagram objava treba sliku: odaberi sliku iz galerije, učitaj datoteku ili zalijepi javni URL slike.")
    if not public_media_url(post):
        raise RuntimeError(
            "Instagram traži javni URL slike. Upiši PUBLIC_MEDIA_BASE_URL (npr. Cloudflare Tunnel ili ngrok adresu koja "
            "pokazuje na Studio) ili u objavi zalijepi vanjski https URL slike."
        )
    p = instagram_payloads(post)
    try:
        r1 = _http("POST", p["container"]["url"], form={**p["container"]["form"], "access_token": token}, timeout=60)
        cid = ((r1 or {}).get("json") or {}).get("id")
        if not cid:
            raise RuntimeError(f"Meta nije vratila ID kontejnera: {(r1 or {}).get('text', '')[:300]}")
        r2 = _http("POST", p["publish"]["url"], form={"creation_id": cid, "access_token": token}, timeout=60)
        mid = ((r2 or {}).get("json") or {}).get("id")
        if not mid:
            raise RuntimeError(f"Meta nije objavila medij: {(r2 or {}).get('text', '')[:300]}")
    except HttpError as exc:
        raise RuntimeError("Instagram: " + redact(str(exc), token)) from None
    return {"ok": True, "container_id": cid, "media_id": mid}


def facebook_payload(post: dict, data: bytes | None, filename: str = "slika.png") -> dict:
    page = env("META_FB_PAGE_ID")
    v = graph_version()
    if data is None and post.get("media_url"):
        return {"url": f"{GRAPH_BASE}/{v}/{page}/photos", "form": {"url": post["media_url"], "caption": full_caption(post)}, "files": None}
    if data is None:
        return {"url": f"{GRAPH_BASE}/{v}/{page}/feed", "form": {"message": full_caption(post)}, "files": None}
    return {"url": f"{GRAPH_BASE}/{v}/{page}/photos", "form": {"caption": full_caption(post)}, "files": {"source": (filename, data, None)}}


def publish_facebook(post: dict) -> dict:
    token, page = env("META_ACCESS_TOKEN"), env("META_FB_PAGE_ID")
    if not token or not page:
        raise RuntimeError("Facebook nije podešen: u Postavkama upiši META_ACCESS_TOKEN (Page token) i META_FB_PAGE_ID.")
    data, name = (None, "")
    if post.get("media_path") or post.get("gallery_id"):
        data, name = media_bytes(post)
    p = facebook_payload(post, data, name or "slika.png")
    try:
        r = _http("POST", p["url"], form={**p["form"], "access_token": token}, files=p["files"], timeout=120)
    except HttpError as exc:
        raise RuntimeError("Facebook: " + redact(str(exc), token)) from None
    j = (r or {}).get("json") or {}
    if not (j.get("id") or j.get("post_id")):
        raise RuntimeError(f"Facebook nije vratio ID objave: {(r or {}).get('text', '')[:300]}")
    return {"ok": True, "id": j.get("post_id") or j.get("id")}


def telegram_payload(chat_id: str, caption: str, data: bytes | None, filename: str = "slika.png", photo_url: str = "") -> dict:
    token = env("TELEGRAM_BOT_TOKEN")
    if data is not None:
        return {"url": f"https://api.telegram.org/bot{token}/sendPhoto", "form": {"chat_id": str(chat_id), "caption": caption[:1024]},
                "files": {"photo": (filename, data, None)}}
    if photo_url:
        return {"url": f"https://api.telegram.org/bot{token}/sendPhoto", "form": {"chat_id": str(chat_id), "photo": photo_url, "caption": caption[:1024]}, "files": None}
    return {"url": f"https://api.telegram.org/bot{token}/sendMessage", "form": {"chat_id": str(chat_id), "text": caption[:4096]}, "files": None}


def telegram_send(chat_id: str, caption: str, data: bytes | None = None, filename: str = "slika.png", photo_url: str = "") -> dict:
    token = env("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Telegram nije podešen: u Postavkama upiši TELEGRAM_BOT_TOKEN.")
    if not chat_id:
        raise RuntimeError("Nedostaje Telegram chat ID (TELEGRAM_CHAT_ID za kanal ili ID fana).")
    p = telegram_payload(chat_id, caption, data, filename, photo_url)
    try:
        r = _http("POST", p["url"], form=p["form"], files=p["files"], timeout=120)
    except HttpError as exc:
        raise RuntimeError("Telegram: " + redact(str(exc), token)) from None
    j = (r or {}).get("json") or {}
    if j.get("ok") is False:
        raise RuntimeError("Telegram: " + str(j.get("description") or "greška"))
    return {"ok": True, "message_id": ((j.get("result") or {}).get("message_id"))}


def publish_telegram(post: dict) -> dict:
    data, name = (None, "")
    if post.get("media_path") or post.get("gallery_id"):
        data, name = media_bytes(post)
    return telegram_send(env("TELEGRAM_CHAT_ID"), full_caption(post), data, name or "slika.png", post.get("media_url") or "")


def premium_payload(post: dict, data: bytes | None, filename: str = "slika.png") -> dict:
    persona = inbox.get_profile(post.get("persona_id")) if post.get("persona_id") else None
    meta = {
        "persona": (persona or {}).get("name") or "",
        "persona_id": post.get("persona_id"),
        "post_type": post.get("post_type") or "public_teaser",
        "caption": full_caption(post),
        "price": post.get("price"),
        "tier": post.get("tier") or "",
        "post_id": post.get("id"),
        "source": "ai-influencer-studio",
    }
    mode = (env("PREMIUM_SEND_MODE") or "json").lower()
    headers = {}
    key = env("PREMIUM_API_KEY")
    if key:
        hdr = env("PREMIUM_AUTH_HEADER") or "Authorization"
        headers[hdr] = ("Bearer " + key) if hdr.lower() == "authorization" and not key.lower().startswith(("bearer ", "basic ")) else key
    if mode == "multipart" and data is not None:
        return {"url": env("PREMIUM_API_URL"), "form": {k: ("" if v is None else v) for k, v in meta.items()}, "files": {"media": (filename, data, None)}, "json": None, "headers": headers}
    body = dict(meta)
    if data is not None:
        body["media_filename"] = filename
        body["media_base64"] = base64.b64encode(data).decode("ascii")
    elif post.get("media_url"):
        body["media_url"] = post["media_url"]
    return {"url": env("PREMIUM_API_URL"), "form": None, "files": None, "json": body, "headers": headers}


def publish_premium(post: dict, *, data: bytes | None = None, filename: str = "") -> dict:
    url = env("PREMIUM_API_URL")
    if not url:
        raise RuntimeError("Premium API nije podešen: u Postavkama upiši PREMIUM_API_URL (i po potrebi PREMIUM_API_KEY).")
    if data is None and (post.get("media_path") or post.get("gallery_id")):
        data, filename = media_bytes(post)
    p = premium_payload(post, data, filename or "slika.png")
    try:
        if p["files"]:
            r = _http("POST", p["url"], form=p["form"], files=p["files"], headers=p["headers"], timeout=120)
        else:
            r = _http("POST", p["url"], json_body=p["json"], headers=p["headers"], timeout=120)
    except HttpError as exc:
        raise RuntimeError("Premium API: " + redact(str(exc), env("PREMIUM_API_KEY"))) from None
    return {"ok": True, "status": (r or {}).get("status"), "response": ((r or {}).get("json") or (r or {}).get("text") or "")}


PUBLISHERS = {"instagram": publish_instagram, "facebook": publish_facebook, "telegram": publish_telegram, "premium_api": publish_premium}


def publish_post(pid: int) -> dict:
    post = _raw_post(pid)
    if not post:
        raise KeyError("Objava ne postoji.")
    channels = post.get("channels") or []
    if not channels:
        raise ValueError("Objava nema odabran kanal.")
    with conn() as c:
        c.execute("UPDATE scheduled_posts SET status='publishing', updated_at=? WHERE id=?", (now(), int(pid)))
    results = dict(jload(post.get("results_json"), {}) or {})
    errors = []
    for ch in channels:
        if (results.get(ch) or {}).get("ok"):
            continue  # već objavljeno na tom kanalu (ponovni pokušaj nakon djelomične greške)
        fn = PUBLISHERS.get(ch)
        try:
            results[ch] = fn(post) if fn else {"ok": False, "error": "Nepoznat kanal."}
        except Exception as exc:
            results[ch] = {"ok": False, "error": str(exc)[:800]}
            errors.append(f"{CHANNEL_LABELS.get(ch, ch)}: {exc}")
    status = "published" if not errors else "error"
    with conn() as c:
        c.execute(
            "UPDATE scheduled_posts SET status=?, results_json=?, error=?, updated_at=?, published_at=? WHERE id=?",
            (status, jdump(results), " | ".join(errors)[:2000], now(), now() if status == "published" else None, int(pid)),
        )
    return get_post(pid)


def run_due(now_ts: float | None = None) -> list[dict]:
    t = now_ts if now_ts is not None else now()
    with conn() as c:
        ids = [r[0] for r in c.execute("SELECT id FROM scheduled_posts WHERE status='scheduled' AND scheduled_at IS NOT NULL AND scheduled_at<=? ORDER BY scheduled_at", (t,)).fetchall()]
    out = []
    for pid in ids:
        try:
            out.append(publish_post(pid))
        except Exception as exc:
            with conn() as c:
                c.execute("UPDATE scheduled_posts SET status='error', error=? WHERE id=?", (str(exc)[:800], pid))
    return out


def _loop() -> None:
    while not _stop.is_set():
        try:
            run_due()
        except Exception:
            pass
        _stop.wait(TICK_S)


def start_scheduler() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="post-scheduler", daemon=True)
    _thread.start()


def stop_scheduler() -> None:
    _stop.set()


def media_for_public(post_id: int, token: str) -> tuple[bytes, str] | None:
    post = _raw_post(post_id)
    if not post or not token or not pysecrets.compare_digest(str(post.get("media_token") or ""), str(token)):
        return None
    try:
        return media_bytes(post)
    except Exception:
        return None
