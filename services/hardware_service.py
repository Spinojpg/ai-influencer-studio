# -*- coding: utf-8 -*-
"""Hardver i RX 6600 (8 GB) profil: detekcija GPU-a, backend, ComfyUI zastavice i okruženje.

KLJUČNO za RX 6600 + ZLUDA: TORCH_BACKENDS_CUDNN_ENABLED=0 uvijek ostaje postavljen
(osim ako ga korisnik svjesno isključi u postavci disable_cudnn), inače ComfyUI zna
zapeti na "Compilation is in progress".
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import comfy_launch
import inbox

BACKENDS = ("auto", "zluda", "rocm", "directml", "cuda", "cpu")
VAE_MODES = ("standard", "tiled", "cpu")
# ComfyUI nema --medvram (to je A1111). "medvram" = ComfyUI zadano upravljanje (bez zastavice).
VRAM_MODES = ("auto", "lowvram", "medvram", "normalvram")
VRAM_MODE_FLAG = {"lowvram": "--lowvram", "normalvram": "--normalvram", "medvram": "", "auto": ""}
DEFAULT_ROCM_GFX = "10.3.0"  # RX 6600 = gfx1032 -> HSA_OVERRIDE_GFX_VERSION=10.3.0

DEFAULTS = {
    "hw_backend": "auto",
    "hw_vae_mode": "tiled",
    "hw_vae_tile": "512",
    "hw_vram_mode": "auto",
    "hw_reserve_vram": "1.0",
    "hw_safe_mode": "1",
    "hw_rocm_gfx": DEFAULT_ROCM_GFX,
    "hw_env_overrides": "",
    "hw_extra_args": "",
    "hw_detected_json": "",
}

# 8 GB siguran mod: SDXL bazne rezolucije po omjeru (širina/visina).
SAFE_SDXL_BASES = (
    (4 / 5, 768, 960),      # IG portret 4:5 -> 1080×1350
    (1.0, 768, 768),        # kvadrat -> 1080×1080
    (9 / 16, 576, 1024),    # story 9:16 -> 1080×1920
    (2 / 3, 704, 1056),     # portret 2:3
    (832 / 1024, 832, 1024),
    (3 / 2, 1056, 704),     # pejzaž
)
SAFE_SD15_MAX_SIDE = 768


# ---------- postavke ----------

def get_settings() -> dict:
    out = {}
    for key, default in DEFAULTS.items():
        try:
            out[key] = inbox.get_setting(key, default)
        except Exception:
            out[key] = default
        if out[key] in (None,):
            out[key] = default
    return normalize(out)


def normalize(raw: dict) -> dict:
    s = dict(DEFAULTS)
    s.update({k: v for k, v in (raw or {}).items() if k in DEFAULTS and v is not None})
    s["hw_backend"] = s["hw_backend"] if s["hw_backend"] in BACKENDS else "auto"
    s["hw_vae_mode"] = s["hw_vae_mode"] if s["hw_vae_mode"] in VAE_MODES else "tiled"
    s["hw_vram_mode"] = s["hw_vram_mode"] if s["hw_vram_mode"] in VRAM_MODES else "auto"
    try:
        tile = int(float(s["hw_vae_tile"]))
    except (TypeError, ValueError):
        tile = 512
    s["hw_vae_tile"] = str(max(256, min(1024, tile - tile % 64)))
    try:
        rv = float(s["hw_reserve_vram"])
    except (TypeError, ValueError):
        rv = 1.0
    s["hw_reserve_vram"] = f"{max(0.0, min(4.0, rv)):.1f}"
    s["hw_safe_mode"] = "1" if str(s["hw_safe_mode"]).lower() in {"1", "true", "on", "yes"} else "0"
    gfx = str(s.get("hw_rocm_gfx") or "").strip()
    s["hw_rocm_gfx"] = gfx if re.fullmatch(r"\d+\.\d+\.\d+", gfx) else DEFAULT_ROCM_GFX
    return s


def save_settings(payload: dict) -> dict:
    cur = get_settings()
    incoming = {}
    alias = {
        "backend": "hw_backend", "vae_mode": "hw_vae_mode", "vae_tile": "hw_vae_tile",
        "vram_mode": "hw_vram_mode", "reserve_vram": "hw_reserve_vram", "safe_mode": "hw_safe_mode",
        "rocm_gfx": "hw_rocm_gfx", "env_overrides": "hw_env_overrides", "extra_args": "hw_extra_args",
    }
    for k, v in (payload or {}).items():
        key = alias.get(k, k)
        if key in DEFAULTS and key != "hw_detected_json":
            if key == "hw_safe_mode":
                v = "1" if v in (True, 1, "1", "true", "on") else "0"
            incoming[key] = str(v if v is not None else "")
    if "hw_env_overrides" in incoming:
        parse_env_overrides(incoming["hw_env_overrides"])  # baca ValueError ako je neispravno
    if "hw_extra_args" in incoming:
        parse_extra_args(incoming["hw_extra_args"])
    merged = normalize({**cur, **incoming})
    for key, val in merged.items():
        if key in incoming or key not in cur:
            inbox.set_setting(key, val)
    # Stara kvačica "Low VRAM" ostaje u sinkronu s izbornikom.
    if "hw_vram_mode" in incoming:
        inbox.set_setting("low_vram", "1" if merged["hw_vram_mode"] == "lowvram" else "0")
    if "disable_cudnn" in (payload or {}):
        inbox.set_setting("disable_cudnn", "1" if payload["disable_cudnn"] in (True, 1, "1", "true", "on") else "0")
    return get_settings()


def parse_env_overrides(text: str) -> dict:
    out = {}
    for i, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Redak {i} mora biti KLJUČ=vrijednost.")
        k, v = line.split("=", 1)
        k = k.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
            raise ValueError(f"Neispravno ime varijable u retku {i}: {k}")
        out[k] = v.strip()
    return out


def parse_extra_args(text: str) -> list[str]:
    args = [a for a in re.split(r"\s+", (text or "").strip()) if a]
    for a in args:
        if not (a.startswith("--") or re.fullmatch(r"[\w.\-:/\\]+", a)):
            raise ValueError(f"Neispravan argument: {a}")
    return args


# ---------- detekcija GPU-a ----------

def _run(argv: list[str], timeout: float = 15) -> str:
    try:
        flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if sys.platform == "win32" else 0
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, creationflags=flags)
        return r.stdout or ""
    except Exception:
        return ""


def parse_cim_json(text: str) -> list[dict]:
    """Izlaz PowerShell Get-CimInstance Win32_VideoController | ConvertTo-Json."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return []
    if isinstance(data, dict):
        data = [data]
    out = []
    for item in data or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name") or item.get("Caption") or "").strip()
        if not name:
            continue
        ram = item.get("AdapterRAM")
        try:
            ram = int(ram)
        except (TypeError, ValueError):
            ram = 0
        out.append({"name": name, "vram_bytes": ram, "driver": str(item.get("DriverVersion") or ""), "source": "cim"})
    return out


def parse_wmic(text: str) -> list[dict]:
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.lower().startswith("adapterram") or line.lower().startswith("node"):
            continue
        parts = [p.strip() for p in line.split(",")]
        # /format:csv -> Node,AdapterRAM,DriverVersion,Name
        if len(parts) >= 4:
            try:
                ram = int(parts[1] or 0)
            except ValueError:
                ram = 0
            out.append({"name": parts[3], "vram_bytes": ram, "driver": parts[2], "source": "wmic"})
    return out


def parse_system_stats(stats: dict) -> list[dict]:
    out = []
    for dev in (stats or {}).get("devices") or []:
        if not isinstance(dev, dict):
            continue
        name = str(dev.get("name") or "")
        # ComfyUI-Zluda: "cuda:0 AMD Radeon RX 6600 [ZLUDA] : native"
        out.append({
            "name": name,
            "vram_bytes": int(dev.get("vram_total") or 0),
            "vram_free": int(dev.get("vram_free") or 0),
            "type": str(dev.get("type") or ""),
            "source": "comfyui",
        })
    return out


def detect_gpus(*, system_stats: dict | None = None, runner=None) -> list[dict]:
    """Windows CIM -> wmic -> ComfyUI /system_stats -> Linux lspci. STUDIO_MOCK_GPU za testove."""
    mock = os.environ.get("STUDIO_MOCK_GPU")
    if mock:
        name, _, vram = mock.partition("|")
        try:
            vb = int(float(vram or 8) * 1024 ** 3)
        except ValueError:
            vb = 8 * 1024 ** 3
        return [{"name": name, "vram_bytes": vb, "source": "mock"}]
    run = runner or _run
    gpus: list[dict] = []
    if sys.platform == "win32" or runner is not None:
        text = run([
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion | ConvertTo-Json -Compress",
        ])
        gpus = parse_cim_json(text)
        if not gpus:
            gpus = parse_wmic(run(["wmic", "path", "win32_VideoController", "get", "Name,AdapterRAM,DriverVersion", "/format:csv"]))
    stats_gpus = parse_system_stats(system_stats or {})
    # Win32 AdapterRAM je 32-bitni (max 4 GB) — VRAM iz ComfyUI-ja je točniji.
    if stats_gpus:
        for g in gpus:
            for s in stats_gpus:
                if s.get("vram_bytes") and _same_card(g["name"], s["name"]):
                    g["vram_bytes"] = max(g.get("vram_bytes") or 0, s["vram_bytes"])
                    g["vram_free"] = s.get("vram_free")
        if not gpus:
            gpus = stats_gpus
    if not gpus and sys.platform.startswith("linux") and runner is None:
        for line in _run(["lspci"]).splitlines():
            if re.search(r"VGA|3D|Display", line):
                gpus.append({"name": line.split(":", 2)[-1].strip(), "vram_bytes": 0, "source": "lspci"})
    return gpus


def _same_card(a: str, b: str) -> bool:
    a, b = a.lower(), b.lower()
    m = re.search(r"(rx|rtx|gtx|arc)\s*([a-z]?\d{3,4}\s*(xt|ti|super)?)", a)
    return bool(m and m.group(0).replace(" ", "") in b.replace(" ", "")) or a in b or b in a


def classify(gpu: dict | None) -> dict:
    name = str((gpu or {}).get("name") or "")
    low = name.lower()
    vram_gb = round(float((gpu or {}).get("vram_bytes") or 0) / 1024 ** 3, 1)
    vendor = "amd" if re.search(r"amd|radeon|\brx\s?\d", low) else "nvidia" if re.search(r"nvidia|geforce|rtx|gtx|quadro", low) else "intel" if "intel" in low else "unknown"
    family, gfx = "", ""
    m = re.search(r"rx\s?(\d{4})\s*(xt|m|s)?", low)
    if vendor == "amd" and m:
        num = int(m.group(1))
        if 6400 <= num <= 6999:
            family = "rdna2"
            gfx = "gfx1032" if num in (6600, 6650) or 6500 <= num < 6700 else "gfx1031" if 6700 <= num < 6800 else "gfx1030"
        elif 7000 <= num <= 7999:
            family = "rdna3"
            gfx = "gfx1100" if num >= 7900 else "gfx1101" if num >= 7700 else "gfx1102"
        elif 5000 <= num <= 5999:
            family = "rdna1"
    is_rx6600 = vendor == "amd" and bool(re.search(r"rx\s?66[05]0", low))
    if is_rx6600 and vram_gb < 7.5:
        vram_gb = 8.0  # AdapterRAM je ograničen na 4 GB u WMI-ju
    return {
        "name": name or "Nepoznata grafička",
        "vendor": vendor,
        "family": family,
        "gfx": gfx,
        "vram_gb": vram_gb,
        "is_rx6600": is_rx6600,
        "low_vram_card": bool(vram_gb and vram_gb <= 8.5) or is_rx6600,
    }


def recommend(profile: dict) -> dict:
    """Preporučene postavke za karticu. RX 6600: ZLUDA, tiled VAE 512, reserve 1 GB, 8 GB siguran mod."""
    vendor = profile.get("vendor")
    vram = float(profile.get("vram_gb") or 0)
    if profile.get("is_rx6600") or (vendor == "amd" and profile.get("family") == "rdna2" and vram <= 8.5):
        return {
            "hw_backend": "zluda", "hw_vae_mode": "tiled", "hw_vae_tile": "512",
            "hw_vram_mode": "auto", "hw_reserve_vram": "1.0", "hw_safe_mode": "1",
            "hw_rocm_gfx": DEFAULT_ROCM_GFX,
            "why": "RX 6600 (8 GB): ZLUDA s isključenim cuDNN-om, tiled VAE 512, 1 GB rezerve VRAM-a i 8 GB siguran mod "
                   "(SDXL baza 768×960 pa upscale). --lowvram nije potreban dok nema out of memory jer usporava.",
        }
    if vendor == "amd":
        return {"hw_backend": "zluda" if os.name == "nt" else "rocm", "hw_vae_mode": "tiled", "hw_vae_tile": "512",
                "hw_vram_mode": "auto", "hw_reserve_vram": "1.0", "hw_safe_mode": "1" if vram <= 10 else "0",
                "hw_rocm_gfx": DEFAULT_ROCM_GFX, "why": "AMD kartica: ZLUDA na Windowsu, ROCm na Linuxu."}
    if vendor == "nvidia":
        return {"hw_backend": "cuda", "hw_vae_mode": "tiled" if vram <= 8.5 else "standard", "hw_vae_tile": "512",
                "hw_vram_mode": "auto", "hw_reserve_vram": "0.8" if vram <= 8.5 else "0.0", "hw_safe_mode": "1" if vram <= 8.5 else "0",
                "hw_rocm_gfx": DEFAULT_ROCM_GFX, "why": "NVIDIA kartica: CUDA."}
    return {"hw_backend": "auto", "hw_vae_mode": "tiled", "hw_vae_tile": "512", "hw_vram_mode": "lowvram",
            "hw_reserve_vram": "1.0", "hw_safe_mode": "1", "hw_rocm_gfx": DEFAULT_ROCM_GFX,
            "why": "Nepoznata kartica: najsigurnije postavke."}


def apply_recommendation(profile: dict | None = None) -> dict:
    prof = profile or hardware_profile().get("profile") or {}
    rec = {k: v for k, v in recommend(prof).items() if k.startswith("hw_")}
    saved = save_settings(rec)
    inbox.set_setting("disable_cudnn", "1")  # ZLUDA quirk: uvijek uključeno
    return saved


_DETECT_CACHE: dict = {}
_DETECT_LOCK = threading.Lock()


def hardware_profile(*, system_stats: dict | None = None, refresh: bool = False, runner=None) -> dict:
    with _DETECT_LOCK:
        if refresh or not _DETECT_CACHE or system_stats:
            gpus = detect_gpus(system_stats=system_stats, runner=runner)
            # Diskretna kartica ima prednost pred integriranom.
            gpus_sorted = sorted(gpus, key=lambda g: (classify(g)["vendor"] in {"amd", "nvidia"}, g.get("vram_bytes") or 0), reverse=True)
            best = gpus_sorted[0] if gpus_sorted else None
            prof = classify(best)
            _DETECT_CACHE.clear()
            _DETECT_CACHE.update({"gpus": gpus, "profile": prof, "recommended": recommend(prof)})
            try:
                inbox.set_setting("hw_detected_json", json.dumps(prof, ensure_ascii=False))
            except Exception:
                pass
        return dict(_DETECT_CACHE)


def effective_backend(settings: dict | None = None, profile: dict | None = None) -> str:
    s = settings or get_settings()
    b = s.get("hw_backend") or "auto"
    if b != "auto":
        return b
    prof = profile
    if prof is None:
        try:
            prof = json.loads(inbox.get_setting("hw_detected_json", "") or "{}")
        except (TypeError, ValueError):
            prof = {}
    vendor = (prof or {}).get("vendor")
    if vendor == "amd":
        return "zluda" if (os.name == "nt" or "zluda" in str(comfy_launch.comfy_dir()).lower()) else "rocm"
    if vendor == "nvidia":
        return "cuda"
    # Zadana instalacija je C:\ComfyUI-Zluda.
    return "zluda" if "zluda" in str(comfy_launch.comfy_dir()).lower() else "auto"


# ---------- ComfyUI zastavice i okruženje ----------

def supported_cli_flags(root: Path | None = None) -> set[str] | None:
    """Zastavice iz ComfyUI comfy/cli_args.py; None ako datoteka nije dostupna (onda ne filtriramo)."""
    base = Path(root) if root else comfy_launch.comfy_root()
    path = base / "comfy" / "cli_args.py"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return set(re.findall(r"[\"'](--[a-z0-9][a-z0-9\-]*)[\"']", text))


def launch_flags(settings: dict | None = None, *, source_text: str = "", supported: set[str] | None = None, check_supported: bool = True) -> list[str]:
    """Dodatne ComfyUI zastavice: VRAM način, --reserve-vram, --cpu-vae, backend (directml/cpu), korisnički argumenti.

    Ne dodaje VRAM zastavicu ako je originalni comfyui-n.bat već ima, i preskače zastavice koje
    instalirani ComfyUI ne poznaje (inače argparse sruši pokretanje).
    """
    s = normalize(settings or get_settings())
    flags: list[str] = []
    backend = s["hw_backend"]
    vflag = VRAM_MODE_FLAG.get(s["hw_vram_mode"], "")
    if backend == "cpu":
        flags.append("--cpu")
    else:
        if backend == "directml":
            flags.append("--directml")
        if vflag and not any(comfy_launch.text_has_flag(source_text, f) for f in comfy_launch.VRAM_FLAGS):
            flags.append(vflag)
        try:
            rv = float(s["hw_reserve_vram"])
        except ValueError:
            rv = 0.0
        if rv > 0 and not comfy_launch.text_has_flag(source_text, "--reserve-vram"):
            flags.append(f"--reserve-vram {rv:.1f}")
        if s["hw_vae_mode"] == "cpu" and not comfy_launch.text_has_flag(source_text, "--cpu-vae"):
            flags.append("--cpu-vae")
    grouped: list[str] = []
    for a in parse_extra_args(s.get("hw_extra_args") or ""):
        if not a.startswith("--") and grouped:
            grouped[-1] += " " + a
        elif a.startswith("--"):
            grouped.append(a)
    for a in grouped:
        if a not in flags and not comfy_launch.text_has_flag(source_text, a.split()[0]):
            flags.append(a)
    if check_supported:
        known = supported if supported is not None else supported_cli_flags()
        if known:
            out: list[str] = []
            skip_value = False
            for i, f in enumerate(flags):
                if skip_value:
                    skip_value = False
                    continue
                head = f.split()[0]
                if head.startswith("--") and head not in known:
                    if " " not in f and i + 1 < len(flags) and not flags[i + 1].startswith("--"):
                        skip_value = True
                    continue
                out.append(f)
            flags = out
    return flags


def process_env(base: dict | None = None, settings: dict | None = None, *, disable_cudnn: bool | None = None, profile: dict | None = None) -> dict:
    """Okruženje ComfyUI procesa. ZLUDA/AMD: TORCH_BACKENDS_CUDNN_ENABLED=0 (obavezno za RX 6600).

    ROCm: HSA_OVERRIDE_GFX_VERSION (RX 6600 / gfx1032 -> 10.3.0). Korisnički override-ovi zadnji.
    """
    s = normalize(settings or get_settings())
    if disable_cudnn is None:
        try:
            disable_cudnn = comfy_launch.setting_on(inbox.get_setting("disable_cudnn", "1"), True)
        except Exception:
            disable_cudnn = True
    env = comfy_launch.comfy_process_env(base, disable_cudnn=bool(disable_cudnn))
    backend = effective_backend(s, profile)
    if backend == "rocm":
        env.setdefault("HSA_OVERRIDE_GFX_VERSION", s["hw_rocm_gfx"] or DEFAULT_ROCM_GFX)
        env["HSA_OVERRIDE_GFX_VERSION"] = s["hw_rocm_gfx"] or DEFAULT_ROCM_GFX
        env.setdefault("PYTORCH_HIP_ALLOC_CONF", "garbage_collection_threshold:0.8,max_split_size_mb:512")
    if backend == "cpu":
        env["CUDA_VISIBLE_DEVICES"] = ""
    env.update(parse_env_overrides(s.get("hw_env_overrides") or ""))
    if disable_cudnn:
        # Override ne smije slučajno vratiti cuDNN na ZLUDA-i.
        env["TORCH_BACKENDS_CUDNN_ENABLED"] = "0"
    return env


def launch_plan(source_text: str = "", settings: dict | None = None) -> dict:
    s = normalize(settings or get_settings())
    low_vram = s["hw_vram_mode"] == "lowvram"
    extra = [f for f in launch_flags(s, source_text=source_text) if f != "--lowvram"]
    env = process_env({}, s)
    return {
        "low_vram": low_vram,
        "extra_flags": extra,
        "env_keys": {k: v for k, v in env.items() if k in {"TORCH_BACKENDS_CUDNN_ENABLED", "HSA_OVERRIDE_GFX_VERSION", "PYTORCH_HIP_ALLOC_CONF", "CUDA_VISIBLE_DEVICES"} or k in parse_env_overrides(s.get("hw_env_overrides") or "")},
        "backend": effective_backend(s),
    }


# ---------- generiranje: 8 GB siguran mod ----------

def safe_base_for(arch: str, width: int, height: int) -> tuple[int, int]:
    """Bazna rezolucija za 8 GB VRAM-a za zadani ciljni omjer."""
    width, height = int(width or 0), int(height or 0)
    if width <= 0 or height <= 0:
        return width, height
    ratio = width / height
    if arch == "sdxl":
        best = min(SAFE_SDXL_BASES, key=lambda b: abs(b[0] - ratio))
        bw, bh = best[1], best[2]
        if abs(best[0] - ratio) > 0.04:
            # slobodan omjer: ~0,74 MP, poravnato na 64
            area = 768 * 960
            bh = int((area / ratio) ** 0.5)
            bw = int(bh * ratio)
            bw, bh = max(512, bw - bw % 64), max(512, bh - bh % 64)
        # nikad veće od traženog
        if bw * bh >= width * height:
            return width - width % 8, height - height % 8
        return bw, bh
    if arch == "sd15":
        side = max(width, height)
        if side <= SAFE_SD15_MAX_SIDE:
            return width - width % 8, height - height % 8
        k = SAFE_SD15_MAX_SIDE / side
        w, h = int(width * k), int(height * k)
        return w - w % 8, h - h % 8
    return width, height


def generation_defaults(settings: dict | None = None) -> dict:
    s = normalize(settings or get_settings())
    return {
        "vae_mode": s["hw_vae_mode"],
        "vae_tile": int(s["hw_vae_tile"]),
        "safe_mode": s["hw_safe_mode"] == "1",
    }


# ---------- restart ComfyUI-ja s novim zastavicama ----------

_RESTART = {"status": "idle", "message": ""}
_RESTART_LOCK = threading.Lock()


def restart_status() -> dict:
    with _RESTART_LOCK:
        return dict(_RESTART)


def restart_comfy(*, comfy_url: str = "", async_: bool = True) -> dict:
    """Ugasi ComfyUI (PID iz comfy.pid ili s porta) i pokreni ga ponovo kroz comfyui-studio.bat s novim zastavicama."""
    with _RESTART_LOCK:
        if _RESTART.get("status") == "running":
            return dict(_RESTART)
        _RESTART.update({"status": "running", "message": "Restartam ComfyUI…"})

    def work():
        try:
            import app_session
            url = comfy_url or os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
            try:
                app_session.restart_marker(inbox.DATA_DIR).parent.mkdir(parents=True, exist_ok=True)
                app_session.restart_marker(inbox.DATA_DIR).write_text("hardware settings", encoding="utf-8")
            except Exception:
                pass
            action = app_session.ensure_fresh_comfy(inbox.DATA_DIR, comfy_url=url)
            import launcher  # lazy: launcher radi os.chdir u mapu aplikacije, što je ista mapa
            launcher.start_comfy_if_needed(wait=False)
            msg = "ComfyUI se ponovo pokreće s novim postavkama (pričekaj 30–90 s)."
            if action == "reuse":
                msg = "ComfyUI nije pokrenut preko Studija pa ga ne mogu ugasiti. Zatvori ga ručno i pokreni Studio ponovo."
            with _RESTART_LOCK:
                _RESTART.update({"status": "done", "message": msg, "action": action})
        except Exception as exc:  # pragma: no cover - ovisi o Windowsu
            with _RESTART_LOCK:
                _RESTART.update({"status": "error", "message": f"Restart nije uspio: {exc}"})

    if async_:
        threading.Thread(target=work, name="comfy-restart", daemon=True).start()
    else:
        work()
    return restart_status()


def public_state(system_stats: dict | None = None) -> dict:
    hp = hardware_profile(system_stats=system_stats)
    s = get_settings()
    vram = {}
    for d in parse_system_stats(system_stats or {}):
        if d.get("vram_bytes"):
            vram = {"total_gb": round(d["vram_bytes"] / 1024 ** 3, 2), "free_gb": round((d.get("vram_free") or 0) / 1024 ** 3, 2), "device": d["name"]}
            break
    try:
        plan = launch_plan("", s)
    except ValueError as exc:
        plan = {"error": str(exc)}
    return {
        "ok": True,
        "settings": s,
        "profile": hp.get("profile"),
        "gpus": hp.get("gpus"),
        "recommended": hp.get("recommended"),
        "effective_backend": effective_backend(s, hp.get("profile")),
        "launch": plan,
        "vram": vram,
        "disable_cudnn": inbox.get_setting("disable_cudnn", "1") != "0",
        "restart": restart_status(),
        "options": {"backends": list(BACKENDS), "vae_modes": list(VAE_MODES), "vram_modes": list(VRAM_MODES)},
    }


# ---------- temperatura GPU-a (LoRA trener, zaštita RX 6600) ----------
#
# Redoslijed na Windowsu: AMD ADL (atiadlxx.dll, ctypes) -> LibreHardwareMonitor / OpenHardwareMonitor WMI
# -> amd-smi / rocm-smi -> nvidia-smi. Na Linuxu: /sys/class/drm/card*/device/hwmon/hwmon*/temp1_input
# -> rocm-smi / amd-smi -> nvidia-smi. Nikad ne izmišljamo broj: ako senzor nije čitljiv, vraćamo
# available=False ("Senzor temperature nedostupan").
#
# Testni hookovi (deterministički): STUDIO_GPU_TEMP=<broj>|none, STUDIO_GPU_TEMP_FILE=<datoteka s brojem>.

_TEMP_LOCK = threading.Lock()
_TEMP_STATE: dict = {"method": None, "fail_until": 0.0, "adl": None, "adl_probe": None}
_TEMP_RETRY_S = 60.0


def _plausible_temp(value) -> float | None:
    try:
        t = float(value)
    except (TypeError, ValueError):
        return None
    if t != t or t <= 0 or t >= 150:
        return None
    return round(t, 1)


def _temp_from_test_hook() -> dict | None:
    path = (os.environ.get("STUDIO_GPU_TEMP_FILE") or "").strip()
    if path:
        try:
            raw = Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            raw = ""
        t = _plausible_temp(raw)
        return _temp_result(t, "test-file")
    fixed = (os.environ.get("STUDIO_GPU_TEMP") or "").strip()
    if fixed:
        t = None if fixed.lower() in {"none", "off", "-"} else _plausible_temp(fixed)
        return _temp_result(t, "test-env")
    return None


def _temp_result(t, source: str) -> dict:
    if t is None:
        return {"available": False, "temp_c": None, "source": "", "message": "Senzor temperature nedostupan"}
    return {"available": True, "temp_c": t, "source": source}


def _read_linux_sysfs(root: str = "/sys/class/drm") -> float | None:
    import glob
    best = None
    for path in sorted(glob.glob(os.path.join(root, "card*", "device", "hwmon", "hwmon*", "temp1_input"))):
        try:
            with open(path, "r", encoding="ascii") as fh:
                raw = fh.read().strip()
            t = _plausible_temp(int(raw) / 1000.0)
        except (OSError, ValueError):
            t = None
        if t is not None and (best is None or t > best):
            best = t
    return best


def parse_nvidia_smi_temp(text: str) -> float | None:
    for line in (text or "").splitlines():
        t = _plausible_temp(line.strip().split(",")[0])
        if t is not None:
            return t
    return None


def parse_rocm_smi_temp(text: str) -> float | None:
    """rocm-smi --showtemp --json ili amd-smi metric -t --json; uzmi rubnu (edge) temperaturu."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        data = None
    found: list[float] = []

    def walk(obj, key=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, str(k).lower())
        elif isinstance(obj, list):
            for v in obj:
                walk(v, key)
        else:
            if "edge" in key or ("temperature" in key and "junction" not in key and "mem" not in key and "hotspot" not in key):
                t = _plausible_temp(obj.get("value") if isinstance(obj, dict) else obj)
                if t is not None:
                    found.append(t)

    if data is not None:
        walk(data)
    else:
        for m in re.finditer(r"(?i)edge\)?\s*\(?C?\)?\s*[:=]\s*([\d.]+)", text or ""):
            t = _plausible_temp(m.group(1))
            if t is not None:
                found.append(t)
    return max(found) if found else None


def parse_lhm_json(text: str) -> float | None:
    """PowerShell (LibreHardwareMonitor/OpenHardwareMonitor WMI) Sensor lista -> GPU temperatura (Core/Edge)."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    if isinstance(data, dict):
        data = [data]
    best = None
    for s in data or []:
        if not isinstance(s, dict):
            continue
        ident = str(s.get("Identifier") or "").lower()
        name = str(s.get("Name") or "").lower()
        if "gpu" not in ident or "hot" in name or "junction" in name or "memory" in name:
            continue
        t = _plausible_temp(s.get("Value"))
        if t is not None and (best is None or t > best):
            best = t
    return best


def _adl_read() -> float | None:
    """AMD ADL preko ctypes. Sve je u try/except; vraća None kad ADL nije dostupan.

    1) ADL2_OverdriveN_Temperature_Get (milistupnjevi) 2) ADL2_New_QueryPMLogData_Get (Overdrive8 / RDNA2,
    senzor PMLOG_TEMPERATURE_EDGE). Prolazi kroz indekse adaptera i uzima prvu uvjerljivu vrijednost.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        st = _TEMP_STATE
        if st.get("adl") is None:
            lib = None
            for dll in ("atiadlxx.dll", "atiadlxy.dll"):
                try:
                    lib = ctypes.WinDLL(dll)
                    break
                except OSError:
                    continue
            if lib is None:
                st["adl"] = False
                return None
            keep: list = []
            alloc_t = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_int)

            def _alloc(size):
                buf = ctypes.create_string_buffer(max(1, int(size)))
                keep.append(buf)
                return ctypes.addressof(buf)

            cb = alloc_t(_alloc)
            ctx = ctypes.c_void_p()
            if lib.ADL2_Main_Control_Create(cb, 1, ctypes.byref(ctx)) != 0:
                st["adl"] = False
                return None
            n = ctypes.c_int(0)
            try:
                lib.ADL2_Adapter_NumberOfAdapters_Get(ctx, ctypes.byref(n))
            except Exception:
                n = ctypes.c_int(1)
            st["adl"] = {"lib": lib, "ctx": ctx, "cb": cb, "keep": keep, "count": max(1, min(16, int(n.value or 1)))}
        adl = st.get("adl")
        if not adl:
            return None
        lib, ctx = adl["lib"], adl["ctx"]
        for idx in range(adl["count"]):
            try:
                temp = ctypes.c_int(0)
                if lib.ADL2_OverdriveN_Temperature_Get(ctx, idx, 1, ctypes.byref(temp)) == 0:
                    t = _plausible_temp(temp.value / 1000.0) or _plausible_temp(temp.value)
                    if t is not None:
                        return t
            except Exception:
                pass
            try:
                # ADLPMLogDataOutput { int size; ADLSingleSensorData sensors[256]; } — veći buffer radi sigurnosti.
                buf = (ctypes.c_int * 4096)()
                buf[0] = 4 + 256 * 8
                if lib.ADL2_New_QueryPMLogData_Get(ctx, idx, ctypes.byref(buf)) == 0:
                    edge = 8  # PMLOG_TEMPERATURE_EDGE
                    supported, value = buf[1 + edge * 2], buf[1 + edge * 2 + 1]
                    if supported:
                        t = _plausible_temp(value)
                        if t is not None:
                            return t
            except Exception:
                pass
    except Exception:
        _TEMP_STATE["adl"] = False
    return None


def _adl_safe() -> float | None:
    """ADL se prvo jednom isproba u zasebnom procesu (ako DLL sruši proces, Studio ostaje živ)."""
    if sys.platform != "win32":
        return None
    st = _TEMP_STATE
    if st.get("adl_probe") is None:
        code = ("import sys; sys.path.insert(0, %r); from services import hardware_service as h; "
                "t = h._adl_read(); print('ADL=' + ('' if t is None else str(t)))") % str(Path(__file__).resolve().parents[1])
        exe = Path(sys.executable)
        if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").is_file():
            exe = exe.with_name("python.exe")
        out = _run([str(exe), "-c", code], timeout=20)
        st["adl_probe"] = "ADL=" in out and bool(out.strip().split("ADL=")[-1].strip())
    if not st["adl_probe"]:
        return None
    return _adl_read()


def _read_windows_wmi() -> float | None:
    for ns in ("root/LibreHardwareMonitor", "root/OpenHardwareMonitor"):
        text = _run([
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            f"Get-CimInstance -Namespace {ns} -ClassName Sensor -ErrorAction SilentlyContinue | "
            "Where-Object { $_.SensorType -eq 'Temperature' } | Select-Object Name,Identifier,Value | ConvertTo-Json -Compress",
        ], timeout=12)
        t = parse_lhm_json(text)
        if t is not None:
            return t
    return None


def _read_smi_tools() -> float | None:
    import shutil as _sh
    if _sh.which("amd-smi"):
        t = parse_rocm_smi_temp(_run(["amd-smi", "metric", "-t", "--json"], timeout=8))
        if t is not None:
            return t
    if _sh.which("rocm-smi"):
        t = parse_rocm_smi_temp(_run(["rocm-smi", "--showtemp", "--json"], timeout=8))
        if t is not None:
            return t
    if _sh.which("nvidia-smi"):
        t = parse_nvidia_smi_temp(_run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"], timeout=8))
        if t is not None:
            return t
    return None


def _temp_methods() -> list[tuple[str, object]]:
    if sys.platform == "win32":
        return [("adl", _adl_safe), ("wmi", _read_windows_wmi), ("smi", _read_smi_tools)]
    return [("sysfs", _read_linux_sysfs), ("smi", _read_smi_tools)]


def read_gpu_temperature() -> dict:
    """{available, temp_c, source}. Ne baca iznimke; ako ništa ne radi, available=False (bez lažnih brojeva)."""
    hook = _temp_from_test_hook()
    if hook is not None:
        return hook
    with _TEMP_LOCK:
        st = _TEMP_STATE
        methods = _temp_methods()
        if st.get("method"):
            methods = [m for m in methods if m[0] == st["method"]] + [m for m in methods if m[0] != st["method"]]
        elif time.time() < st.get("fail_until", 0):
            return {"available": False, "temp_c": None, "source": "", "message": "Senzor temperature nedostupan"}
        for name, fn in methods:
            try:
                t = fn()
            except Exception:
                t = None
            if t is not None:
                st["method"] = name
                return {"available": True, "temp_c": t, "source": name}
        st["method"] = None
        st["fail_until"] = time.time() + _TEMP_RETRY_S
    return {"available": False, "temp_c": None, "source": "", "message": "Senzor temperature nedostupan"}
