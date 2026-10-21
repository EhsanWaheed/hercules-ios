# Hercules Recompiled

A native PC (Windows and Linux) port of the 1997 PlayStation action game *Disney's
Hercules* (all five PAL releases: English, French, German, Italian, Spanish), plus the decompilation work
behind it. The game logic runs unchanged as statically recompiled code; only
the platform layer is replaced: 1080p, true 16:9, HD sprites, level textures
and HUD, a CRT simulation, save states, and a launcher styled after the
game's own title menus (in German, English, French, Spanish and Italian)
that boots straight into the level you pick.

**This repository contains no game data.** You need your own copy of the
game. Every graphic, sound and code byte of the game is read from your disc
image at build or run time, and everything made from it (extracted files,
disassembly, HD texture packs, launcher artwork) stays out of git. The
prebuilt downloads contain the game's program code translated to x86-64, but
no graphics, sound, video or level data: those still come from your disc.
The optional HD texture packs (upscaled from the game's graphics) are
published separately as the [hd-packs](https://github.com/obaidr1/hercules-recompiled/releases/tag/hd-packs)
release; the launcher can also make them from your disc instead.

Fan project, not affiliated with or endorsed by Disney or Sony.

## iPhone and iPad (this fork)

This fork of [obaidr1/hercules-recompiled](https://github.com/obaidr1/hercules-recompiled) adds a native iOS and
iPadOS port. **Version 1.0**: `HerculesIOS-NGF.ipa`, from [Releases](https://github.com/EhsanWaheed/hercules-ios/releases),
contains **no game files**: you add your own disc the first time you open it.

### Features

- **Native, no JIT.** The game runs as statically recompiled ARM64 code (the level code too), so it plays under
  LiveContainer or SideStore without JIT.
- **Liquid Glass launcher.** Your box art, the disc's status, and glass buttons: Play, import your disc from a
  folder or a ZIP (checked against the PAL releases), export and import saves. Controller and keyboard navigation,
  with button hints in the connected controller's own glyphs.
- **Metal renderer.** The CPU draws the PS1's own picture exactly as the software renderer does (the game reads it
  back), the GPU draws the high-resolution one with the same per-pixel rules, so higher resolutions cost the GPU,
  not the CPU: 3x holds a full 60 fps on an iPhone 17 Pro Max through a whole stage (6-10 ms of CPU and under
  1 ms of GPU a frame). 2x by default, up to 4x.
- **MetalFX upscaling** to the screen (spatial), with its output at 720p, 900p, 1080p or the screen's own height;
  sharp-bilinear and nearest as alternatives.
- **Fills the screen.** *Fit screen* has the game draw out to the screen's own shape, the HUD in its corners: no
  bars and nothing cropped in play. 16:9 and 4:3 too, shown fitted, filled or stretched. Movies stay 4:3.
- **Controllers.** Backbone One (PlayStation Edition too), DualSense, DualShock 4, Xbox and other MFi controllers,
  hot-plugged. A Liquid Glass bubble names a controller as it connects, and the settings show its own button
  glyphs and battery. A keyboard (an iPad's Magic Keyboard) plays too.
- **Liquid Glass touch controls.** A D-pad disc, the face buttons in their PlayStation colours, L1/L2, R1/R2,
  Select and Start, with haptics. They hide themselves when a controller or keyboard connects (or with the eye at
  the top), come in three sizes and opacities, and can be dragged where your thumbs rest.
- **Settings panel** over the game: **L3 + R3**, a three-finger tap, or Cmd+S. Display (aspect, fit, render
  resolution, upscaler, MetalFX output, the live frame rate), the controller, the touch controls, skip intro. The
  game pauses while it is open.
- US speed (60 Hz) by default, as the PC release since 0.5.5. The game's own menu (Select + Start) works as on PC.

### What you need

**Your own dump of the English PAL release, SCES-00891** (Redump: *Disney's Action Game featuring Hercules
(Europe)*), as a `.cue` and its `.bin`. This build is translated from that release: the launcher checks the disc
and turns away the others (it says which release a disc is).

### Install

1. Install `HerculesIOS-NGF.ipa` with [LiveContainer](https://github.com/LiveContainer/LiveContainer) or SideStore
   (iOS 17 or later), and open it once so its Documents folder exists.
2. Put the `.cue` and the `.bin` in a folder named exactly **`game`**.
3. Copy that **`game`** folder into the app's **Documents** folder (Files app, or Finder with the device plugged in):
   - **LiveContainer**: Files → On My iPhone → **LiveContainer** → `Data` → `Application` → the app's data folder
     (its name is shown in LiveContainer's settings for the app) → **`Documents`** → put `game` there.
   - **SideStore** (installed as a normal app): Files → On My iPhone → **Hercules** → put `game` there.
4. Open the app: the launcher checks the disc once (a few seconds) and shows **Ready to play**.

Prefer not to copy files by hand? Open the app without a `game` folder and use **Import disc folder…** or **Import
disc ZIP…**: pick the folder (or a ZIP of it) wherever it is, and the launcher copies it into `Documents/game`.

Saves are in `Documents/Saves`, the log of the last run in `Documents/Logs` (every 5 s: the frame rate, the CPU
and GPU time a frame took, and the device's thermal state; handy in a bug report).

### Building it yourself

Generate the English release as in *Getting started* below, with its disc in `port/versions/SCES-00891/disc/`, and
apply the patches (`port/patches/psxrecomp`, `0012` adds the iOS hooks). Then, from `port/`:

```sh
cmake -S versions/SCES-00891 -B build-ios -G Ninja -DCMAKE_SYSTEM_NAME=iOS -DCMAKE_OSX_SYSROOT=iphoneos \
      -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_OSX_DEPLOYMENT_TARGET=17.0 -DCMAKE_BUILD_TYPE=Release \
      -DPSX_ENABLE_VULKAN=OFF
cmake --build build-ios --target psx-runtime     # build-ios/Hercules_Recompiled.app, signed ad hoc
```

`-DHERC_IOS_BUNDLE_DISC=<folder with the .cue and .bin>` puts your disc inside the app (your own copy only). A
`port/ios/LauncherArt.png` (your box art, kept out of git) becomes the launcher's cover and the app icon. The iOS
code is in [`port/ios`](port/ios).

The IPA contains the game's program code translated to ARM64, as the PC downloads contain it for x86-64, but no
graphics, sound, video or level data: those come from your disc.

## Download

Prebuilt for players who don't want to build it themselves:

| System | Download |
|--------|----------|
| Windows 10/11 (x64) | [**hercules-recompiled-windows-x64.zip**](https://github.com/obaidr1/hercules-recompiled/releases/latest/download/hercules-recompiled-windows-x64.zip) |
| Linux (x64, glibc 2.35+: Ubuntu 22.04, Debian 12, Fedora 36 or newer) | [**hercules-recompiled-linux-x64.zip**](https://github.com/obaidr1/hercules-recompiled/releases/latest/download/hercules-recompiled-linux-x64.zip) |

Checksums and release notes: [latest release](https://github.com/obaidr1/hercules-recompiled/releases/latest).

1. Unzip into a folder of its own (the archive has no top-level folder).
2. Start `Hercules_Recompiled.exe` (Windows) or `./Hercules_Recompiled` (Linux).
3. On first start, pick your disc image: the `.cue` of a dump of one of the
   **PAL releases** SCES-00891 (English), -00892 (French), -00893 (German),
   -00894 (Italian) or -00895 (Spanish), `.cue` + `.bin`. The launcher's
   language picks the release; it asks for that release's disc and remembers
   it (`disc.cfg`, `disc-<id>.cfg`) next to the program.
4. Choose a level in the launcher. Keyboard, mouse and gamepads work; F11
   toggles fullscreen.
5. In the game, **Esc** (gamepad: **Select + Start**) opens the menu:
   HD on/off, CRT picture, 16:9 or 4:3, volume, the controls and more,
   all switched live. Every key is listed in [CONTROLS.md](port/CONTROLS.md).

Windows shows a SmartScreen warning because the program is not signed:
click **More info → Run anyway**.

**Updates come by themselves** (from 0.5.0 on): on start the launcher checks
for a new release, shows its changelog and installs it on request. Settings,
saves, the disc path and the HD graphics stay. *Options → General → Auto
updates* turns the check off. Coming from 0.4.0 or older: unzip the new
download over your existing folder once, so your HD graphics and saves stay.

**HD graphics are downloaded after your first game** (from 0.5.1 on): the
launcher fetches the pack for your release from the
[hd-packs](https://github.com/obaidr1/hercules-recompiled/releases/tag/hd-packs)
release in the background, about 1.6 GB, checked against SHA256SUMS.txt; a
second language then only needs the difference, a few to 40 MB. The
progress shows on the main menu and under *Options → Graphics → HD
graphics*; once done, HD is switched on.

If that release has no pack for your disc, the launcher **makes the pack on your PC,
from your disc**, at low priority: about 4 hours on a laptop CPU, while you
play in the original graphics. It stops when you close the launcher and
continues on the next start. For this it downloads, once, about 400 MB from the official sources, each
checked against a fixed SHA-256: a portable Python
([python-build-standalone](https://github.com/astral-sh/python-build-standalone)),
PyTorch (CPU), [spandrel](https://github.com/chaiNNer-org/spandrel) and
chaiNNer's image helpers, and the upscaling models from their authors'
releases ([IllustrationJaNai](https://github.com/the-database/MangaJaNai),
CC BY-NC-SA 4.0; [HDcube](https://github.com/Venomalia/HDcube)). It needs
6 GB of free disk space while it runs; afterwards only the finished pack
(in `mods/texture-packs/`) stays next to the program.

## Good to know

- **Speed and frame rate.** From 0.5.5 the PAL releases run at the speed of
  the US release (SLUS-01029) by default: 60 Hz timing, so the game takes 30
  steps and draws 30 pictures per second instead of 25. Music and movies keep
  their speed. On a 60 Hz screen every picture now stays exactly two
  refreshes, so the slight stutter of 25 pictures on 60 Hz is gone. For the
  original PAL speed set *General → Game speed → PAL* in the launcher.
  60 fps is not possible: both the PAL and the US game wait a fixed two video
  frames per step, and generated in-between frames (blending, optical flow,
  AI interpolation) were tried and looked worse than the original pictures.
- **Widescreen.** In 16:9 the game draws the extra width itself: scenery,
  far background and the HUD at the screen edges, and from 0.5.4 also the
  characters and objects in the side margins.
- **Problems?** Open an [issue](https://github.com/obaidr1/hercules-recompiled/issues)
  with the version (shown in the launcher), your disc's ID (SCES-0089x),
  Windows or Linux, and a screenshot if you can.

## Layout

| Folder | What |
|--------|------|
| [`decomp/`](decomp) | Decompilation of the main executable and the overlays (splat + GCC 2.7.2 / maspsx, byte-identical rebuild), file-format notes (levels, sprites, videos), tools for extraction, HD upscaling and texture packs |
| [`port/`](port) | The PC port, built on [psxrecomp](https://github.com/RetroPortingToolKit/psxrecomp): game configuration, game-specific mods (HD sprites, widescreen, level select, skip intro / direct start, NTSC speed) and the launcher |
| `port/psxrecomp` | Submodule: the upstream framework |
| [`port/patches/psxrecomp`](port/patches/psxrecomp) | Eleven framework changes this port uses that are not upstream (F3/F4 debug overlays and texture-pack tracking across save states; CRT simulation in the GL present path; a hook that lets the game build in its own launcher; a hook for the game's own in-game menu with live settings; the keyboard alongside the gamepad for Player 1; extra builds per disc release sharing one toolchain; a clean debug-server shutdown; the CRT simulation on blended frames; freezing the F4 inspector's picture to mark objects; semi-transparent draws keeping the original texture; NTSC timing for a PAL game as a mod option) |

## Getting started

The five **PAL releases** (SCES-00891 to -00895) work: the root of `port/`
builds the German one, `port/versions/<id>/` each of the others
(`cmake -S versions/<id> -B build-<id>`). US and Japanese versions are not
supported. Tested on Linux (Fedora) and Windows (Wine);
`port/scripts/build_windows.sh` cross-builds the Windows release with MinGW-w64.

Needs GCC/G++, CMake ≥ 3.20, Ninja, pkg-config, git, Python 3 with numpy and
Pillow, and for the launcher PyGObject with GTK 4, libadwaita and
WebKitGTK 6.0.

```sh
git clone --recursive https://github.com/obaidr1/hercules-recompiled
cd hercules-recompiled/port
cd psxrecomp && for p in ../patches/psxrecomp/*.patch; do git apply "$p"; done && cd ..
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

## Licenses

The framework in `port/psxrecomp` and the patches against it are under the
PolyForm Noncommercial License 1.0.0 (see the framework's `LICENSE`).
Third-party tools the decomp uses (splat, maspsx, m2c, the GCC 2.7.2 PSX
toolchain) are not included here and keep their own licenses. The repository's
own code has no license file yet.
