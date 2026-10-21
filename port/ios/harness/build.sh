#!/bin/sh
# Builds the Mac test harness for the Metal renderer (metal_harness.mm) next to this script.
set -e
here=$(cd "$(dirname "$0")" && pwd)
rt="$here/../../psxrecomp/runtime"
out="${1:-$here/metal_harness}"
clang -c -O2 -I"$rt/include" -I"$rt/src" "$rt/src/gpu_sw_renderer.c" -o "$out.sw.o"
clang -c -O2 -I"$rt/include" "$rt/src/gpu_vram_dirty.c" -o "$out.dirty.o"
clang++ -std=c++17 -O2 -fobjc-arc -I"$rt/include" -I"$rt/src" -I"$here/.." \
    "$here/metal_harness.mm" "$here/../ios_metal_renderer.mm" "$out.sw.o" "$out.dirty.o" \
    -framework Foundation -framework Metal -framework QuartzCore -o "$out"
rm -f "$out.sw.o" "$out.dirty.o"
echo "$out"
