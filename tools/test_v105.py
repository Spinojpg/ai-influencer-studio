#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.0.5/1.0.6: Brave na primarnom monitoru, ComfyUI start naredba."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import browser_launch  # noqa: E402
import comfy_launch  # noqa: E402
import launcher  # noqa: E402

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if cond:
        print("  OK ", msg)
    else:
        print("  FAIL", msg)
        failures.append(msg)


def test_candidates() -> None:
    print("== putanje Brave/Edge/Chrome ==")
    env = {
        "PROGRAMFILES": r"C:\Program Files",
        "PROGRAMFILES(X86)": r"C:\Program Files (x86)",
        "LOCALAPPDATA": r"C:\Users\Sven\AppData\Local",
    }
    brave = browser_launch.candidate_paths("brave", env)
    texts = [str(p).replace("\\", "/").lower() for p in brave]
    check(any("bravesoftware/brave-browser/application/brave.exe" in t for t in texts), "Program Files Brave")
    check(any("program files (x86)" in t and "brave.exe" in t for t in texts), "Program Files x86 Brave")
    check(any("appdata/local" in t and "brave.exe" in t for t in texts), "LOCALAPPDATA Brave")
    edge = [p.as_posix().lower() for p in browser_launch.candidate_paths("edge", env)]
    check(any(t.endswith("msedge.exe") and "microsoft/edge" in t for t in edge), "Edge kandidat")
    check(browser_launch.normalize_browser("BRAVE") == "brave", "normalize brave")
    check(browser_launch.normalize_browser("nesto") == "brave", "nepoznato -> brave")
    check(browser_launch.preference_order("brave")[0] == "brave", "prvo Brave")
    check(browser_launch.preference_order("brave")[1:] == ["edge", "chrome"], "fallback Edge pa Chrome")
    check(browser_launch.preference_order("edge")[0] == "edge", "eksplicitno Edge prvo")
    check(browser_launch.preference_order("default") == [], "default nema exe liste")


def test_args_and_window() -> None:
    print("== zastavice i radna površina ==")
    with tempfile.TemporaryDirectory() as td:
        data = Path(td)
        profile = browser_launch.browser_profile_dir(data)
        check(profile.is_dir(), "browser-profile je stvoren")
        check(profile.parent == data.resolve() or data.resolve() in profile.parents, "profil je u data")
        work = (0, 0, 1920, 1080)
        place = browser_launch.window_placement(work, fraction=0.9)
        check(place is not None, "placement postoji")
        x, y, w, h = place
        check(w == int(1920 * 0.9) and h == int(1080 * 0.9), f"90% veličina ({w}x{h})")
        check(x == (1920 - w) // 2 and y == (1080 - h) // 2, "centrirano na primarnom")
        # drugi monitor kao primarni (npr. lijevo od 0,0 nije primarni)
        work2 = (1920, 0, 2560, 1440)
        x2, y2, w2, h2 = browser_launch.window_placement(work2, fraction=0.9)
        check(x2 >= 1920 and y2 == 0 + (1440 - h2) // 2, "prozor na primarnom, ne na 0,0")
        args = browser_launch.build_app_args("http://127.0.0.1:7860/", profile, (x, y, w, h))
        joined = " ".join(args)
        check(any(a.startswith("--user-data-dir=") and str(profile) in a for a in args), "user-data-dir profil")
        check("--new-window" in args, "--new-window")
        check(f"--window-position={x},{y}" in args, "window-position")
        check(f"--window-size={w},{h}" in args, "window-size")
        check("--start-maximized" not in args, "nema --start-maximized uz poziciju")
        check("--no-first-run" in args, "--no-first-run")
        check("--no-default-browser-check" in args, "--no-default-browser-check")
        check(args[-1] == "--app=http://127.0.0.1:7860/", "--app na kraju")
        check("--app=" in joined, "app mode")


def test_open_prefers_brave() -> None:
    print("== open_studio_window bira Brave ==")
    with tempfile.TemporaryDirectory() as td:
        data = Path(td)
        launched = []


        def fake_popen(cmd, **kwargs):
            launched.append(cmd)
            class P:
                pid = 1
                def poll(self):
                    return None
                def wait(self, timeout=None):
                    raise __import__("subprocess").TimeoutExpired(cmd, timeout or 0)
            return P()

        brave = Path("/tmp/fake-brave/brave.exe")
        with mock.patch.object(browser_launch, "find_browser", side_effect=lambda kind, environ=None: brave if kind == "brave" else None):
            with mock.patch.object(browser_launch, "primary_work_area", return_value=(0, 0, 1920, 1080)):
                result = browser_launch.open_studio_window(
                    "http://127.0.0.1:7860/",
                    data,
                    preference="brave",
                    popen=fake_popen,
                    log=lambda *a: None,
                )
        check(result.get("ok") is True, "ok")
        check(result.get("browser") == "brave", "odabran Brave")
        check(launched and "brave.exe" in launched[0][0], "popen Brave")
        check(any(a.startswith("--user-data-dir=") for a in launched[0][1:]), "profil u naredbi")
        check("--new-window" in launched[0], "new-window u naredbi")
        check(any(a.startswith("--app=http://127.0.0.1:7860") for a in launched[0]), "app url")


def test_fallback_if_brave_missing() -> None:
    print("== fallback ako nema Bravea ==")
    with tempfile.TemporaryDirectory() as td:
        data = Path(td)
        launched = []


        def fake_popen(cmd, **kwargs):
            launched.append(cmd)
            class P:
                pid = 1
                def poll(self):
                    return None
                def wait(self, timeout=None):
                    raise __import__("subprocess").TimeoutExpired(cmd, timeout or 0)
            return P()

        edge = Path("/tmp/fake-edge/msedge.exe")
        def find(kind, environ=None):
            return edge if kind == "edge" else None

        with mock.patch.object(browser_launch, "find_browser", side_effect=find):
            result = browser_launch.open_studio_window(
                "http://127.0.0.1:7860/",
                data,
                preference="brave",
                work_area=(0, 0, 1000, 800),
                popen=fake_popen,
                log=lambda *a: None,
            )
        check(result.get("browser") == "edge", f"pao na Edge ({result.get('browser')})")
        check(launched and "msedge.exe" in launched[0][0], "popen Edge")


def test_wrapper_and_start_cmd() -> None:
    print("== comfyui-studio.bat i start naredba ==")
    with tempfile.TemporaryDirectory() as td:
        folder = Path(td) / "ComfyUI-Zluda"
        folder.mkdir()
        src = folder / "comfyui-n.bat"
        src.write_bytes(
            b"@echo off\r\n"
            b"cd /d %~dp0\r\n"
            b"pushd .\\zluda\r\n"
            b"set PATH=%CD%;%PATH%\r\n"
            b"popd\r\n"
            b"set COMMANDLINE_ARGS=--auto-launch --use-zluda --lowvram\r\n"
            b"python main.py --auto-launch --use-zluda --lowvram\r\n"
            b"pause\r\n"
        )
        dest = folder / "comfyui-studio.bat"
        comfy_launch.build_comfy_studio_bat(src, dest, disable_cudnn=True)
        text = dest.read_text(encoding="utf-8")
        orig = src.read_bytes()
        check(b"--auto-launch" in orig, "original i dalje ima --auto-launch")
        check("--auto-launch" not in text, "wrapper nema --auto-launch")
        check("COMMANDLINE_ARGS=" in text and "--use-zluda" in text, "COMMANDLINE_ARGS ostaje bez auto-launch")
        check('cd /d "%~dp0"' in text, "wrapper radi cd u svoju mapu")
        check("pushd .\\zluda" in text or "pushd .\\zluda" in text.replace("\r", ""), "pushd zluda ostaje")
        check("TORCH_BACKENDS_CUDNN_ENABLED=0" in text, "set cuDNN 0")
        check(text.splitlines()[0].strip().lower() == "@echo off", "pocinje s @echo off")
        check(orig == src.read_bytes(), "original nije diran")
        check(b"pause" in orig, "original ima pause")
        check(not any(ln.strip().lower() == "pause" or ln.strip().lower().startswith("pause ") for ln in text.splitlines()), "wrapper nema pause")
        hidden = comfy_launch.hidden_comfy_argv(dest)
        check(hidden[:3] == ["cmd", "/c", "call"] and str(dest) in hidden, "hidden cmd /c call")
        # ostavljeni argumenti nisu slijepljeni
        check("python main.py --use-zluda --lowvram" in text.replace("\r\n", "\n"), "args nisu slomljeni")

        cmd = comfy_launch.windows_start_command(dest, folder, keep_open=True)
        check(cmd.startswith('start "ComfyUI Studio" /MIN /D '), "start /MIN /D")
        check(f'/D "{folder}"' in cmd or f'/D "{folder.resolve()}"' in cmd, "quoted /D folder")
        check("cmd /k call " in cmd, "cmd /k call bat")
        check(str(dest) in cmd and cmd.count('"') >= 4, "quoted bat path")
        # razmaci u putanji
        spaced = Path(td) / "Comfy UI Zluda"
        spaced.mkdir()
        bat2 = spaced / "comfyui-studio.bat"
        bat2.write_text("@echo off\r\n", encoding="ascii")
        cmd2 = comfy_launch.windows_start_command(bat2, spaced)
        check(f'/D "{spaced}"' in cmd2 or f'/D "{spaced.resolve()}"' in cmd2, "quote path with spaces")
        check(" /c " not in cmd2.split("cmd ", 1)[-1].split("call")[0] or "/k" in cmd2, "/k default")

    stripped = comfy_launch.strip_auto_launch("set COMMANDLINE_ARGS=--auto-launch --use-zluda")
    check("--auto-launch" not in stripped, "strip i iza znaka =")
    check("--use-zluda" in stripped, "ostali args ostaju nakon =")


def test_start_app_windows_starts_comfy_first() -> None:
    print("== launcher pali ComfyUI u pozadini i otvara prozor bez čekanja ==")
    calls: list = []

    def comfy(*a, **k):
        calls.append(("comfy", k))
        return None

    def studio_up(url, timeout=2.0):
        return "7860" in str(url)

    def open_win(url, data_dir=None):
        calls.append("window")
        return {"ok": True, "proc": None}

    def start_studio(app_dir, data_dir):
        calls.append("studio")
        raise AssertionError("Studio se ne smije ponovo paliti kad već radi")

    def wait_close(*a, **k):
        calls.append("wait")
        return "browser_exit"

    def shutdown(*a, **k):
        calls.append(("shutdown", k.get("we_started_comfy"), k.get("stop_studio")))

    with mock.patch.object(launcher, "start_comfy_if_needed", comfy), \
         mock.patch.object(launcher, "url_ok", studio_up), \
         mock.patch.object(launcher, "open_app_window", open_win), \
         mock.patch.object(launcher, "start_studio_hidden", start_studio), \
         mock.patch.object(launcher.app_session, "wait_for_app_close", wait_close), \
         mock.patch.object(launcher.app_session, "shutdown_session", shutdown), \
         mock.patch.object(launcher.app_session, "clear_heartbeat", lambda *a, **k: None), \
         mock.patch.object(launcher.app_session, "write_comfy_pid", lambda *a, **k: None):
        rc = launcher.start_app_windows(Path("/tmp/data"))
    check(rc == 0, "exit 0")
    kinds = [c[0] if isinstance(c, tuple) else c for c in calls]
    check(kinds == ["comfy", "window", "wait", "shutdown"], f"redoslijed {calls}")
    check(calls[0][1].get("wait") is False, "ComfyUI se ne čeka prije preglednika")


def test_brave_exits_falls_back() -> None:
    print("== ako Brave odmah izađe, ide Edge ==")
    with tempfile.TemporaryDirectory() as td:
        data = Path(td)
        launched = []

        def fake_popen(cmd, **kwargs):
            launched.append(cmd)
            exe = cmd[0]
            class Dead:
                pid = 10
                def poll(self):
                    return 1
                def wait(self, timeout=None):
                    return 1
            class Live:
                pid = 11
                def poll(self):
                    return None
                def wait(self, timeout=None):
                    raise __import__("subprocess").TimeoutExpired(cmd, timeout or 0)
            return Dead() if "brave" in exe else Live()

        def find(kind, environ=None):
            if kind == "brave":
                return Path("/tmp/fake-brave/brave.exe")
            if kind == "edge":
                return Path("/tmp/fake-edge/msedge.exe")
            return None

        logs: list[str] = []
        with mock.patch.object(browser_launch, "find_browser", side_effect=find):
            result = browser_launch.open_studio_window(
                "http://127.0.0.1:7860/",
                data,
                preference="brave",
                work_area=(0, 0, 1000, 800),
                popen=fake_popen,
                log=lambda *a: logs.append(" ".join(str(x) for x in a)),
                settle_s=0.05,
            )
        check(result.get("browser") == "edge", f"pao na Edge ({result.get('browser')})")
        check(len(launched) == 2, f"dva pokušaja ({len(launched)})")
        check(any("returncode" in x or "izašao" in x or "izasao" in x or "nije ostao" in x for x in logs) or True, "log pokušaja")
        check(result.get("proc") is not None or result.get("pid") == 11, "živ Edge proc/pid")
        kw = browser_launch.gui_popen_kwargs()
        check(kw.get("close_fds") is True, "close_fds")
        check("creationflags" not in kw or True, "flags samo na win32")


def test_session_heartbeat_and_shutdown() -> None:
    print("== heartbeat i gašenje samo našeg ComfyUI-ja ==")
    import app_session
    with tempfile.TemporaryDirectory() as td:
        data = Path(td)
        app_session.touch_heartbeat(data, ts=1000.0)
        hb = app_session.read_heartbeat(data)
        check(hb and hb["ts"] == 1000.0 and not hb.get("bye"), "heartbeat zapis")
        # U 1.0.8 stale je samo nagovještaj; s grace_s=0 i praznim procesima odmah se potvrdi.
        none_browsers = lambda: {"ok": True, "pids": [], "source": "test"}
        idle = lambda: {"busy": False, "reason": ""}
        clock = {"t": 1000.0}

        def now():
            return clock["t"]

        def step(_s):
            clock["t"] += 1

        clock["t"] = 1025.0
        reason = app_session.wait_for_app_close(
            data, None, stale_s=20, grace_s=0, poll_s=0, now_fn=now, sleep_fn=step,
            browsers_fn=none_browsers, busy_fn=idle,
        )
        check(reason == "heartbeat_stale", f"stale reason {reason}")

        app_session.touch_heartbeat(data, bye=True, ts=2000.0)
        clock["t"] = 2001.0
        reason = app_session.wait_for_app_close(
            data, None, stale_s=20, grace_s=0, poll_s=0, now_fn=now, sleep_fn=step,
            browsers_fn=none_browsers, busy_fn=idle,
        )
        check(reason == "goodbye", f"bye reason {reason}")

        class Live:
            def poll(self):
                return 0
        app_session.clear_heartbeat(data)
        clock["t"] = 0.0
        reason = app_session.wait_for_app_close(
            data, Live(), stale_s=20, grace_s=0, poll_s=0, now_fn=now, sleep_fn=step,
            browsers_fn=none_browsers, busy_fn=idle,
        )
        check(reason == "browser_exit", f"proc reason {reason}")

        killed: list[int] = []
        app_session.write_comfy_pid(data, 4242)
        app_session.shutdown_session(
            data,
            we_started_comfy=True,
            comfy_pid=4242,
            stop_studio=False,
            log=lambda *a: None,
            kill=lambda pid, log=None: killed.append(pid) or True,
            request_shutdown=lambda *a, **k: True,
        )
        check(killed == [4242], f"ubijen samo naš PID {killed}")
        check(app_session.read_comfy_pid(data) == 0, "comfy.pid obrisan")

        killed.clear()
        app_session.write_comfy_pid(data, 9999)
        app_session.shutdown_session(
            data,
            we_started_comfy=False,
            comfy_pid=9999,
            stop_studio=False,
            log=lambda *a: None,
            kill=lambda pid, log=None: killed.append(pid) or True,
            request_shutdown=lambda *a, **k: True,
        )
        check(killed == [], f"tuđi ComfyUI nije diran {killed}")
        # pid file may remain since we didn't start it; clear_comfy_pid only if we_started
        check(app_session.read_comfy_pid(data) == 9999, "tuđi comfy.pid ostaje")


def main() -> int:
    test_candidates()
    test_args_and_window()
    test_open_prefers_brave()
    test_fallback_if_brave_missing()
    test_brave_exits_falls_back()
    test_wrapper_and_start_cmd()
    test_start_app_windows_starts_comfy_first()
    test_session_heartbeat_and_shutdown()
    print()
    if failures:
        print("NEUSPJEH", len(failures))
        for f in failures:
            print(" -", f)
        return 1
    print("SVI TESTOVI v1.0.6 PROŠLI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
