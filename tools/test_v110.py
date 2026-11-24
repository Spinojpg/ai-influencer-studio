#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.1.0: services paket, hardver (RX 6600), generiranje (FreeU, tiled VAE, LoRA stack,
InstantID, predlošci, red čekanja, character sheet, dataset), objave, CRM, API rute i UI (Playwright).

Sve vanjsko (ComfyUI, Meta, Telegram, LLM) je lažirano. Za UI: PW_PYTHON=/put/do/pythona-s-playwrightom.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

FAILED = 0


def check(cond, msg):
    global FAILED
    if cond:
        print("  OK ", msg)
    else:
        FAILED += 1
        print("  FAIL", msg)


def tiny_png(w=8, h=8, rgb=(200, 120, 90)) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def png_size(data: bytes) -> tuple[int, int]:
    return struct.unpack(">II", data[16:24])


# ---------------------------------------------------------------- sigurnost / pakiranje

BANNED = re.compile(r"\b(lustify|snofs|nsfw|nude|naked|topless|porn\w*|erotic\w*|lingerie)\b", re.I)


def test_package_and_safety():
    print("== services paket, pakiranje, sigurnost sadržaja ==")
    for name in ("__init__.py", "common.py", "hardware_service.py", "generation_service.py", "posting_service.py", "crm_service.py"):
        check((ROOT / "services" / name).is_file(), f"services/{name}")
    check((ROOT / "static" / "v11.js").is_file() and (ROOT / "static" / "v11.css").is_file(), "static/v11.js + v11.css")
    check((ROOT / "DOKUMENTACIJA.md").is_file(), "DOKUMENTACIJA.md postoji")
    rel = (ROOT / "tools" / "make_release.sh").read_text(encoding="utf-8")
    check("rglob" in rel and "DOKUMENTACIJA.md" in rel and "services" in rel and "static" in rel, "make_release.sh pakira services/, static/ i DOKUMENTACIJA.md")
    # nema eksplicitnih modela / ključnih riječi u kodu koji isporučujemo kao zadani sadržaj
    for p in list((ROOT / "services").glob("*.py")) + list((ROOT / "static").glob("*")) + [ROOT / "api_v11.py", ROOT / "model_download.py"]:
        txt = p.read_text(encoding="utf-8")
        bad = BANNED.findall(txt)
        check(not bad, f"{p.relative_to(ROOT)}: bez eksplicitnih pojmova {bad[:3]}")
    import model_download
    loras = [c for c in model_download.CURATED if c.get("group") == model_download.CURATED_LORA_GROUP]
    check(len(loras) == 6, f"6 preporučenih SDXL LoRA-a ({len(loras)})")
    for c in loras:
        check(c["kind"] == "lora" and c["arch"] == "sdxl" and c["url"].startswith("https://huggingface.co/") and " " not in c["filename"]
              and c["filename"].endswith(".safetensors") and c["size_bytes"] > 1_000_000, f"LoRA {c['id']} ispravna")
        check(not BANNED.search(c["name"] + c["url"] + c["note"]), f"LoRA {c['id']} SFW")
    check(model_download.dest_dir_for("lora").name == "loras", "LoRA ide u models/loras")
    from services import generation_service, crm_service
    for t in generation_service.DEFAULT_TEMPLATES:
        blob = json.dumps(t, ensure_ascii=False)
        check(not BANNED.search(blob), f"predložak {t['key']} SFW")
    check({t["tier"] for t in generation_service.DEFAULT_TEMPLATES} == {"public_teaser", "premium"}, "predlošci: javni teaser + premium")
    sp = crm_service.build_crm_system_prompt({"name": "Luna", "persona_style": "", "age_vibe": "26"}, None, {"level": "high", "label": "Visok"})
    check(not BANNED.search(sp), "CRM sistemski prompt SFW")
    check("adult" in crm_service.ORDER_PROMPT_PREFIX or "portrait" in crm_service.ORDER_PROMPT_PREFIX, "prompt narudžbe je portret")
    idx = (ROOT / "index.html").read_text(encoding="utf-8")
    check('id="persona"' not in idx, 'index.html nema id="persona"')
    for tab in ("pregled", "slike", "influenceri", "video", "kalendar", "poruke", "modeli", "postavke"):
        check(f'data-tab="{tab}"' in idx and f'id="tab-{tab}"' in idx, f"kartica {tab}")
    check("Nacrt za odobrenje" in idx and "Automatsko slanje odmah" in idx, "nazivi načina slanja")
    check('loading="lazy"' in idx and "/static/v11.js" in idx, "lazy slike + v11.js uključen")
    import check_ui_js
    try:
        errs = check_ui_js.check()
        check(not errs, "check_ui_js (inline + static/*.js): " + ("OK" if not errs else errs[0][:200]))
    except RuntimeError as exc:
        print("  SKIP", exc)


# ---------------------------------------------------------------- hardver

def test_hardware():
    print("== hardver: detekcija, preporuka, zastavice, okruženje ==")
    from services import hardware_service as hw
    cim = json.dumps([{"Name": "AMD Radeon RX 6600", "AdapterRAM": 4293918720, "DriverVersion": "31.0.24027.1012"},
                      {"Name": "Microsoft Basic Display Adapter", "AdapterRAM": 0}])
    g = hw.parse_cim_json(cim)
    check(len(g) == 2 and g[0]["name"] == "AMD Radeon RX 6600", "PowerShell CIM JSON")
    check(hw.parse_cim_json(json.dumps({"Name": "AMD Radeon RX 6600", "AdapterRAM": 1}))[0]["source"] == "cim", "CIM s jednim objektom")
    w = hw.parse_wmic("Node,AdapterRAM,DriverVersion,Name\nPC,4293918720,31.0.1,AMD Radeon RX 6600\n")
    check(len(w) == 1 and w[0]["name"] == "AMD Radeon RX 6600", "wmic CSV")
    stats = {"devices": [{"name": "cuda:0 AMD Radeon RX 6600 [ZLUDA] : native", "type": "cuda", "vram_total": 8573157376, "vram_free": 7000000000}]}
    check(hw.parse_system_stats(stats)[0]["vram_bytes"] == 8573157376, "ComfyUI /system_stats")
    calls = []
    def runner(cmd):
        calls.append(cmd[0])
        return "" if cmd[0] == "powershell" else "Node,AdapterRAM,DriverVersion,Name\nPC,4293918720,31.0.1,AMD Radeon RX 6600\n"
    old_mock = os.environ.pop("STUDIO_MOCK_GPU", None)
    try:
        gpus = hw.detect_gpus(system_stats=stats, runner=runner)
    finally:
        if old_mock is not None:
            os.environ["STUDIO_MOCK_GPU"] = old_mock
    check(calls[:2] == ["powershell", "wmic"], f"redoslijed: CIM pa wmic ({calls})")
    check(gpus and gpus[0]["vram_bytes"] >= 8_000_000_000, "VRAM iz ComfyUI-ja ispravlja 4 GB iz WMI-ja")
    prof = hw.classify({"name": "AMD Radeon RX 6600", "vram_bytes": 4293918720})
    check(prof["is_rx6600"] and prof["gfx"] == "gfx1032" and prof["vram_gb"] == 8.0, f"RX 6600 klasifikacija {prof}")
    rec = hw.recommend(prof)
    check(rec["hw_backend"] == "zluda" and rec["hw_vae_mode"] == "tiled" and rec["hw_vae_tile"] == "512" and rec["hw_safe_mode"] == "1", "preporuka za RX 6600")
    base = dict(hw.DEFAULTS)
    f = lambda **kw: hw.launch_flags({**base, **kw}, check_supported=False)
    check("--lowvram" in f(hw_vram_mode="lowvram"), "--lowvram")
    check("--normalvram" in f(hw_vram_mode="normalvram"), "--normalvram")
    check(not any(x in f(hw_vram_mode="medvram") for x in ("--medvram", "--lowvram", "--normalvram")), "medvram = bez zastavice (ComfyUI je nema)")
    check("--reserve-vram 1.0" in f(hw_reserve_vram="1.0"), "--reserve-vram 1.0 kao jedan token")
    check("--cpu-vae" in f(hw_vae_mode="cpu"), "VAE na CPU-u: --cpu-vae")
    check("--directml" in f(hw_backend="directml") and "--cpu" in f(hw_backend="cpu"), "directml / cpu backend")
    check("--lowvram" not in hw.launch_flags({**base, "hw_vram_mode": "lowvram"}, source_text="main.py --lowvram", check_supported=False), "ne duplira VRAM zastavicu iz bat-a")
    filt = hw.launch_flags({**base, "hw_extra_args": "--fake-flag 3 --use-split-cross-attention"}, supported={"--reserve-vram", "--use-split-cross-attention"})
    check("--fake-flag 3" not in filt and "--use-split-cross-attention" in filt, f"nepoznate zastavice se filtriraju ({filt})")
    env = hw.process_env({}, {**base, "hw_backend": "zluda", "hw_env_overrides": "TORCH_BACKENDS_CUDNN_ENABLED=1\nFOO=bar"}, disable_cudnn=True)
    check(env.get("TORCH_BACKENDS_CUDNN_ENABLED") == "0" and env.get("FOO") == "bar", "ZLUDA: TORCH_BACKENDS_CUDNN_ENABLED=0 ostaje i nakon override-a")
    env = hw.process_env({}, {**base, "hw_backend": "rocm"}, disable_cudnn=True)
    check(env.get("HSA_OVERRIDE_GFX_VERSION") == "10.3.0", "ROCm: HSA_OVERRIDE_GFX_VERSION=10.3.0")
    check(hw.process_env({}, {**base, "hw_backend": "cpu"}, disable_cudnn=True).get("CUDA_VISIBLE_DEVICES") == "", "CPU: CUDA_VISIBLE_DEVICES prazan")
    bw, bh = hw.safe_base_for("sdxl", 1080, 1350)
    check(bw * bh < 896 * 1120 and abs(bw / bh - 0.8) < 0.03, f"8 GB siguran mod: SDXL 4:5 baza {bw}×{bh}")
    bw, bh = hw.safe_base_for("sd15", 1080, 1350)
    check(max(bw, bh) <= 768, f"SD 1.5 baza ≤ 768 ({bw}×{bh})")
    plan = hw.launch_plan("", {**base, "hw_backend": "zluda", "hw_vram_mode": "lowvram"})
    check(plan["low_vram"] is True and "--lowvram" not in plan["extra_flags"] and plan["env_keys"].get("TORCH_BACKENDS_CUDNN_ENABLED") == "0", "launch_plan")
    import launcher
    src = (ROOT / "launcher.py").read_text(encoding="utf-8")
    check("hardware_service" in src and "process_env" in src and "launch_plan" in src, "launcher koristi hardware_service (zastavice + okruženje)")
    check(hasattr(launcher, "start_comfy_if_needed"), "launcher.start_comfy_if_needed postoji")


# ---------------------------------------------------------------- generiranje

OBJ_INFO = {
    "KSampler": {}, "CheckpointLoaderSimple": {}, "CLIPTextEncode": {}, "EmptyLatentImage": {}, "VAEDecode": {}, "SaveImage": {},
    "LoraLoader": {}, "LatentUpscaleBy": {}, "ImageScale": {}, "FreeU_V2": {},
    "VAEDecodeTiled": {"input": {"required": {"samples": [], "vae": [], "tile_size": ["INT", {}], "overlap": ["INT", {}]}}},
    "InstantIDModelLoader": {"input": {"required": {"instantid_file": [["ip-adapter.bin"]]}}},
    "InstantIDFaceAnalysis": {"input": {"required": {"provider": [["CPU", "CUDA", "ROCM"]]}}},
    "ApplyInstantID": {}, "ControlNetLoader": {"input": {"required": {"control_net_name": [["instantid/diffusion_pytorch_model.safetensors"]]}}},
    "LoadImage": {},
}


def setup_db(tmp: Path):
    import inbox
    os.environ["STUDIO_DATA_DIR"] = str(tmp)
    inbox.configure_paths(data_dir=tmp)
    inbox.init_db()
    return inbox


def test_workflow():
    print("== workflow: sampler, FreeU_V2, tiled VAE, hires, LoRA stack, InstantID ==")
    import image_gen
    check(image_gen.default_sampler("sdxl") == ("dpmpp_2m_sde", "karras"), "zadani sampler dpmpp_2m_sde + karras")
    common = dict(prompt="adult woman, cafe", negative="child, teen", model="RealVisXL_V5.0_fp16.safetensors", width=768, height=960,
                  batch=1, seed=1, steps=30, arch="sdxl", sampler_name="dpmpp_2m_sde", scheduler="karras")
    old_avail = image_gen.lora_available
    image_gen.lora_available = lambda name, folder=None: True
    try:
        wf = image_gen.build_workflow(**common, object_info=OBJ_INFO, freeu=True, vae_mode="tiled", vae_tile_size=512, hires=True,
                                      hires_scale=1.45, hires_denoise=0.38, hires_steps=14,
                                      loras=[{"name": "a.safetensors", "strength_model": 0.6}, {"name": "b.safetensors", "strength_model": 0.4}, {"name": "c.safetensors", "strength_model": 0.3}])
    finally:
        image_gen.lora_available = old_avail
    classes = [n["class_type"] for n in wf.values()]
    check(wf.get("30", {}).get("class_type") == "FreeU_V2" and wf["30"]["inputs"]["b1"] == 1.3 and wf["30"]["inputs"]["b2"] == 1.4
          and wf["30"]["inputs"]["s1"] == 0.9 and wf["30"]["inputs"]["s2"] == 0.2, "FreeU_V2 b1=1.3 b2=1.4 s1=0.9 s2=0.2")
    tiled = [n for n in wf.values() if n["class_type"] == "VAEDecodeTiled"]
    check(tiled and all(n["inputs"]["tile_size"] == 512 for n in tiled), "VAEDecodeTiled tile 512")
    check(classes.count("LoraLoader") == 3, f"LoRA stack: 3 LoraLoader čvora ({classes.count('LoraLoader')})")
    ks = [n for n in wf.values() if n["class_type"] == "KSampler"]
    check(any(n["inputs"]["sampler_name"] == "dpmpp_2m_sde" for n in ks), "KSampler dpmpp_2m_sde")
    second = [n for n in ks if abs(float(n["inputs"].get("denoise", 1)) - 0.38) < 1e-6]
    check(second and second[0]["inputs"]["steps"] == 14, "hires drugi prolaz: denoise 0.38, 14 koraka")
    up = [n for n in wf.values() if n["class_type"] == "LatentUpscaleBy"]
    check(up and abs(up[0]["inputs"]["scale_by"] - 1.45) < 1e-6, "hires skala 1.45")
    no_fu = image_gen.build_workflow(**common, object_info={k: v for k, v in OBJ_INFO.items() if k != "FreeU_V2"}, freeu=True)
    check("FreeU_V2" not in [n["class_type"] for n in no_fu.values()], "FreeU_V2 preskočen kad ga /object_info nema")
    plain = image_gen.build_workflow(**common, object_info=OBJ_INFO)
    check("FreeU_V2" not in [n["class_type"] for n in plain.values()] and "VAEDecode" in [n["class_type"] for n in plain.values()], "bez opcija: stari graf (VAEDecode)")
    check(image_gen.instantid_available(OBJ_INFO) and not image_gen.instantid_available({}), "instantid_available")
    wf_i = image_gen.build_workflow(**common, object_info=OBJ_INFO, instantid_image="ref.png", instantid_weight=0.7)
    check(wf_i.get("40", {}).get("class_type") == "InstantIDModelLoader" and wf_i.get("41", {}).get("inputs", {}).get("provider") == "CPU",
          "InstantID čvorovi (FaceAnalysis na CPU-u za AMD)")
    check(any(n["class_type"] == "ApplyInstantID" and abs(n["inputs"].get("weight", 0) - 0.7) < 1e-6 for n in wf_i.values()), "ApplyInstantID jačina 0.7")
    check(len(image_gen.normalize_lora_stack([{"name": f"l{i}.safetensors"} for i in range(9)])) <= 5, "LoRA stack najviše 5")


def test_generation_service(tmp: Path):
    print("== generation_service: predlošci, plan, red čekanja, galerija, dataset, character sheet ==")
    inbox = setup_db(tmp)
    import studio
    import image_gen
    from services import generation_service as gs
    tpls = gs.list_templates()
    check(len(tpls) >= 7 and {t["tier"] for t in tpls} == {"public_teaser", "premium"}, f"ugrađeni predlošci ({len(tpls)})")
    t = gs.create_template({"name": "Moj test", "tier": "premium", "prompt_prefix": "studio portrait", "size_preset": "ig_portrait"})
    d = gs.duplicate_template(t["id"])
    check(d["name"].endswith("(kopija)") and d["tier"] == "premium", "dupliciranje predloška")
    u = gs.update_template(d["id"], {"name": "Moj test 2", "steps": 28})
    check(u["name"] == "Moj test 2" and int(u["steps"]) == 28, "uređivanje predloška")
    gs.delete_template(d["id"])
    check(gs.get_template(d["id"]) is None, "brisanje predloška")
    prof = inbox.upsert_profile({"name": "Test Ana", "appearance_prompt": "long dark hair, brown eyes", "age_vibe": "27", "model_type": "sdxl",
                                 "lora_stack": [{"name": "detail.safetensors", "strength_model": 0.5}], "ref_mode": "ipadapter", "send_mode": "auto"})
    check(prof["lora_stack"] and prof["lora_stack"][0]["name"] == "detail.safetensors" and prof["ref_mode"] == "ipadapter" and prof["send_mode"] == "auto",
          "profil: LoRA stack, ref_mode, send_mode")
    old_avail = image_gen.lora_available
    image_gen.lora_available = lambda name, folder=None: True
    try:
        body = {"prompt": "wearing a red bikini on the beach, golden hour", "persona_id": prof["id"], "model": "RealVisXL_V5.0_fp16.safetensors",
                "model_type": "sdxl", "freeu": True, "vae_mode": "tiled", "safe_mode": True, "size_preset": "ig_portrait", "template_id": t["id"],
                "sampler": "dpmpp_2m_sde", "scheduler": "exponential"}
        res = studio.plan_image_generation(body, profile=inbox.get_profile(prof["id"]), object_info=OBJ_INFO)
    except Exception:
        image_gen.lora_available = old_avail
        raise
    check(res.get("ok"), f"plan ok ({res.get('error')})")
    meta = res.get("meta") or {}
    pos = json.dumps(res.get("workflow") or {})
    check("adult woman" in meta.get("prompt", "") and "27" in meta.get("prompt", ""), "osiguranje: 'adult woman, <dob>' u promptu")
    neg = meta.get("negative") or json.dumps([n["inputs"].get("text") for n in res["workflow"].values() if n["class_type"] == "CLIPTextEncode"])
    check("child" in neg and "teen" in neg, "osiguranje: child/teen u negativnom promptu")
    check("red bikini on the beach" in pos, "korisnički prompt nije cenzuriran ključnim riječima")
    check("studio portrait" in pos, "predložak dodan u prompt")
    check(meta.get("scheduler") == "exponential" and meta.get("freeu") is True and meta.get("vae_mode") == "tiled", "meta: scheduler/freeu/vae")
    check(meta.get("safe_mode") is True and res["workflow"]["5"]["inputs"]["width"] < 896, "8 GB siguran mod smanjuje baznu rezoluciju")
    check([x["name"] for x in meta.get("loras") or []] == ["detail.safetensors"], "LoRA stack s profila osobe")
    # red čekanja s lažnim ComfyUI-jem
    calls = {"prompt": 0}
    def fake_req(path, data=None, timeout=15, method=None):
        if path == "/prompt":
            calls["prompt"] += 1
            return {"prompt_id": f"p{calls['prompt']}"}, {}, 200
        if path.startswith("/view"):
            return tiny_png(), {}, 200
        return {}, {}, 200
    def fake_status(pid):
        return {"status": "done", "images": [{"filename": f"{pid}.png", "subfolder": "", "type": "output"}]}
    gs.configure(planner=lambda b: studio.plan_image_generation(b, profile=inbox.get_profile(b.get("persona_id")) if b.get("persona_id") else None, object_info=OBJ_INFO),
                 comfy_request=fake_req, job_status=fake_status, comfy_up=lambda: (True, "ok"), remember_job=lambda pid: None)
    jobs = gs.enqueue_batch({"prompt": "reading a book in a cafe", "persona_id": prof["id"], "seed": 100, "model": "RealVisXL_V5.0_fp16.safetensors", "model_type": "sdxl"},
                            count=3, seed_mode="sequential")
    seeds = [j["body"]["seed"] for j in jobs] if "body" in jobs[0] else [gs.get_job(j["id"])["body"]["seed"] for j in jobs]
    check(seeds == [100, 101, 102], f"serija: uzastopni seedovi {seeds}")
    multi = gs.enqueue_batch({"prompt": "x", "seed": 5}, count=2, template_ids=[tpls[0]["id"], tpls[1]["id"]])
    check(len(multi) == 4, "više predložaka × N")
    gs.cancel_job(multi[-1]["id"])
    check(gs.get_job(multi[-1]["id"])["status"] == "cancelled", "otkazivanje posla")
    gs.retry_job(multi[-1]["id"])
    check(gs.get_job(multi[-1]["id"])["status"] == "queued", "ponovni pokušaj")
    done = 0
    while True:
        j = gs.process_next(sleep=lambda s: None)
        if j is None:
            break
        done += j["status"] == "done"
    q = gs.list_queue()
    check(done == 7 and q["counts"]["done"] == 7, f"radnik obradio sve poslove ({done})")
    check(set(gs.STATUS_LABELS.values()) >= {"U tijeku", "Na čekanju", "Gotovo", "Greška", "Otkazano"}, "statusi na hrvatskom")
    check(gs.clear_finished() >= 7 and not gs.list_queue()["jobs"], "očisti gotove")
    gal = gs.list_gallery(limit=2)
    check(gal["total"] >= 7 and gal["has_more"] and len(gal["items"]) == 2, "galerija: paginacija (Učitaj još)")
    pers = gs.list_gallery(persona_id=prof["id"], limit=50)["items"]
    check(len(pers) == 3, f"galerija po osobi ({len(pers)})")
    for it in pers[:2]:
        gs.rate_image(gallery_id=it["id"], rating=1)
    gs.rate_image(gallery_id=pers[2]["id"], rating=-1)
    check(len(gs.list_gallery(rating=1, limit=50)["items"]) == 2 and len(gs.list_gallery(rating=-1, limit=50)["items"]) == 1, "ocjene Dobra / Loša")
    exp = gs.export_lora_dataset(prof["id"], trigger="testana", repeats=8)
    folder = Path(exp["folder"])
    caps = list(folder.rglob("*.txt"))
    cap_txt = [c.read_text(encoding="utf-8") for c in caps if c.name != "UPUTE.txt"]
    check(exp["images"] == 2 and folder.parent.name == "lora_datasets", f"dataset: samo 2 dobre slike u data/lora_datasets ({exp['images']})")
    check(cap_txt and all(c.startswith("testana, adult woman") for c in cap_txt), "captioni: trigger + adult woman")
    kohya = json.loads((folder / "kohya_sdxl_lora_8gb.json").read_text(encoding="utf-8"))
    check(kohya.get("gradient_checkpointing") and str(kohya.get("mixed_precision")) in {"fp16", "bf16"}, "Kohya 8 GB config")
    check((folder / "onetrainer_sdxl_lora_8gb.json").is_file() and any(p.name.startswith("8_testana") for p in (folder / "img").iterdir()), "OneTrainer config + img/8_testana")
    sheet = gs.queue_character_sheet(prof["id"])
    check(len(sheet["jobs"]) == 4, "character sheet: 4 kadra u redu")
    while gs.process_next(sleep=lambda s: None):
        pass
    sheets = gs.list_gallery(source="character_sheet")["items"]
    check(len(sheets) == 1, "character sheet spojen i spremljen u galeriju")
    if sheets:
        data = gs.read_item_bytes(sheets[0])
        w, h = png_size(data)
        check(data[:8] == b"\x89PNG\r\n\x1a\n" and w > 0 and h > 0, f"character sheet PNG {w}×{h}")
    image_gen.lora_available = old_avail
    pure = gs.stitch_contact_sheet([("a", tiny_png()), ("b", tiny_png()), ("c", None), ("d", tiny_png())], cell=64, use_pil=False)
    pw, ph = png_size(pure)
    check(pure[:4] == b"\x89PNG" and pw >= 128 and ph >= 128, f"čisti Python 2×2 fallback ({pw}×{ph})")
    return prof


# ---------------------------------------------------------------- objave

class FakeHttp:
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, params=None, json_body=None, form=None, files=None, headers=None, timeout=30):
        self.calls.append({"method": method, "url": url, "form": form, "files": files, "json": json_body, "headers": headers or {}})
        if url.endswith("/media"):
            return {"status": 200, "json": {"id": "container-1"}, "text": ""}
        if url.endswith("/media_publish"):
            return {"status": 200, "json": {"id": "media-1"}, "text": ""}
        if "/photos" in url or "/feed" in url:
            return {"status": 200, "json": {"id": "fb-1", "post_id": "fb-1"}, "text": ""}
        if "api.telegram.org" in url:
            return {"status": 200, "json": {"ok": True, "result": {"message_id": 7}}, "text": ""}
        if "premium.example" in url:
            return {"status": 201, "json": {"ok": True, "id": "prem-1"}, "text": ""}
        if "11434" in url or "1234" in url or "x.ai" in url:
            raise OSError("LLM nije pokrenut")
        return {"status": 200, "json": {}, "text": ""}


def test_posting(tmp: Path):
    print("== objave: Instagram, Facebook, Telegram, Premium API, raspored ==")
    from services import posting_service as ps, common
    env_path = tmp / ".env"
    env_path.write_text("# test\nOTHER=1\n", encoding="utf-8")
    common.write_env_values({"META_ACCESS_TOKEN": "tok-secret-123456", "META_IG_USER_ID": "1784", "META_FB_PAGE_ID": "555",
                             "PUBLIC_MEDIA_BASE_URL": "https://studio.example.net", "TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "@kanal",
                             "PREMIUM_API_URL": "https://premium.example/api/posts", "PREMIUM_API_KEY": "pk-xyz"}, env_path)
    txt = env_path.read_text(encoding="utf-8")
    check("OTHER=1" in txt and "META_ACCESS_TOKEN=tok-secret-123456" in txt, "write_env_values: data/.env ažuriran, ostalo sačuvano")
    check(common.mask("tok-secret-123456") != "tok-secret-123456" and "123456" not in common.mask("tok-secret-123456")[:-4], "maskiranje ključeva")
    fake = FakeHttp()
    ps.set_http(fake)
    try:
        post = ps.create_post({"caption": "Jutarnja kava ☕", "hashtags": "#coffee", "channels": ["instagram", "facebook", "telegram", "premium_api"],
                               "post_type": "public_teaser", "status": "draft"})
        post = ps.attach_upload(post["id"], tiny_png(), "png")
        raw = ps._raw_post(post["id"])
        url = ps.public_media_url(raw)
        check(url.startswith("https://studio.example.net/public/media/%d/" % post["id"]), "javni URL slike za Instagram")
        got = ps.media_for_public(post["id"], url.rsplit("/", 1)[-1])
        check(got and got[0][:4] == b"\x89PNG", "/public/media vraća sliku s ispravnim tokenom")
        check(ps.media_for_public(post["id"], "krivi-token") is None, "kriv token = 404")
        ig = ps.instagram_payloads(raw)
        check(ig["container"]["url"].endswith("/1784/media") and ig["container"]["form"]["image_url"] == url and ig["publish"]["url"].endswith("/media_publish"),
              "Instagram: container pa media_publish")
        fb = ps.facebook_payload(raw, tiny_png())
        check(fb["url"].endswith("/555/photos") and fb["files"], "Facebook: /photos multipart")
        check(ps.facebook_payload({"caption": "x"}, None)["url"].endswith("/555/feed"), "Facebook: /feed bez slike")
        tg = ps.telegram_payload("@kanal", "cap", tiny_png())
        check(tg["url"].endswith("/sendPhoto") and "photo" in tg["files"], "Telegram: sendPhoto multipart")
        check(ps.telegram_payload("@kanal", "cap", None)["url"].endswith("/sendMessage"), "Telegram: sendMessage bez slike")
        pj = ps.premium_payload(raw, tiny_png())
        check(pj["json"] and pj["json"].get("media_base64") and pj["headers"].get("Authorization") == "Bearer pk-xyz", "Premium API: JSON + base64 + auth")
        os.environ["PREMIUM_SEND_MODE"] = "multipart"
        check(ps.premium_payload(raw, tiny_png())["files"], "Premium API: multipart način")
        os.environ.pop("PREMIUM_SEND_MODE", None)
        res = ps.publish_post(post["id"])
        check(res["status"] == "published" and all(r.get("ok") for r in res["results"].values()), f"Objavi odmah: svi kanali ({res['status']})")
        check(not any("tok-secret-123456" in json.dumps(c.get("headers")) for c in fake.calls), "token nije u headerima zapisa")
        future = ps.create_post({"caption": "Zakazano", "channels": ["telegram"], "status": "scheduled", "scheduled_at": time.time() + 3600})
        past = ps.create_post({"caption": "Dospjelo", "channels": ["telegram"], "status": "scheduled", "scheduled_at": time.time() - 60})
        done = ps.run_due()
        ids = [d["id"] for d in done]
        check(past["id"] in ids and future["id"] not in ids, "raspored: objavljuje samo dospjele")
        check(ps.get_post(past["id"])["status"] == "published", "status Objavljeno")
        bad = ps.create_post({"caption": "IG bez slike", "channels": ["instagram"], "status": "draft"})
        res = ps.publish_post(bad["id"])
        check(res["status"] == "error" and "treba sliku" in (res.get("error") or ""), "Instagram bez slike: jasna greška")
        lst = ps.list_posts(month=time.strftime("%Y-%m"))
        check(lst["labels"]["draft"] == "Nacrt" and lst["labels"]["scheduled"] == "Zakazano" and lst["labels"]["published"] == "Objavljeno" and lst["labels"]["error"] == "Greška",
              "oznake Nacrt / Zakazano / Objavljeno / Greška")
    finally:
        ps.set_http(None)


# ---------------------------------------------------------------- CRM

def test_crm(tmp: Path, prof: dict):
    print("== CRM: interes, memorija, način slanja, LLM fallback, narudžbe, webhook, analitika ==")
    import inbox
    from services import crm_service as crm, generation_service as gs, posting_service as ps
    fake = FakeHttp()
    crm.set_http(fake)
    ps.set_http(fake)
    try:
        for k in ("XAI_API_KEY", "OLLAMA_BASE_URL", "OPENAI_COMPAT_BASE_URL"):
            os.environ.pop(k, None)
        check(crm.detect_interest("bok, kako si?")["level"] == "low", "interes: nizak")
        check(crm.detect_interest("Koliko košta pretplata na premium?")["level"] in {"high", "subscriber"}, "interes: pretplata")
        check(crm.detect_interest("Možeš li mi napraviti custom fotku za rođendan, platit ću")["level"] == "custom_request", "interes: custom zahtjev")
        check(crm.resolve_backend() == "rules", "bez LLM-a: pravila")
        # način slanja: globalno < kanal < influencer
        inbox.set_setting("send_mode", "approve")
        other = inbox.upsert_profile({"name": "Druga Osoba", "appearance_prompt": "short blonde hair", "age_vibe": "30"})
        check(crm.effective_send_mode(other["id"], "telegram")[0] == "approve", "zadano: nacrt za odobrenje")
        crm.set_send_mode("global", "auto")
        check(crm.effective_send_mode(other["id"], "telegram")[0] == "auto", "globalno: automatsko slanje jednim klikom")
        crm.set_send_mode("channel", "approve", platform="telegram")
        check(crm.effective_send_mode(other["id"], "telegram")[0] == "approve", "kanal nadjačava globalno")
        check(crm.effective_send_mode(prof["id"], "telegram") == ("auto", "influencer"), "influencer nadjačava kanal")
        crm.set_send_mode("channel", "inherit", platform="telegram")
        crm.set_send_mode("global", "approve")
        check(inbox.effective_send_mode(other["id"], "simulate")[0] == "approve", "inbox.effective_send_mode")
        r = inbox.handle_incoming(other["id"], "simulate", "sim-marko", "Bok, ja sam Marko iz Splita. Koliko košta custom portret za rođendan?", display_name="Marko")
        check(r.get("draft_id") and not r.get("auto_sent") and r.get("send_mode") == "approve", "simulacija: nacrt bez xAI ključa (pravila)")
        check((r.get("interest") or {}).get("level") == "custom_request", "simulacija: prepoznat custom zahtjev")
        ct = crm.get_contact(r["contact_id"])
        mem = " ".join(m["content"] for m in crm.memory_for(ct["id"]))
        check("Marko" in mem and "Split" in mem, f"memorija fana: {mem}")
        reply = crm.generate_reply(other, [], "Hej, što radiš danas?", contact=ct)
        check(reply["text"] and reply["backend"] == "rules", "generate_reply fallback na pravila")
        check(not BANNED.search(reply["text"]), "odgovor po pravilima je SFW")
        # narudžba -> generiranje -> isporuka -> plaćeno
        o = crm.create_order(contact_id=ct["id"], profile_id=other["id"], description="rođendanska čestitka u kafiću", price=15)
        check(o["status"] == "pending", "narudžba: na čekanju")
        o = crm.generate_order(o["id"])
        check(o["status"] == "generating", "narudžba: generira se")
        while gs.process_next(sleep=lambda s: None):
            pass
        o = crm.get_order(o["id"])
        check(o["status"] == "ready" and o.get("gallery_id"), f"narudžba: spremno ({o['status']})")
        ojobs = [j for j in gs.list_queue()["jobs"] if j.get("order_id") == o["id"]]
        check(ojobs and crm.ORDER_PROMPT_PREFIX in json.dumps(gs.get_job(ojobs[0]["id"])["body"]), "narudžba ide kroz generation_service (SFW portret)")
        o = crm.deliver_order(o["id"], "local")
        check(o["status"] == "delivered" and Path(o["delivery"]["path"]).is_file(), "isporuka: lokalni izvoz")
        o = crm.mark_order_paid(o["id"])
        check(o["status"] == "paid", "narudžba: plaćeno")
        a = crm.analytics()
        check(a["total_revenue"] >= 15 and a["buyers"] >= 1, "kupnja zabilježena u analitici")
        crm.record_purchase(contact_id=ct["id"], profile_id=other["id"], kind="subscription", amount=9.99, channel="simulate")
        check(crm.get_contact(ct["id"])["tier"] in {"subscriber", "vip"}, "pretplata podiže razinu fana")
        os.environ["CRM_WEBHOOK_SECRET"] = "tajna"
        try:
            crm.handle_webhook({"platform": "premium", "profile_id": other["id"], "user_id": "f1", "text": "bok"}, {"X-Studio-Secret": "kriva"})
            check(False, "webhook bez ispravne tajne mora pasti")
        except PermissionError:
            check(True, "webhook: kriva tajna odbijena")
        w = crm.handle_webhook({"platform": "premium", "profile_id": other["id"], "user_id": "f1", "name": "Ana", "text": "Bok! Imaš li VIP pretplatu?"}, {"X-Studio-Secret": "tajna"})
        check(w["ok"] and w.get("thread_id"), "webhook: poruka u inboxu")
        w = crm.handle_webhook({"event": "tip", "platform": "premium", "profile_id": other["id"], "user_id": "f1", "amount": 5}, {"x-webhook-secret": "tajna"})
        check(w["ok"] and w["purchase"]["kind"] == "tip", "webhook: napojnica zabilježena")
        os.environ.pop("CRM_WEBHOOK_SECRET", None)
        a = crm.analytics()
        check(a["total_contacts"] >= 2 and a["active_subscribers"] >= 1 and a["by_channel"], "analitika: kontakti, pretplatnici, kanali")
        tg = crm.get_or_create_contact(other["id"], "telegram", "999", display_name="Tg fan")
        o2 = crm.create_order(contact_id=tg["id"], profile_id=other["id"], description="shoutout portret", price=10)
        crm.generate_order(o2["id"])
        while gs.process_next(sleep=lambda s: None):
            pass
        o2 = crm.deliver_order(o2["id"], "auto")
        check(o2["status"] == "delivered" and o2["channel"] == "telegram" and any("sendPhoto" in c["url"] for c in fake.calls), "isporuka: Telegram sendPhoto")
    finally:
        crm.set_http(None)
        ps.set_http(None)


# ---------------------------------------------------------------- HTTP API + UI

def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def http(method: str, url: str, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            ctype = r.headers.get("Content-Type") or ""
            return r.status, (json.loads(raw.decode("utf-8")) if "json" in ctype else raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw.decode("utf-8"))
        except Exception:
            return exc.code, raw


BROWSER_SCRIPT = r"""
import json, sys
from playwright.sync_api import sync_playwright
url = sys.argv[1]
exe = sys.argv[2] or None
tabs = ["pregled", "slike", "influenceri", "video", "kalendar", "poruke", "modeli", "postavke"]
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
    pg.wait_for_timeout(2500)
    out = {"tabs": {}}
    for t in tabs:
        pg.click('.tabs button[data-tab="%s"]' % t)
        pg.wait_for_timeout(900)
        out["tabs"][t] = pg.evaluate('(t) => { const el = document.getElementById("tab-" + t); return !!el && el.classList.contains("on") && el.offsetHeight > 0 && el.innerText.length > 20; }', t)
    pg.click('.tabs button[data-tab="poruke"]')
    pg.wait_for_timeout(800)
    pg.click('#v11BigToggle button[data-mode="auto"]')
    pg.wait_for_timeout(800)
    out["auto_on"] = pg.evaluate('() => !!document.querySelector("#v11BigToggle button.auto.on") && document.querySelector("#sendMode button.on").dataset.mode === "auto"')
    pg.click('#v11BigToggle button[data-mode="approve"]')
    pg.wait_for_timeout(800)
    out["approve_on"] = pg.evaluate('() => !!document.querySelector("#v11BigToggle button.approve.on")')
    pg.click('.tabs button[data-tab="slike"]')
    pg.wait_for_timeout(500)
    pg.evaluate('() => { document.getElementById("v11GenBox").open = true; }')
    pg.wait_for_timeout(300)
    out["gen_ui"] = pg.evaluate('() => !!document.getElementById("v11Sampler") && document.getElementById("v11Sampler").value')
    out["extras"] = pg.evaluate('() => window.StudioV11.genExtras()')
    out["hw_quick"] = pg.evaluate('() => document.getElementById("v11HwQuick").innerText')
    out["curated_group"] = pg.evaluate('() => document.getElementById("curatedModels").innerText.indexOf("Preporučene SDXL LoRA-e") >= 0')
    out["errors"] = errs
    out["console"] = cons
    b.close()
print(json.dumps(out, ensure_ascii=False))
"""


def test_server(tmp: Path):
    print("== HTTP API (studio.py) ==")
    data_dir = tmp / "srv"
    data_dir.mkdir()
    port = free_port()
    env = dict(os.environ, STUDIO_DATA_DIR=str(data_dir), STUDIO_PORT=str(port), STUDIO_NO_BROWSER="1",
               COMFYUI_URL="http://127.0.0.1:9", STUDIO_MOCK_GPU="AMD Radeon RX 6600|8")
    for k in ("XAI_API_KEY", "CRM_WEBHOOK_SECRET", "OLLAMA_BASE_URL"):
        env.pop(k, None)
    proc = subprocess.Popen([sys.executable, str(ROOT / "studio.py")], cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(150):
            try:
                http("GET", base + "/api/state")
                break
            except Exception:
                time.sleep(0.1)
        for ep in ("/api/v11/overview", "/api/hardware", "/api/gen/options", "/api/templates", "/api/queue", "/api/gallery", "/api/posts",
                   "/api/crm/contacts", "/api/crm/orders", "/api/crm/analytics", "/api/crm/send-mode", "/api/crm/llm", "/api/env",
                   "/api/inbox/threads", "/api/state", "/api/models/download"):
            code, body = http("GET", base + ep)
            check(code == 200 and isinstance(body, dict) and body.get("ok", True), f"GET {ep}")
        code, hw = http("GET", base + "/api/hardware")
        check(hw["profile"]["is_rx6600"] and hw["effective_backend"] == "zluda" and hw["disable_cudnn"], "hardver: RX 6600, ZLUDA, cuDNN isključen")
        code, rec = http("POST", base + "/api/hardware/recommend", {})
        check(rec["settings"]["hw_vae_mode"] == "tiled" and rec["launch"]["env_keys"].get("TORCH_BACKENDS_CUDNN_ENABLED") == "0", "Primijeni preporuku za RX 6600")
        code, st = http("POST", base + "/api/crm/send-mode", {"scope": "global", "mode": "auto"})
        code, s2 = http("GET", base + "/api/settings")
        check(st["global"] == "auto" and (s2.get("settings") or s2).get("send_mode") == "auto", "send-mode: auto jednim pozivom (i u postavkama)")
        http("POST", base + "/api/crm/send-mode", {"scope": "global", "mode": "approve"})
        code, sim = http("POST", base + "/api/inbox/simulate", {"text": "Bok, koliko košta pretplata?", "fan_name": "Ivo"})
        check(code == 200 and sim.get("draft_id"), "stari /api/inbox/simulate radi bez XAI_API_KEY")
        code, sim2 = http("POST", base + "/api/crm/simulate", {"text": "Možeš li custom portret?", "fan_name": "Ana"})
        check(code == 200 and sim2.get("interest", {}).get("level") == "custom_request", "/api/crm/simulate + interes")
        code, th = http("GET", base + "/api/inbox/threads")
        check(code == 200 and len(th.get("threads") or []) >= 2, "/api/inbox/threads kompatibilan")
        code, tp = http("POST", base + "/api/templates", {"name": "API predložak", "tier": "public_teaser", "prompt_prefix": "street style"})
        tid = tp["template"]["id"]
        code, dup = http("POST", base + f"/api/templates/{tid}/duplicate")
        code, upd = http("PUT", base + f"/api/templates/{tid}", {"name": "API predložak 2"})
        code, dl = http("DELETE", base + f"/api/templates/{dup['template']['id']}")
        check(upd["template"]["name"] == "API predložak 2" and dl["ok"], "predlošci CRUD + dupliciranje preko API-ja")
        code, q = http("POST", base + "/api/queue", {"body": {"prompt": "cafe portrait", "seed": 10}, "count": 3, "seed_mode": "sequential"})
        check(code == 200 and len(q["jobs"]) == 3, "red čekanja: serija od 3")
        code, c = http("POST", base + f"/api/queue/{q['jobs'][0]['id']}/cancel")
        check(c["job"]["status"] == "cancelled", "red čekanja: otkaži")
        code, pst = http("POST", base + "/api/posts", {"caption": "Test objava", "channels": ["telegram"], "status": "scheduled",
                                                       "scheduled_at": time.strftime("%Y-%m-%dT%H:%M", time.localtime(time.time() + 86400)),
                                                       "upload_base64": "data:image/png;base64," + base64.b64encode(tiny_png()).decode()})
        check(code == 200 and pst["post"]["status"] == "scheduled" and pst["post"]["media_preview"], "kalendar: zakazana objava s učitanom slikom")
        code, media = http("GET", base + f"/api/posts/{pst['post']['id']}/media")
        check(code == 200 and isinstance(media, bytes) and media[:4] == b"\x89PNG", "slika objave se poslužuje")
        code, pub = http("POST", base + f"/api/posts/{pst['post']['id']}/publish")
        check(pub["post"]["status"] == "error" and "TELEGRAM" in (pub["post"]["error"] or "").upper(), "Objavi odmah bez ključa: jasna greška")
        code, e = http("POST", base + "/api/env", {"values": {"TELEGRAM_CHAT_ID": "@moj_kanal", "TELEGRAM_BOT_TOKEN": "111:secret-token-abc"}})
        envtxt = (data_dir / ".env").read_text(encoding="utf-8")
        tok = next(i for i in e["items"] if i["key"] == "TELEGRAM_BOT_TOKEN")
        check("TELEGRAM_BOT_TOKEN=111:secret-token-abc" in envtxt and "secret-token-abc" not in json.dumps(e), "ključevi u data/.env, API vraća samo maskirano")
        check(tok["set"] and tok["masked"] and tok["masked"] != "111:secret-token-abc", "maskirani prikaz")
        code, bad = http("POST", base + "/api/env", {"values": {"PATH": "/tmp"}})
        check(code == 400, "nedopušteni ključ odbijen")
        code, wh = http("POST", base + "/api/crm/webhook", {"platform": "premium", "user_id": "fan-77", "name": "Mia", "text": "Bok!"})
        check(code == 200 and wh.get("thread_id"), "POST /api/crm/webhook")
        code, js = http("GET", base + "/static/v11.js")
        check(code == 200 and isinstance(js, bytes) and b"StudioV11" in js, "/static/v11.js")
        code, _ = http("GET", base + "/static/..%2Fstudio.py")
        check(code == 404, "static: nema izlaska iz mape")
        code, _ = http("GET", base + "/public/media/1/krivi")
        check(code == 404, "/public/media s krivim tokenom = 404")
        code, ov = http("GET", base + "/api/v11/overview")
        check(ov["crm"]["total_contacts"] >= 3 and "queue" in ov and ov["hardware"]["cudnn_off"], "Pregled: KPI podaci")
        code, prof = http("GET", base + "/api/state")
        pid = prof["profiles"][0]["id"]
        code, ex = http("POST", base + f"/api/profiles/{pid}/extras", {"lora_stack": [{"name": "x.safetensors", "strength_model": 0.5}], "ref_mode": "instantid", "send_mode": "auto"})
        check(ex["profile"]["ref_mode"] == "instantid" and ex["profile"]["lora_stack"][0]["name"] == "x.safetensors", "profil: dodaci preko API-ja")
        http("POST", base + f"/api/profiles/{pid}/extras", {"send_mode": "", "lora_stack": []})
        test_browser(base + "/")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def test_browser(url: str):
    print("== headless UI: sve kartice bez grešaka ==")
    py = os.environ.get("PW_PYTHON") or sys.executable
    if subprocess.run([py, "-c", "import playwright"], capture_output=True).returncode != 0:
        print("  SKIP playwright nije instaliran (postavi PW_PYTHON)")
        return
    exe = os.environ.get("PW_CHROME") or shutil.which("google-chrome") or shutil.which("chromium") or ""
    r = subprocess.run([py, "-c", BROWSER_SCRIPT, url, exe], capture_output=True, text=True, timeout=240)
    if r.returncode != 0:
        check(False, "browser pokrenut: " + r.stderr[-600:])
        return
    info = json.loads(r.stdout.strip().splitlines()[-1])
    for t, ok in info["tabs"].items():
        check(ok, f"kartica {t} se prikazuje")
    check(not info["errors"], f"nema page grešaka: {info['errors'][:3]}")
    real_console = [c for c in info["console"] if "Failed to load resource" not in c]
    check(not real_console, f"nema console grešaka: {real_console[:3]}")
    check(info["auto_on"] and info["approve_on"], "glavni prekidač Nacrt / Automatsko radi jednim klikom")
    check(info["gen_ui"] == "dpmpp_2m_sde", "Generiranje: sampler dpmpp_2m_sde")
    ex = info["extras"] or {}
    # 1.3.0: zadani hires je sada brzi 1,33× (denoise 0,35, 8 koraka) za RX 6600
    check(ex.get("safe_mode") is True and ex.get("vae_mode") == "tiled" and ex.get("freeu") is True and abs(ex.get("hires_scale", 0) - 1.33) < 1e-6, f"genExtras {ex}")
    check("8 GB siguran mod" in info["hw_quick"] and "RX 6600" in info["hw_quick"], "brzi hardverski prekidači u Generiranju")
    check(info["curated_group"], "Modeli: sekcija Preporučene SDXL LoRA-e")


def main():
    print("test_v110")
    test_package_and_safety()
    test_hardware()
    test_workflow()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        prof = test_generation_service(tmp)
        test_posting(tmp)
        test_crm(tmp, prof)
        test_server(tmp)
    print()
    if FAILED:
        print(f"FAILED {FAILED}")
        return 1
    print("Svi testovi 1.1.0 su prošli.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
