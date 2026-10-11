#!/usr/bin/env python3
"""Cut every texture the level models use into separate PNGs for upscaling.

Usage: cut_textures.py OUT_DIR LEVEL_FILE...

For each i2.x level, every textured face's record gives a texture page, a
palette (CLUT column) and a UV rectangle. Rectangles with the same page and
palette that overlap or touch are merged, so a background piece drawn with
several quads becomes one image (no seams after upscaling). Each piece is
written as an RGBA PNG (palette index 0 = transparent) using the near,
unfogged CLUT row, see docs/port_plan.md.

OUT_DIR/<level>/manifest.json maps every file to its page, palette and
rectangle -- the texture ID a port uses to find the replacement.
"""
import json
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from level_models import header, parse_model  # noqa: E402
from level_models_tex import CLUT_BASE, NEAR_ROW, page_image, png_rgba  # noqa: E402
from level_vram import VRAM_H, VRAM_W, build_vram  # noqa: E402


def face_rects(data):
    """Yield (tpage, clut_column_bits, (u0, v0, u1, v1)) per textured face."""
    hdr = header(data)
    for off in hdr["models"]:
        try:
            parts, _, _ = parse_model(data, off, hdr["pool"])
        except (ValueError, struct.error):
            continue
        for _verts, faces in parts:
            for ids, _flags, tex in faces:
                if tex >> 24:
                    continue
                uv0, clut, uv1, tpage, uv2, uv3 = struct.unpack_from("<6H", data, hdr["tex"] + tex)
                uvs = [uv0, uv1, uv2, uv3][:len(ids)]
                us, vs = [u & 0xFF for u in uvs], [u >> 8 for u in uvs]
                # PS1 rasterisation excludes the right/bottom edge, but keep it:
                # neighbouring pieces may still sample it after filtering.
                yield tpage & 0x1FF, clut & 0x3F, (min(us), min(vs), max(us) + 1, max(vs) + 1)


def merge(rects):
    """Union rectangles that overlap or touch until none do."""
    rects = [list(r) for r in rects]
    changed = True
    while changed:
        changed = False
        out = []
        for r in rects:
            for m in out:
                if r[0] <= m[2] and m[0] <= r[2] and r[1] <= m[3] and m[1] <= r[3]:
                    m[0], m[1] = min(m[0], r[0]), min(m[1], r[1])
                    m[2], m[3] = max(m[2], r[2]), max(m[3], r[3])
                    changed = True
                    break
            else:
                out.append(r)
        rects = out
    return [tuple(min(v, 256) for v in r) for r in rects]


def cut_level(path, out_root):
    data = Path(path).read_bytes()
    if not data.startswith(b"i2."):
        return None
    stem = Path(path).name.replace(".", "_")
    out = out_root / stem
    out.mkdir(parents=True, exist_ok=True)
    vram = np.array(build_vram(data), dtype=np.uint16).reshape(VRAM_H, VRAM_W)

    groups = {}
    for tpage, col, rect in face_rects(data):
        groups.setdefault((tpage, col), set()).add(rect)

    manifest, pixels = [], 0
    for (tpage, col), rects in sorted(groups.items()):
        clut = (CLUT_BASE + (NEAR_ROW << 6)) | col
        page = page_image(vram, tpage, clut)
        for x0, y0, x1, y1 in sorted(merge(rects)):
            piece = page[y0:y1, x0:x1]
            if not piece[..., 3].any():
                continue                      # fully transparent: nothing to upscale
            name = f"tp{tpage:03x}_cl{col:02x}_{x0:03d}_{y0:03d}_{x1 - x0}x{y1 - y0}.png"
            png_rgba(out / name, np.ascontiguousarray(piece))
            manifest.append({"file": name, "texpage": tpage, "clut_column": col,
                             "depth_bits": 4 if not (tpage >> 7) & 3 else 8,
                             "u": x0, "v": y0, "w": x1 - x0, "h": y1 - y0})
            pixels += (x1 - x0) * (y1 - y0)
    (out / "manifest.json").write_text(json.dumps(
        {"level": Path(path).name, "clut_row": NEAR_ROW, "textures": manifest}, indent=1))
    return len(manifest), pixels


def main():
    out_root = Path(sys.argv[1])
    total = 0
    for name in sys.argv[2:]:
        res = cut_level(name, out_root)
        if res:
            total += res[0]
            print(f"{name}: {res[0]} textures, {res[1]} pixels")
    print(f"total: {total} textures in {out_root}")


if __name__ == "__main__":
    main()
