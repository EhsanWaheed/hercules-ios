#!/usr/bin/env python3
"""Name HD level textures for PSXRecomp's DuckStation-format texture packs.

ENGINE1 uploads a level's texture block 1 in one LoadImage, 384x512 words at
VRAM (384, 0) (docs/level_format.md), and PSXRecomp tracks it as one upload.
Every texture cut by cut_textures.py is a rectangle of that upload drawn with
one CLUT column; the CLUT row is the depth-fog level (shade 1..29, row 480 +
shade), so a texture needs one replacement per distinct fog palette:

    texupload-P4-<xxh3(block)>-<xxh3(16 CLUT words)>-384x512-<x>-<y>-<w>x<h>-P0-15
    texupload-P8-...-<xxh3(256 CLUT words)>-...-P0-255

x/y are texels from the upload's top left (4 per word for P4, 2 for P8).
Full palette ranges are used (no reduced-range prefix convention).

The HD image (cut with the near row 1, upscaled) is fogged per pixel: the
nearest near-palette colour picks an index i and the pixel moves by
fog[i] - near[i], so palette colours land exactly on the game's fog colours
and the upscaled detail in between is kept.

    python3 tools/level_texpack.py assets/textures_cut assets/textures_hd PACK_DIR

Writes PACK_DIR/replacements/levels/<level>/<name>.png.
"""
import argparse
import ctypes
import json
import multiprocessing
import os
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from level_vram import build_vram  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BLOCK_X, BLOCK_W, BLOCK_H = 384, 384, 512
CLUT_X, CLUT_Y = 768, 480
SHADES = range(1, 30)       # clamp(depth >> 5, 1, 29)

_lib = ctypes.CDLL(str(Path(__file__).resolve().parent / "native/libxxh3.so"))
_lib.xxh3_64.restype = ctypes.c_ulonglong
_lib.xxh3_64.argtypes = (ctypes.c_char_p, ctypes.c_ulong)


def xxh3(data):
    return _lib.xxh3_64(data, len(data))


def rgb(words):
    w = np.asarray(words, np.int32)
    c = np.stack([(w >> s) & 31 for s in (0, 5, 10)], axis=-1)
    return (c << 3 | c >> 2).astype(np.float32)


def nearest(px, pal, rows=1 << 16):
    """Index into pal of the closest colour for every row of px, in chunks
    so the pixel x palette distance matrix stays small."""
    pal_sq = (pal ** 2).sum(1)
    out = np.empty(len(px), np.intp)
    for a in range(0, len(px), rows):
        chunk = px[a:a + rows]
        out[a:a + rows] = (pal_sq[None, :] - 2 * chunk @ pal.T).argmin(1)
    return out


def load_image(src, crop):
    """crop = (left, right, w): keep texel columns left..right of w."""
    img = Image.open(src).convert("RGBA")
    if crop:
        left, right, w = crop
        img = img.crop((left * img.width // w, 0, right * img.width // w, img.height))
    return np.array(img)


def render(job):
    """One HD image, written once per shade: every pixel moves by the fog
    shift of its nearest near-palette colour."""
    src, crop, near, outs = job
    img = load_image(src, crop)
    near = np.array(near)
    pal_n = rgb(near)
    used = np.nonzero(near != 0)[0]                      # index 0 = transparent
    px = img[..., :3].reshape(-1, 3).astype(np.float32)
    i = None
    for dst, fogged in outs:
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        tmp = dst + ".tmp.png"
        fogged = np.array(fogged)
        if np.array_equal(near, fogged):
            out = img
        else:
            if i is None:
                i = used[nearest(px, pal_n[used])]
            shift = rgb(fogged)[i] - pal_n[i]
            out = img.copy()
            out[..., :3] = np.clip(px + shift, 0, 255).round().astype(np.uint8).reshape(img.shape[0], img.shape[1], 3)
        Image.fromarray(out).save(tmp, compress_level=1)
        os.replace(tmp, dst)


def level_jobs(level_dir, hd_dir, out_dir):
    manifest = json.loads((level_dir / "manifest.json").read_text())
    data = (ROOT / "files/LV" / manifest["level"]).read_bytes()
    vram = np.array(build_vram(data), np.uint16).reshape(512, 1024)
    block = vram[0:BLOCK_H, BLOCK_X:BLOCK_X + BLOCK_W]
    src_hash = xxh3(block.astype("<u2").tobytes())
    jobs, missing = [], 0
    for t in manifest["textures"]:
        src = hd_dir / t["file"]
        if not src.exists():
            missing += 1
            continue
        p8 = t["depth_bits"] == 8
        n = 256 if p8 else 16
        cx = CLUT_X + 16 * t["clut_column"]
        page_x = (t["texpage"] & 0xF) * 64 - BLOCK_X
        page_y = ((t["texpage"] >> 4) & 1) * 256
        x = page_x * (2 if p8 else 4) + t["u"]
        y = page_y + t["v"]
        # The pack loader wants x and width in whole VRAM words (2 or 4
        # texels); trim to the words fully inside, the edge stays native.
        ppw = 2 if p8 else 4
        x0, x1 = -(-x // ppw) * ppw, (x + t["w"]) // ppw * ppw
        if x1 <= x0:
            continue
        crop = None if (x0, x1) == (x, x + t["w"]) else (x0 - x, x1 - x, t["w"])
        near = vram[CLUT_Y + 1, cx:cx + n]
        seen, outs = set(), []
        for shade in SHADES:
            pal = vram[CLUT_Y + shade, cx:cx + n]
            pal_hash = xxh3(pal.astype("<u2").tobytes())
            if pal_hash in seen:
                continue
            seen.add(pal_hash)
            name = (f"texupload-{'P8' if p8 else 'P4'}-{src_hash:016X}-{pal_hash:016X}-"
                    f"{BLOCK_W}x{BLOCK_H}-{x0}-{y}-{x1 - x0}x{t['h']}-P0-{n - 1}")
            outs.append((str(out_dir / f"{name}.png"), pal.tolist()))
        jobs.append((str(src), crop, near.tolist(), outs))
    return src_hash, jobs, missing


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cut", type=Path, help="cut_textures.py output (manifests)")
    ap.add_argument("hd", type=Path, help="upscaled textures, same layout")
    ap.add_argument("pack", type=Path)
    ap.add_argument("--levels", nargs="*", help="e.g. L1_1 (default: all)")
    ap.add_argument("--workers", type=int, default=min(os.cpu_count(), 6))
    args = ap.parse_args()
    jobs = []
    for level_dir in sorted(p for p in args.cut.iterdir() if (p / "manifest.json").exists()):
        if args.levels and level_dir.name not in args.levels:
            continue
        out = args.pack / "replacements/levels" / level_dir.name
        src_hash, lj, missing = level_jobs(level_dir, args.hd / level_dir.name, out)
        print(f"{level_dir.name}: upload {src_hash:016X}, {sum(len(j[3]) for j in lj)} images"
              + (f", {missing} textures without HD image" if missing else ""), flush=True)
        jobs += lj
    with multiprocessing.Pool(args.workers) as pool:
        for i, _ in enumerate(pool.imap_unordered(render, jobs), 1):
            if i % 100 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)
    print(f"{sum(len(j[3]) for j in jobs)} images -> {args.pack / 'replacements/levels'}")


if __name__ == "__main__":
    main()
