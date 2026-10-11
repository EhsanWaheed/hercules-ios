#!/usr/bin/env python3
"""Rebuild the VRAM a level uploads and save it as PNG views.

Usage: level_vram.py OUT_DIR LEVEL_FILE...

Only handles the i2.x layout (see docs/level_format.md). For each level:
  <name>_vram16.png       full 1024x512 VRAM as direct 15-bit colour
  <name>_tex{1,2}_4bpp.png texture blocks read as 4-bit indexed, CLUT row 0
  <name>_tex{1,2}_8bpp.png texture blocks read as 8-bit indexed, CLUT row 0
The 4/8-bit views use one palette for everything, so colours are only a
first approximation; which CLUT each texture really uses is not known yet.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fullscreen2png import expand5, png  # noqa: E402

VRAM_W, VRAM_H = 1024, 512
# (header field, VRAM x, y, width, height) from func_80039848
BLOCKS = [(0x14, 384, 0, 384, 512), (0x18, 768, 256, 256, 224), (0x1C, 768, 480, 256, 32)]
CLUT_X, CLUT_Y = 768, 480


def rgb(p):
    return bytes((expand5(p & 31), expand5((p >> 5) & 31), expand5((p >> 10) & 31)))


def build_vram(data):
    vram = [0] * (VRAM_W * VRAM_H)
    for field, x, y, w, h in BLOCKS:
        start = field + struct.unpack_from("<I", data, field)[0]
        block = data[start:start + w * h * 2]
        block += bytes(w * h * 2 - len(block))      # L7: block runs past the file
        for row in range(h):
            words = struct.unpack_from(f"<{w}H", block, row * w * 2)
            vram[(y + row) * VRAM_W + x:(y + row) * VRAM_W + x + w] = words
    return vram


def indexed_view(vram, x, y, w, h, bpp, clut):
    per_word = 16 // bpp
    rows = []
    for row in range(h):
        out = bytearray()
        for word in vram[(y + row) * VRAM_W + x:(y + row) * VRAM_W + x + w]:
            for i in range(per_word):
                out += clut[(word >> (i * bpp)) & ((1 << bpp) - 1)]
        rows.append(bytes(out))
    return w * per_word, h, rows


def main():
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in sys.argv[2:]:
        path = Path(name)
        data = path.read_bytes()
        if not data.startswith(b"i2."):
            print(f"skip {name}: {data[:4]!r} is not the i2.x layout")
            continue
        stem = path.name.replace(".", "_")
        vram = build_vram(data)
        rows = [b"".join(rgb(p) for p in vram[r * VRAM_W:(r + 1) * VRAM_W]) for r in range(VRAM_H)]
        png(out_dir / f"{stem}_vram16.png", VRAM_W, VRAM_H, rows)
        clut = [rgb(p) for p in vram[CLUT_Y * VRAM_W + CLUT_X:CLUT_Y * VRAM_W + CLUT_X + 256]]
        for idx, (_, x, y, w, h) in enumerate(BLOCKS[:2], 1):
            for bpp in (4, 8):
                width, height, view = indexed_view(vram, x, y, w, h, bpp, clut)
                png(out_dir / f"{stem}_tex{idx}_{bpp}bpp.png", width, height, view)
        print(f"wrote {stem}")


if __name__ == "__main__":
    main()
