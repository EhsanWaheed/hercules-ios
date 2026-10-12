#!/usr/bin/env python3
"""Turn HD sprite blocks into DuckStation texture replacements.

DuckStation (texture cache on, EnableTextureReplacements) names paletted
replacements after hashes of its own VRAM write tracking, which we do not
reproduce. Instead: play with texture dumping enabled, then this tool matches
every dumped `texupload-*.png` against the original sprite blocks and writes
an HD image for it into the replacements folder under the dump's name.

    python3 tools/sprite_duckstation.py CELLS_DIR [--game-dir DIR]

CELLS_DIR: output of sprite_cells.py (manifest.json + <sprite>/<key>.png)
--game-dir: DuckStation's textures/<serial> folder (default: Flatpak path
            for SCES-00893); reads dumps/, writes replacements/sprites/.

What a dump looks like (seen in play):
- the game uploads a column of 32x32 slots (16 x 32n halfwords, 8 bit), one
  decoded block at the top-left of each slot, the rest of the slot is stale;
- the dump is only the rectangle the GPU sampled (name field
  `<x>-<y>-<w>x<h>` inside the upload), so blocks are often cut off;
- colours go through DuckStation's 5->8 bit conversion (differs from ours
  by 1) and the frame may be drawn with another palette (flash, silhouette),
  which can merge colours.
So every slot is matched by its opaque mask inside the block area, then
checked for a consistent colour mapping (block colour -> dump colour). The HD
block is recoloured with that mapping; parts without a match keep the dump
pixels, scaled up 4x (nearest), so nothing goes missing.
"""
import argparse
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sprite_cells import ORIG, cut_sprite  # noqa: E402

GAME_DIR = Path.home() / ".var/app/org.duckstation.DuckStation/config/duckstation/textures/SCES-00893"
NAME = re.compile(r"texupload-(\w+?)-[0-9A-F]+-[0-9A-F]+-(\d+)x(\d+)-(\d+)-(\d+)-(\d+)x(\d+)-")
SLOT = 32
MIN_PIXELS = 16  # opaque pixels needed before a (partial) match is trusted


def codes(rgba):
    """5-bit colour code per pixel (1..32768), 0 = transparent."""
    a = np.asarray(rgba)
    c = a[..., :3].astype(np.int32) >> 3
    code = (c[..., 0] << 10 | c[..., 1] << 5 | c[..., 2]) + 1
    code[a[..., 3] < 128] = 0
    return code


class Blocks:
    """All distinct original blocks, grouped by size for vectorised search."""

    def __init__(self, cells):
        seen = {}
        for meta_path in sorted(ORIG.glob("*/*/meta.json")):
            for key, _, info in cut_sprite(meta_path, ORIG, 1, verify=True):
                hd = cells / info["sprite"] / f"{key}.png"
                c = codes(info["expect"])
                k = (c.shape, c.tobytes())
                if k not in seen or (not seen[k][2].exists() and hd.exists()):
                    seen[k] = (c, info["expect"], hd)
        by_size = {}
        for c, rgba, hd in seen.values():
            by_size.setdefault(c.shape, []).append((c, rgba, hd))
        self.groups = []
        for (h, w), items in by_size.items():
            code = np.stack([i[0] for i in items])
            self.groups.append((h, w, code, code > 0, [i[1] for i in items], [i[2] for i in items]))
        self.count = len(seen)
        self.windows = {}

    def lookup(self, h, w, opaque, window):
        """opaque-mask bytes of one window -> block indices (built on first use)."""
        key = (h, w, window)
        if key not in self.windows:
            cx0, cy0, x1, y1 = window
            table = {}
            for i, m in enumerate(opaque[:, cy0:y1, cx0:x1]):
                table.setdefault(np.packbits(m).tobytes(), []).append(i)
            self.windows[key] = table
        return self.windows[key]

    def match(self, part, cx0, cy0):
        """Best block for a dump crop `part` that sits at (cx0, cy0) in a slot."""
        pc = codes(part)
        best = None
        for h, w, code, opaque, rgbas, hds in self.groups:
            x1, y1 = min(w, cx0 + pc.shape[1]), min(h, cy0 + pc.shape[0])
            if x1 <= cx0 or y1 <= cy0:
                continue
            d = pc[:y1 - cy0, :x1 - cx0]
            dop = d > 0
            if dop.sum() < MIN_PIXELS:
                continue
            for i in self.lookup(h, w, opaque, (cx0, cy0, x1, y1)).get(np.packbits(dop).tobytes(), ()):
                b = code[i, cy0:y1, cx0:x1][dop]
                pairs = np.unique(np.stack([b, d[dop]], 1), axis=0)
                if len(np.unique(pairs[:, 0])) != len(pairs):
                    continue  # one block colour would need two dump colours
                exact = bool((pairs[:, 0] == pairs[:, 1]).all())
                score = (int(dop.sum()), exact, h * w)
                if best is None or score > best[0]:
                    best = (score, rgbas[i], hds[i], (cx0, cy0, x1, y1))
        return best


def recolour(hd, orig, part, area):
    """Map the HD block's original colours to the colours seen in the dump."""
    cx0, cy0, x1, y1 = area
    o = np.asarray(orig)[cy0:y1, cx0:x1]
    p = np.asarray(part)[:y1 - cy0, :x1 - cx0]
    vis = (o[..., 3] > 0) & (p[..., 3] >= 128)
    lut = {}
    for oc, pc in zip(o[vis][:, :3], p[vis]):
        lut[tuple(oc)] = pc  # RGBA: semi-transparent sprites (STP) dump alpha < 255
    out = np.array(hd)
    if all(np.array_equal(np.array(k), v[:3]) and v[3] == 255 for k, v in lut.items()):
        return out  # same palette: keep the HD block as is
    src = np.array(list(lut), np.int32)
    dst = np.array(list(lut.values()), np.uint8)
    m = out[..., 3] > 0
    px = out[m][:, :3].astype(np.int32)
    nearest = ((px[:, None, :] - src[None]) ** 2).sum(2).argmin(1)
    out[m] = dst[nearest]
    return out


def build(dump_path, blocks, scale):
    """HD image for one dump, plus (slots matched, slots total)."""
    m = NAME.match(dump_path.name)
    ox, oy, w, h = map(int, m.groups()[3:])
    dump = np.asarray(Image.open(dump_path).convert("RGBA"))
    out = np.asarray(Image.fromarray(dump).resize((w * scale, h * scale), Image.NEAREST)).copy()
    hit = total = 0
    for s in range(oy // SLOT, (oy + h - 1) // SLOT + 1):
        if ox >= SLOT:
            break
        total += 1
        y0 = s * SLOT - oy  # slot top in dump coordinates
        cy0, cx0 = max(-y0, 0), ox
        part = dump[max(y0, 0):y0 + SLOT, :SLOT - ox]
        best = blocks.match(part, cx0, cy0)
        if best is None or not best[2].exists():
            continue
        _, orig, hd_path, area = best
        hd = np.asarray(Image.open(hd_path).convert("RGBA"))
        hd = recolour(hd, orig, part, area)
        ax0, ay0, ax1, ay1 = area
        crop = hd[ay0 * scale:ay1 * scale, ax0 * scale:ax1 * scale]
        dy = (max(y0, 0)) * scale
        out[dy:dy + crop.shape[0], :crop.shape[1]] = crop
        hit += 1
    return out, hit, total


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cells", type=Path)
    ap.add_argument("--game-dir", type=Path, default=GAME_DIR)
    ap.add_argument("--scale", type=int, default=4)
    args = ap.parse_args()

    dumps = sorted((args.game_dir / "dumps").glob("texupload-*8-*.png"))
    if not dumps:
        sys.exit(f"no 8-bit texupload-*.png in {args.game_dir / 'dumps'}")
    blocks = Blocks(args.cells)
    print(f"{blocks.count} distinct original blocks", flush=True)
    out = args.game_dir / "replacements" / "sprites"
    out.mkdir(parents=True, exist_ok=True)
    full = some = 0
    unmatched = []
    for n, d in enumerate(dumps, 1):
        target = out / d.name
        if target.exists():
            full += 1
            continue
        img, hit, total = build(d, blocks, args.scale)
        if hit == 0:
            unmatched.append(d.name)
        else:
            Image.fromarray(img).save(target)
            full += hit == total
            some += hit < total
        if n % 5000 == 0:
            print(f"  {n}/{len(dumps)}", flush=True)
    print(f"{len(dumps)} dumps: {full} fully HD, {some} partly HD, {len(unmatched)} without match")
    if unmatched:
        (out / "unmatched.txt").write_text("\n".join(unmatched) + "\n")
        print(f"list of unmatched dumps: {out / 'unmatched.txt'}")


if __name__ == "__main__":
    main()
