#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Provjera i primjena ažuriranja s GitHub Releases. Stdlib only."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sys
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

DEFAULT_ASSET = "studio.zip"
DEFAULT_SHA_ASSET = "studio.zip.sha256"


def _redact(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return value[:3] + "…" + value[-2:]


def _safe_err(text: str, token: str = "") -> str:
    if token:
        text = text.replace(token, _redact(token))
    return text


def parse_version(tag: str) -> tuple[int, int, int]:
    raw = (tag or "").strip()
    if raw.lower().startswith("v") and re.match(r"^v\d", raw, re.I):
        raw = raw[1:]
    parts = re.split(r"[^\d]+", raw)
    nums = [int(p) for p in parts if p != ""][:3]
    while len(nums) < 3:
        nums.append(0)
    return nums[0], nums[1], nums[2]


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def load_version(app_dir: Path) -> dict:
    path = Path(app_dir) / "version.json"
    if not path.is_file():
        return {"version": "0.0.0", "name": "AI Influencer Studio"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": "0.0.0", "name": "AI Influencer Studio"}
    if not isinstance(data, dict):
        return {"version": "0.0.0", "name": "AI Influencer Studio"}
    data.setdefault("version", "0.0.0")
    return data


def load_update_config(data_dir: Path) -> dict:
    path = Path(data_dir) / "update.json"
    default = {
        "source": "github",
        "owner": "Spinojpg",
        "repo": "ai-influencer-studio",
        "private": True,
        "asset": DEFAULT_ASSET,
        "checksum_asset": DEFAULT_SHA_ASSET,
        "api_base": "https://api.github.com",
    }
    if not path.is_file():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    if not isinstance(data, dict):
        return default
    out = dict(default)
    out.update({k: v for k, v in data.items() if v is not None})
    return out


def write_default_update_config(data_dir: Path) -> Path:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "update.json"
    if not path.is_file():
        path.write_text(
            json.dumps(load_update_config(data_dir), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return path


def _token_from_env_file(path: Path) -> str:
    """Pročitaj GITHUB_TOKEN iz data/.env bez ispisa vrijednosti."""
    path = Path(path)
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in {"'", '"'}:
            val = val[1:-1]
        if key in {"GITHUB_TOKEN", "GH_TOKEN"} and val:
            return val
    return ""


def github_token(env: dict | None = None, data_dir: Path | None = None) -> str:
    src = env if env is not None else os.environ
    tok = (src.get("GITHUB_TOKEN") or src.get("GH_TOKEN") or "").strip()
    if tok:
        return tok
    if data_dir is not None:
        return _token_from_env_file(Path(data_dir) / ".env")
    return ""


def _http_request(
    url: str,
    *,
    token: str = "",
    accept: str = "application/vnd.github+json",
    dest: Path | None = None,
    timeout: float = 60,
) -> bytes:
    headers = {
        "User-Agent": "AI-Influencer-Studio-Updater",
        "Accept": accept,
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(_safe_err(f"HTTP {exc.code} za {url}: {body}", token)) from None
    except urllib.error.URLError as exc:
        raise RuntimeError(_safe_err(f"Mrežna greška: {getattr(exc, 'reason', exc)}", token)) from None
    if dest:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    return data


def fetch_latest(cfg: dict, token: str = "") -> dict:
    owner = (cfg.get("owner") or "").strip()
    repo = (cfg.get("repo") or "").strip()
    if not owner or not repo:
        raise RuntimeError(
            "Izvor ažuriranja nije podešen. Uredi data/update.json "
            "(owner i repo na GitHubu)."
        )
    private = bool(cfg.get("private", True))
    if private and not token:
        raise RuntimeError(
            "Ovaj izvor ažuriranja je privatni GitHub repo. "
            "Upiši GITHUB_TOKEN u data/.env (fine-grained, samo ovaj repo, "
            "Contents: Read-only). Koraci su u TOKEN_UPUTE.txt."
        )
    api_base = (cfg.get("api_base") or "https://api.github.com").rstrip("/")
    url = f"{api_base}/repos/{owner}/{repo}/releases/latest"
    try:
        raw = _http_request(url, token=token, accept="application/vnd.github+json")
    except RuntimeError as exc:
        msg = str(exc)
        if token and ("HTTP 401" in msg or "HTTP 403" in msg):
            raise RuntimeError(
                "GitHub je odbio token. Provjeri da je GITHUB_TOKEN u data/.env "
                "važeći i da ima Contents: Read-only na Spinojpg/ai-influencer-studio."
            ) from None
        if "HTTP 404" in msg:
            raise RuntimeError(
                "GitHub nije našao izdanja ili repo (404). Ako je repo privatni, "
                "treba važeći GITHUB_TOKEN u data/.env. Vidi TOKEN_UPUTE.txt."
            ) from None
        raise
    try:
        rel = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub API nije vratio valjani JSON.") from exc
    tag = rel.get("tag_name") or rel.get("name") or ""
    notes = (rel.get("body") or "").strip()
    asset_name = (cfg.get("asset") or DEFAULT_ASSET).strip() or DEFAULT_ASSET
    sha_name = (cfg.get("checksum_asset") or DEFAULT_SHA_ASSET).strip() or DEFAULT_SHA_ASSET
    zip_asset = None
    sha_asset = None
    for asset in rel.get("assets") or []:
        name = asset.get("name") or ""
        if name == asset_name:
            zip_asset = asset
        elif name == sha_name:
            sha_asset = asset
    if not zip_asset:
        names = [a.get("name") for a in (rel.get("assets") or [])]
        raise RuntimeError(
            f"U izdanju {tag} nema datoteke {asset_name}. "
            f"Dostupno: {', '.join(str(n) for n in names if n) or 'ništa'}."
        )
    return {
        "tag": tag,
        "version": tag,
        "name": rel.get("name") or tag,
        "notes": notes,
        "published_at": rel.get("published_at") or "",
        "zip_name": zip_asset.get("name"),
        "zip_api_url": zip_asset.get("url") or "",
        "zip_download_url": zip_asset.get("browser_download_url") or "",
        "sha_api_url": (sha_asset or {}).get("url") or "",
        "sha_download_url": (sha_asset or {}).get("browser_download_url") or "",
        "sha_available": bool(sha_asset),
    }


def _download_asset(
    api_url: str,
    browser_url: str,
    dest: Path,
    token: str,
    *,
    private: bool = True,
) -> Path:
    """Privatni repo: samo API asset URL + Accept: application/octet-stream + Authorization."""
    if private or token:
        if not token:
            raise RuntimeError(
                "Privatni repo zahtijeva GITHUB_TOKEN u data/.env. Vidi TOKEN_UPUTE.txt."
            )
        if not api_url:
            raise RuntimeError(
                "Nema API URL-a za preuzimanje izdanja (treba url polje asseta, ne browser_download_url)."
            )
        _http_request(
            api_url,
            token=token,
            accept="application/octet-stream",
            dest=dest,
            timeout=180,
        )
        return dest
    url = browser_url or api_url
    if not url:
        raise RuntimeError("Nema URL-a za preuzimanje izdanja.")
    _http_request(url, token=token, accept="application/octet-stream", dest=dest, timeout=180)
    return dest


def parse_sha256_file(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise RuntimeError("Datoteka sha256 je prazna.")
    first = text.splitlines()[0].strip()
    # "deadbeef...  studio.zip" ili samo hex
    token = first.split()[0].strip()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", token):
        raise RuntimeError("sha256 datoteka nema valjani hash.")
    return token.lower()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_zip(path: Path) -> Path:
    """Provjeri da je ZIP valjan i da sadrži studio.py ili version.json."""
    path = Path(path)
    if not zipfile.is_zipfile(path):
        raise RuntimeError("Preuzeta datoteka nije valjani ZIP.")
    with zipfile.ZipFile(path, "r") as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"ZIP je oštećen (datoteka: {bad}).")
        names = zf.namelist()
    if not _zip_payload_root(path):
        raise RuntimeError("ZIP ne sadrži studio.py ni version.json — odbacujem ažuriranje.")
    if any(n.replace("\\", "/").startswith("/") or ".." in Path(n).parts for n in names):
        raise RuntimeError("ZIP sadrži nesigurne putanje.")
    return path


def _zip_payload_root(zip_path: Path) -> list[str] | None:
    """Vrati listu namelist; odredi korijen s studio.py / version.json."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = [n.replace("\\", "/") for n in zf.namelist() if n and not n.endswith("/")]
    if any(n == "studio.py" or n.endswith("/studio.py") for n in names):
        return names
    if any(n == "version.json" or n.endswith("/version.json") for n in names):
        return names
    return None


def extract_app_zip(zip_path: Path, dest_dir: Path) -> None:
    """Raspakiraj u dest_dir. Ako ZIP ima jedan korijenski folder, odvij ga."""
    dest_dir = Path(dest_dir)
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = [n.replace("\\", "/") for n in zf.namelist()]
        files = [n for n in names if n and not n.endswith("/")]
        tops = set()
        for n in files:
            parts = n.split("/")
            if parts[0] in {".", ""}:
                continue
            tops.add(parts[0] if len(parts) > 1 else "")
        unwrap = None
        real_tops = {t for t in tops if t}
        if len(real_tops) == 1:
            root = next(iter(real_tops))
            has_payload = any(
                n == f"{root}/studio.py" or n == f"{root}/version.json"
                for n in files
            )
            if has_payload:
                unwrap = root
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if name.endswith("/") or name.endswith("\\"):
                continue
            rel = name
            if unwrap and (rel == unwrap or rel.startswith(unwrap + "/")):
                rel = rel[len(unwrap) + 1 :]
            if not rel:
                continue
            # Nikad ne raspakiravaj korisničke podatke u app dir.
            first = rel.split("/")[0].lower()
            if first in {"data", ".env"} or rel.lower() == ".env":
                continue
            target = (dest_dir / rel).resolve()
            if dest_dir.resolve() not in target.parents and target != dest_dir.resolve():
                raise RuntimeError("ZIP je pokušao pisati izvan mape aplikacije.")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)


def updater_log(data_dir: Path | None, msg: str) -> None:
    """Zapiši korak u data/logs/updater.log. Nikad ne ispisuj tokene."""
    if not data_dir:
        return
    try:
        log_dir = Path(data_dir) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + str(msg).replace("\n", " ") + "\n"
        with (log_dir / "updater.log").open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass


PROTECTED_DIR_NAMES = {
    "data",
    "logs",
    "pending-update",
    "update-helper",
    "backup",
    ".app-staging",
    ".app-previous",
}
PROTECTED_FILE_NAMES = {
    ".env",
    "studio.pid",
    "launcher.pid",
    "update-result.json",
    "studio.db",
    "profiles.json",
    "persona.json",
}


def _is_protected_rel(rel: Path) -> bool:
    parts = rel.parts
    if not parts:
        return True
    if parts[0] in PROTECTED_DIR_NAMES or parts[0].startswith(".app-"):
        return True
    if rel.name in PROTECTED_FILE_NAMES:
        return True
    if rel.as_posix().lower() in {".env", "data/.env"}:
        return True
    return False


def iter_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    out = []
    for p in root.rglob("*"):
        if p.is_file():
            out.append(p)
    return out


def replace_file(src: Path, dest: Path, *, retries: int = 20, delay: float = 0.2) -> None:
    """Kopiraj pa os.replace, s ponovnim pokušajima (Windows zaključane datoteke)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".newtmp")
    shutil.copy2(src, tmp)
    last: Exception | None = None
    for i in range(retries):
        try:
            os.replace(str(tmp), str(dest))
            return
        except PermissionError as exc:
            last = exc
            time.sleep(delay * (1 + i * 0.15))
        except OSError as exc:
            last = exc
            # WinError 5 / 32
            if getattr(exc, "winerror", None) in {5, 32} or exc.errno in {13, 11, 16}:
                time.sleep(delay * (1 + i * 0.15))
                continue
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise
    if tmp.exists():
        try:
            tmp.unlink()
        except OSError:
            pass
    raise RuntimeError(f"Ne mogu zamijeniti {dest}: {last}")


def _rollback_from_backup(backup: Path, app_dir: Path, new_files: list[Path], data_dir: Path | None) -> None:
    updater_log(data_dir, f"ROLLBACK iz {backup}")
    if backup.is_dir():
        for src in iter_files(backup):
            rel = src.relative_to(backup)
            if _is_protected_rel(rel):
                continue
            try:
                replace_file(src, app_dir / rel, retries=8, delay=0.15)
            except Exception as exc:
                updater_log(data_dir, f"rollback nije mogao vratiti {rel}: {exc}")
    for path in new_files:
        try:
            rel = path.relative_to(app_dir)
        except ValueError:
            continue
        if _is_protected_rel(rel):
            continue
        bak = backup / rel
        if not bak.is_file() and path.is_file():
            try:
                path.unlink()
                updater_log(data_dir, f"rollback uklonio novu datoteku {rel}")
            except OSError as exc:
                updater_log(data_dir, f"rollback nije uklonio {rel}: {exc}")


def apply_zip(
    zip_path: Path,
    app_dir: Path,
    backup_dir: Path,
    *,
    expected_version: str | None = None,
    data_dir: Path | None = None,
) -> Path:
    """
    Zamijeni datoteke u app_dir sadržajem ZIP-a, datoteku po datoteku.
    Nikad ne preimenuje app_dir (na Windowsu to padne ako je cwd ili ima otvorene fajlove).
    Uspjeh se javlja tek nakon što version.json na disku odgovara očekivanoj verziji.
    """
    app_dir = Path(app_dir).resolve()
    backup_dir = Path(backup_dir).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    verify_zip(zip_path)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    old_ver = load_version(app_dir).get("version", "unknown")
    updater_log(data_dir, f"apply_zip start app={app_dir} zip={zip_path} old={old_ver} expected={expected_version}")
    backup = backup_dir / f"app-{old_ver}-{stamp}"
    # Staging UVIJEK izvan app_dir (parent ili backup_dir).
    staging = backup_dir / f".staging-{os.getpid()}-{stamp}"
    try:
        extract_app_zip(zip_path, staging)
        if not (staging / "studio.py").is_file() and not (staging / "version.json").is_file():
            raise RuntimeError("Raspakirani update nema studio.py.")
        staged = [p for p in iter_files(staging) if not _is_protected_rel(p.relative_to(staging))]
        updater_log(data_dir, f"staging {staging} datoteka={len(staged)}")

        if app_dir.exists():
            backup.mkdir(parents=True, exist_ok=True)
            for src in iter_files(app_dir):
                rel = src.relative_to(app_dir)
                if _is_protected_rel(rel):
                    continue
                dest = backup / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            updater_log(data_dir, f"backup {backup}")

        new_written: list[Path] = []
        for src in staged:
            rel = src.relative_to(staging)
            dest = app_dir / rel
            updater_log(data_dir, f"zamjena {rel}")
            replace_file(src, dest)
            new_written.append(dest)

        staged_rels = {p.relative_to(staging).as_posix() for p in staged}
        if app_dir.is_dir():
            for existing in iter_files(app_dir):
                rel = existing.relative_to(app_dir)
                if _is_protected_rel(rel):
                    continue
                if rel.as_posix() not in staged_rels:
                    try:
                        existing.unlink()
                        updater_log(data_dir, f"uklonjena stara {rel}")
                    except OSError as exc:
                        updater_log(data_dir, f"nisam uklonio {rel}: {exc}")

        manifest = {
            "version": load_version(app_dir).get("version"),
            "files": sorted(staged_rels),
            "ts": time.time(),
        }
        (app_dir / "update-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        new_ver = load_version(app_dir).get("version") or ""
        updater_log(data_dir, f"version.json na disku: {new_ver}")
        if expected_version:
            want = expected_version
            if want.lower().startswith("v") and want[1:2].isdigit():
                want_cmp = want[1:]
            else:
                want_cmp = want
            got_cmp = new_ver[1:] if new_ver.lower().startswith("v") and new_ver[1:2].isdigit() else new_ver
            if parse_version(got_cmp) != parse_version(want_cmp):
                raise RuntimeError(
                    f"Nakon primjene version.json je {new_ver!r}, očekivano {expected_version!r}."
                )
        if not new_ver:
            raise RuntimeError("Nakon primjene nema version.json.")
        updater_log(data_dir, f"apply_zip OK -> {new_ver}")
        shutil.rmtree(staging, ignore_errors=True)
        return backup
    except Exception as exc:
        updater_log(data_dir, f"apply_zip GREŠKA: {exc}")
        try:
            _rollback_from_backup(backup, app_dir, iter_files(app_dir), data_dir)
        except Exception as rex:
            updater_log(data_dir, f"rollback greška: {rex}")
        shutil.rmtree(staging, ignore_errors=True)
        raise



def check_for_update(app_dir: Path, data_dir: Path, token: str = "") -> dict:
    current = load_version(app_dir)
    cfg = load_update_config(data_dir)
    token = token or github_token(data_dir=data_dir)
    current_ver = current.get("version") or "0.0.0"
    if not (cfg.get("owner") and cfg.get("repo")):
        return {
            "ok": True,
            "configured": False,
            "current": current_ver,
            "latest": None,
            "newer": False,
            "message": "Izvor ažuriranja nije podešen. Uredi data/update.json (GitHub owner/repo).",
        }
    latest = fetch_latest(cfg, token=token)
    newer = is_newer(latest["version"], current_ver)
    return {
        "ok": True,
        "configured": True,
        "current": current_ver,
        "latest": latest["version"],
        "latest_tag": latest["tag"],
        "newer": newer,
        "notes": latest.get("notes") or "",
        "name": latest.get("name") or "",
        "sha_available": latest.get("sha_available"),
        "release": latest,
        "message": (
            f"Dostupna je verzija {latest['version']}."
            if newer
            else f"Imaš najnoviju verziju ({current_ver})."
        ),
    }


def download_and_verify(release: dict, dest_dir: Path, cfg: dict, token: str = "") -> dict:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / (cfg.get("asset") or DEFAULT_ASSET)
    private = bool(cfg.get("private", True))
    _download_asset(
        release.get("zip_api_url") or "",
        release.get("zip_download_url") or "",
        zip_path,
        token,
        private=private,
    )
    expected = None
    if release.get("sha_available"):
        sha_bytes = _download_asset(
            release.get("sha_api_url") or "",
            release.get("sha_download_url") or "",
            dest_dir / (cfg.get("checksum_asset") or DEFAULT_SHA_ASSET),
            token,
            private=private,
        )
        # _download_asset writes file; also returned bytes if we change it — read file
        sha_text = (dest_dir / (cfg.get("checksum_asset") or DEFAULT_SHA_ASSET)).read_text(encoding="utf-8")
        expected = parse_sha256_file(sha_text)
        actual = file_sha256(zip_path)
        if actual != expected:
            zip_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"sha256 se ne podudara (očekivano {expected[:12]}…, dobiveno {actual[:12]}…)."
            )
    verify_zip(zip_path)
    return {"zip_path": str(zip_path), "sha256": file_sha256(zip_path), "expected_sha256": expected}


def write_update_result(data_dir: Path, payload: dict) -> Path:
    path = Path(data_dir) / "update-result.json"
    payload = dict(payload)
    payload["ts"] = time.time()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_update_result(data_dir: Path) -> dict | None:
    path = Path(data_dir) / "update-result.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def ack_update_result(data_dir: Path) -> None:
    path = Path(data_dir) / "update-result.json"
    if path.is_file():
        try:
            path.unlink()
        except OSError:
            pass


def perform_update(app_dir: Path, data_dir: Path, token: str = "", backup_parent: Path | None = None) -> dict:
    """Preuzmi, provjeri i instaliraj noviju verziju. data_dir se ne dira."""
    app_dir = Path(app_dir).resolve()
    data_dir = Path(data_dir).resolve()
    # Zaštita: nikad ne piši update preko data mape.
    if data_dir.resolve() == app_dir.resolve() or app_dir.resolve() in data_dir.resolve().parents:
        # data inside app would be bad; we still skip extracting data/ from zip
        pass
    if data_dir.resolve() == app_dir.resolve():
        raise RuntimeError("DATA_DIR i APP_DIR ne smiju biti ista mapa.")
    token = token or github_token(data_dir=data_dir)
    info = check_for_update(app_dir, data_dir, token=token)
    if not info.get("configured"):
        raise RuntimeError(info.get("message") or "Update nije podešen.")
    if not info.get("newer"):
        return {**info, "applied": False}
    cfg = load_update_config(data_dir)
    pending = data_dir / "pending-update"
    downloaded = download_and_verify(info["release"], pending, cfg, token=token)
    backup_parent = Path(backup_parent or (app_dir.parent / "backup"))
    old_ver = info["current"]
    expected = info.get("latest")
    updater_log(data_dir, f"perform_update preuzeto, primjenjujem expected={expected}")
    backup = apply_zip(
        Path(downloaded["zip_path"]),
        app_dir,
        backup_parent,
        expected_version=expected,
        data_dir=data_dir,
    )
    new_ver = load_version(app_dir).get("version") or ""
    if not new_ver or (expected and parse_version(new_ver) != parse_version(expected)):
        raise RuntimeError(f"Verzija nakon updatea ({new_ver}) ne odgovara {expected}.")
    result = {
        "ok": True,
        "applied": True,
        "from_version": old_ver,
        "updated_to": new_ver,
        "changelog": info.get("notes") or "",
        "backup": str(backup),
        "message": f"Ažurirano na verziju {new_ver}",
    }
    write_update_result(data_dir, result)
    shutil.rmtree(pending, ignore_errors=True)
    updater_log(data_dir, f"perform_update OK {old_ver} -> {new_ver}")
    return result


def install_helper(app_dir: Path, data_dir: Path, zip_path: Path | None = None) -> Path:
    """Stavi apply_helper.py + updater.py u data/update-helper. Po mogućnosti iz novog ZIP-a."""
    dest = Path(data_dir) / "update-helper"
    dest.mkdir(parents=True, exist_ok=True)
    copied = set()
    if zip_path and Path(zip_path).is_file():
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = [n.replace("\\", "/") for n in zf.namelist()]
                for want in ("apply_helper.py", "updater.py"):
                    match = next((n for n in names if n == want or n.endswith("/" + want)), None)
                    if not match:
                        continue
                    target = dest / Path(match).name
                    with zf.open(match) as src, target.open("wb") as out:
                        shutil.copyfileobj(src, out)
                    copied.add(want)
                    updater_log(data_dir, f"helper {want} iz ZIP-a")
        except Exception as exc:
            updater_log(data_dir, f"helper iz ZIP-a nije uspio: {exc}")
    for name in ("apply_helper.py", "updater.py"):
        if name in copied:
            continue
        src = Path(app_dir) / name
        if src.is_file():
            shutil.copy2(src, dest / name)
            updater_log(data_dir, f"helper {name} iz app mape")
    if not (dest / "apply_helper.py").is_file():
        raise RuntimeError("Nema apply_helper.py za pokretanje updatea.")
    return dest


def spawn_apply_helper(app_dir: Path, data_dir: Path, zip_path: Path | None = None) -> subprocess.Popen:
    """Pokreni helper iz data mape, cwd=data, bez držanja app mape kao cwd."""
    dest = install_helper(app_dir, data_dir, zip_path)
    script = dest / "apply_helper.py"
    cmd = [sys.executable, str(script)]
    env = os.environ.copy()
    env["STUDIO_APP_DIR"] = str(Path(app_dir).resolve())
    env["STUDIO_DATA_DIR"] = str(Path(data_dir).resolve())
    wait = str(os.getpid())
    env["STUDIO_WAIT_PIDS"] = wait
    updater_log(data_dir, f"spawn helper {cmd} cwd={data_dir} wait_pids={wait}")
    kwargs: dict = {
        "cwd": str(Path(data_dir).resolve()),
        "env": env,
        "close_fds": True,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        flags = int(getattr(subprocess, "DETACHED_PROCESS", 0x00000008))
        flags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
        flags |= int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)
