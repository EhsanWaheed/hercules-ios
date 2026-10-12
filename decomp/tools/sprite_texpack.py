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

Every block also gets an `STP8` twin (same hashes). Nearly every sprite
colour has the PSX semi-transparency bit set; it only matters for primitives
drawn semi-transparent (shadows, ghost effects), and for those the runtime
prefers the ST image. There, alpha 143 marks a blended texel (the
DuckStation dump convention), 255 an opaque one; without the twin a shadow
would be drawn solid.

P8 images are hard links to sprite_cells.py output (copies across
filesystems); ST images are written.

    python3 tools/sprite_texpack.py CELLS_DIR PACK_DIR
    e.g. assets/sprite_cells/DAT2-schutz
         ~/psx-decomp/HerculesRecomp/build-release/mods/texture-packs/SCES-00893

Writes PACK_DIR/replacements/sprites/<SDx>/<file>/<name>.png.
"""
import argparse
import ctypes
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sprite_cells import ROOT, palette_words  # noqa: E402
from sprites import decode_frame, parse_file  # noqa: E402

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

ST_ALPHA = 143

_lib = ctypes.CDLL(str(Path(__file__).resolve().parent / "native/libxxh3.so"))
_lib.xxh3_64.restype = ctypes.c_ulonglong
_lib.xxh3_64.argtypes = (ctypes.c_char_p, ctypes.c_ulong)


def xxh3(data):
    return _lib.xxh3_64(data, len(data))


def block_name(pixels, pal_words, w, h, mode="P8"):
    top = max(pixels)
    clut = (pal_words * 8)[:2 * (top + 1)]
    return (f"texupload-{mode}-{xxh3(bytes(pixels)):016X}-{xxh3(clut):016X}-"
            f"{w // 2}x{h}-0-0-{w}x{h}-P0-{top}")


def st_image(src, pixels, pal_words, w, h):
    """The HD block with alpha 143 where the original colour has bit 15."""
    img = np.array(Image.open(src).convert("RGBA"))
    words = np.frombuffer(pal_words, "<u2")[np.frombuffer(bytes(pixels), np.uint8).reshape(h, w) & 0x1F]
    stp = (words & 0x8000) != 0
    sy, sx = img.shape[0] // h, img.shape[1] // w
    stp = np.repeat(np.repeat(stp, sy, axis=0), sx, axis=1)
    alpha = img[..., 3]
    img[..., 3] = np.where(alpha == 0, 0, np.where(stp, ST_ALPHA, 255))
    return Image.fromarray(img)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cells", type=Path)
    ap.add_argument("pack", type=Path)
    args = ap.parse_args()
    manifest = json.loads((args.cells / "manifest.json").read_text())
    out_root = args.pack / "replacements/sprites"

    files = {}
    frames = {}
    written = skipped = 0
    names = {}
    for key, info in manifest.items():
        src = args.cells / info["sprite"] / f"{key}.png"
        if not src.exists():
            skipped += 1
            continue
        sprite = info["sprite"]
        if sprite not in files:
            meta = json.loads((ROOT / "assets/sprites" / sprite / "meta.json").read_text())
            data = (ROOT / meta["file"]).read_bytes()
            files[sprite] = (data, parse_file(data))
        data, (_, entries, run_table) = files[sprite]
        fk = (sprite, info["frame"])
        if fk not in frames:
            frames.clear()  # manifest is grouped by frame; keep memory flat
            frames[fk] = decode_frame(data, 4 + (entries[info["frame"] - 1] >> 8), run_table)[1]
        cell = frames[fk][info["cell"]]
        pw = palette_words(data, info["palette"])
        name = block_name(cell["pixels"], pw, cell["w"], cell["h"])
        if name in names:  # same pixels + palette reached from another file
            continue
        names[name] = key
        dst = out_root / sprite / f"{name}.png"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            dst.unlink()
        try:
            os.link(src, dst)
        except OSError:
            shutil.copyfile(src, dst)
        st = out_root / sprite / f"{block_name(cell['pixels'], pw, cell['w'], cell['h'], 'STP8')}.png"
        st_image(src, cell["pixels"], pw, cell["w"], cell["h"]).save(st, compress_level=1)
        written += 1
    print(f"{written} blocks (P8 + STP8 each), {skipped} without image -> {out_root}")


if __name__ == "__main__":
    main()
