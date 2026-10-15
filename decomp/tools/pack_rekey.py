#!/usr/bin/env python3
"""Reuse an HD pack made for one PAL version on another version's disc.

Replacements are named after the original pixels, so most of a pack fits
every disc as it is: sprite blocks and HUD pieces (texpage names) hash only
their own rectangle. Level textures are the exception: their names start
with the hash of the whole 384x512 texture block (tools/level_texpack.py),
so a level whose block differs in a single pixel (EN: L1, L3, L6) matches
nothing, although almost every texture in it is unchanged.

`rekey` writes a pack for the target disc: every replacement is hard-linked
(copied across file systems) under its name for the target. A level texture
gets the target's block hash in its name when the words of its own rectangle
are the same on the target disc and its palette exists there; textures whose
pixels did change are listed in rekey_report.json and left out (they need a
new upscale, e.g. tools/hd_pack_build.py --base). Nothing is drawn twice.

The rectangle check needs the pack's source pixels: either
replacements/levels/rects.json in the pack (written by level_texpack.py, or
by `describe` for older packs) or the source disc's files (--source-files).

    python3 tools/pack_rekey.py rekey SOURCE_PACK TARGET_FILES OUT_PACK [--source-files DIR]
    python3 tools/pack_rekey.py describe PACK FILES     # add rects.json
"""
import argparse
import ctypes
import json
import os
import re
import shutil
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from level_vram import build_vram  # noqa: E402

BLOCK_X, BLOCK_W, BLOCK_H = 384, 384, 512
CLUT_X, CLUT_Y, CLUT_ROWS = 768, 480, 32
RECTS = "replacements/levels/rects.json"

_lib = ctypes.CDLL(str(Path(__file__).resolve().parent / "native/libxxh3.so"))
_lib.xxh3_64.restype = ctypes.c_ulonglong
_lib.xxh3_64.argtypes = (ctypes.c_char_p, ctypes.c_ulong)
NAME = re.compile(r"texupload-(P4|P8|STP4|STP8)-([0-9A-F]{16})-([0-9A-F]{16})-(\d+)x(\d+)-(\d+)-(\d+)-(\d+)x(\d+)-P(\d+)-(\d+)\.png$")


def xxh3(a):
    b = np.ascontiguousarray(a).astype("<u2").tobytes()
    return f"{_lib.xxh3_64(b, len(b)):016X}"


def level_blocks(files):
    """{block hash: (level, vram)} of every i2.x level on a disc."""
    out = {}
    for p in sorted((Path(files) / "LV").glob("L*.1")):
        try:
            v = np.array(build_vram(p.read_bytes()), np.uint16).reshape(512, 1024)
        except (struct.error, IndexError, ValueError):
            continue
        out[xxh3(v[:BLOCK_H, BLOCK_X:BLOCK_X + BLOCK_W])] = (p.name, v)
    return out


def rect_words(block, m):
    """The block words a texture name's rectangle covers (word-aligned)."""
    per_word = 2 if m[1].endswith("P8") else 4
    x, y, w, h = int(m[6]), int(m[7]), int(m[8]), int(m[9])
    return block[y:y + h, x // per_word:(x + w + per_word - 1) // per_word]


def palettes(vram):
    """xxh3 of every 16- and 256-entry CLUT in the level's CLUT block."""
    return {xxh3(vram[y, x:x + n]) for y in range(CLUT_Y, CLUT_Y + CLUT_ROWS)
            for n in (16, 256) for x in range(CLUT_X, 1024 - n + 1, 16)}


def describe(pack, files):
    """rects.json: {file name: xxh3 of its rectangle's words} for level textures."""
    blocks = level_blocks(files)
    rects = {}
    for f in sorted((Path(pack) / "replacements/levels").rglob("*.png")):
        m = NAME.match(f.name)
        if m and m[2] in blocks:
            v = blocks[m[2]][1]
            rects[f.name] = xxh3(rect_words(v[:BLOCK_H, BLOCK_X:BLOCK_X + BLOCK_W], m))
    (Path(pack) / RECTS).parent.mkdir(parents=True, exist_ok=True)
    (Path(pack) / RECTS).write_text(json.dumps(rects, indent=0) + "\n")
    return len(rects)


def link(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def rekey(source_pack, target_files, out_pack, source_files=None):
    source_pack, out_pack = Path(source_pack), Path(out_pack)
    if out_pack.resolve() == source_pack.resolve():
        raise SystemExit("out pack must be a new folder")
    if source_files:
        rects_path = None
        src_blocks = level_blocks(source_files)
    else:
        rects_path = source_pack / RECTS
        if not rects_path.exists():
            raise SystemExit(f"{rects_path} missing: pass --source-files or run `describe` first")
        rects = json.loads(rects_path.read_text())
    target = level_blocks(target_files)
    by_level = {lv: (h, v) for h, (lv, v) in target.items()}
    tpals = {}
    stats = dict(kept=0, rekeyed=0, changed=0)
    needs_new, out_rects = [], {}
    src_rep, out_rep = source_pack / "replacements", out_pack / "replacements"
    for src in sorted(src_rep.rglob("*.png")):
        rel = src.relative_to(src_rep)
        m = NAME.match(src.name)
        if not m or not rel.parts[0] == "levels":
            link(src, out_rep / rel)       # sprites, HUD: names hash their own pixels
            stats["kept"] += 1
            continue
        if m[2] in target:                 # this level's block is the same on the target
            link(src, out_rep / rel)
            out_rects[src.name] = rects.get(src.name) if not source_files else None
            stats["kept"] += 1
            continue
        level = rel.parts[1].replace("_", ".") if len(rel.parts) > 2 else None
        if level not in by_level:
            stats["changed"] += 1
            needs_new.append(f"{level} {src.name} (level not on target)")
            continue
        thash, tv = by_level[level]
        want = (rects.get(src.name) if not source_files else
                xxh3(rect_words(src_blocks[m[2]][1][:BLOCK_H, BLOCK_X:BLOCK_X + BLOCK_W], m))
                if m[2] in src_blocks else None)
        have = xxh3(rect_words(tv[:BLOCK_H, BLOCK_X:BLOCK_X + BLOCK_W], m))
        if level not in tpals:
            tpals[level] = palettes(tv)
        if want is not None and want == have and m[3] in tpals[level]:
            name = src.name.replace(f"-{m[2]}-", f"-{thash}-", 1)
            link(src, out_rep / rel.parent / name)
            out_rects[name] = have
            stats["rekeyed"] += 1
        else:
            stats["changed"] += 1
            needs_new.append(f"{level} {src.name}" + (" (pixels)" if want != have else " (palette)"))
    if source_files:                       # recompute the kept ones' rects on the target
        out_rects = None
    for f in ("config.yaml",):
        if (source_pack / f).exists():
            shutil.copyfile(source_pack / f, out_pack / f)
    (out_pack / "dumps").mkdir(parents=True, exist_ok=True)
    if out_rects is None:
        describe(out_pack, target_files)
    else:
        (out_pack / RECTS).parent.mkdir(parents=True, exist_ok=True)
        (out_pack / RECTS).write_text(json.dumps(out_rects, indent=0) + "\n")
    report = dict(stats, needs_new=needs_new)
    (out_pack / "rekey_report.json").write_text(json.dumps(report, indent=1))
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rekey")
    r.add_argument("source_pack", type=Path)
    r.add_argument("target_files", type=Path)
    r.add_argument("out_pack", type=Path)
    r.add_argument("--source-files", type=Path, help="source disc files instead of rects.json")
    d = sub.add_parser("describe")
    d.add_argument("pack", type=Path)
    d.add_argument("files", type=Path)
    a = ap.parse_args()
    if a.cmd == "describe":
        print(f"{describe(a.pack, a.files)} level textures described in {a.pack / RECTS}")
        return
    rep = rekey(a.source_pack, a.target_files, a.out_pack, a.source_files)
    print(json.dumps({k: v for k, v in rep.items() if k != "needs_new"}))
    for c in rep["needs_new"][:20]:
        print("  needs new HD:", c)


if __name__ == "__main__":
    main()
