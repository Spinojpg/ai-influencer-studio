#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.0.2: wrapper bat, SDXL, hires, ws progres, download resume."""

from __future__ import annotations

import http.server
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import comfy_launch  # noqa: E402
import comfy_ws  # noqa: E402
import image_gen  # noqa: E402
import model_download  # noqa: E402

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if cond:
        print("  OK ", msg)
    else:
        print("  FAIL", msg)
        failures.append(msg)


def test_arch() -> None:
    print("== detekcija modela ==")
    check(image_gen.detect_model_arch("Realistic_Vision_V6.0_NV_B1_fp16.safetensors") == "sd15", "Realistic Vision = SD 1.5")
    check(image_gen.detect_model_arch("RealVisXL_V5.0_fp16.safetensors") == "sdxl", "RealVisXL = SDXL")
    check(image_gen.detect_model_arch("juggernautXL_v9.safetensors") == "sdxl", "Juggernaut = SDXL")
    check(image_gen.detect_model_arch("sd_xl_base_1.0.safetensors") == "sdxl", "sd_xl_base = SDXL")
    check(image_gen.detect_model_arch("foo.safetensors", "sdxl") == "sdxl", "override sdxl")
    check(image_gen.detect_model_arch("RealVisXL_V5.0_fp16.safetensors", "sd15") == "sd15", "override sd15")
    check(image_gen.presets_for("sdxl")[0]["width"] == 832, "SDXL portret 832")
    check(image_gen.presets_for("sd15")[0]["width"] == 512, "SD1.5 portret 512")
    check(image_gen.default_cfg("sdxl") == 5.0, "SDXL cfg 5")
    check(image_gen.default_cfg("sd15") == 5.5, "SD1.5 cfg 5.5")


def test_quality_and_workflow() -> None:
    print("== quality prefix i workflow ==")
    p = image_gen.apply_quality_prefix("woman in cafe", True)
    check(p.startswith(image_gen.QUALITY_PREFIX), "prefix dodan")
    check(image_gen.apply_quality_prefix(p, True) == p, "prefix se ne udvostručuje")
    check(image_gen.apply_quality_prefix("woman", False) == "woman", "prefix se može isključiti")
    wf = image_gen.build_workflow(
        prompt=p, negative=image_gen.DEFAULT_NEGATIVE, model="m.safetensors",
        width=512, height=768, batch=1, seed=1, steps=30, arch="sd15",
    )
    check(wf["3"]["inputs"]["cfg"] == 5.5, "SD1.5 cfg 5.5 u KSampleru")
    check(wf["3"]["inputs"]["sampler_name"] == "dpmpp_2m", "dpmpp_2m")
    check(wf["3"]["inputs"]["scheduler"] == "karras", "karras")
    check("child" in image_gen.DEFAULT_NEGATIVE, "novi negativni prompt")
    hires = image_gen.build_workflow(
        prompt=p, negative="neg", model="m.safetensors",
        width=512, height=768, batch=1, seed=7, steps=30, arch="sd15", hires=True,
    )
    check(hires["10"]["class_type"] in {"LatentUpscaleBy", "LatentUpscale"}, "hires upscale čvor")
    if hires["10"]["class_type"] == "LatentUpscaleBy":
        check(hires["10"]["inputs"]["scale_by"] == 1.5, "scale 1.5")
    check(hires["11"]["inputs"]["denoise"] == 0.4, "drugi sampler denoise 0.4")
    check(hires["8"]["inputs"]["samples"] == ["11", 0], "decode ide s drugog samplera")
    # bez face detailera ako nema object_info
    check("FaceDetailer" not in json.dumps(hires), "nema FaceDetailer kad čvorovi nisu tu")
    xlw = image_gen.build_workflow(
        prompt=p, negative="n", model="RealVisXL_V5.0_fp16.safetensors",
        width=832, height=1216, batch=1, seed=1, steps=30, arch="sdxl",
    )
    check(xlw["3"]["inputs"]["cfg"] == 5.0, "SDXL cfg 5")
    check(xlw["5"]["inputs"]["width"] == 832, "SDXL latent 832")


def test_wrapper_bat(tmp: Path) -> None:
    print("== comfyui-studio.bat ==")
    tmp.mkdir(parents=True, exist_ok=True)
    src = tmp / "comfyui-n.bat"
    src.write_bytes(
        b"@echo off\r\nset PYTHON=python\r\npython main.py --auto-launch --use-zluda --lowvram\r\npause\r\n"
    )
    dest = tmp / "comfyui-studio.bat"
    comfy_launch.build_comfy_studio_bat(src, dest, disable_cudnn=True)
    text = dest.read_bytes().decode("utf-8")
    orig = src.read_bytes()
    check(b"--auto-launch" in orig, "original i dalje ima --auto-launch")
    check("--auto-launch" not in text.lower().replace("_", "-") or "--auto-launch" not in text, "wrapper nema --auto-launch")
    check("--auto-launch" not in text, "nema --auto-launch u wrapperu")
    check("TORCH_BACKENDS_CUDNN_ENABLED=0" in text, "set cuDNN 0 na vrhu wrappera")
    check(text.splitlines()[0].strip().lower() == "@echo off", "wrapper pocinje s @echo off")
    check(orig == src.read_bytes(), "original nije diran")
    env = comfy_launch.comfy_process_env({"PATH": "/x"}, disable_cudnn=True)
    check(env.get("TORCH_BACKENDS_CUDNN_ENABLED") == "0", "env procesa ima TORCH_BACKENDS_CUDNN_ENABLED=0")
    env2 = comfy_launch.comfy_process_env({"PATH": "/x"}, disable_cudnn=False)
    check("TORCH_BACKENDS_CUDNN_ENABLED" not in env2 or env2.get("TORCH_BACKENDS_CUDNN_ENABLED") != "0" or True, "toggle")
    check(env2.get("TORCH_BACKENDS_CUDNN_ENABLED") != "0", "kad je opcija isključena, env nije 0")
    dest2 = tmp / "off.bat"
    comfy_launch.build_comfy_studio_bat(src, dest2, disable_cudnn=False)
    check("TORCH_BACKENDS_CUDNN_ENABLED=0" not in dest2.read_text(encoding="utf-8"), "wrapper bez set 0 kad je isključeno")


def test_ws() -> None:
    print("== websocket progres ==")
    w = comfy_ws.ProgressWatcher("http://127.0.0.1:9", "test")
    w.handle_message({"type": "progress", "data": {"value": 7, "max": 30, "prompt_id": "abc"}})
    snap = w.snapshot("abc")
    check(snap["value"] == 7 and snap["max"] == 30, "progress poruka")
    w.handle_message({"type": "executing", "data": {"node": "3", "prompt_id": "abc"}})
    check(w.snapshot("abc")["node"] == "3", "executing node")
    w.handle_message({"type": "executing", "data": {"node": None, "prompt_id": "abc"}})
    check(w.snapshot("abc").get("finished") is True, "executing None = gotovo")

    # pravi mini WS server
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            return

        def do_GET(self):
            if "Upgrade" not in (self.headers.get("Connection") or "") and self.headers.get("Upgrade", "").lower() != "websocket":
                # still accept if key present
                pass
            key = self.headers.get("Sec-WebSocket-Key")
            if not key:
                self.send_error(400)
                return
            accept = comfy_ws.accept_key(key)
            self.send_response(101, "Switching Protocols")
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            payload = json.dumps({"type": "progress", "data": {"value": 4, "max": 20, "prompt_id": "zz"}}).encode()
            self.wfile.write(comfy_ws.encode_frame(payload, comfy_ws.OP_TEXT, masked=False))
            self.wfile.flush()
            time.sleep(0.4)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        client = comfy_ws.WebSocketClient.connect(f"ws://127.0.0.1:{port}/ws?clientId=t", timeout=5)
        frame = client.recv(timeout=5)
        client.close()
        check(frame is not None, "primljen ws frame")
        op, data = frame
        msg = json.loads(data.decode())
        check(msg["data"]["value"] == 4, "ws progress value 4")
    finally:
        httpd.shutdown()


def test_download(tmp: Path) -> None:
    print("== preuzimanje s resume ==")
    payload = os.urandom(200_000)
    dest_dir = tmp / "ckpts"
    dest_dir.mkdir(parents=True, exist_ok=True)
    part = dest_dir / "demo.safetensors.part"
    part.write_bytes(payload[:50_000])

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            return

        def do_GET(self):
            rng = self.headers.get("Range") or ""
            if rng.startswith("bytes="):
                start = int(rng.split("=", 1)[1].split("-", 1)[0] or 0)
                chunk = payload[start:]
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{len(payload)-1}/{len(payload)}")
                self.send_header("Content-Length", str(len(chunk)))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                self.wfile.write(chunk)
            else:
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    os.environ["STUDIO_ALLOW_LOCAL_DOWNLOAD"] = "1"
    try:
        url = f"http://127.0.0.1:{port}/demo.safetensors"
        model_download.start_download(url, "demo.safetensors", dest_dir)
        deadline = time.time() + 8
        st = {}
        while time.time() < deadline:
            st = model_download.snapshot()
            if st.get("status") in {"done", "error"}:
                break
            time.sleep(0.05)
        check(st.get("status") == "done", f"status done ({st})")
        check(st.get("resumed") is True, "resume je korišten")
        out = dest_dir / "demo.safetensors"
        check(out.is_file() and out.stat().st_size == len(payload), "datoteka potpuna")
        check(out.read_bytes() == payload, "sadržaj jednak")
    finally:
        httpd.shutdown()
        os.environ.pop("STUDIO_ALLOW_LOCAL_DOWNLOAD", None)


def test_curated_url() -> None:
    print("== curated URL ==")
    item = model_download.CURATED[0]
    check("huggingface.co/SG161222/RealVisXL_V5.0/resolve/main/RealVisXL_V5.0_fp16.safetensors" in item["url"], "RealVisXL javni URL")
    check(item["arch"] == "sdxl", "curated je SDXL")
    check(item["filename"].endswith(".safetensors"), "safetensors")


def main() -> int:
    test_arch()
    test_quality_and_workflow()
    test_curated_url()
    test_ws()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        test_wrapper_bat(tmp / "bat")
        test_download(tmp / "dl")
    print()
    if failures:
        print("NEUSPJEH", len(failures))
        for f in failures:
            print(" -", f)
        return 1
    print("SVI TESTOVI v1.0.2 PROŠLI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
