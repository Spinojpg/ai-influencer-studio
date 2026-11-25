#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za LoRA trener (v1.2.0): dataset, Pillow priprema, Kohya struktura, 8 GB postavke za RX 6600,
ZLUDA okruženje, /free, zaključavanje GPU-a, simulirano treniranje (STUDIO_LORA_TRAINER_CMD),
temperatura GPU-a (upozorenje / auto-stop), prekid stabla procesa, auto-dodavanje LoRA-e osobi,
okidač u generiranju, izolacija osoba, HTTP API i UI (Playwright uz PW_PYTHON).
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FAKE = ROOT / "tools" / "fixtures" / "fake_lora_trainer.py"
FAKE_CMD = f'"{sys.executable}" "{FAKE}"'
BANNED = re.compile(r"\b(lustify|snofs|nsfw|nude|naked|topless|porn\w*|erotic\w*|lingerie)\b", re.I)

FAILED = 0


def check(cond, msg):
    global FAILED
    if cond:
        print("  OK ", msg)
    else:
        FAILED += 1
        print("  FAIL", msg)


# ---------------------------------------------------------------- pomoćno

class FakeComfy(BaseHTTPRequestHandler):
    calls: list = []

    def log_message(self, *a):
        pass

    def _ok(self, obj):
        raw = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        FakeComfy.calls.append(("POST", self.path, body.decode("utf-8", "replace")))
        self._ok({})

    def do_GET(self):
        FakeComfy.calls.append(("GET", self.path, ""))
        self._ok({"system": {}, "devices": []} if self.path.startswith("/system_stats") else {})


def start_fake_comfy():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeComfy)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def http(method, url, body=None, raw=None, ctype=None):
    data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
    headers = {"Content-Type": ctype or "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = r.read()
            return r.status, (json.loads(payload.decode()) if "json" in (r.headers.get("Content-Type") or "") else payload)
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        try:
            return exc.code, json.loads(payload.decode())
        except Exception:
            return exc.code, payload


def jpeg(w, h, color=(120, 90, 80), exif_orientation=None, mode="RGB", fmt="JPEG") -> bytes:
    from PIL import Image
    im = Image.new(mode, (w, h), color)
    # gornji dio drugačije boje da se vidi rotacija
    for x in range(w):
        for y in range(min(20, h)):
            im.putpixel((x, y), (250, 10, 10) if mode == "RGB" else (250, 10, 10, 255))
    b = io.BytesIO()
    kw = {}
    if exif_orientation:
        ex = Image.Exif()
        ex[0x0112] = exif_orientation
        kw["exif"] = ex.tobytes()
    im.save(b, fmt, **kw)
    return b.getvalue()


def varied_images(n, base=0):
    out = []
    for i in range(n):
        w, h = (600, 900) if i % 3 else (900, 600)
        out.append((jpeg(w, h, ((base + i * 13) % 255, (i * 29) % 255, 140)), f"slika_{base}_{i}.jpg"))
    return out


def wait_job(lt, jid, timeout=60):
    end = time.time() + timeout
    j = lt.get_job(jid)
    while time.time() < end:
        j = lt.get_job(jid)
        if not j["active"]:
            t = lt._threads.get(int(jid))
            if t is not None:
                t.join(timeout=10)
            return lt.get_job(jid)
        time.sleep(0.05)
    return j


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:  # zombi = mrtav
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            return fh.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return True


# ---------------------------------------------------------------- setup

def setup(tmp: Path):
    comfy = tmp / "ComfyUI"
    for d in ("models/checkpoints", "models/loras"):
        (comfy / d).mkdir(parents=True, exist_ok=True)
    for name in ("RealVisXL_V5.0_fp16.safetensors", "realisticVisionV60B1_v51HyperVAE.safetensors", "krea2_dev_fp8.safetensors"):
        (comfy / "models" / "checkpoints" / name).write_bytes(b"x" * 64)
    os.environ["COMFYUI_DIR"] = str(comfy)
    for k in ("COMFYUI_MODELS_DIR", "COMFYUI_LORAS_DIR", "STUDIO_GPU_TEMP", "STUDIO_GPU_TEMP_FILE"):
        os.environ.pop(k, None)
    os.environ["STUDIO_DATA_DIR"] = str(tmp / "data")
    os.environ["STUDIO_LORA_TRAINER_CMD"] = FAKE_CMD
    os.environ["STUDIO_LORA_TEMP_INTERVAL"] = "0.05"
    os.environ["STUDIO_GPU_TEMP"] = "61"
    (tmp / "data").mkdir()
    import inbox
    inbox.configure_paths(data_dir=tmp / "data")
    inbox.init_db()
    import services
    services.init_schema()
    return comfy


# ---------------------------------------------------------------- testovi

def test_schema_and_triggers():
    print("== shema, mape po osobi, jedinstveni okidači ==")
    import inbox
    from services import lora_trainer_service as lt
    from services.common import conn
    with conn() as c:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        pcols = {r[1] for r in c.execute("PRAGMA table_info(profiles)").fetchall()}
        jcols = {r[1] for r in c.execute("PRAGMA table_info(lora_training_jobs)").fetchall()}
    check({"lora_training_jobs", "persona_trained_loras", "lora_dataset_images"} <= tables, "tablice lora_training_jobs / persona_trained_loras / dataset")
    check("lora_trigger" in pcols, "profiles.lora_trigger")
    check({"status", "current_step", "total_steps", "eta_seconds", "gpu_temp_c", "gpu_temp_peak_c", "gpu_warning_message", "log_tail", "output_path"} <= jcols,
          "stupci posla (napredak, temperatura, log)")
    a = inbox.upsert_profile({"name": "Ana Kovač", "appearance_prompt": "long dark hair, brown eyes, freckles, natural makeup", "age_vibe": "27",
                              "preferred_model": "RealVisXL_V5.0_fp16.safetensors", "model_type": "sdxl"})
    b = inbox.upsert_profile({"name": "Ana Kovac", "appearance_prompt": "short blonde hair, blue eyes", "age_vibe": "31",
                              "preferred_model": "RealVisXL_V5.0_fp16.safetensors", "model_type": "sdxl"})
    s = inbox.upsert_profile({"name": "Mia", "appearance_prompt": "curly red hair, green eyes", "age_vibe": "24",
                              "preferred_model": "realisticVisionV60B1_v51HyperVAE.safetensors", "model_type": "sd15"})
    ta, tb = lt.ensure_trigger(a["id"]), lt.ensure_trigger(b["id"])
    check(ta.startswith("chr_anakovac") and tb.startswith("chr_anakovac") and ta != tb, f"jedinstveni okidači ({ta}, {tb})")
    check(lt.ensure_trigger(a["id"]) == ta and inbox.get_profile(a["id"])["lora_trigger"] == ta, "okidač je stabilan i spremljen u profil")
    da, db = lt.persona_dirs(a["id"]), lt.persona_dirs(b["id"])
    check(da["raw"] != db["raw"] and f"persona_{a['id']}" in str(da["root"]) and da["raw"].is_dir(), "zasebne mape po osobi")
    return a["id"], b["id"], s["id"]


def test_guidance():
    print("== broj slika: savjeti i blokada ==")
    from services import lora_trainer_service as lt
    g = {n: lt.count_guidance(n) for n in (3, 10, 15, 30, 40, 45, 61)}
    check(not g[3]["can_train"] and g[3]["color"] == "bad", "manje od 5 = blokirano")
    check(g[10]["message"] == "Premalo slika, preporuka je 15–40" + "." or g[10]["message"].startswith("Premalo slika, preporuka je 15–40"), f"10 slika: {g[10]['message']}")
    check(g[10]["can_train"] and g[10]["color"] == "warn", "10 slika: upozorenje, ali može")
    check(all(g[n]["message"] == "Idealno" and g[n]["color"] == "ok" for n in (15, 30, 40)), "15–40 = zeleno Idealno")
    check(g[45]["message"].startswith("Previše slika, preporuka je do 40") and g[45]["can_train"], "45 slika: upozorenje")
    check(not g[61]["can_train"], "više od 60 = blokirano")


def test_images(pa, pb):
    print("== Pillow: EXIF, RGB, minimalna veličina, duplikati, uvoz iz galerije ==")
    import inbox
    from PIL import Image
    from services import lora_trainer_service as lt
    from services import generation_service as gs
    rot = jpeg(400, 300, exif_orientation=6)
    rgba = jpeg(500, 500, (10, 200, 30, 128), mode="RGBA", fmt="PNG")
    r = lt.add_images(pa, [(rot, "rot.jpg"), (rgba, "alfa.png"), (jpeg(120, 300), "mala.jpg"), (b"ovo nije slika nego tekst " * 8, "x.jpg"), (rot, "dup.jpg")])
    reasons = [s["reason"] for s in r["skipped"]]
    check(len(r["added"]) == 2, f"dodane 2 ispravne slike ({len(r['added'])})")
    check(any("256" in x for x in reasons), f"premala slika odbijena: {reasons}")
    check(any("oštećen" in x.lower() or "nije slika" in x.lower() or "ne mogu" in x.lower() for x in reasons), f"oštećena slika odbijena {reasons}")
    check(any("već" in x.lower() for x in reasons), "duplikat preskočen")
    items = {it["original_name"]: it for it in r["dataset"]["items"]}
    check(items["rot.jpg"]["width"] == 300 and items["rot.jpg"]["height"] == 400, "EXIF orijentacija ispravljena (300×400)")
    raw = lt.persona_dirs(pa)["raw"] / items["alfa.png"]["filename"]
    with Image.open(raw) as im:
        check(im.mode == "RGB", "RGBA pretvoren u RGB")
    st = lt.dataset_state(pa)
    cap = st["items"][0]["caption"]
    trig = lt.ensure_trigger(pa)
    check(cap.startswith(trig + ",") and "adult woman, 27 years old" in cap, f"automatski opis: {cap}")
    check("long dark hair" in cap and "brown eyes" in cap, "opis sadrži izgled osobe")
    # vlastiti opis i brisanje
    iid = items["alfa.png"]["id"]
    st = lt.set_caption(pa, iid, "smiling in a cafe, portrait")
    it = next(x for x in st["items"] if x["id"] == iid)
    check(it["caption"].startswith(trig + ", ") and "smiling in a cafe" in it["caption"], "vlastiti opis dobiva okidač")
    st = lt.delete_image(pa, iid)
    check(st["count"] == 1 and not raw.exists(), "brisanje slike iz dataseta (i datoteke)")
    # uvoz: referentne slike + „Dobra” iz galerije
    inbox.add_reference_images(pb, [(jpeg(700, 700, (30, 60, 90)), ".jpg"), (jpeg(640, 800, (90, 60, 30)), ".jpg")])
    old_list, old_read = gs.list_gallery, gs.read_item_bytes
    gs.list_gallery = lambda persona_id=None, rating=None, limit=200, **kw: {"items": [{"id": 901, "filename": "g1.png", "rating": 1}, {"id": 902, "filename": "g2.png", "rating": 1}] if persona_id == pb and rating == 1 else []}
    gs.read_item_bytes = lambda it: jpeg(768, 1024, ((it["id"] - 900) * 90, 30, 200))
    try:
        imp = lt.import_from_persona(pb, ["refs", "good"])
    finally:
        gs.list_gallery, gs.read_item_bytes = old_list, old_read
    srcs = sorted(x["source"] for x in imp["dataset"]["items"])
    check(len(imp["added"]) == 4 and srcs.count("ref") == 2 and srcs.count("gallery") == 2, f"uvoz iz galerije osobe: {srcs} {imp['skipped']}")
    try:
        lt.import_from_persona(pa, ["refs"])
        check(False, "uvoz bez slika treba jasnu poruku")
    except ValueError as exc:
        check("referentnih" in str(exc), "uvoz bez slika: jasna poruka")
    # popuni datasete: A = 16 (idealno), B = 4 (+2 = 6)
    lt.clear_dataset(pa)
    r = lt.add_images(pa, varied_images(16))
    check(r["dataset"]["count"] == 16 and r["dataset"]["guidance"]["message"] == "Idealno", "osoba A: 16 slika = Idealno")
    lt.add_images(pb, varied_images(2, base=100))
    check(lt.dataset_state(pb)["count"] == 6, "osoba B: 6 slika (zasebni dataset)")
    check(lt.dataset_state(pa)["count"] == 16, "izolacija: dataset osobe A netaknut")


def test_prepare_and_config(pa, ps):
    print("== Kohya struktura, rezolucije, 8 GB postavke, okruženje ==")
    from PIL import Image
    from services import lora_trainer_service as lt
    trig = lt.ensure_trigger(pa)
    info = lt.prepare_dataset(pa, resolution=768, trigger=trig, repeats=5)
    prep = lt.persona_dirs(pa)["prepared"]
    sub = prep / "img" / f"5_{trig}"
    pngs = sorted(sub.glob("*.png"))
    check(sub.is_dir() and len(pngs) == 16 and len(list(sub.glob("*.txt"))) == 16, f"<repeats>_<okidač> mapa sa 16 slika + opisa ({sub.name})")
    with Image.open(pngs[0]) as im:
        check(im.size == (768, 768) and im.mode == "RGB", f"SDXL izrez 768×768 ({im.size})")
    txt = pngs[0].with_suffix(".txt").read_text(encoding="utf-8")
    check(txt.startswith(trig) and "adult woman" in txt, "opis uz sliku")
    toml = (prep / "dataset.toml").read_text(encoding="utf-8")
    check("[[datasets]]" in toml and "[[datasets.subsets]]" in toml and "num_repeats = 5" in toml and "resolution = 768" in toml and "batch_size = 1" in toml,
          "dataset.toml (Kohya)")
    check(info.get("count", 16) == 16, "prepare_dataset vraća broj slika")
    # SD 1.5 osoba -> 512
    lt.add_images(ps, varied_images(6, base=50))
    plan15 = lt.compute_plan(ps, "balanced", {})
    check(plan15["arch"] == "sd15" and plan15["resolution"] == 512, f"SD 1.5 -> 512 ({plan15['arch']}, {plan15['resolution']})")
    plan = lt.compute_plan(pa, "balanced", {})
    check(plan["arch"] == "sdxl" and plan["resolution"] == 768 and plan["rank"] == 16 and plan["alpha"] == 8, "SDXL: 768, dim 16, alpha 8")
    check(lt.compute_plan(pa, "balanced", {"resolution": 1024})["resolution"] == 768, "balanced na 8 GB ostaje na 768 (1024 samo u Detaljnije)")
    check(lt.compute_plan(pa, "detailed", {"resolution": 1024})["resolution"] == 1024, "Detaljnije i dalje dopušta SDXL 1024")
    check(lt.compute_plan(pa, "balanced", {"resolution": 2048})["resolution"] == 768, "nedopuštena rezolucija -> zadana")
    fast, det = lt.compute_plan(pa, "fast", {}), lt.compute_plan(pa, "detailed", {})
    check(fast["total_steps"] < plan["total_steps"] < det["total_steps"], f"profili brzi < preporučeni < detaljni ({fast['total_steps']}, {plan['total_steps']}, {det['total_steps']})")
    check(plan["eta_seconds"] > 0, "procjena trajanja")
    cfg = lt.build_training_config(plan, base_path=Path("/m/x.safetensors"), output_dir=Path("/o"), output_name="char_x_v1", logs_dir=Path("/l"))
    want = {"gradient_checkpointing": True, "train_batch_size": 1, "mixed_precision": "fp16", "cache_latents": True, "cache_latents_to_disk": True,
            "cache_text_encoder_outputs": True, "cache_text_encoder_outputs_to_disk": True, "network_dim": 16, "network_alpha": 8,
            "optimizer_type": "Adafactor", "lr_scheduler": "constant_with_warmup", "sdpa": True, "xformers": False, "no_half_vae": True}
    bad = {k: cfg.get(k) for k, v in want.items() if cfg.get(k) != v}
    check(not bad, f"8 GB sigurne postavke (SDXL) {bad}")
    check(any("relative_step=False" in a for a in cfg["optimizer_args"]), "Adafactor argumenti")
    check(cfg.get("save_every_n_epochs") == 1 and cfg.get("save_last_n_epochs") == 3, "spremanje nakon svake epohe, zadnje 3")
    check(cfg.get("persistent_data_loader_workers") is False and cfg.get("mem_eff_attn") is False and cfg.get("max_grad_norm") == 0, "VRAM: bez persistent loadera, sdpa, max_grad_norm=0")
    check(not plan.get("resume", {}).get("available") and not plan.get("resume_applied"), "nema nastavka na praznom izlazu")
    tom = lt.to_toml(cfg)
    check("xformers = false" in tom and "8bit" not in tom.lower() and "bitsandbytes" not in tom.lower(), "TOML: bez xformersa i bitsandbytes")
    cfg15 = lt.build_training_config(plan15, base_path=Path("/m/y.safetensors"), output_dir=Path("/o"), output_name="y", logs_dir=Path("/l"))
    check(not cfg15.get("cache_text_encoder_outputs") and cfg15["sdpa"] and not cfg15["xformers"], "SD 1.5 konfiguracija")
    env = lt.training_env()
    check(env.get("TORCH_BACKENDS_CUDNN_ENABLED") == "0" and env.get("PYTORCH_CUDA_ALLOC_CONF") == "max_split_size_mb:128" and env.get("PYTHONUTF8") == "1",
          "okruženje: cuDNN isključen, alloc conf, UTF-8")
    req = lt.parse_requirements("accelerate==1.15.0\ntransformers==5.17.0\ndiffusers[torch]==0.40.0\nbitsandbytes==0.45.0\nxformers\ntorch==2.5\n"
                                "tensorboard\nopencv-python==4.8.1.78\n-e .\nprodigyopt\nsafetensors==0.4.5\n")
    check("bitsandbytes==0.45.0" not in req and not any(x.startswith("xformers") or x.startswith("torch") for x in req), f"pip bez bitsandbytes/xformers/torch: {req}")
    check("diffusers==0.40.0" in req and "accelerate==1.15.0" in req, "pip: diffusers bez [torch] extra")
    launcher = lt.LAUNCHER_SOURCE
    check("TORCH_BACKENDS_CUDNN_ENABLED" in launcher and "enable_flash_sdp" in launcher, "launcher: cuDNN off + SDP fallback za ZLUDA")


def test_base_model(pa):
    print("== bazni model: model osobe, Krea 2 odbijen ==")
    import inbox
    from services import lora_trainer_service as lt
    base, arch = lt.resolve_base_model(inbox.get_profile(pa))
    check(base == "RealVisXL_V5.0_fp16.safetensors" and arch == "sdxl", "model osobe")
    try:
        lt.compute_plan(pa, "balanced", {"base_model": "krea2_dev_fp8.safetensors"})
        check(False, "Krea 2 mora biti odbijen")
    except ValueError as exc:
        check("Krea 2" in str(exc) and "SDXL" in str(exc), f"Krea 2 odbijen hrvatskom porukom")
    cks = lt.list_base_checkpoints()
    check({c["arch"] for c in cks} == {"sdxl", "sd15"}, f"popis baznih modela bez Krea 2 ({[c['name'] for c in cks]})")


def test_temperature_parsing():
    print("== temperatura GPU-a: parseri, pragovi, nedostupan senzor ==")
    from services import hardware_service as hw
    from services import lora_trainer_service as lt
    check(hw.parse_nvidia_smi_temp("67\n") == 67.0, "nvidia-smi")
    check(hw.parse_rocm_smi_temp(json.dumps({"card0": {"Temperature (Sensor edge) (C)": "71.0", "Temperature (Sensor junction) (C)": "85.0"}})) == 71.0, "rocm-smi edge (ne junction)")
    lhm = [{"Identifier": "/gpu-amd/0/temperature/0", "Name": "GPU Core", "Value": 72.5}, {"Identifier": "/gpu-amd/0/temperature/2", "Name": "GPU Hot Spot", "Value": 90},
           {"Identifier": "/amdcpu/0/temperature/0", "Name": "Core", "Value": 60}]
    check(hw.parse_lhm_json(json.dumps(lhm)) == 72.5, "LibreHardwareMonitor WMI (bez hot spota i CPU-a)")
    os.environ["STUDIO_GPU_TEMP"] = "none"
    t = hw.read_gpu_temperature()
    check(t["available"] is False and t["temp_c"] is None and t.get("message") == "Senzor temperature nedostupan", "nedostupan senzor: bez lažnih brojeva")
    os.environ["STUDIO_GPU_TEMP"] = "74"
    t = hw.read_gpu_temperature()
    check(t["available"] and t["temp_c"] == 74.0, "test hook temperature")
    os.environ["STUDIO_GPU_TEMP"] = "61"
    st, msg = lt.classify_temp(None)
    check(st == "unavailable" and msg == "Senzor temperature nedostupan", "klasifikacija: nedostupno")
    check(lt.classify_temp(70)[0] == "ok", "70°C ok")
    st, msg = lt.classify_temp(81)
    check(st == "warn" and msg == "GPU temperatura je visoka (81°C). Provjeri ventilatore i protok zraka.", f"80°C+ upozorenje: {msg}")
    check(lt.classify_temp(88)[0] == "critical", "88°C kritično")
    try:
        lt.save_temp_settings({"warn_c": 90, "critical_c": 85, "stop_c": 92})
        check(False, "neispravni pragovi")
    except ValueError:
        check(True, "neispravni pragovi odbijeni")
    ts = lt.save_temp_settings({"warn_c": 80, "critical_c": 88, "stop_c": 95, "autostop": True})
    check(ts["stop_c"] == 95, "auto-stop prag podesiv")
    lt.save_temp_settings({"warn_c": 80, "critical_c": 88, "stop_c": 92, "autostop": True})


def test_training_run(pa, pb, comfy_url, comfy_dir):
    print("== simulirano treniranje: /free, napredak, auto-dodavanje, verzije ==")
    import inbox
    from services import lora_trainer_service as lt
    from services import generation_service as gs
    lt.configure(comfy_url=comfy_url)
    FakeComfy.calls.clear()
    try:
        lt.start_training(pb, "fast", {"steps": 100, "epochs": 2, "base_model": "krea2_dev_fp8.safetensors"})
        check(False, "Krea 2 start")
    except ValueError:
        check(True, "start s Krea 2 odbijen")
    lt.clear_dataset(pb)
    lt.add_images(pb, varied_images(4, base=200))
    try:
        lt.start_training(pb, "fast", {})
        check(False, "manje od 5 slika mora biti blokirano")
    except ValueError as exc:
        check("Premalo" in str(exc), "start s 4 slike blokiran")
    lt.add_images(pb, varied_images(4, base=300))  # B = 8
    job = lt.start_training(pa, "fast", {"steps": 100, "epochs": 2})
    j = wait_job(lt, job["id"])
    check(j["status"] == "completed", f"posao završen ({j['status']}: {j.get('error_message')})")
    frees = [c for c in FakeComfy.calls if c[0] == "POST" and c[1] == "/free"]
    check(frees and '"unload_models": true' in frees[0][2], "ComfyUI /free pozvan prije treniranja")
    check(j["config"].get("comfy_freed") is True, "posao bilježi oslobođeni VRAM")
    check(j["current_step"] == j["total_steps"] and j["total_steps"] > 0 and j["progress_pct"] == 100, f"napredak {j['current_step']}/{j['total_steps']}")
    check(j["current_epoch"] == 2 and j["loss"] is not None, "epoha i loss iz izlaza")
    log = "\n".join(j["log_lines"])
    check("TORCH_BACKENDS_CUDNN_ENABLED=0" in log and "max_split_size_mb:128" in log, "trener dobiva cuDNN=0 i alloc conf")
    check("--config_file" in log and "--dataset_config" in log, "trener dobiva --config_file i --dataset_config")
    slug_file = j["lora_filename"]
    out = comfy_dir / "models" / "loras" / slug_file
    check(re.fullmatch(r"char_ana_kovac_v1\.safetensors", slug_file) is not None and out.is_file(), f"izlaz u ComfyUI/models/loras ({slug_file})")
    prof = inbox.get_profile(pa)
    trig = prof["lora_trigger"]
    check(prof["preferred_lora"] == slug_file and float(prof["preferred_lora_strength"]) == 0.8 and trig, "LoRA automatski dodana osobi (0.8 + okidač)")
    tr = lt.list_trained(pa)
    check(len(tr) == 1 and tr[0]["is_active"] and tr[0]["exists"], "persona_trained_loras zapis")
    check(not inbox.get_profile(pb).get("preferred_lora"), "izolacija: osoba B nema LoRA-u osobe A")
    # druga verzija + zadrži tuđe LoRA-e u stacku
    inbox.upsert_profile({**inbox.get_profile(pa), "lora_stack": [{"name": slug_file, "strength_model": 0.7}, {"name": "detail_tweaker.safetensors", "strength_model": 0.4}]}, pa)
    j2 = wait_job(lt, lt.start_training(pa, "fast", {"steps": 100, "epochs": 2})["id"])
    prof = inbox.get_profile(pa)
    stack = [x["name"] for x in prof.get("lora_stack") or []]
    check(j2["status"] == "completed" and j2["lora_filename"] == "char_ana_kovac_v2.safetensors" and prof["preferred_lora"] == j2["lora_filename"], "nova verzija v2 postaje aktivna")
    check(slug_file not in stack and "detail_tweaker.safetensors" in stack, f"stara verzija maknuta iz stacka, ostale LoRA-e ostaju ({stack})")
    act = lt.activate_lora(pa, lora_filename=slug_file)
    check(inbox.get_profile(pa)["preferred_lora"] == slug_file and act.get("ok", True), "activate: povratak na v1")
    lt.activate_lora(pa, lora_filename=j2["lora_filename"])
    # osoba B
    jb = wait_job(lt, lt.start_training(pb, "fast", {"steps": 100, "epochs": 2})["id"])
    pbp = inbox.get_profile(pb)
    check(jb["status"] == "completed" and pbp["preferred_lora"] == jb["lora_filename"] and pbp["lora_trigger"] != trig, "osoba B: vlastita LoRA i okidač")
    check(inbox.get_profile(pa)["preferred_lora"] == "char_ana_kovac_v2.safetensors", "izolacija: osoba A zadržala svoju LoRA-u")
    check(not gs.gpu_busy_training(), "GPU slobodan nakon treniranja")
    # neuspjeh (OOM) -> hrvatski savjet
    os.environ["FAKE_TRAINER_MODE"] = "fail"
    try:
        jf = wait_job(lt, lt.start_training(pb, "fast", {"steps": 100, "epochs": 2})["id"])
    finally:
        os.environ.pop("FAKE_TRAINER_MODE", None)
    check(jf["status"] == "failed" and "VRAM" in (jf["error_message"] or ""), f"OOM: jasna poruka ({jf['error_message']})")
    check(inbox.get_profile(pb)["preferred_lora"] == jb["lora_filename"], "neuspjeh ne mijenja profil")
    return trig


def test_generation_trigger(pa, pb, ps, trig_a):
    print("== generiranje: okidač + LoRA osobe, izolacija ==")
    import inbox
    import studio
    from services import lora_trainer_service as lt
    (Path(os.environ["COMFYUI_DIR"]) / "models" / "loras" / "detail_tweaker.safetensors").write_bytes(b"x" * 32)
    obj = {"KSampler": {}, "CheckpointLoaderSimple": {}, "CLIPTextEncode": {}, "EmptyLatentImage": {}, "VAEDecode": {}, "SaveImage": {}, "LoraLoader": {}}
    pa_prof = inbox.get_profile(pa)
    body = {"prompt": "sitting in a sunny cafe, smiling", "persona_id": pa, "model": "RealVisXL_V5.0_fp16.safetensors", "model_type": "sdxl", "seed": 1}
    res = studio.plan_image_generation(dict(body), profile=pa_prof, object_info=obj)
    wf = json.dumps(res.get("workflow") or {})
    meta = res.get("meta") or {}
    check(res.get("ok"), f"plan ok ({res.get('error')})")
    check(meta.get("lora_trigger") == trig_a and trig_a in meta.get("prompt", ""), "okidač automatski u promptu")
    check(pa_prof["preferred_lora"] in wf and meta.get("lora") == pa_prof["preferred_lora"] and abs(float(meta.get("lora_strength") or 0) - 0.8) < 1e-6, "LoRA osobe (0.8) u workflowu")
    check("adult woman" in meta.get("prompt", "") and "sitting in a sunny cafe" in meta.get("prompt", ""), "scena i 'adult woman' ostaju")
    res_ui = studio.plan_image_generation(dict(body, lora=pa_prof["preferred_lora"], lora_strength=0.8), profile=pa_prof, object_info=obj)
    check((res_ui.get("meta") or {}).get("lora_trigger") == trig_a, "UI šalje LoRA-u osobe -> okidač")
    res_off = studio.plan_image_generation(dict(body, lora=""), profile=pa_prof, object_info=obj)
    check(not (res_off.get("meta") or {}).get("lora_trigger") and trig_a not in (res_off.get("meta") or {}).get("prompt", ""), "LoRA isključena -> bez okidača")
    pb_prof = inbox.get_profile(pb)
    old_refs = inbox.reference_paths
    inbox.reference_paths = lambda pid: []  # B ima referentne slike; IP-Adapter ovdje nije tema
    try:
        res_b = studio.plan_image_generation(dict(body, persona_id=pb), profile=pb_prof, object_info=obj)
    finally:
        inbox.reference_paths = old_refs
    mb = res_b.get("meta") or {}
    check(mb.get("lora_trigger") == pb_prof["lora_trigger"] and not re.search(rf"\b{trig_a}\b", mb.get("prompt", "")) and pa_prof["preferred_lora"] not in json.dumps(res_b.get("workflow")),
          "izolacija: osoba B ne dobiva okidač ni LoRA-u osobe A")
    res_s = studio.plan_image_generation(dict(body, persona_id=ps, model="realisticVisionV60B1_v51HyperVAE.safetensors", model_type="sd15"), profile=inbox.get_profile(ps), object_info=obj)
    check(not (res_s.get("meta") or {}).get("lora_trigger"), "osoba bez trenirane LoRA-e: bez okidača")
    check(lt.trigger_for_generation(pa_prof, {}, "krea2") == "", "Krea 2: bez okidača")
    check(lt.apply_trigger("chr_x, beach", "chr_x") == "chr_x, beach" and lt.apply_trigger("beach", "chr_x") == "chr_x, beach", "okidač se ne duplicira")


def test_temperature_run(pa):
    print("== treniranje: upozorenje na 80°C, auto-stop na 92°C ==")
    from services import lora_trainer_service as lt
    tmpf = Path(tempfile.mkstemp(suffix=".txt")[1])
    tmpf.write_text("65", encoding="utf-8")
    os.environ.pop("STUDIO_GPU_TEMP", None)
    os.environ.update({"STUDIO_GPU_TEMP_FILE": str(tmpf), "FAKE_TRAINER_HEAT_FILE": str(tmpf), "FAKE_TRAINER_HEAT_AT": "8:83,40:93",
                       "FAKE_TRAINER_DELAY": "0.03"})
    try:
        job = lt.start_training(pa, "fast", {"steps": 300, "epochs": 2})
        seen_warn = None
        end = time.time() + 60
        while time.time() < end:
            j = lt.get_job(job["id"])
            if j["gpu_temp_status"] == "warn" and not seen_warn:
                seen_warn = j["gpu_warning_message"]
            if not j["active"]:
                break
            time.sleep(0.02)
        j = wait_job(lt, job["id"])
    finally:
        for k in ("STUDIO_GPU_TEMP_FILE", "FAKE_TRAINER_HEAT_FILE", "FAKE_TRAINER_HEAT_AT", "FAKE_TRAINER_DELAY"):
            os.environ.pop(k, None)
        os.environ["STUDIO_GPU_TEMP"] = "61"
        tmpf.unlink(missing_ok=True)
    log = "\n".join(j["log_lines"])
    check(seen_warn == "GPU temperatura je visoka (83°C). Provjeri ventilatore i protok zraka.", f"upozorenje uživo: {seen_warn}")
    check("GPU temperatura je visoka (83°C)" in log, "upozorenje zapisano u log")
    check(j["status"] == "paused_overheat" and (j["gpu_temp_peak_c"] or 0) >= 92, f"auto-stop: {j['status']} (vrh {j['gpu_temp_peak_c']})")
    check(j["current_step"] < j["total_steps"], "proces zaustavljen prije kraja")
    check("92" in (j["gpu_warning_message"] or "") or "93" in (j["gpu_warning_message"] or ""), f"poruka o auto-stopu: {j['gpu_warning_message']}")
    check(not lt.training_active(), "nakon auto-stopa GPU je slobodan")


def test_cancel_and_lock(pa, pb):
    print("== jedan posao istovremeno, blokada generiranja, Zaustavi (stablo procesa) ==")
    from services import lora_trainer_service as lt
    from services import generation_service as gs
    pidf = Path(tempfile.mkstemp(suffix=".pid")[1])
    pidf.write_text("", encoding="utf-8")
    os.environ.update({"FAKE_TRAINER_MODE": "slow", "FAKE_TRAINER_DELAY": "0.2", "FAKE_TRAINER_PID_FILE": str(pidf), "FAKE_TRAINER_CHILD": "1"})
    try:
        job = lt.start_training(pa, "fast", {"steps": 300, "epochs": 2})
        end = time.time() + 20
        while time.time() < end and lt.get_job(job["id"])["status"] != "training":
            time.sleep(0.05)
        check(lt.get_job(job["id"])["status"] == "training", "status: training")
        try:
            lt.start_training(pb, "fast", {"steps": 100, "epochs": 2})
            check(False, "drugi posao mora biti blokiran")
        except lt.TrainerBusy as exc:
            check("već" in str(exc).lower() or "traje" in str(exc).lower(), "drugi posao istovremeno blokiran")
        check(gs.gpu_busy_training() and gs.process_next() is None, "red generiranja čeka dok traje treniranje")
        try:
            lt.delete_image(pa, lt.dataset_state(pa)["items"][0]["id"])
            check(False, "brisanje tijekom treniranja")
        except (ValueError, RuntimeError, lt.TrainerBusy):
            check(True, "dataset zaključan tijekom treniranja")
        pids = [int(x) for x in pidf.read_text().split()]
        check(len(pids) == 2 and all(pid_alive(p) for p in pids), "trener i njegov podproces rade")
        j = lt.cancel_job(job["id"])
        time.sleep(0.3)
        check(j["status"] == "canceled", f"Zaustavi -> canceled ({j['status']})")
        check(not any(pid_alive(p) for p in pids), "ugašeno cijelo stablo procesa (SIGTERM grupi)")
        check(not lt.training_active() and not gs.gpu_busy_training(), "GPU otključan")
    finally:
        for k in ("FAKE_TRAINER_MODE", "FAKE_TRAINER_DELAY", "FAKE_TRAINER_PID_FILE", "FAKE_TRAINER_CHILD"):
            os.environ.pop(k, None)
        pidf.unlink(missing_ok=True)
    # zastarjeli aktivni posao nakon pada Studija
    from services.common import conn
    with conn() as c:
        cur = c.execute("INSERT INTO lora_training_jobs(profile_id, status, created_at) VALUES (?,?,?)", (pa, "training", time.time()))
        sid = cur.lastrowid
    lt.ensure_schema()
    st = lt.get_job(sid)
    check(st["status"] == "failed" and "zatvoren" in st["error_message"], "nakon ponovnog pokretanja zastarjeli posao = failed")


def test_status_install():
    print("== status / priprema okruženja ==")
    from services import lora_trainer_service as lt
    st = lt.status()
    check(st["ready"] and st["override_cmd"] and not st["backend_installed"], "status: override spreman, sd-scripts nije instaliran")
    check(st["sd_scripts_dir"].replace("\\", "/").endswith("trainer/sd-scripts"), f"sd-scripts u <DATA_DIR>/trainer/sd-scripts ({st['sd_scripts_dir']})")
    check([p["id"] for p in st["presets"]] == ["fast", "balanced", "detailed"] and st["default_preset"] == "balanced", "profili i zadani 'balanced'")
    check(next(p for p in st["presets"] if p["id"] == "balanced")["label"] == "Preporučeno za RX 6600", "oznaka 'Preporučeno za RX 6600'")
    check("bitsandbytes" in lt.SKIP_PACKAGES and "xformers" in lt.SKIP_PACKAGES, "instalacija preskače bitsandbytes i xformers")
    check(callable(lt.install_backend) and isinstance(lt.install_state(), dict), "install_backend API")


# ---------------------------------------------------------------- HTTP + UI

BROWSER_SCRIPT = r"""
import json, sys
from playwright.sync_api import sync_playwright
url, exe, img_dir, pid = sys.argv[1], sys.argv[2] or None, sys.argv[3], int(sys.argv[4])
import glob
files = sorted(glob.glob(img_dir + "/*.jpg"))
out = {}
with sync_playwright() as p:
    kw = {"args": ["--no-sandbox"]}
    if exe:
        kw["executable_path"] = exe
    b = p.chromium.launch(**kw)
    pg = b.new_page(viewport={"width": 1400, "height": 1000})
    errs, cons = [], []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: cons.append(m.text) if m.type == "error" else None)
    pg.goto(url)
    pg.wait_for_timeout(2000)
    pg.click('.tabs button[data-tab="influenceri"]')
    pg.wait_for_selector("#ltPersona option", state="attached", timeout=15000)
    pg.wait_for_timeout(800)
    out["visible"] = pg.evaluate('() => { const e = document.getElementById("loraTrainer"); return !!e && e.offsetHeight > 100 && e.closest("#tab-influenceri") !== null; }')
    out["steps_text"] = pg.inner_text("#loraTrainer")
    out["presets"] = pg.evaluate('() => Array.from(document.querySelectorAll("#ltPresets .lt-preset")).map(b => [b.dataset.preset, b.classList.contains("on")])')
    out["setup_hidden"] = pg.evaluate('() => document.getElementById("ltSetup").hidden')
    out["nav_tabs"] = pg.evaluate('() => document.querySelectorAll(".tabs button").length')
    out["persona_btn"] = pg.evaluate('() => !!document.getElementById("pLoraTrainer")')
    pg.select_option("#ltPersona", str(pid))
    pg.wait_for_timeout(600)
    pg.set_input_files("#ltFile", files[:3])
    pg.wait_for_function('() => /^3 /.test(document.getElementById("ltCount").textContent)', timeout=20000)
    out["count_low"] = [pg.inner_text("#ltCount"), pg.get_attribute("#ltCount", "class")]
    out["start_disabled_low"] = pg.is_disabled("#ltStart")
    pg.set_input_files("#ltFile", files[3:18])
    pg.wait_for_function('() => /^18 /.test(document.getElementById("ltCount").textContent)', timeout=30000)
    out["count_ok"] = [pg.inner_text("#ltCount"), pg.get_attribute("#ltCount", "class")]
    out["thumbs"] = pg.evaluate('() => document.querySelectorAll("#ltGrid .lt-shot img").length')
    pg.click("#ltGrid .lt-shot .lt-del", force=True)
    pg.wait_for_function('() => /^17 /.test(document.getElementById("ltCount").textContent)', timeout=10000)
    out["after_delete"] = pg.inner_text("#ltCount")
    out["captions_hidden"] = pg.evaluate('() => !document.getElementById("ltCaps").open')
    pg.click('#ltPresets [data-preset="fast"]')
    pg.wait_for_timeout(300)
    pg.evaluate('() => { document.getElementById("ltAdv").open = true; }')
    pg.fill("#ltSteps", "100")
    pg.fill("#ltEpochs", "2")
    pg.dispatch_event("#ltEpochs", "change")
    pg.wait_for_timeout(700)
    out["plan"] = pg.inner_text("#ltPlan")
    out["start_enabled"] = not pg.is_disabled("#ltStart")
    pg.click("#ltStart")
    pg.wait_for_selector('#ltJob [data-act="gen"]', timeout=60000)
    out["done_text"] = pg.inner_text("#ltJob")
    pg.locator("#loraTrainer").screenshot(path=img_dir + "/../ui_trainer.png")
    pg.click('#ltJob [data-act="gen"]')
    pg.wait_for_timeout(1500)
    out["gen_tab"] = pg.evaluate('() => document.getElementById("tab-slike").classList.contains("on")')
    out["gen_persona"] = pg.evaluate('() => document.getElementById("osoba").value')
    out["gen_lora"] = pg.evaluate('() => document.getElementById("lora").value')
    pg.screenshot(path=img_dir + "/../ui_done.png", full_page=False)
    out["errors"] = errs
    out["console"] = cons
    b.close()
print(json.dumps(out, ensure_ascii=False))
"""


def test_http_and_ui(tmp: Path, comfy_dir: Path):
    print("== HTTP API (studio.py) + headless UI ==")
    data_dir = tmp / "srv"
    data_dir.mkdir()
    comfy_srv, comfy_url = start_fake_comfy()
    port = free_port()
    env = dict(os.environ, STUDIO_DATA_DIR=str(data_dir), STUDIO_PORT=str(port), STUDIO_NO_BROWSER="1", COMFYUI_URL=comfy_url,
               STUDIO_MOCK_GPU="AMD Radeon RX 6600|8", COMFYUI_DIR=str(comfy_dir), STUDIO_LORA_TRAINER_CMD=FAKE_CMD, STUDIO_GPU_TEMP="66",
               STUDIO_LORA_TEMP_INTERVAL="0.1")
    for k in ("XAI_API_KEY", "FAKE_TRAINER_MODE"):
        env.pop(k, None)
    proc = subprocess.Popen([sys.executable, str(ROOT / "studio.py")], cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(200):
            try:
                http("GET", base + "/api/state")
                break
            except Exception:
                time.sleep(0.1)
        code, st = http("GET", base + "/api/lora-trainer/status")
        check(code == 200 and st["ready"] and st["gpu_temp"]["temp_c"] == 66.0, "GET status")
        code, gt = http("GET", base + "/api/lora-trainer/gpu-temp")
        check(code == 200 and gt["available"] and gt["status"] == "ok", "GET gpu-temp")
        code, ib = http("GET", base + "/api/lora-trainer/install-backend")
        check(code == 200 and "install" in ib, "GET install-backend")
        code, s = http("GET", base + "/api/state")
        pid = s["profiles"][0]["id"]
        http("PUT", base + f"/api/profiles/{pid}", {**s["profiles"][0], "preferred_model": "RealVisXL_V5.0_fp16.safetensors", "model_type": "sdxl", "age_vibe": "28"})
        code, p2 = http("POST", base + "/api/profiles", {"name": "Lea", "appearance_prompt": "wavy brown hair", "age_vibe": "29",
                                                           "preferred_model": "RealVisXL_V5.0_fp16.safetensors", "model_type": "sdxl"})
        pid2 = (p2.get("profile") or {}).get("id") or p2.get("id")
        code, pers = http("GET", base + "/api/lora-trainer/personas")
        check(code == 200 and len(pers["personas"]) >= 2, "GET personas")
        imgs = [{"name": f"i{i}.jpg", "data": "data:image/jpeg;base64," + base64.b64encode(jpeg(600, 800, (i * 20, 100, 90))).decode()} for i in range(6)]
        code, up = http("POST", base + f"/api/lora-trainer/dataset/{pid2}/upload", {"images": imgs})
        check(code == 200 and len(up["added"]) == 6 and up["dataset"]["guidance"]["color"] == "warn", "POST upload (JSON base64)")
        bnd = "----studio" + str(int(time.time()))
        parts = b""
        for i in range(2):
            parts += (f"--{bnd}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"m{i}.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n").encode() + jpeg(640, 640, (5, 50 + i * 40, 200)) + b"\r\n"
        parts += f"--{bnd}--\r\n".encode()
        code, mu = http("POST", base + f"/api/lora-trainer/dataset/{pid2}/upload", raw=parts, ctype=f"multipart/form-data; boundary={bnd}")
        check(code == 200 and len(mu.get("added") or []) == 2, f"POST upload (multipart) {code} {str(mu)[:120]}")
        code, ds = http("GET", base + f"/api/lora-trainer/dataset/{pid2}")
        check(code == 200 and ds["count"] == 8, "GET dataset")
        code, th = http("GET", base + ds["items"][0]["thumb_url"])
        check(code == 200 and isinstance(th, bytes) and th[:2] == b"\xff\xd8", "GET sličica")
        code, cp = http("POST", base + f"/api/lora-trainer/dataset/{pid2}/images/{ds['items'][0]['id']}/caption", {"caption": "close-up portrait"})
        check(code == 200, "POST opis")
        code, dl = http("DELETE", base + f"/api/lora-trainer/dataset/{pid2}/images/{ds['items'][1]['id']}")
        check(code == 200 and dl["count"] == 7, "DELETE slika")
        code, pl = http("POST", base + "/api/lora-trainer/plan", {"profile_id": pid2, "preset": "balanced", "advanced": {}})
        check(code == 200 and pl["plan"]["arch"] == "sdxl" and pl["plan"]["total_steps"] > 0, "POST plan")
        code, kr = http("POST", base + "/api/lora-trainer/plan", {"profile_id": pid2, "advanced": {"base_model": "krea2_dev_fp8.safetensors"}})
        check(code == 400 and "Krea 2" in kr["error"], "plan s Krea 2 -> 400 + poruka")
        code, bad = http("POST", base + "/api/lora-trainer/start", {"profile_id": 99999})
        check(code in (400, 404), "start za nepostojeću osobu")
        # spor posao: 409 za drugi posao i za /api/generate
        envslow = {"preset": "fast", "advanced": {"steps": 2000, "epochs": 2}}
        # (spori način kroz STUDIO env nije moguć naknadno; 2000 koraka s fake trenerom traje ~20 s)
        code, sj = http("POST", base + "/api/lora-trainer/start", {"profile_id": pid2, **envslow})
        check(code == 200 and sj["job"]["status"] in ("queued", "preparing", "caching", "training"), "POST start")
        code, busy = http("POST", base + "/api/lora-trainer/start", {"profile_id": pid, **envslow})
        check(code == 409, "drugi start -> 409")
        code, gen = http("POST", base + "/api/generate", {"prompt": "test", "persona_id": pid})
        check(code == 409 and gen.get("need") == "lora-training", "/api/generate tijekom treniranja -> 409")
        code, jb = http("GET", base + f"/api/lora-trainer/jobs/{sj['job']['id']}")
        check(code == 200 and jb["job"]["active"], "GET jobs/<id>")
        code, cj = http("POST", base + f"/api/lora-trainer/jobs/{sj['job']['id']}/cancel")
        check(code == 200 and cj["job"]["status"] == "canceled", "POST cancel")
        code, js = http("GET", base + f"/api/lora-trainer/jobs?profile_id={pid2}")
        check(code == 200 and js["jobs"] and js["active_job"] is None, "GET jobs")
        code, sj = http("POST", base + "/api/lora-trainer/start", {"profile_id": pid2, "preset": "fast", "advanced": {"steps": 100, "epochs": 2}})
        end = time.time() + 60
        job = sj["job"]
        while time.time() < end and job["active"]:
            time.sleep(0.2)
            job = http("GET", base + f"/api/lora-trainer/jobs/{job['id']}")[1]["job"]
        check(job["status"] == "completed" and job["gpu_temp_c"] == 66.0, f"posao preko API-ja završen ({job['status']})")
        check(any(c[1] == "/free" for c in FakeComfy.calls), "server je pozvao ComfyUI /free")
        code, lo = http("GET", base + f"/api/lora-trainer/loras?profile_id={pid2}")
        check(code == 200 and lo["loras"] and lo["loras"][0]["is_active"], "GET loras")
        code, ac = http("POST", base + "/api/lora-trainer/activate", {"profile_id": pid2, "lora_id": lo["loras"][0]["id"]})
        check(code == 200, "POST activate")
        code, s3 = http("GET", base + "/api/state")
        p3 = next(p for p in s3["profiles"] if p["id"] == pid2)
        check(p3["preferred_lora"] == job["lora_filename"] and p3["lora_trigger"] == job["trigger_word"], "/api/state: profil ima LoRA-u i okidač")
        code, sett = http("POST", base + "/api/lora-trainer/settings", {"warn_c": 80, "critical_c": 88, "stop_c": 90, "autostop": True})
        check(code == 200 and sett["temp"]["stop_c"] == 90, "POST settings (prag auto-stopa)")
        code, js_raw = http("GET", base + "/static/lora_trainer.js")
        check(code == 200 and b"StudioLoraTrainer" in js_raw, "/static/lora_trainer.js")
        code, css = http("GET", base + "/static/lora_trainer.css")
        check(code == 200, "/static/lora_trainer.css")
        browser(base + "/", tmp, pid)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()
        comfy_srv.shutdown()


def browser(url: str, tmp: Path, pid: int):
    py = os.environ.get("PW_PYTHON") or sys.executable
    if subprocess.run([py, "-c", "import playwright"], capture_output=True).returncode != 0:
        print("  SKIP playwright nije instaliran (postavi PW_PYTHON)")
        return
    img_dir = tmp / "ui_imgs"
    img_dir.mkdir()
    for i in range(20):
        (img_dir / f"u{i:02d}.jpg").write_bytes(jpeg(640, 860, ((i * 37) % 255, 90, (i * 11) % 255)))
    exe = os.environ.get("PW_CHROME") or shutil.which("google-chrome") or shutil.which("chromium") or ""
    r = subprocess.run([py, "-c", BROWSER_SCRIPT, url, exe, str(img_dir), str(pid)], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        check(False, "browser: " + r.stderr[-900:])
        return
    o = json.loads(r.stdout.strip().splitlines()[-1])
    for name in ("ui_done.png", "ui_trainer.png"):
        if (tmp / name).exists():
            shutil.copy(tmp / name, "/tmp/lora_trainer_" + name)
    t = o["steps_text"]
    check(o["visible"], "LoRA trener u kartici Osobe")
    for s in ("Odaberi osobu", "Dodaj 15–40 slika", "Pokreni treniranje", "Uvezi iz galerije osobe", "Pregled opisa", "Napredno", "Povuci slike ovdje"):
        check(s in t, f"UI tekst: {s}")
    check(o["presets"] == [["fast", False], ["balanced", True], ["detailed", False]], f"profili, zadano Preporučeno ({o['presets']})")
    check(o["setup_hidden"], "bez bannera kad je trener spreman")
    check(o["nav_tabs"] == 8, f"gornja navigacija nije proširena ({o['nav_tabs']})")
    check(o["persona_btn"], "gumb 'LoRA trener' na kartici osobe")
    check("Premalo slika za treniranje" in o["count_low"][0] and "bad" in (o["count_low"][1] or "") and o["start_disabled_low"], f"3 slike: crveno + gumb onemogućen ({o['count_low']})")
    check("Idealno" in o["count_ok"][0] and "ok" in (o["count_ok"][1] or "").split(), f"18 slika: zeleno Idealno ({o['count_ok']})")
    check(o["thumbs"] == 18 and o["after_delete"].startswith("17 "), "mini galerija + brisanje")
    check(o["captions_hidden"], "opisi skriveni pod 'Pregled opisa'")
    check("koraka" in o["plan"] and "RX 6600" in o["plan"], f"plan: {o['plan'][:120]}")
    check(o["start_enabled"], "gumb Pokreni treniranje omogućen")
    check("automatski dodana" in o["done_text"] and "Generiraj s ovom osobom" in o["done_text"], "poruka o završetku + Generiraj s ovom osobom")
    check(o["gen_tab"] and o["gen_persona"] == str(pid) and o["gen_lora"].startswith("char_"), f"Generiranje: osoba i LoRA odabrani ({o['gen_persona']}, {o['gen_lora']})")
    check(not o["errors"], f"nema page grešaka: {o['errors'][:3]}")
    real = [c for c in o["console"] if "Failed to load resource" not in c]
    check(not real, f"nema console grešaka: {real[:3]}")



def test_progress_resume_stall(pa, comfy_dir):
    print("== tqdm \\r napredak, nastavak od epohe, upozorenje na zastoj ==")
    from services import lora_trainer_service as lt

    line = "\x1b[K\x1b[Asteps:  29%|██▉       | 336/1160 [34:31<1:24:40,  6.17s/it, avr_loss=0.106]"
    info = lt.parse_progress_line(line)
    check(info.get("step") == 336 and info.get("total") == 1160 and info.get("remaining") == 1 * 3600 + 24 * 60 + 40 and abs((info.get("loss") or 0) - 0.106) < 1e-6,
          f"parse tqdm+ANSI: {info}")
    buf, lines = lt.decode_trainer_chunks(b"", b"cache...\rsteps:  10%|##        | 10/100 [00:10<01:30,  2.00s/it, avr_loss=0.12]\rsteps:  11%|##        | 11/100 [00:11<01:28,  2.00s/it, avr_loss=0.11]\nepoch 2/8\n")
    steps = [lt.parse_progress_line(x) for x in lines]
    check(len(lines) == 4 and steps[1].get("step") == 10 and steps[2].get("step") == 11 and steps[3].get("epoch") == 2,
          f"cijepanje po \\r/\\n: {lines!r} {steps}")
    tmp = comfy_dir / "epoch_tmp"
    tmp.mkdir(exist_ok=True)
    (tmp / "char_x_v5-000001.safetensors").write_bytes(b"x" * 32)
    (tmp / "char_x_v5-000002.safetensors").write_bytes(b"y" * 48)
    (tmp / "char_x_v5.safetensors").write_bytes(b"z" * 16)
    ck = lt.list_epoch_checkpoints(tmp, "char_x_v5")
    check([c["epoch"] for c in ck] == [1, 2] and lt.latest_epoch_checkpoint(tmp, "char_x_v5")["epoch"] == 2, "popis epoha 00000N")
    check(lt.partial_lora_filename("char_x_v5.safetensors", 2) == "char_x_v5-e2.safetensors", "ime djelomične LoRA-e")

    # živi koraci iz tqdm \\r (prije novog retka epohe 2)
    os.environ["FAKE_TRAINER_DELAY"] = "0.04"
    os.environ.pop("FAKE_TRAINER_STOP_AT", None)
    os.environ.pop("FAKE_TRAINER_MODE", None)
    job = lt.start_training(pa, "fast", {"steps": 100, "epochs": 2, "resume": False})
    seen = 0
    end = time.time() + 20
    while time.time() < end:
        j = lt.get_job(job["id"])
        seen = max(seen, int(j.get("current_step") or 0))
        if seen >= 3 and j["status"] == "training":
            break
        if not j["active"]:
            break
        time.sleep(0.04)
    check(seen >= 3, f"koraci se osvježavaju uživo iz tqdm \\r (vidio {seen})")
    # ne čekaj kraj ovog posla — zaustavi da uštedimo vrijeme; epoha 1 možda još nije spremljena
    if lt.get_job(job["id"])["active"]:
        lt.cancel_job(job["id"])
        wait_job(lt, job["id"])

    # prekid nakon 1. epohe -> djelomična LoRA + nastavak
    plan = lt.compute_plan(pa, "fast", {"steps": 100, "epochs": 2, "resume": False})
    stop_at = max(1, int(plan["total_steps"] // max(1, plan["epochs"])))
    os.environ["FAKE_TRAINER_STOP_AT"] = str(stop_at)
    os.environ["FAKE_TRAINER_DELAY"] = "0.01"
    try:
        j1 = wait_job(lt, lt.start_training(pa, "fast", {"steps": 100, "epochs": 2, "resume": False})["id"])
    finally:
        os.environ.pop("FAKE_TRAINER_STOP_AT", None)
    check(j1["status"] in {"failed", "canceled"}, f"prekid nakon epohe 1 ({j1['status']}: {j1.get('error_message')})")
    check((j1.get("lora_filename") or "").endswith("-e1.safetensors") or (j1.get("output_path") or "").endswith("-e1.safetensors"),
          f"djelomična LoRA spremljena kao -e1 ({j1.get('lora_filename')} {j1.get('output_path')})")
    outp = Path(j1.get("output_path") or "")
    check(outp.is_file() and outp.stat().st_size > 0, "djelomična LoRA postoji na disku")
    plan_r = lt.compute_plan(pa, "fast", {"steps": 100, "epochs": 2})
    r = plan_r.get("resume") or {}
    check(r.get("available") and r.get("epoch") == 1 and r.get("label") == "Nastavi od epohe 1", f"plan nudi nastavak: {r}")
    check(plan_r.get("resume_applied") and plan_r["epochs"] == 1 and plan_r.get("network_weights"), f"zadano nastavi: epohe={plan_r.get('epochs')} w={plan_r.get('network_weights')}")
    plan_fresh = lt.compute_plan(pa, "fast", {"steps": 100, "epochs": 2, "resume": False})
    check(not plan_fresh.get("resume_applied") and plan_fresh["epochs"] == 2, "resume=False kreće ispočetka")
    j2 = wait_job(lt, lt.start_training(pa, "fast", {"steps": 100, "epochs": 2})["id"])
    check(j2["status"] == "completed", f"nastavak završio ({j2['status']}: {j2.get('error_message')})")
    train_cfg = (j2.get("config") or {}).get("training") or {}
    check(bool(train_cfg.get("network_weights")) and int((j2.get("config") or {}).get("resume_from_epoch") or 0) == 1, f"network_weights i resume_from_epoch=1 ({train_cfg.get('network_weights')})")
    check(j2.get("lora_filename") and not str(j2.get("lora_filename")).endswith("-e1.safetensors"), f"konačna LoRA nije -e1 ({j2.get('lora_filename')})")

    # zastoj: upozorenje, bez auto-stopa (zadano)
    lt.configure(stall_warn=0.35, stall_stop=8)
    os.environ["FAKE_TRAINER_MODE"] = "stall"
    os.environ["FAKE_TRAINER_STOP_AT"] = "5"
    os.environ["FAKE_TRAINER_DELAY"] = "0.02"
    try:
        js = lt.start_training(pa, "fast", {"steps": 100, "epochs": 2, "resume": False, "stall_autostop": False})
        warned = None
        end = time.time() + 12
        while time.time() < end:
            j = lt.get_job(js["id"])
            if j.get("stall_warning"):
                warned = j
                break
            if not j["active"]:
                warned = j
                break
            time.sleep(0.05)
        check(warned and warned.get("stall_warning") and warned.get("stall_message") == lt.STALL_MESSAGE, f"upozorenje na zastoj: {None if not warned else warned.get('stall_message')}")
        check(warned.get("active") or warned.get("status") == "training", f"zadano samo upozorenje, posao još traje ({warned.get('status')})")
        lt.cancel_job(js["id"])
        wait_job(lt, js["id"])

        # opcijski auto-stop
        lt.configure(stall_warn=0.25, stall_stop=0.5)
        ja = lt.start_training(pa, "fast", {"steps": 100, "epochs": 2, "resume": False, "stall_autostop": True})
        jt = wait_job(lt, ja["id"], timeout=20)
        check(jt["status"] == "failed" and lt.STALL_MESSAGE in (jt.get("error_message") or ""), f"auto-stop na zastoj: {jt['status']} {jt.get('error_message')}")
    finally:
        os.environ.pop("FAKE_TRAINER_MODE", None)
        os.environ.pop("FAKE_TRAINER_STOP_AT", None)
        os.environ.pop("FAKE_TRAINER_DELAY", None)
        lt.configure(stall_warn=None, stall_stop=None)
        os.environ["STUDIO_GPU_TEMP"] = "61"


def test_static_safety():
    print("== UI datoteke, sigurnost sadržaja, pakiranje ==")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    check('id="loraTrainer"' in html and "/static/lora_trainer.js" in html and "/static/lora_trainer.css" in html, "index.html uključuje trener")
    js = (ROOT / "static" / "lora_trainer.js").read_text(encoding="utf-8")
    for s in ("Pripremi okruženje za treniranje", "Zaustavi", "Prikaži log", "Generiraj s ovom osobom", "Senzor temperature nedostupan", "Ne zatvaraj Studio", "Nastavi od epohe", "ltResume"):
        check(s in js, f"lora_trainer.js: {s}")
    for p in ("services/lora_trainer_service.py", "api_lora.py", "static/lora_trainer.js", "static/lora_trainer.css", "services/hardware_service.py"):
        txt = (ROOT / p).read_text(encoding="utf-8")
        check(not BANNED.search(txt), f"{p}: bez zabranjenih izraza")
        check(not re.search(r"(ghp_|github_pat_|xai-)[A-Za-z0-9]{10,}", txt), f"{p}: bez tokena")
    rel = (ROOT / "tools" / "make_release.sh").read_text(encoding="utf-8")
    check(all(x in rel for x in ("services/lora_trainer_service.py", "api_lora.py", "static/lora_trainer.js")), "make_release.sh: nove datoteke u obaveznima")
    svc = (ROOT / "services" / "lora_trainer_service.py").read_text(encoding="utf-8")
    check("adult woman" in svc and "keyword" not in svc.lower(), "opisi: adult woman; bez filtriranja korisničkih promptova")


def main():
    print("test_lora_trainer")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        comfy = setup(tmp)
        comfy_srv, comfy_url = start_fake_comfy()
        try:
            pa, pb, ps = test_schema_and_triggers()
            test_guidance()
            test_images(pa, pb)
            test_prepare_and_config(pa, ps)
            test_base_model(pa)
            test_temperature_parsing()
            test_status_install()
            trig = test_training_run(pa, pb, comfy_url, comfy)
            test_generation_trigger(pa, pb, ps, trig)
            test_temperature_run(pa)
            test_cancel_and_lock(pa, pb)
            test_progress_resume_stall(pa, comfy)
        finally:
            comfy_srv.shutdown()
        test_static_safety()
        test_http_and_ui(tmp, comfy)
    print()
    if FAILED:
        print(f"NEUSPJELO: {FAILED}")
        sys.exit(1)
    print("SVE OK")


if __name__ == "__main__":
    main()
