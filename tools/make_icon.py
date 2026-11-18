#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Napravi app.ico iz tools/icon_source.jpg.

Bijela pozadina izvan zaobljenog kvadrata postaje prozirna (anti-alias),
više veličina: 16/24/32/48/64/128/256. Male veličine malo zgušnjavaju zlatne linije.
"""
from __future__ import annotations

import io
import struct
import sys
from pathlib import Path

SIZES = (16, 24, 32, 48, 64, 128, 256)


def _rounded_rect_sdf(hh, ww, x0, y0, x1, y1, rad, np):
    yy, xx = np.ogrid[:hh, :ww]
    x = xx.astype(np.float32) + 0.5
    y = yy.astype(np.float32) + 0.5
    hx = (x1 - x0) / 2.0
    hy = (y1 - y0) / 2.0
    px = np.abs(x - (x0 + x1) / 2.0)
    py = np.abs(y - (y0 + y1) / 2.0)
    qx = px - hx + rad
    qy = py - hy + rad
    outside = np.sqrt(np.maximum(qx, 0) ** 2 + np.maximum(qy, 0) ** 2)
    inside = np.minimum(np.maximum(qx, qy), 0.0)
    return inside + outside - rad


def build_base(src: Path):
    import numpy as np
    from PIL import Image

    im = Image.open(src).convert("RGB")
    arr = np.asarray(im).astype(np.float32)
    h, w, _ = arr.shape
    mn = arr.min(axis=2)
    alpha_raw = np.clip((250.0 - mn) / 20.0, 0.0, 1.0)
    solid = alpha_raw >= 0.6
    ys, xs = np.where(solid)
    if len(xs) == 0:
        raise RuntimeError("U izvoru nisam našao zaobljeni kvadrat (sve je bijelo?).")
    cy, cx = (int(ys.min()) + int(ys.max())) // 2, (int(xs.min()) + int(xs.max())) // 2
    row = solid[cy]
    left = int(np.argmax(row))
    right = int(w - 1 - np.argmax(row[::-1]))
    col = solid[:, cx]
    top = int(np.argmax(col))
    bot = int(h - 1 - np.argmax(col[::-1]))
    top_xs = np.where(solid[top])[0]
    cw, ch = right - left + 1, bot - top + 1
    side0 = min(cw, ch)
    radius = float(np.clip(float(top_xs[0] - left) if len(top_xs) else 0.17 * side0, 0.12 * side0, 0.28 * side0))

    sdf = _rounded_rect_sdf(h, w, float(left), float(top), float(right + 1), float(bot + 1), radius, np)
    mask = np.clip(0.5 - sdf / 1.0, 0.0, 1.0)
    alpha = mask * np.maximum(alpha_raw, (sdf < -1.0).astype(np.float32))
    fg = arr.copy()
    pa = np.clip(alpha_raw, 0, 1)[..., None]
    fringe = (alpha_raw > 0.02) & (alpha_raw < 0.98)
    rec = np.clip((arr - (1.0 - pa) * 255.0) / np.maximum(pa, 1e-6), 0, 255)
    fg[fringe] = rec[fringe]
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., :3] = np.clip(fg, 0, 255).astype(np.uint8)
    rgba[..., 3] = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)

    side = min(cw, ch)
    cx0 = left + (cw - side) // 2
    cy0 = top + (ch - side) // 2
    square = rgba[cy0 : cy0 + side, cx0 : cx0 + side].copy()
    return Image.fromarray(square, "RGBA"), radius, side


def _thicken_gold(img, px: int):
    if px <= 0:
        return img
    import numpy as np
    from PIL import Image, ImageFilter

    a = np.asarray(img).copy()
    rgb, al = a[..., :3].astype(np.int16), a[..., 3]
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    gold = (r > 80) & (r > b + 25) & (g > b) & (al > 80)
    gold_img = Image.fromarray((gold.astype(np.uint8) * 255), "L")
    gold_img = gold_img.filter(ImageFilter.MaxFilter(px * 2 + 1))
    gmask = np.asarray(gold_img) > 0
    if gold.any():
        mean_col = rgb[gold].mean(axis=0)
        paint = gmask & ~gold & (al > 200)
        a[..., :3][paint] = mean_col.astype(np.uint8)
    return Image.fromarray(a, "RGBA")


def render_size(base, radius: float, src_side: int, size: int):
    import numpy as np
    from PIL import Image, ImageEnhance

    src = base
    if size <= 32:
        px = 3 if size <= 16 else (2 if size <= 24 else 1)
        src = _thicken_gold(base, px)
    img = src
    if size < 64:
        mid = max(size * 4, 64)
        img = img.resize((mid, mid), Image.Resampling.LANCZOS)
        rgb = ImageEnhance.Contrast(img.convert("RGB")).enhance(1.08)
        rgb = ImageEnhance.Sharpness(rgb).enhance(1.25)
        out = Image.new("RGBA", img.size)
        out.paste(rgb, mask=img.split()[-1])
        out.putalpha(img.split()[-1])
        img = out
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    a = np.asarray(img).astype(np.float32)
    rad = radius * (size / src_side)
    sdf = _rounded_rect_sdf(size, size, 0.0, 0.0, float(size), float(size), rad, np)
    m = np.clip(0.5 - sdf / 0.85, 0.0, 1.0)
    a[..., 3] = np.clip(a[..., 3] * m, 0, 255)
    return Image.fromarray(a.astype(np.uint8), "RGBA")


def write_ico(path: Path, frames: list) -> None:
    def png_bytes(im) -> bytes:
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    entries = [(im.size[0], png_bytes(im)) for im in frames]
    offset = 6 + 16 * len(entries)
    chunks = [struct.pack("<HHH", 0, 1, len(entries))]
    blobs = []
    for sz, blob in entries:
        bw = 0 if sz >= 256 else sz
        bh = 0 if sz >= 256 else sz
        chunks.append(struct.pack("<BBBBHHII", bw, bh, 0, 0, 1, 32, len(blob), offset))
        blobs.append(blob)
        offset += len(blob)
    path.write_bytes(b"".join(chunks) + b"".join(blobs))


def make_icon(dest: Path, source: Path | None = None) -> Path:
    root = Path(__file__).resolve().parents[1]
    source = Path(source) if source else root / "tools" / "icon_source.jpg"
    if not source.is_file():
        raise SystemExit(f"Nema izvora ikone: {source}")
    dest = Path(dest)
    base, radius, side = build_base(source)
    frames = [render_size(base, radius, side, sz) for sz in SIZES]
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_ico(dest, frames)
    return dest


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    root = Path(__file__).resolve().parents[1]
    dest = Path(argv[0]) if argv else root / "app.ico"
    source = Path(argv[1]) if len(argv) > 1 else root / "tools" / "icon_source.jpg"
    path = make_icon(dest, source)
    print(f"Napisao {path} ({path.stat().st_size} bajtova, veličine {', '.join(str(s) for s in SIZES)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
