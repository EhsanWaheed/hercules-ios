#!/usr/bin/env bash
# Portable Linux release: SDL3 and the C++ runtime built in, so the only
# system needs are glibc (2.35+), OpenGL and X11/Wayland libraries.
#
#   scripts/build_linux_release.sh      -> dist/hercules-<VERSION>-linux-x64.zip
#
# Needs generated/ (psxrecomp_cli.py generate) and the Linux recompiler in
# build-recompiler/ (psxrecomp/tools/ci/build_emitters.sh) for the bundled
# overlay toolchain.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# static SDL3 from the retcomm clang toolchain (building SDL from source would
# need the X11/Wayland/audio development packages)
TC="${RETCOMM_TOOLCHAIN:-$HOME/.local/share/retcomm/toolchains/cmake-clang-v1/latest}"
cmake -S . -B build-linux -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DSDL3_DIR="$TC/deps/lib/cmake/SDL3" \
  -DCMAKE_EXE_LINKER_FLAGS="-static-libstdc++"
cmake --build build-linux --target psx-runtime
mkdir -p build-linux/assets/fonts build-linux/assets/img
RELEASE_VERSION="$(cat VERSION)" bash scripts/package_release.sh build-linux linux-x64 build-recompiler
