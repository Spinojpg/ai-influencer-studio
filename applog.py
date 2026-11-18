#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Logovi u data/logs i siguran stdout/stderr (pythonw: oba su None)."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED: dict[str, Path] = {}


class _LogWriter:
    """File-like objekt koji ide u logging, opcionalno i na stari stream."""

    encoding = "utf-8"
    errors = "replace"
    closed = False
    name = "<studio-log>"

    def __init__(self, logger: logging.Logger, level: int, also=None) -> None:
        self.logger = logger
        self.level = level
        self.also = also if _usable(also) else None
        self._buf = ""

    def write(self, msg) -> int:
        if not msg:
            return 0
        if isinstance(msg, bytes):
            msg = msg.decode(self.encoding, errors=self.errors)
        if self.also is not None:
            try:
                self.also.write(msg)
                self.also.flush()
            except Exception:
                self.also = None
        self._buf += msg
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            text = line.rstrip("\r")
            if text:
                try:
                    self.logger.log(self.level, text)
                except Exception:
                    pass
        return len(msg) if isinstance(msg, (str, bytes)) else 0

    def flush(self) -> None:
        leftover = self._buf.rstrip("\r")
        self._buf = ""
        if leftover.strip():
            try:
                self.logger.log(self.level, leftover)
            except Exception:
                pass
        if self.also is not None:
            try:
                self.also.flush()
            except Exception:
                self.also = None

    def isatty(self) -> bool:
        return False

    def reconfigure(self, **_kwargs) -> None:
        return None

    def close(self) -> None:
        self.flush()

    def fileno(self) -> int:
        raise OSError("log writer has no fileno")

    def readable(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False


def _usable(stream) -> bool:
    if stream is None:
        return False
    write = getattr(stream, "write", None)
    if not callable(write):
        return False
    try:
        closed = getattr(stream, "closed", False)
        if closed:
            return False
    except Exception:
        return False
    return True


def logs_dir(data_dir: Path) -> Path:
    path = Path(data_dir) / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def setup(data_dir: Path, name: str, *, force_redirect: bool | None = None) -> Path:
    """
    Rotirajući log u data/logs/<name>.log.
    Ako je stdout/stderr None (pythonw) ili force_redirect, preusmjeri ih u log.
    Inače (vidljivi cmd) ispis ostaje na konzoli i ide i u datoteku.
    """
    data_dir = Path(data_dir)
    path = logs_dir(data_dir) / f"{name}.log"
    if _CONFIGURED.get(name) == path.resolve() and _usable(sys.stdout) and _usable(sys.stderr):
        return path

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # Izbjegni duple handlere pri ponovnom pozivu.
    for h in list(logger.handlers):
        if isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", "") == str(path):
            break
    else:
        handler = RotatingFileHandler(
            path,
            maxBytes=2_000_000,
            backupCount=5,
            encoding="utf-8",
            delay=True,
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
        )
        logger.addHandler(handler)

    if force_redirect is None:
        force_redirect = (
            os.environ.get("STUDIO_FORCE_LOG") == "1"
            or not _usable(sys.stdout)
            or not _usable(sys.stderr)
        )

    # Uvijek zamijeni neupotrebljive streamove. Ako je konzola živa, tee u log.
    out_also = None if (force_redirect or not _usable(sys.stdout)) else sys.stdout
    err_also = None if (force_redirect or not _usable(sys.stderr)) else sys.stderr
    # Ako već jesu naši writeri, ne umataj ponovno.
    if not isinstance(sys.stdout, _LogWriter):
        sys.stdout = _LogWriter(logger, logging.INFO, also=out_also)
    if not isinstance(sys.stderr, _LogWriter):
        sys.stderr = _LogWriter(logger, logging.ERROR, also=err_also)

    _CONFIGURED[name] = path.resolve()
    try:
        logger.info("Log je spreman: %s", path)
    except Exception:
        pass
    return path


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def safe_stdio() -> None:
    """Nakon setupa: UTF-8 na pravim konzolnim streamovima, bez rušenja ako je None."""
    for stream in (sys.stdout, sys.stderr):
        if not _usable(stream):
            continue
        reconf = getattr(stream, "reconfigure", None)
        if not callable(reconf):
            continue
        try:
            reconf(encoding="utf-8", errors="replace")
        except Exception:
            pass
