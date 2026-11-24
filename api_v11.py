# -*- coding: utf-8 -*-
"""HTTP rute za 1.1.0 (hardver, generiranje, red čekanja, galerija, kalendar, CRM, .env postavke).

studio.py zove handle() prije svojih ruta; postojeći /api/* endpointi ostaju netaknuti.
"""

from __future__ import annotations

import base64
import mimetypes
import re
import time
from pathlib import Path

import inbox
from services import crm_service, generation_service, hardware_service, posting_service
from services.common import env, mask, write_env_values

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
STATIC_TYPES = {".js": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}

# Ključevi koje Postavke smiju upisati u data/.env (vrijednosti se nikad ne vraćaju, samo maskirano).
ENV_KEYS = [
    ("META_ACCESS_TOKEN", "Meta (Instagram/Facebook) access token", True),
    ("META_IG_USER_ID", "Instagram Business user ID", False),
    ("META_FB_PAGE_ID", "Facebook Page ID", False),
    ("PUBLIC_MEDIA_BASE_URL", "Javni URL Studija (tunel) za Instagram slike", False),
    ("GRAPH_API_VERSION", "Graph API verzija (npr. v22.0)", False),
    ("TELEGRAM_BOT_TOKEN", "Telegram bot token", True),
    ("TELEGRAM_CHAT_ID", "Telegram kanal/chat ID za objave", False),
    ("PREMIUM_API_URL", "Premium platforma: API URL za objave", False),
    ("PREMIUM_API_KEY", "Premium platforma: API ključ", True),
    ("PREMIUM_AUTH_HEADER", "Premium: ime auth headera (zadano Authorization)", False),
    ("PREMIUM_SEND_MODE", "Premium: json ili multipart", False),
    ("PREMIUM_MESSAGE_URL", "Premium: URL za odgovore fanovima", False),
    ("CRM_WEBHOOK_SECRET", "Tajna za /api/crm/webhook (header X-Studio-Secret)", True),
    ("XAI_API_KEY", "xAI Grok API ključ", True),
    ("XAI_MODEL", "xAI model", False),
    ("OLLAMA_BASE_URL", "Ollama URL (zadano http://127.0.0.1:11434)", False),
    ("OLLAMA_MODEL", "Ollama model (npr. llama3.1:8b)", False),
    ("OPENAI_COMPAT_BASE_URL", "OpenAI-kompatibilan URL (LM Studio: http://127.0.0.1:1234/v1)", False),
    ("OPENAI_COMPAT_API_KEY", "OpenAI-kompatibilan API ključ", True),
    ("OPENAI_COMPAT_MODEL", "OpenAI-kompatibilan model", False),
    ("IG_VERIFY_TOKEN", "Instagram webhook verify token", True),
    ("IG_APP_SECRET", "Instagram app secret", True),
    ("IG_ACCESS_TOKEN", "Instagram Messaging token (DM)", True),
]
ENV_KEY_SET = {k for k, _l, _s in ENV_KEYS}


def env_public() -> dict:
    items = []
    for key, label, is_secret in ENV_KEYS:
        val = env(key)
        items.append({"key": key, "label": label, "secret": is_secret, "set": bool(val), "masked": mask(val) if is_secret else val})
    return {"ok": True, "items": items, "path": str(inbox.ENV_PATH)}


def _int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _q(query: dict, key: str, default: str = "") -> str:
    return (query.get(key) or [default])[0]


def gpu_live_payload(ctx: dict) -> dict:
    """1.3.0: kompaktna živa GPU traka (opterećenje, temperatura, VRAM, trenutni posao). Brzo: keš ~2,5 s."""
    stats = None
    try:
        ok, _msg = ctx["comfy_up"]()
        stats = ctx["system_stats"]() if ok else None
    except Exception:
        stats = None
    live = hardware_service.gpu_live(system_stats=stats)
    temp_status, temp_msg = "unavailable", ""
    activity = {"generating": False, "training": False, "label": "", "step": None, "total": None, "progress": None}
    try:
        from services import lora_trainer_service as lt
        temp_status, temp_msg = lt.classify_temp(live.get("temp_c"))
        job = lt.active_job()
        if job:
            activity.update({"training": True, "label": job.get("status_label") or "Treniranje…",
                             "step": job.get("current_step"), "total": job.get("total_steps"),
                             "progress": (float(job.get("progress_pct") or 0) / 100.0)})
    except Exception:
        pass
    if not activity["training"]:
        try:
            q = generation_service.list_queue(limit=3, include_finished=False)
            run = next((j for j in q["jobs"] if j.get("status") == "running"), None)
            if run:
                activity.update({"generating": True, "label": run.get("label") or "Generiranje…", "progress": float(run.get("progress") or 0)})
        except Exception:
            pass
    return {**live, "temp_status": temp_status, "temp_message": temp_msg, "activity": activity}


def overview(handler_ctx: dict) -> dict:
    comfy_ok, comfy_msg = handler_ctx["comfy_up"]()
    stats = handler_ctx["system_stats"]() if comfy_ok else {}
    hw = hardware_service.public_state(stats)
    q = generation_service.list_queue(limit=5)
    crm = crm_service.dashboard()
    prof = hw.get("profile") or {}
    return {
        "ok": True,
        "comfy": {"ok": comfy_ok, "message": comfy_msg},
        "hardware": {"name": prof.get("name"), "vram_gb": prof.get("vram_gb"), "is_rx6600": prof.get("is_rx6600"),
                     "backend": hw.get("effective_backend"), "vram": hw.get("vram"), "safe_mode": hw["settings"]["hw_safe_mode"] == "1",
                     "vae_mode": hw["settings"]["hw_vae_mode"], "cudnn_off": hw.get("disable_cudnn")},
        "queue": q["counts"],
        "queue_jobs": q["jobs"][:5],
        "posts_today": posting_service.posts_today(),
        "upcoming_posts": posting_service.list_posts()["upcoming"][:5],
        "crm": crm,
        "send_mode": crm_service.send_mode_state()["global"],
        "llm": crm_service.llm_status()["active"],
        "profiles": len(inbox.list_profiles()),
        "gallery_total": generation_service.list_gallery(limit=1)["total"],
        **dashboard_series(),
    }


def dashboard_series(days: int = 14) -> dict:
    """1.3.0: nizovi za Početnu (prihod i slike po danu, ocjene, zakazane objave, osobe s LoRA-om). Nikad ne baca."""
    from services.common import conn
    import datetime as _dt
    today = _dt.date.today()
    start = _dt.datetime.combine(today - _dt.timedelta(days=days - 1), _dt.time()).timestamp()
    labels = [(today - _dt.timedelta(days=days - 1 - i)).isoformat() for i in range(days)]

    def series(sql: str) -> list:
        vals = [0.0] * days
        try:
            with conn() as c:
                for ts, val in c.execute(sql, (start,)).fetchall():
                    i = (_dt.date.fromtimestamp(float(ts)) - (today - _dt.timedelta(days=days - 1))).days
                    if 0 <= i < days:
                        vals[i] += float(val or 0)
        except Exception:
            pass
        return [round(v, 2) for v in vals]

    out = {
        "series_days": labels,
        "revenue_series": series("SELECT created_at, amount FROM crm_purchases WHERE created_at>=?"),
        "images_series": series("SELECT created_at, 1 FROM gallery_items WHERE created_at>=?"),
        "rated_good": 0, "rated_bad": 0, "scheduled_posts": 0, "personas_with_lora": 0,
    }
    try:
        with conn() as c:
            for r, n in c.execute("SELECT rating, COUNT(*) FROM gallery_items GROUP BY rating").fetchall():
                if int(r or 0) == 1:
                    out["rated_good"] = int(n)
                elif int(r or 0) == -1:
                    out["rated_bad"] = int(n)
            out["scheduled_posts"] = int(c.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status='scheduled'").fetchone()[0])
            out["personas_with_lora"] = int(c.execute("SELECT COUNT(*) FROM profiles WHERE COALESCE(preferred_lora,'')<>''").fetchone()[0])
    except Exception:
        pass
    return out


def gen_options(ctx: dict) -> dict:
    info = ctx["object_info"]() or {}
    import image_gen
    import character
    opts = generation_service.ui_options()
    opts.update({
        "ok": True,
        "templates": generation_service.list_templates(),
        "nodes": {
            "freeu_v2": (not info) or ("FreeU_V2" in info),
            "vae_tiled": (not info) or ("VAEDecodeTiled" in info),
            "instantid": image_gen.instantid_available(info),
            "ipadapter": character.ipadapter_nodes_ok(info),
            "face_detailer": character.face_detailer_nodes_ok(info),
            "catalog": bool(info),
        },
        "pil": generation_service.pil_available(),
    })
    return opts


def handle(h, method: str, path: str, query: dict, body: dict | None, ctx: dict) -> bool:
    """Vrati True ako je ruta obrađena. h = StudioHandler (ima _json i _send)."""
    try:
        return _route(h, method, path, query, body or {}, ctx)
    except KeyError as exc:
        h._json(404, {"ok": False, "error": str(exc).strip("'\"")})
    except PermissionError as exc:
        h._json(403, {"ok": False, "error": str(exc)})
    except ValueError as exc:
        h._json(400, {"ok": False, "error": str(exc)})
    except RuntimeError as exc:
        h._json(400, {"ok": False, "error": str(exc)})
    return True


def _route(h, method: str, path: str, query: dict, body: dict, ctx: dict) -> bool:
    J = h._json
    if method == "GET" and path.startswith("/static/"):
        name = path[len("/static/"):]
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", name) or Path(name).suffix not in STATIC_TYPES:
            h._send(404, b"", "text/plain")
            return True
        f = STATIC_DIR / name
        if not f.is_file():
            h._send(404, b"", "text/plain")
            return True
        h._send(200, f.read_bytes(), STATIC_TYPES[f.suffix], {"Cache-Control": "no-cache"})
        return True

    m = re.fullmatch(r"/public/media/(\d+)/([A-Za-z0-9_\-]+)", path)
    if method == "GET" and m:
        got = posting_service.media_for_public(int(m.group(1)), m.group(2))
        if not got:
            h._send(404, b"", "text/plain")
            return True
        data, name = got
        h._send(200, data, mimetypes.guess_type(name)[0] or "image/png", {"Cache-Control": "public, max-age=600"})
        return True

    if not path.startswith("/api/"):
        return False

    # ---------- pregled ----------
    if method == "GET" and path == "/api/v11/overview":
        J(200, overview(ctx))
        return True

    # ---------- hardver ----------
    if path == "/api/hardware":
        if method == "GET":
            stats = ctx["system_stats"]() if ctx["comfy_up"]()[0] else {}
            J(200, hardware_service.public_state(stats))
            return True
        if method == "POST":
            hardware_service.save_settings(body)
            J(200, {**hardware_service.public_state(), "saved": True})
            return True
    if method == "POST" and path == "/api/hardware/detect":
        stats = ctx["system_stats"]() if ctx["comfy_up"]()[0] else {}
        hardware_service.hardware_profile(system_stats=stats or None, refresh=True)
        J(200, hardware_service.public_state(stats))
        return True
    if method == "POST" and path == "/api/hardware/recommend":
        hardware_service.apply_recommendation()
        res = hardware_service.public_state()
        if body.get("restart"):
            res["restart"] = hardware_service.restart_comfy()
        J(200, {**res, "saved": True})
        return True
    if method == "GET" and path == "/api/gpu-live":
        J(200, gpu_live_payload(ctx))
        return True
    if path == "/api/hardware/restart":
        J(200, {"ok": True, "restart": hardware_service.restart_comfy() if method == "POST" else hardware_service.restart_status()})
        return True

    # ---------- generiranje: opcije, predlošci ----------
    if method == "GET" and path == "/api/gen/options":
        J(200, gen_options(ctx))
        return True
    if path == "/api/templates":
        if method == "GET":
            J(200, {"ok": True, "templates": generation_service.list_templates(_q(query, "tier"))})
            return True
        if method == "POST":
            J(200, {"ok": True, "template": generation_service.create_template(body)})
            return True
    m = re.fullmatch(r"/api/templates/(\d+)(/duplicate)?", path)
    if m:
        tid = int(m.group(1))
        if method == "POST" and m.group(2):
            J(200, {"ok": True, "template": generation_service.duplicate_template(tid)})
            return True
        if method == "GET":
            t = generation_service.get_template(tid)
            if not t:
                raise KeyError("Predložak ne postoji.")
            J(200, {"ok": True, "template": t})
            return True
        if method in {"PUT", "POST"}:
            J(200, {"ok": True, "template": generation_service.update_template(tid, body)})
            return True
        if method == "DELETE":
            generation_service.delete_template(tid)
            J(200, {"ok": True})
            return True

    # ---------- red čekanja ----------
    if path == "/api/queue":
        if method == "GET":
            J(200, generation_service.list_queue(limit=_int(_q(query, "limit", "80"), 80)))
            return True
        if method == "POST":
            gen_body = body.get("body") if isinstance(body.get("body"), dict) else {k: v for k, v in body.items() if k not in {"count", "seed_mode", "template_ids"}}
            jobs = generation_service.enqueue_batch(gen_body, count=_int(body.get("count"), 1) or 1, seed_mode=str(body.get("seed_mode") or "random"),
                                                    template_ids=body.get("template_ids") or None)
            J(200, {"ok": True, "jobs": jobs, "queue": generation_service.list_queue(limit=20)})
            return True
    if method == "POST" and path == "/api/queue/clear":
        J(200, {"ok": True, "removed": generation_service.clear_finished()})
        return True
    m = re.fullmatch(r"/api/queue/(\d+)/(cancel|retry)", path)
    if method == "POST" and m:
        fn = generation_service.cancel_job if m.group(2) == "cancel" else generation_service.retry_job
        J(200, {"ok": True, "job": fn(int(m.group(1)))})
        return True
    if method == "POST" and path == "/api/character-sheet":
        pid = _int(body.get("persona_id") or body.get("profile_id"))
        if not pid:
            raise ValueError("Odaberi osobu.")
        extra = {k: v for k, v in body.items() if k not in {"persona_id", "profile_id"}}
        J(200, generation_service.queue_character_sheet(pid, extra))
        return True

    # ---------- galerija, ocjene, dataset ----------
    if method == "GET" and path == "/api/gallery":
        J(200, generation_service.list_gallery(persona_id=_q(query, "persona_id") or None, rating=_q(query, "rating") or None,
                                               offset=_int(_q(query, "offset", "0"), 0), limit=_int(_q(query, "limit", "24"), 24),
                                               source=_q(query, "source")))
        return True
    m = re.fullmatch(r"/api/gallery/file/(\d+)", path)
    if method == "GET" and m:
        item = generation_service.gallery_item(int(m.group(1)))
        p = generation_service.local_file_for(item) if item else None
        if not item or not p:
            h._send(404, b"", "text/plain")
            return True
        dl = _q(query, "download") in {"1", "true"}
        h._send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "image/png",
                {"Content-Disposition": f'{"attachment" if dl else "inline"}; filename="{p.name}"', "Cache-Control": "private, max-age=3600"})
        return True
    m = re.fullmatch(r"/api/gallery/(\d+)", path)
    if method == "DELETE" and m:
        generation_service.delete_gallery_item(int(m.group(1)))
        J(200, {"ok": True})
        return True
    if method == "POST" and path == "/api/gallery/rate":
        item = generation_service.rate_image(gallery_id=_int(body.get("gallery_id")), filename=str(body.get("filename") or ""),
                                             subfolder=str(body.get("subfolder") or ""), type_=str(body.get("type") or "output"),
                                             rating=_int(body.get("rating"), 0), persona_id=_int(body.get("persona_id")),
                                             prompt=str(body.get("prompt") or ""), seed=body.get("seed") or "", model=str(body.get("model") or ""))
        J(200, {"ok": True, "item": item, "lora_sync": (item or {}).get("lora_sync")})
        return True
    if method == "POST" and path == "/api/lora-dataset/export":
        pid = _int(body.get("persona_id"))
        if not pid:
            raise ValueError("Odaberi osobu.")
        J(200, generation_service.export_lora_dataset(pid, trigger=str(body.get("trigger") or ""), repeats=_int(body.get("repeats"), 10) or 10))
        return True
    m = re.fullmatch(r"/api/profiles/(\d+)/extras", path)
    if m and method in {"POST", "PUT"}:
        pid = int(m.group(1))
        if not inbox.get_profile(pid):
            raise KeyError("Profil ne postoji.")
        generation_service.save_profile_extras(pid, body)
        J(200, {"ok": True, "profile": inbox.get_profile(pid)})
        return True

    # ---------- kalendar i objave ----------
    if path == "/api/posts":
        if method == "GET":
            J(200, posting_service.list_posts(month=_q(query, "month"), status=_q(query, "status")))
            return True
        if method == "POST":
            post = posting_service.create_post(body)
            if body.get("upload_base64"):
                post = posting_service.attach_upload(post["id"], base64.b64decode(str(body["upload_base64"]).split(",")[-1]), str(body.get("upload_ext") or "png"))
            if body.get("publish_now"):
                post = posting_service.publish_post(post["id"])
            J(200, {"ok": True, "post": post})
            return True
    m = re.fullmatch(r"/api/posts/(\d+)(?:/(publish|upload|media))?", path)
    if m:
        pid, action = int(m.group(1)), m.group(2)
        if action == "media" and method == "GET":
            post = posting_service._raw_post(pid)
            if not post:
                raise KeyError("Objava ne postoji.")
            data, name = posting_service.media_bytes(post)
            h._send(200, data, mimetypes.guess_type(name)[0] or "image/png", {"Cache-Control": "private, max-age=600"})
            return True
        if action == "publish" and method == "POST":
            J(200, {"ok": True, "post": posting_service.publish_post(pid)})
            return True
        if action == "upload" and method == "POST":
            data = base64.b64decode(str(body.get("data") or "").split(",")[-1])
            J(200, {"ok": True, "post": posting_service.attach_upload(pid, data, str(body.get("ext") or "png"))})
            return True
        if not action and method == "GET":
            p = posting_service.get_post(pid)
            if not p:
                raise KeyError("Objava ne postoji.")
            J(200, {"ok": True, "post": p})
            return True
        if not action and method in {"PUT", "POST"}:
            post = posting_service.update_post(pid, body)
            if body.get("upload_base64"):
                post = posting_service.attach_upload(pid, base64.b64decode(str(body["upload_base64"]).split(",")[-1]), str(body.get("upload_ext") or "png"))
            J(200, {"ok": True, "post": post})
            return True
        if not action and method == "DELETE":
            posting_service.delete_post(pid)
            J(200, {"ok": True})
            return True

    # ---------- CRM ----------
    if method == "POST" and path == "/api/crm/webhook":
        J(200, crm_service.handle_webhook(body, dict(h.headers.items()) if getattr(h, "headers", None) else {}))
        return True
    if method == "POST" and path == "/api/crm/simulate":
        text = str(body.get("text") or "").strip()
        if not text:
            raise ValueError("Upiši poruku fana.")
        pid = _int(body.get("profile_id")) or inbox.active_profile_id()
        if not pid:
            raise ValueError("Nema aktivnog influencera.")
        fan = (str(body.get("fan_name") or "Fan").strip() or "Fan")[:60]
        uid = "sim-" + re.sub(r"[^a-z0-9]+", "-", fan.lower())[:40]
        J(200, inbox.handle_incoming(pid, "simulate", uid, text, display_name=fan))
        return True
    if method == "GET" and path == "/api/crm/contacts":
        J(200, {"ok": True, "contacts": crm_service.list_contacts(tier=_q(query, "tier"), profile_id=_q(query, "profile_id") or None,
                                                                   interest=_q(query, "interest"), q=_q(query, "q"))})
        return True
    m = re.fullmatch(r"/api/crm/contacts/(\d+)", path)
    if m:
        cid = int(m.group(1))
        if method == "GET":
            J(200, {"ok": True, "contact": crm_service.contact_detail(cid)})
            return True
        if method in {"POST", "PUT"}:
            J(200, {"ok": True, "contact": crm_service.update_contact(cid, body)})
            return True
    m = re.fullmatch(r"/api/crm/threads/(\d+)/contact", path)
    if method == "GET" and m:
        ct = crm_service.contact_for_thread(int(m.group(1)))
        J(200, {"ok": True, "contact": crm_service.contact_detail(ct["id"]) if ct else None})
        return True
    if path == "/api/crm/orders":
        if method == "GET":
            J(200, {"ok": True, "orders": crm_service.list_orders(status=_q(query, "status")), "labels": crm_service.ORDER_LABELS})
            return True
        if method == "POST":
            o = crm_service.create_order(contact_id=_int(body.get("contact_id")), profile_id=_int(body.get("profile_id")),
                                         description=str(body.get("description") or ""), price=body.get("price"),
                                         source_message_id=_int(body.get("message_id")), thread_id=_int(body.get("thread_id")))
            if body.get("generate"):
                o = crm_service.generate_order(o["id"])
            J(200, {"ok": True, "order": o})
            return True
    m = re.fullmatch(r"/api/crm/orders/(\d+)(?:/(generate|deliver|paid))?", path)
    if m and method in {"POST", "PUT"}:
        oid, action = int(m.group(1)), m.group(2)
        if action == "generate":
            o = crm_service.generate_order(oid)
        elif action == "deliver":
            o = crm_service.deliver_order(oid, str(body.get("channel") or "auto"), str(body.get("message") or ""))
        elif action == "paid":
            o = crm_service.mark_order_paid(oid, body.get("amount"))
        else:
            o = crm_service.update_order(oid, body)
        J(200, {"ok": True, "order": o})
        return True
    if method == "POST" and path == "/api/crm/purchases":
        J(200, {"ok": True, "purchase": crm_service.record_purchase(contact_id=_int(body.get("contact_id")), profile_id=_int(body.get("profile_id")),
                                                                   kind=str(body.get("kind") or "custom"), amount=body.get("amount") or 0,
                                                                   currency=str(body.get("currency") or "EUR"), channel=str(body.get("channel") or ""),
                                                                   content_type=str(body.get("content_type") or "premium"), template_id=_int(body.get("template_id")),
                                                                   note=str(body.get("note") or ""))})
        return True
    if method == "GET" and path == "/api/crm/analytics":
        J(200, crm_service.analytics(_q(query, "profile_id") or None))
        return True
    if path == "/api/crm/send-mode":
        if method == "POST":
            J(200, {"ok": True, **crm_service.set_send_mode(str(body.get("scope") or "global"), str(body.get("mode") or ""),
                                                             platform=str(body.get("platform") or ""), profile_id=_int(body.get("profile_id")))})
            return True
        J(200, {"ok": True, **crm_service.send_mode_state()})
        return True
    if path == "/api/crm/llm":
        J(200, {"ok": True, **(crm_service.save_llm_settings(body) if method == "POST" else crm_service.llm_status())})
        return True
    if method == "POST" and path == "/api/crm/sync-meta":
        J(200, crm_service.sync_meta(_int(body.get("profile_id"))))
        return True

    # ---------- data/.env ----------
    if path == "/api/env":
        if method == "GET":
            J(200, env_public())
            return True
        if method == "POST":
            values = body.get("values") or {}
            clear = body.get("clear") or []
            bad = [k for k in list(values) + list(clear) if k not in ENV_KEY_SET]
            if bad:
                raise ValueError("Ovi ključevi se ne mogu mijenjati iz Studija: " + ", ".join(bad))
            upd = {k: str(v).strip() for k, v in values.items() if str(v).strip()}
            upd.update({k: "" for k in clear})
            changed = write_env_values(upd) if upd else []
            J(200, {**env_public(), "changed": changed})
            return True
    return False
