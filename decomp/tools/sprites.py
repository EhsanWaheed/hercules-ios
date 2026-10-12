#!/usr/bin/env python3
"""Decode Hercules sprite files (SD1/, SD3/, SD4/; tag `i1.4`).

Usage: sprites.py check FILE...        validate decoding of every frame
       sprites.py dump OUT_DIR FILE... decode cells to raw index data + JSON

Reimplements ENGINE1 func_8003FF1C (decompressor) and the cell handling of
func_8003F9D4; see docs/sprite_format.md for the format.
"""
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE1 = ROOT / "files/EX/ENGINE1."
ENGINE1_BASE = 0x80038350
DIST_TABLE = 0x8006AB3B        # D_8006AB3B: back-reference distances


def load_dist_table():
    exe = ENGINE1.read_bytes()
    off = DIST_TABLE - ENGINE1_BASE + 0x800
    return exe[off:off + 0x48]


DIST = load_dist_table()


class DecodeError(Exception):
    pass


def decompress(data, pos, out_len, dist_sel, run_table):
    """Exact port of func_8003FF1C. Returns (bytes, new pos)."""
    out = bytearray()

    def word():
        nonlocal pos
        if pos + 2 > len(data):
            raise DecodeError("stream overrun")
        w = data[pos] | data[pos + 1] << 8
        pos += 2
        return w

    def put(*vals):
        out.extend(v & 0xFF for v in vals)

    def control(c):
        """Handle one control byte. Returns a control byte to process next
        (the literal tail's high byte), or None to read on."""
        if c & 0x80:
            v = run_table[(c >> 4) & 7]
            put(*([v] * ((c & 0xF) + 3)))
        elif c & 0x40:
            if c & 0x20:
                put(*([0] * ((c & 0x1F) + 4)))
            else:
                for _ in range(c & 0x1F):
                    w = word()
                    put(w, w >> 6, w >> 11)
                t = word()
                put(t)
                if t & 0x20:
                    if t & 0x40:
                        if len(out) < out_len:
                            return (t >> 8) & 0xFF
                    else:
                        put(t >> 8)
                else:
                    put(t >> 6, t >> 11)
        else:
            dist = DIST[dist_sel + (c & 0xFC)]
            if dist == 0 or dist > len(out):
                raise DecodeError(f"bad back-reference distance {dist} at {len(out)}")
            src = len(out) - dist
            for k in range((c & 3) + 3):
                out.append(out[src + k])
        return None

    def process(c):
        # A literal tail may chain one more control byte (its own high byte);
        # the asm then still goes on with the original word's high byte.
        while c is not None:
            c = control(c)

    while len(out) < out_len:
        w = word()
        process(w & 0xFF)
        if len(out) >= out_len:
            break
        process(w >> 8)
    if len(out) < out_len:
        raise DecodeError("short output")
    return bytes(out[:out_len]), pos


def parse_file(data):
    if data[:4] != b"i1.4":
        raise DecodeError("not an i1.4 file")
    n = struct.unpack_from("<H", data, 4)[0]
    entries = [struct.unpack_from("<I", data, 4 + 4 * k)[0] for k in range(1, n + 1)]
    run_table = data[8 + 4 * n:16 + 4 * n]
    return n, entries, run_table


def decode_frame(data, off, run_table, raw=False):
    """Decode one frame. Returns (header dict, cells, end position)."""
    count, extra = data[off], struct.unpack_from("<b", data, off + 1)[0]
    head = data[off + 2:off + 8]
    extra_data = data[off + 8:off + 8 + 6 * extra] if extra > 0 else b""
    cells_at = off + 8 + 6 * max(extra, 0)
    pos = cells_at + 4 * count
    cells = []
    for i in range(count):
        desc = data[cells_at + 4 * i:cells_at + 4 * i + 4]
        b = desc[0]
        width = ((b & 3) + 1) * 8
        height = (((b & 0xC) >> 2) + 1) * 8
        if b & 0x80:
            # func_8003F9D4 only decodes cells without bit 7; these carry no
            # pixel data of their own (presumably reuse another cell).
            cells.append({"desc": desc.hex(), "w": width, "h": height, "pixels": None})
            continue
        if raw:
            pix = data[pos:pos + width * height]
            pos += width * height
        else:
            pix, pos = decompress(data, pos, width * height, (b & 3) + 1, run_table)
        cells.append({"desc": desc.hex(), "w": width, "h": height, "pixels": pix})
    return {"count": count, "extra": extra, "head": head.hex(),
            "extra_data": extra_data.hex()}, cells, pos


def frame_bounds(data, entries):
    starts = sorted({4 + (e >> 8) for e in entries if e >> 8})
    return starts + [len(data)]


def check(paths):
    total = good = 0
    for p in paths:
        data = Path(p).read_bytes()
        n, entries, run_table = parse_file(data)
        bounds = frame_bounds(data, entries)
        ok = bad = 0
        first_err = None
        empty = 0
        for k, e in enumerate(entries, 1):
            if e >> 8 == 0:
                empty += 1             # entry 0 = no frame in this slot
                continue
            off = 4 + (e >> 8)
            nxt = next(b for b in bounds if b > off)
            try:
                _h, _cells, end = decode_frame(data, off, run_table)
                if 0 <= nxt - end < 4:
                    ok += 1
                    continue
                raise DecodeError(f"ends at {end:#x}, next frame at {nxt:#x}")
            except (DecodeError, IndexError, struct.error) as exc:
                bad += 1
                if first_err is None:
                    first_err = f"frame {k} @{off:#x}: {exc}"
        total += n - empty
        good += ok
        print(f"{p}: {ok}/{n - empty} frames decode exactly ({empty} empty slots)"
              + (f"  first error: {first_err}" if first_err else ""))
    print(f"total: {good}/{total}")


def palettes(data):
    """The file's m palettes (32 colours each) as RGBA lists; colour 0 is clear."""
    n, m = struct.unpack_from("<HH", data, 4)
    table = 16 + 4 * n
    out = []
    for i in range(m):
        base = 4 + struct.unpack_from("<H", data, table + 2 * i)[0] + 4   # skip 0x20,0x20 header
        cols = []
        for j in range(32):
            c = struct.unpack_from("<H", data, base + 2 * j)[0]
            r, g, b = c & 31, (c >> 5) & 31, (c >> 10) & 31
            cols.append((r << 3 | r >> 2, g << 3 | g >> 2, b << 3 | b >> 2, 0 if c == 0 else 255))
        out.append(cols)
    return out


def dump(out_root, paths):
    """Assemble every frame from its cells and write PNG + meta.json per file.

    Cell descriptor bytes 2/3 are signed x/y offsets from the frame's anchor;
    pixels are 5-bit palette indices (upper bits are leftovers of the packing).
    """
    import hashlib

    import numpy as np
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from level_models_tex import png_rgba

    for p in paths:
        data = Path(p).read_bytes()
        n, entries, run_table = parse_file(data)
        pals = palettes(data)
        out = Path(out_root) / Path(p).parent.name / Path(p).name.replace(".", "_")
        out.mkdir(parents=True, exist_ok=True)
        seen, frames = {}, []
        for k, e in enumerate(entries, 1):
            if not e >> 8:
                frames.append({"frame": k, "empty": True})
                continue
            off = 4 + (e >> 8)
            pal_index = e & 0xFF
            info = {"frame": k, "palette": pal_index}
            if pal_index >= len(pals):
                info["palette_out_of_range"] = True
            try:
                head, cells, end = decode_frame(data, off, run_table)
            except (DecodeError, IndexError, struct.error) as exc:
                info["error"] = str(exc)
                frames.append(info)
                continue
            key = hashlib.md5(data[off:end] + bytes([pal_index])).hexdigest()
            if key in seen:
                info["same_as"] = seen[key]
                frames.append(info)
                continue
            seen[key] = k
            placed = []
            for c in cells:
                d = bytes.fromhex(c["desc"])
                x, y = struct.unpack("<bb", d[2:4])
                placed.append((x, y, c))
            drawn = [(x, y, c) for x, y, c in placed if c["pixels"] is not None]
            info.update(head)
            info["cells"] = [{"desc": c["desc"], "x": x, "y": y, "w": c["w"], "h": c["h"],
                              "has_pixels": c["pixels"] is not None} for x, y, c in placed]
            if drawn:
                x0 = min(x for x, _, _ in drawn)
                y0 = min(y for _, y, _ in drawn)
                x1 = max(x + c["w"] for x, _, c in drawn)
                y1 = max(y + c["h"] for _, y, c in drawn)
                img = np.zeros((y1 - y0, x1 - x0, 4), dtype=np.uint8)
                pal = np.array(pals[pal_index % len(pals)], dtype=np.uint8)
                for x, y, c in drawn:
                    idx = np.frombuffer(c["pixels"], dtype=np.uint8).reshape(c["h"], c["w"]) & 0x1F
                    rgba = pal[idx]
                    region = img[y - y0:y - y0 + c["h"], x - x0:x - x0 + c["w"]]
                    mask = idx != 0
                    region[mask] = rgba[mask]
                info["png"] = f"f{k:04d}.png"
                info["anchor"] = [-x0, -y0]        # anchor position inside the PNG
                info["size"] = [x1 - x0, y1 - y0]
                png_rgba(out / info["png"], img)
            frames.append(info)
        (out / "meta.json").write_text(json.dumps({"file": p, "frames": frames}, indent=1))
        written = sum(1 for f in frames if "png" in f)
        print(f"{p}: {written} unique frames written, {n} slots")


def main():
    if sys.argv[1] == "check":
        check(sys.argv[2:])
    elif sys.argv[1] == "dump":
        dump(sys.argv[2], sys.argv[3:])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
