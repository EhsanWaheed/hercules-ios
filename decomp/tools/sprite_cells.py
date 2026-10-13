#!/usr/bin/env python3
"""Cut (upscaled) sprite frames back into the pixel blocks the game uploads.

A frame is drawn from decoded blocks (8..32 px, one per cell with own pixels);
cells without own pixels draw a sub-rectangle of the last block, so one block
acts as a small atlas (see docs/sprite_format.md). The game uploads each block
to VRAM and draws it with the frame's palette, so the PC port (or an emulator)
replaces textures per block. This tool rebuilds every block at SCALE from the
assembled frame PNGs and names it by a check value over the uploaded data:

    key = blake2b-64(raw block bytes as decoded + 32 palette words)

Output: OUT/<SDx>/<file>/<key>.png and OUT/manifest.json
        {key: {w, h, scale, sprite, frame, cell, palette, frames: [...]}}.
Atlas areas no cell draws stay transparent (never visible in the game).

    python3 tools/sprite_cells.py FRAMES_DIR OUT_DIR [--scale 4]
    python3 tools/sprite_cells.py --verify      cut the original frames at 1x
                                                and compare with the decoded blocks

FRAMES_DIR mirrors assets/sprites (SD1/S1_3/fNNNN.png); frames are matched by
name with assets/sprites/*/*/meta.json.
"""
import argparse
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sprites import decode_frame, palettes, parse_file  # noqa: E402

# HERC_ROOT: a work tree with the same layout (files/, assets/sprites/), used
# by hd_pack_build.py; default the decomp project itself.
ROOT = Path(os.environ.get("HERC_ROOT") or Path(__file__).resolve().parent.parent)
ORIG = ROOT / "assets/sprites"


def palette_words(data, i):
    """Raw 32 palette entries (15-bit colours) of palette i, as uploaded."""
    n, m = struct.unpack_from("<HH", data, 4)
    base = 4 + struct.unpack_from("<H", data, 16 + 4 * n + 2 * (i % m))[0] + 4
    return data[base:base + 64]


def block_key(pixels, pal_words):
    return hashlib.blake2b(bytes(pixels) + pal_words, digest_size=8).hexdigest()


def cut_sprite(meta_path, frames_dir, scale, verify=False):
    """Yield (key, rgba block, info) for every block of one sprite file."""
    meta = json.loads(meta_path.read_text())
    data = (ROOT / meta["file"]).read_bytes()
    _, entries, run_table = parse_file(data)
    pals = palettes(data)
    rel = meta_path.parent.relative_to(ORIG)
    for f in meta["frames"]:
        if "png" not in f:
            continue
        src = frames_dir / rel / f["png"]
        if not src.exists():
            continue
        frame = np.asarray(Image.open(src).convert("RGBA"))
        ax, ay = f["anchor"]
        if frame.shape[1] != f["size"][0] * scale or frame.shape[0] != f["size"][1] * scale:
            print(f"{src}: size {frame.shape[1]}x{frame.shape[0]} != {scale}x original", file=sys.stderr)
            continue
        off = 4 + (entries[f["frame"] - 1] >> 8)
        _, cells, _ = decode_frame(data, off, run_table)
        pw = palette_words(data, f["palette"])
        pal = np.array(pals[f["palette"] % len(pals)], np.uint8)
        block = None
        for ci, (c, ci_meta) in enumerate(zip(cells, f["cells"])):
            if c["pixels"] is not None:
                if block is not None:
                    yield block
                key = block_key(c["pixels"], pw)
                img = np.zeros((c["h"] * scale, c["w"] * scale, 4), np.uint8)
                block = (key, img, {"w": c["w"], "h": c["h"], "scale": scale,
                                    "sprite": rel.as_posix(), "frame": f["frame"], "cell": ci,
                                    "palette": f["palette"]})
                if verify:
                    idx = np.frombuffer(c["pixels"], np.uint8).reshape(c["h"], c["w"]) & 0x1F
                    block[2]["expect"] = pal[idx]
            if block is None:
                continue
            u, v, dw, dh = ci_meta["u"], ci_meta["v"], ci_meta["w"], ci_meta["h"]
            dw, dh = min(dw, c_w(block) - u), min(dh, c_h(block) - v)
            if dw <= 0 or dh <= 0:
                continue
            x, y = (ci_meta["x"] + ax) * scale, (ci_meta["y"] + ay) * scale
            region = frame[y:y + dh * scale, x:x + dw * scale]
            block[1][v * scale:v * scale + region.shape[0], u * scale:u * scale + region.shape[1]] = region
            block[2].setdefault("drawn", []).append((u, v, dw, dh))
        if block is not None:
            yield block


def c_w(block):
    return block[2]["w"]


def c_h(block):
    return block[2]["h"]


def verify_blocks():
    """Cut the original frames at 1x; every drawn pixel must equal palette[index]."""
    blocks = bad = 0
    def picked(m):
        rel = m.parent.relative_to(ORIG).as_posix()
        return rel not in args.skip and (not args.only or rel in args.only)
    for meta_path in [m for m in sorted(ORIG.glob("*/*/meta.json")) if picked(m)]:
        for key, img, info in cut_sprite(meta_path, ORIG, 1, verify=True):
            exp = info["expect"]
            for u, v, dw, dh in info.get("drawn", []):
                a = img[v:v + dh, u:u + dw]
                e = exp[v:v + dh, u:u + dw]
                vis = e[..., 3] > 0
                if not (np.array_equal(a[vis], e[vis]) and (a[~vis][..., 3] == 0).all()):
                    bad += 1
                    if bad <= 5:
                        print(f"mismatch: {info['sprite']} frame {info['frame']} cell {info['cell']}")
                    break
            blocks += 1
    print(f"{blocks} blocks checked, {bad} mismatches")
    return bad == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("frames", type=Path, nargs="?")
    ap.add_argument("out", type=Path, nargs="?")
    ap.add_argument("--scale", type=int, default=4)
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--skip", action="append", default=[], help="sprite to leave out (e.g. SD3/S3_1)")
    ap.add_argument("--only", action="append", default=[], help="cut only these sprites")
    args = ap.parse_args()
    if args.verify:
        sys.exit(0 if verify_blocks() else 1)
    if not args.frames or not args.out:
        ap.error("FRAMES_DIR and OUT_DIR are required")

    manifest, written, dupes = {}, 0, 0
    def picked(m):
        rel = m.parent.relative_to(ORIG).as_posix()
        return rel not in args.skip and (not args.only or rel in args.only)
    for meta_path in [m for m in sorted(ORIG.glob("*/*/meta.json")) if picked(m)]:
        for key, img, info in cut_sprite(meta_path, args.frames, args.scale):
            if key in manifest:
                # Same upload drawn in another frame: keep the first cut.
                manifest[key]["frames"].append([info["sprite"], info["frame"]])
                dupes += 1
                continue
            info.pop("drawn", None)
            manifest[key] = {**info, "frames": [[info["sprite"], info["frame"]]]}
            dst = args.out / info["sprite"] / f"{key}.png"
            dst.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(img, "RGBA").save(dst, optimize=True)
            written += 1
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"{written} unique blocks written, {dupes} repeats in other frames")


if __name__ == "__main__":
    main()
