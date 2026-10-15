#!/usr/bin/env bash
# Stages the build of one more PAL release into a game folder as lang/<id>/:
# the executable and what it reads from its own folder (game.toml,
# game_options.toml, the mod catalog, assets). The game folder's
# overlay_toolchain/, bios/, settings, keys, discs and HD packs are shared;
# the launcher in the game folder starts this build when the player picks
# its language (launcher_native/hl_launcher.cpp, struct Release).
#
#   scripts/stage_release_build.sh <build-dir> <game-dir>
#
# e.g. after  cmake -S versions/SCES-00891 -B build-en ... && cmake --build build-en
#      scripts/stage_release_build.sh build-en dist/stage-game-linux-x64
set -euo pipefail
BUILD="${1:?usage: $0 <build-dir> <game-dir>}"
GAME="${2:?usage: $0 <build-dir> <game-dir>}"
ID="$(sed -n 's/^id = "\(SCES-[0-9]*\)"$/\1/p' "$BUILD/game.toml" | head -1)"
[[ -n "$ID" ]] || { echo "error: no [game] id in $BUILD/game.toml" >&2; exit 1; }
[[ "$ID" != "SCES-00893" ]] || { echo "error: $ID is the game folder's own build" >&2; exit 1; }
EXE="$BUILD/Hercules_Recompiled"
[[ -f "$EXE.exe" ]] && EXE="$EXE.exe"
[[ -f "$EXE" ]] || { echo "error: no executable in $BUILD" >&2; exit 1; }

DEST="$GAME/lang/$ID"
rm -rf "$DEST"
mkdir -p "$DEST/mods" "$DEST/saves"
cp -a "$EXE" "$DEST/"
for f in game.toml game_options.toml Hercules_Recompiled.execution.json psx_game_version.txt; do
  [[ -f "$BUILD/$f" ]] && cp -a "$BUILD/$f" "$DEST/"
done
cp -a "$BUILD/assets" "$DEST/"
cp -a "$BUILD/mods/bundled" "$DEST/mods/"
[[ -f "$BUILD/mods/README.md" ]] && cp -a "$BUILD/mods/README.md" "$DEST/mods/"
echo "staged $ID -> $DEST"
