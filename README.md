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

Only the **German PAL release (SCES-00893)** works: the port, its mods and
the HD pack are tied to that exact disc. US, Japanese and other PAL versions
are not supported. Tested on Linux (Fedora).

Needs GCC/G++, CMake ≥ 3.20, Ninja, pkg-config, git, Python 3 with numpy and
Pillow, and for the launcher PyGObject with GTK 4, libadwaita and
WebKitGTK 6.0.

```sh
git clone --recursive https://github.com/obaidr1/hercules-recompiled
cd hercules-recompiled/port
cd psxrecomp && git apply ../patches/psxrecomp/*.patch && cd ..
mkdir -p disc   # copy your dump here, Redump names:
                # "Disneys Hercules Action-Spiel (Germany).cue" + ".bin"
./psxrecomp/tools/ci/build_emitters.sh
python3 psxrecomp/psxrecomp_cli.py generate --config game.toml --project-root . \
    --disc "disc/Disneys Hercules Action-Spiel (Germany).cue"
cmake -S . -B build-release -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build-release --target psx-runtime
python3 launcher/build_assets.py --sd   # launcher art from your disc
./hercules-launcher
```

**HD graphics** are made from your disc on your PC (first start of the
launcher asks; about 4 hours on a laptop CPU). They need a Python with torch
and spandrel (e.g. the one bundled with [chaiNNer](https://chainner.app)) and
three upscaling models you download yourself (their licences forbid
redistribution), placed in `~/psx-decomp/models/` (or `$HERC_MODELS`):

- `IllustrationJaNai/4x_IllustrationJaNai_V1_DAT2_190k.pth`
- `Models/HDcube/4xHDCube4Compact.pth`
- `Models/HDcube/4xHDcube-Alpha.pth`

`decomp/tools/hd_pack_build.py` runs the same build from the command line.

`decomp/docs/HANDOFF.md` is the running project log (German): current state,
formats, how each mod hooks the game, and open tasks.

## Licenses

The framework in `port/psxrecomp` and the patches against it are under the
PolyForm Noncommercial License 1.0.0 (see the framework's `LICENSE`).
Third-party tools the decomp uses (splat, maspsx, m2c, the GCC 2.7.2 PSX
toolchain) are not included here and keep their own licenses. The repository's
own code has no license file yet.
