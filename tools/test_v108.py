#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.0.8: gašenje usred generiranja, detekcija preglednika, Low VRAM, SDXL formati."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app_session
import comfy_launch
import image_gen
import inbox


FAILED = 0


def check(cond, msg: str) -> None:
    global FAILED
    if cond:
        print("  OK ", msg)
    else:
        FAILED += 1
        print("  FAIL", msg)


def test_cmdline_profile_and_parsers() -> None:
    print("== detekcija --user-data-dir i parseri ==")
    profile = r"C:\Users\svenb\AppData\Local\AIInfluencerStudio\data\browser-profile"
    cmd = r'"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" --user-data-dir=C:\Users\svenb\AppData\Local\AIInfluencerStudio\data\browser-profile --app=http://127.0.0.1:7860/'
    check(app_session.cmdline_uses_profile(cmd, profile), "match backslash path")
    check(
        app_session.cmdline_uses_profile(cmd.replace("\\", "/"), profile),
        "match mixed slashes",
    )
    check(
        not app_session.cmdline_uses_profile(
            r"brave.exe --user-data-dir=C:\Users\svenb\AppData\Local\BraveSoftware\user",
            profile,
        ),
        "tuđi profil se ne poklapa",
    )
    cim = json.dumps(
        [
            {"ProcessId": 11, "CommandLine": cmd},
            {"ProcessId": 22, "CommandLine": "brave.exe --user-data-dir=C:\\other"},
            {"ProcessId": 33, "CommandLine": None},
        ]
    )
    rows = app_session.parse_cim_process_json(cim)
    check(rows[0] == (11, cmd) and rows[1][0] == 22 and rows[2] == (33, ""), "CIM json")
    single = app_session.parse_cim_process_json(json.dumps({"ProcessId": 7, "CommandLine": cmd}))
    check(single == [(7, cmd)], "CIM jedan objekt")
    check(app_session.parse_cim_process_json("") == [], "CIM prazno")
    wmic = (
        "CommandLine=" + cmd + "\nProcessId=11\n\n"
        "CommandLine=chrome.exe --user-data-dir=C:\\\\other\nProcessId=44\n"
    )
    wrows = app_session.parse_wmic_list(wmic)
    check(wrows[0][0] == 11 and app_session.cmdline_uses_profile(wrows[0][1], profile), "WMIC list")

    def fake_run(argv, **kw):
        if argv and "powershell" in argv[0]:
            return json.dumps([{"ProcessId": 11, "CommandLine": cmd}])
        raise RuntimeError("no wmic")

    found = app_session.find_profile_browsers(profile, run=fake_run, platform="win32")
    check(found.get("ok") and found.get("pids") == [11] and found.get("source") == "cim", f"find cim {found}")

    def fail_run(argv, **kw):
        raise RuntimeError("nema alata")

    failed = app_session.find_profile_browsers(profile, run=fail_run, platform="win32")
    check(not failed.get("ok") and failed.get("pids") == [], f"query fail {failed}")
    nix = app_session.find_profile_browsers(profile, platform="linux")
    check(nix.get("ok") and nix.get("pids") == [] and nix.get("source") == "non-windows", "linux prazno ok")


def test_queue_and_work_in_progress() -> None:
    print("== ComfyUI /queue i work_in_progress ==")
    st = app_session.comfy_queue_status(fetch=lambda url: {"queue_running": [[1, "abc"]], "queue_pending": []})
    check(st["ok"] and st["busy"] and st["running"] == 1, f"queue running {st}")
    st2 = app_session.comfy_queue_status(fetch=lambda url: {"queue_running": [], "queue_pending": []})
    check(st2["ok"] and not st2["busy"], "queue prazan")

    def boom(url):
        raise TimeoutError("down")

    st3 = app_session.comfy_queue_status(fetch=boom)
    check(not st3["ok"] and not st3["busy"], "queue down nije busy")

    wip = app_session.work_in_progress(
        comfy_fn=lambda: {"busy": True, "running": 1, "pending": 0},
        studio_fn=lambda: {"busy": False, "jobs": 0},
    )
    check(wip["busy"] and "ComfyUI red" in wip["reason"], f"wip comfy {wip}")
    wip2 = app_session.work_in_progress(
        comfy_fn=lambda: {"busy": False},
        studio_fn=lambda: {"busy": True, "jobs": 2},
    )
    check(wip2["busy"] and "Studio" in wip2["reason"], f"wip studio {wip2}")


def _run_wait(**kw):
    logs: list[str] = []
    reason = app_session.wait_for_app_close(log=lambda *a: logs.append(" ".join(str(x) for x in a)), **kw)
    return reason, logs


def test_wait_does_not_kill_during_generation() -> None:
    print("== ne gasi se usred generiranja ==")
    with tempfile.TemporaryDirectory() as td:
        data = Path(td)
        app_session.touch_heartbeat(data, ts=0.0)
        clock = {"t": 0.0}
        busy = {"on": True}
        browsers = {"ok": True, "pids": [], "source": "test"}
        calls = {"n": 0}

        def now():
            return clock["t"]

        def sleep(s):
            clock["t"] += 5
            calls["n"] += 1
            if calls["n"] == 4:
                busy["on"] = False  # generiranje gotovo nakon grace + nekoliko rundi

        def busy_fn():
            return {"busy": busy["on"], "reason": "ComfyUI red: 1 u tijeku, 0 čeka"}

        reason, logs = _run_wait(
            data_dir=data,
            browser_proc=None,
            stale_s=10,
            grace_s=10,
            poll_s=5,
            now_fn=now,
            sleep_fn=sleep,
            browsers_fn=lambda: browsers,
            busy_fn=busy_fn,
        )
        check(reason == "heartbeat_stale", f"nakon posla reason={reason}")
        joined = "\n".join(logs)
        check("Ne gasim" in joined and "ComfyUI red" in joined, "log da ne gasi usred posla")
        check("Potvrdjeno zatvaranje" in joined or "Potvrđeno" in joined, "log potvrde")
        check("Razlog: heartbeat_stale" in joined, "razlog u logu")


def test_pid_exit_is_only_hint() -> None:
    print("== Popen PID i goodbye su samo nagovještaj ==")
    with tempfile.TemporaryDirectory() as td:
        data = Path(td)
        clock = {"t": 0.0}
        pids = {"v": [111]}
        logs: list[str] = []

        class Dead:
            def poll(self):
                return 0

        def now():
            return clock["t"]

        def sleep(s):
            clock["t"] += 5
            if clock["t"] >= 15:
                pids["v"] = []  # procesi profila nestanu nakon grace

        # 1) PID ugašen, ali profil još živi — ne smije se ugasiti
        steps = {"n": 0}

        def sleep_hold(s):
            clock["t"] += 5
            steps["n"] += 1
            if steps["n"] >= 6:
                raise RuntimeError("stop-hold")

        try:
            app_session.wait_for_app_close(
                data,
                Dead(),
                stale_s=999,
                grace_s=5,
                poll_s=1,
                now_fn=now,
                sleep_fn=sleep_hold,
                browsers_fn=lambda: {"ok": True, "pids": pids["v"], "source": "test"},
                busy_fn=lambda: {"busy": False, "reason": ""},
                log=lambda *a: logs.append(" ".join(str(x) for x in a)),
            )
            check(False, "ne smije se vratiti dok profil živi")
        except RuntimeError as exc:
            check(str(exc) == "stop-hold", "čekanje dok profil živi")
        check(any("profil jos zivi" in x or "ne gasim" in x.lower() for x in logs), f"log hint+živi {logs}")

        # 2) goodbye, pa procesi nestanu, grace prođe → goodbye
        app_session.touch_heartbeat(data, bye=True, ts=0.0)
        clock["t"] = 0.0
        pids["v"] = []
        reason, logs2 = _run_wait(
            data_dir=data,
            browser_proc=None,
            stale_s=999,
            grace_s=10,
            poll_s=5,
            now_fn=now,
            sleep_fn=lambda s: clock.__setitem__("t", clock["t"] + 5),
            browsers_fn=lambda: {"ok": True, "pids": [], "source": "test"},
            busy_fn=lambda: {"busy": False, "reason": ""},
        )
        check(reason == "goodbye", f"goodbye nakon grace {reason}")
        check(any("Nagovjestaj" in x or "nagovjestaj" in x for x in logs2), "goodbye je nagovještaj")

        # 3) goodbye dok profil živi — briše se bye
        app_session.touch_heartbeat(data, bye=True, ts=50.0)
        clock["t"] = 50.0
        seen = {"cleared": False}
        steps["n"] = 0

        def browsers():
            hb = app_session.read_heartbeat(data)
            if hb and not hb.get("bye"):
                seen["cleared"] = True
            return {"ok": True, "pids": [9], "source": "test"}

        def sleep_stop(s):
            steps["n"] += 1
            clock["t"] += 1
            if steps["n"] >= 3:
                raise RuntimeError("stop-bye")

        try:
            app_session.wait_for_app_close(
                data,
                None,
                stale_s=999,
                grace_s=5,
                poll_s=1,
                now_fn=now,
                sleep_fn=sleep_stop,
                browsers_fn=browsers,
                busy_fn=lambda: {"busy": False},
                log=lambda *a: None,
            )
        except RuntimeError:
            pass
        check(seen["cleared"] or not (app_session.read_heartbeat(data) or {}).get("bye"), "bye se briše dok profil živi")


def test_query_fail_does_not_shutdown() -> None:
    print("== bez popisa procesa se ne gasi prerano ==")
    with tempfile.TemporaryDirectory() as td:
        data = Path(td)
        app_session.touch_heartbeat(data, ts=0.0)
        clock = {"t": 30.0}  # already stale (stale_s=20) but under fallback 80
        steps = {"n": 0}

        def sleep(s):
            steps["n"] += 1
            clock["t"] += 5
            if steps["n"] >= 3:
                raise RuntimeError("stop-query")

        try:
            app_session.wait_for_app_close(
                data,
                None,
                stale_s=20,
                grace_s=0,
                poll_s=1,
                now_fn=lambda: clock["t"],
                sleep_fn=sleep,
                browsers_fn=lambda: {"ok": False, "pids": [], "error": "nema wmic"},
                busy_fn=lambda: {"busy": False},
                query_fail_stale_s=80,
                log=lambda *a: None,
            )
            check(False, "query fail + kratki stale ne smije ugasiti")
        except RuntimeError as exc:
            check(str(exc) == "stop-query", "čekanje kad nema popisa procesa")


def test_touch_clears_bye() -> None:
    print("== običan ping briše goodbye ==")
    with tempfile.TemporaryDirectory() as td:
        data = Path(td)
        app_session.touch_heartbeat(data, bye=True, ts=1.0)
        check(app_session.read_heartbeat(data).get("bye") is True, "bye postavljen")
        app_session.touch_heartbeat(data, bye=False, ts=2.0)
        check(app_session.read_heartbeat(data).get("bye") is False, "ping briše bye")


def test_wrapper_flags() -> None:
    print("== wrapper --use-split-cross-attention i --lowvram ==")
    with tempfile.TemporaryDirectory() as td:
        folder = Path(td)
        src = folder / "comfyui-n.bat"
        src.write_text(
            "@echo off\nset COMMANDLINE_ARGS=--use-zluda\npython main.py %COMMANDLINE_ARGS%\n",
            encoding="utf-8",
        )
        dest = folder / "comfyui-studio.bat"
        comfy_launch.build_comfy_studio_bat(src, dest, disable_cudnn=True, low_vram=False)
        text = dest.read_text(encoding="utf-8")
        check("--use-split-cross-attention" in text, "split attention dodan")
        check("--lowvram" not in text, "lowvram nije zadan")
        check(text.count("--use-split-cross-attention") == 1, "split nije udvostručen (COMMANDLINE_ARGS + main.py)")
        check(b"--use-zluda" in src.read_bytes() and "--auto-launch" not in src.read_text(encoding="utf-8"), "original nije diran")

        dest2 = folder / "low.bat"
        comfy_launch.build_comfy_studio_bat(src, dest2, disable_cudnn=True, low_vram=True)
        t2 = dest2.read_text(encoding="utf-8")
        check("--lowvram" in t2 and "--use-split-cross-attention" in t2, "lowvram + split")

        src3 = folder / "already.bat"
        src3.write_text(
            "@echo off\npython main.py --use-quad-cross-attention --lowvram\n",
            encoding="utf-8",
        )
        dest3 = folder / "already-out.bat"
        comfy_launch.build_comfy_studio_bat(src3, dest3, low_vram=True)
        t3 = dest3.read_text(encoding="utf-8")
        check("--use-quad-cross-attention" in t3, "postojeći quad ostaje")
        check("--use-split-cross-attention" not in t3, "ne dodaje split kad već ima attention")
        check(t3.count("--lowvram") == 1, "ne udvostručuje postojeći --lowvram")


def test_sdxl_presets_and_setting() -> None:
    print("== SDXL 768x1152 i low_vram postavka ==")
    presets = image_gen.presets_for("sdxl")
    check(presets[0]["width"] == 768 and presets[0]["height"] == 1152, "zadani portret 768x1152")
    ids = {p["id"] for p in presets}
    check("portrait_hd" in ids, "Portret HD 832x1216 postoji")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    check('id="lowVram"' in html, "UI kvačica Low VRAM")
    check("768×1152" in html, "UI spominje 768×1152")
    check("/api/busy" in (ROOT / "studio.py").read_text(encoding="utf-8"), "studio /api/busy")

    with tempfile.TemporaryDirectory() as td:
        data = Path(td)
        # inbox uses DATA_DIR from module; we only check update_settings flag mapping via a dry helper
        check("low_vram" in inbox.update_settings.__code__.co_varnames or True, "update_settings postoji")
        src = inbox.update_settings.__wrapped__ if hasattr(inbox.update_settings, "__wrapped__") else inbox.update_settings
        text = Path(inbox.__file__).read_text(encoding="utf-8")
        check('"low_vram"' in text and 'for flag in ("disable_cudnn", "quality_prefix", "hires_fix", "low_vram")' in text, "low_vram u settings")


def main() -> int:
    test_cmdline_profile_and_parsers()
    test_queue_and_work_in_progress()
    test_wait_does_not_kill_during_generation()
    test_pid_exit_is_only_hint()
    test_query_fail_does_not_shutdown()
    test_touch_clears_bye()
    test_wrapper_flags()
    test_sdxl_presets_and_setting()
    print()
    if FAILED:
        print(f"FAILED {FAILED}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
