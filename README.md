# Hercules Recompiled

A native PC (Linux) port of the 1997 PlayStation action game *Disney's
Hercules* (PAL, German release **SCES-00893**), plus the decompilation work
behind it. The game logic runs unchanged as statically recompiled code; only
the platform layer is replaced: 1080p, true 16:9, HD sprites, level textures
and HUD, a CRT simulation, save states, and a launcher styled after the
game's own title menus (in German, English, French, Spanish and Italian)
that boots straight into the level you pick.

**This repository contains no game data.** You need your own copy of the
game. Every graphic, sound and code byte of the game is read from your disc
image at build or run time, and everything made from it (extracted files,
disassembly, HD texture packs, launcher artwork) stays out of git.

Fan project, not affiliated with or endorsed by Disney or Sony.

## Layout

| Folder | What |
|--------|------|
| [`decomp/`](decomp) | Decompilation of the main executable and the overlays (splat + GCC 2.7.2 / maspsx, byte-identical rebuild), file-format notes (levels, sprites, videos), tools for extraction, HD upscaling and texture packs |
| [`port/`](port) | The PC port, built on [psxrecomp](https://github.com/RetroPortingToolKit/psxrecomp): game configuration, game-specific mods (HD sprites, widescreen, level select, skip intro / direct start) and the launcher |
| `port/psxrecomp` | Submodule: the upstream framework |
| [`port/patches/psxrecomp`](port/patches/psxrecomp) | Two framework changes this port uses that are not upstream (F3/F4 debug overlays and texture-pack tracking across save states; CRT simulation in the GL present path) |

## Getting started

```sh
git clone --recursive https://github.com/obaidr1/hercules-recompiled
cd hercules-recompiled/port/psxrecomp
git am ../patches/psxrecomp/*.patch
```

Then follow `decomp/docs/workflow.md` (extracting your disc, building the
decomp) and `port/psxrecomp/docs/GAME_PROJECT_SETUP.md` (building the port).
Some scripts still assume the original local layout
(`~/psx-decomp/hercules` for `decomp/`, `~/psx-decomp/HerculesRecomp` for
`port/`); symlinking those paths is the quickest way to use them unchanged.

`decomp/docs/HANDOFF.md` is the running project log (German): current state,
formats, how each mod hooks the game, and open tasks.

## Licenses

The framework in `port/psxrecomp` and the patches against it are under the
PolyForm Noncommercial License 1.0.0 (see the framework's `LICENSE`).
Third-party tools the decomp uses (splat, maspsx, m2c, the GCC 2.7.2 PSX
toolchain) are not included here and keep their own licenses. The repository's
own code has no license file yet.
