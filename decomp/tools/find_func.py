#!/usr/bin/env python3
"""Find a function from one code file in others by instruction shape.

Compares opcode, register fields and R-type function codes; immediates,
jump targets and %lo/%hi parts are ignored, so a function relinked at
another address or with other gp offsets still matches.

    python3 tools/find_func.py SRC_BIN SRC_VRAM FUNC_ADDR LEN TARGET_BIN TARGET_VRAM [...]
(binaries include the 0x800-byte header; VRAM = load address of offset 0x800)
"""
import struct
import sys


def shape(w):
    op = w >> 26
    if op == 0:          # R-type: everything but shamt matters
        return w & 0xFFFFF83F
    if op in (2, 3):     # j / jal
        return op << 26
    return w & 0xFFFF0000  # I-type: opcode + rs + rt


def words(path):
    d = open(path, "rb").read()[0x800:]
    return [struct.unpack_from("<I", d, i)[0] for i in range(0, len(d) - 3, 4)]


def main():
    src, src_vram, func, length = sys.argv[1], int(sys.argv[2], 16), int(sys.argv[3], 16), int(sys.argv[4], 16)
    sw = words(src)
    i = (func - src_vram) // 4
    pat = [shape(w) for w in sw[i:i + length // 4]]
    for tgt, tv in zip(sys.argv[5::2], sys.argv[6::2]):
        tw = [shape(w) for w in words(tgt)]
        best = []
        for k in range(len(tw) - len(pat)):
            same = sum(a == b for a, b in zip(pat, tw[k:k + len(pat)]))
            if same > 0.8 * len(pat):
                best.append((same, int(tv, 16) + 4 * k))
        best.sort(reverse=True)
        print(tgt, [(f"{a:#x}", f"{s}/{len(pat)}") for s, a in best[:3]])


if __name__ == "__main__":
    main()
