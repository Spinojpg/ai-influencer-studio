#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Konzistentnost lika: referentne slike, IP-Adapter Plus Face, težina izgleda, Face Detailer."""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

import comfy_launch
import image_gen

MAX_REFS = 3
DEFAULT_IPADAPTER_WEIGHT = 0.8
IPADAPTER_WEIGHT_MIN = 0.6
IPADAPTER_WEIGHT_MAX = 1.0
DEFAULT_APPEARANCE_WEIGHT = 1.3
APPEARANCE_WEIGHT_MIN = 1.0
APPEARANCE_WEIGHT_MAX = 1.5

IPADAPTER_PRESET = "PLUS FACE (portraits)"
IPADAPTER_WEIGHT_TYPE = "standard"

CLIP_VISION_NAME = "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"
IPADAPTER_SDXL_NAME = "ip-adapter-plus-face_sdxl_vit-h.safetensors"
IPADAPTER_SD15_NAME = "ip-adapter-plus-face_sd15.safetensors"
FACE_YOLO_NAME = "face_yolov8m.pt"
FACE_YOLO_WIDGET = "bbox/face_yolov8m.pt"

IPADAPTER_NODE_DIR = "ComfyUI_IPAdapter_plus"
IPADAPTER_NODE_URL = "https://github.com/cubiq/ComfyUI_IPAdapter_plus.git"
IMPACT_PACK_DIR = "ComfyUI-Impact-Pack"
IMPACT_PACK_URL = "https://github.com/ltdrdata/ComfyUI-Impact-Pack.git"
IMPACT_SUBPACK_DIR = "ComfyUI-Impact-Subpack"
IMPACT_SUBPACK_URL = "https://github.com/ltdrdata/ComfyUI-Impact-Subpack.git"

IPADAPTER_NODES = ("IPAdapterUnifiedLoader", "IPAdapter")
FACE_DETAILER_NODES = ("FaceDetailer", "UltralyticsDetectorProvider")

# Konzervativno za RX 6600 (8 GB): jedan ciklus, manji guide, bez SAM-a.
FACE_DETAILER_DEFAULTS = {
    "guide_size": 384.0,
    "guide_size_for": True,
    "max_size": 768.0,
    "denoise": 0.4,
    "feather": 5,
    "noise_mask": True,
    "force_inpaint": True,
    "bbox_threshold": 0.5,
    "bbox_dilation": 10,
    "bbox_crop_factor": 3.0,
    "sam_detection_hint": "center-1",
    "sam_dilation": 0,
    "sam_threshold": 0.93,
    "sam_bbox_expansion": 0,
    "sam_mask_hint_threshold": 0.7,
    "sam_mask_hint_use_negative": "False",
    "drop_size": 10,
    "wildcard": "",
    "cycle": 1,
}


def clamp_weight(value, lo: float, hi: float, default: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def clamp_ipadapter_weight(value, default: float = DEFAULT_IPADAPTER_WEIGHT) -> float:
    # UI je 0.6–1.0; API dopušta malo širi raspon da testovi mogu stati na rub.
    return clamp_weight(value, 0.0, 1.5, default)


def clamp_appearance_weight(value, default: float = DEFAULT_APPEARANCE_WEIGHT) -> float:
    return clamp_weight(value, APPEARANCE_WEIGHT_MIN, APPEARANCE_WEIGHT_MAX, default)


def emphasize_text(text: str, weight: float) -> str:
    """Omotaj tekst kao (tekst:W), osim ako je već težinski omot ili je W=1."""
    text = (text or "").strip()
    if not text:
        return ""
    try:
        w = float(weight)
    except (TypeError, ValueError):
        w = 1.0
    if abs(w - 1.0) < 0.001:
        return text
    if re.match(r"^\(.*:\s*[\d.]+\s*\)$", text):
        return text
    return f"({text}:{w:g})"


def _exists_file(folder: Path, name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    if (folder / name).is_file():
        return True
    return name in set(comfy_launch.list_files(folder))


def _node_dir_present(dirname: str) -> bool:
    path = comfy_launch.custom_nodes_dir() / dirname
    return path.is_dir() and any(path.iterdir()) if path.is_dir() else False


def file_status() -> dict:
    clip = _exists_file(comfy_launch.clip_vision_dir(), CLIP_VISION_NAME)
    sdxl = _exists_file(comfy_launch.ipadapter_dir(), IPADAPTER_SDXL_NAME)
    sd15 = _exists_file(comfy_launch.ipadapter_dir(), IPADAPTER_SD15_NAME)
    yolo = _exists_file(comfy_launch.ultralytics_bbox_dir(), FACE_YOLO_NAME)
    missing = []
    if not clip:
        missing.append(f"{CLIP_VISION_NAME} (models/clip_vision)")
    if not sdxl:
        missing.append(f"{IPADAPTER_SDXL_NAME} (models/ipadapter)")
    if not sd15:
        missing.append(f"{IPADAPTER_SD15_NAME} (models/ipadapter)")
    return {
        "clip_vision": clip,
        "sdxl": sdxl,
        "sd15": sd15,
        "yolo": yolo,
        "ready_sdxl": clip and sdxl,
        "ready_sd15": clip and sd15,
        "ready": clip and sdxl and sd15,
        "missing": missing,
        "paths": {
            "clip_vision": str(comfy_launch.clip_vision_dir()),
            "ipadapter": str(comfy_launch.ipadapter_dir()),
            "ultralytics_bbox": str(comfy_launch.ultralytics_bbox_dir()),
        },
    }


def nodes_loaded(object_info: dict | None, names: tuple[str, ...] | list[str]) -> bool:
    return all(image_gen._node_exists(object_info, n) for n in names)


def catalog_available(object_info: dict | None) -> bool:
    return image_gen._object_info_catalog(object_info) is not None


def ipadapter_nodes_ok(object_info: dict | None) -> bool | None:
    """True/False ako je katalog poznat; None ako object_info još nije spreman."""
    if not catalog_available(object_info):
        return None
    return nodes_loaded(object_info, IPADAPTER_NODES)


def face_detailer_nodes_ok(object_info: dict | None) -> bool | None:
    if not catalog_available(object_info):
        return None
    return nodes_loaded(object_info, FACE_DETAILER_NODES)


def capabilities(object_info: dict | None = None) -> dict:
    files = file_status()
    ipa_nodes = ipadapter_nodes_ok(object_info)
    face_nodes = face_detailer_nodes_ok(object_info)
    ipa_dir = _node_dir_present(IPADAPTER_NODE_DIR)
    impact_dir = _node_dir_present(IMPACT_PACK_DIR)
    subpack_dir = _node_dir_present(IMPACT_SUBPACK_DIR)

    if ipa_nodes is True and files["ready"]:
        ipa_msg = "IP-Adapter Plus Face je spreman za SDXL i SD 1.5."
    elif ipa_nodes is True and (files["ready_sdxl"] or files["ready_sd15"]):
        missing = ", ".join(files["missing"])
        ipa_msg = "Čvorovi su tu, ali nedostaju datoteke: " + missing + ". Preuzmi paket u kartici Modeli."
    elif ipa_dir and ipa_nodes is False:
        ipa_msg = (
            "Čvor ComfyUI_IPAdapter_plus je na disku, ali ComfyUI ga još nije učitao. "
            "Zatvori Studio i ponovo ga pokreni."
        )
    elif ipa_nodes is False or not ipa_dir:
        ipa_msg = (
            "Za referentne slike lica treba čvor ComfyUI_IPAdapter_plus i paket modela "
            "(CLIP Vision + Plus Face). Pritisni „Instaliraj IP-Adapter” u kartici Modeli. Treba Git."
        )
    else:
        ipa_msg = "Provjeravam IP-Adapter podršku…"

    if face_nodes is True and files["yolo"]:
        face_msg = (
            "Face Detailer je spreman. Na RX 6600 (8 GB) ostavi ga isključenim osim ako želiš "
            "dodatni prolaz po licu (sporije, više VRAM-a)."
        )
    elif (impact_dir or subpack_dir) and face_nodes is False:
        face_msg = (
            "Čvorovi Impact Packa su na disku, ali ComfyUI ih još nije učitao. "
            "Ponovo pokreni Studio. Ako se ne pojave, instalacija možda nije uspjela — vidi data\\logs\\character.log."
        )
    elif face_nodes is True and not files["yolo"]:
        face_msg = "Čvorovi su tu, ali nedostaje face_yolov8m.pt. Preuzmi ga u kartici Modeli (Face Detailer)."
    else:
        face_msg = (
            "Face Detailer je opcionalan (Impact Pack + Subpack + face_yolov8m.pt). "
            "Po zadanom je isključen jer na 8 GB VRAM-a može biti tijesan. "
            "Ako instalacija ne uspije, opcija ostaje skrivena."
        )

    return {
        "ipadapter": {
            "nodes": ipa_nodes,
            "nodes_on_disk": ipa_dir,
            "files": {
                "clip_vision": files["clip_vision"],
                "sdxl": files["sdxl"],
                "sd15": files["sd15"],
                "ready_sdxl": files["ready_sdxl"],
                "ready_sd15": files["ready_sd15"],
                "ready": files["ready"],
                "missing": files["missing"],
            },
            "ready": bool(ipa_nodes is not False and (files["ready_sdxl"] or files["ready_sd15"])),
            "preset": IPADAPTER_PRESET,
            "message": ipa_msg,
        },
        "face_detailer": {
            "nodes": face_nodes,
            "nodes_on_disk": impact_dir and subpack_dir,
            "model": files["yolo"],
            "ready": bool(face_nodes is not False and files["yolo"]),
            "message": face_msg,
        },
        "max_refs": MAX_REFS,
        "defaults": {
            "ipadapter_weight": DEFAULT_IPADAPTER_WEIGHT,
            "appearance_weight": DEFAULT_APPEARANCE_WEIGHT,
        },
    }


def ipadapter_error(arch: str, object_info: dict | None = None, *, want_refs: bool = True) -> dict | None:
    """Poruka ako korisnik ima referentne slike, a podrška nije spremna. None ako je OK ili ne treba."""
    if not want_refs:
        return None
    if (arch or "").lower() in {"krea2", "krea"}:
        return None
    caps = capabilities(object_info)
    ipa = caps["ipadapter"]
    files = ipa["files"]
    nodes = ipa["nodes"]
    if nodes is False:
        return {
            "ok": False,
            "status": 400,
            "need": "ipadapter-nodes",
            "error": ipa["message"],
        }
    if arch == "sdxl" and not files["ready_sdxl"]:
        return {
            "ok": False,
            "status": 400,
            "need": "ipadapter-files",
            "error": (
                "Referentne slike lica trebaju paket IP-Adapter Plus Face. "
                "Otvori karticu Modeli i preuzmi „IP-Adapter Plus Face”, ili pritisni "
                "„Instaliraj IP-Adapter”. Nedostaje: " + ", ".join(files["missing"])
            ),
            "missing": files["missing"],
        }
    if arch == "sd15" and not files["ready_sd15"]:
        return {
            "ok": False,
            "status": 400,
            "need": "ipadapter-files",
            "error": (
                "Referentne slike lica za SD 1.5 trebaju CLIP Vision i "
                f"{IPADAPTER_SD15_NAME}. Preuzmi paket „IP-Adapter Plus Face” u kartici Modeli. "
                "Nedostaje: " + ", ".join(files["missing"])
            ),
            "missing": files["missing"],
        }
    if not files["ready_sdxl"] and not files["ready_sd15"]:
        return {
            "ok": False,
            "status": 400,
            "need": "ipadapter-files",
            "error": (
                "Nedostaju datoteke za IP-Adapter Plus Face. Preuzmi paket u kartici Modeli. "
                "Nedostaje: " + ", ".join(files["missing"])
            ),
            "missing": files["missing"],
        }
    return None


def face_detailer_error(object_info: dict | None = None, *, want: bool = True) -> dict | None:
    if not want:
        return None
    caps = capabilities(object_info)
    face = caps["face_detailer"]
    if face["nodes"] is False:
        return {
            "ok": False,
            "status": 400,
            "need": "face-detailer-nodes",
            "error": (
                "Face Detailer nije dostupan: čvorovi ComfyUI-Impact-Pack / Impact-Subpack nisu učitani. "
                + face["message"]
            ),
        }
    if not face["model"]:
        return {
            "ok": False,
            "status": 400,
            "need": "face-detailer-model",
            "error": (
                "Face Detailer treba detektor lica face_yolov8m.pt u models/ultralytics/bbox. "
                "Preuzmi ga u kartici Modeli (Face Detailer) ili pritisni „Instaliraj Face Detailer”."
            ),
        }
    return None


def stage_reference_images(paths: list[Path | str], *, prefix: str = "studio_refs") -> list[str]:
    """Kopiraj referentne slike u ComfyUI input/studio_refs/ i vrati imena za LoadImage."""
    out: list[str] = []
    dest_root = comfy_launch.input_dir() / prefix
    dest_root.mkdir(parents=True, exist_ok=True)
    for i, raw in enumerate(list(paths)[:MAX_REFS], start=1):
        src = Path(raw)
        if not src.is_file():
            continue
        ext = src.suffix.lower() if src.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} else ".png"
        digest = hashlib.sha1(str(src.resolve()).encode("utf-8", "replace")).hexdigest()[:10]
        name = f"{prefix}/p{digest}_{i}{ext}"
        dest = comfy_launch.input_dir() / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.is_file() or dest.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dest)
        out.append(name.replace("\\", "/"))
    return out


def _batch_images(wf: dict, image_refs: list[list], start_id: int = 83) -> list:
    """Spoji više IMAGE izlaza preko ImageBatch (ugniježđeno za 3 slike)."""
    if not image_refs:
        raise ValueError("Nema slika za ImageBatch.")
    if len(image_refs) == 1:
        return image_refs[0]
    current = image_refs[0]
    nid = start_id
    for nxt in image_refs[1:]:
        wf[str(nid)] = {
            "class_type": "ImageBatch",
            "inputs": {"image1": current, "image2": nxt},
        }
        current = [str(nid), 0]
        nid += 1
    return current


def apply_ipadapter_to_workflow(
    wf: dict,
    model_ref: list,
    image_names: list[str],
    *,
    weight: float = DEFAULT_IPADAPTER_WEIGHT,
    object_info: dict | None = None,
) -> list:
    """Dodaj LoadImage (+ ImageBatch) + UnifiedLoader + IPAdapter. Vrati novi MODEL ref.

    CLIP se ne mijenja. InsightFace se ne koristi (PLUS FACE preset).
    """
    names = [n for n in (image_names or []) if str(n).strip()][:MAX_REFS]
    if not names:
        return model_ref
    _ = object_info  # rezervirano za buduće usklađivanje widgeta
    load_ids = (80, 81, 82)
    image_refs: list[list] = []
    for i, name in enumerate(names):
        nid = str(load_ids[i] if i < len(load_ids) else 80 + i)
        wf[nid] = {
            "class_type": "LoadImage",
            "inputs": {"image": str(name).replace("\\", "/")},
        }
        image_refs.append([nid, 0])
    image_ref = _batch_images(wf, image_refs, start_id=83)
    wf["85"] = {
        "class_type": "IPAdapterUnifiedLoader",
        "inputs": {
            "model": model_ref,
            "preset": IPADAPTER_PRESET,
        },
    }
    wf["86"] = {
        "class_type": "IPAdapter",
        "inputs": {
            "model": ["85", 0],
            "ipadapter": ["85", 1],
            "image": image_ref,
            "weight": float(clamp_ipadapter_weight(weight)),
            "start_at": 0.0,
            "end_at": 1.0,
            "weight_type": IPADAPTER_WEIGHT_TYPE,
        },
    }
    return ["86", 0]


def apply_face_detailer(
    wf: dict,
    *,
    image_ref: list,
    model_ref: list,
    clip_ref: list,
    vae_ref: list,
    positive_ref: list,
    negative_ref: list,
    seed: int,
    steps: int,
    cfg: float,
    sampler_name: str,
    scheduler: str,
    object_info: dict | None = None,
) -> list:
    """FaceDetailer između VAEDecode i SaveImage. Bez SAM-a, konzervativne veličine za 8 GB."""
    _ = object_info
    model_name = FACE_YOLO_WIDGET
    catalog = image_gen._object_info_catalog(object_info) or {}
    node = catalog.get("UltralyticsDetectorProvider") if isinstance(catalog, dict) else None
    required = ((node or {}).get("input") or {}).get("required") or {}
    typ = required.get("model_name")
    opts: list = []
    if isinstance(typ, list) and typ:
        first = typ[0]
        opts = list(first) if isinstance(first, list) else list(typ)
    if opts:
        lowered = [str(x) for x in opts]
        pick = next((x for x in lowered if "face_yolov8m" in x.lower()), None)
        if not pick:
            pick = next((x for x in lowered if "face" in x.lower() and "yolo" in x.lower()), None)
        if pick:
            model_name = pick
    wf["90"] = {
        "class_type": "UltralyticsDetectorProvider",
        "inputs": {"model_name": model_name},
    }
    defaults = dict(FACE_DETAILER_DEFAULTS)
    steps_use = max(4, min(int(steps), 16))
    wf["91"] = {
        "class_type": "FaceDetailer",
        "inputs": {
            "image": image_ref,
            "model": model_ref,
            "clip": clip_ref,
            "vae": vae_ref,
            "guide_size": float(defaults["guide_size"]),
            "guide_size_for": bool(defaults["guide_size_for"]),
            "max_size": float(defaults["max_size"]),
            "seed": int(seed),
            "steps": int(steps_use),
            "cfg": float(cfg),
            "sampler_name": sampler_name,
            "scheduler": scheduler,
            "positive": positive_ref,
            "negative": negative_ref,
            "denoise": float(defaults["denoise"]),
            "feather": int(defaults["feather"]),
            "noise_mask": bool(defaults["noise_mask"]),
            "force_inpaint": bool(defaults["force_inpaint"]),
            "bbox_threshold": float(defaults["bbox_threshold"]),
            "bbox_dilation": int(defaults["bbox_dilation"]),
            "bbox_crop_factor": float(defaults["bbox_crop_factor"]),
            "sam_detection_hint": defaults["sam_detection_hint"],
            "sam_dilation": int(defaults["sam_dilation"]),
            "sam_threshold": float(defaults["sam_threshold"]),
            "sam_bbox_expansion": int(defaults["sam_bbox_expansion"]),
            "sam_mask_hint_threshold": float(defaults["sam_mask_hint_threshold"]),
            "sam_mask_hint_use_negative": defaults["sam_mask_hint_use_negative"],
            "drop_size": int(defaults["drop_size"]),
            "bbox_detector": ["90", 0],
            "wildcard": defaults["wildcard"],
            "cycle": int(defaults["cycle"]),
        },
    }
    return ["91", 0]


def truthy(value, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "on", "da"}:
        return True
    if s in {"0", "false", "no", "off", "ne"}:
        return False
    return default
