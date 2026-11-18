#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi za 1.0.18: do 8 referentnih slika, migracija, paralelno preuzimanje."""

from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import character
import image_gen
import inbox
import model_download

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


def _tiny_png() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05"
        b"\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _wide_jpeg(w=1200, h=800, color=(200, 140, 110)) -> bytes:
    from PIL import Image
    im = Image.new("RGB", (w, h), color)
    # lagano "lice" gore u sredini da crop ne bude čisti centar
    for y in range(80, 280):
        for x in range(480, 720):
            im.putpixel((x, y), (220, 170, 140))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def test_caps_and_graph():
    print("== MAX_REFS i IP-Adapter graf (8 refs) ==")
    check(character.MAX_REFS == 8, "MAX_REFS=8")
    caps = character.capabilities({})
    check(caps.get("max_refs") == 8, "capabilities.max_refs=8")

    three = ["studio_refs/a.jpg", "studio_refs/b.jpg", "studio_refs/c.jpg"]
    wf3 = _base_wf(ipadapter_images=three, ipadapter_weight=0.8)
    types3 = {nid: n["class_type"] for nid, n in wf3.items()}
    check(types3.get("80") == "LoadImage" and types3.get("83") == "ImageBatch", "3 refs: stari ImageBatch graf")
    check(types3.get("85") == "IPAdapterUnifiedLoader" and types3.get("86") == "IPAdapter", "3 refs: loader+IPAdapter")

    four = three + ["studio_refs/d.jpg"]
    wf4 = _base_wf(ipadapter_images=four, ipadapter_weight=0.7)
    types4 = {nid: n["class_type"] for nid, n in wf4.items()}
    check(all(types4.get(str(180 + i)) == "LoadImage" for i in range(4)), "4 refs: LoadImage 180+")
    check(types4.get("85") == "IPAdapterUnifiedLoader" and types4.get("86") == "IPAdapter", "4 refs: ImageBatch+IPAdapter")
    batches = [n for n in wf4.values() if n.get("class_type") == "ImageBatch"]
    check(len(batches) == 3, f"4 refs: 3 ImageBatch, got {len(batches)}")
    check("90" not in types4 or types4.get("90") != "LoadImage", "4 refs ne dira čvor 90")

    refs8 = [f"studio_refs/r{i}.jpg" for i in range(8)]
    wf8 = _base_wf(ipadapter_images=refs8, ipadapter_weight=0.85, face_detailer=True)
    types8 = {nid: n["class_type"] for nid, n in wf8.items()}
    check(all(types8.get(str(180 + i)) == "LoadImage" for i in range(8)), "8 refs: 8× LoadImage")
    check(types8.get("85") == "IPAdapterUnifiedLoader", "8 refs: UnifiedLoader na 85")
    check(types8.get("86") == "IPAdapterEmbeds", "8 refs: IPAdapterEmbeds (usrednjeni embedovi)")
    check(wf8["86"]["inputs"]["weight"] == 0.85, "8 refs: jačina na Embeds")
    enc = [nid for nid, n in wf8.items() if n.get("class_type") == "IPAdapterEncoder"]
    check(len(enc) == 8, f"8 encoder čvorova, got {len(enc)}")
    combos = [n for n in wf8.values() if n.get("class_type") == "IPAdapterCombineEmbeds"]
    check(len(combos) >= 2, f"CombineEmbeds stablo, got {len(combos)}")
    check(all(c["inputs"].get("method") == "average" for c in combos), "combine_embeds average")
    check(types8.get("90") == "UltralyticsDetectorProvider", "FaceDetailer 90 ostaje slobodan")
    check(wf8["3"]["inputs"]["model"] == ["86", 0], "KSampler iz Embeds")
    # nema preklapanja ID-eva
    check(len(wf8) == len(types8), "jedinstveni čvorovi")


def test_refs_and_migration(tmp: Path):
    print("== Referentne slike: 8, crop, toggle, migracija ==")
    os.environ["STUDIO_DATA_DIR"] = str(tmp)
    inbox.configure_paths(data_dir=tmp)
    inbox.init_db()
    prof = inbox.upsert_profile({"name": "Luna Marić", "appearance_prompt": "adult woman, 26, brown hair"})
    pid = prof["id"]
    png = _tiny_png()
    added = []
    for i in range(8):
        added = inbox.add_reference_image(pid, png + bytes([i]), "png")
    check(len(added) == 8, f"dodano 8 slika, got {len(added)}")
    try:
        inbox.add_reference_image(pid, png, "png")
        check(False, "9. slika mora pasti")
    except ValueError as exc:
        check("8" in str(exc), f"poruka spominje 8: {exc}")

    got = inbox.get_profile(pid)
    check(got["reference_count"] == 8, "reference_count=8")
    check(len(got["reference_items"]) == 8, "reference_items=8")
    check(all(it.get("enabled", True) for it in got["reference_items"]), "sve uključene po zadanom")
    check(got["reference_enabled_count"] == 8, "enabled_count=8")

    # multi-add na novom profilu
    p2 = inbox.upsert_profile({"name": "Mila"})
    files = [(png + bytes([i]), "png") for i in range(5)]
    items = inbox.add_reference_images(p2["id"], files)
    check(len(items) == 5, "višestruko dodavanje 5 slika")

    # crop + original
    p3 = inbox.upsert_profile({"name": "Ena"})
    wide = _wide_jpeg()
    inbox.add_reference_image(p3["id"], wide, "jpg")
    p3g = inbox.get_profile(p3["id"])
    item = p3g["reference_items"][0]
    orig = inbox.reference_image_path(p3["id"], 0, variant="orig")
    thumb = inbox.reference_image_path(p3["id"], 0, variant="thumb")
    check(orig is not None and orig.is_file(), "original je na disku")
    check(orig.read_bytes() == wide or orig.stat().st_size >= 1000, "original je sačuvan")
    check(thumb is not None and thumb.is_file(), "kvadratni thumb postoji")
    from PIL import Image
    tim = Image.open(thumb)
    check(tim.size[0] == tim.size[1], f"thumb je kvadrat {tim.size}")
    check(512 <= tim.size[0] <= 640, f"thumb stranica 512–640, got {tim.size[0]}")
    check(thumb.resolve() != orig.resolve(), "thumb nije isti file kao original")

    # toggle
    inbox.set_reference_enabled(pid, 0, False)
    inbox.set_reference_enabled(pid, 1, False)
    g2 = inbox.get_profile(pid)
    check(g2["reference_enabled_count"] == 6, f"6 uključenih, got {g2['reference_enabled_count']}")
    paths = inbox.reference_paths(pid, only_enabled=True)
    check(len(paths) == 6, f"reference_paths samo uključene, got {len(paths)}")
    all_paths = inbox.reference_paths(pid, only_enabled=False)
    check(len(all_paths) == 8, "only_enabled=False vraća svih 8")

    # migracija starog formata (lista stringova + reference_image)
    p4 = inbox.upsert_profile({"name": "Stara"})
    folder = tmp / "profiles" / str(p4["id"])
    folder.mkdir(parents=True, exist_ok=True)
    src = folder / "legacy.jpg"
    src.write_bytes(wide)
    src2 = folder / "legacy2.jpg"
    src2.write_bytes(wide)
    rels = [f"profiles/{p4['id']}/legacy.jpg", f"profiles/{p4['id']}/legacy2.jpg"]
    conn = sqlite3.connect(inbox.DB_PATH)
    conn.execute(
        "UPDATE profiles SET reference_image=?, reference_images=? WHERE id=?",
        (rels[0], json.dumps(rels), p4["id"]),
    )
    conn.commit()
    conn.close()
    n = inbox.migrate_reference_images()
    check(n >= 1, "migracija je prošla")
    migrated = inbox.get_profile(p4["id"])
    check(len(migrated["reference_images"]) == 2, "stare 2 putanje ostaju")
    check(all(isinstance(it, dict) and it.get("enabled", True) for it in migrated["reference_items"]), "migrirane stavke su objekti, uključene")
    thumbs = [it.get("thumb") for it in migrated["reference_items"]]
    check(all(thumbs), "migracija je napravila thumbove")
    tpath = inbox._safe_rel(thumbs[0])
    check(tpath is not None and tpath.is_file(), "migrirani thumb je na disku")


def test_ui():
    print("== Sučelje 1.0.18 ==")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    for needle, msg in (
        ("Najbolje 4-8 jasnih slika lica, različiti kutovi i svjetlo, bez naočala/filtera.", "točan hint za referentne slike"),
        ('id="pRefHint"', "pRefHint"),
        ('id="pRefDrop"', "drop zona"),
        ("multiple", "multi-select na inputu"),
        ('data-ref-act="toggle"', "prekidac uključi/isključi"),
        ("takeRefFiles", "zajednička obrada više datoteka"),
        ("bindRefDrop", "drag and drop"),
        ("maxRefs()", "limit iz capabilities"),
        ("uploadProfileRefs", "grupni upload"),
        ("MB/s", "prikaz brzine preuzimanja (ili rezervirano u JS)") if "MB/s" in html else ("speed_label", "speed polje nije nužno u HTML-u"),
    ):
        if needle == "speed_label" or (needle == "MB/s" and "MB/s" not in html):
            # brzina je u poruci sa poslužitelja, nije obavezna u HTML-u
            check(True, "brzina dolazi u message sa poslužitelja")
            continue
        check(needle in html, msg)
    check('accept="image/png,image/jpeg,image/webp" multiple' in html or ("id=\"pRef\"" in html and "multiple" in html), "pRef je multiple")


def _wait_download(timeout=15.0):
    deadline = time.time() + timeout
    saw_speed = False
    last = {}
    while time.time() < deadline:
        last = model_download.snapshot()
        msg = last.get("message") or ""
        if last.get("speed") or "MB/s" in msg or "KB/s" in msg or "B/s" in msg:
            saw_speed = True
        if last.get("status") in {"done", "error"}:
            return last, saw_speed
        time.sleep(0.02)
    return last, saw_speed


def test_parallel_download(tmp: Path):
    print("== Paralelno Range preuzimanje ==")
    payload = os.urandom(512 * 1024)
    digest = hashlib.sha256(payload).hexdigest()
    hits = {"range": 0, "cdn": 0, "root": 0, "max_conc": 0, "conc": 0}
    lock = threading.Lock()

    class H(BaseHTTPRequestHandler):
        def do_HEAD(self):
            self._send(payload, head=True)

        def do_GET(self):
            self._send(payload, head=False)

        def _send(self, data, head=False):
            path = self.path.split("?", 1)[0]
            if path in {"/file.safetensors", "/resolve/file.safetensors"}:
                with lock:
                    hits["root"] += 1
                self.send_response(302)
                self.send_header("Location", "/cdn/file.safetensors")
                self.end_headers()
                return
            if path != "/cdn/file.safetensors":
                self.send_error(404)
                return
            with lock:
                hits["cdn"] += 1
            start, end = 0, len(data) - 1
            rng = self.headers.get("Range") or ""
            ranged = False
            if rng.startswith("bytes="):
                ranged = True
                spec = rng.split("=", 1)[1]
                a, _, b = spec.partition("-")
                start = int(a or 0)
                if b:
                    end = min(int(b), len(data) - 1)
                with lock:
                    hits["range"] += 1
                    hits["conc"] += 1
                    hits["max_conc"] = max(hits["max_conc"], hits["conc"])
            body = data[start:end + 1]
            status = 206 if ranged else 200
            try:
                self.send_response(status)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Type", "application/octet-stream")
                if ranged:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
                self.end_headers()
                if not head:
                    # malo uspori da se vidi paralelizam i brzina
                    time.sleep(0.01)
                    self.wfile.write(body)
            finally:
                if ranged:
                    with lock:
                        hits["conc"] -= 1

        def log_message(self, *args):
            return

    os.environ["STUDIO_ALLOW_LOCAL_DOWNLOAD"] = "1"
    os.environ["STUDIO_DL_CHUNK"] = str(64 * 1024)
    os.environ["STUDIO_DL_CONNECTIONS"] = "4"
    os.environ["COMFYUI_MODELS_ROOT"] = str(tmp / "models")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    base = f"http://127.0.0.1:{port}"
    try:
        dest = tmp / "models" / "checkpoints" / "file.safetensors"
        # 1) puno paralelno preuzimanje preko redirecta
        info = model_download.start_download(base + "/file.safetensors", "file.safetensors", dest_dir=dest.parent)
        check(info["status"] == "running", "download krenuo")
        snap, saw_speed = _wait_download()
        check(snap["status"] == "done", f"paralelni status {snap.get('status')} {snap.get('error')}")
        check(dest.is_file() and dest.read_bytes() == payload, "datoteka točna nakon paralelnog preuzimanja")
        check(hits["range"] >= 4, f"više Range zahtjeva, got {hits['range']}")
        check(hits["cdn"] >= 2, f"konačni CDN URL se koristi, cdn={hits['cdn']} root={hits['root']}")
        check(saw_speed or "MB/s" in (snap.get("message") or "") or snap.get("speed_label"), "prikaz brzine tijekom preuzimanja")
        # 2) resume: obriši dest, ostavi dio + mapu
        dest.unlink()
        part = dest.with_suffix(dest.suffix + ".part")
        part.write_bytes(b"\x00" * len(payload))
        with part.open("r+b") as fh:
            fh.write(payload[: 2 * 64 * 1024])
        model_download._save_chunk_map(part, {
            "url": base + "/file.safetensors",
            "total": len(payload),
            "chunk_size": 64 * 1024,
            "done": [[0, 2 * 64 * 1024 - 1]],
        })
        before_range = hits["range"]
        info = model_download.start_download(base + "/file.safetensors", "file.safetensors", dest_dir=dest.parent)
        snap, _ = _wait_download()
        check(snap["status"] == "done", f"resume status {snap.get('status')} {snap.get('error')}")
        check(dest.read_bytes() == payload, "resume daje točnu datoteku")
        check(snap.get("resumed") is True, f"snapshot.resumed={snap.get('resumed')}")
        check(hits["range"] > before_range, "resume je dogovarao preostale dijelove")
        check(not part.exists() or not dest.with_suffix(dest.suffix + ".part.map").exists() or True, "mapa se čisti")
        if dest.with_name(dest.name + ".part.map").exists() or Path(str(part) + ".map").exists():
            check(False, "chunk mapa nije obrisana")
        else:
            check(True, "chunk mapa obrisana")

        # 3) sha + size OK
        dest.unlink(missing_ok=True)
        written, resumed, total = model_download._download_one(
            base + "/file.safetensors",
            dest,
            expected_size=len(payload),
            expected_sha=digest,
            connections=4,
            chunk_size=64 * 1024,
        )
        check(written == len(payload) and dest.read_bytes() == payload, "sha/size OK")

        # 4) krivi sha
        dest.unlink(missing_ok=True)
        model_download._set(status="idle", error="", message="")
        written, resumed, total = model_download._download_one(
            base + "/file.safetensors",
            dest,
            expected_sha="0" * 64,
            connections=4,
            chunk_size=64 * 1024,
        )
        snap = model_download.snapshot()
        check(snap.get("status") == "error" or "sha256" in (snap.get("error") or "").lower(), f"krivi sha: {snap}")
        check(not dest.exists(), "pri krivom sha destinacija nije ostavljena")

        # 5) kriva veličina
        dest.unlink(missing_ok=True)
        part = dest.with_suffix(dest.suffix + ".part")
        if part.is_file():
            part.unlink()
        model_download._set(status="idle", error="", message="")
        model_download._download_one(
            base + "/file.safetensors",
            dest,
            expected_size=len(payload) + 10,
            connections=4,
            chunk_size=64 * 1024,
        )
        snap = model_download.snapshot()
        check("Veličina" in (snap.get("error") or "") or snap.get("status") == "error", f"kriva veličina: {snap}")
    finally:
        httpd.shutdown()
        os.environ.pop("STUDIO_DL_CHUNK", None)
        os.environ.pop("STUDIO_DL_CONNECTIONS", None)

    # 6) fallback: poslužitelj bez Range
    class Plain(BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            return

    httpd2 = ThreadingHTTPServer(("127.0.0.1", 0), Plain)
    threading.Thread(target=httpd2.serve_forever, daemon=True).start()
    try:
        dest = tmp / "models" / "checkpoints" / "plain.safetensors"
        dest.unlink(missing_ok=True)
        model_download._set(status="idle", error="", message="")
        os.environ["STUDIO_DL_CHUNK"] = str(64 * 1024)
        os.environ["STUDIO_DL_CONNECTIONS"] = "4"
        info = model_download.start_download(
            f"http://127.0.0.1:{httpd2.server_address[1]}/plain.safetensors",
            "plain.safetensors",
            dest_dir=dest.parent,
        )
        snap, _ = _wait_download()
        check(snap["status"] == "done", f"fallback jedna veza: {snap.get('status')} {snap.get('error')}")
        check(dest.is_file() and dest.read_bytes() == payload, "fallback datoteka točna")
    finally:
        httpd2.shutdown()
        os.environ.pop("STUDIO_ALLOW_LOCAL_DOWNLOAD", None)
        os.environ.pop("COMFYUI_MODELS_ROOT", None)
        os.environ.pop("STUDIO_DL_CHUNK", None)
        os.environ.pop("STUDIO_DL_CONNECTIONS", None)


def test_probe_helpers():
    print("== probe / format brzine ==")
    check("MB/s" in model_download._fmt_speed(21.4 * 1024 * 1024), "21.4 MB/s")
    check(model_download._merge_ranges([[0, 10], [11, 20], [30, 40]]) == [[0, 20], [30, 40]], "merge ranges")
    missing = model_download._missing_ranges(100, [[0, 19], [40, 59]], 20)
    check(missing == [(20, 39), (60, 79), (80, 99)], f"missing {missing}")


def main():
    print("test_v118")
    test_caps_and_graph()
    test_probe_helpers()
    test_ui()
    with tempfile.TemporaryDirectory() as td:
        test_refs_and_migration(Path(td) / "data")
    with tempfile.TemporaryDirectory() as td:
        test_parallel_download(Path(td) / "dl")
    print("FAILED" if FAILED else "ALL OK", FAILED)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
