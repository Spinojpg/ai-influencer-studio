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

import app_session
import applog
import comfy_launch
import comfy_ws
import image_gen
import inbox
import installed_models
import model_download
import updater
import video as video_mod
import video_install
import character
import character_install
import subprocess

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"

COMFY_BASE = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
HOST = os.environ.get("STUDIO_HOST", "127.0.0.1")
PORT = int(os.environ.get("STUDIO_PORT", "7860"))
CLIENT_ID = "simple-studio"
DEFAULT_MODEL = "Realistic_Vision_V6.0_NV_B1_fp16.safetensors"

DEFAULT_NEGATIVE = image_gen.DEFAULT_NEGATIVE
QUALITY_PREFIX = image_gen.QUALITY_PREFIX


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
    names = list_checkpoint_models()
    for n in list_diffusion_models():
        if n not in names:
            names.append(n)
    return names


def list_checkpoint_models() -> list[str]:
    for path in ("/models/checkpoints", "/object_info/CheckpointLoaderSimple"):
        try:
            data, _, _ = comfy_request(path, timeout=8)
            names = parse_ckpt_list(data)
            if names:
                return names
        except Exception:
            continue
    return comfy_launch.list_files(comfy_launch.checkpoints_dir())


def parse_unet_list(data) -> list[str]:
    if isinstance(data, list):
        return [str(x) for x in data if x]
    if not isinstance(data, dict):
        return []
    node = data.get("UNETLoader", data)
    try:
        names = node["input"]["required"]["unet_name"][0]
        if isinstance(names, list):
            return [str(x) for x in names if x]
    except Exception:
        pass
    return []


def list_diffusion_models() -> list[str]:
    names: list[str] = []
    for path in ("/models/diffusion_models", "/object_info/UNETLoader"):
        try:
            data, _, _ = comfy_request(path, timeout=8)
            found = parse_unet_list(data)
            if found:
                names = found
                break
        except Exception:
            continue
    if not names:
        names = comfy_launch.list_files(comfy_launch.diffusion_models_dir())
    return names


def parse_lora_list(data) -> list[str]:
    if isinstance(data, list):
        return [str(x) for x in data if x]
    if not isinstance(data, dict):
        return []
    node = data.get("LoraLoader", data)
    try:
        names = node["input"]["required"]["lora_name"][0]
        if isinstance(names, list):
            return [str(x) for x in names if x]
    except Exception:
        pass
    return []


def list_lora_names() -> list[str]:
    for path in ("/models/loras", "/object_info/LoraLoader"):
        try:
            data, _, _ = comfy_request(path, timeout=8)
            names = parse_lora_list(data)
            if names:
                return names
        except Exception:
            continue
    return image_gen.list_loras()


def fetch_lora_metadata(name: str) -> dict:
    """Metapodaci LoRA-e: prvo ComfyUI /view_metadata/loras, zatim lokalna datoteka."""
    filename = (name or "").replace("\\", "/").split("/")[-1]
    if not filename:
        return {}
    try:
        qs = urllib.parse.urlencode({"filename": filename})
        data, _, _ = comfy_request("/view_metadata/loras?" + qs, timeout=6)
        if isinstance(data, dict) and data:
            return data
    except Exception:
        pass
    return image_gen.read_safetensors_metadata(comfy_launch.loras_dir() / filename)


def lora_entries(names: list[str] | None = None) -> list[dict]:
    if names is None:
        names = list_lora_names()
    return image_gen.classify_loras(names, metadata_fn=fetch_lora_metadata)


def resolve_generation_profile(body: dict, fallback: dict | None = None) -> dict | None:
    """Profil osobe za sliku (persona_id), inače predani fallback (aktivni)."""
    raw = body.get("persona_id", body.get("profile_id"))
    if raw not in (None, ""):
        try:
            pid = int(raw)
        except (TypeError, ValueError):
            return fallback
        if fallback and fallback.get("id") is not None:
            try:
                if int(fallback["id"]) == pid:
                    return fallback
            except (TypeError, ValueError):
                pass
        try:
            prof = inbox.get_profile(pid)
            if prof:
                return prof
        except Exception:
            pass
        return fallback
    return fallback


def resolve_appearance(body: dict, profile: dict | None) -> str:
    """Izgled iz odabrane osobe + Dodatno, ili ručni body['persona'] (stari klijenti/testovi)."""
    extra = (body.get("appearance_extra") or body.get("dodatno") or "").strip()
    has_id = body.get("persona_id", body.get("profile_id")) not in (None, "")
    if has_id and profile:
        return image_gen.appearance_from_profile(profile, extra)
    typed = (body.get("persona") or "").strip()
    if typed:
        if extra:
            return image_gen.appearance_from_profile({"appearance_prompt": typed}, extra)
        return typed
    if profile:
        return image_gen.appearance_from_profile(profile, extra)
    return extra


def object_info() -> dict:
    try:
        data, _, _ = comfy_request("/object_info", timeout=20)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def model_entries(names: list[str] | None = None) -> list[dict]:
    if names is None:
        ckpts = list_checkpoint_models()
        diffs = list_diffusion_models()
        entries = []
        seen = set()
        for n in diffs:
            if n in seen:
                continue
            seen.add(n)
            arch = image_gen.detect_model_arch(n)
            if arch != "krea2":
                arch = "krea2" if "krea" in n.lower() else arch
            label = "Krea 2" if arch == "krea2" else ("SDXL" if arch == "sdxl" else "SD 1.5")
            entries.append({"name": n, "arch": arch, "kind": "diffusion", "group": label})
        for n in ckpts:
            if n in seen:
                continue
            seen.add(n)
            arch = image_gen.detect_model_arch(n)
            label = "SDXL" if arch == "sdxl" else "SD 1.5"
            entries.append({"name": n, "arch": arch, "kind": "checkpoint", "group": label})
        return entries
    return [{"name": n, "arch": image_gen.detect_model_arch(n), "kind": "checkpoint", "group": ""} for n in names]


def krea2_file_status() -> dict:
    """Koje Krea 2 datoteke već stoje u ComfyUI mapama."""
    unet = image_gen.KREA2_UNET
    clip = image_gen.KREA2_CLIP
    vae = image_gen.KREA2_VAE
    unet_dir = comfy_launch.diffusion_models_dir()
    clip_dir = comfy_launch.text_encoders_dir()
    vae_dir = comfy_launch.vae_dir()
    have_unet = (unet_dir / unet).is_file() or unet in set(comfy_launch.list_files(unet_dir))
    have_clip = (clip_dir / clip).is_file() or clip in set(comfy_launch.list_files(clip_dir))
    have_vae = (vae_dir / vae).is_file() or vae in set(comfy_launch.list_files(vae_dir))
    missing = []
    if not have_unet:
        missing.append(f"{unet} (models/diffusion_models)")
    if not have_clip:
        missing.append(f"{clip} (models/text_encoders)")
    if not have_vae:
        missing.append(f"{vae} (models/vae)")
    return {
        "unet": have_unet,
        "clip": have_clip,
        "vae": have_vae,
        "ready": have_unet and have_clip and have_vae,
        "missing": missing,
        "paths": {
            "diffusion_models": str(unet_dir),
            "text_encoders": str(clip_dir),
            "vae": str(vae_dir),
        },
    }


_JOBS: dict[str, float] = {}
_OBJECT_INFO_CACHE: dict | None = None


def remember_job(prompt_id: str) -> None:
    _JOBS[str(prompt_id)] = time.time()



def forget_finished_job(prompt_id: str) -> None:
    _JOBS.pop(str(prompt_id), None)


def comfy_queue_busy() -> dict:
    try:
        data, _, _ = comfy_request("/queue", timeout=3)
    except Exception as exc:
        return {"ok": False, "busy": False, "running": 0, "pending": 0, "error": str(exc)}
    if not isinstance(data, dict):
        return {"ok": False, "busy": False, "running": 0, "pending": 0, "error": "neočekivani /queue"}
    running = data.get("queue_running") or []
    pending = data.get("queue_pending") or []
    n_run = len(running) if isinstance(running, list) else 0
    n_pend = len(pending) if isinstance(pending, list) else 0
    return {"ok": True, "busy": (n_run + n_pend) > 0, "running": n_run, "pending": n_pend, "error": ""}


def studio_busy_payload() -> dict:
    """Za pokretač: ne gasi se dok ComfyUI red ili naši poslovi rade."""
    queue = comfy_queue_busy()
    active = []
    for pid, started in list(_JOBS.items()):
        try:
            st = job_status(pid)
        except Exception:
            st = {"status": "running"}
        status = str(st.get("status") or "running")
        if status in {"done", "error"}:
            forget_finished_job(pid)
            continue
        active.append({"prompt_id": pid, "status": status, "started": started})
    busy = bool(queue.get("busy") or active)
    return {
        "ok": True,
        "busy": busy,
        "jobs": len(active),
        "active": active,
        "queue": {k: queue.get(k) for k in ("ok", "busy", "running", "pending", "error")},
    }


def cached_object_info() -> dict:
    global _OBJECT_INFO_CACHE
    if _OBJECT_INFO_CACHE is None:
        _OBJECT_INFO_CACHE = object_info()
    return _OBJECT_INFO_CACHE or {}


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
    classified["install"] = video_install.snapshot()
    classified["nodes_on_disk"] = {
        r["id"]: (comfy_launch.custom_nodes_dir() / r["dir"]).is_dir()
        for r in video_mod.REPOS
    }
    return classified


def build_workflow(**kwargs) -> dict:
    """Thin passthrough to image_gen.build_workflow (accepts all its kwargs)."""
    return image_gen.build_workflow(**kwargs)


def _image_identity(item: dict) -> tuple:
    return (
        str(item.get("filename") or ""),
        str(item.get("subfolder") or ""),
        str(item.get("type") or "output"),
        str(item.get("kind") or ""),
    )


def dedupe_images(images: list[dict]) -> list[dict]:
    """Makni duplikate i temp preview ako postoji konačni output.

    ComfyUI u /history često stavi iste slike i na VAEDecode/PreviewImage
    (type=temp) i na SaveImage (type=output). Za batch=2 to izgleda kao 4 slike.
    """
    unique: list[dict] = []
    seen: set[tuple] = set()
    for item in images or []:
        if not isinstance(item, dict) or not item.get("filename"):
            continue
        key = _image_identity(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    stills = [i for i in unique if not i.get("kind")]
    media = [i for i in unique if i.get("kind")]
    if any((i.get("type") or "output") == "output" for i in stills):
        stills = [i for i in stills if (i.get("type") or "output") == "output"]
    return stills + media


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
    return dedupe_images(images)


def job_status(prompt_id: str) -> dict:
    started = _JOBS.get(str(prompt_id))
    elapsed = (time.time() - started) if started else None
    ws = comfy_ws.progress_for(prompt_id)
    progress = {"value": 0.0, "max": 1.0, "indeterminate": True, "source": "none"}
    http_ok = False
    try:
        prog, _, _ = comfy_request("/progress", timeout=3)
        if isinstance(prog, dict) and (prog.get("max") or prog.get("value")):
            val = float(prog.get("value") or 0)
            mx = float(prog.get("max") or 1) or 1
            if val > 0 or mx > 1:
                progress = {"value": val, "max": mx, "indeterminate": val <= 0, "source": "http"}
                http_ok = True
    except Exception:
        pass
    if ws.get("connected") or (ws.get("value") or 0) > 0:
        val = float(ws.get("value") or 0)
        mx = float(ws.get("max") or 1) or 1
        if val > 0 or ws.get("last_type") == "progress":
            progress = {"value": val, "max": mx, "indeterminate": val <= 0, "source": "ws"}
        elif not http_ok:
            progress = {"value": 0.0, "max": 1.0, "indeterminate": True, "source": "ws"}
    hint = "Prvo pokretanje može trajati dulje."
    common = {
        "elapsed_s": elapsed,
        "ws_connected": bool(ws.get("connected")),
        "hint": hint,
    }

    try:
        data, _, _ = comfy_request("/history/" + urllib.parse.quote(prompt_id), timeout=8)
    except Exception as exc:
        return {
            "status": "running",
            "progress": progress,
            "images": [],
            "error": None,
            "note": str(exc),
            **common,
        }

    entry = None
    if isinstance(data, dict):
        entry = data.get(prompt_id)
        if entry is None and len(data) == 1:
            entry = next(iter(data.values()))
        if entry is None and "outputs" in data:
            entry = data

    if not entry:
        return {"status": "running", "progress": progress, "images": [], "error": None, **common}

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
    if ws.get("error") and not error_text:
        error_text = str(ws.get("error"))

    if error_text or status_str in {"error", "failed", "exception"}:
        return {
            "status": "error",
            "progress": {"value": 1, "max": 1, "indeterminate": False, "source": progress.get("source")},
            "images": images,
            "error": error_text or "ComfyUI je prijavio grešku pri generiranju.",
            **common,
        }

    if completed or images or status_str == "success" or ws.get("finished"):
        if images or completed or status_str == "success":
            return {
                "status": "done",
                "progress": {"value": 1, "max": 1, "indeterminate": False, "source": progress.get("source")},
                "images": images,
                "error": None,
                **common,
            }

    return {"status": "running", "progress": progress, "images": images, "error": None, **common}


def clamp_int(value, lo, hi, default):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def clamp_float(value, lo, hi, default):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))



def _optional_int(value):
    if value is None or value is False or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def plan_image_generation(
    body: dict,
    *,
    profile: dict | None = None,
    object_info: dict | None = None,
) -> dict:
    """Složi ComfyUI workflow za /api/generate (bez HTTP-a i bez reda čekanja).

    Vraća {ok, workflow, meta} ili {ok: False, status, error, ...}.
    """
    prof = resolve_generation_profile(body, profile)
    appearance = resolve_appearance(body, prof)
    scene = (body.get("prompt") or "").strip()
    if not scene:
        return {"ok": False, "status": 400, "error": "Upiši opis slike."}

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

    override = (body.get("model_type") or (prof or {}).get("model_type") or "")
    arch = image_gen.detect_model_arch(model, override)
    quality_on = body.get("quality_prefix")
    if quality_on is None:
        quality_on = inbox.get_setting("quality_prefix", "1") != "0"
    adult_term = image_gen.adult_term_for_profile(prof, appearance=appearance, scene=scene)
    if "appearance_weight" in body and body.get("appearance_weight") not in (None, ""):
        appearance_weight = character.clamp_appearance_weight(body.get("appearance_weight"))
    elif prof and prof.get("appearance_weight") not in (None, ""):
        appearance_weight = character.clamp_appearance_weight(prof.get("appearance_weight"))
    else:
        appearance_weight = character.DEFAULT_APPEARANCE_WEIGHT
    built = image_gen.build_positive_prompt(
        scene=scene,
        appearance=appearance,
        quality=bool(quality_on),
        adult_term=adult_term,
        appearance_weight=appearance_weight,
    )
    prompt = built["prompt"]

    dim_max = 2048 if arch == "krea2" else 1536
    canvas = image_gen.resolve_canvas(
        arch,
        body.get("width"),
        body.get("height"),
        output_width=body.get("output_width"),
        output_height=body.get("output_height"),
        preset_id=str(body.get("size_preset") or body.get("preset_id") or ""),
        dim_max=dim_max,
    )
    width = canvas["width"]
    height = canvas["height"]
    output_width = canvas["output_width"]
    output_height = canvas["output_height"]
    batch = clamp_int(body.get("batch"), 1, 4, 1)
    steps = clamp_int(body.get("steps"), 4, 50, image_gen.default_steps(arch))
    cfg = body.get("cfg")
    try:
        cfg = float(cfg) if cfg is not None and cfg != "" else image_gen.default_cfg(arch)
    except (TypeError, ValueError):
        cfg = image_gen.default_cfg(arch)
    hires = bool(body.get("hires"))
    if hires and arch == "sdxl" and not body.get("hires_force"):
        # dopušteno, ali UI upozorava na VRAM; ne blokiramo ako je korisnik svjesno uključio
        pass

    lock_seed = character.truthy(body.get("lock_seed"), character.truthy((prof or {}).get("lock_seed"), False))
    seed = body.get("seed")
    seed_missing = seed is None or seed == ""
    try:
        seed_negative = (not seed_missing) and int(seed) < 0
    except (TypeError, ValueError):
        seed_negative = True
    if lock_seed and (seed_missing or seed_negative):
        stored = (prof or {}).get("locked_seed")
        try:
            if stored not in (None, "", "-1", -1) and int(stored) >= 0:
                seed = int(stored)
            else:
                seed = random.randint(0, 2_147_483_647)
        except (TypeError, ValueError):
            seed = random.randint(0, 2_147_483_647)
    elif seed_missing or seed_negative:
        seed = random.randint(0, 2_147_483_647)
    else:
        seed = clamp_int(seed, 0, 2_147_483_647, random.randint(0, 2_147_483_647))

    turbo = bool(body.get("turbo"))
    if "lora" in body or "user_lora" in body:
        user_lora = (body.get("lora") or body.get("user_lora") or "").strip()
    else:
        user_lora = ((prof or {}).get("preferred_lora") or "").strip()
    if image_gen.is_turbo_lora_file(user_lora):
        user_lora = ""
    strength_src = body.get("lora_strength", body.get("user_lora_strength"))
    if strength_src in (None, "") and "lora" not in body and "user_lora" not in body and prof:
        strength_src = prof.get("preferred_lora_strength")
    default_strength = 0.8
    if prof and prof.get("preferred_lora_strength") not in (None, "") and not ("lora_strength" in body or "user_lora_strength" in body):
        default_strength = clamp_float(prof.get("preferred_lora_strength"), 0.0, 1.5, 0.8)
    user_lora_strength = clamp_float(strength_src, 0.0, 1.5, default_strength)
    sampler_name, scheduler = image_gen.default_sampler(arch)

    if arch == "krea2":
        err = image_gen.krea2_support_error(object_info)
        if err:
            return {"ok": False, "status": 400, "error": err, "need": "comfy-update", "arch": "krea2"}
        st = krea2_file_status()
        if not st["ready"]:
            missing = ", ".join(st["missing"])
            return {
                "ok": False,
                "status": 400,
                "error": (
                    "Nedostaju datoteke za Krea 2 Turbo. Otvori karticu Modeli i preuzmi paket "
                    "„Krea 2 Turbo (FP8)”. Nedostaje: " + missing
                ),
                "need": "krea2-files",
                "missing": st["missing"],
            }
        spec = image_gen.KREA2_TURBO
        steps = int(spec["steps"])
        cfg = float(spec["cfg"])
        sampler_name = spec["sampler_name"]
        scheduler = spec["scheduler"]
        hires = False
        user_lora = ""
        turbo = False  # ne miješaj Hyper-SDXL LoRA; meta.krea_turbo označava način
        krea_turbo = True
    else:
        krea_turbo = False

    if user_lora and arch != "krea2" and not image_gen.lora_available(user_lora):
        return {
            "ok": False,
            "status": 400,
            "error": "Odabrana LoRA nije pronađena u models/loras.",
            "need": "lora",
        }

    if turbo and arch != "krea2":
        if arch != "sdxl":
            return {
                "ok": False,
                "status": 400,
                "error": "Turbo (8 koraka) radi samo sa SDXL modelima (npr. RealVisXL).",
                "need": "sdxl",
            }
        spec = image_gen.TURBO_SDXL
        if not image_gen.lora_available(spec["lora_filename"]):
            return {
                "ok": False,
                "status": 400,
                "error": "Turbo LoRA još nije preuzet. Otvori karticu Modeli i preuzmi Hyper-SDXL Turbo (8 koraka).",
                "need_lora": spec["id"],
            }
        steps = spec["steps"]
        cfg = spec["cfg"]
        sampler_name = spec["sampler_name"]
        scheduler = spec["scheduler"]
        hires = False

    if "ipadapter_weight" in body and body.get("ipadapter_weight") not in (None, ""):
        ipadapter_weight = character.clamp_ipadapter_weight(body.get("ipadapter_weight"))
    elif prof and prof.get("ipadapter_weight") not in (None, ""):
        ipadapter_weight = character.clamp_ipadapter_weight(prof.get("ipadapter_weight"))
    else:
        ipadapter_weight = character.DEFAULT_IPADAPTER_WEIGHT

    face_detailer = character.truthy(body.get("face_detailer"), character.truthy((prof or {}).get("face_detailer"), False))
    if arch == "krea2":
        face_detailer = False

    ipadapter_images: list[str] = []
    if arch != "krea2":
        staged = body.get("ipadapter_images") or body.get("ref_images")
        if isinstance(staged, list) and staged and all(isinstance(x, str) and x.strip() for x in staged):
            ipadapter_images = [x.replace("\\", "/").strip() for x in staged][: character.MAX_REFS]
        else:
            paths = []
            if prof and prof.get("id") is not None:
                try:
                    paths = inbox.reference_paths(int(prof["id"]))
                except Exception:
                    paths = []
            if paths:
                err = character.ipadapter_error(arch, object_info, want_refs=True)
                if err:
                    return err
                try:
                    ipadapter_images = character.stage_reference_images(paths, prefix=f"studio_refs/p{int(prof['id'])}")
                except Exception as exc:
                    return {"ok": False, "status": 500, "error": f"Ne mogu pripremiti referentne slike: {exc}"}

        if ipadapter_images:
            err = character.ipadapter_error(arch, object_info, want_refs=True)
            if err:
                return err

    if face_detailer:
        err = character.face_detailer_error(object_info, want=True)
        if err:
            return err

    workflow = build_workflow(
        prompt=prompt,
        negative=negative,
        model=model,
        width=width,
        height=height,
        batch=batch,
        seed=seed,
        steps=steps,
        cfg=cfg,
        sampler_name=sampler_name,
        scheduler=scheduler,
        arch=arch,
        hires=hires,
        object_info=object_info if object_info is not None else {},
        user_lora=user_lora if arch != "krea2" else "",
        user_lora_strength=user_lora_strength,
        turbo=turbo,
        prompt_chunks=None if arch == "krea2" else built["chunks"],
        ipadapter_images=ipadapter_images if arch != "krea2" else [],
        ipadapter_weight=ipadapter_weight,
        face_detailer=bool(face_detailer) and arch != "krea2",
        output_width=output_width,
        output_height=output_height,
    )
    return {
        "ok": True,
        "workflow": workflow,
        "built": built,
        "meta": {
            "ok": True,
            "seed": seed,
            "model": model,
            "width": output_width,
            "height": output_height,
            "gen_width": width,
            "gen_height": height,
            "output_width": output_width,
            "output_height": output_height,
            "size_preset": canvas.get("preset_id") or "",
            "batch": batch,
            "steps": steps,
            "cfg": cfg,
            "arch": arch,
            "hires": hires,
            "turbo": bool(turbo or krea_turbo),
            "krea_turbo": krea_turbo,
            "lora": user_lora if arch != "krea2" else "",
            "lora_strength": user_lora_strength if (arch != "krea2" and user_lora) else None,
            "appearance_weight": appearance_weight,
            "ipadapter": bool(ipadapter_images) and arch != "krea2",
            "ipadapter_weight": ipadapter_weight if (ipadapter_images and arch != "krea2") else None,
            "ipadapter_images": ipadapter_images if arch != "krea2" else [],
            "face_detailer": bool(face_detailer) and arch != "krea2",
            "lock_seed": bool(lock_seed),
            "prompt": prompt,
            "tokens": built["tokens"],
            "token_warn": built["warn"],
            "token_limit": built["limit"],
            "kind": "image",
        },
    }


def compose_prompt(persona: str, prompt: str) -> str:
    persona = (persona or "").strip()
    prompt = (prompt or "").strip()
    if persona and prompt:
        if prompt.lower().startswith(persona.lower()):
            return prompt
        return f"{persona}, {prompt}"
    return persona or prompt



def stage_init_image(info: dict | str) -> str:
    """Skini sliku iz ComfyUI outputa/uploada u input mapu i vrati ime za LoadImage."""
    if isinstance(info, str):
        name = Path(info).name
        src_guess = comfy_launch.comfy_dir() / "output" / name
        if src_guess.is_file():
            dest = comfy_launch.comfy_dir() / "input"
            dest.mkdir(parents=True, exist_ok=True)
            target = dest / name
            if src_guess.resolve() != target.resolve():
                import shutil
                shutil.copy2(src_guess, target)
            return name
        return name
    filename = (info.get("filename") or "").strip()
    if not filename:
        raise ValueError("Nedostaje ime referentne slike.")
    typ = (info.get("type") or "output").strip() or "output"
    sub = (info.get("subfolder") or "").strip()
    qs = urllib.parse.urlencode({"filename": filename, "subfolder": sub, "type": typ})
    raw, _, _ = comfy_request("/view?" + qs, timeout=30)
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        raise RuntimeError("Ne mogu dohvatiti referentnu sliku iz ComfyUI-ja.")
    dest = comfy_launch.comfy_dir() / "input"
    dest.mkdir(parents=True, exist_ok=True)
    safe = Path(filename).name
    (dest / safe).write_bytes(bytes(raw))
    return safe


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

        if path in ("/app.ico", "/favicon.ico"):
            ico = ROOT / "app.ico"
            if not ico.is_file():
                self._send(404, b"", "image/x-icon")
                return
            self._send(200, ico.read_bytes(), "image/x-icon")
            return

        if path in ("/webhook/instagram", "/api/ig/webhook"):
            self._ig_verify(query)
            return

        if path == "/api/status":
            ok, msg = comfy_up()
            self._json(200, {"ok": ok, "message": msg, "comfy": COMFY_BASE})
            return

        if path == "/api/heartbeat":
            hb = app_session.read_heartbeat(inbox.DATA_DIR) or {}
            self._json(200, {"ok": True, "heartbeat": hb})
            return

        if path == "/api/busy":
            self._json(200, studio_busy_payload())
            return

        if path == "/api/state":
            ok, msg = comfy_up()
            state = inbox.app_state()
            state["comfy"] = {"ok": ok, "message": msg, "url": COMFY_BASE}
            state["version"] = updater.load_version(Path(__file__).resolve().parent).get("version") or "0.0.0"
            state["app_dir"] = str(Path(__file__).resolve().parent)
            state["update"] = updater.read_update_result(inbox.DATA_DIR)
            state["presets"] = {"sd15": image_gen.SD15_PRESETS, "sdxl": image_gen.SDXL_PRESETS}
            state["lowvram_note"] = image_gen.LOWVRAM_NOTE
            state["quality_prefix_text"] = QUALITY_PREFIX
            try:
                state["character"] = character_install.current_status(cached_object_info())
            except Exception:
                state["character"] = {"ok": True, "capabilities": character.capabilities({})}
            self._json(200, state)
            return

        if path == "/api/update/check":
            self._update_check()
            return

        if path == "/api/models/installed":
            selected = (query.get("selected") or [""])[0]
            payload = installed_models.list_installed(selected=selected or None)
            payload["curated"] = installed_models.annotate_curated(model_download.CURATED, payload)
            self._json(200, payload)
            return

        if path == "/api/models":
            self._models_payload()
            return

        if path == "/api/loras":
            self._loras_payload()
            return

        if path == "/api/models/download":
            self._json(200, {"ok": True, "download": model_download.snapshot(), "curated": model_download.CURATED})
            return

        if path == "/api/profiles":
            self._json(200, {"ok": True, "profiles": inbox.list_profiles(), "active_profile_id": inbox.active_profile_id()})
            return

        if path == "/api/character" or path == "/api/character/status":
            self._json(200, character_install.current_status(cached_object_info()))
            return

        if path == "/api/character/install":
            self._json(200, {"ok": True, "install": character_install.snapshot()})
            return

        m = re.fullmatch(r"/api/profiles/(\d+)/refs/(\d+)", path)
        if m:
            variant = (query.get("variant") or query.get("v") or ["thumb"])[0]
            self._serve_reference(int(m.group(1)), index=int(m.group(2)), variant=variant)
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

        if path == "/api/video/install":
            self._json(200, {"ok": True, **video_install.current_status(cached_object_info() if comfy_up()[0] else {})})
            return

        if path == "/api/prompt/preview":
            self._json(400, {"ok": False, "error": "Koristi POST."})
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

    def _serve_reference(self, pid: int, index: int = 0, variant: str = "thumb") -> None:
        path = inbox.reference_image_path(pid, index, variant=variant or "thumb")
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

        if path == "/api/heartbeat":
            qs = urllib.parse.parse_qs(parsed.query)
            bye = "bye" in qs or (qs.get("bye") or [""])[0] in {"1", "true", "yes"}
            if raw:
                try:
                    extra = self._read_json_from(raw)
                    if isinstance(extra, dict) and extra.get("bye"):
                        bye = True
                except Exception:
                    pass
            hb = app_session.touch_heartbeat(inbox.DATA_DIR, bye=bye)
            self._json(200, {"ok": True, "heartbeat": hb})
            return

        if path == "/api/shutdown":
            self._json(200, {"ok": True, "message": "Gasim poslužitelj."})
            _schedule_studio_exit()
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

        if path == "/api/video/install":
            try:
                info = video_install.start_install(include_sd15=body.get("include_sd15", True) is not False)
            except RuntimeError as exc:
                self._json(400, {"ok": False, "error": str(exc), "install": video_install.snapshot()})
                return
            self._json(200, {"ok": True, "install": info})
            return

        if path == "/api/prompt/preview":
            self._json(200, {"ok": True, **self._preview_prompt(body)})
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

        if path == "/api/character/install":
            kind = (body.get("kind") or body.get("what") or "ipadapter")
            try:
                snap = character_install.start_install(str(kind))
            except ValueError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
                return
            except RuntimeError as exc:
                self._json(409, {"ok": False, "error": str(exc), "install": character_install.snapshot()})
                return
            self._json(200, {"ok": True, "install": snap})
            return

        m = re.fullmatch(r"/api/profiles/(\d+)/refs", path)
        if m:
            self._upload_reference(int(m.group(1)), body)
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

        if path == "/api/models/download":
            self._start_model_download(body)
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
        zip_path = Path(downloaded["zip_path"])
        updater.updater_log(inbox.DATA_DIR, f"UI apply preuzeo {info.get('latest')}, spawn helper")
        updater.spawn_apply_helper(ROOT, inbox.DATA_DIR, zip_path)
        _schedule_studio_exit()
        self._json(200, {
            "ok": True,
            "applied": False,
            "restarting": True,
            "pending": True,
            "current": updater.load_version(Path(__file__).resolve().parent).get("version"),
            "latest": info.get("latest"),
            "message": "Paket je preuzet. Ažuriranje se sada primjenjuje u pozadini; verzija će se potvrditi s diska nakon restarta.",
        })

    def _handle_put(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        raw = self._read_body()
        try:
            body = self._read_json_from(raw) if raw else {}
        except Exception:
            self._json(400, {"ok": False, "error": "Tijelo zahtjeva nije valjani JSON."})
            return
        mref = re.fullmatch(r"/api/profiles/(\d+)/refs", parsed.path)
        if mref:
            if not isinstance(body, dict):
                self._json(400, {"ok": False, "error": "Tijelo zahtjeva nije objekt."})
                return
            try:
                pid = int(mref.group(1))
                items = inbox.update_reference_items(
                    pid,
                    order=body.get("order") or body.get("refs") or None,
                    enabled=body.get("enabled") if "enabled" in body else body.get("flags"),
                    index=_optional_int(body.get("index") if "index" in body else body.get("i")),
                    items=body.get("items") if isinstance(body.get("items"), list) else None,
                )
                refs = [it["path"] for it in items]
            except KeyError as exc:
                self._json(404, {"ok": False, "error": str(exc)})
                return
            except ValueError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
                return
            self._json(200, {"ok": True, "profile": inbox.get_profile(pid), "reference_images": refs, "reference_items": items})
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
        if parsed.path == "/api/models/installed":
            self._delete_installed_model()
            return
        mref = re.fullmatch(r"/api/profiles/(\d+)/refs/(\d+)", parsed.path)
        if mref:
            try:
                refs = inbox.delete_reference_image(int(mref.group(1)), index=int(mref.group(2)))
            except KeyError as exc:
                self._json(404, {"ok": False, "error": str(exc)})
                return
            except ValueError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
                return
            pid = int(mref.group(1))
            self._json(200, {"ok": True, "profile": inbox.get_profile(pid), "reference_images": refs})
            return
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

    def _delete_installed_model(self) -> None:
        raw = self._read_body()
        try:
            body = self._read_json_from(raw) if raw else {}
        except json.JSONDecodeError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        rel = (body.get("path") or body.get("rel") or (query.get("path") or [""])[0] or "").strip()
        folder = (body.get("folder") or (query.get("folder") or [""])[0] or "").strip()
        name = (body.get("name") or body.get("filename") or (query.get("name") or [""])[0] or "").strip()
        selected = (body.get("selected") or (query.get("selected") or [""])[0] or "").strip()
        try:
            result = installed_models.delete_model(rel or None, folder=folder or None, name=name or None, selected=selected or None)
        except installed_models.ModelPathError as exc:
            code = 404 if getattr(exc, "code", "") == "missing" else 400
            self._json(code, {"ok": False, "error": str(exc)})
            return
        if not result.get("ok"):
            status = 409 if result.get("locked") else 400
            self._json(status, result)
            return
        self._json(200, result)

    def _upload_reference(self, pid: int, body: dict) -> None:
        def _one(entry, default_ext="jpg"):
            if isinstance(entry, str):
                b64, ext, header = entry, default_ext, ""
            elif isinstance(entry, dict):
                b64 = entry.get("image_b64") or entry.get("image") or ""
                ext = (entry.get("ext") or default_ext).lstrip(".")
                header = ""
            else:
                return None, None, "Neispravan zapis slike."
            if isinstance(b64, str) and b64.startswith("data:"):
                try:
                    header, b64 = b64.split(",", 1)
                except ValueError:
                    return None, None, "Neispravan data-URL."
                ext = "jpg"
                if "png" in header:
                    ext = "png"
                elif "webp" in header:
                    ext = "webp"
            if not b64:
                return None, None, "Nedostaje slika."
            try:
                data = base64.b64decode(b64, validate=False)
            except Exception:
                return None, None, "Slika nije valjani base64."
            if len(data) < 20 or len(data) > 8_000_000:
                return None, None, "Slika je prazna ili veća od 8 MB."
            return data, ext, None

        files = []
        raw_list = body.get("images") or body.get("files") or body.get("refs")
        if isinstance(raw_list, list) and raw_list and not isinstance(raw_list[0], (int, float)):
            # lista slika; ignoriraj ako je to zapravo lista putanja (reorder)
            looks_image = False
            for item in raw_list:
                if isinstance(item, dict) and (item.get("image") or item.get("image_b64")):
                    looks_image = True
                    break
                if isinstance(item, str) and (item.startswith("data:") or len(item) > 200):
                    looks_image = True
                    break
            if looks_image:
                for item in raw_list:
                    data, ext, err = _one(item, (body.get("ext") or "jpg").lstrip("."))
                    if err:
                        self._json(400, {"ok": False, "error": err})
                        return
                    files.append((data, ext))
        if not files:
            data, ext, err = _one(body, (body.get("ext") or "jpg").lstrip("."))
            if err and not raw_list:
                self._json(400, {"ok": False, "error": err})
                return
            if not err and data:
                files.append((data, ext))
        if not files:
            self._json(400, {"ok": False, "error": "Nedostaje slika."})
            return
        try:
            items = inbox.add_reference_images(pid, files)
        except KeyError as exc:
            self._json(404, {"ok": False, "error": str(exc)})
            return
        except ValueError as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return
        refs = [it["path"] for it in items]
        idx = max(0, len(refs) - 1)
        prof = inbox.get_profile(pid)
        self._json(200, {
            "ok": True,
            "reference_image": refs[0] if refs else "",
            "reference_images": refs,
            "reference_items": (prof or {}).get("reference_items") or items,
            "url": f"/api/profiles/{pid}/refs/{idx}",
            "profile": prof,
        })

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

        active = inbox.get_profile(inbox.active_profile_id())
        result = plan_image_generation(
            body,
            profile=resolve_generation_profile(body, active),
            object_info=cached_object_info(),
        )
        if not result.get("ok"):
            payload = {k: v for k, v in result.items() if k not in {"workflow", "built", "status"}}
            self._json(int(result.get("status") or 400), payload)
            return
        self._queue_prompt(result["workflow"], result["meta"])

    def _preview_prompt(self, body: dict) -> dict:
        active = inbox.get_profile(inbox.active_profile_id())
        prof = resolve_generation_profile(body, active)
        appearance = resolve_appearance(body, prof)
        scene = body.get("prompt") or body.get("scene") or ""
        quality_on = body.get("quality_prefix")
        if quality_on is None:
            quality_on = inbox.get_setting("quality_prefix", "1") != "0"
        adult_term = image_gen.adult_term_for_profile(prof, appearance=appearance, scene=scene)
        if "appearance_weight" in body and body.get("appearance_weight") not in (None, ""):
            appearance_weight = character.clamp_appearance_weight(body.get("appearance_weight"))
        elif prof and prof.get("appearance_weight") not in (None, ""):
            appearance_weight = character.clamp_appearance_weight(prof.get("appearance_weight"))
        else:
            appearance_weight = character.DEFAULT_APPEARANCE_WEIGHT
        return image_gen.build_positive_prompt(
            scene=scene,
            appearance=appearance,
            quality=bool(quality_on),
            adult_term=adult_term,
            appearance_weight=appearance_weight,
        )

    def _generate_video(self, body: dict) -> None:
        caps = video_capabilities()
        if not caps.get("comfy_ok"):
            self._json(503, {"ok": False, "error": caps.get("comfy_message") or caps.get("message")})
            return
        if not caps.get("ready") and not caps.get("ad_ok"):
            self._json(400, {
                "ok": False,
                "error": caps.get("message") or "Video podrška nije instalirana. Pritisni „Instaliraj video podršku”.",
                "capabilities": caps,
            })
            return
        active = inbox.get_profile(inbox.active_profile_id())
        prof = resolve_generation_profile(body, active)
        appearance = resolve_appearance(body, prof)
        scene = (body.get("prompt") or "").strip()
        quality_on = body.get("quality_prefix")
        if quality_on is None:
            quality_on = inbox.get_setting("quality_prefix", "1") != "0"
        adult_term = image_gen.adult_term_for_profile(prof, appearance=appearance, scene=scene or "subtle natural movement, gentle motion")
        built = image_gen.build_positive_prompt(
            scene=scene or "subtle natural movement, gentle motion",
            appearance=appearance,
            quality=bool(quality_on),
            adult_term=adult_term,
        )
        prompt = built["prompt"]
        if not scene and not body.get("init_image") and not body.get("image"):
            self._json(400, {"ok": False, "error": "Upiši opis klipa ili odaberi sliku."})
            return
        negative = (body.get("negative") or "").strip()
        if not negative and prof:
            negative = (prof.get("negative_prompt") or "").strip()
        if not negative:
            negative = DEFAULT_NEGATIVE
        model = (body.get("model") or "").strip()
        sd15s = caps.get("sd15_models") or video_mod.list_sd15_models()
        model = video_mod.pick_sd15_model(model, sd15s)
        if not model or image_gen.detect_model_arch(model) != "sd15":
            self._json(400, {
                "ok": False,
                "error": "Za video treba SD 1.5 model (npr. Realistic Vision). Pritisni „Instaliraj video podršku” ili preuzmi ga u Modelima.",
                "capabilities": caps,
            })
            return
        rec = caps.get("recommend") or video_mod.recommend_settings(8)
        width = clamp_int(body.get("width"), 256, 768, rec["width"])
        height = clamp_int(body.get("height"), 256, 768, rec["height"])
        frames = clamp_int(body.get("frames"), 8, 24, rec["frames"])
        steps = clamp_int(body.get("steps"), 8, 30, rec["steps"])
        fps = clamp_int(body.get("fps"), 4, 16, rec.get("fps") or 8)
        seed = body.get("seed")
        if seed is None or seed == "" or int(seed) < 0:
            seed = random.randint(0, 2_147_483_647)
        else:
            seed = clamp_int(seed, 0, 2_147_483_647, random.randint(0, 2_147_483_647))
        init_name = ""
        init_info = body.get("init_image") or body.get("image")
        if init_info:
            try:
                init_name = stage_init_image(init_info)
            except Exception as exc:
                self._json(400, {"ok": False, "error": f"Referentna slika nije spremna: {exc}"})
                return
        info = cached_object_info()
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
            fps=fps,
            init_image=init_name,
            motion_model=caps.get("motion_model") or "",
            object_info=info,
            prompt_chunks=built["chunks"],
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
            "fps": fps,
            "prompt": prompt,
            "kind": "video",
            "warning": note,
            "init_image": init_name,
            "tokens": built["tokens"],
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
        remember_job(str(prompt_id))
        try:
            comfy_ws.start_watcher(COMFY_BASE, CLIENT_ID)
        except Exception:
            pass
        extra = dict(extra)
        extra["prompt_id"] = prompt_id
        extra["hint"] = "Prvo pokretanje može trajati dulje."
        self._json(200, extra)


    def _loras_payload(self) -> None:
        entries = lora_entries()
        self._json(200, {
            "ok": True,
            "loras": entries,
            "loras_dir": str(comfy_launch.loras_dir()),
            "excluded": [image_gen.TURBO_SDXL["lora_filename"]],
        })

    def _models_payload(self) -> None:
        ok, msg = comfy_up()
        names = list_models() if ok else []
        models = model_entries(names)
        default = DEFAULT_MODEL
        name_list = [m["name"] for m in models]
        if default not in name_list and name_list:
            default = name_list[0]
        prof = inbox.get_profile(inbox.active_profile_id())
        if prof and prof.get("preferred_model") and prof["preferred_model"] in name_list:
            default = prof["preferred_model"]
        default_arch = image_gen.detect_model_arch(
            default, (prof or {}).get("model_type") if prof else ""
        )
        installed = installed_models.list_installed(selected=default)
        payload = {
            "ok": ok,
            "error": None if ok else msg,
            "models": name_list,
            "models_info": models,
            "default": default,
            "default_arch": default_arch,
            "presets": {
                "sd15": image_gen.SD15_PRESETS,
                "sdxl": image_gen.SDXL_PRESETS,
                "krea2": image_gen.KREA2_PRESETS,
            },
            "curated": installed_models.annotate_curated(model_download.CURATED, installed),
            "installed": installed,
            "download": model_download.snapshot(),
            "checkpoints_dir": str(comfy_launch.checkpoints_dir()),
            "diffusion_models_dir": str(comfy_launch.diffusion_models_dir()),
            "text_encoders_dir": str(comfy_launch.text_encoders_dir()),
            "vae_dir": str(comfy_launch.vae_dir()),
            "krea2": image_gen.KREA2_TURBO,
            "krea2_files": krea2_file_status(),
            "loras_dir": str(comfy_launch.loras_dir()),
            "loras": image_gen.list_loras(),
            "loras_info": lora_entries(),
            "turbo": image_gen.TURBO_SDXL,
            "turbo_ready": image_gen.lora_available(image_gen.TURBO_SDXL["lora_filename"]),
            "character": character_install.current_status(cached_object_info() if ok else {}),
            "lowvram_note": image_gen.LOWVRAM_NOTE,
            "triton_note": (
                "Triton test na ovom PC-u pada jer clang ne nalazi stdio.h (nema Visual Studio / Windows SDK). "
                "Popravak (Build Tools + SDK) možda upali pokoje jezgre, ali na ZLUDA to nije ključno za brzinu. "
                "Pravi dobitak je Turbo LoRA (8 koraka)."
            ),
        }
        self._json(200, payload)

    def _start_model_download(self, body: dict) -> None:
        curated_id = (body.get("id") or body.get("curated") or "").strip()
        url = (body.get("url") or "").strip()
        filename = (body.get("filename") or "").strip()
        dest_dir = None
        if body.get("kind"):
            dest_dir = model_download.dest_dir_for(str(body.get("kind")))
        if curated_id:
            item = next((c for c in model_download.CURATED if c["id"] == curated_id), None)
            if not item:
                self._json(400, {"ok": False, "error": "Nepoznat predloženi model."})
                return
            try:
                info = model_download.start_curated(item)
            except (ValueError, RuntimeError) as exc:
                self._json(400, {"ok": False, "error": str(exc)})
                return
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})
                return
            self._json(200, {"ok": True, "download": info})
            return
        try:
            info = model_download.start_download(url, filename or None, dest_dir=dest_dir)
        except (ValueError, RuntimeError) as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return
        except Exception as exc:
            self._json(500, {"ok": False, "error": str(exc)})
            return
        self._json(200, {"ok": True, "download": info})


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


def _schedule_studio_exit() -> None:
    """Ugasi ovaj poslužitelj da helper može zamijeniti datoteke."""
    def _later():
        time.sleep(0.6)
        httpd = _httpd
        if httpd is not None:
            try:
                httpd.shutdown()
            except Exception:
                os._exit(0)
        else:
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
    try:
        comfy_ws.start_watcher(COMFY_BASE, CLIENT_ID)
    except Exception:
        pass
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
        try:
            comfy_ws.stop_watcher()
        except Exception:
            pass
        httpd.server_close()
        _clear_pid()
    return 0


if __name__ == "__main__":
    sys.exit(main())
