#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimalan WebSocket klijent (stdlib) za ComfyUI /ws progres."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import threading
import time
import urllib.parse
from typing import Any

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OP_CONT = 0x0
OP_TEXT = 0x1
OP_BIN = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


def http_to_ws_url(http_base: str, client_id: str) -> str:
    base = (http_base or "http://127.0.0.1:8188").rstrip("/")
    if base.startswith("https://"):
        ws = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        ws = "ws://" + base[len("http://") :]
    elif base.startswith("ws://") or base.startswith("wss://"):
        ws = base
    else:
        ws = "ws://" + base
    return f"{ws}/ws?clientId={urllib.parse.quote(client_id)}"


def _parse_ws_url(url: str) -> tuple[str, int, str, bool]:
    u = urllib.parse.urlparse(url)
    scheme = (u.scheme or "ws").lower()
    secure = scheme == "wss"
    host = u.hostname or "127.0.0.1"
    port = u.port or (443 if secure else 80)
    path = u.path or "/"
    if u.query:
        path += "?" + u.query
    return host, int(port), path, secure


def accept_key(sec_key: str) -> str:
    digest = hashlib.sha1((sec_key + GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def mask_payload(payload: bytes, key: bytes | None = None) -> tuple[bytes, bytes]:
    if key is None:
        key = os.urandom(4)
    out = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    return key, out


def encode_frame(payload: bytes, opcode: int = OP_TEXT, *, masked: bool = True) -> bytes:
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    first = 0x80 | (opcode & 0x0F)
    length = len(payload)
    if length < 126:
        header = bytes([first, (0x80 if masked else 0x00) | length])
    elif length < 65536:
        header = bytes([first, (0x80 if masked else 0x00) | 126]) + struct.pack("!H", length)
    else:
        header = bytes([first, (0x80 if masked else 0x00) | 127]) + struct.pack("!Q", length)
    if masked:
        key, data = mask_payload(payload)
        return header + key + data
    return header + payload


def decode_frame(buf: bytes) -> tuple[int, bytes, bytes] | None:
    """Vrati (opcode, payload, remainder) ili None ako frame nije potpun."""
    if len(buf) < 2:
        return None
    opcode = buf[0] & 0x0F
    masked = bool(buf[1] & 0x80)
    length = buf[1] & 0x7F
    idx = 2
    if length == 126:
        if len(buf) < 4:
            return None
        length = struct.unpack("!H", buf[2:4])[0]
        idx = 4
    elif length == 127:
        if len(buf) < 10:
            return None
        length = struct.unpack("!Q", buf[2:10])[0]
        idx = 10
    mask_key = b""
    if masked:
        if len(buf) < idx + 4:
            return None
        mask_key = buf[idx : idx + 4]
        idx += 4
    if len(buf) < idx + length:
        return None
    data = buf[idx : idx + length]
    if masked:
        data = bytes(b ^ mask_key[i % 4] for i, b in enumerate(data))
    return opcode, data, buf[idx + length :]


class WebSocketClient:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self._buf = b""

    @classmethod
    def connect(cls, url: str, timeout: float = 8.0) -> "WebSocketClient":
        host, port, path, secure = _parse_ws_url(url)
        raw = socket.create_connection((host, port), timeout=timeout)
        if secure:
            import ssl

            ctx = ssl.create_default_context()
            raw = ctx.wrap_socket(raw, server_hostname=host)
        raw.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        raw.sendall(req.encode("ascii"))
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = raw.recv(4096)
            if not chunk:
                raw.close()
                raise ConnectionError("WebSocket rukovanje je prekinuto.")
            header += chunk
            if len(header) > 16_384:
                raw.close()
                raise ConnectionError("WebSocket rukovanje je predugačko.")
        head, rest = header.split(b"\r\n\r\n", 1)
        status_line = head.split(b"\r\n", 1)[0].decode("ascii", "replace")
        if "101" not in status_line:
            raw.close()
            raise ConnectionError(f"WebSocket nije prihvaćen: {status_line}")
        # Provjeri Accept ako postoji.
        expected = accept_key(key).encode("ascii")
        if b"sec-websocket-accept:" in head.lower() and expected.lower() not in head.lower():
            raw.close()
            raise ConnectionError("WebSocket Accept ključ se ne podudara.")
        client = cls(raw)
        client._buf = rest
        return client

    def send(self, payload: bytes, opcode: int = OP_TEXT) -> None:
        self.sock.sendall(encode_frame(payload, opcode, masked=True))

    def send_text(self, text: str) -> None:
        self.send(text.encode("utf-8"), OP_TEXT)

    def ping_pong(self, payload: bytes, opcode: int) -> None:
        self.send(payload, opcode)

    def close(self) -> None:
        try:
            self.sock.sendall(encode_frame(b"", OP_CLOSE, masked=True))
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass

    def recv(self, timeout: float | None = None) -> tuple[int, bytes] | None:
        if timeout is not None:
            self.sock.settimeout(timeout)
        while True:
            parsed = decode_frame(self._buf)
            if parsed is None:
                try:
                    chunk = self.sock.recv(4096)
                except socket.timeout:
                    return None
                if not chunk:
                    raise ConnectionError("WebSocket zatvoren.")
                self._buf += chunk
                continue
            opcode, data, rest = parsed
            self._buf = rest
            if opcode == OP_CONT:
                # Jednostavan klijent: tretiraj kao tekst ako je već spojeno.
                return opcode, data
            if opcode == OP_PING:
                try:
                    self.ping_pong(data, OP_PONG)
                except Exception:
                    pass
                continue
            if opcode == OP_PONG:
                continue
            return opcode, data


class ProgressWatcher:
    """Pozadinska nit: sluša ComfyUI /ws i pamti progress/executing."""

    def __init__(self, http_base: str, client_id: str) -> None:
        self.http_base = http_base
        self.client_id = client_id
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = {
            "connected": False,
            "value": 0,
            "max": 1,
            "prompt_id": None,
            "node": None,
            "updated": 0.0,
            "last_type": None,
            "error": None,
        }
        self._by_prompt: dict[str, dict[str, Any]] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="comfy-ws", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self, prompt_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            base = dict(self._state)
            if prompt_id and prompt_id in self._by_prompt:
                merged = dict(base)
                merged.update(self._by_prompt[prompt_id])
                return merged
            return base

    def _update(self, **kwargs: Any) -> None:
        with self._lock:
            self._state.update(kwargs)
            self._state["updated"] = time.time()
            pid = kwargs.get("prompt_id") or self._state.get("prompt_id")
            if pid:
                rec = self._by_prompt.setdefault(str(pid), {})
                rec.update(kwargs)
                rec["updated"] = self._state["updated"]

    def handle_message(self, msg: dict) -> None:
        """Javno radi testova: obradi jednu ComfyUI poruku."""
        typ = msg.get("type")
        data = msg.get("data") or {}
        if not isinstance(data, dict):
            data = {}
        if typ == "progress":
            value = data.get("value")
            maximum = data.get("max")
            try:
                value_f = float(value)
                max_f = float(maximum if maximum not in (None, 0) else 1)
            except (TypeError, ValueError):
                return
            self._update(
                value=value_f,
                max=max_f or 1,
                prompt_id=data.get("prompt_id") or self._state.get("prompt_id"),
                last_type="progress",
            )
        elif typ == "executing":
            node = data.get("node")
            pid = data.get("prompt_id")
            # node je None kad je izvršavanje gotovo.
            self._update(
                prompt_id=pid or self._state.get("prompt_id"),
                node=node,
                last_type="executing",
                finished=node is None,
            )
        elif typ in {"executed", "execution_cached", "execution_success"}:
            self._update(
                prompt_id=data.get("prompt_id") or self._state.get("prompt_id"),
                last_type=typ,
            )
        elif typ in {"execution_error", "execution_interrupted"}:
            err = data.get("exception_message") or data.get("message") or typ
            self._update(
                prompt_id=data.get("prompt_id") or self._state.get("prompt_id"),
                last_type=typ,
                error=str(err),
            )

    def _run(self) -> None:
        delay = 1.0
        while not self._stop.is_set():
            ws = None
            try:
                url = http_to_ws_url(self.http_base, self.client_id)
                ws = WebSocketClient.connect(url, timeout=8)
                self._update(connected=True, error=None)
                delay = 1.0
                while not self._stop.is_set():
                    frame = ws.recv(timeout=1.0)
                    if frame is None:
                        continue
                    opcode, payload = frame
                    if opcode == OP_CLOSE:
                        break
                    if opcode == OP_BIN:
                        continue
                    if opcode not in {OP_TEXT, OP_CONT}:
                        continue
                    try:
                        msg = json.loads(payload.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if isinstance(msg, dict):
                        self.handle_message(msg)
            except Exception as exc:
                self._update(connected=False, error=str(exc)[:300])
            finally:
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:
                        pass
            if self._stop.is_set():
                break
            self._stop.wait(delay)
            delay = min(delay * 1.5, 8.0)


_watcher: ProgressWatcher | None = None
_watcher_lock = threading.Lock()


def start_watcher(http_base: str, client_id: str) -> ProgressWatcher:
    global _watcher
    with _watcher_lock:
        if _watcher is None:
            _watcher = ProgressWatcher(http_base, client_id)
            _watcher.start()
        return _watcher


def stop_watcher() -> None:
    global _watcher
    with _watcher_lock:
        if _watcher is not None:
            _watcher.stop()
            _watcher = None


def progress_for(prompt_id: str | None = None) -> dict[str, Any]:
    w = _watcher
    if w is None:
        return {"connected": False, "value": 0, "max": 1}
    return w.snapshot(prompt_id)
