#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sigurna instalacija ComfyUI custom nodeova (1.0.19).

- uvijek u <ComfyUI>/custom_nodes/<ime> (isti root iz kojeg se pali comfyui-n.bat),
- provjera <ime>/__init__.py, izravnavanje ugniježđenih klonova (ime/ime/__init__.py),
- nepotpune mape se preimenuju u *.disabled (ComfyUI ih preskače), ne brišu se,
- bez Gita: GitHub zip (codeload) i raspakiravanje,
- pip u ComfyUI venv s constraintsom koji drži instalirani torch/numpy (ZLUDA build se ne dira).
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

import comfy_launch

# Paketi koje pip nikad ne smije mijenjati u ZLUDA venvu.
PINNED_PACKAGES = ("torch", "torchvision", "torchaudio", "numpy")
SKIP_REQUIREMENT_RE = re.compile(r"^\s*(torch|torchvision|torchaudio)\b", re.I)
USER_AGENT = "AI-Influencer-Studio"


def _noop_log(msg: str) -> None:
    try:
        print(msg)
    except Exception:
        pass


# ----------------------------------------------------------------- stanje mape

def node_dir(dirname: str, nodes_dir: Path | None = None) -> Path:
    return Path(nodes_dir) if nodes_dir is not None else comfy_launch.custom_nodes_dir()


def _find_nested_package(dest: Path, max_depth: int = 3) -> Path | None:
    """Prva podmapa (do max_depth) koja ima __init__.py — za izravnavanje ugniježđenog klona."""
    if not dest.is_dir():
        return None
    queue: list[tuple[Path, int]] = [(dest, 0)]
    while queue:
        cur, depth = queue.pop(0)
        if depth > 0 and (cur / "__init__.py").is_file():
            return cur
        if depth >= max_depth:
            continue
        try:
            children = sorted(p for p in cur.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name != "__pycache__")
        except OSError:
            continue
        for child in children:
            queue.append((child, depth + 1))
    return None


def node_state(dirname: str, nodes_dir: Path | None = None) -> dict:
    base = node_dir(dirname, nodes_dir)
    dest = base / dirname
    exists = dest.is_dir()
    has_init = (dest / "__init__.py").is_file()
    nested = None if has_init or not exists else _find_nested_package(dest)
    non_empty = False
    if exists:
        try:
            non_empty = any(dest.iterdir())
        except OSError:
            non_empty = False
    return {
        "dirname": dirname,
        "path": str(dest),
        "custom_nodes": str(base),
        "exists": exists,
        "non_empty": non_empty,
        "has_init": has_init,
        "valid": has_init,
        "nested": str(nested) if nested else "",
        "git": (dest / ".git").is_dir(),
        "disabled": (base / (dirname + ".disabled")).is_dir(),
    }


def flatten_nested(dest: Path, log=_noop_log) -> bool:
    """dest/<x>/__init__.py -> dest/__init__.py (premjesti sadržaj gore). True ako je popravljeno."""
    if (dest / "__init__.py").is_file():
        return True
    inner = _find_nested_package(dest)
    if inner is None:
        return False
    log(f"Mapa {dest.name} je ugniježđena ({inner.relative_to(dest)}) — izravnavam.")
    tmp = dest.parent / (dest.name + ".flatten-tmp")
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    shutil.move(str(inner), str(tmp))
    # Ostatak stare mape (prazni omotači, .git omotača) sklanjamo u .disabled.
    leftovers = [p for p in dest.iterdir()] if dest.is_dir() else []
    if leftovers:
        quarantine(dest, log=log)
    else:
        dest.rmdir()
    shutil.move(str(tmp), str(dest))
    return (dest / "__init__.py").is_file()


def quarantine(dest: Path, log=_noop_log) -> Path | None:
    """Preimenuj nepotpunu mapu u <ime>.broken-<ts>.disabled (ComfyUI preskače *.disabled)."""
    if not dest.exists():
        return None
    target = dest.parent / f"{dest.name}.broken-{time.strftime('%Y%m%d-%H%M%S')}.disabled"
    n = 1
    while target.exists():
        target = dest.parent / f"{dest.name}.broken-{time.strftime('%Y%m%d-%H%M%S')}-{n}.disabled"
        n += 1
    shutil.move(str(dest), str(target))
    log(f"Nepotpuna mapa {dest.name} je preimenovana u {target.name} (ComfyUI je preskače).")
    return target


# ----------------------------------------------------------------- dohvat koda

def github_owner_repo(url: str) -> tuple[str, str]:
    m = re.search(r"github\.com[/:]([^/]+)/([^/#?]+?)(?:\.git)?/?$", (url or "").strip())
    if not m:
        raise ValueError(f"Nije GitHub URL: {url}")
    return m.group(1), m.group(2)


def codeload_urls(url: str) -> list[str]:
    owner, repo = github_owner_repo(url)
    return [f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{b}" for b in ("main", "master")]


def _http_get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def extract_zip_to(data: bytes, dest: Path) -> None:
    """Raspakiraj GitHub zip (repo-main/...) tako da sadržaj ide izravno u dest."""
    with tempfile.TemporaryDirectory(prefix="node-zip-", dir=str(dest.parent)) as td:
        tmp = Path(td)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for member in zf.namelist():
                target = (tmp / member).resolve()
                if not str(target).startswith(str(tmp.resolve())):
                    raise RuntimeError("Neispravan zip (putanja izvan mape).")
            zf.extractall(tmp)
        tops = [p for p in tmp.iterdir() if not p.name.startswith("__MACOSX")]
        src = tops[0] if len(tops) == 1 and tops[0].is_dir() else tmp
        if dest.exists():
            raise RuntimeError(f"{dest} već postoji.")
        if src is tmp:
            dest.mkdir(parents=True)
            for p in tmp.iterdir():
                shutil.move(str(p), str(dest / p.name))
        else:
            shutil.move(str(src), str(dest))


def download_zip(url: str, dest: Path, log=_noop_log, fetch=_http_get) -> None:
    errors = []
    for zurl in codeload_urls(url):
        try:
            log(f"Preuzimam {zurl} (bez Gita)…")
            data = fetch(zurl)
            extract_zip_to(data, dest)
            return
        except Exception as exc:  # pokušaj sljedeću granu
            errors.append(f"{zurl}: {exc}")
            if dest.exists() and not (dest / "__init__.py").is_file():
                shutil.rmtree(dest, ignore_errors=True)
    raise RuntimeError("Preuzimanje zip arhive nije uspjelo: " + " | ".join(errors)[-600:])


def _run(argv: list[str], *, cwd: Path | None = None, timeout: int = 900, env: dict | None = None) -> tuple[int, str]:
    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)) if os.name == "nt" else 0
    e = dict(os.environ if env is None else env)
    e.setdefault("GIT_TERMINAL_PROMPT", "0")
    e.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run(
        argv, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace", env=e, creationflags=flags,
    )
    out = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()
    return proc.returncode, out[-6000:]


def ensure_node(
    url: str,
    dirname: str,
    *,
    git: str = "",
    nodes_dir: Path | None = None,
    log=_noop_log,
    run=None,
    fetch=_http_get,
) -> dict:
    """Osiguraj ispravan <custom_nodes>/<dirname>/__init__.py. Vraća node_state."""
    run = run or _run
    base = node_dir(dirname, nodes_dir)
    base.mkdir(parents=True, exist_ok=True)
    dest = base / dirname
    log(f"Mapa čvora: {dest}")

    if dest.is_dir() and not (dest / "__init__.py").is_file():
        if not flatten_nested(dest, log=log):
            if dest.is_dir() and not any(dest.iterdir()):
                dest.rmdir()
            else:
                quarantine(dest, log=log)

    if (dest / "__init__.py").is_file():
        if git and (dest / ".git").is_dir():
            code, out = run([git, "-C", str(dest), "pull", "--ff-only"], timeout=300)
            if code != 0:
                log(f"git pull za {dirname} nije uspio — koristim postojeću kopiju. {out[-300:]}")
        else:
            log(f"{dirname} je već na disku.")
        return node_state(dirname, base)

    cloned = False
    if git:
        log(f"Kloniram {url} u {dest}…")
        code, out = run([git, "clone", "--depth", "1", url, str(dest)], timeout=900)
        if code == 0 and dest.is_dir():
            cloned = True
        else:
            log(f"git clone nije uspio ({out[-400:] or 'nema izlaza'}). Pokušavam zip.")
            if dest.exists():
                quarantine(dest, log=log)
    if not cloned:
        download_zip(url, dest, log=log, fetch=fetch)
    flatten_nested(dest, log=log)
    state = node_state(dirname, base)
    if not state["valid"]:
        raise RuntimeError(f"{dirname} nema __init__.py nakon instalacije ({dest}).")
    log(f"{dirname} je spreman na disku ({dest}).")
    return state


# ----------------------------------------------------------------- pip

def installed_versions(py: Path | str, packages=PINNED_PACKAGES, run=None) -> dict:
    run = run or _run
    code_src = (
        "import importlib.metadata as m\n"
        f"for n in {list(packages)!r}:\n"
        "    try:\n        print(n + '==' + m.version(n))\n"
        "    except Exception:\n        pass\n"
    )
    try:
        code, out = run([str(py), "-c", code_src], timeout=120)
    except Exception:
        return {}
    if code != 0:
        return {}
    vers = {}
    for line in out.splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+)==(\S+)$", line.strip())
        if m:
            vers[m.group(1).lower()] = m.group(2)
    return vers


def filtered_requirements(req: Path) -> list[str]:
    lines = []
    for raw in req.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if SKIP_REQUIREMENT_RE.match(line):
            continue
        lines.append(line)
    return lines


def _req_name(line: str) -> str:
    return re.split(r"[<>=!~;\[\s@]", line.strip(), maxsplit=1)[0]


def install_requirements(node_path: Path, py: Path | str, *, log=_noop_log, run=None) -> list[str]:
    """pip install requirements.txt bez diranja torcha/numpyja. Vraća popis paketa koji nisu prošli."""
    run = run or _run
    node_path = Path(node_path)
    req = node_path / "requirements.txt"
    if not req.is_file():
        log(f"{node_path.name}: nema requirements.txt.")
        return []
    if not Path(py).is_file():
        raise RuntimeError(f"Nema ComfyUI venv Pythona: {py}")
    lines = filtered_requirements(req)
    if not lines:
        return []
    pins = installed_versions(py, run=run)
    with tempfile.TemporaryDirectory(prefix="studio-pip-") as td:
        cfile = Path(td) / "constraints.txt"
        cfile.write_text("".join(f"{k}=={v}\n" for k, v in pins.items()), encoding="utf-8")
        rfile = Path(td) / "requirements.txt"
        rfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
        env = dict(os.environ, PIP_CONSTRAINT=str(cfile), PIP_DISABLE_PIP_VERSION_CHECK="1")
        log(f"pip: {node_path.name} ({len(lines)} paketa, torch/numpy zaključani: {', '.join(f'{k} {v}' for k, v in pins.items()) or 'nepoznato'})…")
        code, out = run([str(py), "-m", "pip", "install", "-r", str(rfile), "-c", str(cfile)], timeout=1800, env=env)
        if code == 0:
            log(f"pip za {node_path.name} je gotov.")
            return []
        log(f"pip za cijeli popis nije uspio, pokušavam paket po paket. {out[-300:]}")
        failed = []
        for line in lines:
            c, o = run([str(py), "-m", "pip", "install", line, "-c", str(cfile)], timeout=900, env=env)
            if c != 0:
                failed.append(_req_name(line))
                log(f"pip: {line} nije uspio: {o[-200:]}")
        return failed


def run_install_script(node_path: Path, py: Path | str, *, log=_noop_log, run=None) -> bool:
    """install.py (Impact Pack/Subpack) s venv Pythonom i istim constraintsom."""
    run = run or _run
    script = Path(node_path) / "install.py"
    if not script.is_file():
        return True
    pins = installed_versions(py, run=run)
    with tempfile.TemporaryDirectory(prefix="studio-pip-") as td:
        cfile = Path(td) / "constraints.txt"
        cfile.write_text("".join(f"{k}=={v}\n" for k, v in pins.items()), encoding="utf-8")
        env = dict(os.environ, PIP_CONSTRAINT=str(cfile), PIP_DISABLE_PIP_VERSION_CHECK="1", COMFYUI_PATH=str(comfy_launch.comfy_root()))
        log(f"Pokrećem {Path(node_path).name}/install.py…")
        code, out = run([str(py), str(script)], cwd=Path(node_path), timeout=1800, env=env)
    if code != 0:
        log(f"install.py za {Path(node_path).name} nije uspio: {out[-400:]}")
        return False
    return True


# ----------------------------------------------------------------- stvarna custom_nodes mapa

_LOG_CACHE: dict = {"key": None, "info": {}}


def comfy_log_path() -> Path:
    try:
        import inbox
        return Path(inbox.DATA_DIR) / "logs" / "comfyui.log"
    except Exception:
        return Path(os.environ.get("STUDIO_DATA_DIR") or "data") / "logs" / "comfyui.log"


def comfy_log_info(path: Path | None = None) -> dict:
    import comfy_log
    p = Path(path) if path is not None else comfy_log_path()
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
    except OSError:
        return {}
    if _LOG_CACHE["key"] != key:
        _LOG_CACHE["key"] = key
        _LOG_CACHE["info"] = comfy_log.parse_file(p)
    return _LOG_CACHE["info"]


def effective_custom_nodes_dir(log_info: dict | None = None) -> Path:
    """custom_nodes koju ComfyUI stvarno skenira (iz loga), inače <ComfyUI>/custom_nodes."""
    import comfy_log
    if os.environ.get("COMFYUI_CUSTOM_NODES_DIR"):
        return comfy_launch.custom_nodes_dir()
    info = comfy_log_info() if log_info is None else log_info
    seen = comfy_log.comfy_custom_nodes_dir(info)
    if seen and Path(seen).is_dir():
        return Path(seen)
    return comfy_launch.custom_nodes_dir()
