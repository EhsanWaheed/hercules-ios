// ios_overlay.h - the iOS settings panel and the controller bubble (ios_overlay.mm).
#pragma once

#ifdef __cplusplus
extern "C" {
#endif

// Once per presented frame (ios_present.mm): installs the panel over the game's window the first time, and while
// the panel is open holds the game here (it is paused), turning the run loop for the panel.
void herc_overlay_frame(void);

// The controller bubble ("DualSense · Connected") shows over this window from now on (the launcher's, then the
// game's).
void herc_bubble_attach(void *uiwindow);

#ifdef __cplusplus
}
#endif
