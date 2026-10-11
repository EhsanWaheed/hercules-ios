#!/bin/bash
# Prepare a decomp-permuter directory for one function.
#
# Usage: tools/permute_setup.sh FUNC CANDIDATE.c [ASM_FOLDER]
#   CANDIDATE.c  the function plus any declarations it needs
#   ASM_FOLDER   defaults to asm/main/nonmatchings/boot
# Creates permuter/FUNC/ with base.c, target.o, compile.sh and settings.toml.
# Run it with: ../.venv/bin/python ../tools/decomp-permuter/permuter.py permuter/FUNC -j8
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FUNC="$1"
CANDIDATE="$(realpath "$2")"
ASM_FOLDER="${3:-asm/main/nonmatchings/boot}"
DIR="$ROOT/permuter/$FUNC"
GCC_VER="$(sed -n 's/^GCC_VER *?= *//p' "$ROOT/Makefile")"
ASPSX_VER="$(sed -n 's/^ASPSX_VER *?= *//p' "$ROOT/Makefile")"
AS_FLAGS="-EL -march=r3000 -mtune=r3000 -mabi=32 -G0 -no-pad-sections"

rm -rf "$DIR" && mkdir -p "$DIR"

# Target: the original function assembled on its own.
{
    echo '.include "macro.inc"'
    echo '.set noat'
    echo '.set noreorder'
    echo '.section .text'
    cat "$ROOT/$ASM_FOLDER/$FUNC.s"
} > "$DIR/target.s"
mips64-linux-gnu-as $AS_FLAGS -I"$ROOT/include" -o "$DIR/target.o" "$DIR/target.s"

# Base: preprocessed shared declarations from the source file + candidate.
SRC="$ROOT/src/main/boot.c"
grep -v '^INCLUDE_ASM' "$SRC" | awk '/^[a-zA-Z].*\) \{$/{skip=1} !skip{print} skip && /^}/{skip=0}' \
    | cpp -undef -P -DPERMUTER -I"$ROOT/include" - > "$DIR/base.c"
cat "$CANDIDATE" >> "$DIR/base.c"

cat > "$DIR/compile.sh" <<EOF
#!/bin/bash
# Usage: compile.sh INPUT.c -o OUTPUT.o
cpp -undef -P "\$1" \\
  | "$ROOT/../tools/gcc/$GCC_VER/cc1" -quiet -G0 -O2 -funsigned-char -w -fpeephole \\
      -ffunction-cse -fpcc-struct-return -fcommon -msoft-float -mgas -fgnu-linker \\
  | "$ROOT/../.venv/bin/python" "$ROOT/../tools/maspsx/maspsx.py" --aspsx-version=$ASPSX_VER \\
  | mips64-linux-gnu-as $AS_FLAGS -o "\$3"
EOF
chmod +x "$DIR/compile.sh"

cat > "$DIR/settings.toml" <<EOF
func_name = "$FUNC"
compiler_type = "gcc"
objdump_command = "mips64-linux-gnu-objdump -drz -m mips:3000 -EL"
EOF

"$DIR/compile.sh" "$DIR/base.c" -o "$DIR/base.o"
echo "ready: $DIR"
