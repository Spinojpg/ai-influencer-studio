#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.0.15: instalirani modeli, brisanje, dedupe slika."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import image_gen
import installed_models
import model_download
import studio

FAILED = 0


def check(cond, msg):
    global FAILED
    if cond:
        print("  OK ", msg)
    else:
        FAILED += 1
        print("  FAIL", msg)


def test_format_size():
    print("== format_size ==")
    check(installed_models.format_size(0) == "0 B", "0 B")
    check(installed_models.format_size(500) == "500 B", "500 B")
    check(installed_models.format_size(1536) == "1,5 KB", f"1,5 KB got {installed_models.format_size(1536)}")
    check(installed_models.format_size(750 * 1024 * 1024) == "750 MB", f"750 MB got {installed_models.format_size(750 * 1024 * 1024)}")
    check(installed_models.format_size(254 * 1024 * 1024) == "254 MB", "254 MB")
    got = installed_models.format_size(int(6.5 * 1024**3))
    check(got == "6,5 GB", f"6,5 GB got {got}")


def _write(path: Path, size: int = 32) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_list_and_delete(tmp: Path):
    print("== popis i brisanje ==")
    root = tmp / "models"
    (root / "checkpoints").mkdir(parents=True)
    (root / "loras").mkdir()
    (root / "diffusion_models").mkdir()
    (root / "text_encoders").mkdir()
    (root / "vae").mkdir()
    (root / "animatediff_models").mkdir()
    _write(root / "checkpoints" / "RealVisXL_V5.0_fp16.safetensors", 64)
    _write(root / "checkpoints" / "note.txt", 8)
    _write(root / "loras" / image_gen.TURBO_SDXL["lora_filename"], 16)
    _write(root / "loras" / "face-xl.safetensors", 16)
    _write(root / "diffusion_models" / image_gen.KREA2_UNET, 24)
    _write(root / "text_encoders" / image_gen.KREA2_CLIP, 20)
    _write(root / "vae" / image_gen.KREA2_VAE, 12)
    _write(root / "animatediff_models" / "mm_sd_v15_v2.ckpt", 10)
    _write(root / "loras" / "extra.gguf", 11)
    _write(root / "orphan.safetensors", 9)  # direktno u models/ — ne smije u popis

    os.environ["COMFYUI_MODELS_ROOT"] = str(root)
    try:
        data = installed_models.list_installed(selected="RealVisXL_V5.0_fp16.safetensors")
        names = {f["name"]: f for f in data["files"]}
        check("orphan.safetensors" not in names, "datoteka u korijenu models nije na popisu")
        check("note.txt" not in names, "txt nije na popisu")
        check("RealVisXL_V5.0_fp16.safetensors" in names, "checkpoint je na popisu")
        check(names["RealVisXL_V5.0_fp16.safetensors"]["folder"] == "checkpoints", "folder checkpoint")
        check(names["RealVisXL_V5.0_fp16.safetensors"]["selected"] is True, "odabrani model označen")
        check(names["face-xl.safetensors"]["selected"] is False, "druga datoteka nije odabrana")
        check(names["extra.gguf"]["folder"] == "loras", "gguf je na popisu")
        turbo = names[image_gen.TURBO_SDXL["lora_filename"]]
        check(turbo["required"] is True and turbo["bundle"] == "turbo", "Turbo LoRA je označena kao potrebna")
        check(names[image_gen.KREA2_UNET]["bundle"] == "krea2", "Krea2 UNET potrebna")
        check(names[image_gen.KREA2_CLIP]["bundle"] == "krea2", "Krea2 CLIP potrebna")
        check(names[image_gen.KREA2_VAE]["bundle"] == "krea2", "Krea2 VAE potrebna")
        check(data["total_bytes"] == 64 + 16 + 16 + 24 + 20 + 12 + 10 + 11, f"zbroj {data['total_bytes']}")
        check("GB" in data["total_label"] or "MB" in data["total_label"] or "B" in data["total_label"], "total_label postoji")
        check(names["mm_sd_v15_v2.ckpt"]["folder"] == "animatediff_models", "animatediff")

        curated = installed_models.annotate_curated(model_download.CURATED, data)
        by_id = {c["id"]: c for c in curated}
        check(by_id["realvisxl-v5-fp16"]["installed"] is True, "katalog: RealVis instaliran")
        check(by_id["krea2-turbo-fp8"]["installed"] is True, "katalog: Krea 2 paket instaliran")
        check(by_id["hyper-sdxl-8step-cfg"]["installed"] is True, "katalog: Turbo LoRA instalirana")
        check(by_id["juggernaut-xl-ragnarok"]["installed"] is False, "katalog: Juggernaut nije instaliran")

        result = installed_models.delete_model("loras/face-xl.safetensors")
        check(result["ok"] is True, "brisanje LoRA-e uspješno")
        check(not (root / "loras" / "face-xl.safetensors").exists(), "datoteka je nestala")
        left = {f["name"] for f in result["installed"]["files"]}
        check("face-xl.safetensors" not in left, "popis nakon brisanja više nema datoteku")
        check(result["curated"], "curated se vraća nakon brisanja")
    finally:
        os.environ.pop("COMFYUI_MODELS_ROOT", None)


def test_path_safety(tmp: Path):
    print("== sigurnost putanje ==")
    root = tmp / "models"
    outside = tmp / "outside.safetensors"
    _write(outside, 8)
    _write(root / "checkpoints" / "ok.safetensors", 8)
    _write(root / "vae" / "inside.safetensors", 8)
    os.environ["COMFYUI_MODELS_ROOT"] = str(root)
    try:
        # traversal
        for bad in (
            "../outside.safetensors",
            "checkpoints/../../outside.safetensors",
            "checkpoints/../../../etc/passwd",
            "/etc/passwd",
            "ok.safetensors",
            "checkpoints/ok.txt",
            "checkpoints/../outside.safetensors",
            str(outside),
        ):
            try:
                installed_models.resolve_model_file(bad)
                check(False, f"trebao odbiti {bad}")
            except installed_models.ModelPathError:
                check(True, f"odbijen {bad}")

        # symlink izvan roota
        link = root / "checkpoints" / "escape.safetensors"
        link.symlink_to(outside)
        try:
            installed_models.resolve_model_file("checkpoints/escape.safetensors")
            check(False, "symlink izvan roota treba odbiti")
        except installed_models.ModelPathError:
            check(True, "symlink izvan roota odbijen")
        listed = {f["path"] for f in installed_models.list_installed()["files"]}
        check("checkpoints/escape.safetensors" not in listed, "vanjski symlink nije na popisu")

        # symlink unutar roota: brisanje miče poveznicu, meta ostaje
        inner = root / "checkpoints" / "alias.safetensors"
        inner.symlink_to(root / "vae" / "inside.safetensors")
        resolved = installed_models.resolve_model_file("checkpoints/alias.safetensors")
        check(resolved.is_symlink(), "vraća se symlink, ne meta")
        res = installed_models.delete_model("checkpoints/alias.safetensors")
        check(res["ok"] is True, "brisanje unutarnjeg symlinka")
        check(not inner.exists(), "symlink obrisan")
        check((root / "vae" / "inside.safetensors").exists(), "meta ostaje")

        # folder + name
        path = installed_models.resolve_model_file(None, folder="checkpoints", name="ok.safetensors")
        check(path.name == "ok.safetensors", "folder+name radi")

        # zaključana datoteka
        def locked(self_or_path=None, *a, **k):
            err = PermissionError(13, "denied")
            raise err

        orig = installed_models._unlink
        installed_models._unlink = lambda path: (_ for _ in ()).throw(PermissionError(13, "denied"))
        try:
            out = installed_models.delete_model("checkpoints/ok.safetensors")
            check(out["ok"] is False and out.get("locked") is True, "locked flag")
            check("zaključana" in (out.get("error") or "").lower() or "ComfyUI" in (out.get("error") or ""), "hrvatska poruka za lock")
            check((root / "checkpoints" / "ok.safetensors").exists(), "zaključana datoteka nije obrisana")
        finally:
            installed_models._unlink = orig

        # Windows share violation
        def winlock(path):
            err = OSError(32, "in use")
            err.winerror = 32
            raise err

        installed_models._unlink = winlock
        try:
            out = installed_models.delete_model("checkpoints/ok.safetensors")
            check(out.get("locked") is True, "winerror 32 -> locked")
            check("ponovo pokreni" in (out.get("error") or "").lower() or "generiranja" in (out.get("error") or "").lower(), "poruka predlaže retry")
        finally:
            installed_models._unlink = orig
    finally:
        os.environ.pop("COMFYUI_MODELS_ROOT", None)


def test_extract_images_dedupe():
    print("== dedupe extract_images (batch 2 -> ne 4) ==")
    # Tipičan ComfyUI /history: VAEDecode temp preview + SaveImage output, batch=2.
    hist = {
        "outputs": {
            "8": {
                "images": [
                    {"filename": "ComfyUI_temp_00001_.png", "subfolder": "", "type": "temp"},
                    {"filename": "ComfyUI_temp_00002_.png", "subfolder": "", "type": "temp"},
                ]
            },
            "9": {
                "images": [
                    {"filename": "studio_00001_.png", "subfolder": "", "type": "output"},
                    {"filename": "studio_00002_.png", "subfolder": "", "type": "output"},
                ]
            },
        }
    }
    imgs = studio.extract_images(hist)
    check(len(imgs) == 2, f"preview+output batch=2 daje 2, dobio {len(imgs)} {[i['filename'] for i in imgs]}")
    check(all(i["type"] == "output" for i in imgs), "samo type=output")
    check([i["filename"] for i in imgs] == ["studio_00001_.png", "studio_00002_.png"], "imena output datoteka")

    # Isti zapis dvaput u dva čvora (isti filename+subfolder+type)
    dup = {
        "outputs": {
            "9": {"images": [{"filename": "studio_00001_.png", "subfolder": "", "type": "output"}]},
            "99": {"images": [{"filename": "studio_00001_.png", "subfolder": "", "type": "output"}]},
        }
    }
    imgs = studio.extract_images(dup)
    check(len(imgs) == 1, f"isti ključ se ne ponavlja, dobio {len(imgs)}")

    # Samo temp (nema SaveImage) — zadrži temp, ali dedupe
    only_temp = {
        "outputs": {
            "8": {
                "images": [
                    {"filename": "preview_01.png", "subfolder": "", "type": "temp"},
                    {"filename": "preview_01.png", "subfolder": "", "type": "temp"},
                    {"filename": "preview_02.png", "subfolder": "", "type": "temp"},
                ]
            }
        }
    }
    imgs = studio.extract_images(only_temp)
    check(len(imgs) == 2, f"samo temp, dedupe na 2, dobio {len(imgs)}")

    # Različiti subfolder ili type ostaju odvojeni ako nema output stillova? 
    # Ako postoji output, temp se baca.
    mixed_types = {
        "outputs": {
            "a": {"images": [{"filename": "x.png", "subfolder": "", "type": "temp"}]},
            "b": {"images": [{"filename": "x.png", "subfolder": "", "type": "output"}]},
        }
    }
    imgs = studio.extract_images(mixed_types)
    check(len(imgs) == 1 and imgs[0]["type"] == "output", "isti filename, preferiraj output")

    # Video + slike se ne miješaju u filteru
    media = {
        "outputs": {
            "9": {"images": [{"filename": "studio_00001_.png", "subfolder": "", "type": "output"}]},
            "20": {"gifs": [{"filename": "clip.mp4", "subfolder": "", "type": "output"}]},
        }
    }
    imgs = studio.extract_images(media)
    check(len(imgs) == 2, f"slika + video, dobio {len(imgs)}")
    check(any(i.get("kind") == "gifs" for i in imgs), "gif/video zadržan")

    # dedupe_images izravno
    four = [
        {"filename": "a.png", "subfolder": "", "type": "temp"},
        {"filename": "b.png", "subfolder": "", "type": "temp"},
        {"filename": "a.png", "subfolder": "", "type": "output"},
        {"filename": "b.png", "subfolder": "", "type": "output"},
    ]
    out = studio.dedupe_images(four)
    check(len(out) == 2, f"dedupe_images 4->2, dobio {len(out)}")


def test_curated_partial(tmp: Path):
    print("== djelomično instaliran paket ==")
    root = tmp / "models"
    _write(root / "diffusion_models" / image_gen.KREA2_UNET, 8)
    os.environ["COMFYUI_MODELS_ROOT"] = str(root)
    try:
        data = installed_models.list_installed()
        curated = installed_models.annotate_curated(model_download.CURATED, data)
        krea = next(c for c in curated if c["id"] == "krea2-turbo-fp8")
        check(krea["installed"] is False and krea["partial"] is True, "Krea 2 partial kad fali encoder/VAE")
    finally:
        os.environ.pop("COMFYUI_MODELS_ROOT", None)


def main():
    print("AI Influencer Studio — testovi 1.0.15")
    test_format_size()
    test_extract_images_dedupe()
    with tempfile.TemporaryDirectory() as td:
        test_list_and_delete(Path(td) / "a")
        test_path_safety(Path(td) / "b")
        test_curated_partial(Path(td) / "c")
    if FAILED:
        print(f"\nFAILED: {FAILED}")
        return 1
    print("\nSvi testovi 1.0.15 su prošli.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
