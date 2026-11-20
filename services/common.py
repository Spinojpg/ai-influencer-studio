# -*- coding: utf-8 -*-
"""Zajednički pomoćnici za servise: SQLite veza, JSON, HTTP (JSON + multipart) i data/.env.

Samo standardna biblioteka. Tajne (tokeni, ključevi) žive isključivo u data/.env i
nikad se ne vraćaju u API odgovorima ni logovima — samo maskirano.
"""

from __future__ import annotations

import contextlib
import json
import mimetypes
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import inbox

UA = "AI-Influencer-Studio/1.1"


# ---------- baza ----------

@contextlib.contextmanager
def conn():
    """Ista studio.db kao inbox.py (WAL, foreign keys), pod istim zaključavanjem."""
    with inbox._lock:
        c = inbox.db()
        try:
            yield c
            c.commit()
        finally:
            c.close()


def now() -> float:
    return time.time()


def jload(raw, default=None):
    if raw in (None, ""):
        return default
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def jdump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def row_dict(row) -> dict:
    return {k: row[k] for k in row.keys()} if row is not None else {}


def truthy(value, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "on", "da"}:
        return True
    if s in {"0", "false", "no", "off", "ne"}:
        return False
    return default


def clamp_float(value, lo: float, hi: float, default: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    if n != n:  # NaN
        return default
    return max(lo, min(hi, n))


def clamp_int(value, lo: int, hi: int, default: int) -> int:
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def slugify(text: str, fallback: str = "osoba") -> str:
    table = str.maketrans({"č": "c", "ć": "c", "š": "s", "ž": "z", "đ": "d", "Č": "c", "Ć": "c", "Š": "s", "Ž": "z", "Đ": "d"})
    s = (text or "").translate(table).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:60] or fallback


def data_dir() -> Path:
    return Path(inbox.DATA_DIR)


# ---------- tajne / data/.env ----------

def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def mask(value: str) -> str:
    value = value or ""
    if not value:
        return ""
    if len(value) <= 8:
        return "••••"
    return value[:3] + "••••" + value[-2:]


def redact(text: str, *secrets: str) -> str:
    out = str(text or "")
    for s in secrets:
        if s and len(s) >= 4 and s in out:
            out = out.replace(s, mask(s))
    return out


_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def write_env_values(values: dict, path: Path | None = None) -> list[str]:
    """Upiši/ažuriraj ključeve u data/.env (ostale linije i komentari ostaju). Vrati promijenjene ključeve.

    Prazan string briše vrijednost (KEY=). None znači "ne diraj".
    """
    path = Path(path or inbox.ENV_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    pending = {k: ("" if v is None else str(v)) for k, v in values.items() if v is not None}
    for k, v in pending.items():
        if "\n" in v or "\r" in v:
            raise ValueError(f"Vrijednost za {k} ne smije imati novi red.")
    changed: list[str] = []
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = _ENV_LINE.match(line)
        if m and m.group(1) in pending and m.group(1) not in seen:
            key = m.group(1)
            seen.add(key)
            out.append(f"{key}={pending[key]}")
            changed.append(key)
            continue
        out.append(line)
    for key, val in pending.items():
        if key not in seen:
            out.append(f"{key}={val}")
            changed.append(key)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
    os.replace(tmp, path)
    for key, val in pending.items():
        if val:
            os.environ[key] = val
        else:
            os.environ.pop(key, None)
    return changed


# ---------- HTTP ----------

class HttpError(RuntimeError):
    def __init__(self, message: str, status: int = 0, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def encode_multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    """files: {field: (filename, bytes, content_type|None)}"""
    boundary = "----AISStudio" + uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in (fields or {}).items():
        if value is None:
            continue
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n".encode("utf-8"))
        parts.append((value if isinstance(value, str) else json.dumps(value) if isinstance(value, (dict, list)) else str(value)).encode("utf-8"))
        parts.append(b"\r\n")
    for name, spec in (files or {}).items():
        filename, data, ctype = spec
        ctype = ctype or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{Path(filename).name}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n".encode("utf-8")
        )
        parts.append(bytes(data))
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def http_request(
    method: str,
    url: str,
    *,
    params: dict | None = None,
    json_body=None,
    form: dict | None = None,
    files: dict | None = None,
    headers: dict | None = None,
    timeout: float = 60,
) -> dict:
    """Vrati {status, json, text}. Na HTTP grešci baca HttpError s porukom bez tajni."""
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    hdrs = {"User-Agent": UA, "Accept": "application/json"}
    hdrs.update(headers or {})
    data = None
    if files:
        data, ctype = encode_multipart(form or {}, files)
        hdrs["Content-Type"] = ctype
    elif json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode({k: (v if isinstance(v, str) else json.dumps(v) if isinstance(v, (dict, list)) else str(v)) for k, v in form.items() if v is not None}).encode("utf-8")
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            text = raw.decode("utf-8", errors="replace")
            try:
                parsed = json.loads(text) if text.strip() else None
            except ValueError:
                parsed = None
            return {"status": resp.status, "json": parsed, "text": text[:4000]}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:2000]
        raise HttpError(f"HTTP {exc.code}: {body[:500]}", exc.code, body) from None
    except urllib.error.URLError as exc:
        raise HttpError(f"Mrežna greška: {getattr(exc, 'reason', exc)}") from None
    except (TimeoutError, OSError) as exc:
        raise HttpError(f"Mrežna greška: {exc}") from None
