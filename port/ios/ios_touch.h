// ios_touch.h - the on-screen glass controls (ios_touch.mm).
#pragma once

#ifdef __cplusplus
extern "C" {
#endif

// Puts the controls over the game's window (the settings panel's install does).
void herc_touch_install(void *uiwindow);
// The settings panel is open: the controls step aside (and let go of every button).
void herc_touch_set_panel_open(int open);
// Layout editing (drag the controls; the game stays paused until Done).
void herc_touch_begin_edit(void);
int herc_touch_editing(void);

// ios.touchMode: 0 Auto (shown while no controller or keyboard is connected), 1 Always, 2 Off.
int herc_touch_mode(void);
void herc_touch_set_mode(int mode);
// ios.touchSize: 0 small, 1 medium, 2 large. ios.touchOpacity: 0 low, 1 medium, 2 high.
int herc_touch_size(void);
void herc_touch_set_size(int size);
int herc_touch_opacity(void);
void herc_touch_set_opacity(int opacity);
void herc_touch_reset_layout(void);

#ifdef __cplusplus
}
#endif
