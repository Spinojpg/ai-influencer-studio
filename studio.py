#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI Influencer Studio — Jednostavno.

Lokalno web sučelje (port 7860): slike preko ComfyUI, poruke fanova preko Grok API-ja.
Samo Python standardna biblioteka.
"""

from __future__ import annotations

import base64
import json
import os
import random
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import applog
import inbox
import updater
import video as video_mod
import subprocess

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"

COMFY_BASE = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
HOST = os.environ.get("STUDIO_HOST", "127.0.0.1")
PORT = int(os.environ.get("STUDIO_PORT", "7860"))
CLIENT_ID = "simple-studio"
DEFAULT_MODEL = "Realistic_Vision_V6.0_NV_B1_fp16.safetensors"

DEFAULT_NEGATIVE = (
    "low quality, worst quality, blurry, deformed, ugly, bad anatomy, "
    "extra fingers, extra limbs, mutated hands, watermark, text, logo, "
    "jpeg artifacts, oversaturated, cartoon, 3d render, plastic skin, "
    "cropped, out of frame"
)


def _stdio_utf8() -> None:
    applog.safe_stdio()


def comfy_request(path: str, data=None, timeout: float = 15, method: str | None = None):
    url = COMFY_BASE + path
    body = None
    headers = {"Accept": "application/json", "User-Agent": "AI-Influencer-Studio/1.0"}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        ctype = resp.headers.get("Content-Type", "")
        if not raw:
            return None, dict(resp.headers), resp.status
        if "json" in ctype.lower() or raw[:1] in (b"{", b"["):
            try:
                return json.loads(raw.decode("utf-8")), dict(resp.headers), resp.status
            except json.JSONDecodeError:
                return raw, dict(resp.headers), resp.status
        return raw, dict(resp.headers), resp.status


def comfy_up() -> tuple[bool, str]:
    try:
        payload, _, _ = comfy_request("/system_stats", timeout=3)
        ver = ""
        if isinstance(payload, dict):
            ver = str((payload.get("system") or {}).get("comfyui_version") or "")
        msg = "ComfyUI je spojen."
        if ver:
            msg = f"ComfyUI je spojen (verzija {ver})."
        return True, msg
    except urllib.error.URLError as exc:
        return False, (
            "ComfyUI nije pokrenut ili ne odgovara na "
            f"{COMFY_BASE}. Pokreni comfyui-n.bat u mapi C:\\ComfyUI-Zluda "
            f"(detalj: {exc.reason if getattr(exc, 'reason', None) else exc})."
        )
    except Exception as exc:
        return False, f"Ne mogu se spojiti na ComfyUI ({exc}). Pokreni comfyui-n.bat."


def parse_ckpt_list(data) -> list[str]:
    if isinstance(data, list):
        return [str(x) for x in data if x]
    if not isinstance(data, dict):
        return []
    node = data.get("CheckpointLoaderSimple", data)
    try:
        names = node["input"]["required"]["ckpt_name"][0]
        if isinstance(names, list):
            return [str(x) for x in names if x]
    except Exception:
        pass
    return []


def list_models() -> list[str]:
    for path in ("/models/checkpoints", "/object_info/CheckpointLoaderSimple"):
        try:
            data, _, _ = comfy_request(path, timeout=8)
            names = parse_ckpt_list(data)
            if names:
                return names
        except Exception:
            continue
    return []


def video_capabilities() -> dict:
    caps = {
        "ready": False,
        "animatediff": [],
        "svd": [],
        "vhs": [],
        "native": [],
        "message": "",
        "comfy_ok": False,
        "recommend": video_mod.recommend_settings(8),
        "notes_hr": video_mod.recommend_settings(8)["note"],
    }
    ok, msg = comfy_up()
    caps["comfy_ok"] = ok
    caps["comfy_message"] = msg
    if not ok:
        caps["message"] = msg
        caps["notes_hr"] = video_mod.classify_nodes({}).get("notes_hr", "")
        return caps
    try:
        info, _, _ = comfy_request("/object_info", timeout=20)
    except Exception as exc:
        caps["message"] = f"Ne mogu dohvatiti popis čvorova iz ComfyUI-ja ({exc})."
        return caps
    if not isinstance(info, dict):
        caps["message"] = "ComfyUI /object_info nije vratio očekivani opis čvorova."
        return caps
    classified = video_mod.classify_nodes(info)
    classified["comfy_ok"] = True
    classified["comfy_message"] = msg
    classified["recommend"] = video_mod.recommend_settings(8)
    return classified


def build_workflow(
    *,
    prompt: str,
    negative: str,
    model: str,
    width: int,
    height: int,
    batch: int,
    seed: int,
    steps: int,
) -> dict:
    return {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": model},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {
                "width": int(width),
                "height": int(height),
                "batch_size": int(batch),
            },
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative, "clip": ["4", 1]},
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": int(seed),
                "steps": int(steps),
                "cfg": 5,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "denoise": 1,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "studio", "images": ["8", 0]},
        },
    }


def extract_images(hist_entry: dict) -> list[dict]:
    images = []
    outputs = (hist_entry or {}).get("outputs") or {}
    for node_out in outputs.values():
        if not isinstance(node_out, dict):
            continue
        for img in node_out.get("images") or []:
            if not isinstance(img, dict):
                continue
            filename = img.get("filename")
            if not filename:
                continue
            images.append(
                {
                    "filename": filename,
                    "subfolder": img.get("subfolder") or "",
                    "type": img.get("type") or "output",
                }
            )
        for key in ("gifs", "videos", "audio"):
            for item in node_out.get(key) or []:
                if isinstance(item, dict) and item.get("filename"):
                    images.append(
                        {
                            "filename": item["filename"],
                            "subfolder": item.get("subfolder") or "",
                            "type": item.get("type") or "output",
                            "kind": key,
                        }
                    )
    return images


def job_status(prompt_id: str) -> dict:
    progress = {"value": 0, "max": 1}
    try:
        prog, _, _ = comfy_request("/progress", timeout=5)
        if isinstance(prog, dict):
            progress["value"] = float(prog.get("value") or 0)
            progress["max"] = float(prog.get("max") or 1) or 1
    except Exception:
        pass

    try:
        data, _, _ = comfy_request("/history/" + urllib.parse.quote(prompt_id), timeout=8)
    except Exception as exc:
        return {
            "status": "running",
            "progress": progress,
            "images": [],
            "error": None,
            "note": str(exc),
        }

    entry = None
    if isinstance(data, dict):
        entry = data.get(prompt_id)
        if entry is None and len(data) == 1:
            entry = next(iter(data.values()))
        if entry is None and "outputs" in data:
            entry = data

    if not entry:
        return {"status": "running", "progress": progress, "images": [], "error": None}

    status_obj = entry.get("status") or {}
    status_str = str(status_obj.get("status_str") or "").lower()
    completed = bool(status_obj.get("completed"))
    images = extract_images(entry)

    messages = status_obj.get("messages") or []
    error_text = None
    for item in messages:
        if isinstance(item, (list, tuple)) and item and str(item[0]).lower().endswith("error"):
            error_text = json.dumps(item, ensure_ascii=False)
        elif isinstance(item, dict) and item.get("type") == "error":
            error_text = json.dumps(item, ensure_ascii=False)

    if error_text or status_str in {"error", "failed", "exception"}:
        return {
            "status": "error",
            "progress": {"value": 1, "max": 1},
            "images": images,
            "error": error_text or "ComfyUI je prijavio grešku pri generiranju.",
        }

    if completed or images or status_str == "success":
        return {
            "status": "done",
            "progress": {"value": 1, "max": 1},
            "images": images,
            "error": None,
        }

    return {"status": "running", "progress": progress, "images": images, "error": None}


def clamp_int(value, lo, hi, default):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def compose_prompt(persona: str, prompt: str) -> str:
    persona = (persona or "").strip()
    prompt = (prompt or "").strip()
    if persona and prompt:
        if prompt.lower().startswith(persona.lower()):
            return prompt
        return f"{persona}, {prompt}"
    return persona or prompt


class StudioHandler(BaseHTTPRequestHandler):
    server_version = "SimpleStudio/1.0"

    def log_message(self, fmt: str, *args) -> None:
        try:
            msg = fmt % args
        except Exception:
            msg = str(fmt)
        # Nikad ne zapisuj tajne iz queryja ili zaglavlja.
        for name in ("XAI_API_KEY", "IG_ACCESS_TOKEN", "IG_APP_SECRET", "IG_VERIFY_TOKEN", "TELEGRAM_BOT_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
            try:
                val = inbox.secret(name)
            except Exception:
                val = ""
            if val:
                try:
                    msg = msg.replace(val, inbox._redact(val))
                except Exception:
                    pass
        try:
            applog.get_logger("studio").info("%s - %s", self.address_string(), msg)
        except Exception:
            pass

    def log_error(self, fmt: str, *args) -> None:
        try:
            msg = fmt % args
        except Exception:
            msg = str(fmt)
        try:
            applog.get_logger("studio").error("%s - %s", self.address_string(), msg)
        except Exception:
            pass

    def _headers_already_sent(self) -> bool:
        return bool(getattr(self, "_studio_headers_sent", False))

    def _send_error_response(self) -> None:
        if self._headers_already_sent():
            self.close_connection = True
            return
        try:
            self._json(500, {"ok": False, "error": "Unutarnja greška poslužitelja."})
        except Exception:
            self.close_connection = True
            try:
                applog.get_logger("studio").exception("Nisam mogao poslati HTTP 500")
            except Exception:
                pass

    def handle(self) -> None:
        try:
            super().handle()
        except Exception:
            try:
                applog.get_logger("studio").exception("Nepopravljiva greška HTTP veze")
            except Exception:
                pass
            self.close_connection = True

    def _send(self, code: int, body: bytes, content_type: str, extra_headers=None) -> None:
        self.send_response(code)
        self._studio_headers_sent = True
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        headers = {"Cache-Control": "no-store"}
        if extra_headers:
            headers.update(extra_headers)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, raw, "application/json; charset=utf-8")

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 20_000_000:
            raise ValueError("Zahtjev je prevelik.")
        return self.rfile.read(length) if length else b""

    def _read_json_from(self, raw: bytes):
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        try:
            self._handle_get()
        except Exception:
            try:
                applog.get_logger("studio").exception("Greška u GET %s", getattr(self, "path", ""))
            except Exception:
                pass
            self._send_error_response()

    def do_POST(self) -> None:  # noqa: N802
        try:
            self._handle_post()
        except Exception:
            try:
                applog.get_logger("studio").exception("Greška u zahtjevu %s", getattr(self, "path", ""))
            except Exception:
                pass
            self._send_error_response()

    def do_PUT(self) -> None:  # noqa: N802
        try:
            self._handle_put()
        except Exception:
            try:
                applog.get_logger("studio").exception("Greška u zahtjevu %s", getattr(self, "path", ""))
            except Exception:
                pass
            self._send_error_response()

    def do_DELETE(self) -> None:  # noqa: N802
        try:
            self._handle_delete()
        except Exception:
            try:
                applog.get_logger("studio").exception("Greška u zahtjevu %s", getattr(self, "path", ""))
            except Exception:
                pass
            self._send_error_response()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, b"", "text/plain")

    def _handle_get(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            if not INDEX.is_file():
                self._send(500, "Nedostaje index.html.".encode("utf-8"), "text/plain; charset=utf-8")
                return
            self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
            return

        if path in ("/webhook/instagram", "/api/ig/webhook"):
            self._ig_verify(query)
            return

        if path == "/api/status":
            ok, msg = comfy_up()
            self._json(200, {"ok": ok, "message": msg, "comfy": COMFY_BASE})
            return

        if path == "/api/state":
            ok, msg = comfy_up()
            state = inbox.app_state()
            state["comfy"] = {"ok": ok, "message": msg, "url": COMFY_BASE}
            state["version"] = updater.load_version(ROOT).get("version") or "0.0.0"
            state["update"] = updater.read_update_result(inbox.DATA_DIR)
            self._json(200, state)
            return

        if path == "/api/update/check":
            self._update_check()
            return

        if path == "/api/models":
            ok, msg = comfy_up()
            if not ok:
                self._json(200, {"ok": False, "error": msg, "models": [], "default": DEFAULT_MODEL})
                return
            models = list_models()
            default = DEFAULT_MODEL if DEFAULT_MODEL in models else (models[0] if models else DEFAULT_MODEL)
            prof = inbox.get_profile(inbox.active_profile_id())
            if prof and prof.get("preferred_model") and prof["preferred_model"] in models:
                default = prof["preferred_model"]
            self._json(200, {"ok": True, "models": models, "default": default})
            return

        if path == "/api/profiles":
            self._json(200, {"ok": True, "profiles": inbox.list_profiles(), "active_profile_id": inbox.active_profile_id()})
            return

        m = re.fullmatch(r"/api/profiles/(\d+)/image", path)
        if m:
            self._serve_reference(int(m.group(1)))
            return

        m = re.fullmatch(r"/api/profiles/(\d+)", path)
        if m:
            prof = inbox.get_profile(int(m.group(1)))
            if not prof:
                self._json(404, {"ok": False, "error": "Profil ne postoji."})
                return
            self._json(200, {"ok": True, "profile": prof})
            return

        if path == "/api/settings":
            self._json(200, {"ok": True, "settings": inbox.public_settings()})
            return

        if path == "/api/inbox/threads":
            pid = query.get("profile_id", [None])[0]
            try:
                pid = int(pid) if pid else inbox.active_profile_id()
            except ValueError:
                pid = inbox.active_profile_id()
            if not pid:
                self._json(200, {"ok": True, "threads": []})
                return
            self._json(200, {"ok": True, "threads": inbox.list_threads(pid)})
            return

        m = re.fullmatch(r"/api/inbox/threads/(\d+)", path)
        if m:
            data = inbox.get_thread(int(m.group(1)))
            if not data:
                self._json(404, {"ok": False, "error": "Razgovor ne postoji."})
                return
            self._json(200, {"ok": True, "thread": data})
            return

        if path == "/api/video/capabilities":
            self._json(200, {"ok": True, **video_capabilities()})
            return

        if path.startswith("/api/job/"):
            prompt_id = urllib.parse.unquote(path[len("/api/job/") :]).strip()
            if not prompt_id:
                self._json(400, {"ok": False, "error": "Nedostaje prompt_id."})
                return
            result = job_status(prompt_id)
            result["ok"] = result.get("status") != "error"
            result["prompt_id"] = prompt_id
            for img in result.get("images") or []:
                img["url"] = "/api/view?" + urllib.parse.urlencode(
                    {
                        "filename": img["filename"],
                        "subfolder": img.get("subfolder") or "",
                        "type": img.get("type") or "output",
                    }
                )
            self._json(200, result)
            return

        if path == "/api/view":
            self._proxy_view(query)
            return

        self._send(404, "Nije pronađeno.".encode("utf-8"), "text/plain; charset=utf-8")

    def _ig_verify(self, query) -> None:
        mode = (query.get("hub.mode") or [""])[0]
        token = (query.get("hub.verify_token") or [""])[0]
        challenge = (query.get("hub.challenge") or [""])[0]
        ok, payload = inbox.verify_instagram_webhook(mode, token, challenge)
        if ok:
            body = payload.encode("utf-8")
            self._send(200, body, "text/plain; charset=utf-8")
        else:
            self._send(403, payload.encode("utf-8"), "text/plain; charset=utf-8")

    def _serve_reference(self, pid: int) -> None:
        path = inbox.reference_image_path(pid)
        if not path:
            self._json(404, {"ok": False, "error": "Nema referentne slike."})
            return
        data = path.read_bytes()
        ext = path.suffix.lower()
        ctype = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(ext, "application/octet-stream")
        self._send(200, data, ctype, {"Cache-Control": "private, max-age=3600"})

    def _proxy_view(self, query) -> None:
        filename = (query.get("filename") or [""])[0]
        if not filename or "/" in filename or "\\" in filename or ".." in filename:
            self._json(400, {"ok": False, "error": "Neispravno ime datoteke."})
            return
        params = {
            "filename": filename,
            "subfolder": (query.get("subfolder") or [""])[0],
            "type": (query.get("type") or ["output"])[0] or "output",
        }
        url = COMFY_BASE + "/view?" + urllib.parse.urlencode(params)
        download = (query.get("download") or [""])[0] in {"1", "true", "yes"}
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AI-Influencer-Studio/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                ctype = resp.headers.get("Content-Type") or "image/png"
            headers = {}
            if download:
                headers["Content-Disposition"] = f'attachment; filename="{filename}"'
            else:
                headers["Content-Disposition"] = f'inline; filename="{filename}"'
            headers["Cache-Control"] = "private, max-age=3600"
            self._send(200, data, ctype, headers)
        except urllib.error.HTTPError as exc:
            self._json(exc.code, {"ok": False, "error": f"ComfyUI /view: HTTP {exc.code}"})
        except Exception as exc:
            self._json(502, {"ok": False, "error": f"Ne mogu dohvatiti sliku: {exc}"})

    def _handle_post(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        raw = self._read_body()

        if path in ("/webhook/instagram", "/api/ig/webhook"):
            self._ig_incoming(raw)
            return

        try:
            body = self._read_json_from(raw) if raw else {}
        except Exception:
            self._json(400, {"ok": False, "error": "Tijelo zahtjeva nije valjani JSON."})
            return
        if not isinstance(body, dict):
            self._json(400, {"ok": False, "error": "Tijelo zahtjeva nije objekt."})
            return

        if path == "/api/generate":
            self._generate_image(body)
            return

        if path == "/api/video/generate":
            self._generate_video(body)
            return

        if path == "/api/profiles":
            try:
                prof = inbox.upsert_profile(body)
            except ValueError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
                return
            self._json(200, {"ok": True, "profile": prof})
            return

        if path == "/api/profiles/select":
            try:
                pid = int(body.get("id"))
            except (TypeError, ValueError):
                self._json(400, {"ok": False, "error": "Nedostaje id profila."})
                return
            if not inbox.get_profile(pid):
                self._json(404, {"ok": False, "error": "Profil ne postoji."})
                return
            inbox.set_setting("active_profile_id", str(pid))
            inbox.export_profiles_json()
            self._json(200, {"ok": True, "active_profile_id": pid, "profile": inbox.get_profile(pid)})
            return

        m = re.fullmatch(r"/api/profiles/(\d+)/image", path)
        if m:
            self._upload_reference(int(m.group(1)), body)
            return

        if path == "/api/settings":
            try:
                settings = inbox.update_settings(body)
            except ValueError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
                return
            self._json(200, {"ok": True, "settings": settings})
            return

        if path == "/api/inbox/simulate":
            text = (body.get("text") or body.get("message") or "").strip()
            if not text:
                self._json(400, {"ok": False, "error": "Upiši poruku fana."})
                return
            pid = body.get("profile_id") or inbox.active_profile_id()
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                self._json(400, {"ok": False, "error": "Nema aktivnog profila."})
                return
            fan = (body.get("fan_name") or "Fan").strip() or "Fan"
            if not inbox.xai_configured():
                self._json(400, {"ok": False, "error": "Nema XAI_API_KEY. Uredi .env — vidi PORUKE_UPUTE.txt."})
                return
            try:
                result = inbox.handle_incoming(pid, "simulate", "sim-" + fan.lower().replace(" ", "-")[:40], text, display_name=fan)
            except Exception as exc:
                self._json(400, {"ok": False, "error": str(exc)})
                return
            self._json(200, result)
            return

        m = re.fullmatch(r"/api/inbox/drafts/(\d+)/(send|edit|discard|regenerate)", path)
        if m:
            self._draft_action(int(m.group(1)), m.group(2), body)
            return

        m = re.fullmatch(r"/api/inbox/threads/(\d+)/pause", path)
        if m:
            try:
                data = inbox.set_thread_paused(int(m.group(1)), bool(body.get("paused", True)))
            except KeyError as exc:
                self._json(404, {"ok": False, "error": str(exc)})
                return
            self._json(200, {"ok": True, "thread": data})
            return

        if path == "/api/update/check":
            self._update_check()
            return

        if path == "/api/update/apply":
            self._update_apply()
            return

        if path == "/api/update/ack":
            updater.ack_update_result(inbox.DATA_DIR)
            self._json(200, {"ok": True})
            return

        self._json(404, {"ok": False, "error": "Nepoznat endpoint."})

    def _update_check(self) -> None:
        try:
            token = updater.github_token(data_dir=inbox.DATA_DIR)
            info = updater.check_for_update(ROOT, inbox.DATA_DIR, token=token)
        except Exception as exc:
            self._json(400, {"ok": False, "error": updater._safe_err(str(exc), updater.github_token(data_dir=inbox.DATA_DIR))})
            return
        # Ne šalji sirove URL-ove s tokenima; frontend treba samo sažetak.
        info = dict(info)
        info.pop("release", None)
        self._json(200, info)

    def _update_apply(self) -> None:
        token = updater.github_token(data_dir=inbox.DATA_DIR)
        try:
            info = updater.check_for_update(ROOT, inbox.DATA_DIR, token=token)
            if not info.get("configured"):
                self._json(400, {"ok": False, "error": info.get("message") or "Update nije podešen."})
                return
            if not info.get("newer"):
                self._json(200, {"ok": True, "applied": False, "message": info.get("message")})
                return
            cfg = updater.load_update_config(inbox.DATA_DIR)
            pending = inbox.DATA_DIR / "pending-update"
            downloaded = updater.download_and_verify(info["release"], pending, cfg, token=token)
            meta = {
                "zip_path": downloaded["zip_path"],
                "notes": info.get("notes") or "",
                "latest": info.get("latest"),
                "current": info.get("current"),
            }
            (pending / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            self._json(400, {"ok": False, "error": updater._safe_err(str(exc), token)})
            return
        _spawn_updater_and_exit()
        self._json(200, {
            "ok": True,
            "restarting": True,
            "message": "Preuzeto. Aplikacija će se sada restartati i instalirati ažuriranje.",
            "latest": info.get("latest"),
        })

    def _handle_put(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        raw = self._read_body()
        try:
            body = self._read_json_from(raw) if raw else {}
        except Exception:
            self._json(400, {"ok": False, "error": "Tijelo zahtjeva nije valjani JSON."})
            return
        m = re.fullmatch(r"/api/profiles/(\d+)", parsed.path)
        if not m:
            if parsed.path == "/api/settings":
                try:
                    settings = inbox.update_settings(body if isinstance(body, dict) else {})
                except ValueError as exc:
                    self._json(400, {"ok": False, "error": str(exc)})
                    return
                self._json(200, {"ok": True, "settings": settings})
                return
            self._json(404, {"ok": False, "error": "Nepoznat endpoint."})
            return
        if not isinstance(body, dict):
            self._json(400, {"ok": False, "error": "Tijelo zahtjeva nije objekt."})
            return
        try:
            prof = inbox.upsert_profile(body, pid=int(m.group(1)))
        except KeyError as exc:
            self._json(404, {"ok": False, "error": str(exc)})
            return
        except ValueError as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return
        self._json(200, {"ok": True, "profile": prof})

    def _handle_delete(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        m = re.fullmatch(r"/api/profiles/(\d+)", parsed.path)
        if not m:
            self._json(404, {"ok": False, "error": "Nepoznat endpoint."})
            return
        try:
            inbox.delete_profile(int(m.group(1)))
        except ValueError as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return
        self._json(200, {"ok": True, "profiles": inbox.list_profiles(), "active_profile_id": inbox.active_profile_id()})

    def _upload_reference(self, pid: int, body: dict) -> None:
        b64 = body.get("image_b64") or body.get("image") or ""
        if isinstance(b64, str) and b64.startswith("data:"):
            try:
                header, b64 = b64.split(",", 1)
            except ValueError:
                self._json(400, {"ok": False, "error": "Neispravan data-URL."})
                return
            ext = "jpg"
            if "png" in header:
                ext = "png"
            elif "webp" in header:
                ext = "webp"
        else:
            ext = (body.get("ext") or "jpg").lstrip(".")
        if not b64:
            self._json(400, {"ok": False, "error": "Nedostaje slika."})
            return
        try:
            data = base64.b64decode(b64, validate=False)
        except Exception:
            self._json(400, {"ok": False, "error": "Slika nije valjani base64."})
            return
        if len(data) < 20 or len(data) > 8_000_000:
            self._json(400, {"ok": False, "error": "Slika je prazna ili veća od 8 MB."})
            return
        try:
            rel = inbox.save_reference_image(pid, data, ext)
        except KeyError as exc:
            self._json(404, {"ok": False, "error": str(exc)})
            return
        self._json(200, {"ok": True, "reference_image": rel, "url": f"/api/profiles/{pid}/image"})

    def _draft_action(self, draft_id: int, action: str, body: dict) -> None:
        try:
            if action == "send":
                msg = inbox.send_draft(draft_id)
            elif action == "edit":
                msg = inbox.edit_draft(draft_id, body.get("body") or body.get("text") or "")
            elif action == "discard":
                msg = inbox.discard_draft(draft_id)
            elif action == "regenerate":
                if not inbox.xai_configured():
                    self._json(400, {"ok": False, "error": "Nema XAI_API_KEY."})
                    return
                msg = inbox.regenerate_draft(draft_id)
            else:
                self._json(404, {"ok": False, "error": "Nepoznata akcija."})
                return
        except (KeyError, ValueError, RuntimeError) as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return
        self._json(200, {"ok": True, "message": msg})

    def _ig_incoming(self, raw: bytes) -> None:
        header = self.headers.get("X-Hub-Signature-256") or self.headers.get("X-Hub-Signature") or ""
        if not inbox.secret("IG_APP_SECRET"):
            self._json(403, {"ok": False, "error": "IG_APP_SECRET nije postavljen u .env — webhook je odbijen."})
            return
        if not inbox.check_instagram_signature(raw, header):
            self._json(403, {"ok": False, "error": "Neispravan potpis webhooka."})
            return
        try:
            payload = json.loads(raw.decode("utf-8") if raw else "{}")
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "Neispravan JSON."})
            return
        try:
            result = inbox.process_instagram_webhook(payload)
        except Exception as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return
        self._json(200, result)

    def _generate_image(self, body: dict) -> None:
        ok, msg = comfy_up()
        if not ok:
            self._json(503, {"ok": False, "error": msg})
            return

        prof = inbox.get_profile(inbox.active_profile_id())
        prefix = (body.get("persona") or "").strip()
        if not prefix and prof:
            prefix = prof.get("appearance_prompt") or ""
        prompt = compose_prompt(prefix, body.get("prompt") or "")
        if not prompt:
            self._json(400, {"ok": False, "error": "Upiši opis slike."})
            return

        negative = (body.get("negative") or "").strip()
        if not negative and prof:
            negative = (prof.get("negative_prompt") or "").strip()
        if not negative:
            negative = DEFAULT_NEGATIVE

        model = (body.get("model") or "").strip()
        if not model and prof:
            model = (prof.get("preferred_model") or "").strip()
        if not model:
            model = DEFAULT_MODEL

        width = clamp_int(body.get("width"), 256, 1024, 512)
        height = clamp_int(body.get("height"), 256, 1024, 768)
        width = max(256, min(1024, width - (width % 8)))
        height = max(256, min(1024, height - (height % 8)))
        batch = clamp_int(body.get("batch"), 1, 4, 1)
        steps = clamp_int(body.get("steps"), 4, 50, 20)

        seed = body.get("seed")
        if seed is None or seed == "" or int(seed) < 0:
            seed = random.randint(0, 2_147_483_647)
        else:
            seed = clamp_int(seed, 0, 2_147_483_647, random.randint(0, 2_147_483_647))

        workflow = build_workflow(
            prompt=prompt,
            negative=negative,
            model=model,
            width=width,
            height=height,
            batch=batch,
            seed=seed,
            steps=steps,
        )
        self._queue_prompt(workflow, {
            "ok": True,
            "seed": seed,
            "model": model,
            "width": width,
            "height": height,
            "batch": batch,
            "steps": steps,
            "prompt": prompt,
            "kind": "image",
        })

    def _generate_video(self, body: dict) -> None:
        caps = video_capabilities()
        if not caps.get("comfy_ok"):
            self._json(503, {"ok": False, "error": caps.get("comfy_message") or caps.get("message")})
            return
        prof = inbox.get_profile(inbox.active_profile_id())
        prefix = (body.get("persona") or "").strip()
        if not prefix and prof:
            prefix = prof.get("appearance_prompt") or ""
        prompt = compose_prompt(prefix, body.get("prompt") or "")
        if not prompt:
            self._json(400, {"ok": False, "error": "Upiši opis klipa."})
            return
        negative = (body.get("negative") or "").strip()
        if not negative and prof:
            negative = (prof.get("negative_prompt") or "").strip()
        if not negative:
            negative = DEFAULT_NEGATIVE
        model = (body.get("model") or "").strip()
        if not model and prof:
            model = (prof.get("preferred_model") or "").strip()
        if not model:
            model = DEFAULT_MODEL
        rec = caps.get("recommend") or video_mod.recommend_settings(8)
        width = clamp_int(body.get("width"), 256, 512, rec["width"])
        height = clamp_int(body.get("height"), 256, 512, rec["height"])
        frames = clamp_int(body.get("frames"), 4, 16, rec["frames"])
        steps = clamp_int(body.get("steps"), 8, 30, rec["steps"])
        seed = body.get("seed")
        if seed is None or seed == "" or int(seed) < 0:
            seed = random.randint(0, 2_147_483_647)
        else:
            seed = clamp_int(seed, 0, 2_147_483_647, random.randint(0, 2_147_483_647))
        wf, note = video_mod.build_video_workflow(
            caps,
            prompt=prompt,
            negative=negative,
            model=model,
            width=width,
            height=height,
            frames=frames,
            steps=steps,
            seed=seed,
        )
        if not wf:
            self._json(400, {"ok": False, "error": note, "capabilities": caps})
            return
        self._queue_prompt(wf, {
            "ok": True,
            "seed": seed,
            "model": model,
            "width": width,
            "height": height,
            "frames": frames,
            "steps": steps,
            "prompt": prompt,
            "kind": "video",
            "warning": note,
        })

    def _queue_prompt(self, workflow: dict, extra: dict) -> None:
        payload = {"prompt": workflow, "client_id": CLIENT_ID}
        try:
            result, _, _ = comfy_request("/prompt", data=payload, timeout=30)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:2000]
            self._json(502, {"ok": False, "error": f"ComfyUI je odbio zadatak (HTTP {exc.code}). {detail}"})
            return
        except Exception as exc:
            self._json(503, {"ok": False, "error": f"ComfyUI ne odgovara: {exc}. Pokreni comfyui-n.bat."})
            return
        if not isinstance(result, dict):
            self._json(502, {"ok": False, "error": "Neočekivani odgovor od ComfyUI /prompt."})
            return
        node_errors = result.get("node_errors") or {}
        if result.get("error") or node_errors:
            self._json(400, {"ok": False, "error": "ComfyUI nije prihvatio workflow.", "detail": result.get("error") or node_errors})
            return
        prompt_id = result.get("prompt_id")
        if not prompt_id:
            self._json(502, {"ok": False, "error": "ComfyUI nije vratio prompt_id."})
            return
        extra = dict(extra)
        extra["prompt_id"] = prompt_id
        self._json(200, extra)


_httpd = None
PID_FILE = None


def _write_pid(data_dir: Path) -> None:
    global PID_FILE
    PID_FILE = Path(data_dir) / "studio.pid"
    try:
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        PID_FILE = None


def _clear_pid() -> None:
    if PID_FILE and PID_FILE.is_file():
        try:
            if PID_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
                PID_FILE.unlink()
        except OSError:
            pass


def _spawn_updater_and_exit() -> None:
    """Pokreni launcher --apply-pending i ugasi ovaj poslužitelj."""
    cmd = [sys.executable, str(ROOT / "launcher.py"), "--apply-pending"]
    env = os.environ.copy()
    env["STUDIO_APP_DIR"] = str(ROOT)
    env["STUDIO_DATA_DIR"] = str(inbox.DATA_DIR)
    env["STUDIO_SKIP_UPDATE"] = "1"
    kwargs = {"cwd": str(ROOT), "env": env, "close_fds": True}
    if sys.platform == "win32":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        kwargs["creationflags"] = flags
        kwargs["stdin"] = subprocess.DEVNULL
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)

    def _later():
        time.sleep(0.8)
        httpd = _httpd
        if httpd is not None:
            try:
                httpd.shutdown()
            except Exception:
                os._exit(0)

    threading.Thread(target=_later, daemon=True).start()


def open_browser(url: str) -> None:
    time.sleep(0.7)
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main() -> int:
    global _httpd
    inbox.configure_paths()
    applog.setup(inbox.DATA_DIR, "studio")
    _stdio_utf8()
    inbox.load_dotenv(inbox.ENV_PATH)
    inbox.load_dotenv(ROOT / ".env")
    inbox.init_db()
    updater.write_default_update_config(inbox.DATA_DIR)
    _write_pid(inbox.DATA_DIR)
    if inbox.get_setting("telegram_enabled") == "1" and inbox.secret("TELEGRAM_BOT_TOKEN"):
        inbox.start_telegram_worker()
        print("Telegram long polling je ukljucen.")
    if not INDEX.is_file():
        print("GRESKA: Nedostaje index.html pored studio.py")
        return 1

    httpd = ThreadingHTTPServer((HOST, PORT), StudioHandler)
    _httpd = httpd
    url = f"http://{HOST}:{PORT}/"
    ver = updater.load_version(ROOT).get("version") or "?"
    print("============================================")
    print("  AI Influencer Studio - Jednostavno")
    print(f"  Verzija:  {ver}")
    print(f"  Sucelje:  {url}")
    print(f"  ComfyUI:  {COMFY_BASE}")
    print(f"  Podaci:   {inbox.DATA_DIR}")
    print(f"  Log:      {inbox.DATA_DIR / 'logs' / 'studio.log'}")
    print("  Kartice: Slike, Poruke, Influenceri")
    print("============================================")
    print("Zaustavi sa Ctrl+C.")
    ok, msg = comfy_up()
    print(("OK: " if ok else "UPOZORENJE: ") + msg)
    if inbox.xai_configured():
        print("OK: xAI kljuc je ucitan iz okruzenja / .env")
    else:
        print("UPOZORENJE: Nema XAI_API_KEY. Kartica Poruke treba kljuc u .env — vidi PORUKE_UPUTE.txt")
    if os.environ.get("STUDIO_NO_BROWSER") != "1":
        threading.Thread(target=open_browser, args=(url,), daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nZaustavljam...")
    finally:
        inbox.stop_telegram_worker()
        httpd.server_close()
        _clear_pid()
    return 0


if __name__ == "__main__":
    sys.exit(main())
