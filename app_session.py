#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sesija aplikacije: heartbeat prozora, gašenje Studija i ComfyUI stabla koje smo mi pokrenuli."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HEARTBEAT_NAME = "heartbeat.json"
COMFY_PID_NAME = "comfy.pid"
STUDIO_PID_NAME = "studio.pid"


def _pid_path(data_dir: Path, name: str) -> Path:
    return Path(data_dir) / name


def write_pid(data_dir: Path, name: str, pid: int) -> None:
    path = _pid_path(data_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(int(pid)), encoding="utf-8")


def read_pid(data_dir: Path, name: str) -> int:
    path = _pid_path(data_dir, name)
    if not path.is_file():
        return 0
    try:
        return int(path.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return 0


def clear_pid(data_dir: Path, name: str) -> None:
    path = _pid_path(data_dir, name)
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def write_comfy_pid(data_dir: Path, pid: int) -> None:
    write_pid(data_dir, COMFY_PID_NAME, pid)


def read_comfy_pid(data_dir: Path) -> int:
    return read_pid(data_dir, COMFY_PID_NAME)


def clear_comfy_pid(data_dir: Path) -> None:
    clear_pid(data_dir, COMFY_PID_NAME)


def touch_heartbeat(data_dir: Path, *, bye: bool = False, ts: float | None = None) -> dict:
    path = Path(data_dir) / HEARTBEAT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    # Običan ping briše bye — pagehide/beforeunload su samo nagovještaj.
    data = {
        "ts": float(ts if ts is not None else time.time()),
        "bye": bool(bye),
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def read_heartbeat(data_dir: Path) -> dict | None:
    path = Path(data_dir) / HEARTBEAT_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def clear_heartbeat(data_dir: Path) -> None:
    path = Path(data_dir) / HEARTBEAT_NAME
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def kill_process_tree(pid: int, log=print) -> bool:
    """taskkill /T /F /PID na Windowsu; SIGTERM drugdje. Ne dira PID 0."""
    pid = int(pid or 0)
    if pid <= 0:
        return False
    if pid == os.getpid():
        log("Odbijam ugasiti vlastiti PID.")
        return False
    log(f"Gasim stablo procesa PID {pid}")
    if sys.platform == "win32":
        try:
            r = subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            out = ((r.stdout or "") + " " + (r.stderr or "")).strip()
            log(f"taskkill /T /F /PID {pid} -> {r.returncode} {out}")
            return r.returncode == 0
        except Exception as exc:
            log(f"taskkill nije uspio: {exc}")
            return False
    try:
        os.kill(pid, signal.SIGTERM)
        log(f"SIGTERM poslan {pid}")
        return True
    except OSError as exc:
        log(f"kill {pid} nije uspio: {exc}")
        return False


def request_studio_shutdown(studio_url: str, log=print) -> bool:
    url = (studio_url or "http://127.0.0.1:7860/").rstrip("/") + "/api/shutdown"
    try:
        req = urllib.request.Request(url, data=b"{}", method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=3) as resp:
            log(f"Studio /api/shutdown -> {resp.status}")
            return 200 <= resp.status < 500
    except Exception as exc:
        log(f"Studio /api/shutdown nije uspio: {exc}")
        return False


def shutdown_session(
    data_dir: Path,
    *,
    studio_proc=None,
    studio_url: str = "http://127.0.0.1:7860/",
    we_started_comfy: bool = False,
    comfy_pid: int = 0,
    stop_studio: bool = True,
    log=print,
    kill=kill_process_tree,
    request_shutdown=request_studio_shutdown,
) -> None:
    """Ugasi Studio. ComfyUI stablo samo ako smo ga mi pokrenuli."""
    log("Gasim sesiju aplikacije...")
    if stop_studio:
        request_shutdown(studio_url, log=log)
        if studio_proc is not None:
            poll = getattr(studio_proc, "poll", None)
            still = True if not callable(poll) else poll() is None
            if still:
                term = getattr(studio_proc, "terminate", None)
                if callable(term):
                    try:
                        term()
                    except Exception:
                        pass
                wait = getattr(studio_proc, "wait", None)
                if callable(wait):
                    try:
                        wait(timeout=4)
                    except Exception:
                        pass
            poll2 = getattr(studio_proc, "poll", None)
            if callable(poll2) and poll2() is None:
                spid = getattr(studio_proc, "pid", 0) or 0
                kill(spid, log=log)
        spid = read_pid(data_dir, STUDIO_PID_NAME)
        if spid and spid != os.getpid():
            kill(spid, log=log)
        clear_pid(data_dir, STUDIO_PID_NAME)
    if we_started_comfy:
        pid = int(comfy_pid or 0) or read_comfy_pid(data_dir)
        if pid:
            log(f"Gasim ComfyUI stablo koje je pokrenuo launcher (PID {pid})")
            kill(pid, log=log)
        else:
            log("we_started_comfy ali nema PID-a — ne diram tuđi ComfyUI.")
        clear_comfy_pid(data_dir)
    else:
        log("ComfyUI nisam ja pokrenuo — ne gasim ga.")
    clear_heartbeat(data_dir)
    log("Sesija je ugašena.")



DEFAULT_STALE_S = 120.0
DEFAULT_GRACE_S = 15.0
DEFAULT_QUERY_FAIL_STALE_S = 300.0
COMFY_URL_DEFAULT = "http://127.0.0.1:8188"
STUDIO_URL_DEFAULT = "http://127.0.0.1:7860/"
BROWSER_PROCESS_NAMES = ("brave.exe", "chrome.exe", "msedge.exe", "brave", "google-chrome", "msedge", "chromium")


def _norm_cmd(text: str) -> str:
    return (text or "").replace("/", "\\").lower()


def cmdline_uses_profile(cmdline: str, profile_dir: Path | str) -> bool:
    """True ako command line sadrži naš --user-data-dir (ili samu putanju profila)."""
    if not cmdline or not profile_dir:
        return False
    raw = _norm_cmd(cmdline)
    marker = _norm_cmd(str(Path(profile_dir)))
    while marker.endswith("\\"):
        marker = marker[:-1]
    if not marker:
        return False
    if marker not in raw:
        return False
    # Preferiraj eksplicitni flag, ali putanja profila je dovoljna.
    return True


def parse_cim_process_json(text: str) -> list[tuple[int, str]]:
    raw = (text or "").strip()
    if not raw or raw.lower() in {"null", "none"}:
        return []
    data = json.loads(raw)
    if data is None:
        return []
    if isinstance(data, dict):
        rows = [data]
    elif isinstance(data, list):
        rows = data
    else:
        return []
    out: list[tuple[int, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            pid = int(row.get("ProcessId") or row.get("processid") or 0)
        except (TypeError, ValueError):
            continue
        cmd = row.get("CommandLine") if "CommandLine" in row else row.get("commandline")
        if pid:
            out.append((pid, "" if cmd is None else str(cmd)))
    return out


def parse_wmic_list(text: str) -> list[tuple[int, str]]:
    entries: list[dict] = []
    cur: dict[str, str] = {}
    for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if not stripped:
            if cur:
                entries.append(cur)
                cur = {}
            continue
        if "=" not in stripped:
            continue
        key, val = stripped.split("=", 1)
        cur[key.strip().lower()] = val.strip()
    if cur:
        entries.append(cur)
    out: list[tuple[int, str]] = []
    for row in entries:
        try:
            pid = int(row.get("processid") or 0)
        except (TypeError, ValueError):
            continue
        if pid:
            out.append((pid, row.get("commandline") or ""))
    return out


def _run_capture(argv: list[str], *, timeout: float = 15.0) -> str:
    flags = 0
    if sys.platform == "win32":
        flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
    )
    if proc.returncode not in (0, None) and not (proc.stdout or "").strip():
        err = (proc.stderr or "").strip() or f"exit {proc.returncode}"
        raise RuntimeError(err)
    return proc.stdout or ""


def list_windows_browser_cmdlines(*, run=None) -> tuple[list[tuple[int, str]], str | None, str]:
    """Vrati (pid, commandline) za Brave/Edge/Chrome bez psutil-a."""
    run = run or _run_capture
    names = " or ".join(
        f"Name='{n}'" for n in BROWSER_PROCESS_NAMES if n.endswith(".exe")
    )
    ps = (
        f"Get-CimInstance Win32_Process -Filter \"{names}\" | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        out = run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps]
        )
        return parse_cim_process_json(out), "cim", ""
    except Exception as exc:
        cim_err = str(exc)
    where = " or ".join(f"name='{n}'" for n in BROWSER_PROCESS_NAMES if n.endswith(".exe"))
    try:
        out = run(
            ["wmic", "process", "where", where, "get", "ProcessId,CommandLine", "/FORMAT:LIST"]
        )
        return parse_wmic_list(out), "wmic", ""
    except Exception as exc:
        return [], None, f"cim: {cim_err}; wmic: {exc}"


def find_profile_browsers(
    profile_dir: Path | str | None,
    *,
    log=print,
    run=None,
    platform: str | None = None,
) -> dict:
    """Pronađi procese preglednika čiji command line sadrži naš --user-data-dir."""
    plat = platform if platform is not None else sys.platform
    if plat != "win32":
        return {"ok": True, "pids": [], "source": "non-windows", "error": ""}
    cmdlines, source, err = list_windows_browser_cmdlines(run=run)
    if source is None:
        return {"ok": False, "pids": [], "source": None, "error": err or "nema popisa procesa"}
    pids = [pid for pid, cmd in cmdlines if cmdline_uses_profile(cmd, profile_dir or "")]
    return {"ok": True, "pids": pids, "source": source, "error": ""}


def _http_json(url: str, *, timeout: float = 3.0):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw) if raw else {}


def comfy_queue_status(comfy_url: str = COMFY_URL_DEFAULT, *, fetch=_http_json) -> dict:
    url = comfy_url.rstrip("/") + "/queue"
    try:
        data = fetch(url)
    except Exception as exc:
        return {"ok": False, "busy": False, "running": 0, "pending": 0, "error": str(exc)}
    if not isinstance(data, dict):
        return {"ok": False, "busy": False, "running": 0, "pending": 0, "error": "neočekivani /queue"}
    running = data.get("queue_running") or []
    pending = data.get("queue_pending") or []
    n_run = len(running) if isinstance(running, list) else 0
    n_pend = len(pending) if isinstance(pending, list) else 0
    return {"ok": True, "busy": (n_run + n_pend) > 0, "running": n_run, "pending": n_pend, "error": ""}


def studio_busy_status(studio_url: str = STUDIO_URL_DEFAULT, *, fetch=_http_json) -> dict:
    url = studio_url.rstrip("/") + "/api/busy"
    try:
        data = fetch(url)
    except Exception as exc:
        return {"ok": False, "busy": False, "jobs": 0, "error": str(exc)}
    if not isinstance(data, dict):
        return {"ok": False, "busy": False, "jobs": 0, "error": "neočekivani /api/busy"}
    jobs = data.get("jobs")
    try:
        n_jobs = int(jobs if jobs is not None else (1 if data.get("busy") else 0))
    except (TypeError, ValueError):
        n_jobs = 1 if data.get("busy") else 0
    return {"ok": True, "busy": bool(data.get("busy")), "jobs": n_jobs, "error": ""}


def work_in_progress(
    *,
    comfy_url: str = COMFY_URL_DEFAULT,
    studio_url: str = STUDIO_URL_DEFAULT,
    fetch=_http_json,
    comfy_fn=None,
    studio_fn=None,
) -> dict:
    comfy = comfy_fn() if comfy_fn is not None else comfy_queue_status(comfy_url, fetch=fetch)
    studio = studio_fn() if studio_fn is not None else studio_busy_status(studio_url, fetch=fetch)
    parts = []
    if comfy.get("busy"):
        parts.append(f"ComfyUI red: {comfy.get('running', 0)} u tijeku, {comfy.get('pending', 0)} čeka")
    if studio.get("busy"):
        parts.append(f"Studio ima generiranje u tijeku ({studio.get('jobs', 0)})")
    return {
        "busy": bool(comfy.get("busy") or studio.get("busy")),
        "reason": "; ".join(parts),
        "comfy": comfy,
        "studio": studio,
    }


def _profile_dir_for(data_dir: Path, profile_dir: Path | None = None) -> Path:
    if profile_dir is not None:
        return Path(profile_dir)
    try:
        import browser_launch
        return Path(browser_launch.browser_profile_dir(data_dir))
    except Exception:
        return Path(data_dir) / "browser-profile"


def clear_heartbeat_bye(data_dir: Path) -> None:
    """Makni goodbye zastavicu, ostavi zadnji ts (prozor je i dalje živ)."""
    prev = read_heartbeat(data_dir) or {}
    if not prev.get("bye"):
        return
    ts = prev.get("ts")
    try:
        ts_f = float(ts) if ts is not None else time.time()
    except (TypeError, ValueError):
        ts_f = time.time()
    touch_heartbeat(data_dir, bye=False, ts=ts_f)


def wait_for_app_close(
    data_dir: Path,
    browser_proc=None,
    *,
    stale_s: float = DEFAULT_STALE_S,
    grace_s: float = DEFAULT_GRACE_S,
    poll_s: float = 1.0,
    now_fn=time.time,
    sleep_fn=time.sleep,
    log=print,
    profile_dir: Path | None = None,
    browsers_fn=None,
    busy_fn=None,
    comfy_url: str = COMFY_URL_DEFAULT,
    studio_url: str = STUDIO_URL_DEFAULT,
    query_fail_stale_s: float = DEFAULT_QUERY_FAIL_STALE_S,
) -> str:
    """
    Čeka stvarno zatvaranje prozora aplikacije.

    Popen PID, pagehide/goodbye i tišina heartbeat-a su samo nagovještaji.
    Gašenje ide tek kad (1) nema procesa preglednika s našim --user-data-dir,
    (2) prođe grace period, i (3) ComfyUI red i Studio nemaju posla u tijeku.
    Heartbeat timeout je 120 s (preglednici usporavaju timere u pozadini).
    """
    profile = _profile_dir_for(data_dir, profile_dir)
    log(
        f"Cekam zatvaranje prozora (profil={profile}, heartbeat {stale_s:.0f}s, "
        f"potvrda {grace_s:.0f}s). Ne gasim usred generiranja."
    )
    pending: tuple[str, float] | None = None
    last_busy_log = -1e9
    last_query_log = -1e9
    last_pid_log = -1e9

    def _browsers() -> dict:
        if browsers_fn is not None:
            got = browsers_fn()
            if isinstance(got, dict):
                return got
            pids = [int(x) for x in (got or [])]
            return {"ok": True, "pids": pids, "source": "inject", "error": ""}
        return find_profile_browsers(profile, log=log)

    def _busy() -> dict:
        if busy_fn is not None:
            got = busy_fn()
            if isinstance(got, dict):
                return got
            return {"busy": bool(got), "reason": "generiranje u tijeku" if got else ""}
        return work_in_progress(comfy_url=comfy_url, studio_url=studio_url)

    while True:
        now = float(now_fn())
        info = _browsers()
        pids = list(info.get("pids") or [])
        query_ok = bool(info.get("ok", True))

        proc_code = None
        proc_dead = False
        if browser_proc is not None:
            poll = getattr(browser_proc, "poll", None)
            if callable(poll):
                proc_code = poll()
                proc_dead = proc_code is not None

        hb = read_heartbeat(data_dir)
        goodbye = bool(hb and hb.get("bye"))
        stale = False
        hb_age = 0.0
        if hb:
            try:
                ts = float(hb.get("ts") if hb.get("ts") is not None else 0)
            except (TypeError, ValueError):
                ts = 0.0
            hb_age = now - ts
            if hb_age >= stale_s:
                stale = True

        if pids:
            if goodbye:
                log(
                    f"pagehide/goodbye je samo nagovjestaj — preglednik s nasim profilom "
                    f"jos radi (PID {pids}). Ignoriram goodbye."
                )
                try:
                    clear_heartbeat_bye(data_dir)
                except Exception:
                    pass
            if proc_dead and now - last_pid_log >= 30:
                log(
                    f"Pokrenuti PID preglednika je izasao (returncode={proc_code}), "
                    f"ali profil jos zivi (PID {pids}) — ne gasim."
                )
                last_pid_log = now
            if pending is not None:
                log(f"Nagovjestaj {pending[0]} otkazan: profil jos zivi (PID {pids}).")
                pending = None
            sleep_fn(poll_s)
            continue

        hint = None
        if goodbye:
            hint = "goodbye"
        elif proc_dead:
            hint = "browser_exit"
        elif stale:
            hint = "heartbeat_stale"

        if hint and not query_ok:
            fallback = max(float(query_fail_stale_s), float(stale_s) * 2)
            if not (stale and hb_age >= fallback):
                if now - last_query_log >= 30:
                    log(
                        f"Ne mogu popisati procese preglednika ({info.get('error') or 'nema izvora'}) "
                        f"— ne gasim dok ne potvrdim. hint={hint}"
                    )
                    last_query_log = now
                sleep_fn(poll_s)
                continue
            if now - last_query_log >= 30:
                log(
                    f"Procesi preglednika nisu se mogli popisati, ali heartbeat šuti već "
                    f"{hb_age:.0f}s. Nastavljam uz oprez ({hint})."
                )
                last_query_log = now

        if hint:
            if pending is None or pending[0] != hint:
                pending = (hint, now)
                extra = f" (returncode={proc_code})" if hint == "browser_exit" else ""
                log(
                    f"Nagovjestaj zatvaranja: {hint}{extra} — cekam {grace_s:.0f}s i "
                    f"ponovno provjeravam procese i red ComfyUI-ja."
                )
            elif now - pending[1] >= grace_s:
                wip = _busy()
                if wip.get("busy"):
                    if now - last_busy_log >= 15:
                        why = wip.get("reason") or "ima posla u tijeku"
                        log(
                            f"Ne gasim: prozor izgleda zatvoren ({hint}), ali {why}. "
                            f"Cekam kraj generiranja."
                        )
                        last_busy_log = now
                    sleep_fn(poll_s)
                    continue
                log(
                    f"Potvrdjeno zatvaranje. Razlog: {hint}. Nema procesa s "
                    f"--user-data-dir={profile}. Nema posla u ComfyUI redu ni Studiju."
                )
                return hint
        else:
            pending = None

        sleep_fn(poll_s)
