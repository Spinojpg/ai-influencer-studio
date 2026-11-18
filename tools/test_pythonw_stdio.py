#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Simuliraj pythonw: sys.stdout = sys.stderr = None, pa GET / mora vratiti 200."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_http(url: str, seconds: float) -> tuple[int, bytes]:
    deadline = time.time() + seconds
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                return resp.status, resp.read()
        except Exception as exc:
            last_err = exc
            time.sleep(0.15)
    raise RuntimeError(f"Nema odgovora s {url}: {last_err}")


def main() -> int:
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="studio-stdio-") as td:
        data = Path(td) / "data"
        data.mkdir()
        wrapper = Path(td) / "run_like_pythonw.py"
        wrapper.write_text(
            "\n".join(
                [
                    "import sys",
                    "sys.stdout = None",
                    "sys.stderr = None",
                    "import studio",
                    "raise SystemExit(studio.main())",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["STUDIO_HOST"] = "127.0.0.1"
        env["STUDIO_PORT"] = str(port)
        env["STUDIO_NO_BROWSER"] = "1"
        env["STUDIO_APP_DIR"] = str(ROOT)
        env["STUDIO_DATA_DIR"] = str(data)
        env["STUDIO_SKIP_UPDATE"] = "1"
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.Popen(
            [sys.executable, str(wrapper)],
            cwd=str(ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
        )
        url = f"http://127.0.0.1:{port}/"
        try:
            # Proces ne smije odmah umrijeti zbog print() na None.
            time.sleep(0.8)
            if proc.poll() is not None:
                print(f"FAIL proces je izašao sa {proc.returncode} prije zahtjeva")
                log = data / "logs" / "studio.log"
                if log.is_file():
                    print(log.read_text(encoding="utf-8", errors="replace")[-2000:])
                return 1
            status, body = wait_http(url, 15)
            print(f"GET / -> {status}, {len(body)} bajtova")
            if status != 200:
                print("FAIL očekivao 200")
                return 1
            if b"AI Influencer Studio" not in body and b"<!DOCTYPE" not in body.upper() and b"<html" not in body.lower():
                print("FAIL tijelo ne izgleda kao index.html")
                return 1
            # Drugi zahtjev (log_message se zove pri svakom)
            status2, _ = wait_http(url, 5)
            if status2 != 200:
                print(f"FAIL drugi GET / -> {status2}")
                return 1
            log = data / "logs" / "studio.log"
            if not log.is_file():
                print("FAIL nema studio.log")
                return 1
            text = log.read_text(encoding="utf-8", errors="replace")
            if "GET /" not in text and '"GET /' not in text:
                # BaseHTTPRequestHandler format is typically GET / HTTP/1.1
                if "GET" not in text:
                    print("FAIL log ne sadrži zahtjev:")
                    print(text[-2000:])
                    return 1
            if "Log je spreman" not in text and "Sucelje" not in text and "Verzija" not in text:
                # banner should have been printed into the log
                print("UPOZORENJE: banner nije u logu, ali GET je 200")
            # stdio None nije srušio handler
            print("OK pythonw simulacija: GET / = 200, log =", log)
            return 0
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)


if __name__ == "__main__":
    raise SystemExit(main())
