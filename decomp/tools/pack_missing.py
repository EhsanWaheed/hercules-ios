#!/usr/bin/env python3
"""What an HD pack still lacks for one disc, before anything is upscaled.

Replacement names depend only on the original pixels and palettes, so they
can be computed from the disc: a sprite frame needs upscaling when one of its
blocks has no image at all (sprite_texpack.py writes every block in every
palette of its file from one upscale, so any palette counts; some frame
headers name a palette the file does not have), a
cut level texture when none of its fog-level names (level_texpack.py) is in
the pack. hd_pack_build.py --base uses this to upscale only what the reused
pack does not cover.

Run in a work tree (HERC_ROOT) with files/, assets/sprites/ (sprites.py
dump) and assets/textures_cut/ (cut_textures.py):

    HERC_ROOT=WORK python3 tools/pack_missing.py PACK OUT.json
    HERC_ROOT=WORK python3 tools/pack_missing.py PACK --prune

OUT.json: {"sprites": ["SD4/S4_1/f0001.png", ...],
           "levels": ["L1_1/tp026_cl02_000_000_128x128.png", ...]}
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sprite_cells import ROOT, palette_words  # noqa: E402
from sprite_texpack import EFFECT_FRAMES, block_name  # noqa: E402
from sprites import decode_frame, parse_file  # noqa: E402
import level_texpack  # noqa: E402


def pack_names(pack, kind):
    return {p.stem for p in (Path(pack) / "replacements" / kind).rglob("*.png")}


def pixel_hash(name):
    """texupload-P8-<pixels>-<palette>-...: the block's own part of a name."""
    return name.split("-")[2]


def disc_sprite_hashes():
    """Pixel hashes of every sprite block on this disc (all frames, all cells)."""
    out = set()
    for meta_path in sorted((ROOT / "assets/sprites").rglob("meta.json")):
        meta = json.loads(meta_path.read_text())
        data = (ROOT / meta["file"]).read_bytes()
        _, entries, run_table = parse_file(data)
        for f in meta["frames"]:
            if "png" not in f:            # empty slot or not decodable (S4.1 frame 1)
                continue
            _, cells, _ = decode_frame(data, 4 + (entries[f["frame"] - 1] >> 8), run_table)
            pw = palette_words(data, f["palette"])
            out.update(pixel_hash(block_name(bytes(c["pixels"]), pw, c["w"], c["h"]))
                       for c in cells if c["pixels"] is not None)
    return out


def prune_sprites(pack):
    """Remove sprite images whose block does not exist on this disc.

    A pack carried over from another language still holds that language's
    text sprites; they can never match here, and the pack loader refuses
    more than 262,144 files.
    """
    used, removed = disc_sprite_hashes(), 0
    for p in (Path(pack) / "replacements/sprites").rglob("texupload-*.png"):
        if pixel_hash(p.stem) not in used:
            p.unlink()
            removed += 1
    return removed


def missing_sprites(pack):
    have = {pixel_hash(n) for n in pack_names(pack, "sprites") if n.startswith("texupload-")}
    out = []
    for meta_path in sorted((ROOT / "assets/sprites").rglob("meta.json")):
        meta = json.loads(meta_path.read_text())
        rel = meta_path.parent.relative_to(ROOT / "assets/sprites").as_posix()
        data = (ROOT / meta["file"]).read_bytes()
        _, entries, run_table = parse_file(data)
        for f in meta["frames"]:
            if "png" not in f or (rel, f["frame"]) in EFFECT_FRAMES:
                continue
            _, cells, _ = decode_frame(data, 4 + (entries[f["frame"] - 1] >> 8), run_table)
            pw = palette_words(data, f["palette"])
            if any(c["pixels"] is not None and
                   pixel_hash(block_name(bytes(c["pixels"]), pw, c["w"], c["h"])) not in have
                   for c in cells):
                out.append(f"{rel}/{f['png']}")
    return out


def missing_levels(pack):
    have = pack_names(pack, "levels")
    out = []
    cut = ROOT / "assets/textures_cut"
    for level_dir in sorted(p for p in cut.iterdir() if (p / "manifest.json").exists()):
        # level_jobs pairs each cut texture (here: its own file as "HD") with
        # the pack names it would get
        _, jobs, _ = level_texpack.level_jobs(level_dir, level_dir, Path("x"))
        for src, _crop, _near, outs in jobs:
            if not any(Path(o).stem in have for o, _ in outs):
                out.append(f"{level_dir.name}/{Path(src).name}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pack", type=Path)
    ap.add_argument("out", type=Path, nargs="?")
    ap.add_argument("--prune", action="store_true",
                    help="delete sprite images of blocks this disc does not have (no OUT)")
    a = ap.parse_args()
    if a.prune:
        print(f"{prune_sprites(a.pack)} sprite images of other discs removed")
        return
    res = {"sprites": missing_sprites(a.pack), "levels": missing_levels(a.pack)}
    a.out.write_text(json.dumps(res, indent=0) + "\n")
    print(f"missing: {len(res['sprites'])} sprite frames, {len(res['levels'])} level textures")


if __name__ == "__main__":
    main()
