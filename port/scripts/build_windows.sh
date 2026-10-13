#!/usr/bin/env bash
# Cross-build the Windows release on Linux (MinGW-w64) and package it.
#
#   scripts/build_windows.sh [VERSION]      -> dist/hercules-<VERSION>-windows-x64.zip
#
# Needs: mingw64-gcc mingw64-gcc-c++ mingw64-winpthreads-static (Fedora names),
# cmake, ninja, and generated/ (psxrecomp_cli.py generate). Test with Wine:
#   WINEPREFIX=~/.wine-hercules wine dist/<unzipped>/Hercules_Recompiled.exe
#
# Notes from getting it to build:
# - CC/CXX/LDFLAGS from the retcomm clang toolchain profile must not leak in
#   (--rtlib=compiler-rt breaks MinGW GCC).
# - MinGW GCC defaults to C++20, where path::u8string() is std::u8string; the
#   framework is written for C++17 (clang's default on Linux).
# - A system/prebuilt SDL3 found by CMake is not a Windows one: build SDL3 from
#   source, statically (one exe, no SDL3.dll).
# - Fedora's MinGW sysroot is /usr/x86_64-w64-mingw32/sys-root/mingw.
# - The recompiler ships inside overlay_toolchain/ (the game compiles overlay
#   code from the player's disc at run time): link it statically.
# - The framework packager expects recomp-ui's assets/{fonts,img}; we have no
#   recomp-ui, so they are created empty.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-$(cat "$ROOT/VERSION" 2>/dev/null || echo 0.0.0)}"
cd "$ROOT"
unset CC CXX LDFLAGS CFLAGS CXXFLAGS
TOOLCHAIN="$ROOT/psxrecomp/cmake/toolchain-mingw-w64.cmake"
SYSROOT=/usr/x86_64-w64-mingw32/sys-root/mingw

cmake -S . -B build-win -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN" -DCMAKE_FIND_ROOT_PATH="$SYSROOT" \
  -DCMAKE_CXX_STANDARD=17 -DCMAKE_CXX_STANDARD_REQUIRED=ON \
  -DCMAKE_DISABLE_FIND_PACKAGE_SDL3=TRUE
cmake --build build-win --target psx-runtime

cmake -S psxrecomp/recompiler -B build-recompiler-win -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN" -DCMAKE_FIND_ROOT_PATH="$SYSROOT" \
  -DCMAKE_EXE_LINKER_FLAGS="-static -static-libgcc -static-libstdc++"
cmake --build build-recompiler-win --target psxrecomp-game psxrecomp-bios

mkdir -p build-win/assets/fonts build-win/assets/img
RELEASE_VERSION="$VERSION" bash scripts/package_release.sh build-win windows-x64 build-recompiler-win
