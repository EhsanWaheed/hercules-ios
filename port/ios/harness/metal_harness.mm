// metal_harness.mm - replays a trace of the Metal renderer's backend calls (ios_metal_renderer.mm HERC_TRACE) on the
// Mac, whose Apple-silicon GPU has the framebuffer fetch the iOS Simulator lacks. With --verify every presented
// frame is compared with the software renderer's (the renderer's own verify mode); either way the renderer's stats
// line reports what the frames cost.
//
//   build.sh && ./metal_harness trace.bin [--verify] [--scale N]
#include "gpu_render.h"
#include "gpu_sw_renderer.h"
#include "ios_metal_renderer.h"
#include "ios_metal_trace.h"

#import <Foundation/Foundation.h>
#import <QuartzCore/QuartzCore.h>

#include <cstdio>
#include <cstring>
#include <vector>

// What the renderer reads from the rest of the runtime.
static uint16_t g_vram[1024 * 512];
static int g_bd;
extern "C" {
uint16_t *gpu_get_vram_ptr(void) { return g_vram; }
int psx_ws_prim_in_backdrop(void) { return g_bd; }
int g_ws_bd_stretch_on = 1;  // gpu_gl_renderer.c's defaults
int g_ws_bd_stretch_pct = 0;
void gr_register_host_software_backend(const GpuRenderBackend *) {}
}

int main(int argc, char **argv) {
    @autoreleasepool {
        if (argc < 2) {
            fprintf(stderr, "usage: %s trace.bin [--verify] [--scale N]\n", argv[0]);
            return 2;
        }
        bool verify = false;
        int scale_override = 0;
        for (int i = 2; i < argc; ++i) {
            if (!strcmp(argv[i], "--verify")) verify = true;
            else if (!strcmp(argv[i], "--scale") && i + 1 < argc) scale_override = atoi(argv[++i]);
        }
        [NSUserDefaults.standardUserDefaults registerDefaults:@{@"ios.metalVerify" : @(verify)}];
        FILE *f = fopen(argv[1], "rb");
        if (!f) { perror(argv[1]); return 1; }
        const GpuRenderBackend *b = herc_metal_backend();
        std::vector<uint32_t> out(4096u * 2048u);
        std::vector<uint8_t> payload;
        int32_t a[32];
        uint64_t records = 0, frames = 0;
        const double t0 = CACurrentMediaTime();
        for (;;) {
            int32_t hdr[2];
            if (fread(hdr, 4, 2, f) != 2) break;
            if (hdr[1] < 0 || hdr[1] > 32 || fread(a, 4, (size_t)hdr[1], f) != (size_t)hdr[1]) break;
            uint32_t len;
            if (fread(&len, 4, 1, f) != 1) break;
            payload.resize(len);
            if (len && fread(payload.data(), 1, len, f) != len) break;
            ++records;
            const int op = hdr[0], n = hdr[1];
            if (n > 0) g_bd = a[n - 1];
            const int pitch = 4096 * 4;
            switch (op) {
            case HT_VRAM:
                memcpy(g_vram, payload.data(), std::min<size_t>(len, sizeof g_vram));
                b->init(g_vram);
                break;
            case HT_SET_SCALE: b->set_scale(scale_override ? scale_override : a[0]); break;
            case HT_SET_FILTER: b->set_texture_filter(a[0]); break;
            case HT_SET_SEMI: b->set_semi_transparency(a[0], a[1]); break;
            case HT_SET_MASK: b->set_mask_bits(a[0], a[1]); break;
            case HT_SET_TW: b->set_texture_window((uint32_t)a[0]); break;
            case HT_SET_MOD: b->set_color_modulation(a[0], a[1], a[2], a[3]); break;
            case HT_SET_PRECISE: b->set_precise_triangle(a[0], a[1], a[2], a[3], a[4], a[5], a[6]); break;
            case HT_SET_PERSP: {
                float q[3];
                memcpy(q, a + 1, 12);
                b->set_perspective_triangle(a[0], q[0], q[1], q[2]);
                break;
            }
            case HT_FILL: b->fill_rect(a[0], a[1], a[2], a[3], (uint16_t)a[4]); break;
            case HT_COPY: b->copy_rect(a[0], a[1], a[2], a[3], a[4], a[5]); break;
            case HT_FLAT_TRI: b->draw_flat_triangle(a[0], a[1], a[2], a[3], a[4], a[5], (uint16_t)a[6]); break;
            case HT_GOURAUD:
                b->draw_gouraud_triangle(a[0], a[1], (uint16_t)a[2], a[3], a[4], (uint16_t)a[5], a[6], a[7],
                                         (uint16_t)a[8]);
                break;
            case HT_TEX_TRI:
                b->draw_textured_triangle(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8], a[9], a[10], a[11],
                                          (uint16_t)a[12], (uint16_t)a[13], (uint16_t)a[14]);
                break;
            case HT_SHADED_TEX_TRI:
                b->draw_shaded_textured_triangle(a[0], a[1], a[2], a[3], (uint32_t)a[4], a[5], a[6], a[7], a[8],
                                                 (uint32_t)a[9], a[10], a[11], a[12], a[13], (uint32_t)a[14],
                                                 (uint16_t)a[15], (uint16_t)a[16], (uint16_t)a[17], a[18]);
                break;
            case HT_FLAT_RECT: b->draw_flat_rect(a[0], a[1], a[2], a[3], (uint16_t)a[4]); break;
            case HT_TEX_RECT:
                b->draw_textured_rect(a[0], a[1], a[2], a[3], a[4], a[5], (uint16_t)a[6], (uint16_t)a[7],
                                      (uint16_t)a[8]);
                break;
            case HT_TEX_RECT_SCALED:
                b->draw_textured_rect_scaled(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], (uint16_t)a[8],
                                             (uint16_t)a[9], (uint16_t)a[10]);
                break;
            case HT_LINE: b->draw_line(a[0], a[1], a[2], a[3], (uint16_t)a[4]); break;
            case HT_SHADED_LINE: b->draw_shaded_line(a[0], a[1], (uint16_t)a[2], a[3], a[4], (uint16_t)a[5]); break;
            case HT_VRAM_WRITE: b->vram_write(a[0], a[1], (uint16_t)a[2]); break;
            case HT_TRANSFER_IN: b->vram_transfer_in(a[0], a[1], a[2], a[3], (const uint16_t *)payload.data()); break;
            case HT_DRAW_AREA: b->set_draw_area(a[0], a[1], a[2], a[3]); break;
            case HT_DRAW_OFFSET: b->set_draw_offset(a[0], a[1]); break;
            case HT_DISPLAY_HIRES:
                b->render_display_hires(out.data(), pitch, a[0], a[1], a[2], a[3]);
                HercMetalFrame fr;
                herc_metal_take_frame(&fr);
                ++frames;
                break;
            case HT_WIDE_CONFIGURE: b->wide_configure(a[0], a[1]); break;
            case HT_WIDE_VIEW: b->wide_set_view(a[0], a[1], a[2], a[3]); break;
            case HT_WIDE_TARGET: b->wide_set_target(a[0]); break;
            case HT_WIDE_DISABLE: b->wide_disable_target(); break;
            case HT_WIDE_CLEAR: b->wide_clear(a[0], a[1], a[2], (uint16_t)a[3]); break;
            case HT_WIDE_MARGINS: b->wide_clear_margins(a[0], a[1], a[2], (uint16_t)a[3], a[4]); break;
            case HT_DISPLAY_WIDE: {
                b->render_wide_display(out.data(), pitch, a[0], a[1], a[2]);
                HercMetalFrame fr;
                herc_metal_take_frame(&fr);
                ++frames;
                break;
            }
            default:
                fprintf(stderr, "unknown record %d after %llu records\n", op, (unsigned long long)records);
                return 1;
            }
        }
        herc_metal_finish();
        const double t = CACurrentMediaTime() - t0;
        fprintf(stderr, "replayed %llu records, %llu frames in %.2f s (%.1f frames/s, CPU and GPU together)\n",
                (unsigned long long)records, (unsigned long long)frames, t, frames / t);
        return 0;
    }
}
