#!/usr/bin/env python3
"""Write HerculesRecomp's AOT overlay profile (psxrecomp AOT methods v1).

Images: the three engines (PS-X EXEs at 0x80038350, swapped at run time) and
the level code overlays OV1-OV11 at the bases splat uses (ov*.yaml). OV0 holds
no code. Declared entries are the functions whose address is stored somewhere
(config/indirect_targets.json, "address_taken", from any file); the recompiler
cannot find those through jal, and every one is a real function start.
Overlay bytes outside splat's asm subsegment (leading jump tables, trailing
data) are declared excluded_ranges: the recompiler otherwise takes pointers to
data as function-pointer targets (OV10's data start decoded as code).
ENGINE3 declares no entries: the pipeline composes ENGINE3's last page with
OV2/OV8/OV10 and then requires every declared ENGINE3 entry inside that
small window ("Excluded required loader entry"). Its own discovery finds 74 of
the 77 address-taken ENGINE3 functions; the other three stay interpreted.
Loader evidence: ENGINE1's level table (docs/level_format.md) points into the
ENGINE1 overlays, and its overlay pointers are pinned with a words check.

    python3 tools/aot_profile.py ~/psx-decomp/HerculesRecomp/aot/overlays.json [--expected N]

Other PAL versions (same code, moved; see tools/version_map.py): pass the
version's extracted files, its address map and disc image, e.g.

    python3 tools/aot_profile.py OUT.json --files files-eu \
        --map versions/SCES-00891.map.json --game-id SCES-00891 \
        --disc "disc-eu/Disney's Action Game featuring Hercules (Europe).bin"
"""
import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DISC_SHA256 = "0359cf0c126f20de455cd585b9637b4f6c235876026a3e665af0a0738f6aae05"
ENGINES = ["engine1", "engine3", "title"]
OVERLAYS = [f"ov{i}" for i in range(1, 12)]
LEVEL_TABLE = 0x8006C228  # ENGINE1, 28 bytes per level
FILES = ROOT / "files"     # --files: another version's extracted disc
VMAP = None                # --map: tools/version_map.py output


def moved(image, addr):
    """The address in the selected version (identity for the German one)."""
    if VMAP is None:
        return addr
    sys.path.insert(0, str(ROOT / "tools"))
    from version_map import lookup
    return lookup(VMAP, image, addr)


def vram(name):
    """Load address of an overlay in the selected version (splat's is German)."""
    base = int(re.search(r"vram: (0x[0-9A-Fa-f]+)", (ROOT / f"{name}.yaml").read_text())[1], 16)
    return base + (VMAP["load_shift"][name] if VMAP else 0)


def disc_name(name):
    return f"EX/{name.upper()}." if name in ENGINES else f"OV/{name.upper()}."


def image_range(name):
    data = (FILES / disc_name(name)).read_bytes()
    if name in ENGINES:
        return 0x80038350, 0x80038350 + len(data) - 0x800
    base = vram(name)
    return base, base + len(data)


def asm_span(name):
    """File offsets of the asm subsegment (splat yaml)."""
    subs = re.findall(r"- \[(0x[0-9A-Fa-f]+)(?:, (\w+))?\]", (ROOT / f"{name}.yaml").read_text())
    for i, (offset, kind) in enumerate(subs):
        if kind == "asm":  # ends at the next subsegment or the segment end marker
            return int(offset, 16), int(subs[i + 1][0], 16)
    raise ValueError(f"{name}: no asm subsegment")


def data_exclusions(name):
    # overlays keep their layout in every version (tools/version_map.py)
    data = (FILES / disc_name(name)).read_bytes()
    base = vram(name)
    lo, hi = asm_span(name)
    ranges = []
    for start, end, what in ((0, lo, "jump tables and constants before the code"),
                             (hi, len(data) & ~3, "data after the last function")):
        if end > start:
            ranges.append(dict(start=f"{base + start:#010x}", end=f"{base + end:#010x}",
                               sha256=hashlib.sha256(data[start:end]).hexdigest(),
                               reason=f"{name.upper()} {what} (splat {name}.yaml)"))
    return ranges


def address_taken(targets):
    """Address-taken functions, grouped by the file that contains them."""
    found = {name: set() for name in ENGINES + OVERLAYS}
    for info in targets.values():
        for func, homes in info.get("address_taken", {}).items():
            for home in homes:
                if home in found:
                    found[home].add(int(func, 16))
    return found


def level_table_check():
    data = (FILES / "EX/ENGINE1.").read_bytes()
    table = moved("engine1", LEVEL_TABLE)
    values = {}
    for level in range(12):
        for k in range(4, 7):
            addr = table + 28 * level + 4 * k
            word = struct.unpack_from("<I", data, addr - 0x80038350 + 0x800)[0]
            if word:
                values[f"{addr:#010x}"] = f"{word:#010x}"
    return dict(method="words", file="EX/ENGINE1.", file_offset="0x800", base="0x80038350",
                values=values)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("--expected", type=int, default=0)
    ap.add_argument("--files", type=Path, help="extracted disc of another version")
    ap.add_argument("--map", type=Path, help="tools/version_map.py output for it")
    ap.add_argument("--game-id", default="SCES-00893")
    ap.add_argument("--disc", type=Path, help="disc image (.bin) to take the SHA-256 of")
    args = ap.parse_args()
    global FILES, VMAP
    if args.files:
        FILES = args.files.resolve()
    if args.map:
        VMAP = json.loads(args.map.read_text())
    disc_sha = hashlib.sha256(args.disc.read_bytes()).hexdigest() if args.disc else DISC_SHA256
    targets = json.loads((ROOT / "config/indirect_targets.json").read_text())
    taken = address_taken(targets)
    images = []
    for name in ENGINES + OVERLAYS:
        lo, hi = image_range(name)
        mapped = (moved(name, a) for a in taken[name])
        entries = sorted(f"{a:#010x}" for a in mapped if a is not None and lo <= a < hi and a % 4 == 0)
        if name == "engine3":
            entries = []
        spec = dict(files=[disc_name(name)], entries=entries)
        if name in ENGINES:
            spec = dict(method="psx_exe", **spec)
        else:
            spec = dict(method="fixed_address_files", load_addr=f"{lo:#010x}", allow_missing=True,
                        excluded_ranges=data_exclusions(name), **spec)
        images.append(spec)
    profile = {
        "schema": "psxrecomp AOT methods v1",
        "game_id": args.game_id,
        "static_output": "generated/overlays_static.c",
        "disc_hashes": {"sha256": disc_sha},
        "strict_bounds": True,
        "checks": [level_table_check()],
        "images": images,
        "expected_records": args.expected,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(profile, indent=2) + "\n")
    print(f"{args.out}: {len(images)} images, "
          f"{sum(len(i['entries']) for i in images)} declared entries")


if __name__ == "__main__":
    main()
