#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""py_compile + simulacija updatea protiv lokalnog mock GitHub API-ja."""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import traceback
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import inbox  # noqa: E402
import updater  # noqa: E402

TOKEN = "ghs_test_secret_token_DO_NOT_LOG_xyz"
failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if cond:
        print("  OK ", msg)
    else:
        print("  FAIL", msg)
        failures.append(msg)


def py_compile_all() -> None:
    print("== py_compile ==")
    import py_compile
    files = [
        ROOT / "studio.py",
        ROOT / "inbox.py",
        ROOT / "updater.py",
        ROOT / "launcher.py",
        ROOT / "video.py",
        ROOT / "tools" / "make_icon.py",
        ROOT / "tools" / "test_updater.py",
        ROOT / "apply_helper.py",
        ROOT / "applog.py",
        ROOT / "comfy_ws.py",
        ROOT / "comfy_launch.py",
        ROOT / "image_gen.py",
        ROOT / "model_download.py",
    ]
    for f in files:
        py_compile.compile(str(f), doraise=True)
        print("  OK ", f.name)


def make_app_tree(app: Path, version: str, extra: dict[str, str] | None = None) -> None:
    app.mkdir(parents=True, exist_ok=True)
    (app / "studio.py").write_text(
        f"# studio stub {version}\nVERSION = '{version}'\n", encoding="utf-8"
    )
    (app / "version.json").write_text(
        json.dumps({"version": version, "name": "AI Influencer Studio"}, indent=2),
        encoding="utf-8",
    )
    (app / "index.html").write_text(f"<html>v{version}</html>", encoding="utf-8")
    (app / f"marker-{version}.txt").write_text(version, encoding="utf-8")
    if extra:
        for rel, content in extra.items():
            dest = app / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")


def zip_tree(src: Path, dest: Path, wrap_root: str | None = "simple-studio") -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in src.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(src).as_posix()
            arc = f"{wrap_root}/{rel}" if wrap_root else rel
            zf.write(p, arc)
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    dest.with_suffix(dest.suffix + ".sha256").write_text(
        f"{digest}  {dest.name}\n", encoding="ascii"
    )
    return digest


class MockGitHub(http.server.BaseHTTPRequestHandler):
    """Minimalan GitHub Releases API. zip/sha se mijenjaju preko server.payloads."""

    def log_message(self, fmt, *args):
        return  # tišina

    def _record(self):
        hits = getattr(self.server, "hits", None)
        if hits is not None:
            hits.append(self.path)

    def _auth_ok(self) -> bool:
        need = getattr(self.server, "require_token", "")
        if not need:
            return True
        hdr = self.headers.get("Authorization") or ""
        return hdr in {f"Bearer {need}", f"token {need}"}

    def do_GET(self):
        self._record()
        if not self._auth_ok():
            self.send_error(401, "need token")
            return
        payloads = self.server.payloads  # type: ignore[attr-defined]
        if self.path.rstrip("/").endswith("/releases/latest") or self.path.endswith("/releases/latest"):
            body = json.dumps(payloads["release"]).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        assets = payloads.get("assets") or {}
        # /download/studio.zip or /repos/.../assets/1
        key = None
        if self.path.endswith("studio.zip") or self.path.endswith("/assets/1"):
            key = "zip"
        elif self.path.endswith("studio.zip.sha256") or self.path.endswith("/assets/2"):
            key = "sha"
        if key and key in assets:
            data = assets[key]
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(404, self.path)


def start_mock(payloads: dict, require_token: str = "") -> tuple[http.server.HTTPServer, str]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()
    sock.close()
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), MockGitHub)
    httpd.payloads = payloads
    httpd.require_token = require_token
    httpd.hits = []
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, f"http://127.0.0.1:{port}"


def release_json(base: str, tag: str, notes: str, sha: bool = True) -> dict:
    assets = [
        {
            "name": "studio.zip",
            "url": f"{base}/repos/sven/studio/assets/1",
            "browser_download_url": f"{base}/download/studio.zip",
        }
    ]
    if sha:
        assets.append(
            {
                "name": "studio.zip.sha256",
                "url": f"{base}/repos/sven/studio/assets/2",
                "browser_download_url": f"{base}/download/studio.zip.sha256",
            }
        )
    return {
        "tag_name": tag,
        "name": f"Studio {tag}",
        "body": notes,
        "published_at": "2026-11-18T00:00:00Z",
        "assets": assets,
    }


def test_semver() -> None:
    print("== semver ==")
    check(updater.parse_version("v1.2.3") == (1, 2, 3), "parse v1.2.3")
    check(updater.parse_version("2.0") == (2, 0, 0), "parse 2.0")
    check(updater.is_newer("1.0.1", "1.0.0"), "1.0.1 > 1.0.0")
    check(not updater.is_newer("1.0.0", "1.0.0"), "isto nije novije")
    check(not updater.is_newer("1.0.0", "1.2.0"), "starije nije novije")


def test_migrate(tmp: Path) -> None:
    print("== migracija ==")
    app = tmp / "legacy-app"
    dest = tmp / "legacy-data"
    app.mkdir()
    (app / ".env").write_text("XAI_API_KEY=oldkey\n", encoding="utf-8")
    (app / "data").mkdir()
    (app / "data" / "studio.db").write_text("db", encoding="utf-8")
    (app / "data" / "profiles" / "1").mkdir(parents=True)
    (app / "data" / "profiles" / "1" / "pic.txt").write_text("img", encoding="utf-8")
    dest.mkdir(exist_ok=True)
    (dest / ".env").write_text("XAI_API_KEY=KEEP\n", encoding="utf-8")  # ne prepisuj
    inbox.migrate_legacy_data(app, dest)
    check((dest / ".env").read_text(encoding="utf-8") == "XAI_API_KEY=KEEP\n", "postojeći .env se ne prepisuje")
    check((dest / "studio.db").read_text(encoding="utf-8") == "db", "studio.db preseljen")
    check((dest / "profiles" / "1" / "pic.txt").read_text(encoding="utf-8") == "img", "profili preseljeni")
    # infer
    inst = tmp / "AIInfluencerStudio" / "app"
    inst.mkdir(parents=True)
    d = inbox.infer_data_dir(inst)
    check(d == inst.parent / "data", "infer_data_dir za .../AIInfluencerStudio/app")


def test_successful_update(tmp: Path) -> None:
    print("== uspješan update (podaci netaknuti) ==")
    inst = tmp / "AIInfluencerStudio"
    app = inst / "app"
    data = inst / "data"
    make_app_tree(app, "1.0.0")
    data.mkdir(parents=True)
    (data / ".env").write_text(f"GITHUB_TOKEN={TOKEN}\nXAI_API_KEY=keep-me\n", encoding="utf-8")
    (data / "studio.db").write_text("USER-DB-BYTES", encoding="utf-8")
    (data / "profiles" / "1").mkdir(parents=True)
    (data / "profiles" / "1" / "ref.txt").write_text("ref", encoding="utf-8")
    (data / "uploads" / "a.txt").parent.mkdir(parents=True, exist_ok=True)
    (data / "uploads" / "a.txt").write_text("up", encoding="utf-8")

    new_src = tmp / "new-src"
    make_app_tree(
        new_src,
        "1.1.0",
        extra={
            "data/.env": "GITHUB_TOKEN=HACKED\n",
            "data/studio.db": "EVIL-DB",
            ".env": "SHOULD-NOT-LAND",
        },
    )
    zpath = tmp / "payloads" / "studio.zip"
    digest = zip_tree(new_src, zpath)

    # placeholder server then fill release with actual base
    payloads = {"release": {}, "assets": {"zip": zpath.read_bytes(), "sha": f"{digest}  studio.zip\n".encode()}}
    httpd, base = start_mock(payloads, require_token=TOKEN)
    try:
        payloads["release"] = release_json(base, "v1.1.0", "Nove prečace i updater.", sha=True)
        (data / "update.json").write_text(
            json.dumps({
                "source": "github",
                "owner": "sven",
                "repo": "studio",
                "asset": "studio.zip",
                "checksum_asset": "studio.zip.sha256",
                "api_base": base,
                "private": True,
            }, indent=2),
            encoding="utf-8",
        )
        os.environ["GITHUB_TOKEN"] = TOKEN
        result = updater.perform_update(app, data)
        check(result.get("applied") is True, "applied=True")
        check(result.get("updated_to") == "1.1.0", f"updated_to 1.1.0 ({result.get('updated_to')})")
        check((app / "version.json").read_text(encoding="utf-8").find("1.1.0") >= 0, "app version.json 1.1.0")
        check((app / "marker-1.1.0.txt").is_file(), "nova marker datoteka")
        check(not (app / "marker-1.0.0.txt").is_file(), "stari marker uklonjen")
        check((data / ".env").read_text(encoding="utf-8") == f"GITHUB_TOKEN={TOKEN}\nXAI_API_KEY=keep-me\n", "data/.env netaknut")
        check((data / "studio.db").read_text(encoding="utf-8") == "USER-DB-BYTES", "studio.db netaknut")
        check((data / "profiles" / "1" / "ref.txt").read_text(encoding="utf-8") == "ref", "profili netaknuti")
        check((data / "uploads" / "a.txt").read_text(encoding="utf-8") == "up", "uploads netaknuti")
        check(not (app / ".env").exists(), "zip .env nije raspakiran u app")
        check(not (app / "data").exists() or (app / "data" / "studio.db").read_text(encoding="utf-8") != "EVIL-DB", "zip data nije pregazio korisničke podatke")
        # token se ne smije pojaviti u rezultatu
        dumped = json.dumps(result)
        check(TOKEN not in dumped, "GITHUB_TOKEN nije u rezultatu updatea")
        res_file = data / "update-result.json"
        if res_file.is_file():
            check(TOKEN not in res_file.read_text(encoding="utf-8"), "token nije u update-result.json")
        check("Ažurirano na verziju 1.1.0" in (result.get("message") or ""), "poruka Ažurirano na verziju")
        check("Nove prečace" in (result.get("changelog") or ""), "changelog iz release notes")
        hits = list(getattr(httpd, "hits", []))
        check(any("/assets/1" in h for h in hits), f"zip preuzet preko API asset URL-a {hits}")
        check(any("/assets/2" in h for h in hits), "sha preuzet preko API asset URL-a")
        check(not any("/download/" in h for h in hits), "nije korišten browser_download_url")
    finally:
        httpd.shutdown()
        os.environ.pop("GITHUB_TOKEN", None)


def test_corrupt_and_bad_sha(tmp: Path) -> None:
    print("== rollback / nevaljani zip ==")
    inst = tmp / "badcase"
    app = inst / "app"
    data = inst / "data"
    make_app_tree(app, "1.0.0")
    (app / "keep.txt").write_text("old-app", encoding="utf-8")
    data.mkdir(parents=True)
    (data / ".env").write_text("XAI_API_KEY=keep-me\n", encoding="utf-8")
    (data / "studio.db").write_text("USER-DB-BYTES", encoding="utf-8")

    # 1) corrupt bytes as zip
    payloads = {"release": {}, "assets": {"zip": b"this is not a zip at all", "sha": b""}}
    httpd, base = start_mock(payloads, require_token="")
    try:
        # no sha so verify_zip should fail
        payloads["release"] = release_json(base, "v9.9.9", "corrupt", sha=False)
        (data / "update.json").write_text(
            json.dumps({
                "owner": "sven", "repo": "studio", "api_base": base,
                "asset": "studio.zip", "checksum_asset": "studio.zip.sha256",
                "private": False,
            }),
            encoding="utf-8",
        )
        raised = False
        try:
            updater.perform_update(app, data)
        except Exception as exc:
            raised = True
            check("ZIP" in str(exc) or "zip" in str(exc).lower() or "valjan" in str(exc).lower(), f"greška spominje ZIP ({exc})")
        check(raised, "corrupt zip podiže iznimku")
        check((app / "version.json").read_text(encoding="utf-8").find("1.0.0") >= 0, "app ostaje 1.0.0 nakon corrupt zip")
        check((app / "keep.txt").read_text(encoding="utf-8") == "old-app", "stare app datoteke ostaju")
        check((data / "studio.db").read_text(encoding="utf-8") == "USER-DB-BYTES", "data netaknut nakon corrupt zip")
        check((data / ".env").read_text(encoding="utf-8") == "XAI_API_KEY=keep-me\n", ".env netaknut nakon corrupt zip")
    finally:
        httpd.shutdown()

    # 2) valjani zip, krivi sha256
    print("== krivi sha256 ==")
    new_src = tmp / "new-sha"
    make_app_tree(new_src, "1.2.0")
    zpath = tmp / "payloads2" / "studio.zip"
    zip_tree(new_src, zpath)
    bad_sha = ("0" * 64) + "  studio.zip\n"
    payloads = {"release": {}, "assets": {"zip": zpath.read_bytes(), "sha": bad_sha.encode()}}
    httpd, base = start_mock(payloads)
    try:
        payloads["release"] = release_json(base, "v1.2.0", "sha fail", sha=True)
        (data / "update.json").write_text(
            json.dumps({"owner": "sven", "repo": "studio", "api_base": base, "private": False}),
            encoding="utf-8",
        )
        raised = False
        try:
            updater.perform_update(app, data)
        except Exception as exc:
            raised = True
            check("sha256" in str(exc).lower(), f"greška spominje sha256 ({exc})")
        check(raised, "krivi sha podiže iznimku")
        check((app / "version.json").read_text(encoding="utf-8").find("1.0.0") >= 0, "app ostaje 1.0.0 nakon krivog sha")
        check((data / "studio.db").read_text(encoding="utf-8") == "USER-DB-BYTES", "data netaknut nakon krivog sha")
    finally:
        httpd.shutdown()

    # 3) rollback mid-apply (os.replace pada na jednoj novoj datoteci)
    print("== rollback ako zamjena datoteke padne usred primjene ==")
    new_src = tmp / "new-roll"
    make_app_tree(new_src, "2.0.0")
    zpath = tmp / "payloads3" / "studio.zip"
    zip_tree(new_src, zpath, wrap_root=None)
    orig_replace = os.replace

    def flaky(a, b):
        if Path(b).name == "marker-2.0.0.txt":
            raise PermissionError("simulated file lock mid-apply")
        return orig_replace(a, b)

    os.replace = flaky  # type: ignore[assignment]
    try:
        raised = False
        try:
            updater.apply_zip(zpath, app, inst / "backup", data_dir=data)
        except Exception as exc:
            raised = True
            check("simulated" in str(exc) or "zamijeniti" in str(exc), f"očekivana simulirana greška ({exc})")
        check(raised, "apply_zip pada kad je datoteka zaključana")
        check((app / "version.json").is_file(), "app dir postoji nakon rollbacka")
        check((app / "version.json").read_text(encoding="utf-8").find("1.0.0") >= 0, "rollback vratio 1.0.0")
        check((app / "keep.txt").is_file() and (app / "keep.txt").read_text(encoding="utf-8") == "old-app", "rollback vratio stare datoteke")
        check((data / "studio.db").read_text(encoding="utf-8") == "USER-DB-BYTES", "data netaknut nakon rollbacka")
        check(not (app / "marker-2.0.0.txt").is_file(), "djelomično nova datoteka nije ostala")
    finally:
        os.replace = orig_replace  # type: ignore[assignment]


def test_token_redaction() -> None:
    print("== redakcija tokena ==")
    msg = updater._safe_err(f"HTTP 401 za https://example?token={TOKEN}: bad {TOKEN}", TOKEN)
    check(TOKEN not in msg, "token nije u _safe_err poruci")
    check("ghs" in msg or "…" in msg or "****" in msg, "ima redaktirani oblik")


def test_paths_env(tmp: Path) -> None:
    print("== STUDIO_DATA_DIR ==")
    app = tmp / "portable"
    data = tmp / "elsewhere-data"
    make_app_tree(app, "1.0.0")
    os.environ["STUDIO_APP_DIR"] = str(app)
    os.environ["STUDIO_DATA_DIR"] = str(data)
    try:
        d = inbox.configure_paths()
        check(d.resolve() == data.resolve(), "configure_paths poštuje STUDIO_DATA_DIR")
        check(inbox.ENV_PATH == data / ".env", "ENV_PATH u data/.env")
        check((data / "profiles").is_dir(), "profiles dir stvoren")
    finally:
        os.environ.pop("STUDIO_APP_DIR", None)
        os.environ.pop("STUDIO_DATA_DIR", None)
        inbox._PATHS_READY = False


def test_default_source_and_private_token(tmp: Path) -> None:
    print("== zadani izvor i obavezan token ==")
    cfg = updater.load_update_config(tmp / "no-file")
    check(cfg.get("owner") == "Spinojpg", "default owner Spinojpg")
    check(cfg.get("repo") == "ai-influencer-studio", "default repo ai-influencer-studio")
    check(cfg.get("private") is True, "default private=True")
    path = updater.write_default_update_config(tmp / "cfg")
    written = json.loads(path.read_text(encoding="utf-8"))
    check(written.get("owner") == "Spinojpg", "write_default owner")
    check(written.get("repo") == "ai-influencer-studio", "write_default repo")

    app = tmp / "app"
    data = tmp / "data"
    make_app_tree(app, "1.0.0")
    data.mkdir()
    (data / "update.json").write_text(
        json.dumps({
            "owner": "Spinojpg",
            "repo": "ai-influencer-studio",
            "private": True,
            "api_base": "http://127.0.0.1:9",
        }),
        encoding="utf-8",
    )
    # bez tokena, bez HTTP poziva
    os.environ.pop("GITHUB_TOKEN", None)
    os.environ.pop("GH_TOKEN", None)
    raised = False
    try:
        updater.check_for_update(app, data, token="")
    except Exception as exc:
        raised = True
        msg = str(exc)
        check("GITHUB_TOKEN" in msg or "token" in msg.lower(), f"poruka spominje token ({exc})")
        check("privatni" in msg.lower() or "Privatni" in msg or "privatnog" in msg.lower() or "privatni" in msg, "poruka spominje privatni repo")
        check("ghs_" not in msg, "nema curenja u poruci")
    check(raised, "privatni repo bez tokena podiže iznimku")

    # token samo u data/.env, ne u os.environ
    (data / ".env").write_text(f"GITHUB_TOKEN={TOKEN}\n", encoding="utf-8")
    tok = updater.github_token(data_dir=data)
    check(tok == TOKEN, "github_token cita data/.env")
    check(TOKEN not in f"log {updater._safe_err('x', tok)}".replace(updater._redact(TOKEN), ""), "redakcija i dalje radi")


def test_rename_blocked_still_applies(tmp: Path) -> None:
    print("== in-place apply kad preimenovanje app mape padne (Windows cwd) ==")
    app = tmp / "inst" / "app"
    data = tmp / "inst" / "data"
    make_app_tree(app, "1.0.1")
    data.mkdir(parents=True)
    (data / "user.txt").write_text("keep", encoding="utf-8")
    new_src = tmp / "new"
    make_app_tree(new_src, "1.0.3", extra={"novo.py": "print('ok')\n"})
    zpath = tmp / "studio.zip"
    zip_tree(new_src, zpath)

    real_rename = Path.rename
    blocked = {"count": 0}

    def guarded(self, target):
        if self.resolve() == app.resolve() or Path(target).resolve() == app.resolve():
            blocked["count"] += 1
            raise PermissionError(13, "simulated Windows cwd lock")
        return real_rename(self, target)

    Path.rename = guarded  # type: ignore[method-assign]
    try:
        backup = updater.apply_zip(
            zpath, app, tmp / "backup", expected_version="1.0.3", data_dir=data
        )
        ver = json.loads((app / "version.json").read_text(encoding="utf-8"))["version"]
        check(ver == "1.0.3", f"version.json na disku je 1.0.3 ({ver})")
        check((app / "novo.py").is_file(), "nova datoteka je tu")
        check(not (app / "marker-1.0.1.txt").is_file(), "stari marker je uklonjen")
        check((data / "user.txt").read_text(encoding="utf-8") == "keep", "data nije dirana")
        check(app.is_dir() and app.resolve() == (tmp / "inst" / "app").resolve(), "app_dir nije preimenovan")
        check(backup.is_dir(), "backup postoji")
        log = data / "logs" / "updater.log"
        check(log.is_file() and "apply_zip OK" in log.read_text(encoding="utf-8"), "korak je u updater.log")
        # apply_zip ne smije ovisiti o rename mape: ako je rename bio pozvan, ostao je u except
        check(True, "apply nije pao usprkos zabranjenom renameu app mape")
    finally:
        Path.rename = real_rename  # type: ignore[method-assign]


def test_expected_version_rollback(tmp: Path) -> None:
    print("== rollback kad version.json ne odgovara expected ==")
    app = tmp / "app"
    data = tmp / "data"
    make_app_tree(app, "1.0.1")
    (app / "keep-old.py").write_text("old", encoding="utf-8")
    data.mkdir(parents=True)
    new_src = tmp / "new"
    make_app_tree(new_src, "9.9.9")
    zpath = tmp / "studio.zip"
    zip_tree(new_src, zpath)
    raised = False
    try:
        updater.apply_zip(zpath, app, tmp / "backup", expected_version="1.0.3", data_dir=data)
    except RuntimeError as exc:
        raised = True
        check("očekivano" in str(exc) or "ocekivano" in str(exc).lower() or "1.0.3" in str(exc), f"poruka: {exc}")
    check(raised, "apply_zip diže grešku pri krivoj verziji")
    ver = json.loads((app / "version.json").read_text(encoding="utf-8"))["version"]
    check(ver == "1.0.1", f"rollback vratio 1.0.1 ({ver})")
    check((app / "keep-old.py").is_file(), "stara datoteka vraćena")
    check(not (app / "marker-9.9.9.txt").is_file(), "nova verzija nije ostala")


def test_replace_retries(tmp: Path) -> None:
    print("== os.replace retry na PermissionError ==")
    tmp.mkdir(parents=True, exist_ok=True)
    src = tmp / "src.txt"
    dest = tmp / "dest.txt"
    src.write_text("NEW", encoding="utf-8")
    dest.write_text("OLD", encoding="utf-8")
    real = os.replace
    hits = {"n": 0}

    def flaky(a, b):
        hits["n"] += 1
        if hits["n"] <= 2:
            raise PermissionError(32, "simulated lock")
        return real(a, b)

    os.replace = flaky  # type: ignore[assignment]
    try:
        updater.replace_file(src, dest, retries=8, delay=0.01)
        check(dest.read_text(encoding="utf-8") == "NEW", "datoteka zamijenjena nakon retryja")
        check(hits["n"] == 3, f"dva neuspjeha pa uspjeh ({hits['n']})")
    finally:
        os.replace = real  # type: ignore[assignment]


def test_apply_helper_process(tmp: Path) -> None:
    print("== apply_helper iz data mape primijeni pending zip ==")
    inst = tmp / "AIInfluencerStudio"
    app = inst / "app"
    data = inst / "data"
    make_app_tree(app, "1.0.1", extra={"launcher.py": "open('launched.txt','w').write('1')\n"})
    data.mkdir(parents=True)
    new_src = tmp / "new"
    make_app_tree(new_src, "1.0.3")
    pending = data / "pending-update"
    pending.mkdir(parents=True)
    zpath = pending / "studio.zip"
    zip_tree(new_src, zpath)
    (pending / "meta.json").write_text(
        json.dumps({"zip_path": str(zpath), "latest": "1.0.3", "notes": "ok"}),
        encoding="utf-8",
    )
    os.environ["STUDIO_APP_DIR"] = str(app)
    os.environ["STUDIO_DATA_DIR"] = str(data)
    os.environ.pop("STUDIO_WAIT_PIDS", None)
    here = Path.cwd()
    import apply_helper

    # ne pokreći pravi launcher
    apply_helper.APP_DIR = app
    apply_helper.DATA_DIR = data
    started = {"n": 0}
    apply_helper.start_app = lambda: started.__setitem__("n", started["n"] + 1)
    rc = apply_helper.main()
    check(rc == 0, f"helper exit 0 ({rc})")
    ver = json.loads((app / "version.json").read_text(encoding="utf-8"))["version"]
    check(ver == "1.0.3", f"helper je zapisao 1.0.3 ({ver})")
    result = json.loads((data / "update-result.json").read_text(encoding="utf-8"))
    check(result.get("applied") is True and result.get("updated_to") == "1.0.3", "update-result istinit")
    check(started["n"] == 1, "helper je pokrenuo aplikaciju nakon uspjeha")
    check(not pending.exists() or not (pending / "studio.zip").is_file(), "pending je očišćen")
    os.chdir(here)


def test_make_release(tmp: Path) -> None:
    print("== make_release.sh (u kopiji) ==")
    orig_before = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))["version"]
    copy = tmp / "relsrc"
    shutil.copytree(
        ROOT,
        copy,
        ignore=shutil.ignore_patterns("__pycache__", "data", "dist", ".git", "*.pyc"),
    )
    script = copy / "tools" / "make_release.sh"
    import subprocess
    r = subprocess.run(
        ["bash", str(script), "1.0.1", "Testno izdanje iz automatskog testa."],
        cwd=str(copy),
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        check(False, f"make_release.sh exit {r.returncode}")
        return
    z = copy / "dist" / "studio.zip"
    sha = copy / "dist" / "studio.zip.sha256"
    check(z.is_file(), "dist/studio.zip postoji")
    check(sha.is_file(), "dist/studio.zip.sha256 postoji")
    digest = sha.read_text(encoding="utf-8").split()[0]
    check(digest == hashlib.sha256(z.read_bytes()).hexdigest(), "sha256 se podudara")
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
    check(any(n.endswith("studio.py") for n in names), "zip sadrži studio.py")
    check(any(n.endswith("version.json") for n in names), "zip sadrži version.json")
    check(not any("/data/" in n or n.endswith(".env") for n in names), "zip nema data/ ni .env")
    ver = json.loads((copy / "version.json").read_text(encoding="utf-8"))["version"]
    check(ver == "1.0.1", f"kopija bumpana na 1.0.1 ({ver})")
    # original tree remains 1.0.0
    orig = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))["version"]
    check(orig == orig_before, f"izvorni version.json ostaje {orig_before} ({orig})")
    check(any(n.endswith("apply_helper.py") for n in names), "zip sadrži apply_helper.py")
    check(any(n.endswith("popravi_update.bat") for n in names), "zip sadrži popravi_update.bat")


def main() -> int:
    py_compile_all()
    test_semver()
    test_token_redaction()
    with tempfile.TemporaryDirectory(prefix="studio-upd-") as td:
        tmp = Path(td)
        try:
            test_migrate(tmp)
            test_paths_env(tmp)
            test_default_source_and_private_token(tmp / "defaults")
            test_successful_update(tmp / "ok")
            test_corrupt_and_bad_sha(tmp / "bad")
            test_rename_blocked_still_applies(tmp / "winlock")
            test_expected_version_rollback(tmp / "rollback")
            test_replace_retries(tmp / "retry")
            test_apply_helper_process(tmp / "helper")
            test_make_release(tmp)
        except Exception:
            traceback.print_exc()
            failures.append("neuhvaćena iznimka")
    print()
    if failures:
        print(f"NEUSPJEH: {len(failures)} test(ova)")
        for f in failures:
            print(" -", f)
        return 1
    print("SVI TESTOVI PROŠLI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
