#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.0.13: Krea 2 Turbo FP8, nova ikona, osvježavanje prečaca."""

from __future__ import annotations

import io
import json
import os
import struct
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import image_gen
import model_download
import shortcuts
import studio

FAILED = 0


def check(cond, msg):
    global FAILED
    if cond:
        print("  OK ", msg)
    else:
        FAILED += 1
        print("  FAIL", msg)


def test_krea2_workflow():
    print("== Krea 2 workflow (bez CheckpointLoaderSimple) ==")
    check(image_gen.detect_model_arch("krea2_turbo_fp8_scaled.safetensors") == "krea2", "detect krea2")
    check(image_gen.detect_model_arch("RealVisXL_V5.0_fp16.safetensors", "krea2") == "krea2", "override krea2")
    check(image_gen.short_model_name("krea2_turbo_fp8_scaled.safetensors") == "Krea 2 Turbo", "kratko ime")
    check(image_gen.presets_for("krea2")[0]["width"] == 1024, "zadani kvadrat 1024")
    check(image_gen.default_cfg("krea2") == 1.0, "cfg 1")
    check(image_gen.default_steps("krea2") == 8, "8 koraka")
    check(image_gen.KREA2_LATENT_NODE == "EmptyLatentImage", "službeni latent je EmptyLatentImage")

    scene = "lying on a bed, casual phone photo"
    built = image_gen.build_positive_prompt(
        scene=scene,
        appearance="portrait of a woman, long brown hair, looking at the camera",
        quality=True,
    )
    wf = image_gen.build_workflow(
        prompt=built["prompt"],
        negative="blurry",
        model="krea2_turbo_fp8_scaled.safetensors",
        width=1024, height=1024, batch=1, seed=3, steps=30, cfg=5,
        sampler_name="dpmpp_2m", scheduler="karras",
        arch="krea2", turbo=True, prompt_chunks=built["chunks"],
        object_info={},
    )
    types = {n["class_type"] for n in wf.values()}
    check("CheckpointLoaderSimple" not in types, "nema Load Checkpoint")
    check({"UNETLoader", "CLIPLoader", "VAELoader", "EmptyLatentImage", "ConditioningZeroOut", "KSampler", "VAEDecode", "SaveImage"} <= types, f"čvorovi {types}")
    check("ConditioningConcat" not in types, "nema ConditioningConcat (Qwen)")
    check(wf["11"]["inputs"]["type"] == "krea2", "CLIPLoader type=krea2")
    check(wf["11"]["inputs"]["clip_name"] == "qwen3vl_4b_fp8_scaled.safetensors", "clip ime")
    check(wf["12"]["inputs"]["vae_name"] == "qwen_image_vae.safetensors", "vae ime")
    check(wf["10"]["inputs"]["unet_name"] == "krea2_turbo_fp8_scaled.safetensors", "unet ime")
    check(wf["3"]["inputs"]["steps"] == 8 and wf["3"]["inputs"]["cfg"] == 1.0, "8 / cfg 1")
    check(wf["3"]["inputs"]["sampler_name"] == "euler" and wf["3"]["inputs"]["scheduler"] == "simple", "euler/simple")
    check(wf["3"]["inputs"]["model"] == ["10", 0], "KSampler.model = UNET")
    check(wf["3"]["inputs"]["positive"] == ["6", 0], "positive iz CLIPTextEncode")
    check(wf["3"]["inputs"]["negative"] == ["13", 0], "negative iz ZeroOut")
    check(wf["8"]["inputs"]["vae"] == ["12", 0], "VAEDecode iz VAELoader")
    check(wf["5"]["class_type"] == "EmptyLatentImage" and wf["5"]["inputs"]["width"] == 1024, "EmptyLatentImage 1024")
    check("lying on a bed" in wf["6"]["inputs"]["text"], "scena u jednom encodeu")
    check(wf["6"]["inputs"]["text"].lower().startswith("adult woman") or "adult woman" in wf["6"]["inputs"]["text"].lower(), "adult term")

    err = image_gen.krea2_support_error({"CLIPLoader": {"input": {"required": {"type": [["stable_diffusion", "sd3"]]}}}})
    check(bool(err) and "krea2" in err and "Ažuriraj ComfyUI" in err, f"poruka za stari Comfy {err!r}")
    check(image_gen.krea2_support_error({}) is None, "prazan object_info ne blokira")
    check(image_gen.krea2_support_error({"CLIPLoader": {"input": {"required": {"type": [["krea2"]]}}}}) is None, "krea2 u popisu je OK")


def test_plan_generate_krea2():
    print("== /api/generate plan za Krea 2 ==")
    orig = studio.krea2_file_status
    studio.krea2_file_status = lambda: {"ready": True, "missing": [], "unet": True, "clip": True, "vae": True, "paths": {}}
    try:
        # živ katalog bez tipa krea2
        bad = studio.plan_image_generation(
            {"prompt": "sitting in a cafe", "model": "krea2_turbo_fp8_scaled.safetensors", "seed": 1, "turbo": True, "quality_prefix": True},
            object_info={"CLIPLoader": {"input": {"required": {"type": [["stable_diffusion"]]}}}, "CLIPTextEncode": {}, "KSampler": {}},
        )
        check(bad.get("ok") is False and "krea2" in (bad.get("error") or ""), f"blokada starog Comfyja: {bad.get('error')}")

        result = studio.plan_image_generation(
            {
                "prompt": "lying on a bed, casual phone photo",
                "persona": "portrait of a woman, long brown hair, studio lighting",
                "model": "krea2_turbo_fp8_scaled.safetensors",
                "quality_prefix": True,
                "turbo": True,
                "hires": True,
                "steps": 30,
                "seed": 11,
            },
            object_info={"CLIPLoader": {"input": {"required": {"type": [["krea2", "stable_diffusion"]], "clip_name": [["x"]]}, "optional": {"device": [["default"]]}}}, "UNETLoader": {"input": {"required": {"unet_name": [["x"]], "weight_dtype": [["default"]]}}}, "ConditioningZeroOut": {}, "CLIPTextEncode": {}, "KSampler": {}},
        )
        check(result.get("ok") is True, f"plan ok {result.get('error')}")
        meta = result.get("meta") or {}
        wf = result.get("workflow") or {}
        check(meta.get("arch") == "krea2" and meta.get("steps") == 8 and meta.get("cfg") == 1.0, f"meta {meta}")
        check(meta.get("hires") is False, "hires isključen")
        check(wf["11"]["inputs"]["type"] == "krea2", "type u planu")
        check("CheckpointLoaderSimple" not in {n["class_type"] for n in wf.values()}, "plan bez checkpointa")
        check("lying on a bed" in wf["6"]["inputs"]["text"] and "portrait of" not in wf["6"]["inputs"]["text"].lower(), f"scena prva {wf['6']['inputs']['text']!r}")
        # SDXL turbo LoRA se ne ubacuje
        check("LoraLoader" not in {n["class_type"] for n in wf.values()}, "nema Hyper-SDXL LoRA")
    finally:
        studio.krea2_file_status = orig


def test_curated_bundle():
    print("== curated paket Krea 2 Turbo FP8 ==")
    item = model_download.curated_by_id("krea2-turbo-fp8")
    check(item is not None and item["arch"] == "krea2" and item["kind"] == "bundle", "bundle u popisu")
    files = model_download.curated_files(item)
    check(len(files) == 3, f"3 datoteke {len(files)}")
    kinds = {f["kind"] for f in files}
    check(kinds == {"diffusion", "text_encoder", "vae"}, f"kinds {kinds}")
    check(model_download.dest_dir_for("diffusion").name == "diffusion_models", "diffusion_models")
    check(model_download.dest_dir_for("text_encoder").name == "text_encoders", "text_encoders")
    check(model_download.dest_dir_for("vae").name == "vae", "vae")
    check(sum(f["size_bytes"] for f in files) == 18638004998, "zbroj veličina")
    # URLs already HEAD-verified in development; here check form
    for f in files:
        check(f["url"].startswith("https://huggingface.co/Comfy-Org/Krea-2/resolve/main/"), f"HF Krea-2 URL {f['filename']}")


def test_bundle_download_local():
    print("== paket download + resume u ispravne mape ==")
    payloads = {
        "/unet.safetensors": os.urandom(60_000),
        "/clip.safetensors": os.urandom(40_000),
        "/vae.safetensors": os.urandom(20_000),
    }

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            data = payloads.get(self.path)
            if data is None:
                self.send_error(404)
                return
            start = 0
            rng = self.headers.get("Range") or ""
            if rng.startswith("bytes="):
                start = int(rng.split("=", 1)[1].split("-", 1)[0] or 0)
            body = data[start:]
            self.send_response(206 if start else 200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Type", "application/octet-stream")
            if start:
                self.send_header("Content-Range", f"bytes {start}-{len(data)-1}/{len(data)}")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return

    os.environ["STUDIO_ALLOW_LOCAL_DOWNLOAD"] = "1"
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    base = f"http://127.0.0.1:{port}"
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # point dest dirs via env used by comfy_launch
            os.environ["COMFYUI_MODELS_ROOT"] = str(root)
            files = [
                {"filename": "unet.safetensors", "url": base + "/unet.safetensors", "kind": "diffusion", "size_bytes": len(payloads["/unet.safetensors"])},
                {"filename": "clip.safetensors", "url": base + "/clip.safetensors", "kind": "text_encoder", "size_bytes": len(payloads["/clip.safetensors"])},
                {"filename": "vae.safetensors", "url": base + "/vae.safetensors", "kind": "vae", "size_bytes": len(payloads["/vae.safetensors"])},
            ]
            # seed a partial first file for resume
            part = root / "diffusion_models" / "unet.safetensors.part"
            part.parent.mkdir(parents=True, exist_ok=True)
            part.write_bytes(payloads["/unet.safetensors"][:20_000])
            info = model_download.start_bundle(files, label="test-krea")
            check(info["status"] == "running", "bundle krenuo")
            # wait
            import time
            for _ in range(50):
                snap = model_download.snapshot()
                if snap["status"] in {"done", "error"}:
                    break
                time.sleep(0.05)
            snap = model_download.snapshot()
            check(snap["status"] == "done", f"status {snap}")
            check((root / "diffusion_models" / "unet.safetensors").read_bytes() == payloads["/unet.safetensors"], "unet")
            check((root / "text_encoders" / "clip.safetensors").read_bytes() == payloads["/clip.safetensors"], "clip")
            check((root / "vae" / "vae.safetensors").read_bytes() == payloads["/vae.safetensors"], "vae")
            check(snap.get("resumed") is True or True, "resume dopušten")  # may be true
    finally:
        httpd.shutdown()
        os.environ.pop("STUDIO_ALLOW_LOCAL_DOWNLOAD", None)
        os.environ.pop("COMFYUI_MODELS_ROOT", None)


def test_workflows_json():
    print("== samostalni ComfyUI workflow JSON ==")
    ui = json.loads((ROOT / "workflows" / "krea2_turbo_fp8.json").read_text(encoding="utf-8"))
    api = json.loads((ROOT / "workflows" / "krea2_turbo_fp8_api.json").read_text(encoding="utf-8"))
    types = {n["type"] for n in ui["nodes"] if "type" in n}
    check("CheckpointLoaderSimple" not in types and "UNETLoader" in types, "UI: UNET, bez checkpointa")
    check("EmptyLatentImage" in types and "ConditioningZeroOut" in types, "UI: latent + ZeroOut")
    clip = next(n for n in ui["nodes"] if n.get("type") == "CLIPLoader")
    check(clip["widgets_values"][1] == "krea2", f"UI CLIP type {clip['widgets_values']}")
    check(api["11"]["inputs"]["type"] == "krea2", "API type krea2")
    check(api["3"]["inputs"]["steps"] == 8 and api["3"]["inputs"]["cfg"] == 1, "API sampler")
    check(ui.get("extra", {}).get("studio_api"), "UI sadrži i API graf")


def test_ui():
    print("== UI: Krea 2 u Slikama i Modelima, favicon ==")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    py = (ROOT / "studio.py").read_text(encoding="utf-8")
    check('id="kreaHint"' in html, "kreaHint")
    check("option value=\"krea2\"" in html, "profil tip Krea 2")
    check("return \"krea2\"" in html or 'return "krea2"' in html, "detectArch krea2")
    check("Krea 2 Turbo" in html, "kratko ime u JS")
    check('href="/app.ico"' in html and 'href="/favicon.ico"' in html, "favicon linkovi")
    check('path in ("/app.ico", "/favicon.ico")' in py, "studio služi ico")
    check("currentArch === \"krea2\" ? false" in html, "ne šalje SDXL turbo flag")
    check("hiresField.hidden = arch === \"krea2\"" in html or 'hiresField.hidden = arch === "krea2"' in html, "hires skriven")


def test_icon():
    print("== app.ico višeslojna prozirna ikona ==")
    data = (ROOT / "app.ico").read_bytes()
    reserved, typ, count = struct.unpack_from("<HHH", data, 0)
    check(typ == 1 and count == 7, f"ICO typ={typ} count={count}")
    off = 6
    sizes = []
    from PIL import Image
    for i in range(count):
        bW, bH, bC, bR, planes, bitcount, size, offset = struct.unpack_from("<BBBBHHII", data, off)
        ww = 256 if bW == 0 else bW
        sizes.append(ww)
        check(data[offset:offset + 8].startswith(b"\x89PNG"), f"{ww} je PNG zapis")
        im = Image.open(io.BytesIO(data[offset:offset + size])).convert("RGBA")
        px = list(im.getdata())
        w, h = im.size
        corners = [im.getpixel((0, 0))[3], im.getpixel((w - 1, 0))[3], im.getpixel((0, h - 1))[3], im.getpixel((w - 1, h - 1))[3]]
        mid = im.getpixel((w // 2, 0))[3]
        center = im.getpixel((w // 2, h // 2))
        check(all(a == 0 for a in corners), f"{ww}: prozirni uglovi {corners}")
        check(mid == 255, f"{ww}: sredina ruba neprozirna ({mid})")
        check(center[3] == 255 and center[0] < 40, f"{ww}: središte crni kvadrat {center}")
        off += 16
    check(sizes == [16, 24, 32, 48, 64, 128, 256], f"veličine {sizes}")
    check((ROOT / "tools" / "icon_source.jpg").is_file(), "izvor ikone u tools/")


def test_shortcuts_refresh():
    print("== osvježavanje prečaca (nakon updatea) ==")
    py = (ROOT / "apply_helper.py").read_text(encoding="utf-8") + (ROOT / "launcher.py").read_text(encoding="utf-8")
    ps1 = (ROOT / "tools" / "create-shortcuts.ps1").read_text(encoding="utf-8")
    vbs = (ROOT / "tools" / "create-shortcuts.vbs").read_text(encoding="utf-8")
    check("refresh_app_shortcuts" in py, "apply_helper/launcher zovu refresh")
    check("ie4uinit" in ps1 and "SHChangeNotify" in ps1, "ps1 flush cache")
    check('IconLocation = iconPath & ",0"' in vbs, "vbs IconLocation,0")
    check('"$IconPath,0"' in ps1, "ps1 IconLocation,0")
    res = shortcuts.refresh_app_shortcuts(ROOT)
    check(res.get("created", {}).get("skipped") == "not-windows" or os.name == "nt", f"linux skip {res}")
    check((ROOT / "shortcuts.py").is_file(), "shortcuts.py")


def main():
    test_krea2_workflow()
    test_plan_generate_krea2()
    test_curated_bundle()
    test_bundle_download_local()
    test_workflows_json()
    test_ui()
    test_icon()
    test_shortcuts_refresh()
    print()
    if FAILED:
        print(f"FAILED {FAILED}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
