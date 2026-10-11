#!/usr/bin/env python3
"""Export the models of an i2.x level as textured OBJ + MTL + PNG pages.

Usage: level_models_tex.py OUT_DIR LEVEL_FILE...

Per level OUT_DIR/<level>/ gets one OBJ per model, a shared materials.mtl
and one RGBA PNG per (texture page, palette) pair the models use.

Texture records (header rel 0x28 + face offset, 12 bytes):
  u16 uv0, u16 clut column bits, u16 uv1, u16 texpage, u16 uv2, u16 uv3
The game picks the CLUT row at draw time from depth: clamp(depth / 32, 1,
29), so far faces blend towards the fog colour. This export uses row 1,
the closest (unfogged) shade.
Texpage: bits 0-3 x/64, bit 4 y/256, bits 7-8 colour depth (0 = 4-bit,
1 = 8-bit). CLUT field: x/16 in bits 0-5, y in bits 6-14.
"""
import struct
import sys
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from level_models import header, parse_model  # noqa: E402
from level_vram import VRAM_H, VRAM_W, build_vram  # noqa: E402

CLUT_BASE = 0x7830        # VRAM (768, 480), ORed in by func_80039D34
NEAR_ROW = 1              # depth shade for the closest distance


def png_rgba(path, img):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))
    path.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def to_rgba(words):
    w = words.astype(np.int32)
    rgb = np.stack([(w >> s) & 31 for s in (0, 5, 10)], axis=-1)
    rgb = (rgb << 3 | rgb >> 2).astype(np.uint8)
    alpha = np.where(w == 0, 0, 255).astype(np.uint8)[..., None]   # 0 = transparent
    return np.concatenate([rgb, alpha], axis=-1)


def page_image(vram, tpage, clut):
    px, py = (tpage & 0xF) * 64, ((tpage >> 4) & 1) * 256
    depth = (tpage >> 7) & 3
    cx, cy = (clut & 0x3F) * 16, (clut >> 6) & 0x1FF
    if depth == 0:
        words = vram[py:py + 256, px:px + 64].astype(np.uint16)
        idx = np.empty((256, 256), dtype=np.uint16)
        for i in range(4):
            idx[:, i::4] = (words >> (4 * i)) & 0xF
        pal = vram[cy, cx:cx + 16]
    elif depth == 1:
        words = vram[py:py + 256, px:px + 128].astype(np.uint16)
        idx = np.empty((256, 256), dtype=np.uint16)
        idx[:, 0::2], idx[:, 1::2] = words & 0xFF, words >> 8
        pal = vram[cy, cx:cx + 256]
    else:
        return to_rgba(vram[py:py + 256, px:px + 256])
    return to_rgba(pal[np.minimum(idx, len(pal) - 1)])


def export_level(level_path, out_root):
    data = Path(level_path).read_bytes()
    if not data.startswith(b"i2."):
        return None
    stem = Path(level_path).name.replace(".", "_")
    out = out_root / stem
    out.mkdir(parents=True, exist_ok=True)
    vram = np.array(build_vram(data), dtype=np.uint16).reshape(VRAM_H, VRAM_W)
    row = NEAR_ROW
    hdr = header(data)
    materials = {}            # (tpage, clut) -> name
    count = 0
    for i, off in enumerate(hdr["models"], 1):
        try:
            parts, _, _ = parse_model(data, off, hdr["pool"])
        except (ValueError, struct.error):
            continue
        lines = ["mtllib materials.mtl"]
        vbase, vtbase = 1, 1
        for p, (verts, faces) in enumerate(parts):
            lines.append(f"o part{p}")
            lines += [f"v {x} {-y} {z}" for x, y, z in verts]
            for ids, _flags, tex in faces:
                order = [0, 1, 3, 2] if len(ids) == 4 else [0, 1, 2]
                if tex >> 24:
                    lines.append("usemtl flat")
                    lines.append("f " + " ".join(str(vbase + ids[k]) for k in order))
                    continue
                uv0, clut, uv1, tpage, uv2, uv3 = struct.unpack_from("<6H", data, hdr["tex"] + tex)
                clut = (clut & ~0x7FC0) | ((CLUT_BASE + (row << 6)) & 0x7FC0)
                key = (tpage & 0x1FF, clut)
                if key not in materials:
                    materials[key] = f"tp{key[0]:03x}_cl{key[1]:04x}"
                    png_rgba(out / f"{materials[key]}.png", page_image(vram, *key))
                uvs = [uv0, uv1, uv2, uv3]
                lines.append(f"usemtl {materials[key]}")
                for k in order:
                    u, v = uvs[k] & 0xFF, uvs[k] >> 8
                    lines.append(f"vt {(u + 0.5) / 256:.5f} {1 - (v + 0.5) / 256:.5f}")
                lines.append("f " + " ".join(f"{vbase + ids[k]}/{vtbase + j}"
                                             for j, k in enumerate(order)))
                vtbase += len(order)
            vbase += len(verts)
        (out / f"model{i:03}.obj").write_text("\n".join(lines) + "\n")
        count += 1
    mtl = ["newmtl flat", "Kd 0.6 0.6 0.6", ""]
    for name in materials.values():
        mtl += [f"newmtl {name}", "Kd 1 1 1", f"map_Kd {name}.png", f"map_d {name}.png", ""]
    (out / "materials.mtl").write_text("\n".join(mtl))
    return count, len(materials), row


def main():
    out_root = Path(sys.argv[1])
    for name in sys.argv[2:]:
        res = export_level(name, out_root)
        if res:
            print(f"{name}: {res[0]} models, {res[1]} texture pages, CLUT row {res[2]}")


if __name__ == "__main__":
    main()
