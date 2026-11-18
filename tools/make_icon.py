#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Napravi app.ico — jednostavna zlatna ikona portreta."""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path


def png_rgba(w: int, h: int, rgba: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    raw = b"".join(b"\x00" + rgba[y * w * 4 : (y + 1) * w * 4] for y in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def draw(size: int) -> bytes:
    px = bytearray(size * size * 4)

    def put(x, y, r, g, b, a=255):
        if 0 <= x < size and 0 <= y < size:
            i = (y * size + x) * 4
            oa = px[i + 3] / 255.0
            na = a / 255.0
            outa = na + oa * (1 - na)
            if outa <= 0:
                return

            def c(nc, oc):
                return int((nc * na + oc * oa * (1 - na)) / outa)

            px[i] = c(r, px[i])
            px[i + 1] = c(g, px[i + 1])
            px[i + 2] = c(b, px[i + 2])
            px[i + 3] = int(outa * 255)

    pad = size * 0.06
    rad = size * 0.22
    # dark tile
    x0, y0, x1, y1, rad2 = pad, pad, size - pad, size - pad, rad
    for y in range(size):
        for x in range(size):
            cx = min(max(x + 0.5, x0 + rad2), x1 - rad2)
            cy = min(max(y + 0.5, y0 + rad2), y1 - rad2)
            if x0 + rad2 <= x + 0.5 <= x1 - rad2 and y0 + rad2 <= y + 0.5 <= y1 - rad2:
                d = 0.0
            else:
                dx = (x + 0.5) - cx
                dy = (y + 0.5) - cy
                d = (dx * dx + dy * dy) ** 0.5 - rad2
            if d < 1:
                a = 255 if d <= 0 else int(255 * max(0, 1 - d))
                if a:
                    put(x, y, 14, 16, 20, a)

    inset = size * 0.16
    ir = size * 0.18
    x0, y0, x1, y1 = inset, inset, size - inset, size - inset
    for y in range(size):
        ty = (y - y0) / max(1, (y1 - y0))
        ty = min(1, max(0, ty))
        col = (lerp(240, 154, ty * 0.85), lerp(207, 78, ty), lerp(147, 62, ty))
        for x in range(size):
            cx = min(max(x + 0.5, x0 + ir), x1 - ir)
            cy = min(max(y + 0.5, y0 + ir), y1 - ir)
            if x0 + ir <= x + 0.5 <= x1 - ir and y0 + ir <= y + 0.5 <= y1 - ir:
                d = 0.0
            else:
                dx = (x + 0.5) - cx
                dy = (y + 0.5) - cy
                d = (dx * dx + dy * dy) ** 0.5 - ir
            if d < 1 and (x0 - 1 <= x <= x1 + 1 and y0 - 1 <= y <= y1 + 1):
                a = 255 if d <= 0 else int(255 * max(0, 1 - d))
                if a:
                    put(x, y, *col, a)

    ink = (26, 18, 12)
    cx, cy = size / 2, size * 0.46
    rx, ry = size * 0.16, size * 0.20
    stroke = 2.2 * (size / 64)
    for y in range(size):
        for x in range(size):
            nx = (x + 0.5 - cx) / rx
            ny = (y + 0.5 - cy) / ry
            dist = (nx * nx + ny * ny) ** 0.5
            lim = stroke / min(rx, ry)
            if abs(dist - 1.0) < lim:
                t = abs(dist - 1.0) / lim
                a = int(220 * max(0, 1 - t))
                if a:
                    put(x, y, *ink, a)
    scx, scy = size / 2, size * 0.86
    srx, sry = size * 0.28, size * 0.18
    for y in range(size):
        for x in range(size):
            if (y + 0.5) > scy:
                continue
            nx = (x + 0.5 - scx) / srx
            ny = (y + 0.5 - scy) / sry
            dist = (nx * nx + ny * ny) ** 0.5
            lim = stroke / min(srx, sry)
            if abs(dist - 1.0) < lim:
                t = abs(dist - 1.0) / lim
                a = int(200 * max(0, 1 - t))
                if a:
                    put(x, y, *ink, a)
    sx, sy = size * 0.70, size * 0.30
    arm = size * 0.055
    thin = size * 0.012
    for y in range(size):
        for x in range(size):
            dx, dy = x + 0.5 - sx, y + 0.5 - sy
            ax, ay = abs(dx), abs(dy)
            if ax < thin and ay < arm:
                put(x, y, 255, 246, 220, int(255 * max(0, 1 - ay / arm)))
            if ay < thin and ax < arm:
                put(x, y, 255, 246, 220, int(255 * max(0, 1 - ax / arm)))
    return bytes(px)


def write_ico(path: Path, sizes=(16, 32, 48, 64, 256)) -> None:
    pngs = [(s, png_rgba(s, s, draw(s))) for s in sizes]
    count = len(pngs)
    offset = 6 + 16 * count
    entries = b""
    body = b""
    for s, data in pngs:
        w = 0 if s >= 256 else s
        h = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        body += data
    path.write_bytes(struct.pack("<HHH", 0, 1, count) + entries + body)


def main(argv=None) -> int:
    dest = Path(argv[1] if argv and len(argv) > 1 else Path(__file__).resolve().parents[1] / "app.ico")
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_ico(dest)
    print("Napisao", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
