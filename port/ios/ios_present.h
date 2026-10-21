// ios_present.h - the iOS presenter's settings (ios_present.mm), for the
// settings panel.
#pragma once

#ifdef __cplusplus
extern "C" {
#endif

enum { HERC_UPSCALER_METALFX = 0, HERC_UPSCALER_SHARP = 1, HERC_UPSCALER_NEAREST = 2 };
enum { HERC_FIT_FIT = 0, HERC_FIT_FILL = 1, HERC_FIT_STRETCH = 2 };

int herc_present_upscaler(void);           // HERC_UPSCALER_*
void herc_present_set_upscaler(int mode);
int herc_present_fx_rows(void);            // MetalFX output height: 720, 900, 1080; 0 the size shown
void herc_present_set_fx_rows(int rows);
int herc_present_screen_fit(void);         // HERC_FIT_*: bars, cropped to fill, or stretched
void herc_present_set_screen_fit(int fit);
int herc_present_metalfx_available(void);
double herc_present_fps(void);             // frames presented per second (the game's full speed is 60)  // 0 until the first frame, or without MetalFX

#ifdef __cplusplus
}
#endif
