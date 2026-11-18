#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.0.5: Brave na primarnom monitoru, ComfyUI start naredba."""

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
        args = browser_launch.build_app_args("http://127.0.0.1:7860/", profile, (x, y, w, h), maximized=True)
        joined = " ".join(args)
        check(any(a.startswith("--user-data-dir=") and str(profile) in a for a in args), "user-data-dir profil")
        check("--new-window" in args, "--new-window")
        check(f"--window-position={x},{y}" in args, "window-position")
        check(f"--window-size={w},{h}" in args, "window-size")
        check("--start-maximized" in args, "--start-maximized nakon pozicije")
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
    print("== launcher pali ComfyUI i kad Studio već radi ==")
    calls: list[str] = []

    def comfy():
        calls.append("comfy")
        return None

    def studio_up(url, timeout=2.0):
        return "7860" in str(url)

    def open_win(url, data_dir=None):
        calls.append("window")

    def start_studio(app_dir, data_dir):
        calls.append("studio")
        raise AssertionError("Studio se ne smije ponovo paliti kad već radi")

    with mock.patch.object(launcher, "start_comfy_if_needed", comfy), \
         mock.patch.object(launcher, "url_ok", studio_up), \
         mock.patch.object(launcher, "open_app_window", open_win), \
         mock.patch.object(launcher, "start_studio_hidden", start_studio):
        rc = launcher.start_app_windows(Path("/tmp/data"))
    check(rc == 0, "exit 0")
    check(calls == ["comfy", "window"], f"redoslijed {calls}")


def main() -> int:
    test_candidates()
    test_args_and_window()
    test_open_prefers_brave()
    test_fallback_if_brave_missing()
    test_wrapper_and_start_cmd()
    test_start_app_windows_starts_comfy_first()
    print()
    if failures:
        print("NEUSPJEH", len(failures))
        for f in failures:
            print(" -", f)
        return 1
    print("SVI TESTOVI v1.0.5 PROŠLI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
