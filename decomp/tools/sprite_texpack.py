#!/usr/bin/env python3
"""Name HD sprite blocks for PSXRecomp's DuckStation-format texture packs.

The port's sprite hook (HerculesRecomp mod `hercules.hd-sprites`) uploads
every decoded block once more as its own w x h rectangle, right after the
game's column upload (docs/sprite_format.md, "VRAM sprite cache"). The pack
then tracks one upload per block, so a replacement is named

    texupload-P8-<xxh3(block bytes)>-<xxh3(CLUT prefix)>-<w/2>x<h>-0-0-<w>x<h>-P0-<max>

- block bytes: the decoded 8-bit indices as the game writes them (upper bits
  included, so indices go up to 255; rows of w bytes, no padding)
- CLUT: a palette row in VRAM holds the 32 colours eight times (checked
  against DuckStation dumps); with a reduced range P0-<max> the hash covers
  the first max+1 words (DuckStation convention, see the PSXRecomp doc
  DUCKSTATION_TEXTURE_FORMAT.md)

Objects pick their palette at run time (obj+0x1E), not from the frame
table: Hercules is drawn with palette 3 of his file in level 1, while the
frames name palette 0. So every block is written for every palette of its
file, recoloured index by index from the upscaled default image (204,704
distinct names). Only the frame's own palette also gets an `STP8` twin: all
twins would exceed the pack loader's 262,144-file limit.

Every default-palette block also gets an `STP8` twin (same hashes). Nearly every sprite
colour has the PSX semi-transparency bit set; it only matters for primitives
drawn semi-transparent (shadows, ghost effects), and for those the runtime
prefers the ST image. There, alpha 143 marks a blended texel (the
DuckStation dump convention), 255 an opaque one; without the twin a shadow
would be drawn solid.

Effects keep their original pixels. The mod skips semi-transparent objects
itself; frames preloaded for all objects (ENGINE1 func_8003D6C0) cannot be
told apart at run time, so their effect frames (EFFECT_FRAMES) get no image.

In VRAM the unused entries of a short palette (file words 0 after index 0)
read 0x8000, not 0: checked against every palette row in level 1 (coins
use S1.2 palette 8, 17 colours). The names hash the words as uploaded.

P8 images are hard links to sprite_cells.py output (copies across
filesystems); ST images are written.

    python3 tools/sprite_texpack.py CELLS_DIR PACK_DIR
    e.g. assets/sprite_cells/DAT2-schutz
         ~/psx-decomp/HerculesRecomp/build-release/mods/texture-packs/SCES-00893

Writes PACK_DIR/replacements/sprites/<SDx>/<file>/<name>.png.
"""
import argparse
import json
import multiprocessing
import os
import shutil
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sprite_cells import ROOT, palette_words  # noqa: E402
from sprites import decode_frame, palettes, parse_file  # noqa: E402

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

ST_ALPHA = 143

# Preloaded effect frames that stay native: (sprite dir, 1-based frame).
# S1.2 preloads frames 1-28 (HUD), 108-129 (coins) and 262-263 (sparkles).
EFFECT_FRAMES = {("SD1/S1_2", 262), ("SD1/S1_2", 263)}

from xxh3 import xxh3  # noqa: E402


def vram_words(pal_words):
    """Palette words as they sit in VRAM: unused entries read 0x8000."""
    w = struct.unpack("<32H", pal_words)
    return struct.pack("<32H", w[0], *(x or 0x8000 for x in w[1:]))


def block_name(pixels, pal_words, w, h, mode="P8"):
    top = max(pixels)
    clut = (pal_words * 8)[:2 * (top + 1)]
    return (f"texupload-{mode}-{xxh3(bytes(pixels)):016X}-{xxh3(clut):016X}-"
            f"{w // 2}x{h}-0-0-{w}x{h}-P0-{top}")


def st_image(src, pixels, pal_words, w, h):
    """The HD block with alpha 143 where the original colour has bit 15."""
    img = np.array((src if isinstance(src, Image.Image) else Image.open(src)).convert("RGBA"))
    words = np.frombuffer(pal_words, "<u2")[np.frombuffer(bytes(pixels), np.uint8).reshape(h, w) & 0x1F]
    stp = (words & 0x8000) != 0
    sy, sx = img.shape[0] // h, img.shape[1] // w
    stp = np.repeat(np.repeat(stp, sy, axis=0), sx, axis=1)
    alpha = img[..., 3]
    img[..., 3] = np.where(alpha == 0, 0, np.where(stp, ST_ALPHA, 255))
    return Image.fromarray(img)


def recolor(src, pixels, w, h, pal_from, pal_to):
    """Map each HD pixel to its palette index (the upscaled original index
    first, else any index with that colour) and paint it from pal_to."""
    img = np.array(Image.open(src).convert("RGBA"))
    sy, sx = img.shape[0] // h, img.shape[1] // w
    idx = np.frombuffer(bytes(pixels), np.uint8).reshape(h, w) & 0x1F
    idx = np.repeat(np.repeat(idx, sy, axis=0), sx, axis=1)
    pf, pt = np.array(pal_from, np.int64), np.array(pal_to, np.uint8)
    key = (img[..., 0].astype(np.int64) << 16) | (img[..., 1].astype(np.int64) << 8) | img[..., 2]
    fkeys = (pf[:, 0] << 16) | (pf[:, 1] << 8) | pf[:, 2]
    by_index = key == fkeys[idx]
    lut = {}
    for j in range(31, 0, -1):  # lowest non-zero index wins
        lut[int(fkeys[j])] = j
    other = np.vectorize(lambda k: lut.get(int(k), -1), otypes=[np.int64])(key[~by_index]) \
        if (~by_index).any() else np.empty(0, np.int64)
    out = img.copy()
    sel = idx[by_index]
    out[by_index, :3] = pt[sel, :3]
    out[by_index, 3] = np.where(img[by_index, 3] == 0, 0, pt[sel, 3])
    rows = np.argwhere(~by_index)
    for (y, x), j in zip(rows, other):
        if j >= 0 and img[y, x, 3]:
            out[y, x] = pt[j]
    return Image.fromarray(out)


def render(job):
    kind, src, dst, pixels, w, h, pal_from, pal_to, pw = job
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    if kind == "link":
        try:
            os.link(src, dst)
        except OSError:
            shutil.copyfile(src, dst)
    elif kind == "st":
        st_image(src, pixels, pw, w, h).save(dst, compress_level=1)
    elif kind == "recolor_st":
        img = recolor(src, pixels, w, h, pal_from, pal_to)
        st_image(img, pixels, pw, w, h).save(dst, compress_level=1)
    else:
        recolor(src, pixels, w, h, pal_from, pal_to).save(dst, compress_level=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cells", type=Path)
    ap.add_argument("pack", type=Path)
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    args = ap.parse_args()
    manifest = json.loads((args.cells / "manifest.json").read_text())
    out_root = args.pack / "replacements/sprites"

    files = {}
    frames = {}
    jobs = []
    skipped = 0
    names = set()
    for key, info in manifest.items():
        src = args.cells / info["sprite"] / f"{key}.png"
        if not src.exists():
            skipped += 1
            continue
        sprite = info["sprite"]
        if any(tuple(f) in EFFECT_FRAMES for f in info["frames"]):
            continue
        if sprite not in files:
            meta = json.loads((ROOT / "assets/sprites" / sprite / "meta.json").read_text())
            data = (ROOT / meta["file"]).read_bytes()
            files[sprite] = (data, parse_file(data), palettes(data))
        data, (_, entries, run_table), rgba = files[sprite]
        fk = (sprite, info["frame"])
        if fk not in frames:
            frames.clear()  # manifest is grouped by frame; keep memory flat
            frames[fk] = decode_frame(data, 4 + (entries[info["frame"] - 1] >> 8), run_table)[1]
        cell = frames[fk][info["cell"]]
        px, w, h = bytes(cell["pixels"]), cell["w"], cell["h"]
        count = struct.unpack_from("<HH", data, 4)[1]
        default = info["palette"] % count
        # A frame naming a palette the file lacks (coins: 200 of 19) is drawn
        # with another one (coins: 8), so its blocks get ST twins in all.
        st_all = info["palette"] >= count
        order = [default] + [p for p in range(count) if p != default]
        for p in order:
            pw = vram_words(palette_words(data, p))
            name = block_name(px, pw, w, h)
            if name in names:  # same pixels + palette reached elsewhere
                continue
            names.add(name)
            dst = str(out_root / sprite / f"{name}.png")
            if p == default:
                jobs.append(("link", str(src), dst, px, w, h, None, None, pw))
                st = str(out_root / sprite / f"{block_name(px, pw, w, h, 'STP8')}.png")
                jobs.append(("st", str(src), st, px, w, h, None, None, pw))
            else:
                jobs.append(("recolor", str(src), dst, px, w, h, rgba[default], rgba[p], pw))
                if st_all:
                    st = str(out_root / sprite / f"{block_name(px, pw, w, h, 'STP8')}.png")
                    jobs.append(("recolor_st", str(src), st, px, w, h, rgba[default], rgba[p], pw))
    print(f"{len(names)} P8 names, {len(jobs)} images to write", flush=True)
    with multiprocessing.Pool(args.workers) as pool:
        for i, _ in enumerate(pool.imap_unordered(render, jobs, chunksize=64), 1):
            if i % 20000 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)
    print(f"{len(jobs)} images, {skipped} blocks without image -> {out_root}")


if __name__ == "__main__":
    main()
