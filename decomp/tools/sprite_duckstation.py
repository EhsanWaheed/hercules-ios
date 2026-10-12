#!/usr/bin/env python3
"""Turn HD sprite blocks into DuckStation texture replacements.

DuckStation (texture cache on, EnableTextureReplacements) names paletted
replacements after hashes of its own VRAM write tracking, which we do not
reproduce. Instead: play with texture dumping enabled, then this tool matches
every dumped `texupload-*.png` against the original sprite blocks (pixel by
pixel, colour 0 = transparent) and copies the HD block (from sprite_cells.py)
into the replacements folder under the dump's name.

    python3 tools/sprite_duckstation.py CELLS_DIR [--game-dir DIR]

CELLS_DIR: output of sprite_cells.py (manifest.json + <sprite>/<key>.png)
--game-dir: DuckStation's textures/<serial> folder (default: Flatpak path
            for SCES-00893); reads dumps/, writes replacements/sprites/.
Dumps that do not match a whole block are listed (sub-rectangles or merged
uploads would need extra handling).
"""
import argparse
import hashlib
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sprite_cells import ORIG, cut_sprite  # noqa: E402

GAME_DIR = Path.home() / ".var/app/org.duckstation.DuckStation/config/duckstation/textures/SCES-00893"


def content_hash(rgba):
    """Hash of an RGBA image with transparent pixels normalised to 0,0,0,0."""
    a = np.array(rgba, np.uint8)
    a[a[..., 3] < 128] = 0
    a[a[..., 3] >= 128, 3] = 255
    return hashlib.blake2b(a.tobytes() + bytes(str(a.shape), "ascii"), digest_size=16).digest()


def original_index():
    """content hash of each original block (palette colours) -> (sprite, key)."""
    index = {}
    for meta_path in sorted(ORIG.glob("*/*/meta.json")):
        for key, _, info in cut_sprite(meta_path, ORIG, 1, verify=True):
            index.setdefault(content_hash(info["expect"]), (info["sprite"], key))
    return index


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cells", type=Path)
    ap.add_argument("--game-dir", type=Path, default=GAME_DIR)
    args = ap.parse_args()

    dumps = sorted((args.game_dir / "dumps").glob("texupload-*.png"))
    if not dumps:
        sys.exit(f"no texupload-*.png in {args.game_dir / 'dumps'}")
    index = original_index()
    out = args.game_dir / "replacements" / "sprites"
    out.mkdir(parents=True, exist_ok=True)
    matched, no_hd, unmatched = 0, 0, []
    for d in dumps:
        with Image.open(d) as im:
            h = content_hash(np.asarray(im.convert("RGBA")))
        hit = index.get(h)
        if hit is None:
            unmatched.append(d.name)
            continue
        src = args.cells / hit[0] / f"{hit[1]}.png"
        if not src.exists():
            no_hd += 1
            continue
        shutil.copyfile(src, out / d.name)
        matched += 1
    print(f"{len(dumps)} dumps: {matched} replaced with HD sprite blocks, "
          f"{no_hd} sprite blocks without HD version, {len(unmatched)} not a sprite block")
    if unmatched:
        (out / "unmatched.txt").write_text("\n".join(unmatched) + "\n")
        print(f"list of unmatched dumps: {out / 'unmatched.txt'}")


if __name__ == "__main__":
    main()
