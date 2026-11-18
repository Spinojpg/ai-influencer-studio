#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Priprema ComfyUI pokretanja: env, wrapper .bat, mapa modela."""

from __future__ import annotations

import os
import re
from pathlib import Path

DEFAULT_COMFY_DIR = r"C:\ComfyUI-Zluda"
WRAPPER_NAME = "comfyui-studio.bat"
SOURCE_NAME = "comfyui-n.bat"


def comfy_dir() -> Path:
    raw = (os.environ.get("COMFYUI_DIR") or "").strip() or DEFAULT_COMFY_DIR
    return Path(raw)


def checkpoints_dir() -> Path:
    raw = (os.environ.get("COMFYUI_MODELS_DIR") or "").strip()
    if raw:
        return Path(raw)
    return comfy_dir() / "models" / "checkpoints"


def setting_on(raw: str | None, default: bool = True) -> bool:
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() not in {"0", "false", "off", "no", "ne"}


def comfy_process_env(base: dict | None = None, *, disable_cudnn: bool = True) -> dict:
    """Okruženje koje NASLIJEĐUJE python proces ComfyUI-ja (pouzdanije od set u .bat)."""
    env = dict(base if base is not None else os.environ)
    if disable_cudnn:
        env["TORCH_BACKENDS_CUDNN_ENABLED"] = "0"
    return env


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16")
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def strip_auto_launch(text: str) -> str:
    """Makni --auto-launch i iz COMMANDLINE_ARGS=--auto-launch (bez razmaka pred zastavicom)."""
    text = re.sub(r"(?i)(?<=\s)--auto[-_]launch\b(=\S*)?", "", text)
    text = re.sub(r"(?i)(?<==)--auto[-_]launch\b(=\S*)?", "", text)
    text = re.sub(r"(?i)^[ \t]*--auto[-_]launch\b(=\S*)?", "", text, flags=re.M)
    # Ne ostavljaj dvostruke razmake između preostalih argumenata.
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


def strip_pause(text: str) -> str:
    """Makni pause iz wrappera — skriveni proces nema tipkovnicu, log ide u comfyui.log."""
    return re.sub(
        r"(?im)^([ \t]*)pause\b.*$",
        r"\1rem pause removed — output goes to comfyui.log",
        text,
    )


def hidden_comfy_argv(bat: Path) -> list[str]:
    """cmd /c call <bat> — bez vidljive konzole kad se koristi s CREATE_NO_WINDOW."""
    return ["cmd", "/c", "call", str(Path(bat))]


def _win_quote(path: Path) -> str:
    s = str(path).replace('"', "")
    return f'"{s}"'


def windows_start_command(bat: Path, folder: Path, *, keep_open: bool = True) -> str:
    """
    cmd /c start naredba koja:
    - otvori pravi novi konzolni prozor (stdio nije naslijeđen od pythonw),
    - postavi radni dir na ComfyUI mapu (/D) da relativni pushd zluda radi,
    - minimizira prozor.
    """
    bat = Path(bat)
    folder = Path(folder)
    switch = "/k" if keep_open else "/c"
    return (
        f'start "ComfyUI Studio" /MIN /D {_win_quote(folder)} '
        f"cmd {switch} call {_win_quote(bat)}"
    )



ATTN_FLAGS = (
    "--use-split-cross-attention",
    "--use-quad-cross-attention",
    "--use-pytorch-cross-attention",
    "--use-sage-attention",
    "--use-flash-attention",
)
VRAM_FLAGS = ("--lowvram", "--novram", "--highvram", "--normalvram", "--cpu", "--gpu-only")


def text_has_flag(text: str, flag: str) -> bool:
    return re.search(rf"(?i)(?:^|[\s=]){re.escape(flag)}\b", text or "") is not None


def planned_cli_flags(source_text: str, *, low_vram: bool = False, extra: list[str] | None = None) -> list[str]:
    """Zastavice koje dodajemo u wrapper, bez udvostručavanja onih koje su već u originalu."""
    flags: list[str] = []
    if not any(text_has_flag(source_text, f) for f in ATTN_FLAGS):
        flags.append("--use-split-cross-attention")
    if low_vram and not any(text_has_flag(source_text, f) for f in VRAM_FLAGS):
        flags.append("--lowvram")
    for item in extra or []:
        item = (item or "").strip()
        if item and item not in flags and not text_has_flag(source_text, item) and item not in flags:
            flags.append(item)
    return flags


def inject_cli_flags(text: str, flags: list[str]) -> str:
    """Dodaj zastavice u set COMMANDLINE_ARGS= ili na liniju s main.py."""
    to_add = [f for f in flags if f and not text_has_flag(text, f)]
    if not to_add:
        return text
    addition = " ".join(to_add)

    def append_args_line(match: re.Match) -> str:
        line = match.group(0).rstrip("\r\n")
        # Ne diraj nastavak linije sa ^ ili \
        if line.endswith("^") or line.endswith("\\"):
            return match.group(0)
        nl = "\r\n" if match.group(0).endswith("\r\n") else ("\n" if match.group(0).endswith("\n") else "")
        return line + " " + addition + nl

    new, n = re.subn(r"(?im)^[ \t]*set[ \t]+COMMANDLINE_ARGS=.*$", append_args_line, text, count=1)
    if n:
        text = new

        def maybe_main(match: re.Match) -> str:
            line = match.group(0)
            if "COMMANDLINE_ARGS" in line.upper():
                return line
            return append_args_line(match)

        new2, n2 = re.subn(r"(?im)^.*\bmain\.py\b.*$", maybe_main, text, count=1)
        return new2 if n2 else text
    new, n = re.subn(r"(?im)^.*\bmain\.py\b.*$", append_args_line, text, count=1)
    if n:
        return new
    # Ako nema ni COMMANDLINE_ARGS ni main.py, dodaj set na vrh tijela kasnije.
    return text + ("" if text.endswith("\n") else "\n") + f"set COMMANDLINE_ARGS=%COMMANDLINE_ARGS% {addition}\n"


def build_comfy_studio_bat(
    src: Path,
    dest: Path | None = None,
    *,
    disable_cudnn: bool = True,
    low_vram: bool = False,
    extra_flags: list[str] | None = None,
) -> Path:
    """
    Napravi comfyui-studio.bat iz comfyui-n.bat:
    - original se NE mijenja
    - makni --auto-launch (ComfyUI ne otvara svoj 8188 prozor)
    - na vrh stavi set TORCH_BACKENDS_CUDNN_ENABLED=0 ako je uključeno
    - dodaj --use-split-cross-attention (brzina/memorija na RX 6600) ako već nema attention zastavice
    - opcionalno --lowvram ako je uključeno i original nema VRAM zastavicu
    """
    src = Path(src)
    dest = Path(dest) if dest is not None else src.parent / WRAPPER_NAME
    text = _read_text(src)
    text = strip_auto_launch(text)
    text = strip_pause(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    flags = planned_cli_flags(text, low_vram=low_vram, extra=extra_flags)
    text = inject_cli_flags(text, flags)
    # Skinuti vodeći @echo off da ga stavimo jednom na vrh.
    body = text.lstrip("\ufeff")
    if body.lower().startswith("@echo off"):
        body = body.split("\n", 1)[1] if "\n" in body else ""
    header = [
        "@echo off",
        "rem Generated by AI Influencer Studio. Do not edit. Original comfyui-n.bat is unchanged.",
    ]
    if disable_cudnn:
        header.append("set TORCH_BACKENDS_CUDNN_ENABLED=0")
    # Relativni pushd .\zluda i slične naredbe moraju ići iz mape .bat datoteke,
    # ne iz cwd pokretača (često %LOCALAPPDATA%\AIInfluencerStudio\app).
    header.append('cd /d "%~dp0"')
    header.append("")
    out = "\r\n".join(header) + body.replace("\n", "\r\n")
    if not out.endswith("\r\n"):
        out += "\r\n"
    dest.write_bytes(out.encode("utf-8"))
    return dest
