#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.0.19: LoRA izbornik u Slikama mora vidjeti iste LoRA-e kao kartica Modeli.

Bug (1.0.18): Modeli (skeniranje diska) pokazuju 2 LoRA-e, a izbornik je prazan jer je
popis dolazio samo iz ComfyUI-ja (ili s diska bez podmapa) i zatim se filtrirao po
arhitekturi (SD 1.5 LoRA uz SDXL model, ili SDXL uz zadani "sd15" dok ComfyUI još nije
spreman), pa su se datoteke skrivale.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILED = 0


def check(cond, msg):
    global FAILED
    if cond:
        print("  OK ", msg)
    else:
        FAILED += 1
        print("  FAIL", msg)


def write_lora(path: Path, meta: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = json.dumps({"__metadata__": meta or {}}).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(header)) + header + b"\0" * 16)


def make_models(root: Path, *, turbo: bool = True, user: bool = True) -> None:
    import image_gen
    (root / "loras").mkdir(parents=True, exist_ok=True)
    (root / "checkpoints").mkdir(parents=True, exist_ok=True)
    if turbo:
        write_lora(root / "loras" / image_gen.TURBO_SDXL["lora_filename"])
    if user:
        # nepoznata arhitektura (ni ime ni metapodaci ne govore ništa)
        write_lora(root / "loras" / "MyStyle.safetensors")
        # SD 1.5 po metapodacima, u podmapi
        write_lora(root / "loras" / "likovi" / "luna_face.safetensors", {"ss_base_model_version": "sd_v1"})


def test_backend():
    print("== backend: disk + ComfyUI ==")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "models"
        make_models(root)
        os.environ["COMFYUI_MODELS_ROOT"] = str(root)
        os.environ.pop("COMFYUI_LORAS_DIR", None)
        import image_gen
        import installed_models
        import studio

        sub = os.path.join("likovi", "luna_face.safetensors")
        fs = image_gen.list_loras()
        check(sub in fs and "MyStyle.safetensors" in fs, f"disk sken vidi podmape: {fs}")
        inst = [f for f in installed_models.list_installed()["files"] if f["folder"] == "loras"]
        check(len(inst) == 3, f"Modeli vide 3 datoteke u loras (2 + Turbo): {[f['path'] for f in inst]}")

        orig = studio.comfy_lora_names
        try:
            # ComfyUI ne odgovara / još se pali
            studio.comfy_lora_names = lambda: None
            entries = studio.lora_entries()
            names = {e["name"] for e in entries}
            check(names == {"MyStyle.safetensors", sub}, f"ComfyUI nedostupan: 2 LoRA-e s diska, bez Turbo: {names}")
            entries_off = studio.lora_entries(comfy_ok=False)
            check(len(entries_off) == 2, "comfy_ok=False: popis s diska bez čekanja ComfyUI-ja")

            # ComfyUI odgovara, ali vraća prazan popis
            studio.comfy_lora_names = lambda: []
            check(len(studio.lora_entries()) == 2, "ComfyUI vraća prazan popis: i dalje 2 LoRA-e")

            # ComfyUI ima zastarjeli popis (samo Turbo) - disk se spaja
            studio.comfy_lora_names = lambda: [image_gen.TURBO_SDXL["lora_filename"]]
            check(len(studio.lora_entries()) == 2, "zastarjeli ComfyUI popis: disk se spaja")

            # ComfyUI vraća isto ime s drugim separatorom - nema duplikata, zadrži ComfyUI zapis
            studio.comfy_lora_names = lambda: ["likovi\\luna_face.safetensors", "MyStyle.safetensors"]
            ent = studio.lora_entries()
            check(len(ent) == 2, f"bez duplikata kod \\ vs /: {[e['name'] for e in ent]}")
            check("likovi\\luna_face.safetensors" in {e["name"] for e in ent}, "zadržan ComfyUI zapis imena")
        finally:
            studio.comfy_lora_names = orig

        by = {e["name"]: e for e in studio.lora_entries(comfy_ok=False)}
        check(by["MyStyle.safetensors"]["arch"] == "unknown", "nepoznata arhitektura ostaje unknown")
        check(by[sub]["arch"] == "sd15", "metapodaci iz podmape pročitani (sd15)")

        sdxl = image_gen.loras_for_arch(list(by.values()), "sdxl")
        check(len(sdxl) == 2, "uz SDXL model se vide obje (ništa skriveno)")
        check(all(e["compatible"] is False for e in sdxl), "obje su 'Ostalo / možda nekompatibilno' za SDXL")
        sd15 = image_gen.loras_for_arch(list(by.values()), "sd15")
        check(sd15[0]["name"] == sub and sd15[0]["compatible"], "uz SD 1.5 je SD 1.5 LoRA prva")
        check(image_gen.loras_for_arch(list(by.values()), "krea2") == [], "Krea 2 bez LoRA izbornika")

        check(image_gen.lora_available(sub), "lora_available za podmapu")
        check(image_gen.lora_available("likovi/LUNA_face.safetensors"), "lora_available neosjetljivo na / i velika slova")

        # Samo Turbo LoRA
        shutil.rmtree(root / "loras")
        make_models(root, user=False)
        check(studio.lora_entries(comfy_ok=False) == [], "samo Turbo: korisnički popis prazan")
        check(studio.turbo_lora_present() is True, "samo Turbo: turbo_present=True za hint")
        os.environ.pop("COMFYUI_MODELS_ROOT", None)


BROWSER_SCRIPT = r"""
import json, sys
from playwright.sync_api import sync_playwright
url = sys.argv[1]
exe = sys.argv[2] or None
with sync_playwright() as p:
    kw = {"args": ["--no-sandbox"]}
    if exe:
        kw["executable_path"] = exe
    b = p.chromium.launch(**kw)
    pg = b.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(url)
    pg.wait_for_timeout(3000)
    opts = lambda: pg.evaluate('''() => [...document.querySelectorAll("#lora option")].filter(o => o.value).map(o => ({v: o.value, g: (o.parentElement.label || "")}))''')
    out = {"initial": opts()}
    pg.evaluate('''() => {
      const m = document.getElementById("model");
      const o = document.createElement("option");
      o.value = "RealVisXL_V5.0_fp16.safetensors"; o.textContent = o.value; o.dataset.arch = "sdxl";
      m.appendChild(o); m.value = o.value; m.dispatchEvent(new Event("change"));
    }''')
    out["sdxl"] = opts()
    out["has_refresh"] = pg.evaluate('() => !!document.getElementById("loraRefresh")')
    pg.evaluate("() => document.getElementById('loraRefresh').click()")
    pg.wait_for_timeout(1500)
    out["after_refresh"] = opts()
    out["hint"] = pg.evaluate('() => document.getElementById("loraHint").textContent')
    out["errors"] = errs
    b.close()
print(json.dumps(out, ensure_ascii=False))
"""


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def get(url: str):
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def run_server(models_root: Path, data_dir: Path):
    port = free_port()
    env = dict(os.environ, STUDIO_DATA_DIR=str(data_dir), STUDIO_PORT=str(port), STUDIO_NO_BROWSER="1",
               COMFYUI_URL="http://127.0.0.1:9", COMFYUI_MODELS_ROOT=str(models_root))
    proc = subprocess.Popen([sys.executable, str(ROOT / "studio.py")], cwd=str(ROOT), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            get(base + "/api/state")
            break
        except Exception:
            time.sleep(0.1)
    return proc, base


def test_server_and_ui():
    print("== server + UI (ComfyUI nije pokrenut) ==")
    fixture = ROOT / "tools" / "fixtures" / "v115_data"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "models"
        make_models(root)
        data = Path(td) / "data"
        if fixture.is_dir():
            shutil.copytree(fixture, data)
        else:
            data.mkdir()
        proc, base = run_server(root, data)
        try:
            _, d = get(base + "/api/loras")
            check(len(d.get("loras") or []) == 2, f"/api/loras: 2 LoRA-e ({[x['name'] for x in d.get('loras') or []]})")
            check(d.get("turbo_present") is True, "/api/loras: turbo_present")
            _, m = get(base + "/api/models")
            check(len(m.get("loras_info") or []) == 2, "/api/models loras_info: 2 LoRA-e i kad ComfyUI ne radi")
            py = os.environ.get("PW_PYTHON") or sys.executable
            if subprocess.run([py, "-c", "import playwright"], capture_output=True).returncode != 0:
                print("  SKIP playwright nije instaliran (postavi PW_PYTHON)")
                return
            exe = os.environ.get("PW_CHROME") or shutil.which("google-chrome") or shutil.which("chromium") or ""
            r = subprocess.run([py, "-c", BROWSER_SCRIPT, base + "/#slike", exe], capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                check(False, "browser: " + r.stderr[-400:])
                return
            info = json.loads(r.stdout.strip().splitlines()[-1])
            check(not info["errors"], f"nema JS grešaka: {info['errors'][:2]}")
            check(len(info["initial"]) == 2, f"izbornik odmah ima 2 LoRA-e: {info['initial']}")
            check(len(info["sdxl"]) == 2, f"uz SDXL model i dalje 2: {info['sdxl']}")
            check(all("Ostalo" in o["g"] for o in info["sdxl"]), "uz SDXL su obje pod Ostalo / možda nekompatibilno")
            check(info["has_refresh"], "gumb ↻ Osvježi postoji")
            check(len(info["after_refresh"]) == 2, "nakon osvježavanja 2 LoRA-e")
            check(not any("Turbo" in o["v"] or "Hyper" in o["v"] for o in info["after_refresh"]), "Turbo LoRA nije u izborniku")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

        # samo Turbo LoRA -> prazan izbornik + hint
        shutil.rmtree(root / "loras")
        make_models(root, user=False)
        proc, base = run_server(root, data)
        try:
            py = os.environ.get("PW_PYTHON") or sys.executable
            exe = os.environ.get("PW_CHROME") or shutil.which("google-chrome") or shutil.which("chromium") or ""
            r = subprocess.run([py, "-c", BROWSER_SCRIPT, base + "/#slike", exe], capture_output=True, text=True, timeout=120)
            info = json.loads(r.stdout.strip().splitlines()[-1])
            check(info["after_refresh"] == [], "samo Turbo: izbornik prazan")
            check("samo Turbo" in info["hint"], f"samo Turbo: hint objašnjava ({info['hint'][:80]})")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


SAMPLE_LOG_FAILED = r"""
===== 2026-11-18T20:00:00 cmd cmd /c comfyui-studio.bat cwd=C:\ComfyUI-Zluda =====
Total VRAM 8176 MB
Import times for custom nodes:
   0.0 seconds: C:\ComfyUI-Zluda\custom_nodes\websocket_image_save.py
===== 2026-11-18T21:00:00 cmd cmd /c comfyui-studio.bat cwd=C:\ComfyUI-Zluda =====
Traceback (most recent call last):
  File "C:\ComfyUI-Zluda\nodes.py", line 2122, in load_custom_node
    module_spec.loader.exec_module(module)
  File "C:\ComfyUI-Zluda\custom_nodes\ComfyUI-Impact-Pack\__init__.py", line 10, in <module>
    import piexif
ModuleNotFoundError: No module named 'piexif'

Cannot import C:\ComfyUI-Zluda\custom_nodes\ComfyUI-Impact-Pack module for custom nodes: No module named 'piexif'

Import times for custom nodes:
   0.0 seconds: C:\ComfyUI-Zluda\custom_nodes\websocket_image_save.py
   0.1 seconds: C:\ComfyUI-Zluda\custom_nodes\ComfyUI_IPAdapter_plus
   0.0 seconds (IMPORT FAILED): C:\ComfyUI-Zluda\custom_nodes\ComfyUI-Impact-Pack
   0.5 seconds: C:\ComfyUI-Zluda\custom_nodes\ComfyUI-Manager
"""

SAMPLE_LOG_NOT_SEEN = r"""
Import times for custom nodes:
   0.0 seconds: C:\ComfyUI-Zluda\custom_nodes\cfz_cudnn.toggle.py
   0.0 seconds: C:\ComfyUI-Zluda\custom_nodes\cfz_vae_loader.py
   0.0 seconds: C:\ComfyUI-Zluda\custom_nodes\CFZ-SwitchMenu
   0.0 seconds: C:\ComfyUI-Zluda\custom_nodes\websocket_image_save.py
   0.0 seconds: C:\ComfyUI-Zluda\custom_nodes\ComfyUI-Manager
"""


def test_comfy_log():
    print("== comfyui.log dijagnostika ==")
    import comfy_log
    info = comfy_log.parse(SAMPLE_LOG_FAILED)
    check(info["has_import_list"], "nađen popis Import times")
    check("ComfyUI_IPAdapter_plus" in info["loaded"], "IPAdapter učitan")
    f = info["failed"].get("ComfyUI-Impact-Pack") or {}
    check(f.get("module") == "piexif", f"IMPORT FAILED + nedostaje modul: {f.get('error')}")
    check(any("import piexif" in t for t in f.get("trace") or []), "traceback sačuvan")
    check(comfy_log.comfy_custom_nodes_dir(info) == r"C:\ComfyUI-Zluda\custom_nodes", "stvarna custom_nodes mapa iz loga")
    state_ok = {"exists": True, "valid": True, "path": r"C:\ComfyUI-Zluda\custom_nodes\ComfyUI-Impact-Pack",
                "custom_nodes": r"C:\ComfyUI-Zluda\custom_nodes"}
    msg = comfy_log.diagnose("ComfyUI-Impact-Pack", info, state_ok)
    check("piexif" in msg and "Popravi" in msg, f"poruka s razlogom: {msg}")
    check(comfy_log.diagnose("ComfyUI_IPAdapter_plus", info, state_ok) == "", "učitan čvor: bez poruke")

    info2 = comfy_log.parse(SAMPLE_LOG_NOT_SEEN)
    msg2 = comfy_log.diagnose("ComfyUI_IPAdapter_plus", info2, dict(state_ok, path=r"C:\ComfyUI-Zluda\custom_nodes\ComfyUI_IPAdapter_plus"))
    check("nije vidio" in msg2, f"ComfyUI nije vidio mapu: {msg2[:90]}")
    msg3 = comfy_log.diagnose("ComfyUI_IPAdapter_plus", info2, dict(state_ok, custom_nodes=r"C:\Users\x\AppData\custom_nodes"))
    check("učitava čvorove iz" in msg3, f"kriva mapa prepoznata: {msg3[:90]}")
    msg4 = comfy_log.diagnose("X", info2, {"exists": True, "valid": False, "path": "p"})
    check("nema __init__.py" in msg4, "nepotpuna mapa prepoznata")


def _make_zip(top: str, files: dict) -> bytes:
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(f"{top}/{name}", data)
    return buf.getvalue()


def test_node_install():
    print("== instalacija čvorova (putanja, ugniježđeno, zip, pip) ==")
    import node_install
    with tempfile.TemporaryDirectory() as td:
        nodes = Path(td) / "ComfyUI-Zluda" / "custom_nodes"
        (nodes / "ComfyUI-Manager").mkdir(parents=True)
        (nodes / "ComfyUI-Manager" / "__init__.py").write_text("# manager")
        logs = []

        # bez Gita -> zip s codeloada (main ne postoji, master postoji)
        calls = []
        def fetch(url):
            calls.append(url)
            if url.endswith("/main"):
                raise OSError("404")
            return _make_zip("ComfyUI_IPAdapter_plus-master", {"__init__.py": "x=1\n", "IPAdapterPlus.py": "y=1\n"})
        st = node_install.ensure_node("https://github.com/cubiq/ComfyUI_IPAdapter_plus.git", "ComfyUI_IPAdapter_plus",
                                      git="", nodes_dir=nodes, log=logs.append, fetch=fetch)
        check(st["valid"] and (nodes / "ComfyUI_IPAdapter_plus" / "__init__.py").is_file(), "zip fallback -> custom_nodes/ime/__init__.py")
        check(calls[0].startswith("https://codeload.github.com/cubiq/ComfyUI_IPAdapter_plus/zip/refs/heads/"), f"codeload URL: {calls[0]}")
        check((nodes / "ComfyUI-Manager" / "__init__.py").is_file(), "ComfyUI-Manager netaknut")

        # ugniježđeni klon -> izravnaj
        nested = nodes / "ComfyUI-Impact-Pack" / "ComfyUI-Impact-Pack"
        nested.mkdir(parents=True)
        (nested / "__init__.py").write_text("x=1\n")
        (nested / "requirements.txt").write_text("piexif\ntorch>=2.0\nultralytics\n")
        st2 = node_install.ensure_node("https://github.com/ltdrdata/ComfyUI-Impact-Pack.git", "ComfyUI-Impact-Pack",
                                       git="", nodes_dir=nodes, log=logs.append, fetch=lambda u: (_ for _ in ()).throw(OSError("ne zovi")))
        check(st2["valid"] and (nodes / "ComfyUI-Impact-Pack" / "requirements.txt").is_file(), "ugniježđena mapa izravnana")

        # nepotpuna mapa (samo .git, bez __init__) -> u .disabled, pa ponovno preuzmi
        broken = nodes / "ComfyUI-Impact-Subpack"
        (broken / ".git").mkdir(parents=True)
        st3 = node_install.ensure_node("https://github.com/ltdrdata/ComfyUI-Impact-Subpack", "ComfyUI-Impact-Subpack",
                                       git="", nodes_dir=nodes, log=logs.append,
                                       fetch=lambda u: _make_zip("ComfyUI-Impact-Subpack-main", {"__init__.py": ""}))
        check(st3["valid"], "nepotpuna mapa zamijenjena ispravnom")
        check(any(p.name.endswith(".disabled") for p in nodes.iterdir()), "stara nepotpuna mapa preimenovana u *.disabled (ComfyUI je preskače)")

        # pravi git klon iz lokalnog repoa
        git = shutil.which("git")
        if git:
            src = Path(td) / "srcrepo"
            src.mkdir()
            (src / "__init__.py").write_text("")
            subprocess.run([git, "init", "-q", str(src)], check=True)
            subprocess.run([git, "-C", str(src), "add", "."], check=True)
            subprocess.run([git, "-C", str(src), "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "i"], check=True)
            st4 = node_install.ensure_node(str(src), "LocalNode", git=git, nodes_dir=nodes, log=logs.append)
            check(st4["valid"] and st4["git"], "git clone u custom_nodes/ime")

        # pip: torch se ne dira, constraints drže instalirane verzije
        fake_py = Path(td) / "python.exe"
        fake_py.write_text("")
        seen = []
        def run(argv, cwd=None, timeout=0, env=None):
            seen.append((argv, env or {}))
            if "-c" in argv and "importlib.metadata" in " ".join(argv):
                return 0, "torch==2.3.0+zluda\nnumpy==1.26.4\n"
            return 0, "ok"
        failed = node_install.install_requirements(nodes / "ComfyUI-Impact-Pack", fake_py, log=logs.append, run=run)
        pip_call = [a for a, e in seen if "-r" in a][0]
        env = [e for a, e in seen if "-r" in a][0]
        req_text = Path(pip_call[pip_call.index("-r") + 1]).read_text() if Path(pip_call[pip_call.index("-r") + 1]).exists() else ""
        check(failed == [], "pip prošao")
        check(str(fake_py) == pip_call[0] and pip_call[1:4] == ["-m", "pip", "install"], "pip ide kroz ComfyUI venv python")
        check("-c" in pip_call and env.get("PIP_CONSTRAINT"), "constraints + PIP_CONSTRAINT postavljeni")
        filtered = node_install.filtered_requirements(nodes / "ComfyUI-Impact-Pack" / "requirements.txt")
        check("torch>=2.0" not in filtered and "piexif" in filtered, f"torch izbačen iz requirements: {filtered}")

        # pip pada za cijeli popis -> paket po paket, vrati one koji nisu prošli
        def run_fail(argv, cwd=None, timeout=0, env=None):
            if "importlib.metadata" in " ".join(argv):
                return 0, "torch==2.3.0\n"
            if "-r" in argv:
                return 1, "error"
            return (1, "no") if "ultralytics" in argv else (0, "ok")
        failed2 = node_install.install_requirements(nodes / "ComfyUI-Impact-Pack", fake_py, log=logs.append, run=run_fail)
        check(failed2 == ["ultralytics"], f"neuspjeli paketi prijavljeni: {failed2}")


def test_capabilities_and_restart():
    print("== poruke u UI + svjež ComfyUI ==")
    import character
    import node_install
    import app_session
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "ComfyUI-Zluda"
        (root / "custom_nodes" / "ComfyUI_IPAdapter_plus").mkdir(parents=True)
        (root / "custom_nodes" / "ComfyUI_IPAdapter_plus" / "__init__.py").write_text("")
        (root / "main.py").write_text("")
        os.environ["COMFYUI_DIR"] = str(root)
        log = Path(td) / "comfyui.log"
        log.write_text(SAMPLE_LOG_NOT_SEEN.replace("C:\\ComfyUI-Zluda\\custom_nodes", "C:\\Elsewhere\\custom_nodes"))
        orig = node_install.comfy_log_path
        node_install.comfy_log_path = lambda: log
        try:
            oi = {"CheckpointLoaderSimple": {}, "KSampler": {}}
            caps = character.capabilities(oi)
            ipa = caps["ipadapter"]
            check(ipa["nodes"] is False and ipa["nodes_on_disk"] is True, "čvor na disku, ComfyUI ga nema")
            check("učitava čvorove iz" in ipa["message"], f"poruka objašnjava krivu mapu: {ipa['message'][:100]}")
            check(ipa["repair"] is True, "gumb Popravi ponuđen")
            log.write_text(SAMPLE_LOG_NOT_SEEN.replace("C:\\ComfyUI-Zluda\\custom_nodes\\", str(root / "custom_nodes") + "/"))
            caps = character.capabilities(oi)
            check(Path(caps["ipadapter"]["node"]["custom_nodes"]) == root / "custom_nodes", "mapa = <ComfyUI>/custom_nodes")
            check("nije vidio" in caps["ipadapter"]["message"], f"poruka: nije vidio ({caps['ipadapter']['message'][:80]})")
            oi_ok = dict(oi, IPAdapterUnifiedLoader={}, IPAdapter={})
            check(character.capabilities(oi_ok)["ipadapter"]["nodes"] is True, "provjera učitanosti preko /object_info (IPAdapterUnifiedLoader)")
            check(character.FACE_DETAILER_NODES[0] == "FaceDetailer", "Face Detailer provjera traži FaceDetailer u /object_info")
        finally:
            node_install.comfy_log_path = orig
            os.environ.pop("COMFYUI_DIR", None)

        # launcher: zaostali ComfyUI iz prošle sesije se gasi
        data = Path(td) / "data"
        data.mkdir()
        up = {"v": True}
        killed = []
        def kill(pid, log=print):
            killed.append(pid); up["v"] = False; return True
        app_session.write_comfy_pid(data, 4242)
        act = app_session.ensure_fresh_comfy(data, url_ok=lambda u: up["v"], kill=kill, alive_fn=lambda p: True,
                                             port_pid_fn=lambda port: 0, sleep=lambda s: None, log=lambda m: None)
        check(act == "restart_pid" and killed == [4242], f"stari ComfyUI (comfy.pid) ugašen: {act} {killed}")
        check(app_session.read_comfy_pid(data) == 0, "comfy.pid očišćen")
        # bez PID-a, ali čeka restart zbog novih čvorova -> PID s porta
        up["v"] = True; killed.clear()
        app_session.restart_marker(data).write_text("ipadapter")
        act = app_session.ensure_fresh_comfy(data, url_ok=lambda u: up["v"], kill=kill, alive_fn=lambda p: False,
                                             port_pid_fn=lambda port: 777 if port == 8188 else 0, sleep=lambda s: None, log=lambda m: None)
        check(act == "restart_port" and killed == [777], f"restart po portu 8188: {act} {killed}")
        check(not app_session.restart_marker(data).exists(), "marker očišćen nakon restarta")
        # tuđi ComfyUI bez markera se ne dira
        up["v"] = True; killed.clear()
        act = app_session.ensure_fresh_comfy(data, url_ok=lambda u: up["v"], kill=kill, alive_fn=lambda p: False,
                                             port_pid_fn=lambda port: 777, sleep=lambda s: None, log=lambda m: None)
        check(act == "reuse" and killed == [], "tuđi ComfyUI bez razloga se ne gasi")
        check(app_session.parse_netstat_listening(
            "  TCP    127.0.0.1:8188     0.0.0.0:0      LISTENING       9132\n  TCP    0.0.0.0:445  0.0.0.0:0  LISTENING  4\n", 8188) == 9132,
            "netstat parser")

    import studio
    calls = {"n": 0}
    orig_oi = studio.object_info
    studio.object_info = lambda: (calls.__setitem__("n", calls["n"] + 1) or {"KSampler": {}})
    try:
        studio.invalidate_object_info()
        studio.cached_object_info(); studio.cached_object_info()
        check(calls["n"] == 1, "object_info keširan unutar TTL-a")
        studio.cached_object_info(0)
        check(calls["n"] == 2, "object_info se osvježi (nije zauvijek zapamćen)")
    finally:
        studio.object_info = orig_oi
        studio.invalidate_object_info()


def main():
    print("test_v119")
    test_comfy_log()
    test_node_install()
    test_capabilities_and_restart()
    test_backend()
    test_server_and_ui()
    print("FAILED" if FAILED else "ALL OK", FAILED)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
