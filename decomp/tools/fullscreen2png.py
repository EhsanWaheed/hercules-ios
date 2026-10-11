#!/usr/bin/env python3
"""Convert Hercules full-screen images (TI/, CR/) to PNG.

Format (inferred from the files): an 18-byte header followed by raw 15-bit
PSX pixels. Header bytes 12..15 hold width and height (u16 LE each). A file
may hold several images back to back.

Pixels are little-endian u16: bits 0-4 red, 5-9 green, 10-14 blue, bit 15 the
semi-transparency flag (ignored here).

Usage: fullscreen2png.py OUT_DIR FILE...
"""
import struct
import sys
import zlib
from pathlib import Path

HEADER = 18


def png(path, width, height, rgb_rows):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + row for row in rgb_rows)
    data = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))
    path.write_bytes(data)


def expand5(v):
    return (v << 3) | (v >> 2)


def convert(blob, out_stem):
    written, offset, index = [], 0, 0
    while offset + HEADER <= len(blob):
        width, height = struct.unpack_from("<HH", blob, offset + 12)
        size = width * height * 2
        pixels = blob[offset + HEADER:offset + HEADER + size]
        if not width or not height or len(pixels) != size:
            break
        rows = []
        for y in range(height):
            row = bytearray()
            for (p,) in struct.iter_unpack("<H", pixels[y * width * 2:(y + 1) * width * 2]):
                row += bytes((expand5(p & 31), expand5((p >> 5) & 31), expand5((p >> 10) & 31)))
            rows.append(bytes(row))
        name = out_stem if index == 0 and offset + HEADER + size == len(blob) else f"{out_stem}_{index}"
        target = Path(f"{name}.png")
        png(target, width, height, rows)
        written.append(target)
        offset += HEADER + size
        index += 1
    return written, offset == len(blob)


def main():
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    total, partial = 0, []
    for name in sys.argv[2:]:
        src = Path(name)
        stem = out_dir / f"{src.parent.name}_{src.name.replace('.', '_').rstrip('_')}"
        written, complete = convert(src.read_bytes(), stem)
        total += len(written)
        if not complete:
            partial.append(name)
    print(f"{total} images written to {out_dir}")
    for name in partial:
        print(f"not fully consumed: {name}")


if __name__ == "__main__":
    main()
