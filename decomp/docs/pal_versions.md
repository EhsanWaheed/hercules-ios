# PAL versions

One disc per language; the port builds one executable per disc and the
launcher asks for the disc that matches the chosen language.

| Language | Serial | Boot file | Disc here | Extracted |
|----------|--------|-----------|-----------|-----------|
| English | SCES-00891 | `SCES_008.91` | `disc-eu/` | `files-eu/` |
| French | SCES-00892 | `SCES_008.92` | `disc-fr/` | `files-fr/` |
| German | SCES-00893 | `SCES_008.93` | `disc/` | `files/` |
| Italian | SCES-00894 | `SCES_008.94` | `disc-it/` | `files-it/` |
| Spanish | SCES-00895 | `SCES_008.95` | `disc-es/` | `files-es/` |

Disc images and extracted files are not in Git. All are single-track
MODE2/2352. The French and Italian downloads came without a `.cue`;
`disc-fr/` and `disc-it/` have hand-written ones. SHA-1 of the images: FR
`ae5033f6…09bd`, IT `c306fb7d…e4fe`, ES `de1a1d72…a285`, matching the
hashes listed for these dumps online.

## Languages

Each disc holds one language and has no language select. All in-game text
(menus, level titles, passwords, memory card messages) is SD4 sprites in
that language; speech (XA), videos (MV), credits (CR), the loading screen
(LD) and HUD medallions (STP) differ per disc as well.

## Files compared with the German disc

| | English | French | Italian | Spanish |
|---|---|---|---|---|
| files | 309 | 311 | 312 | 311 |
| byte-identical | 195 | 227 | 201 | 224 |
| SD4 menu text | 16 differ | 15 | 15 | 15 |
| SD1 | `S1.32` differs | same | same | same |
| LV levels | L1, L3, L6 differ | same | same | same |
| CR / MV / XA / SND | 32 / 23 / 5 / 15 | 8 / 22 / 5 / 15 | 34 / 22 / 5 / 15 | 9 / 23 / 5 / 15 |
| EX, OV, STP, LD | all differ (code moved, see below) | | | |

Only the English disc changes level data (L1, L3: a few texture pixels; L6:
heavily). HD replacements are named after content hashes, so everything
built from identical files matches on every disc; the rest is rebuilt from
the player's disc by `tools/hd_pack_build.py`.

## Code

Same source, built again per language. `tools/version_map.py` finds every
German function (splat glabels) in the other build by instruction shape
(opcodes and registers equal, immediates free) and collects data addresses
and gp offsets from the matched code; `versions/<ID>.map.json` is the result
(not in Git, rebuilt in a second).

| | English | French | Italian | Spanish |
|---|---|---|---|---|
| main exe | same layout; one function (0x800110D0) differs in register use | same layout | same layout | same layout |
| ENGINE1 / ENGINE3 | +0x14 after func 0x8003B820 / 0x8003ABFC | +0x04 | unchanged | -0x38 |
| TITLE | -0x3C..+0x08, 3 functions changed | unchanged | unchanged | unchanged |
| overlays OV0-OV11 load address | -0x38 | -0x20 | -0x2C | -0x74 |
| gp offsets (sprite globals) | +8 | -4 | -0xC | -8 |

ENGINE1 0x8003B820 and ENGINE3 0x8003ABFC change length in every version
but Italian, where they keep it and only their contents differ
(language-dependent code); everything else matches one to one. Overlays load
right above the engine, so their load address follows the engine's end (from
ENGINE1's level table, `+0x10`); their bytes differ only in the absolute
addresses inside.

## Port

`tools/port_version.py` writes `HerculesRecomp/versions/<ID>/`:
`hercules_addrs.h` (every address the mods use; instruction words read from
that disc), `game.toml` (+ `game.gen.toml` with absolute paths for code
generation), and a `CMakeLists.txt` entry that builds the shared
`hercules_game.cmake` for that version. `tools/aot_profile.py --files --map
--game-id --disc` writes its AOT profile. See HANDOFF for the commands.

Found on the way: the TITLE upload queue is `0x8007BD58` (`lui 0x8008` with
a negative low half), not `0x8008BD58` as the sprite mod had it, so TITLE's
sprites never got their per-block uploads.

## HD pack for every language

HD art is made once and reused on every disc; only content that really
differs is upscaled again, automatically.

- Sprite blocks and HUD pieces are named after their own pixels: they match
  on every disc that has them.
- Level textures are named after the whole 384x512 block. `tools/pack_rekey.py
  rekey` renames each one for the target disc when the words of its own
  rectangle and its palette are unchanged. It needs the source pixels, from
  `replacements/levels/rects.json` in the pack (level_texpack.py writes it;
  `pack_rekey.py describe` adds it to older packs) or `--source-files`.
- `tools/pack_missing.py` lists what a pack still lacks for a disc; a sprite
  block counts as present in any palette (one upscale is recoloured into all
  palettes of its file; some frame headers name a palette the file lacks).
- `tools/hd_pack_build.py DISC WORK --base PACK [--base-files DIR]` does both
  and upscales only the gap; images of the base pack always win.

What the German pack lacks per disc (2026-10-14):

| | English | French | Italian | Spanish |
|---|---|---|---|---|
| level textures renamed | 865 | 0 | 0 | 0 |
| level textures to upscale | 10 (L1 5, L3 4, L6 1) | 0 | 0 | 0 |
| sprite frames to upscale | 438 (SD4 text, S1.32) | 112 | 261 | 131 |

The German pack on the German disc lacks nothing.

## Downloadable packs (launcher)

The launcher's HD row now downloads the ready pack for the player's disc
(HerculesRecomp `hd/hd_auto.py`): assets `hd-<serial>-<n>.zip` +
`SHA256SUMS.txt` of the GitHub pre-release `hd-packs` (pre-release so that
`update/updater.py`'s releases/latest never sees it). No archive for the disc
-> the local build from the disc as before. Movies, sound and the game itself
always come from the player's disc.

    python3 tools/hd_pack_release.py OUT SCES-00891=PACK ... # parts < 1.9 GB
    HerculesRecomp/dist/hd-packs/upload.sh                   # publish (public!)

Packs 2026-10-14 (German pack reused for the others, only their own text
sprites and EN's 10 changed level textures upscaled): EN 255,147 files,
FR 248,756, DE 247,645, IT 248,661, ES 248,633; two archives each, 2.4-2.6 GB.

## Language = release (launcher)

Each disc holds one language, so the launcher's language picks the release
(HerculesRecomp `launcher_native/hl_launcher.cpp`, `struct Release`): de
SCES-00893, en -00891, fr -00892, it -00894, es -00895. One build per release:

    <game>/                 German build, launcher.ini, keybinds.ini, discs,
                            mods/texture-packs/<id>/, overlay_toolchain/, bios/
    <game>/lang/<id>/       the other builds: exe, game.toml, saves/, cache/,
                            settings.toml, mods/state.toml (written per start)

- Discs: `disc.cfg` (German, as before) and `disc-<id>.cfg`. No disc for the
  chosen language: on "start" the launcher names the release it needs and
  opens the file picker; a disc of another release is remembered for that one.
  First start without any disc: whatever disc is picked sets the language.
- The launcher draws itself from the chosen release's disc (menu words,
  captions and level names are then the game's own in that language), else
  from any disc it knows. The font is the German disc's strip when there is
  one (most letters); otherwise the disc's own strip, which holds only its
  pause menu's letters (EN larger, other order): `build_font(..., release)`
  has a row table per release and draws missing letters (F H J K W Z ...).
- Sprite decoding needs ENGINE1's run-length table: `Release::dist_table`.
- The game it starts gets `PSX_HL_HOME` (its in-game menu then uses the game
  folder's launcher.ini and HD packs) and `PSX_KEYBINDS_INI` (one keybinds.ini
  for all). The framework looks for `overlay_toolchain/` up to two folders
  above the exe; the BIOS is found by walking up anyway.
- Save states and memory cards stay per release (same entry PC in all five,
  different RAM layout).
- Release: `scripts/build_linux_release.sh` / `build_windows.sh` build all five;
  `package_release.sh` stages the others with `stage_release_build.sh` into
  the archive (`HERC_EXTRA_BUILDS`). The updater protects `lang/<id>/` user
  files, `disc-*.cfg` and `hd-build-*/` like the German ones.

## Tests 2026-10-14 (RunPod: RTX PRO 4500, 128 cores)

`tools/port_debug/lang_matrix.py` (15 games at once, SDL_VIDEO_DRIVER=offscreen
for NVIDIA EGL) ran a cold boot and a direct start into each of the 11 levels
for all five versions: 60/60 runs reach the level in the right engine
(ENGINE3: 2, 8, 10), movies play, audio audible in every 10 s slice after the
first, title cards and menus in the disc's language (checked by eye). HD share
per level is the same in every language (`matrix_summary.py`); ENGINE3 levels
(21-25 %) and level 3 (32 %) are low in German too: their level textures are
not in any pack yet.
