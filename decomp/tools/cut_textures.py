#!/usr/bin/env python3
"""Cut every texture the level models use into separate PNGs for upscaling.

Usage: cut_textures.py OUT_DIR LEVEL_FILE...

For each i2.x level, every textured face (models and tiles) gives a texture page, a
palette (CLUT column) and a UV rectangle. Rectangles with the same page and
palette that overlap or touch are merged, so a background piece drawn with
several quads becomes one image (no seams after upscaling). Each piece is
written as an RGBA PNG (palette index 0 = transparent) using the near,
unfogged CLUT row (fog: 31 depth rows, row = clamp(depth / 32, 1, 29)).

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


def textured_faces(data, hdr):
    """Yield (vertex count, texture-record offset) for every textured face.

    Models (group B): flat if the texture word's top byte is non-zero.
    Tiles (group A, see tile_faces): flat if face flag bit 7 is set; the top
    byte of the texture word is an ordering-table depth bias there.
    """
    for off in hdr["models"]:
        try:
            parts, _, _ = parse_model(data, off, hdr["pool"])
        except (ValueError, struct.error):
            continue
        for _verts, faces in parts:
            for ids, _flags, tex in faces:
                if not tex >> 24:
                    yield len(ids), tex
    for _index, faces in tile_faces(data):
        for ids, flags, tex in faces:
            if not flags & 0x80:
                yield len(ids), tex & 0xFFFF


def tile_faces(data):
    """Yield (tile index, faces) for the level's tile set (table group A).

    From ENGINE1 func_800459C0: entry i (1-based) at group A + (i-1)*4; its
    first s16 * 4 is the offset to the tile definition:
      s16 type, u8 vertex count, u8 face count, vertices (u32 each, same
      packing as models), one u32, then 8-byte faces like the models'.
    """
    n, _e, a, _m, _c, _d = struct.unpack_from("<6H", data, 8)
    base = 0x30 + 4 * n + 16
    for i in range(a):
        entry = base + 4 * i
        tile = entry + 4 * struct.unpack_from("<h", data, entry)[0]
        nverts, nfaces = data[tile + 2], data[tile + 3]
        pos = tile + 4 + 4 * nverts + 4
        faces = []
        for k in range(nfaces):
            idx, tex = struct.unpack_from("<II", data, pos + 8 * k)
            flags = idx >> 24
            ids = [(idx >> (6 * j)) & 0x3F for j in range(4 if flags & 0x08 else 3)]
            if max(ids) >= nverts:
                break                  # not a valid tile (empty placeholder)
            faces.append((ids, flags, tex))
        else:
            yield i + 1, faces


def face_rects(data):
    """Yield (tpage, clut_column_bits, (u0, v0, u1, v1)) per textured face."""
    hdr = header(data)
    for nids, tex in textured_faces(data, hdr):
        uv0, clut, uv1, tpage, uv2, uv3 = struct.unpack_from("<6H", data, hdr["tex"] + tex)
        uvs = [uv0, uv1, uv2, uv3][:nids]
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
