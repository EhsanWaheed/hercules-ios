// ios_metal_renderer.h - the Metal renderer (ios_metal_renderer.mm) and what it shares with the presenter.
#pragma once

#ifdef __OBJC__
#import <Metal/Metal.h>
#endif

#ifdef __cplusplus
extern "C" {
#endif

// A frame on the GPU: a region of a 15-bit target (the hi-res mirror or a wide surface), in pixels.
typedef struct HercMetalFrame {
    void *texture;  // id<MTLTexture>, R16Uint
    int x, y, w, h;
} HercMetalFrame;

// The frame the last display readout handed over, once.
int herc_metal_take_frame(HercMetalFrame *frame);
int herc_metal_active(void);

#ifdef __OBJC__
id<MTLDevice> herc_metal_device(void);
id<MTLCommandQueue> herc_metal_queue(void);
// Decodes the frame's region into `out` (BGRA8, the region's size), as the software renderer's rgb555_to_argb.
void herc_metal_decode(id<MTLCommandBuffer> cb, const HercMetalFrame *frame, id<MTLTexture> out);
#endif

#ifdef __cplusplus
}
#endif
