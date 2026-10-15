#!/usr/bin/env python3
"""Map addresses of the German build (SCES-00893) to another PAL version.

All PAL versions are the same source built again: functions keep their
order and instruction shapes, but code moves (ENGINE1/ENGINE3 by +0x14 from
some point on, TITLE by varying amounts) and data addresses and gp offsets
change. This tool finds every German function (glabels in asm/) in the other
version's file by its instruction shape: opcodes and registers must match,
immediates (data addresses, gp offsets, jal targets) may differ.

From the matched functions it also collects data references: a `lui` + `lo`
pair or a gp-relative access at the same instruction gives the other
version's address for the same datum.

    python3 tools/version_map.py FILES_DIR OUT.json      # build the map
    python3 tools/version_map.py --lookup OUT.json engine1 0x8003FD7C

FILES_DIR is the other version's extracted disc (files-eu/). The map lists,
per image, [de_start, de_end, other_start(, "fuzzy"|"changed")] for every
function ("changed": other length, only its start is mapped), plus
per image "data" {de_addr: other_addr} and "gp" {de_off: other_off}, and
"load_shift" {overlay: change of its load address}.
"""
import argparse
import json
import re
import struct
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# image: (German file, boot-exe-relative name in the other disc, base, header)
IMAGES = {
    "main": ("SCES_008.93", None, 0x80010000, 0x800),
    "engine1": ("EX/ENGINE1.", "EX/ENGINE1.", 0x80038350, 0x800),
    "engine3": ("EX/ENGINE3.", "EX/ENGINE3.", 0x80038350, 0x800),
    "title": ("EX/TITLE.", "EX/TITLE.", 0x80038350, 0x800),
}
GP_REG = 28
LINE = re.compile(r"/\* [0-9A-F]+ ([0-9A-F]{8}) ([0-9A-F]{8}) \*/")


def overlay_images():
    for y in sorted(ROOT.glob("ov*.yaml")):
        name = y.stem
        vram = int(re.search(r"vram: (0x[0-9A-Fa-f]+)", y.read_text())[1], 16)
        n = name[2:]
        IMAGES[name] = (f"OV/OV{n}.", f"OV/OV{n}.", vram, 0)


def boot_exe(files):
    cnf = (files / "SYSTEM.CNF").read_text(errors="replace")
    return re.search(r"cdrom:\\?([A-Z_0-9.]+)", cnf)[1]


def functions(name):
    """(start, end) of every German function, from the splat asm output."""
    starts, last = {}, {}
    cur = None
    for s in sorted((ROOT / "asm" / name).rglob("*.s")):
        for line in s.read_text().splitlines():
            if line.startswith("glabel "):
                cur = line.split()[1]
                continue
            m = LINE.search(line)
            if m and cur:
                addr = int(m[1], 16)
                starts.setdefault(cur, addr)
                last[cur] = addr
            if line.startswith("endlabel"):
                cur = None
    return sorted((starts[f], last[f] + 4) for f in starts if f in last)


def shape(w):
    op = w >> 26
    if op == 0 or op == 0x12 or op in (1, 4, 5, 6, 7):   # SPECIAL, COP2, branches
        return w
    if op in (2, 3):                                     # j / jal: target may move
        return op << 26
    return w & 0xFFFF0000                                # I-type: imm may change


def words(data, off, n):
    return struct.unpack_from(f"<{n}I", data, off)


def find(de, eu, de_off, n, hint, window=0x1000):
    """EU file offset whose n words have the same shapes, nearest to hint."""
    want = [shape(w) for w in words(de, de_off, n)]
    for d in sorted(range(-window, window + 1, 4), key=lambda d: abs(d)):
        o = de_off + hint + d
        if 0 <= o <= len(eu) - 4 * n and [shape(w) for w in words(eu, o, n)] == want:
            return o
    return None


def refs(code, base):
    """Data references in a function: {instr address: (kind, value)}."""
    out, hi = {}, {}
    for i, w in enumerate(code):
        op, rs, rt, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
        simm = imm - 0x10000 if imm & 0x8000 else imm
        a = base + 4 * i
        if op == 0x0F:                                   # lui
            hi[rt] = imm << 16
        elif op in (0x09, 0x20, 0x21, 0x23, 0x24, 0x25, 0x28, 0x29, 0x2B, 0x22, 0x26, 0x2A, 0x2E):
            if rs == GP_REG:
                out[a] = ("gp", simm)
            elif rs in hi:
                out[a] = ("abs", (hi[rs] + simm) & 0xFFFFFFFF)
        if op in (2, 3) or (op == 0 and (w & 0x3F) in (8, 9)):
            hi.clear()                                   # keep pairs local
    return out


def load_shift(de, eu, base, hdr):
    """Load-address change of a raw overlay: its internal jal targets move by it.

    Overlays are linked for a fixed address above the engine, and the engine's
    end moves between versions (EN: -0x38), so the same bytes load elsewhere.
    """
    votes = Counter()
    lo, hi = base, base + len(de) - hdr
    for off in range(hdr, min(len(de), len(eu)) - 3, 4):
        a, b = struct.unpack_from("<I", de, off)[0], struct.unpack_from("<I", eu, off)[0]
        if a >> 26 == 3 and b >> 26 == 3:
            ta, tb = 0x80000000 | (a & 0x3FFFFFF) << 2, 0x80000000 | (b & 0x3FFFFFF) << 2
            if lo <= ta < hi:
                votes[tb - ta] += 1
    return votes.most_common(1)[0][0] if votes else None


def build(files):
    overlay_images()
    result = {"data": {}, "gp": {}}
    for name, (de_rel, eu_rel, base, hdr) in IMAGES.items():
        de_path = ROOT / "files" / de_rel
        eu_path = files / (eu_rel or boot_exe(files))
        if not (de_path.exists() and eu_path.exists()):
            continue
        de, eu = de_path.read_bytes(), eu_path.read_bytes()
        data_votes, gp_votes = defaultdict(Counter), defaultdict(Counter)
        funcs, hint, miss, fuzzy = [], 0, 0, 0
        for start, end in functions(name):
            off, n = start - base + hdr, (end - start) // 4
            if off < 0 or off + 4 * n > len(de) or n == 0:
                continue
            o = find(de, eu, off, n, hint)
            if o is None:
                # recompiled differently (e.g. other register choice): accept the
                # expected place if most shapes agree and the next function matches
                o = off + hint
                same = 0
                if 0 <= o <= len(eu) - 4 * n:
                    same = sum(shape(x) == shape(y) for x, y in zip(words(de, off, n), words(eu, o, n)))
                if same < 0.5 * n:
                    # changed length: it starts where the previous one ends
                    miss += 1
                    prev = funcs[-1] if funcs else None
                    other = prev[2] + (start - prev[0]) if prev and prev[2] is not None else None
                    funcs.append([start, end, other, "changed"])
                    continue
                fuzzy += 1
                funcs.append([start, end, start + hint, "fuzzy"])
                continue
            hint = o - off
            funcs.append([start, end, start + hint])
            a = refs(words(de, off, n), start)
            b = refs(words(eu, o, n), start + hint)
            for (ka, va), (kb, vb) in zip((a[k] for k in sorted(a)), (b[k] for k in sorted(b))):
                if ka == kb == "gp":
                    gp_votes[va][vb] += 1
                elif ka == kb == "abs":
                    data_votes[va][vb] += 1
        if name.startswith("ov"):
            reloc = load_shift(de, eu, base, hdr)
            if reloc is None:   # no internal jal: same as overlays with this base
                same = [k for k, (_, _, b, _) in IMAGES.items() if k.startswith("ov") and b == base]
                found = [result.get("load_shift", {}).get(k) for k in same]
                found = [x for x in found if x is not None] or [
                    load_shift((ROOT / "files" / IMAGES[k][0]).read_bytes(),
                               (files / IMAGES[k][1]).read_bytes(), IMAGES[k][2], 0) for k in same]
                reloc = Counter(x for x in found if x is not None).most_common(1)[0][0]
            for f in funcs:
                if f[2] is not None:
                    f[2] += reloc
            result.setdefault("load_shift", {})[name] = reloc
        shifts = Counter(f[2] - f[0] for f in funcs if f[2] is not None and len(f) == 3)
        print(f"{name}: {len(funcs) - miss - fuzzy}/{len(funcs)} functions matched, "
              f"{fuzzy} by position only, {miss} changed, shifts {dict(shifts.most_common(4))}")
        result[name] = funcs
        result["data"][name] = {f"0x{k:08X}": f"0x{v.most_common(1)[0][0]:08X}"
                                for k, v in sorted(data_votes.items())}
        result["gp"][name] = {f"0x{k & 0xFFFF:04X}" if k >= 0 else str(k): f"0x{v.most_common(1)[0][0] & 0xFFFF:04X}"
                              for k, v in sorted(gp_votes.items())}
    return result


def lookup(m, image, addr):
    """Code address (inside a function) or data address of the other version."""
    for f in m[image]:
        if f[0] <= addr < f[1]:
            if f[2] is None or (f[3:] == ["changed"] and addr != f[0]):
                return None             # inside a function whose body changed
            return f[2] + (addr - f[0])
    hit = m["data"][image].get(f"0x{addr:08X}")
    return int(hit, 16) if hit else None


def lookup_gp(m, image, off):
    hit = m["gp"][image].get(f"0x{off & 0xFFFF:04X}")
    return int(hit, 16) if hit else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lookup", nargs=3, metavar=("MAP", "IMAGE", "ADDR"))
    ap.add_argument("--gp", action="store_true", help="--lookup ADDR is a gp offset")
    ap.add_argument("files", nargs="?", type=Path)
    ap.add_argument("out", nargs="?", type=Path)
    a = ap.parse_args()
    if a.lookup:
        m = json.loads(Path(a.lookup[0]).read_text())
        r = (lookup_gp if a.gp else lookup)(m, a.lookup[1], int(a.lookup[2], 16))
        print("none" if r is None else f"0x{r:08X}")
        return
    m = build(a.files)
    a.out.write_text(json.dumps(m, indent=1) + "\n")
    print(f"{sum(map(len, m['data'].values()))} data addresses, "
          f"{sum(map(len, m['gp'].values()))} gp offsets -> {a.out}")


if __name__ == "__main__":
    main()
