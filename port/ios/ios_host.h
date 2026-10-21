// ios_host.h - the runtime's writable root on iOS (ios_host.mm).
#pragma once

// Makes Library/Application Support/Hercules the runtime's home: links the
// bundled files into it, points argv[0] at it and makes it the working
// directory. Call before main() resolves any path (the launcher does).
void herc_ios_prepare_runtime(char **argv);

#ifdef __cplusplus
#include <string>
// Library/Application Support/Hercules: where game.toml and mods/state.toml are written.
std::string herc_ios_runtime_root();

// The settings the game reads at start (ios.aspect, ios.renderLines), written into the runtime's game.toml and
// mods/state.toml before it starts.
std::string herc_ios_aspect();        // "screen", "16:9" or "4:3"
std::string herc_ios_render_lines();  // internal_resolution: "native", "480", "720", "960"
void herc_ios_write_game_config();
void herc_ios_write_mod_state();
#endif

// The connected controller's family: 1 PlayStation, 2 any other, 0 none
// (ios_launcher.mm; the settings panel and touch controls use it too).
int herc_pad_family(void);
