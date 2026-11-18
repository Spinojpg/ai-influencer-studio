#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Upiši GITHUB_TOKEN u data/.env, bez ispisa vrijednosti."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def upsert_env(env_path: Path, key: str, value: str) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    found = False
    out: list[str] = []
    for line in lines:
        raw = line.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k = raw.split("=", 1)[0].strip()
            if k == key:
                out.append(f"{key}={value}")
                found = True
                continue
        out.append(line)
    if not found:
        if out and out[-1].strip() != "":
            out.append("")
        out.append(f"{key}={value}")
    text = "\n".join(out)
    if not text.endswith("\n"):
        text += "\n"
    env_path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        print("Koristenje: set_github_token.py DATA_DIR", file=sys.stderr)
        return 2
    data_dir = Path(argv[0])
    token = (os.environ.get("STUDIO_SET_GITHUB_TOKEN") or "").strip()
    if not token and not sys.stdin.isatty():
        token = sys.stdin.read().strip()
    if not token:
        print("Nema tokena — preskacem.")
        return 1
    # Nikad ne ispisuj vrijednost.
    upsert_env(data_dir / ".env", "GITHUB_TOKEN", token)
    print("GITHUB_TOKEN je spremljen u data/.env")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
