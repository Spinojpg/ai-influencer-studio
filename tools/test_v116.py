#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.0.16: konzistentnost lika, IP-Adapter, Face Detailer, IG formati."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import character
import image_gen
import inbox
import model_download
import studio

FAILED = 0


def check(cond, msg):
    global FAILED
    if cond:
        print("  OK ", msg)
    else:
        FAILED += 1
        print("  FAIL", msg)


def _base_wf(**kwargs):
    args = dict(
        prompt="adult woman, sitting in a cafe",
        negative=image_gen.DEFAULT_NEGATIVE,
        model="RealVisXL_V5.0_fp16.safetensors",
        width=768,
        height=1152,
        batch=1,
        seed=7,
        steps=30,
        cfg=5.0,
        sampler_name="dpmpp_2m",
        scheduler="karras",
        arch="sdxl",
        object_info={},
    )
    args.update(kwargs)
    return image_gen.build_workflow(**args)


def test_ig_presets():
    print("== IG formati ==")
    sdxl = {p["id"]: p for p in image_gen.SDXL_PRESETS}
    sd15 = {p["id"]: p for p in image_gen.SD15_PRESETS}
    krea = {p["id"]: p for p in image_gen.KREA2_PRESETS}
    check(image_gen.presets_for("sdxl")[0]["width"] == 768, "zadani SDXL portret ostaje 768")
    check(image_gen.presets_for("sdxl")[0]["height"] == 1152, "zadani SDXL portret ostaje 1152")
    check(image_gen.presets_for("sd15")[0]["width"] == 512, "zadani SD1.5 portret ostaje 512")

    for pack, label in ((sdxl, "SDXL"), (krea, "Krea 2")):
        check(pack["ig_portrait"]["width"] == 896 and pack["ig_portrait"]["height"] == 1120, f"{label} 4:5 platno 896×1120")
        check(pack["ig_portrait"]["output_width"] == 1080 and pack["ig_portrait"]["output_height"] == 1350, f"{label} 4:5 izlaz 1080×1350")
        check(pack["ig_square"]["width"] == 1024 and pack["ig_square"]["output_width"] == 1080, f"{label} 1:1 platno 1024, izlaz 1080")
        check(pack["ig_story"]["width"] == 768 and pack["ig_story"]["height"] == 1368, f"{label} 9:16 platno 768×1368")
        check(pack["ig_story"]["output_width"] == 1080 and pack["ig_story"]["output_height"] == 1920, f"{label} 9:16 izlaz 1080×1920")

    check(sd15["ig_portrait"]["width"] == 512 and sd15["ig_portrait"]["height"] == 640, "SD1.5 4:5 manje platno 512×640")
    check(sd15["ig_square"]["width"] == 512 and sd15["ig_square"]["output_width"] == 1080, "SD1.5 1:1 512→1080")
    check(sd15["ig_story"]["width"] == 432 and sd15["ig_story"]["height"] == 768, "SD1.5 9:16 432×768")
    for pr in list(sdxl.values()) + list(sd15.values()) + list(krea.values()):
        check(pr["width"] % 8 == 0 and pr["height"] % 8 == 0, f"{pr['id']} gen je višekratnik 8")

    mapped = image_gen.resolve_canvas("sdxl", 1080, 1350)
    check(mapped["width"] == 896 and mapped["height"] == 1120, "1080×1350 se mapira na sigurno platno")
    check(mapped["output_width"] == 1080 and mapped["upscale"] is True, "izlaz ostaje 1080×1350")
    story = image_gen.resolve_canvas("sd15", None, None, preset_id="ig_story")
    check(story["width"] == 432 and story["output_height"] == 1920, "preset_id ig_story za SD1.5")
    plain = image_gen.resolve_canvas("sdxl", 768, 1152)
    check(plain["upscale"] is False and plain["output_width"] == 768, "obični portret bez upscalea")


def test_ig_workflow_scale():
    print("== ImageScale u workflowu ==")
    wf = _base_wf(width=896, height=1120, output_width=1080, output_height=1350)
    scale = wf.get("92") or {}
    check(scale.get("class_type") == "ImageScale", "ImageScale čvor")
    inp = scale.get("inputs") or {}
    check(inp.get("upscale_method") == "lanczos", "lanczos")
    check(inp.get("width") == 1080 and inp.get("height") == 1350, "IG 4:5 izlaz")
    check(inp.get("crop") == "disabled", "crop disabled")
    check(wf["9"]["inputs"]["images"] == ["92", 0], "SaveImage čita uvećanu sliku")
    check(wf["5"]["inputs"]["width"] == 896 and wf["5"]["inputs"]["height"] == 1120, "latent ostaje 896×1120")

    plain = _base_wf(width=768, height=1152)
    check("92" not in plain, "nema ImageScale za obični portret")
    check(plain["9"]["inputs"]["images"] == ["8", 0], "SaveImage iz VAEDecode")

    krea = image_gen.build_workflow(
        prompt="adult woman, cafe",
        negative="",
        model=image_gen.KREA2_UNET,
        width=768,
        height=1368,
        batch=1,
        seed=1,
        steps=8,
        arch="krea2",
        object_info={},
        output_width=1080,
        output_height=1920,
    )
    check(krea.get("92", {}).get("class_type") == "ImageScale", "Krea 2 također ima ImageScale")
    check(krea["9"]["inputs"]["images"] == ["92", 0], "Krea SaveImage s IG izlaza")
    check("IPAdapter" not in {n.get("class_type") for n in krea.values()}, "Krea 2 bez IP-Adaptera")


def test_appearance_weight():
    print("== Težina izgleda ==")
    built = image_gen.build_positive_prompt(
        scene="lying on a bed",
        appearance="long wavy brown hair, green eyes",
        quality=True,
        adult_term="adult woman, 26",
        appearance_weight=1.3,
    )
    appear_chunk = next((c for c in built["chunks"] if "long wavy brown hair" in c), "")
    check("(long wavy brown hair, green eyes:1.3)" == appear_chunk or appear_chunk.startswith("("), f"omot težine: {appear_chunk!r}")
    check(":1.3)" in appear_chunk, "težina 1.3 u chunku")
    check("lying on a bed" in built["chunks"][0], "scena ostaje prva")
    check("child, teen" in image_gen.DEFAULT_NEGATIVE, "child/teen u negativnom")
    one = image_gen.build_positive_prompt(
        scene="in a cafe",
        appearance="auburn hair",
        quality=False,
        appearance_weight=1.0,
    )
    check(any(c == "auburn hair" for c in one["chunks"]), "težina 1.0 ne omotava")


def test_preferred_model_and_lora():
    print("== Preferirani model i LoRA po osobi ==")
    prof = {
        "id": 4,
        "name": "Luna Marić",
        "appearance_prompt": "shoulder-length brown hair, green eyes",
        "age_vibe": "26",
        "preferred_model": "juggernautXL_ragnarok.safetensors",
        "preferred_lora": "face-xl.safetensors",
        "preferred_lora_strength": 0.7,
        "model_type": "sdxl",
        "lock_seed": True,
        "locked_seed": "4242",
        "appearance_weight": 1.4,
    }
    orig = image_gen.lora_available
    image_gen.lora_available = lambda name, folder=None: True
    try:
        used = studio.plan_image_generation(
            {"prompt": "sitting in a cafe, window light", "persona_id": 4, "quality_prefix": False},
            profile=prof,
            object_info={},
        )
        over = studio.plan_image_generation(
            {
                "prompt": "sitting in a cafe",
                "persona_id": 4,
                "model": "RealVisXL_V5.0_fp16.safetensors",
                "model_type": "sdxl",
                "lora": "other-xl.safetensors",
                "lora_strength": 0.5,
                "seed": 99,
                "lock_seed": True,
                "quality_prefix": False,
            },
            profile=prof,
            object_info={},
        )
    finally:
        image_gen.lora_available = orig

    check(used.get("ok") is True, f"plan s preferencijama: {used.get('error')}")
    check((used.get("meta") or {}).get("model") == "juggernautXL_ragnarok.safetensors", "preferred_model se koristi kad body nema model")
    check((used.get("meta") or {}).get("lora") == "face-xl.safetensors", "preferred_lora se koristi kad body nema lora")
    check((used.get("meta") or {}).get("lora_strength") == 0.7, "preferred jačina LoRA-e")
    check((used.get("meta") or {}).get("seed") == 4242, "zaključani seed kad je body seed prazan")
    appear = " ".join((used.get("built") or {}).get("chunks") or [])
    check(":1.4)" in appear and "shoulder-length brown hair" in appear, "težina izgleda s profila 1.4")

    check(over.get("ok") is True, f"override plan: {over.get('error')}")
    check((over.get("meta") or {}).get("model") == "RealVisXL_V5.0_fp16.safetensors", "body.model prebija preferred_model")
    check((over.get("meta") or {}).get("lora") == "other-xl.safetensors", "body.lora prebija preferred_lora")
    check((over.get("meta") or {}).get("seed") == 99, "eksplicitni seed prebija zaključani")


def test_ipadapter_and_detailer_graphs():
    print("== Workflow grafovi: refs, LoRA, turbo, Face Detailer, SD1.5 ==")
    refs = ["studio_refs/p4_1.jpg", "studio_refs/p4_2.jpg", "studio_refs/p4_3.jpg"]
    wf = _base_wf(
        user_lora="face-xl.safetensors",
        user_lora_strength=0.8,
        turbo=True,
        ipadapter_images=refs,
        ipadapter_weight=0.85,
        face_detailer=True,
        output_width=1080,
        output_height=1350,
        width=896,
        height=1120,
    )
    types = {nid: node["class_type"] for nid, node in wf.items()}
    check(types.get("80") == "LoadImage" and types.get("81") == "LoadImage" and types.get("82") == "LoadImage", "3× LoadImage")
    check(wf["80"]["inputs"]["image"] == refs[0], "prva ref datoteka")
    check(types.get("83") == "ImageBatch" and types.get("84") == "ImageBatch", "ImageBatch za 2. i 3. sliku")
    check(types.get("85") == "IPAdapterUnifiedLoader", "UnifiedLoader")
    check(wf["85"]["inputs"]["preset"] == "PLUS FACE (portraits)", "PLUS FACE preset")
    check("insightface" not in json.dumps(wf["85"]).lower(), "nema InsightFace u loaderu")
    check(types.get("86") == "IPAdapter", "IPAdapter apply")
    check(wf["86"]["inputs"]["weight"] == 0.85, "jačina 0.85")
    check(wf["86"]["inputs"]["weight_type"] == "standard", "weight_type standard")
    check(types.get("12") == "LoraLoader", "korisnička LoRA")
    check(types.get("22") == "LoraLoader", "Turbo LoRA u lancu")
    # model ulazi u IP-Adapter nakon LoRA lanca
    check(wf["85"]["inputs"]["model"][0] == "22", "IP-Adapter na modelu nakon LoRA/Turbo")
    check(wf["3"]["inputs"]["model"] == ["86", 0], "KSampler koristi IP-Adapter model")
    check(types.get("90") == "UltralyticsDetectorProvider", "YOLO detektor")
    check(wf["90"]["inputs"]["model_name"] == "bbox/face_yolov8m.pt", "face_yolov8m.pt")
    check(types.get("91") == "FaceDetailer", "FaceDetailer")
    check(wf["91"]["inputs"]["guide_size"] == 384.0, "manji guide za 8 GB")
    check(types.get("92") == "ImageScale", "IG upscale nakon detailera")
    check(wf["9"]["inputs"]["images"] == ["92", 0], "SaveImage iz IG scalea")
    check(wf["92"]["inputs"]["image"] == ["91", 0], "scale čita FaceDetailer")

    off = _base_wf(arch="sd15", model="Realistic_Vision_V5.1_fp16-no-ema.safetensors", width=512, height=768)
    off_types = {n["class_type"] for n in off.values()}
    check("IPAdapter" not in off_types and "FaceDetailer" not in off_types, "bez refs i bez detailera nema tih čvorova")

    one = _base_wf(arch="sd15", model="Realistic_Vision_V5.1.safetensors", width=512, height=640, ipadapter_images=["studio_refs/a.jpg"], ipadapter_weight=0.7)
    check(one["80"]["class_type"] == "LoadImage", "SD1.5 jedna ref")
    check("83" not in one, "jedna slika — nema ImageBatch")
    check(one["86"]["inputs"]["weight"] == 0.7, "SD1.5 jačina")
    check(one["3"]["inputs"]["model"] == ["86", 0], "SD1.5 KSampler iz IP-Adaptera")

    krea = _base_wf(arch="krea2", model=image_gen.KREA2_UNET, width=1024, height=1024, ipadapter_images=refs, face_detailer=True)
    ktypes = {n["class_type"] for n in krea.values()}
    check("IPAdapter" not in ktypes and "FaceDetailer" not in ktypes, "Krea 2 ignora refs i Face Detailer")


def test_plan_ipadapter_and_ig():
    print("== plan_image_generation: refs + IG + greške ==")
    prof = {
        "id": 5,
        "name": "Luna",
        "appearance_prompt": "brown hair, green eyes",
        "age_vibe": "26",
        "preferred_model": "RealVisXL_V5.0_fp16.safetensors",
        "reference_images": ["profiles/5/ref_1.jpg"],
    }
    orig_err = character.ipadapter_error
    orig_face = character.face_detailer_error
    orig_lora = image_gen.lora_available
    character.ipadapter_error = lambda *a, **k: None
    character.face_detailer_error = lambda *a, **k: None
    image_gen.lora_available = lambda name, folder=None: True
    try:
        result = studio.plan_image_generation(
            {
                "prompt": "standing on a balcony, evening light",
                "persona_id": 5,
                "size_preset": "ig_portrait",
                "ipadapter_images": ["studio_refs/p5_1.jpg"],
                "ipadapter_weight": 0.9,
                "face_detailer": True,
                "quality_prefix": True,
                "seed": 3,
            },
            profile=prof,
            object_info={},
        )
        krea = studio.plan_image_generation(
            {
                "prompt": "standing on a balcony",
                "persona_id": 5,
                "model": image_gen.KREA2_UNET,
                "model_type": "krea2",
                "size_preset": "ig_square",
                "ipadapter_images": ["studio_refs/p5_1.jpg"],
                "face_detailer": True,
                "seed": 3,
                "quality_prefix": False,
            },
            profile=prof,
            object_info={},
        )
    finally:
        character.ipadapter_error = orig_err
        character.face_detailer_error = orig_face
        image_gen.lora_available = orig_lora

    check(result.get("ok") is True, f"plan IG+refs: {result.get('error')}")
    meta = result.get("meta") or {}
    wf = result.get("workflow") or {}
    check(meta.get("gen_width") == 896 and meta.get("gen_height") == 1120, f"gen platno {meta.get('gen_width')}x{meta.get('gen_height')}")
    check(meta.get("width") == 1080 and meta.get("height") == 1350, "meta širina/visina su IG izlaz")
    check(meta.get("ipadapter") is True and meta.get("ipadapter_weight") == 0.9, "meta IP-Adapter")
    check(meta.get("face_detailer") is True, "meta Face Detailer")
    check(wf.get("86", {}).get("class_type") == "IPAdapter", "plan ima IPAdapter")
    check(wf.get("91", {}).get("class_type") == "FaceDetailer", "plan ima FaceDetailer")
    check(wf.get("92", {}).get("inputs", {}).get("width") == 1080, "plan ImageScale 1080")

    # Krea 2 plan može pasti na nedostajućim datotekama — to je OK, bitno je da ne ubaci IP-Adapter.
    if krea.get("ok"):
        kwf = krea.get("workflow") or {}
        ktypes = {n.get("class_type") for n in kwf.values()}
        check("IPAdapter" not in ktypes and "FaceDetailer" not in ktypes, "Krea plan bez IP-Adapter/Detailer")
        check((krea.get("meta") or {}).get("width") == 1080, "Krea IG kvadrat izlaz 1080")
    else:
        check("Krea 2" in (krea.get("error") or "") or krea.get("need") in {"krea2-files", "comfy-update"}, f"Krea bez datoteka javlja jasnu grešku: {krea.get('error')}")

    # Kad fale čvorovi, plan vrati hrvatsku poruku.
    blocked = studio.plan_image_generation(
        {
            "prompt": "in a cafe",
            "persona_id": 5,
            "model": "RealVisXL_V5.0_fp16.safetensors",
            "model_type": "sdxl",
            "ipadapter_images": ["studio_refs/p5_1.jpg"],
            "quality_prefix": False,
        },
        profile=prof,
        object_info={"CheckpointLoaderSimple": {}, "KSampler": {}, "CLIPTextEncode": {}},
    )
    check(blocked.get("ok") is False, "blokira kad čvorovi IP-Adaptera nisu u katalogu")
    check(blocked.get("need") == "ipadapter-nodes", f"need=ipadapter-nodes, got {blocked.get('need')}")
    check("IP-Adapter" in (blocked.get("error") or "") or "ComfyUI_IPAdapter" in (blocked.get("error") or ""), "hrvatska poruka s instalacijom")


def test_catalog_and_paths():
    print("== Katalog IP-Adapter paketa ==")
    item = model_download.curated_by_id("ipadapter-plus-face")
    check(item is not None and item.get("kind") == "bundle", "bundle postoji")
    names = {f["filename"]: f for f in item["files"]}
    check("CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors" in names, "CLIP Vision ViT-H ime")
    check(names["CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"]["url"].startswith("https://huggingface.co/h94/IP-Adapter/"), "HF h94 CLIP")
    check(names["CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"]["size_bytes"] == 2528373448, "CLIP veličina")
    check(names["ip-adapter-plus-face_sdxl_vit-h.safetensors"]["size_bytes"] == 847517512, "SDXL plus-face veličina")
    check(names["ip-adapter-plus-face_sd15.safetensors"]["size_bytes"] == 98183288, "SD15 plus-face veličina")
    check(model_download.dest_dir_for("clip_vision") == __import__("comfy_launch").clip_vision_dir(), "dest clip_vision")
    check(model_download.dest_dir_for("ipadapter") == __import__("comfy_launch").ipadapter_dir(), "dest ipadapter")
    yolo = model_download.curated_by_id("face-yolov8m")
    check(yolo and yolo["filename"] == "face_yolov8m.pt" and yolo["size_bytes"] == 52026019, "YOLOv8m lice")
    check("ultralytics" in str(model_download.dest_dir_for("ultralytics_bbox")), "dest ultralytics/bbox")


def test_inbox_refs(tmp: Path):
    print("== Referentne slike u profilu ==")
    os.environ["STUDIO_DATA_DIR"] = str(tmp)
    inbox.configure_paths(data_dir=tmp)
    inbox.init_db()
    prof = inbox.upsert_profile({
        "name": "Luna Marić",
        "appearance_prompt": "adult woman, 26, brown hair, green eyes",
        "preferred_model": "RealVisXL_V5.0_fp16.safetensors",
        "preferred_lora": "face-xl.safetensors",
        "preferred_lora_strength": 0.75,
        "appearance_weight": 1.35,
        "ipadapter_weight": 0.85,
        "face_detailer": False,
        "lock_seed": True,
        "locked_seed": "12345",
        "age_vibe": "26",
    })
    pid = prof["id"]
    check(prof["preferred_lora"] == "face-xl.safetensors", "preferred_lora spremljena")
    check(abs(float(prof["appearance_weight"]) - 1.35) < 0.001, "appearance_weight spremljena")
    check(prof["lock_seed"] is True and str(prof["locked_seed"]) == "12345", "zaključan seed spremljen")
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05"
        b"\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    r1 = inbox.add_reference_image(pid, png, "png")
    r2 = inbox.add_reference_image(pid, png + b"2", "png")
    r3 = inbox.add_reference_image(pid, png + b"3", "png")
    check(len(r1) == 1 and len(r2) == 2 and len(r3) == 3, "dodavanje do 3 slike")
    try:
        inbox.add_reference_image(pid, png, "png")
        check(False, "4. slika mora pasti")
    except ValueError:
        check(True, "4. slika odbijena")
    reordered = inbox.reorder_reference_images(pid, [2, 0, 1])
    check(reordered[0] == r3[2] and reordered[1] == r3[0], f"promjena redoslijeda: {reordered}")
    left = inbox.delete_reference_image(pid, index=1)
    check(len(left) == 2, "brisanje jedne slike")
    got = inbox.get_profile(pid)
    check(got["reference_count"] == 2 and got["has_reference"], "profil vidi ostale slike")
    path = inbox.reference_image_path(pid, 0)
    check(path is not None and path.is_file(), "datoteka je na disku")
    # appearance from profile + adult
    appear = image_gen.appearance_from_profile(got, "")
    term = image_gen.adult_term_for_profile(got, appearance=appear, scene="in a cafe")
    check(term == "adult woman, 26", f"adult + dob: {term}")


def test_ui():
    print("== Sučelje 1.0.16 ==")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    for needle, msg in (
        ("id=\"appearMeta\"", "sažetak Osobe ima meta čipove"),
        ("Zaključaj seed", "zaključavanje seeda u profilu"),
        ("id=\"pRefList\"", "lista referentnih slika"),
        ("id=\"installIpa\"", "gumb Instaliraj IP-Adapter"),
        ("id=\"installFace\"", "gumb Instaliraj Face Detailer"),
        ("id=\"appearWeight\"", "klizač težine izgleda u Napredno"),
        ("id=\"ipaWeight\"", "klizač jačine reference u Napredno"),
        ("id=\"faceDetailer\"", "Face Detailer u Napredno"),
        ("output_width: outputWidth", "payload šalje IG izlaz"),
        ("dataset.ow", "botuni formata nose izlazne IG dimenzije"),
        ("IG formati", "napomena o IG formatima"),
        ("1080", "1080 px u uputi"),
        ("applyProfileToImageForm(selectedPersona())", "promjena Osobe primjenjuje model i LoRA"),
        ("child, teen", "zaštita u default negativnom je u JS-u"),
    ):
        check(needle in html, msg)


def main():
    print("test_v116")
    test_ig_presets()
    test_ig_workflow_scale()
    test_appearance_weight()
    test_preferred_model_and_lora()
    test_ipadapter_and_detailer_graphs()
    test_plan_ipadapter_and_ig()
    test_catalog_and_paths()
    with tempfile.TemporaryDirectory() as td:
        test_inbox_refs(Path(td) / "data")
    test_ui()
    print("FAILED" if FAILED else "ALL OK", FAILED)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
