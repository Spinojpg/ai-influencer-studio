#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Samostalni pomoćnik: čeka da Studio/launcher izađu, pa primijeni pending update.

Pokreće se iz data/update-helper/ s cwd=data (nikad app mapa), da Windowsu
ne smeta preimenovanje/zamjena datoteka.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import updater  # noqa: E402


def _env_path(name: str, default: Path) -> Path:
    raw = (os.environ.get(name) or "").strip()
    return Path(raw).expanduser() if raw else default


DATA_DIR = _env_path("STUDIO_DATA_DIR", HERE.parent)
APP_DIR = _env_path("STUDIO_APP_DIR", DATA_DIR.parent / "app")
STUDIO_URL = os.environ.get("STUDIO_URL", "http://127.0.0.1:7860/")


def log(msg: str) -> None:
    updater.updater_log(DATA_DIR, "[helper] " + msg)
    try:
        print(msg)
    except Exception:
        pass


def pid_running(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            SYNCHRONIZE = 0x00100000
            handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def read_pid(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        return int(path.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return 0


def wait_pids_exit(pids: list[int], timeout: float) -> None:
    deadline = time.time() + timeout
    remaining = [p for p in pids if p and pid_running(p)]
    while remaining and time.time() < deadline:
        time.sleep(0.3)
        remaining = [p for p in remaining if pid_running(p)]
    if remaining:
        log(f"još uvijek rade PID-ovi {remaining}")


def kill_studio(pid: int) -> None:
    if not pid or not pid_running(pid):
        return
    log(f"ugasujem samo Studio PID {pid}")
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception as exc:
        log(f"nisam mogao ugasiti {pid}: {exc}")


def url_up(url: str) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=0.8) as resp:
            return 200 <= resp.status < 500
    except Exception:
        return False


def find_python() -> list[str]:
    venv = Path(r"C:\ComfyUI-Zluda\venv\Scripts\pythonw.exe")
    if venv.is_file():
        return [str(venv)]
    venv2 = Path(r"C:\ComfyUI-Zluda\venv\Scripts\python.exe")
    if venv2.is_file():
        return [str(venv2)]
    return [sys.executable]


def start_app() -> None:
    launcher = APP_DIR / "launcher.py"
    if not launcher.is_file():
        log(f"nema launcher.py u {APP_DIR}")
        return
    cmd = find_python() + [str(launcher), "--no-update"]
    env = os.environ.copy()
    env["STUDIO_APP_DIR"] = str(APP_DIR)
    env["STUDIO_DATA_DIR"] = str(DATA_DIR)
    env["STUDIO_SKIP_UPDATE"] = "1"
    log(f"pokrećem novi launcher: {cmd}")
    kwargs: dict = {"cwd": str(APP_DIR), "env": env, "close_fds": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = int(getattr(subprocess, "DETACHED_PROCESS", 0x00000008)) | int(
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        )
        kwargs["stdin"] = subprocess.DEVNULL
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)


def main() -> int:
    # Ključno: radni dir je data, ne app.
    os.chdir(DATA_DIR)
    log(f"start cwd={Path.cwd()} app={APP_DIR} data={DATA_DIR}")
    studio_pid = read_pid(DATA_DIR / "studio.pid")
    launcher_pid = read_pid(DATA_DIR / "launcher.pid")
    extra = []
    raw = (os.environ.get("STUDIO_WAIT_PIDS") or "").strip()
    if raw:
        for part in raw.split(","):
            try:
                extra.append(int(part.strip()))
            except ValueError:
                pass
    # Naš vlastiti PID se ne čeka.
    self_pid = os.getpid()
    wait_list = [p for p in [studio_pid, launcher_pid, *extra] if p and p != self_pid]
    log(f"čekam izlazak PID-ova {wait_list}")
    wait_pids_exit(wait_list, 20)
    if studio_pid and pid_running(studio_pid):
        kill_studio(studio_pid)
        wait_pids_exit([studio_pid], 15)
    deadline = time.time() + 30
    while time.time() < deadline and url_up(STUDIO_URL):
        time.sleep(0.4)
    log("port 7860 je slobodan" if not url_up(STUDIO_URL) else "UPOZORENJE: 7860 još odgovara")

    pending = DATA_DIR / "pending-update"
    meta_path = pending / "meta.json"
    zip_path = pending / "studio.zip"
    expected = None
    notes = ""
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("zip_path") and Path(meta["zip_path"]).is_file():
                zip_path = Path(meta["zip_path"])
            expected = meta.get("latest") or meta.get("expected")
            notes = meta.get("notes") or ""
        except Exception as exc:
            log(f"meta.json: {exc}")
    if not zip_path.is_file():
        log(f"nema ZIP-a ({zip_path})")
        updater.write_update_result(
            DATA_DIR,
            {
                "ok": False,
                "applied": False,
                "error": "Nema preuzetog studio.zip za primjenu.",
                "message": "Ažuriranje nije primijenjeno (nema paketa).",
            },
        )
        return 1

    backup_parent = APP_DIR.parent / "backup"
    try:
        backup = updater.apply_zip(
            zip_path,
            APP_DIR,
            backup_parent,
            expected_version=expected,
            data_dir=DATA_DIR,
        )
        ver = updater.load_version(APP_DIR).get("version") or ""
        if not ver or (expected and updater.parse_version(ver) != updater.parse_version(str(expected))):
            raise RuntimeError(f"Verzija na disku je {ver!r}, očekivano {expected!r}.")
        updater.write_update_result(
            DATA_DIR,
            {
                "ok": True,
                "applied": True,
                "updated_to": ver,
                "changelog": notes,
                "backup": str(backup),
                "message": f"Ažurirano na verziju {ver}",
            },
        )
        log(f"OK Ažurirano na {ver}")
        try:
            if str(APP_DIR) not in sys.path:
                sys.path.insert(0, str(APP_DIR))
            import shortcuts  # after zip apply so new icon + script are on disk
            shortcuts.refresh_app_shortcuts(APP_DIR, log=log)
        except Exception as exc:
            log(f"prečaci/ikona nisu osvježeni: {exc}")
        import shutil

        shutil.rmtree(pending, ignore_errors=True)
        start_app()
        return 0
    except Exception as exc:
        log(f"FAIL {exc}")
        updater.write_update_result(
            DATA_DIR,
            {
                "ok": False,
                "applied": False,
                "error": updater._safe_err(str(exc), updater.github_token(data_dir=DATA_DIR)),
                "message": "Ažuriranje nije uspjelo. Stara verzija je zadržana. Pogledaj data\\logs\\updater.log.",
            },
        )
        # Pokreni staru (ili vraćenu) aplikaciju da korisnik nije bez nje.
        try:
            start_app()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
