# -*- coding: utf-8 -*-
"""HTTP rute LoRA trenera (/api/lora-trainer/*). studio.py ih zove prije api_v11.

Slike se šalju kao JSON s base64 / data-URL (kao reference osoba) ili kao multipart/form-data.
"""

from __future__ import annotations

import base64
import mimetypes
import re
from email.parser import BytesParser
from email.policy import default as email_policy

from services import lora_trainer_service as lt

PREFIX = "/api/lora-trainer/"


def _int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _q(query: dict, key: str, default: str = "") -> str:
    return (query.get(key) or [default])[0]


def decode_image_entries(body: dict) -> list[tuple[bytes, str]]:
    """{images: [{name, data}]} ili {data, name}; data može biti data-URL ili čisti base64."""
    raw = body.get("images")
    entries = raw if isinstance(raw, list) else [body]
    out = []
    for i, e in enumerate(entries):
        if isinstance(e, str):
            e = {"data": e}
        if not isinstance(e, dict):
            raise ValueError("Neispravan zapis slike.")
        data = e.get("data") or e.get("image") or e.get("image_b64") or ""
        name = str(e.get("name") or f"slika_{i + 1}.jpg")[:120]
        if isinstance(data, str) and data.startswith("data:"):
            data = data.split(",", 1)[-1]
        if not data:
            raise ValueError("Nedostaje slika.")
        try:
            out.append((base64.b64decode(data, validate=False), name))
        except Exception:
            raise ValueError(f"„{name}” nije valjani base64.") from None
    if not out:
        raise ValueError("Nedostaje slika.")
    return out


def parse_multipart(raw: bytes, content_type: str) -> list[tuple[bytes, str]]:
    msg = BytesParser(policy=email_policy).parsebytes(b"Content-Type: " + content_type.encode("latin-1") + b"\r\n\r\n" + raw)
    files = []
    for part in msg.iter_parts():
        fname = part.get_filename()
        if not fname:
            continue
        files.append((part.get_payload(decode=True) or b"", fname))
    if not files:
        raise ValueError("U zahtjevu nema slika.")
    return files


def handle_multipart(h, path: str, raw: bytes, content_type: str) -> None:
    m = re.fullmatch(r"/api/lora-trainer/dataset/(\d+)/upload", path)
    if not m:
        h._json(404, {"ok": False, "error": "Nepoznata ruta."})
        return
    try:
        files = parse_multipart(raw, content_type)
        h._json(200, lt.add_images(int(m.group(1)), files, source="upload"))
    except KeyError as exc:
        h._json(404, {"ok": False, "error": str(exc).strip("'\"")})
    except (ValueError, RuntimeError) as exc:
        h._json(400, {"ok": False, "error": str(exc)})


def handle(h, method: str, path: str, query: dict, body: dict | None, ctx: dict) -> bool:
    try:
        return _route(h, method, path, query, body or {}, ctx)
    except KeyError as exc:
        h._json(404, {"ok": False, "error": str(exc).strip("'\"")})
    except lt.TrainerBusy as exc:
        h._json(409, {"ok": False, "error": str(exc), "need": "busy"})
    except (ValueError, RuntimeError, PermissionError) as exc:
        h._json(400, {"ok": False, "error": str(exc)})
    return True


def _route(h, method: str, path: str, query: dict, body: dict, ctx: dict) -> bool:
    J = h._json
    if not path.startswith(PREFIX):
        return False

    if method == "GET" and path == "/api/lora-trainer/status":
        J(200, lt.status(refresh=_q(query, "refresh") in {"1", "true"}))
        return True
    if path == "/api/lora-trainer/install-backend":
        J(200, lt.install_backend() if method == "POST" else {"ok": True, "install": lt.install_state(), "ready": lt.backend_ready()})
        return True
    if method == "GET" and path == "/api/lora-trainer/gpu-temp":
        t = lt.hardware_service.read_gpu_temperature()
        st, msg = lt.classify_temp(t.get("temp_c") if t.get("available") else None)
        J(200, {"ok": True, **t, "status": st, "message": msg})
        return True
    if path == "/api/lora-trainer/settings":
        J(200, {"ok": True, "temp": lt.save_temp_settings(body) if method == "POST" else lt.temp_settings()})
        return True
    if method == "GET" and path == "/api/lora-trainer/personas":
        J(200, {"ok": True, "personas": lt.personas_overview(), "active_job": lt.active_job()})
        return True

    # ---------- dataset ----------
    m = re.fullmatch(r"/api/lora-trainer/dataset/(\d+)", path)
    if m and method == "GET":
        J(200, lt.dataset_state(int(m.group(1))))
        return True
    m = re.fullmatch(r"/api/lora-trainer/dataset/(\d+)/(upload|import|clear)", path)
    if m and method == "POST":
        pid, action = int(m.group(1)), m.group(2)
        if action == "upload":
            J(200, lt.add_images(pid, decode_image_entries(body), source="upload"))
        elif action == "import":
            src = body.get("sources")
            J(200, lt.import_from_persona(pid, src if isinstance(src, list) else None))
        else:
            J(200, lt.clear_dataset(pid))
        return True
    m = re.fullmatch(r"/api/lora-trainer/dataset/(\d+)/file/(\d+)", path)
    if m and method == "GET":
        p = lt.image_file(int(m.group(1)), int(m.group(2)), thumb=_q(query, "thumb") in {"1", "true"})
        if not p:
            h._send(404, b"", "text/plain")
            return True
        h._send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "image/jpeg", {"Cache-Control": "private, max-age=3600"})
        return True
    m = re.fullmatch(r"/api/lora-trainer/dataset/(\d+)/images/(\d+)(/caption)?", path)
    if m:
        pid, iid = int(m.group(1)), int(m.group(2))
        if m.group(3) and method in {"POST", "PUT"}:
            J(200, lt.set_caption(pid, iid, str(body.get("caption") or "")))
            return True
        if not m.group(3) and method == "DELETE":
            J(200, lt.delete_image(pid, iid))
            return True

    # ---------- plan, treniranje, poslovi ----------
    if path == "/api/lora-trainer/plan" and method in {"GET", "POST"}:
        pid = _int(body.get("profile_id") or _q(query, "profile_id"))
        if not pid:
            raise ValueError("Odaberi osobu.")
        adv = body.get("advanced") if isinstance(body.get("advanced"), dict) else {}
        J(200, {"ok": True, "plan": lt.compute_plan(pid, str(body.get("preset") or _q(query, "preset") or lt.DEFAULT_PRESET), adv)})
        return True
    if method == "POST" and path == "/api/lora-trainer/start":
        pid = _int(body.get("profile_id"))
        if not pid:
            raise ValueError("Odaberi osobu.")
        adv = body.get("advanced") if isinstance(body.get("advanced"), dict) else {}
        J(200, {"ok": True, "job": lt.start_training(pid, str(body.get("preset") or lt.DEFAULT_PRESET), adv)})
        return True
    if method == "GET" and path == "/api/lora-trainer/jobs":
        pid = _q(query, "profile_id")
        J(200, {"ok": True, "jobs": lt.list_jobs(pid or None, limit=_int(_q(query, "limit", "20"), 20) or 20), "active_job": lt.active_job()})
        return True
    m = re.fullmatch(r"/api/lora-trainer/jobs/(\d+)(/cancel)?", path)
    if m:
        jid = int(m.group(1))
        if m.group(2) and method == "POST":
            J(200, {"ok": True, "job": lt.cancel_job(jid)})
            return True
        if not m.group(2) and method == "GET":
            job = lt.get_job(jid)
            if not job:
                raise KeyError("Posao treniranja ne postoji.")
            J(200, {"ok": True, "job": job})
            return True

    # ---------- trenirane LoRA-e osobe ----------
    if method == "GET" and path == "/api/lora-trainer/loras":
        pid = _int(_q(query, "profile_id"))
        if not pid:
            raise ValueError("Odaberi osobu.")
        J(200, {"ok": True, "loras": lt.list_trained(pid)})
        return True
    if method == "POST" and path == "/api/lora-trainer/activate":
        pid = _int(body.get("profile_id"))
        if not pid:
            raise ValueError("Odaberi osobu.")
        J(200, lt.activate_lora(pid, _int(body.get("lora_id")), str(body.get("lora_filename") or "")))
        return True

    J(404, {"ok": False, "error": "Nepoznata ruta LoRA trenera."})
    return True
