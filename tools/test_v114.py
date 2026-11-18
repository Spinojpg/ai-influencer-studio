#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.0.14: izbornik LoRA-e i Osoba umjesto Izgleda."""

from __future__ import annotations

import json
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import image_gen
import studio

FAILED = 0


def check(cond, msg):
    global FAILED
    if cond:
        print("  OK ", msg)
    else:
        FAILED += 1
        print("  FAIL", msg)


def write_safetensors_meta(path: Path, meta: dict) -> None:
    header = json.dumps({"__metadata__": meta, "t": {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]}})
    raw = header.encode("utf-8")
    while len(raw) % 8:
        raw += b" "
    path.write_bytes(struct.pack("<Q", len(raw)) + raw + b"\x00\x00")


def test_detect_lora_arch():
    print("== Detekcija arhitekture LoRA-e ==")
    check(image_gen.detect_lora_arch("add-detail-xl.safetensors") == "sdxl", "filename xl -> sdxl")
    check(image_gen.detect_lora_arch("character_sdxl_v2.safetensors") == "sdxl", "filename sdxl")
    check(image_gen.detect_lora_arch("film-grain-sd15.safetensors") == "sd15", "filename sd15")
    check(image_gen.detect_lora_arch("style_sd1.5.safetensors") == "sd15", "filename sd1.5")
    check(image_gen.detect_lora_arch("mystery-style.safetensors") == "unknown", "nema naznake -> unknown")
    check(
        image_gen.detect_lora_arch(
            "mystery.safetensors",
            {"ss_base_model_version": "sdxl_base_v1.0"},
        )
        == "sdxl",
        "ss_base_model_version sdxl",
    )
    check(
        image_gen.detect_lora_arch(
            "mystery.safetensors",
            {"modelspec.architecture": "stable-diffusion-v1-5"},
        )
        == "sd15",
        "modelspec.architecture sd1.5",
    )
    check(
        image_gen.detect_lora_arch(
            "mystery.safetensors",
            {"ss_base_model_version": "flux_dev"},
        )
        == "unknown",
        "flux ostaje unknown",
    )
    check(image_gen.is_turbo_lora_file(image_gen.TURBO_SDXL["lora_filename"]), "turbo filename prepoznat")
    check(image_gen.is_turbo_lora_file("foo.safetensors") is False, "obična datoteka nije turbo")

    turbo = image_gen.TURBO_SDXL["lora_filename"]
    names = [
        "add-detail-xl.safetensors",
        "film-grain-sd15.safetensors",
        "mystery-style.safetensors",
        turbo,
    ]
    entries = image_gen.classify_loras(names)
    check(all(e["name"] != turbo for e in entries), "Turbo LoRA isključena iz popisa")
    check(len(entries) == 3, f"3 korisničke LoRA-e, dobio {len(entries)}")
    by_name = {e["name"]: e for e in entries}
    check(by_name["add-detail-xl.safetensors"]["arch"] == "sdxl" and by_name["add-detail-xl.safetensors"]["group"] == "SDXL", "grupa SDXL")
    check(by_name["film-grain-sd15.safetensors"]["group"] == "SD 1.5", "grupa SD 1.5")
    check(by_name["mystery-style.safetensors"]["group"] == "Ostalo", "grupa Ostalo")

    sdxl_list = image_gen.loras_for_arch(entries, "sdxl")
    sdxl_names = {e["name"] for e in sdxl_list}
    check("add-detail-xl.safetensors" in sdxl_names, "SDXL vidi XL LoRA")
    check("mystery-style.safetensors" in sdxl_names, "SDXL vidi Ostalo")
    # 1.0.19: ništa se ne skriva — SD 1.5 LoRA je uz SDXL model na kraju, kao nekompatibilna.
    check("film-grain-sd15.safetensors" in sdxl_names, "SDXL vidi i SD 1.5 LoRA (Ostalo / možda nekompatibilno)")
    check(sdxl_list[0]["name"] == "add-detail-xl.safetensors" and sdxl_list[0]["compatible"] is True, "kompatibilna je prva")
    check([e for e in sdxl_list if e["name"] == "film-grain-sd15.safetensors"][0]["compatible"] is False, "SD 1.5 uz SDXL označena kao nekompatibilna")
    sd15_list = image_gen.loras_for_arch(entries, "sd15")
    check(sd15_list[0]["name"] == "film-grain-sd15.safetensors" and len(sd15_list) == 3, "SD 1.5: kompatibilna prva, ostale ostaju")
    check(image_gen.loras_for_arch(entries, "krea2") == [], "Krea 2 nema LoRA izbornik")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "frommeta.safetensors"
        write_safetensors_meta(path, {"ss_base_model_version": "sdxl_base_v1.0"})
        meta = image_gen.read_safetensors_metadata(path)
        check(meta.get("ss_base_model_version") == "sdxl_base_v1.0", f"lokalni metadata {meta}")
        check(image_gen.detect_lora_arch(path.name, meta) == "sdxl", "arch iz lokalnog metadata")


def _base_wf_kwargs(**extra):
    kw = dict(
        prompt="adult woman, sitting in a cafe",
        negative="blurry, child, teen",
        model="RealVisXL_V5.0_fp16.safetensors",
        width=768,
        height=1152,
        batch=1,
        seed=7,
        steps=30,
        cfg=5,
        sampler_name="dpmpp_2m",
        scheduler="karras",
        arch="sdxl",
        object_info={},
    )
    kw.update(extra)
    return kw


def test_lora_workflow_chain():
    print("== LoraLoader lanac (korisnička + Turbo) ==")
    turbo = image_gen.TURBO_SDXL["lora_filename"]

    only_user = image_gen.build_workflow(**_base_wf_kwargs(user_lora="add-detail-xl.safetensors", user_lora_strength=0.8))
    check(only_user["12"]["class_type"] == "LoraLoader", "samo korisnička: node 12")
    check(only_user["12"]["inputs"]["lora_name"] == "add-detail-xl.safetensors", "ime korisničke")
    check(only_user["12"]["inputs"]["strength_model"] == 0.8, "jačina 0.8")
    check(only_user["12"]["inputs"]["model"] == ["4", 0] and only_user["12"]["inputs"]["clip"] == ["4", 1], "veže se na checkpoint")
    check(only_user["3"]["inputs"]["model"] == ["12", 0], "KSampler iz korisničke LoRA-e")
    check(only_user["6"]["inputs"]["clip"] == ["12", 1], "CLIPTextEncode iz LoRA CLIP-a")
    check("22" not in only_user, "nema drugog LoraLoadera")

    only_turbo = image_gen.build_workflow(**_base_wf_kwargs(turbo=True))
    check(only_turbo["12"]["class_type"] == "LoraLoader", "samo Turbo: node 12")
    check(only_turbo["12"]["inputs"]["lora_name"] == turbo, "Turbo ime (regresija 1.0.9)")
    check(only_turbo["3"]["inputs"]["steps"] == 8, "turbo 8 koraka")
    check(only_turbo["3"]["inputs"]["model"] == ["12", 0], "KSampler iz Turbo LoRA-e")

    both = image_gen.build_workflow(
        **_base_wf_kwargs(
            turbo=True,
            user_lora="add-detail-xl.safetensors",
            user_lora_strength=0.75,
        )
    )
    check(both["12"]["inputs"]["lora_name"] == "add-detail-xl.safetensors", "oba: prvo korisnička")
    check(both["12"]["inputs"]["strength_model"] == 0.75, "korisnička jačina ostaje 0.75")
    check(both["22"]["class_type"] == "LoraLoader", "oba: drugi LoraLoader")
    check(both["22"]["inputs"]["lora_name"] == turbo, "oba: zatim Turbo")
    check(both["22"]["inputs"]["model"] == ["12", 0] and both["22"]["inputs"]["clip"] == ["12", 1], "Turbo se veže na korisničku")
    check(both["3"]["inputs"]["model"] == ["22", 0], "KSampler iz lanca")
    check(both["6"]["inputs"]["clip"] == ["22", 1], "CLIP iz lanca")
    check(both["7"]["inputs"]["clip"] == ["22", 1], "negativni CLIP iz lanca")
    check(both["3"]["inputs"]["steps"] == 8 and both["3"]["inputs"]["cfg"] == 5, "turbo postavke uz obje LoRA-e")
    check(both["8"]["inputs"]["vae"] == ["4", 2], "VAE i dalje s checkpointa")

    krea = image_gen.build_workflow(
        prompt="adult woman, on a beach",
        negative="blurry",
        model="krea2_turbo_fp8_scaled.safetensors",
        width=1024,
        height=1024,
        batch=1,
        seed=1,
        steps=8,
        arch="krea2",
        user_lora="add-detail-xl.safetensors",
        turbo=True,
        object_info={},
    )
    types = {n["class_type"] for n in krea.values()}
    check("LoraLoader" not in types, "Krea 2 nema LoraLoader čak i kad je poslana LoRA")
    check("UNETLoader" in types and "CheckpointLoaderSimple" not in types, "Krea 2 i dalje UNET workflow")


def test_appearance_and_adult():
    print("== Izgled s persone i adult prefix ==")
    prof = {
        "id": 3,
        "name": "Luna Marić",
        "appearance_prompt": "portrait of a woman, long wavy brown hair, green eyes, small tattoo on the left shoulder",
        "tattoos": "small tattoo on the left shoulder",
        "age_vibe": "26 godina, opušten gradski vibe",
        "style": "prijateljska, vedra",  # chat stil, ne ide u sliku
    }
    appear = image_gen.appearance_from_profile(prof, "red summer dress")
    check("long wavy brown hair" in appear and "green eyes" in appear, f"kosa i oči: {appear}")
    check("small tattoo on the left shoulder" in appear, "tetovaža")
    check("red summer dress" in appear, "Dodatno")
    check("portrait of" not in appear.lower(), "skida portrait of")
    check("prijateljska" not in appear, "chat stil ne ide u izgled")
    # tetovaža se ne ponavlja
    check(appear.lower().count("small tattoo on the left shoulder") == 1, "bez duplog polja")

    term = image_gen.adult_term_for_profile(prof, appearance=appear, scene="lying on a bed")
    check(term == "adult woman, 26", f"adult s dobi: {term!r}")
    built = image_gen.build_positive_prompt(
        scene="lying on a bed, phone snapshot",
        appearance=appear,
        quality=True,
        adult_term=term,
    )
    check(built["chunks"][0].startswith("adult woman, 26"), f"head={built['chunks'][0]!r}")
    check("lying on a bed" in built["chunks"][0], "scena ostaje prva")
    check(any("long wavy brown hair" in c for c in built["chunks"]), "izgled u sljedećem chunku ili istom")
    check("child, teen" in image_gen.DEFAULT_NEGATIVE, "child/teen u negativnom")

    no_age = image_gen.adult_term_for_profile(
        {"age_vibe": "srednje 20-e, opušten vibe"},
        appearance="brown hair",
        scene="in a cafe",
    )
    check(no_age == "adult woman", f"bez eksplicitne dobi: {no_age!r}")
    check(image_gen.extract_adult_age("srednje 20-e") is None, "20-e nije dob 20")
    check(image_gen.extract_adult_age("godine 2024") is None, "godina nije dob")


def test_plan_persona_and_lora():
    print("== plan_image_generation: persona_id, LoRA + Turbo ==")
    prof = {
        "id": 9,
        "name": "Luna Marić",
        "appearance_prompt": "shoulder-length brown hair, green eyes, light freckles",
        "age_vibe": "26",
        "negative_prompt": "",
        "preferred_model": "",
        "model_type": "auto",
    }
    orig = image_gen.lora_available
    image_gen.lora_available = lambda name, folder=None: True
    try:
        result = studio.plan_image_generation(
            {
                "prompt": "lying on a bed, casual phone photo, morning light",
                "persona_id": 9,
                "appearance_extra": "gold hoop earrings",
                "model": "RealVisXL_V5.0_fp16.safetensors",
                "model_type": "sdxl",
                "turbo": True,
                "lora": "add-detail-xl.safetensors",
                "lora_strength": 0.85,
                "width": 768,
                "height": 1152,
                "seed": 11,
                "quality_prefix": True,
            },
            profile=prof,
            object_info={},
        )
    finally:
        image_gen.lora_available = orig

    check(result.get("ok") is True, f"plan ok: {result.get('error')}")
    wf = result.get("workflow") or {}
    built = result.get("built") or {}
    meta = result.get("meta") or {}
    check(wf.get("12", {}).get("inputs", {}).get("lora_name") == "add-detail-xl.safetensors", "plan: korisnička LoRA")
    check(wf.get("12", {}).get("inputs", {}).get("strength_model") == 0.85, "plan: jačina 0.85")
    check(wf.get("22", {}).get("inputs", {}).get("lora_name") == image_gen.TURBO_SDXL["lora_filename"], "plan: Turbo u lancu")
    check(meta.get("turbo") is True and meta.get("steps") == 8, f"turbo meta {meta}")
    check(meta.get("lora") == "add-detail-xl.safetensors", "meta čuva korisničku LoRA")
    head = (built.get("chunks") or [""])[0]
    check(head.startswith("adult woman, 26"), f"adult+dob u planu: {head!r}")
    check("lying on a bed" in head, "scena u prvom chunku")
    appear_text = " ".join(built.get("chunks") or [])
    check("shoulder-length brown hair" in appear_text and "gold hoop earrings" in appear_text, "profil + Dodatno")

    # stari klijent: samo persona tekst, bez persona_id
    legacy = studio.plan_image_generation(
        {
            "prompt": "sitting in a cafe",
            "persona": "portrait of a woman, auburn hair, looking at the camera",
            "model": "Realistic_Vision_V6.0_NV_B1_fp16.safetensors",
            "model_type": "sd15",
            "seed": 3,
            "quality_prefix": False,
        },
        profile=None,
        object_info={},
    )
    check(legacy.get("ok") is True, f"legacy plan: {legacy.get('error')}")
    lchunks = (legacy.get("built") or {}).get("chunks") or []
    check(lchunks and lchunks[0].startswith("adult woman"), f"legacy adult: {lchunks[:1]}")
    check(any("auburn hair" in c for c in lchunks), "legacy izgled")
    check("LoraLoader" not in {n["class_type"] for n in (legacy.get("workflow") or {}).values()}, "bez LoRA-e")

    # krea2 ignorira lora
    krea = studio.plan_image_generation(
        {
            "prompt": "on a balcony at sunset",
            "persona": "brown hair, green eyes",
            "model": "krea2_turbo_fp8_scaled.safetensors",
            "model_type": "krea2",
            "lora": "add-detail-xl.safetensors",
            "seed": 4,
            "quality_prefix": True,
        },
        profile=None,
        object_info={"CLIPLoader": {"input": {"required": {"type": [["krea2"]], "clip_name": [["qwen3vl_4b_fp8_scaled.safetensors"]]}}}},
    )
    # may fail on missing krea files
    if not krea.get("ok") and krea.get("need") == "krea2-files":
        check(True, "krea2 bez datoteka ispravno javlja need=krea2-files (ne primjenjuje LoRA)")
    else:
        types = {n["class_type"] for n in (krea.get("workflow") or {}).values()}
        check("LoraLoader" not in types, f"krea2 plan bez LoraLoader ({krea.get('error')})")


def test_parse_lora_api():
    print("== parse_lora_list / resolve_appearance ==")
    names = studio.parse_lora_list(
        {"LoraLoader": {"input": {"required": {"lora_name": [["a.safetensors", "b.safetensors"]]}}}}
    )
    check(names == ["a.safetensors", "b.safetensors"], f"object_info LoraLoader {names}")
    check(studio.parse_lora_list(["x.safetensors", "y.safetensors"]) == ["x.safetensors", "y.safetensors"], "/models/loras lista")

    prof = {"id": 1, "appearance_prompt": "green eyes, brown hair", "tattoos": "rose tattoo"}
    text = studio.resolve_appearance({"persona_id": 1, "appearance_extra": "white shirt"}, prof)
    check("green eyes" in text and "rose tattoo" in text and "white shirt" in text, f"resolve {text}")
    typed = studio.resolve_appearance({"persona": "only typed look"}, None)
    check(typed == "only typed look", f"typed fallback {typed}")


def test_ui():
    print("== Sučelje Slike: Osoba i LoRA ==")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    # Osoba je iznad scene, Izgled text field je uklonjen (ostaje samo u editoru profila)
    check('id="osoba"' in html and "for=\"osoba\">Osoba</label>" in html.replace(" ", "").replace("\n", "") or ('for="osoba"' in html and ">Osoba<" in html), "izbornik Osoba")
    check('id="appearSummary"' in html and 'id="appearText"' in html, "sažetak izgleda")
    check('id="appearExtra"' in html and "Dodatno" in html, "polje Dodatno")
    check('id="persona"' not in html, "nema starog polja #persona")
    check("Izgled (s profila, možeš privremeno dopuniti)" not in html, "nema starog Izgled polja na Slikama")
    check("Izgled (prefix za slike)" in html, "editor profila i dalje ima Izgled")

    # LoRA odmah nakon modela
    adv = html.split('id="model"', 1)[1].split("Broj slika", 1)[0]
    check('id="lora"' in adv and 'id="loraField"' in adv, "LoRA izbornik odmah nakon modela")
    check("Bez LoRA-e" in html, "opcija Bez LoRA-e")
    check('id="loraStrength"' in html and 'max="1.5"' in html and 'value="0.8"' in html, "klizač 0–1.5 zadano 0.8")
    check("ais-studio-lora-by-model" in html, "localStorage po modelu")
    check("fillLoraSelect" in html and 'loraField.hidden = arch === "krea2"' in html, "skriva se za Krea 2")
    check("persona_id" in html and "appearance_extra" in html and "lora_strength" in html, "payload šalje persona_id, Dodatno i LoRA")
    check("currentAppearance" in html and "appearanceFromProfile" in html, "izgled se sastavlja s profila")
    check("adult woman" in html, "UI i dalje računa adult prefix")
    check("child, teen" in html, "default negativni i dalje ima child, teen")
    # poredak scene
    check("Prvo ide tvoja scena, zatim izgled s profila" in html, "hint o poretku scene")


def test_helpers_exported():
    print("== Javni API ostaje ==")
    check(callable(studio.parse_lora_list) and callable(studio.lora_entries), "studio lora helpers")
    check(callable(image_gen.build_workflow) and callable(image_gen.appearance_from_profile), "image_gen helpers")


def main():
    test_detect_lora_arch()
    test_lora_workflow_chain()
    test_appearance_and_adult()
    test_plan_persona_and_lora()
    test_parse_lora_api()
    test_ui()
    test_helpers_exported()
    print()
    if FAILED:
        print(f"FAILED {FAILED}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
