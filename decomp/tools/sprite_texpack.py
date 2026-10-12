#!/usr/bin/env python3
"""Name HD sprite blocks for PSXRecomp's DuckStation-format texture packs.

The port's sprite hook (HerculesRecomp mod `hercules.sprite-blocks`) uploads
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

Images are hard links to sprite_cells.py output (copies across filesystems).

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

_lib = ctypes.CDLL(str(Path(__file__).resolve().parent / "native/libxxh3.so"))
_lib.xxh3_64.restype = ctypes.c_ulonglong
_lib.xxh3_64.argtypes = (ctypes.c_char_p, ctypes.c_ulong)


def xxh3(data):
    return _lib.xxh3_64(data, len(data))


def block_name(pixels, pal_words, w, h):
    top = max(pixels)
    clut = (pal_words * 8)[:2 * (top + 1)]
    return (f"texupload-P8-{xxh3(bytes(pixels)):016X}-{xxh3(clut):016X}-"
            f"{w // 2}x{h}-0-0-{w}x{h}-P0-{top}")


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
        name = block_name(cell["pixels"], palette_words(data, info["palette"]), cell["w"], cell["h"])
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
        written += 1
    print(f"{written} replacements, {skipped} blocks without image -> {out_root}")


if __name__ == "__main__":
    main()
