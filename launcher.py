#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pokretač Windows aplikacije: update, ComfyUI, skriveni poslužitelj, Edge --app."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

# Osiguraj da je mapa aplikacije na sys.path i radni dir.
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
os.chdir(APP_DIR)

import applog  # noqa: E402
import comfy_launch  # noqa: E402
import inbox  # noqa: E402
import updater  # noqa: E402

STUDIO_URL = os.environ.get("STUDIO_URL", "http://127.0.0.1:7860/")
COMFY_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
COMFY_DIR_DEFAULT = r"C:\ComfyUI-Zluda"
COMFY_WAIT_S = int(os.environ.get("COMFYUI_WAIT_SECONDS", "300"))
STUDIO_WAIT_S = int(os.environ.get("STUDIO_WAIT_SECONDS", "60"))


def _py_console() -> str:
    applog.safe_stdio()
    return ""


def find_python(prefer_w: bool = True) -> list[str]:
    venv_w = Path(r"C:\ComfyUI-Zluda\venv\Scripts\pythonw.exe")
    venv = Path(r"C:\ComfyUI-Zluda\venv\Scripts\python.exe")
    if prefer_w and venv_w.is_file():
        return [str(venv_w)]
    if venv.is_file():
        return [str(venv)]
    if prefer_w:
        pyw = shutil.which("pyw")
        if pyw:
            return [pyw, "-3.11"]
    py = shutil.which("py")
    if py:
        return [py, "-3.11"]
    exe = sys.executable
    if prefer_w and exe and exe.lower().endswith("python.exe"):
        candidate = Path(exe).with_name("pythonw.exe")
        if candidate.is_file():
            return [str(candidate)]
    return [exe or "python"]


def url_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except Exception:
        return False


def wait_url(url: str, seconds: int) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if url_ok(url):
            return True
        time.sleep(1.2)
    return False


def comfy_dir() -> Path:
    raw = (os.environ.get("COMFYUI_DIR") or "").strip() or COMFY_DIR_DEFAULT
    return Path(raw)


def start_comfy_if_needed() -> subprocess.Popen | None:
    """Pokreni comfyui-studio.bat (generiran iz comfyui-n.bat) u minimiziranom prozoru."""
    if url_ok(COMFY_URL + "/system_stats"):
        print("ComfyUI vec radi.")
        return None
    folder = comfy_dir()
    src = folder / "comfyui-n.bat"
    if not src.is_file():
        print("UPOZORENJE: Nema", src, "- preskacem pokretanje ComfyUI-ja.")
        return None
    try:
        inbox.init_db()
    except Exception:
        pass
    disable_cudnn = comfy_launch.setting_on(inbox.get_setting("disable_cudnn", "1"), True)
    wrapper = folder / comfy_launch.WRAPPER_NAME
    try:
        comfy_launch.build_comfy_studio_bat(src, wrapper, disable_cudnn=disable_cudnn)
        run_bat = wrapper
        print("Napravljen wrapper", wrapper, "(original comfyui-n.bat nije diran)")
    except Exception as exc:
        print("UPOZORENJE: nisam mogao napraviti comfyui-studio.bat:", exc)
        run_bat = src
    env = comfy_launch.comfy_process_env(os.environ, disable_cudnn=disable_cudnn)
    print("Pokrecem ComfyUI iz", folder, "preko", run_bat.name)
    if disable_cudnn:
        print("TORCH_BACKENDS_CUDNN_ENABLED=0 je u okruzenju procesa (ne samo u .bat).")
    try:
        log_path = applog.logs_dir(inbox.DATA_DIR) / "comfyui.log"
        with log_path.open("a", encoding="utf-8") as fh:
            from datetime import datetime
            fh.write(
                f"{datetime.now().isoformat(timespec='seconds')} pokrecem {run_bat} "
                f"(cwd={folder}, cudnn_disabled={disable_cudnn})\n"
            )
    except Exception:
        log_path = None
    proc = None
    if sys.platform == "win32":
        flags = int(getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010))
        flags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001))
        startup.wShowWindow = 6  # SW_MINIMIZE, vidljiv prozor
        proc = subprocess.Popen(
            ["cmd", "/c", run_bat.name],
            cwd=str(folder),
            env=env,
            startupinfo=startup,
            creationflags=flags,
            close_fds=False,
            stdin=None,
            stdout=None,
            stderr=None,
        )
    else:
        proc = subprocess.Popen(
            ["bash", str(run_bat)],
            cwd=str(folder),
            env=env,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
        )
    print("Cekam ComfyUI na", COMFY_URL, "do", COMFY_WAIT_S, "s ...")
    ok = wait_url(COMFY_URL + "/system_stats", COMFY_WAIT_S)
    if ok:
        print("ComfyUI je spreman.")
    else:
        print("UPOZORENJE: ComfyUI nije odgovorio na vrijeme. Studio ce se ipak pokrenuti.")
    if log_path is not None:
        try:
            with log_path.open("a", encoding="utf-8") as fh:
                from datetime import datetime
                fh.write(
                    f"{datetime.now().isoformat(timespec='seconds')} "
                    f"{'spreman na ' + COMFY_URL if ok else 'nije odgovorio u roku'}\n"
                )
        except Exception:
            pass
    return proc


def start_studio_hidden(app_dir: Path, data_dir: Path) -> subprocess.Popen:
    cmd = find_python(prefer_w=True) + [str(app_dir / "studio.py")]
    env = os.environ.copy()
    env["STUDIO_NO_BROWSER"] = "1"
    env["STUDIO_APP_DIR"] = str(app_dir)
    env["STUDIO_DATA_DIR"] = str(data_dir)
    print("Pokrecem Studio posluzitelj...")
    kwargs = {"cwd": str(app_dir), "env": env, "close_fds": True}
    if sys.platform == "win32":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0  # hidden
        kwargs["startupinfo"] = startup
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return subprocess.Popen(cmd, **kwargs)


def _edge_candidates() -> list[Path]:
    names = []
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if not base:
            continue
        names.append(Path(base) / r"Microsoft\Edge\Application\msedge.exe")
        names.append(Path(base) / r"Google\Chrome\Application\chrome.exe")
    # Also typical user chrome
    local = os.environ.get("LOCALAPPDATA")
    if local:
        names.append(Path(local) / r"Google\Chrome\Application\chrome.exe")
    return names


def open_app_window(url: str) -> None:
    url = url if "://" in url else "http://" + url
    if sys.platform == "win32":
        for exe in _edge_candidates():
            if not exe.is_file():
                continue
            try:
                subprocess.Popen([str(exe), f"--app={url}"], close_fds=True)
                print("Otvaram", exe.name, "u app rezimu:", url)
                return
            except OSError:
                continue
    try:
        webbrowser.open(url)
        print("Otvaram zadani preglednik:", url)
    except Exception as exc:
        print("Ne mogu otvoriti preglednik:", exc)


def maybe_update(app_dir: Path, data_dir: Path, force: bool = False) -> bool:
    """Vrati True ako je update primijenjen i treba relansirati launcher."""
    if os.environ.get("STUDIO_SKIP_UPDATE") == "1" and not force:
        return False
    token = updater.github_token(data_dir=inbox.DATA_DIR)
    try:
        info = updater.check_for_update(app_dir, data_dir, token=token)
    except Exception as exc:
        print("Provjera azuriranja nije uspjela:", updater._safe_err(str(exc), token))
        return False
    if not info.get("configured"):
        print(info.get("message") or "Update izvor nije podesen.")
        return False
    if not info.get("newer") and not force:
        print(info.get("message") or "Nema novije verzije.")
        return False
    if not info.get("newer"):
        return False
    print("Dostupna je verzija", info.get("latest"), "- preuzimam...")
    try:
        result = updater.perform_update(app_dir, data_dir, token=token)
    except Exception as exc:
        print("Azuriranje nije uspjelo:", updater._safe_err(str(exc), token))
        updater.write_update_result(
            data_dir,
            {
                "ok": False,
                "applied": False,
                "error": updater._safe_err(str(exc), token),
                "message": "Azuriranje nije uspjelo. Stara verzija je zadrzana.",
            },
        )
        return False
    print(result.get("message") or "Azurirano.")
    return bool(result.get("applied"))


def relaunch_self() -> int:
    cmd = find_python(prefer_w=False) + [str(APP_DIR / "launcher.py"), "--no-update"]
    env = os.environ.copy()
    env["STUDIO_SKIP_UPDATE"] = "1"
    if sys.platform == "win32":
        subprocess.Popen(cmd, cwd=str(APP_DIR), env=env, close_fds=True)
    else:
        os.execv(cmd[0], cmd)
        return 0
    return 0


def apply_pending(app_dir: Path, data_dir: Path) -> bool:
    pending = Path(data_dir) / "pending-update"
    # meta.json may contain zip path and notes
    meta_path = pending / "meta.json"
    zip_path = pending / "studio.zip"
    if not zip_path.is_file() and meta_path.is_file():
        try:
            import json
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("zip_path"):
                zip_path = Path(meta["zip_path"])
        except Exception:
            pass
    if not zip_path.is_file():
        return False
    # Pricekaj da stari posluzitelj ugasi port.
    deadline = time.time() + 30
    while time.time() < deadline and url_ok(STUDIO_URL, timeout=0.8):
        time.sleep(0.5)
    token = updater.github_token(data_dir=inbox.DATA_DIR)
    try:
        backup = updater.apply_zip(zip_path, Path(app_dir), Path(app_dir).parent / "backup")
        ver = updater.load_version(app_dir).get("version")
        notes = ""
        if meta_path.is_file():
            try:
                import json
                notes = json.loads(meta_path.read_text(encoding="utf-8")).get("notes") or ""
            except Exception:
                notes = ""
        updater.write_update_result(
            data_dir,
            {
                "ok": True,
                "applied": True,
                "updated_to": ver,
                "changelog": notes,
                "backup": str(backup),
                "message": f"Ažurirano na verziju {ver}",
            },
        )
        shutil.rmtree(pending, ignore_errors=True)
        return True
    except Exception as exc:
        updater.write_update_result(
            data_dir,
            {
                "ok": False,
                "applied": False,
                "error": updater._safe_err(str(exc), token),
                "message": "Azuriranje nije uspjelo. Stara verzija je zadrzana.",
            },
        )
        return False


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    apply = "--apply-pending" in argv
    no_update = "--no-update" in argv or os.environ.get("STUDIO_SKIP_UPDATE") == "1"
    force = "--force-update" in argv

    inbox.configure_paths(APP_DIR)
    data_dir = inbox.DATA_DIR
    applog.setup(data_dir, "launcher")
    _py_console()
    inbox.load_dotenv(inbox.ENV_PATH)
    try:
        inbox.init_db()
    except Exception:
        pass
    inbox.load_dotenv(APP_DIR / ".env")
    updater.write_default_update_config(data_dir)

    if apply:
        apply_pending(APP_DIR, data_dir)
        no_update = True

    if not no_update:
        if maybe_update(APP_DIR, data_dir, force=force):
            return relaunch_self()

    if url_ok(STUDIO_URL):
        print("Studio vec radi, otvaram prozor.")
        open_app_window(STUDIO_URL)
        return 0

    start_comfy_if_needed()
    proc = start_studio_hidden(APP_DIR, data_dir)
    if not wait_url(STUDIO_URL, STUDIO_WAIT_S):
        print("GRESKA: Studio posluzitelj nije krenuo na", STUDIO_URL)
        if proc.poll() is not None:
            print("Proces je zavrsio sa kodom", proc.returncode)
        return 1
    open_app_window(STUDIO_URL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
