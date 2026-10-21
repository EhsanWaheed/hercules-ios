// ios_metal_trace.h - the record kinds of the Metal renderer's trace (ios_metal_renderer.mm HERC_TRACE), shared with
// the Mac test harness that replays it (tools/ios_metal_harness.mm).
#pragma once

enum HercTraceOp {
    HT_VRAM = 1, HT_SET_SCALE, HT_SET_FILTER, HT_SET_SEMI, HT_SET_MASK, HT_SET_TW, HT_SET_MOD, HT_SET_PRECISE,
    HT_SET_PERSP, HT_FILL, HT_COPY, HT_FLAT_TRI, HT_GOURAUD, HT_TEX_TRI, HT_SHADED_TEX_TRI, HT_FLAT_RECT,
    HT_TEX_RECT, HT_TEX_RECT_SCALED, HT_LINE, HT_SHADED_LINE, HT_VRAM_WRITE, HT_TRANSFER_IN, HT_DRAW_AREA,
    HT_DRAW_OFFSET, HT_DISPLAY_HIRES, HT_WIDE_CONFIGURE, HT_WIDE_VIEW, HT_WIDE_TARGET, HT_WIDE_DISABLE,
    HT_WIDE_CLEAR, HT_WIDE_MARGINS, HT_DISPLAY_WIDE,
};
