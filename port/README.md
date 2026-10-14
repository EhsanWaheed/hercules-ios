# Hercules Recompiled: the PC port

This folder is the PC port of *Disney's Hercules* (PS1, German PAL release
SCES-00893), built on [psxrecomp](https://github.com/RetroPortingToolKit/psxrecomp).
Downloads, what you need and build steps are in the
[main README](../README.md); every key is listed in [CONTROLS.md](CONTROLS.md).

| Folder | What |
|--------|------|
| `game.toml`, `game_options.toml` | the game's configuration for the framework |
| `mods/src`, `mods/preloaded` | the game's mods: HD sprites, widescreen, level select, skip intro / direct start |
| `launcher_native/` | the launcher compiled into the game (menus, options, HD build, updates, in-game menu) |
| `launcher/` | the older Python launcher for source builds on Linux |
| `hd/hd_auto.py` | the automatic HD build the release downloads run |
| `update/updater.py` | in-place updates for the release downloads |
| `scripts/` | release builds for Linux and Windows (MinGW cross-build) |
| `patches/psxrecomp/` | framework changes this port needs that are not upstream |
