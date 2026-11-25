#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.3.7: VAE picker, jačina detail LoRA-a, Skin Realism okidač,
Face Detailer + InstantID conditioning, end_at, FreeU isključen po zadanom,
LoRA stack s Generiranja uvijek stiže u workflow (pravi JSON, ne samo UI)."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory()
TMP = Path(_TMP.name)
(TMP / "data").mkdir()
os.environ["STUDIO_DATA_DIR"] = str(TMP / "data")

import image_gen  # noqa: E402
import inbox  # noqa: E402

inbox.configure_paths(data_dir=TMP / "data")
inbox.init_db()
import services  # noqa: E402

services.init_schema()
import studio  # noqa: E402
from services import generation_service as gs  # noqa: E402
import character  # noqa: E402
import model_download  # noqa: E402

_ROT = str.maketrans("abcdefghijklmnopqrstuvwxyz", "nopqrstuvwxyzabcdefghijklm")
BANNED = re.compile(r"\b(" + "|".join(w.translate(_ROT) for w in ("yhfgvsl", "fabsf", "afsj", "ahqr", "anxrq", "gbcyrff")) + r")\b", re.I)

FAILED = 0

# Potpisi custom čvorova (provjereno na GitHubu, cubiq InstantID / IPAdapter plus, ltdrdata Impact Pack).
APPLY_INSTANTID_REQUIRED = {
    "instantid", "insightface", "control_net", "image", "model", "positive", "negative", "weight", "start_at", "end_at",
}
IPADAPTER_REQUIRED = {"model", "ipadapter", "image", "weight", "start_at", "end_at", "weight_type"}
IPADAPTER_EMBEDS_REQUIRED = {"model", "ipadapter", "pos_embed", "weight", "weight_type", "start_at", "end_at", "embeds_scaling"}
FACE_DETAILER_REQUIRED = {
    "image", "model", "clip", "vae", "guide_size", "guide_size_for", "max_size", "seed", "steps", "cfg",
    "sampler_name", "scheduler", "positive", "negative", "denoise", "feather", "noise_mask", "force_inpaint",
    "bbox_threshold", "bbox_dilation", "bbox_crop_factor", "sam_detection_hint", "sam_dilation", "sam_threshold",
    "sam_bbox_expansion", "sam_mask_hint_threshold", "sam_mask_hint_use_negative", "drop_size", "bbox_detector",
    "wildcard", "cycle",
}


def check(cond, msg):
    global FAILED
    if cond:
        print("  OK ", msg)
    else:
        FAILED += 1
        print("  FAIL", msg)


def nodes(wf: dict, cls: str) -> list[tuple[str, dict]]:
    return [(k, n) for k, n in wf.items() if isinstance(n, dict) and n.get("class_type") == cls]


def node_map(wf: dict) -> dict[str, dict]:
    return {k: n for k, n in wf.items() if isinstance(n, dict)}


def inputs_of(wf: dict, cls: str) -> list[dict]:
    return [n["inputs"] for _, n in nodes(wf, cls)]


def common_wf(**extra):
    kw = dict(
        prompt="standing on a balcony, drinking coffee",
        negative=image_gen.DEFAULT_NEGATIVE,
        model="RealVisXL_V5.0_fp16.safetensors",
        width=768,
        height=960,
        batch=1,
        seed=7,
        steps=24,
        cfg=4.3,
        sampler_name="dpmpp_2m_sde",
        scheduler="karras",
        arch="sdxl",
        object_info=None,
    )
    kw.update(extra)
    return image_gen.build_workflow(**kw)


def plan(body, profile=None, object_info=None):
    orig = image_gen.lora_available
    orig_vae = image_gen.vae_available
    image_gen.lora_available = lambda name, folder=None: True
    image_gen.vae_available = lambda name, folder=None: True
    try:
        return studio.plan_image_generation(body, profile=profile or {}, object_info=object_info if object_info is not None else {})
    finally:
        image_gen.lora_available = orig
        image_gen.vae_available = orig_vae


def test_vae_picker():
    print("== VAE picker i ožičenje ==")
    wf = common_wf(vae="")
    check(not nodes(wf, "VAELoader"), "Iz checkpointa: nema VAELoader")
    dec = inputs_of(wf, "VAEDecode")
    check(dec and dec[0].get("vae") == ["4", 2], "Iz checkpointa: VAEDecode čita checkpoint [4,2]")

    wf = common_wf(vae="sdxl_vae.safetensors")
    loaders = nodes(wf, "VAELoader")
    check(len(loaders) == 1, "odabrani VAE: jedan VAELoader")
    nid, node = loaders[0]
    check(node["inputs"].get("vae_name") == "sdxl_vae.safetensors", "VAELoader.vae_name = sdxl_vae.safetensors")
    vae_ref = [nid, 0]
    decoders = nodes(wf, "VAEDecode") + nodes(wf, "VAEDecodeTiled")
    check(decoders and all(n["inputs"].get("vae") == vae_ref for _, n in decoders), "svi VAEDecode/Tiled idu na VAELoader")

    wf = common_wf(vae="sdxl-vae-fp16-fix.safetensors", vae_mode="tiled", hires=True, face_detailer=True)
    loaders = nodes(wf, "VAELoader")
    check(loaders and loaders[0][1]["inputs"]["vae_name"] == "sdxl-vae-fp16-fix.safetensors", "fp16-fix VAELoader")
    vae_ref = [loaders[0][0], 0]
    for cls in ("VAEDecode", "VAEDecodeTiled", "FaceDetailer"):
        for _, n in nodes(wf, cls):
            check(n["inputs"].get("vae") == vae_ref, f"{cls} vae = VAELoader")

    # SD 1.5 VAE se ne smije priključiti na SDXL
    wf = common_wf(vae="vae-ft-mse-840000-ema-pruned.safetensors", arch="sdxl")
    check(not nodes(wf, "VAELoader"), "SD 1.5 VAE nije ponuđen/priključen na SDXL")
    check(inputs_of(wf, "VAEDecode")[0]["vae"] == ["4", 2], "SDXL pada natrag na checkpoint VAE")

    wf = common_wf(vae="vae-ft-mse-840000-ema-pruned.safetensors", arch="sd15", model="Realistic_Vision_V5.1_fp16-no-ema.safetensors", width=512, height=768)
    loaders = nodes(wf, "VAELoader")
    check(loaders and loaders[0][1]["inputs"]["vae_name"].startswith("vae-ft-mse-840000"), "SD 1.5 smije koristiti vae-ft-mse-840000")

    # rewrite_vae_refs pokriva i VAEEncode (img2img)
    wf = common_wf(vae="sdxl_vae.safetensors")
    wf["99"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["8", 0], "vae": ["4", 2]}}
    image_gen.rewrite_vae_refs(wf, ["19", 0])
    check(wf["99"]["inputs"]["vae"] == ["19", 0], "VAEEncode se preveže na odabrani VAE")

    # katalog
    for cid, fn, arch in (
        ("vae-sdxl", "sdxl_vae.safetensors", "sdxl"),
        ("vae-sdxl-fp16-fix", "sdxl-vae-fp16-fix.safetensors", "sdxl"),
        ("vae-ft-mse-840000", "vae-ft-mse-840000-ema-pruned.safetensors", "sd15"),
    ):
        item = model_download.curated_by_id(cid)
        check(item and item["kind"] == "vae" and item["filename"] == fn and item["arch"] == arch, f"katalog {cid}")
        check(item and item["url"].startswith("https://huggingface.co/"), f"katalog {cid} HF URL")
        check(item and model_download.dest_dir_for(item["kind"]).name == "vae", f"katalog {cid} ide u models/vae")
    fp16 = model_download.curated_by_id("vae-sdxl-fp16-fix")
    check(fp16 and "madebyollin" in fp16["url"] and fp16["filename"] == "sdxl-vae-fp16-fix.safetensors", "fp16-fix se sprema pod prepoznatljivim imenom")

    # plan + payload
    r = plan({
        "prompt": "in a cafe", "model": "RealVisXL_V5.0_fp16.safetensors", "model_type": "sdxl",
        "seed": 3, "vae": "sdxl_vae.safetensors",
    })
    check(r.get("ok") is True, f"plan s VAE ok ({r.get('error')})")
    check((r.get("meta") or {}).get("vae") == "sdxl_vae.safetensors", "meta.vae")
    check(nodes(r["workflow"], "VAELoader"), "plan workflow ima VAELoader")

    # ui_options
    opts = gs.ui_options()
    ids = [v["id"] for v in opts.get("vaes") or []]
    check("checkpoint" in ids and "sdxl_vae" in ids and "sdxl-vae-fp16-fix" in ids, f"ui_options.vaes {ids}")
    mse = next((v for v in opts["vaes"] if v["id"] == "vae-ft-mse-840000"), None)
    check(mse and mse["arch"] == "sd15", "vae-ft-mse označen kao SD 1.5")


def test_detail_loras_and_trigger():
    print("== jačina detail LoRA-a i Skin Realism okidač ==")
    st, notes = gs.add_detail_loras(
        [],
        {"detail_loras": ["skin_realism", "detail"], "detail_lora_weights": {"skin_realism": 0.85, "detail": 1.15}},
        "sdxl",
        available=lambda n, f=None: True,
    )
    by = {x["detail"]: x for x in st}
    check(abs(by["skin_realism"]["strength_model"] - 0.85) < 1e-9, f"Skin Realism jačina 0,85 (ne 0,5) → {by.get('skin_realism')}")
    check(abs(by["detail"]["strength_model"] - 1.15) < 1e-9, "Fini detalji jačina 1,15 (iznad starog cap-a 0,6)")

    # zadane jačine i dalje poštuju cap (stari testovi)
    st, notes = gs.add_detail_loras([], {"detail_loras": ["skin", "detail"]}, "sdxl", available=lambda n, f=None: True)
    check(all(x["strength_model"] <= gs.VRAM_GUARD["detail_max_weight"] for x in st), "zadane 1-klik jačine ≤ 0,6")

    r = plan({
        "prompt": "portrait in daylight",
        "model": "RealVisXL_V5.0_fp16.safetensors",
        "model_type": "sdxl",
        "seed": 11,
        "quality_prefix": False,
        "detail_loras": ["skin_realism"],
        "detail_lora_weights": {"skin_realism": 0.7},
    })
    check(r.get("ok") is True, f"plan skin_realism ok ({r.get('error')})")
    wf = r["workflow"]
    loaders = [n for _, n in nodes(wf, "LoraLoader")]
    skin = next((n for n in loaders if "skin_realism" in n["inputs"].get("lora_name", "")), None)
    check(skin is not None, "Skin Realism LoraLoader u workflowu")
    check(skin and abs(float(skin["inputs"]["strength_model"]) - 0.7) < 1e-9, "strength_model 0,7 u LoraLoaderu")
    check(skin and abs(float(skin["inputs"]["strength_clip"]) - 0.7) < 1e-9, "strength_clip 0,7 u LoraLoaderu")
    pos = " ".join((r.get("built") or {}).get("chunks") or [r.get("built", {}).get("prompt", "")])
    trig = image_gen.SKIN_REALISM_TRIGGER
    check(pos.count(trig) == 1, f"okidač točno jednom u promptu ({pos.count(trig)})")

    # već je u promptu — bez duplikata
    r2 = plan({
        "prompt": f"portrait, {trig}",
        "model": "RealVisXL_V5.0_fp16.safetensors",
        "model_type": "sdxl",
        "seed": 12,
        "quality_prefix": False,
        "detail_loras": ["skin_realism"],
    })
    blob = " ".join((r2.get("built") or {}).get("chunks") or [])
    chunks = (r2.get("built") or {}).get("chunks") or []
    check(all(c.count(trig) <= 1 for c in chunks) and not any((trig + ", " + trig) in c for c in chunks),
          "okidač se ne dodaje ponovno u chunk koji ga već ima")

    # aktivacija preko stacka (ne prekidača)
    r3 = plan({
        "prompt": "candid photo",
        "model": "RealVisXL_V5.0_fp16.safetensors",
        "model_type": "sdxl",
        "seed": 13,
        "quality_prefix": False,
        "loras": [{"name": "skin_realism_xl.safetensors", "strength_model": 0.55, "strength_clip": 0.55}],
    })
    blob = " ".join((r3.get("built") or {}).get("chunks") or [])
    check(trig in blob, "okidač i kad je Skin Realism u LoRA stacku (bez prekidača)")
    loaders = [n for _, n in nodes(r3["workflow"], "LoraLoader")]
    check(any(abs(float(n["inputs"]["strength_model"]) - 0.55) < 1e-9 and "skin_realism" in n["inputs"]["lora_name"] for n in loaders), "stack jačina 0,55 se poštuje")


def test_face_detailer_instantid():
    print("== Face Detailer prima InstantID conditioning, denoise 0,25 ==")
    check(abs(character.FACE_DETAILER_DEFAULTS["denoise"] - 0.25) < 1e-9, "zadani denoise 0,25")
    wf = common_wf(
        face_detailer=True,
        instantid_image="studio_refs/face.png",
        instantid_weight=0.8,
        instantid_end_at=0.8,
    )
    fd = nodes(wf, "FaceDetailer")
    check(fd, "FaceDetailer postoji")
    inp = fd[0][1]["inputs"]
    check(abs(float(inp["denoise"]) - 0.25) < 1e-9, f"FaceDetailer denoise 0,25 ({inp.get('denoise')})")
    pos, neg = inp.get("positive"), inp.get("negative")
    check(pos == ["44", 1] and neg == ["44", 2], f"FD positive/negative = ApplyInstantID izlazi ({pos}, {neg})")
    apply = wf.get("44") or {}
    check(apply.get("class_type") == "ApplyInstantID", "čvor 44 je ApplyInstantID")
    missing = APPLY_INSTANTID_REQUIRED - set((apply.get("inputs") or {}))
    check(not missing, f"ApplyInstantID ulazi pokrivaju potpis ({missing})")
    missing_fd = FACE_DETAILER_REQUIRED - set(inp)
    check(not missing_fd, f"FaceDetailer ulazi pokrivaju potpis ({missing_fd})")
    # KSampler također koristi InstantID conditioning
    ks = inputs_of(wf, "KSampler")
    check(ks and ks[0]["positive"] == ["44", 1] and ks[0]["negative"] == ["44", 2], "KSampler također čita InstantID")


def test_end_at_and_ipadapter():
    print("== InstantID / IP-Adapter end_at i min jačina ==")
    wf = common_wf(instantid_image="studio_refs/face.png")
    apply = wf["44"]["inputs"]
    check(abs(float(apply["end_at"]) - 0.8) < 1e-9, f"InstantID zadani end_at 0,8 ({apply.get('end_at')})")
    wf = common_wf(instantid_image="x.png", instantid_end_at=0.65)
    check(abs(float(wf["44"]["inputs"]["end_at"]) - 0.65) < 1e-9, "InstantID end_at iz payloada")

    wf = common_wf(ipadapter_images=["a.png"], ipadapter_weight=0.35, ipadapter_end_at=0.85)
    ipa = wf.get("86") or {}
    check(ipa.get("class_type") == "IPAdapter", "IPAdapter čvor 86")
    check(abs(float(ipa["inputs"]["end_at"]) - 0.85) < 1e-9, "IPAdapter end_at 0,85")
    check(abs(float(ipa["inputs"]["weight"]) - 0.35) < 1e-9, "IPAdapter weight 0,35 (ispod starog min 0,6)")
    missing = IPADAPTER_REQUIRED - set(ipa["inputs"])
    check(not missing, f"IPAdapter ulazi pokrivaju potpis ({missing})")
    check(character.IPADAPTER_WEIGHT_MIN == 0.2, "IPADAPTER_WEIGHT_MIN = 0,2")

    # 5+ slika ide na IPAdapterEmbeds — dodaj embeds_scaling (obavezno u plus čvoru)
    wf = common_wf(
        ipadapter_images=[f"r{i}.png" for i in range(5)],
        ipadapter_end_at=0.75,
        object_info={"IPAdapterEncoder": {}, "IPAdapterCombineEmbeds": {}, "IPAdapterEmbeds": {}},
    )
    emb = wf.get("86") or {}
    check(emb.get("class_type") == "IPAdapterEmbeds", "5 refs: IPAdapterEmbeds")
    check(abs(float(emb["inputs"]["end_at"]) - 0.75) < 1e-9, "IPAdapterEmbeds end_at")
    check(emb["inputs"].get("embeds_scaling") == "V only", "IPAdapterEmbeds ima obavezni embeds_scaling")
    missing = IPADAPTER_EMBEDS_REQUIRED - set(emb["inputs"])
    check(not missing, f"IPAdapterEmbeds ulazi pokrivaju potpis ({missing})")


def test_freeu_default_off():
    print("== FreeU isključen po zadanom (Realizam / fotoreal) ==")
    wf = common_wf()
    check(not nodes(wf, "FreeU_V2"), "build_workflow bez freeu: nema FreeU_V2")
    r = plan({
        "prompt": "in a park",
        "model": "RealVisXL_V5.0_fp16.safetensors",
        "model_type": "sdxl",
        "seed": 21,
        "quality_profile": "realism",
        "size_preset": "ig_portrait",
    })
    check(r.get("ok") is True, f"Realizam plan ok ({r.get('error')})")
    check(not nodes(r["workflow"], "FreeU_V2"), "Realizam: FreeU_V2 nije u workflowu")
    check((r.get("meta") or {}).get("freeu") is False, "meta.freeu je False")
    r2 = plan({
        "prompt": "in a park",
        "model": "RealVisXL_V5.0_fp16.safetensors",
        "model_type": "sdxl",
        "seed": 22,
        "quality_profile": "realism",
        "freeu": True,
    })
    check(nodes(r2["workflow"], "FreeU_V2"), "eksplicitni freeu=True i dalje doda čvor")
    check(all(t["freeu"] == 0 for t in gs.DEFAULT_TEMPLATES), "ugrađeni predlošci: freeu=0")
    check(gs.default_body_options()["freeu"] is False, "default_body_options.freeu = False")
    check(gs.ui_options()["defaults"]["freeu"] is False, "ui_options.defaults.freeu = False")


def test_lora_stack_hardening():
    print("== LoRA stack s Generiranja uvijek stiže u backend ==")
    # payload kao s glavnog ekrana: uvijek ima 'lora' (LoRA osobe), plus 'loras' sa + Dodaj LoRA
    r = plan({
        "prompt": "walking in town",
        "model": "RealVisXL_V5.0_fp16.safetensors",
        "model_type": "sdxl",
        "seed": 31,
        "lora": "char_amilija.safetensors",
        "lora_strength": 0.8,
        "loras": [
            {"name": "add_detail_xl.safetensors", "strength_model": 0.9, "strength_clip": 0.9},
            {"name": "light_fix.safetensors", "strength_model": 0.4, "strength_clip": 0.4},
        ],
    })
    check(r.get("ok") is True, f"plan sa stackom ok ({r.get('error')})")
    chain = [(n["inputs"]["lora_name"], float(n["inputs"]["strength_model"])) for _, n in nodes(r["workflow"], "LoraLoader")]
    names = [n for n, _ in chain]
    check("char_amilija.safetensors" in names, f"LoRA osobe u lancu {names}")
    check("add_detail_xl.safetensors" in names and "light_fix.safetensors" in names, f"stack s Generiranja u lancu {names}")
    check(any(n == "add_detail_xl.safetensors" and abs(s - 0.9) < 1e-9 for n, s in chain), "jačina 0,9 iz stacka")
    # lanac: svaki sljedeći čita prethodni model
    loaders = nodes(r["workflow"], "LoraLoader")
    prev = None
    ok_chain = True
    for i, (_, n) in enumerate(loaders):
        src = n["inputs"]["model"]
        if i == 0:
            if src != ["4", 0]:
                ok_chain = False
        else:
            if prev is None or src != [prev, 0]:
                ok_chain = False
        prev = loaders[i][0]
    check(ok_chain and len(loaders) >= 3, f"LoraLoaderi su ulančani ({[k for k, _ in loaders]})")

    # 'lora' u bodyju VIŠE NE briše profilni stack
    prof = {"id": 9, "name": "Ana", "appearance_prompt": "long hair", "lora_stack": [
        {"name": "from_profile.safetensors", "strength_model": 0.6, "strength_clip": 0.6, "enabled": True},
    ]}
    stack = gs.resolve_lora_stack({"lora": "char.safetensors", "prompt": "x"}, prof, "sdxl")
    check(any(x["name"] == "from_profile.safetensors" for x in stack), "prisutnost 'lora' ne briše profilni stack")
    stack2 = gs.resolve_lora_stack({"lora": "char.safetensors", "loras": [{"name": "gen.safetensors", "strength_model": 0.5}]}, prof, "sdxl")
    check(any(x["name"] == "gen.safetensors" for x in stack2) and not any(x["name"] == "from_profile.safetensors" for x in stack2), "eksplicitni loras iz bodyja ima prednost")


def test_static_ui():
    print("== statičke provjere UI-ja 1.3.7 ==")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    v11 = (ROOT / "static" / "v11.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "ui_v130.css").read_text(encoding="utf-8")
    check('id="v11VaeFile"' in v11 and "Iz checkpointa" in v11, "UI padajući izbornik VAE s 'Iz checkpointa'")
    check("id=\"v11Freeu\"" in v11 and 'id="v11Freeu" checked' not in v11, "FreeU nije checked po zadanom")
    check("v11IidEnd" in v11 and "Kraj utjecaja" in v11, "InstantID klizač Kraj utjecaja")
    check('id="ipaEndAt"' in html and 'min="0.5"' in html.split('id="ipaEndAt"', 1)[1][:200], "IP-Adapter Kraj utjecaja 0,5–1,0")
    check('id="ipaWeight" min="0.2"' in html and 'id="pIpaWeight" min="0.2"' in html, "IP-Adapter jačina od 0,2")
    check('class="dt-w"' in v11 and 'max="1.5"' in v11 and "detail_lora_weights" in v11, "detail LoRA klizači 0–1,5 i šalju weights")
    check("if (!$(\"v11Sampler\")) return out;" in v11, "Napredno i dalje može biti neučitano")
    # loras se skupljaju PRIJE tog returna
    gen = v11.split("function genExtras()", 1)[1].split("async function enqueueBatch", 1)[0]
    ret = gen.find('if (!$("v11Sampler")) return out;')
    loras_line = gen.find("out.loras")
    check(ret > 0 and loras_line > 0 and loras_line < ret, "genExtras šalje loras i prije učitanog Napredno")
    check(".dt-str" in css, "CSS za jačinu detail LoRA-a")
    for rel in ("static/v11.js", "index.html", "image_gen.py", "services/generation_service.py", "studio.py", "character.py", "model_download.py"):
        txt = (ROOT / rel).read_text(encoding="utf-8")
        check(not BANNED.search(txt), f"{rel}: bez zabranjenih izraza")


def main():
    print("test_v137")
    test_vae_picker()
    test_detail_loras_and_trigger()
    test_face_detailer_instantid()
    test_end_at_and_ipadapter()
    test_freeu_default_off()
    test_lora_stack_hardening()
    test_static_ui()
    print()
    if FAILED:
        print(f"FAILED {FAILED}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
