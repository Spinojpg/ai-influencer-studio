#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Popis i sigurno brisanje datoteka u ComfyUI models/* mapama."""

from __future__ import annotations

import errno
import os
from pathlib import Path

import comfy_launch
import image_gen
import model_download

ALLOWED_SUFFIXES = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf"}
MAX_WALK_DEPTH = 5

FOLDER_LABELS = {
    "checkpoints": "Checkpointi",
    "diffusion_models": "Diffusion modeli",
    "text_encoders": "Text encoderi",
    "vae": "VAE",
    "loras": "LoRA",
    "animatediff_models": "AnimateDiff",
    "clip": "CLIP",
    "clip_vision": "CLIP Vision",
    "controlnet": "ControlNet",
    "embeddings": "Embeddings",
    "unet": "UNET",
    "upscale_models": "Upscale",
    "hypernetworks": "Hypernetworks",
    "photomaker": "PhotoMaker",
    "style_models": "Style modeli",
    "ipadapter": "IP-Adapter",
    "insightface": "InsightFace",
    "gligen": "GLIGEN",
    "vae_approx": "VAE approx",
}

KIND_TO_FOLDER = {
    "checkpoint": "checkpoints",
    "checkpoints": "checkpoints",
    "lora": "loras",
    "loras": "loras",
    "animatediff": "animatediff_models",
    "motion": "animatediff_models",
    "animatediff_models": "animatediff_models",
    "diffusion": "diffusion_models",
    "diffusion_models": "diffusion_models",
    "unet": "diffusion_models",
    "diffusion_model": "diffusion_models",
    "text_encoder": "text_encoders",
    "text_encoders": "text_encoders",
    "clip": "text_encoders",
    "clip_name": "text_encoders",
    "vae": "vae",
    "clip_vision": "clip_vision",
    "clip-vision": "clip_vision",
    "clipvision": "clip_vision",
    "ipadapter": "ipadapter",
    "ip_adapter": "ipadapter",
    "ip-adapter": "ipadapter",
    "ultralytics": "ultralytics/bbox",
    "ultralytics_bbox": "ultralytics/bbox",
    "ultralytics-bbox": "ultralytics/bbox",
    "yolo": "ultralytics/bbox",
    "yolo_bbox": "ultralytics/bbox",
}

LOCKED_ERROR = (
    "Datoteka je zaključana jer je ComfyUI možda koristi. "
    "Pričekaj kraj generiranja ili ponovo pokreni Studio, pa pokušaj opet."
)


class ModelPathError(ValueError):
    def __init__(self, message: str, code: str = "invalid") -> None:
        super().__init__(message)
        self.code = code


def format_size(num: int | float | None) -> str:
    """Čitljiva veličina na hrvatskom (zarez kao decimalni znak)."""
    try:
        n = float(num or 0)
    except (TypeError, ValueError):
        n = 0.0
    if n < 0:
        n = 0.0
    units = ((1, "B", 0), (1024, "KB", 0), (1024**2, "MB", 1), (1024**3, "GB", 2), (1024**4, "TB", 2))
    value, unit, decimals = units[0]
    for thresh, name, dec in units:
        if n >= thresh or name == "B":
            value, unit, decimals = thresh, name, dec
        if n < thresh * 1024 or name == "TB":
            break
    amount = n / value if value else 0
    if unit == "B":
        return f"{int(round(amount))} B"
    if unit == "KB":
        decimals = 0 if amount >= 10 else 1
    elif unit == "MB":
        decimals = 0 if amount >= 10 else 1
    elif unit == "GB":
        decimals = 1 if amount < 10 else 2
    text = f"{amount:.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",") + " " + unit


def models_root() -> Path:
    return comfy_launch.models_root()


def _root_resolved() -> Path:
    return models_root().resolve()


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def normalize_rel(raw: str | None) -> str:
    text = (raw or "").strip().replace("\\", "/")
    text = text.lstrip("/")
    while "//" in text:
        text = text.replace("//", "/")
    return text


def folder_for_kind(kind: str | None) -> str:
    return KIND_TO_FOLDER.get((kind or "").strip().lower(), "checkpoints")


def required_index() -> dict[tuple[str, str], dict]:
    """(folder, lowercase name) -> {bundle, reason}."""
    items = [
        {
            "folder": "loras",
            "name": image_gen.TURBO_SDXL["lora_filename"],
            "bundle": "turbo",
            "reason": "Potrebna za Turbo način (Hyper-SDXL LoRA).",
        },
        {
            "folder": "diffusion_models",
            "name": image_gen.KREA2_UNET,
            "bundle": "krea2",
            "reason": "Potrebna za paket Krea 2 Turbo (diffusion model).",
        },
        {
            "folder": "text_encoders",
            "name": image_gen.KREA2_CLIP,
            "bundle": "krea2",
            "reason": "Potrebna za paket Krea 2 Turbo (text encoder).",
        },
        {
            "folder": "vae",
            "name": image_gen.KREA2_VAE,
            "bundle": "krea2",
            "reason": "Potrebna za paket Krea 2 Turbo (VAE).",
        },
        {
            "folder": "clip_vision",
            "name": "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
            "bundle": "ipadapter",
            "reason": "Potrebna za IP-Adapter Plus Face (CLIP Vision ViT-H).",
        },
        {
            "folder": "ipadapter",
            "name": "ip-adapter-plus-face_sdxl_vit-h.safetensors",
            "bundle": "ipadapter",
            "reason": "Potrebna za IP-Adapter Plus Face (SDXL).",
        },
        {
            "folder": "ipadapter",
            "name": "ip-adapter-plus-face_sd15.safetensors",
            "bundle": "ipadapter",
            "reason": "Potrebna za IP-Adapter Plus Face (SD 1.5).",
        },
        {
            "folder": "ultralytics/bbox",
            "name": "face_yolov8m.pt",
            "bundle": "face_detailer",
            "reason": "Potrebna za Face Detailer (detektor lica).",
        },
    ]
    out: dict[tuple[str, str], dict] = {}
    for item in items:
        out[(item["folder"], item["name"].lower())] = item
    return out


def _split_rel(rel_text: str) -> list[str]:
    if not rel_text:
        raise ModelPathError("Nedostaje putanja datoteke.")
    if rel_text.startswith("/") or (len(rel_text) >= 2 and rel_text[1] == ":"):
        raise ModelPathError("Apsolutna putanja nije dopuštena.")
    parts = [p for p in rel_text.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise ModelPathError("Neispravna putanja datoteke.")
    if len(parts) < 2:
        raise ModelPathError("Datoteka mora biti unutar podmape models (npr. checkpoints).")
    suffix = Path(parts[-1]).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ModelPathError("Dopuštene su samo datoteke .safetensors, .ckpt, .pt, .pth, .bin i .gguf.")
    return parts


def resolve_model_file(rel: str | None, *, folder: str | None = None, name: str | None = None) -> Path:
    """Vrati putanju unutar models/* spremnu za brisanje, ili podigni ModelPathError.

    Symlink čija meta nije unutar mape models se odbija. Ako je meta unutra,
    vraća se sama symlink putanja (briše se poveznica, ne tuđa datoteka).
    """
    if folder or name:
        folder_part = normalize_rel(folder or "")
        file_part = Path(normalize_rel(name or "")).name
        rel_text = "/".join(p for p in (folder_part, file_part) if p)
    else:
        rel_text = normalize_rel(rel)
    parts = _split_rel(rel_text)
    root = _root_resolved()
    candidate = models_root().joinpath(*parts)
    try:
        # Ne slijedi symlink na samoj datoteci pri provjeri roditelja.
        parent = candidate.parent
        parent_real = parent.resolve()
    except OSError as exc:
        raise ModelPathError(f"Ne mogu provjeriti putanju: {exc}") from exc
    if not _is_under(parent_real, root):
        raise ModelPathError("Putanja izlazi iz mape ComfyUI models.")
    if not candidate.exists():
        raise ModelPathError("Datoteka ne postoji.", code="missing")
    if candidate.is_symlink():
        try:
            target = candidate.resolve()
        except OSError as exc:
            raise ModelPathError(f"Ne mogu provjeriti poveznicu: {exc}") from exc
        if not target.is_file() or not _is_under(target, root):
            raise ModelPathError("Poveznica izlazi iz mape ComfyUI models.")
        if target.suffix.lower() not in ALLOWED_SUFFIXES:
            raise ModelPathError("Dopuštene su samo datoteke .safetensors, .ckpt, .pt, .pth, .bin i .gguf.")
        return candidate
    try:
        real = candidate.resolve()
    except OSError as exc:
        raise ModelPathError(f"Ne mogu provjeriti putanju: {exc}") from exc
    if not _is_under(real, root):
        raise ModelPathError("Putanja izlazi iz mape ComfyUI models.")
    if len(real.relative_to(root).parts) < 2:
        raise ModelPathError("Datoteka mora biti unutar podmape models.")
    if real.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ModelPathError("Dopuštene su samo datoteke .safetensors, .ckpt, .pt, .pth, .bin i .gguf.")
    if not real.is_file():
        raise ModelPathError("Datoteka ne postoji.", code="missing")
    return real


def _file_entry(real: Path, root: Path, selected: set[str] | None = None) -> dict | None:
    try:
        rel = real.relative_to(root)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) < 2:
        return None
    folder = parts[0]
    name = parts[-1]
    rel_posix = rel.as_posix()
    try:
        size = int(real.stat().st_size)
    except OSError:
        return None
    req = required_index().get((folder, name.lower()))
    selected = selected or set()
    is_selected = name.lower() in selected or rel_posix.lower() in selected
    return {
        "path": rel_posix,
        "name": name,
        "folder": folder,
        "folder_label": FOLDER_LABELS.get(folder, folder),
        "size": size,
        "size_label": format_size(size),
        "required": bool(req),
        "required_reason": (req or {}).get("reason") or "",
        "bundle": (req or {}).get("bundle") or None,
        "selected": is_selected,
    }


def list_installed(*, selected: str | None = None) -> dict:
    root = models_root()
    files: list[dict] = []
    total = 0
    if not root.is_dir():
        return {
            "ok": True,
            "files": [],
            "total_bytes": 0,
            "total_label": format_size(0),
            "models_root": str(root),
        }
    try:
        root_real = root.resolve()
    except OSError:
        root_real = root
    selected_names = set()
    if selected:
        for part in str(selected).replace("\\", "/").split(","):
            part = part.strip()
            if part:
                selected_names.add(part.lower())
                selected_names.add(Path(part).name.lower())

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d != "__pycache__")
        base = Path(dirpath)
        try:
            base_real = base.resolve()
        except OSError:
            dirnames[:] = []
            continue
        if not _is_under(base_real, root_real):
            dirnames[:] = []
            continue
        try:
            rel_dir = base_real.relative_to(root_real)
        except ValueError:
            dirnames[:] = []
            continue
        depth = 0 if rel_dir == Path(".") else len(rel_dir.parts)
        if depth >= MAX_WALK_DEPTH:
            dirnames[:] = []
        if rel_dir == Path("."):
            continue
        for fname in filenames:
            suffix = Path(fname).suffix.lower()
            if suffix not in ALLOWED_SUFFIXES:
                continue
            path = base / fname
            try:
                if path.is_symlink():
                    target = path.resolve()
                    if not target.is_file() or not _is_under(target, root_real):
                        continue
                    size_src = target
                else:
                    if not path.is_file():
                        continue
                    real = path.resolve()
                    if not _is_under(real, root_real):
                        continue
                    size_src = real
            except OSError:
                continue
            appear_rel = Path(*(([] if rel_dir == Path(".") else list(rel_dir.parts)) + [fname]))
            if len(appear_rel.parts) < 2:
                continue
            try:
                size = int(size_src.stat().st_size)
            except OSError:
                continue
            folder = appear_rel.parts[0]
            name = appear_rel.name
            req = required_index().get((folder, name.lower()))
            is_selected = name.lower() in selected_names or appear_rel.as_posix().lower() in selected_names
            entry = {
                "path": appear_rel.as_posix(),
                "name": name,
                "folder": folder,
                "folder_label": FOLDER_LABELS.get(folder, folder),
                "size": size,
                "size_label": format_size(size),
                "required": bool(req),
                "required_reason": (req or {}).get("reason") or "",
                "bundle": (req or {}).get("bundle") or None,
                "selected": is_selected,
            }
            files.append(entry)
            total += size

    files.sort(key=lambda e: (e["folder"].lower(), e["name"].lower(), e["path"].lower()))
    # Dedup by path in case a symlink and its target were both walked (shouldn't happen with followlinks=False).
    seen: set[str] = set()
    unique: list[dict] = []
    for item in files:
        key = item["path"].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return {
        "ok": True,
        "files": unique,
        "total_bytes": total,
        "total_label": format_size(total),
        "models_root": str(root),
    }


def annotate_curated(curated: list[dict] | None = None, installed: dict | None = None) -> list[dict]:
    installed = installed if installed is not None else list_installed()
    present_keys = {(f["folder"], f["name"].lower()) for f in installed.get("files") or []}
    present_names = {f["name"].lower() for f in installed.get("files") or []}
    out: list[dict] = []
    for raw in curated or model_download.CURATED:
        item = dict(raw)
        parts = item.get("files") or [{"filename": item.get("filename") or "", "kind": item.get("kind")}]
        statuses = []
        for part in parts:
            name = (part.get("filename") or "").strip()
            if not name:
                continue
            folder = folder_for_kind(part.get("kind") or item.get("kind"))
            found = (folder, name.lower()) in present_keys or name.lower() in present_names
            statuses.append({"filename": name, "folder": folder, "installed": found})
        item["files_status"] = statuses
        item["installed"] = bool(statuses) and all(s["installed"] for s in statuses)
        item["partial"] = any(s["installed"] for s in statuses) and not item["installed"]
        out.append(item)
    return out


def _unlink(path: Path) -> None:
    path.unlink()


def _is_lock_error(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    if not isinstance(exc, OSError):
        return False
    winerr = getattr(exc, "winerror", None)
    if winerr in {32, 33, 5}:
        return True
    return exc.errno in {errno.EACCES, errno.EPERM, errno.EBUSY, getattr(errno, "ETXTBSY", 26), getattr(errno, "EWOULDBLOCK", 11)}


def delete_model(
    rel: str | None = None,
    *,
    folder: str | None = None,
    name: str | None = None,
    selected: str | None = None,
) -> dict:
    """Obriši datoteku unutar models/*. Vraća {ok, ...} ili podigne ModelPathError / PermissionError-wrap."""
    real = resolve_model_file(rel, folder=folder, name=name)
    root = _root_resolved()
    try:
        rel_posix = real.relative_to(root).as_posix()
    except ValueError:
        raise ModelPathError("Putanja izlazi iz mape ComfyUI models.")
    entry = _file_entry(real, root, None)
    try:
        _unlink(real)
    except OSError as exc:
        if _is_lock_error(exc):
            return {
                "ok": False,
                "error": LOCKED_ERROR,
                "locked": True,
                "path": rel_posix,
                "name": real.name,
            }
        return {
            "ok": False,
            "error": f"Brisanje nije uspjelo: {exc}",
            "locked": False,
            "path": rel_posix,
            "name": real.name,
        }
    installed = list_installed(selected=selected)
    return {
        "ok": True,
        "deleted": rel_posix,
        "name": real.name,
        "folder": entry["folder"] if entry else rel_posix.split("/")[0],
        "installed": installed,
        "curated": annotate_curated(model_download.CURATED, installed),
    }
