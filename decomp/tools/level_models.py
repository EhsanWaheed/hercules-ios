#!/usr/bin/env python3
"""Parse the 3D models of an i2.x level (see docs/level_format.md).

Usage: level_models.py LEVEL_FILE... [--obj OUT_DIR] [--verbose]

Layout, from ENGINE1 func_80039D34 (draw) and func_8003A184 (vertex unpack):

model record (4-byte aligned, from table group B):
  +0x00 u16  index into the face pool (pool = header rel 0x24), in words
  +0x02 u8   n: number of 8-byte records at +0x0A
  +0x03 u8   size used for culling
  +0x04 u16  animation/matrix parameter (0 = static)
  +0x0A n*8  per-part records (not decoded)
  then per part: s16 vertex count, count * u32 packed vertices
    vertex word: bits 0-7 z (s8), 8-23 x (s16), 24-31 y (s8)
face pool, per part:
  u16 face count, u16 info (high byte: extra index bytes, low byte: more parts)
  faces, 8 bytes each:
    u32 indices: 4 x 6-bit vertex indices (bits 0-23), flags (bits 24-31)
    u32 texture: offset into the texture-record block (header rel 0x28), or a
        flat face if the top byte is non-zero
  info >> 8 extra index bytes, then align to 4
"""
import argparse
import struct
from pathlib import Path

FLAG_QUAD = 0x08    # bit 3 of the face flags: four vertices (see func_80039D34)


def rel(data, off):
    return off + struct.unpack_from("<i", data, off)[0]


def header(data):
    n, e, a, m, c, d = struct.unpack_from("<6H", data, 8)
    table = 0x30 + 4 * n + 16
    return {
        "pool": rel(data, 0x24),
        "tex": rel(data, 0x28),
        "models": [rel(data, table + 4 * (a + i)) for i in range(m)],
    }


def parse_model(data, off, pool_base):
    nrec = data[off + 2]
    pos = off + 0x0A + nrec * 8
    face_pos = pool_base + 4 * struct.unpack_from("<H", data, off)[0]
    parts = []
    while True:
        nverts = struct.unpack_from("<h", data, pos)[0]
        if not 0 < nverts <= 64:
            raise ValueError(f"part {len(parts)}: vertex count {nverts}")
        verts = []
        for (w,) in struct.iter_unpack("<I", data[pos + 2:pos + 2 + 4 * nverts]):
            z = (w & 0xFF) - ((w & 0x80) << 1)
            x = ((w >> 8) & 0xFFFF) - ((w >> 8) & 0x8000) * 2
            y = (w >> 24) - ((w >> 24) & 0x80) * 2
            verts.append((x, y, z))
        pos += 2 + 4 * nverts

        nfaces, info = struct.unpack_from("<HH", data, face_pos)
        face_pos += 4
        faces = []
        for _ in range(nfaces):
            idx, tex = struct.unpack_from("<II", data, face_pos)
            face_pos += 8
            flags = idx >> 24
            ids = [(idx >> (6 * k)) & 0x3F for k in range(4 if flags & FLAG_QUAD else 3)]
            if max(ids) >= nverts:
                raise ValueError(f"part {len(parts)}: face index {max(ids)} >= {nverts}")
            faces.append((ids, flags, tex))
        face_pos += info >> 8
        face_pos = (face_pos + 3) & ~3
        parts.append((verts, faces))
        if not info & 0xFF:
            return parts, pos, face_pos
        pos += 2          # func_80039D34 skips 2 bytes between parts


def write_obj(path, parts):
    lines, base = [], 1
    for p, (verts, faces) in enumerate(parts):
        lines.append(f"o part{p}")
        lines += [f"v {x} {-y} {z}" for x, y, z in verts]
        for ids, _flags, _tex in faces:
            order = [ids[0], ids[1], ids[3], ids[2]] if len(ids) == 4 else ids  # PSX quad order
            lines.append("f " + " ".join(str(base + i) for i in order))
        base += len(verts)
    path.write_text("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("levels", nargs="+")
    ap.add_argument("--obj")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    for name in args.levels:
        data = Path(name).read_bytes()
        if not data.startswith(b"i2."):
            continue
        hdr = header(data)
        ok, errors = 0, []
        for i, off in enumerate(hdr["models"], 1):
            try:
                parts, _end, _fend = parse_model(data, off, hdr["pool"])
            except (ValueError, struct.error) as exc:
                errors.append(f"model {i} @{off:#x}: {exc}")
                continue
            ok += 1
            if args.verbose:
                nv = sum(len(v) for v, _ in parts)
                nf = sum(len(f) for _, f in parts)
                print(f"  model {i:3} @{off:#7x}: {len(parts)} parts, {nv} verts, {nf} faces")
            if args.obj:
                out = Path(args.obj)
                out.mkdir(parents=True, exist_ok=True)
                write_obj(out / f"{Path(name).name.replace('.', '_')}_model{i:03}.obj", parts)
        print(f"{name}: {ok}/{len(hdr['models'])} models parsed")
        for e in errors[:5]:
            print("   ", e)


if __name__ == "__main__":
    main()
