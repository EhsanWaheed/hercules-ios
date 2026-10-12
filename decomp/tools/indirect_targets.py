#!/usr/bin/env python3
"""Collect jump tables and indirect-call targets for the recompiler.

Reads the splat output (asm/<name>/) of every executable and overlay and
writes one JSON file with, per code image:

- functions: start address of every function (from `glabel`)
- jump_tables: table address, owning function, `jr` site, bound from the
  `sltiu` range check and the case targets (entries are cut at the bound and
  at the first word that leaves the owning function)
- address_taken: functions whose address appears as a data word or is built
  in code with lui + addiu/ori -- the candidates for `jalr` and stored
  callbacks; pointers may cross images (engine data -> overlay code and back)
- jalr: number of indirect call sites
- other_jr: indirect jumps that are neither jump tables nor `jr $ra`
  (BIOS call stubs `jr $t2` and the like)

    python3 tools/indirect_targets.py [--out config/indirect_targets.json]

Overlay code is only valid while that overlay is loaded: an overlay's data can
point into itself, its engine and the boot executable; engine data can point
into any overlay of that engine (the level table does), so `address_taken`
lists each target with the images it can belong to. A pointer that matches
several overlays is resolved by whichever is loaded. The recompiler should
still keep a lookup over all function starts as a fallback: callbacks may
also come from level data files at run time.
"""
import argparse
import bisect
import collections
import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INS = re.compile(r"^\s*/\* ([0-9A-F]+) ([0-9A-F]{8}) ([0-9A-F]{8}) \*/\s+(\S+)\s*(.*)$")
REG = r"\$\w+"

ENGINE3_OVERLAYS = {2, 8, 10}
IMAGES = ["main", "engine1", "engine3", "title"] + [f"ov{i}" for i in range(12)]


def host(image):
    """Images whose code may run together with `image` (main is always resident)."""
    if image == "main":
        return ["main"]
    if image.startswith("ov"):
        eng = "engine3" if int(image[2:]) in ENGINE3_OVERLAYS else "engine1"
        return ["main", eng, image]  # other overlays are not loaded at the same time
    return ["main", image] + overlays_of(image)


def overlays_of(engine):
    if engine == "engine1":
        return [f"ov{i}" for i in range(12) if i not in ENGINE3_OVERLAYS]
    if engine == "engine3":
        return [f"ov{i}" for i in sorted(ENGINE3_OVERLAYS)]
    return []


def parse(image):
    """Instructions, function starts, raw data words and jump-table extents."""
    code, funcs, words, tables = [], [], [], {}
    for path in sorted((ROOT / "asm" / image).rglob("*.s")):
        pending, table = False, None
        for line in path.read_text().splitlines():
            if line.startswith("glabel "):
                pending = True
            elif line.startswith("dlabel "):
                name = line.split()[1]
                table = name if name.startswith("jtbl_") else None
                if table:
                    tables[table] = []
            elif line.startswith("enddlabel"):
                table = None
            m = INS.match(line)
            if m and not m.group(4).startswith("."):
                vram = int(m.group(2), 16)
                if pending:
                    funcs.append(vram)
                    pending = False
                code.append((vram, m.group(4), m.group(5)))
                continue
            dm = re.match(r"^\s*/\* [0-9A-F]+ ([0-9A-F]{8}) ([0-9A-F]{8}) \*/\s+\.word", line)
            if dm:
                vram = int(dm.group(1), 16)
                raw = dm.group(2)
                value = struct.unpack("<I", bytes.fromhex(raw))[0]
                words.append((vram, value))
                if table:
                    tables[table].append(value)
    return code, sorted(set(funcs)), words, tables


def scan_code(code):
    """jr/jalr sites, lui-built addresses, and the jump table each jr uses."""
    hi = {}  # register -> upper half from lui
    built, jalr, jr_sites = set(), 0, []
    window = collections.deque(maxlen=16)
    for vram, op, args in code:
        regs = re.findall(REG, args)
        window.append((vram, op, args))
        if op == "lui" and regs:
            m = re.search(r"0x([0-9A-F]+)$", args) or re.search(r"%hi\((\w+?)_?([0-9A-F]{8})?\)", args)
            imm = None
            mm = re.search(r"%hi\(\w*?([0-9A-F]{8})\)", args)
            if mm:
                imm = int(mm.group(1), 16) >> 16
                imm += 1 if int(mm.group(1), 16) & 0x8000 else 0
            elif re.search(r", 0x([0-9A-F]+)$", args):
                imm = int(re.search(r", 0x([0-9A-F]+)$", args).group(1), 16)
            if imm is not None:
                hi[regs[0]] = imm
            continue
        if op in ("addiu", "ori") and len(regs) >= 2 and regs[1] in hi:
            mm = re.search(r"%lo\(\w*?([0-9A-F]{8})\)", args)
            if mm:
                built.add(int(mm.group(1), 16))
            else:
                n = re.search(r", (-?0x[0-9A-F]+|-?\d+)$", args)
                if n:
                    lo = int(n.group(1), 0)
                    if op == "addiu":
                        built.add(((hi[regs[1]] << 16) + lo) & 0xFFFFFFFF)
                    else:
                        built.add((hi[regs[1]] << 16) | (lo & 0xFFFF))
        if op == "jalr":
            jalr += 1
        if op == "jr" and args.strip() != "$ra":
            ctx = list(window)
            tbl = next((re.search(r"jtbl_([0-9A-F]{8})", a).group(1) for _, _, a in reversed(ctx)
                        if "jtbl_" in a), None)
            bound = None
            for _, o, a in reversed(ctx):
                if o == "sltiu":
                    n = re.search(r", (0x[0-9A-F]+|\d+)$", a)
                    bound = int(n.group(1), 0) if n else None
                    break
            jr_sites.append((vram, args.strip(), tbl, bound))
        if regs and op not in ("sw", "sh", "sb", "jr", "jalr", "beq", "bne") and regs[0] in hi and op != "lui":
            hi.pop(regs[0], None)
    return built, jalr, jr_sites


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=ROOT / "config/indirect_targets.json")
    args = ap.parse_args()

    parsed = {img: parse(img) for img in IMAGES}
    starts = {img: set(p[1]) for img, p in parsed.items()}
    result = {}
    for img in IMAGES:
        code, funcs, words, tables = parsed[img]
        built, jalr, jr_sites = scan_code(code)
        owner = lambda a: funcs[bisect.bisect_right(funcs, a) - 1] if funcs and a >= funcs[0] else None
        next_func = lambda f: funcs[bisect.bisect_right(funcs, f)] if bisect.bisect_right(funcs, f) < len(funcs) else 1 << 32

        jump_tables, other_jr = [], []
        for site, reg, tbl, bound in jr_sites:
            if tbl is None:
                other_jr.append({"site": f"{site:08X}", "reg": reg})
                continue
            f = owner(site)
            entries = tables.get(f"jtbl_{tbl}", [])
            if bound:
                entries = entries[:bound]
            cut = []
            for e in entries:
                if not (f <= e < next_func(f)):
                    break
                cut.append(e)
            jump_tables.append({"table": tbl, "function": f"{f:08X}", "site": f"{site:08X}",
                                "bound": bound, "entries": len(cut),
                                "targets": sorted({f"{e:08X}" for e in cut})})

        candidates = {v for _, v in words} | built
        taken = {}
        for value in sorted(candidates):
            where = [h for h in host(img) if value in starts[h]]
            if where:
                taken[f"{value:08X}"] = where
        result[img] = {"functions": len(funcs), "jalr": jalr, "jump_tables": jump_tables,
                       "other_jr": other_jr, "address_taken": taken}

    args.out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"{'image':8} {'funcs':>5} {'jtbl':>4} {'cases':>5} {'short':>5} {'jalr':>4} {'taken':>5} {'other_jr':>8}")
    for img, r in result.items():
        short = sum(1 for t in r["jump_tables"] if t["bound"] and t["entries"] < t["bound"])
        print(f"{img:8} {r['functions']:5} {len(r['jump_tables']):4} {sum(t['entries'] for t in r['jump_tables']):5} "
              f"{short:5} {r['jalr']:4} {len(r['address_taken']):5} {len(r['other_jr']):8}")
    print(f"written {args.out}")


if __name__ == "__main__":
    main()
