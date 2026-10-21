# Hercules iOS

*Disney's Hercules* (PlayStation, 1997) running natively on iPhone and iPad as statically recompiled
ARM64 code. No emulator and no JIT, so it plays under LiveContainer or SideStore.

This is a fork of [**obaidr1/hercules-recompiled**](https://github.com/obaidr1/hercules-recompiled), the native
PC port of the game and the decompilation behind it. That project does the hard part: the recompiled game, the
widescreen and level-select mods, and the framework patches. This fork adds the iOS and iPadOS port.

**[Download the latest release](https://github.com/EhsanWaheed/hercules-ios/releases/latest)**
(`HerculesIOS-NGF.ipa`, version 1.0). The IPA contains **no game files**: you add your own disc.

Fan project, not affiliated with or endorsed by Disney or Sony.

## Features

- **Native, no JIT.** The game runs as statically recompiled ARM64 code (the level code too), so it plays under
  LiveContainer or SideStore without JIT.
- **Liquid Glass launcher.** Your box art, the disc's status, and glass buttons: Play, import your disc from a
  folder or a ZIP (checked against the PAL releases), export and import saves. Controller and keyboard navigation,
  with button hints in the connected controller's own glyphs.
- **Metal renderer.** The CPU draws the PS1's own picture exactly as the original renderer does (the game reads
  it back), and the GPU draws the high-resolution one with the same per-pixel rules. So higher resolutions cost the
  GPU, not the CPU: 3x holds a full 60 fps on an iPhone 17 Pro Max through a whole stage (6–10 ms of CPU and under
  1 ms of GPU a frame), without heating the phone. 2x by default, up to 4x.
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
- **Settings panel** over the game: **L3 + R3**, a three-finger tap, or **Cmd+S**. Display (aspect, fit, render
  resolution, upscaler, MetalFX output, the live frame rate), the controller, the touch controls, skip intro. The
  game pauses while it is open.
- US speed (60 Hz) by default. The game's own menu (Select + Start) works too.

## What you need

- An iPhone or iPad on **iOS 17 or later**, with [LiveContainer](https://github.com/LiveContainer/LiveContainer)
  or SideStore.
- **Your own dump of the English PAL release, SCES-00891** (Redump: *Disney's Action Game featuring Hercules
  (Europe)*), as a `.cue` and its `.bin`. The app is translated from that release: the launcher checks the disc
  and turns away the others (it tells you which release a disc is).

## Install

1. Install `HerculesIOS-NGF.ipa` from [Releases](https://github.com/EhsanWaheed/hercules-ios/releases/latest) with
   LiveContainer or SideStore, and open it once so its Documents folder exists.
2. Put the `.cue` and the `.bin` in a folder named exactly **`game`**.
3. Copy that **`game`** folder into the app's **Documents** folder (Files app, or Finder with the device plugged in):
   - **LiveContainer**: Files → On My iPhone → **LiveContainer** → `Data` → `Application` → the app's data folder
     (its name is shown in LiveContainer's settings for the app) → **`Documents`** → put `game` there.
   - **SideStore** (installed as a normal app): Files → On My iPhone → **Hercules** → put `game` there.
4. Open the app: the launcher checks the disc once (a few seconds) and shows **Ready to play**.

Prefer not to copy files by hand? Open the app without a `game` folder and use **Import disc folder…** or **Import
disc ZIP…**: pick the folder (or a ZIP of it) wherever it is, and the launcher copies it into `Documents/game`.

Updating: install the new IPA over the old one; your disc and saves stay.

## Controls

| | |
|---|---|
| Settings panel | **L3 + R3**, a three-finger tap, or **Cmd+S** |
| Game menu | **Select + Start** |
| Touch controls | Hide or show with the eye at the top; move, resize and fade them in the settings panel |

## Troubleshooting

- Saves are in `Documents/Saves`; export and import them from the launcher.
- `Documents/Logs/hercules.log` is the log of the last run. Every 5 seconds it records the frame rate, the CPU and
  GPU time a frame took and the device's thermal state. Attach it when you open an
  [issue](https://github.com/EhsanWaheed/hercules-ios/issues), with your device and iOS version.

## Building it yourself

1. Set up the English release as in upstream's
   [Getting started](https://github.com/obaidr1/hercules-recompiled#getting-started), with your disc in
   `port/versions/SCES-00891/disc/`, and apply the framework patches in
   [`port/patches/psxrecomp`](port/patches/psxrecomp) (`0012` adds the iOS hooks, `0013` the iOS frame pacer).
2. From `port/`, on a Mac with Xcode:

   ```sh
   cmake -S versions/SCES-00891 -B build-ios -G Ninja -DCMAKE_SYSTEM_NAME=iOS -DCMAKE_OSX_SYSROOT=iphoneos \
         -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_OSX_DEPLOYMENT_TARGET=17.0 -DCMAKE_BUILD_TYPE=Release \
         -DPSX_ENABLE_VULKAN=OFF
   cmake --build build-ios --target psx-runtime     # build-ios/Hercules_Recompiled.app, signed ad hoc
   ```

`-DHERC_IOS_BUNDLE_DISC=<folder with the .cue and .bin>` puts your disc inside the app (your own copy only). A
`port/ios/LauncherArt.png` (your box art, kept out of git) becomes the launcher's cover and the app icon.

The iOS code is in [`port/ios`](port/ios). [`port/ios/harness`](port/ios/harness) replays a recorded session on a
Mac GPU and checks every frame of the Metal renderer against the original renderer.

## About the game files

**This repository and the IPA contain no game data.** The IPA contains the game's program code translated to ARM64
(as upstream's PC downloads contain it for x86-64), but no graphics, sound, video or level data: those come from
your disc. Your disc, and anything made from it, stays out of git.

## PC version

For Windows and Linux, all five PAL releases, HD texture packs and a CRT filter, see the original project:
[obaidr1/hercules-recompiled](https://github.com/obaidr1/hercules-recompiled) and its
[releases](https://github.com/obaidr1/hercules-recompiled/releases/latest). This fork keeps its decompilation
(`decomp/`) and PC port (`port/`) unchanged apart from the iOS hooks.

## Credits and licences

- [obaidr1/hercules-recompiled](https://github.com/obaidr1/hercules-recompiled): the PC port, decompilation and
  game mods this port is built on.
- [psxrecomp](https://github.com/RetroPortingToolKit/psxrecomp): the static recompilation framework.
- [SDL3](https://github.com/libsdl-org/SDL), [miniz](https://github.com/richgel999/miniz).

The framework in `port/psxrecomp` and the patches against it are under the PolyForm Noncommercial License 1.0.0
(see the framework's `LICENSE`). The repository's own code has no license file yet.
