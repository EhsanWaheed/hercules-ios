#!/usr/bin/env python3
"""Match PsyQ library signatures (from ghidra_psx_ldr) against a PS-X EXE.

Usage: psyq_sigmatch.py EXE SIG_ROOT [--version VER] [--symbols OUT]

Without --version, every PsyQ version under SIG_ROOT is scored and the best
ones are listed. With --version, matched labels are printed (or written to OUT)
in splat symbol_addrs format.
"""
import argparse
import json
import re
import struct
from pathlib import Path

MIN_SIG_BYTES = 16
INTERNAL_LABEL = re.compile(r"^(loc|text|data|bss|rdata|sdata|sbss)_[0-9A-Fa-f]+$")


def load_exe(path):
    data = Path(path).read_bytes()
    assert data[:8] == b"PS-X EXE", "not a PS-X EXE"
    t_addr, t_size = struct.unpack_from("<II", data, 0x18)
    return data[0x800:0x800 + t_size], t_addr


def sig_regex(sig):
    parts = []
    for tok in sig.split():
        parts.append(b"." if tok == "??" else re.escape(bytes([int(tok, 16)])))
    return re.compile(b"".join(parts), re.DOTALL), len(parts)


def match_version(text, base, version_dir):
    """Return {obj_name: (addr, labels)} for objects with exactly one aligned match."""
    found = {}
    for lib in sorted(version_dir.glob("*.json")):
        for entry in json.loads(lib.read_text()):
            if not entry.get("sig"):
                continue
            regex, length = sig_regex(entry["sig"])
            if length < MIN_SIG_BYTES:
                continue
            hits = [m.start() for m in regex.finditer(text) if m.start() % 4 == 0]
            if len(hits) == 1:
                key = f"{lib.stem}:{entry['name']}"
                found[key] = (base + hits[0], entry.get("labels", []))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("exe")
    ap.add_argument("sig_root")
    ap.add_argument("--version")
    ap.add_argument("--symbols")
    args = ap.parse_args()

    text, base = load_exe(args.exe)
    root = Path(args.sig_root)

    if not args.version:
        scores = []
        for vdir in sorted(p for p in root.iterdir() if p.is_dir() and p.name.isdigit()):
            scores.append((len(match_version(text, base, vdir)), vdir.name))
        for count, name in sorted(scores, reverse=True):
            print(f"{name:>6}: {count} objects matched")
        return

    found = match_version(text, base, root / args.version)
    symbols = {}
    seen_names = set()
    for key, (addr, labels) in sorted(found.items(), key=lambda kv: kv[1][0]):
        for label in labels:
            name = label["name"]
            # Skip the signatures' internal branch labels; they are not functions.
            if INTERNAL_LABEL.match(name) or name in seen_names:
                continue
            if symbols.setdefault(addr + label["offset"], name) == name:
                seen_names.add(name)
    lines = [f"{name} = 0x{addr:08X}; // type:func" for addr, name in sorted(symbols.items())]
    if args.symbols:
        Path(args.symbols).write_text("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))
    print(f"// {len(found)} objects, {len(symbols)} labels")


if __name__ == "__main__":
    main()
