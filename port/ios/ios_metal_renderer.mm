// ios_metal_renderer.mm - the Metal renderer: the software renderer's scaled picture drawn by the GPU.
//
// The software renderer draws every primitive twice at internal resolution S: into native VRAM (the authoritative
// copy the game reads back and samples textures from) and into an S-scaled mirror the display shows, plus a
// native-wide surface in widescreen (gpu_sw_renderer.c). The mirror is what grows with S*S. This backend keeps the
// native pass on the CPU, unchanged (the software renderer at 1x: exact, and VRAM reads never wait on the GPU), and
// draws the mirrors on the GPU: each primitive is recorded with the software renderer's own scaled coordinates and
// replayed by a fragment shader that repeats its per-pixel arithmetic (ios_metal_shaders.h).
//
// Textures: a primitive samples native VRAM as it is when the CPU has drawn everything before it. The GPU reads a
// snapshot of native VRAM (a ring of copies); a new snapshot is taken only when a primitive samples a 64x64 tile
// drawn since the last one.
//
// The frame reaches the presenter (ios_present.mm) without a CPU readback: render_display_hires and
// render_wide_display hand it the GPU texture and the region to show.
#include "ios_metal_renderer.h"

#include "ios_metal_shaders.h"
#include "ios_metal_trace.h"

extern "C" {
#include "gpu_render.h"
#include "gpu_sw_renderer.h"
#include "gpu_uv.h"
#include "gpu_sw_edges.h"
uint16_t *gpu_get_vram_ptr(void);
int psx_ws_prim_in_backdrop(void);
extern int g_ws_bd_stretch_on, g_ws_bd_stretch_pct;
}

#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <QuartzCore/QuartzCore.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <vector>

namespace {

constexpr int kVramW = 1024, kVramH = 512;
constexpr int kMaxScale = 4;      // main.cpp sizes its staging for SW_MAX_INTERNAL_SCALE
constexpr int kTiles = 128;       // native VRAM as 16 x 8 tiles of 64x64
constexpr int kPages = 4096;      // tile copies in the pool (8 KiB each: 32 MiB)
constexpr int kTables = 8192;     // snapshots: the page of each tile (512 bytes each)
constexpr int kWideSurfaces = 4;  // as the software renderer
constexpr int kInFlight = 3;

// Mirrors ios_metal_shaders.h Prim (all 4-byte fields).
struct Prim {
    int32_t kind, flags, snap, s;
    int32_t cx1, cy1, cx2, cy2;
    int32_t bx0, by0, bx1, by1;
    int32_t x[3], y[3];
    int32_t u[3], v[3];
    int32_t r[3], g[3], b[3];
    float q[3];
    int32_t texpage, clut_x, clut_y, color;
    int32_t tw_mask_x, tw_mask_y, tw_off_x, tw_off_y;
    int32_t mod_r, mod_g, mod_b, pad0;
    int32_t lim[4];
    int64_t fp0, fp1, long_step, short_step0, short_step1;  // the edge walk, fixed per triangle
};
static_assert(sizeof(Prim) == 52 * 4 + 5 * 8, "Prim layout: as the shader's");

enum { K_FLAT_TRI, K_GOURAUD_TRI, K_TEX_TRI, K_SHADED_TEX_TRI, K_FLAT_RECT, K_TEX_RECT, K_TEX_RECT_SCALED, K_BLOCK,
       K_FILL, K_UPLOAD };
enum { F_SEMI = 1, F_MASK_SET = 8, F_MASK_CHECK = 16, F_RAW = 32, F_PERSPECTIVE = 64, F_FILTER = 128 };

// A render target: the hi-res mirror or a wide surface, and the primitives recorded for it since the last commit.
struct Target {
    id<MTLTexture> tex;
    int w = 0, h = 0;
    int base = -1;  // wide: the framebuffer's VRAM x (base_x)
    std::vector<Prim> prims;
};

struct State {
    id<MTLDevice> device;
    id<MTLCommandQueue> queue;
    id<MTLRenderPipelineState> prim_pipe, decode_pipe;
    // Snapshots of native VRAM: tile copies in a pool of pages, and per snapshot a table of the page each tile is
    // in. A primitive's snapshot copies only the tiles it samples that changed since their last copy.
    id<MTLBuffer> pages, tables;
    uint64_t page_used[kPages] = {};  // the latest recording that may read the page
    int16_t page_tile[kPages];        // the tile whose copy the page holds (-1 none)
    uint64_t table_used[kTables] = {};
    uint32_t cur_table[kTiles] = {};  // the newest snapshot's pages
    bool fresh[kTiles] = {};          // the tile's page matches native VRAM
    bool table_changed = true;
    int page_next = 0, table_next = 0, snap_cur = -1;
    // The hi-res mirror is skipped while a wide surface takes the framebuffer's primitives (gameplay in
    // widescreen: only the wide surface is shown), and rebuilt from native VRAM if it is shown anyway.
    bool hires_stale = false;
    // buffers for recorded primitives, reused once the GPU is past them
    struct Pooled { id<MTLBuffer> buf; uint64_t serial; };
    std::vector<Pooled> pool;
    // stats, logged every 5 s
    uint64_t st_frames = 0, st_prims_hires = 0, st_prims_wide = 0, st_snaps = 0, st_tiles = 0, st_stalls = 0,
             st_commits = 0;
    double st_cpu_snap = 0, st_cpu_commit = 0, st_window = 0;
    std::atomic<uint64_t> st_gpu_us{0};
    uint64_t serial = 1;                 // the commit being recorded
    std::atomic<uint64_t> completed{0};
    dispatch_semaphore_t inflight;
    bool ready = false, failed = false;
    bool verify = false;     // ios.metalVerify: the software renderer draws its own mirror too, compared each frame
    uint64_t verify_frames = 0, verify_bad_frames = 0, verify_bad_pixels = 0;
    uint16_t *vram = nullptr;
    int scale = 1;
    Target hires;
    Target wide[kWideSurfaces];
    int wide_w = 0, wide_off = 0, wide_cur = -1, wide_cur_base = 0;
    int view_enabled = 0, view_shift = 0, view_pad_left = 0, view_pad_right = 0;
    // draw state, as the software renderer keeps it (it is forwarded there too)
    int clip_x1 = 0, clip_y1 = 0, clip_x2 = kVramW - 1, clip_y2 = kVramH - 1;
    int semi = 0, semi_mode = 0, mask_set = 0, mask_check = 0;
    int tw_mask_x = 0, tw_mask_y = 0, tw_off_x = 0, tw_off_y = 0;
    int mod_r = 16, mod_g = 16, mod_b = 16, raw = 0;
    int precise = 0, perspective = 0;
    int32_t px16[3] = {}, py16[3] = {};
    float q[3] = {};
    // the frame for the presenter
    HercMetalFrame frame = {};
    bool frame_pending = false;
};

State &st() {
    static State *s = new State;
    return *s;
}

// ---- setup ---------------------------------------------------------------------------------------------------

bool ensure_ready() {
    State &s = st();
    if (s.ready)
        return true;
    if (s.failed)
        return false;
    s.device = herc_metal_device();
    s.queue = herc_metal_queue();
    NSError *err = nil;
    MTLCompileOptions *opts = [MTLCompileOptions new];
    if (@available(iOS 18.0, *))
        opts.mathMode = MTLMathModeSafe;  // IEEE arithmetic, as the CPU's
    id<MTLLibrary> lib = [s.device newLibraryWithSource:@(kHercMetalShaders) options:opts error:&err];
    if (!lib) {
        fprintf(stderr, "[metal] shaders: %s\n", err.localizedDescription.UTF8String);
        s.failed = true;
        return false;
    }
    MTLRenderPipelineDescriptor *d = [MTLRenderPipelineDescriptor new];
    d.vertexFunction = [lib newFunctionWithName:@"prim_vs"];
    d.fragmentFunction = [lib newFunctionWithName:@"prim_fs"];
    d.colorAttachments[0].pixelFormat = MTLPixelFormatR16Uint;
    s.prim_pipe = [s.device newRenderPipelineStateWithDescriptor:d error:&err];
    if (!s.prim_pipe)
        fprintf(stderr, "[metal] primitive pipeline: %s\n", err.localizedDescription.UTF8String);
    d.vertexFunction = [lib newFunctionWithName:@"decode_vs"];
    d.fragmentFunction = [lib newFunctionWithName:@"decode_fs"];
    d.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm;
    s.decode_pipe = [s.device newRenderPipelineStateWithDescriptor:d error:&err];
    s.pages = [s.device newBufferWithLength:(NSUInteger)kPages * 64 * 64 * 2 options:MTLResourceStorageModeShared];
    s.tables = [s.device newBufferWithLength:(NSUInteger)kTables * kTiles * 4 options:MTLResourceStorageModeShared];
    for (int i = 0; i < kPages; ++i)
        s.page_tile[i] = -1;
    if (!s.prim_pipe || !s.decode_pipe || !s.pages || !s.tables) {
        fprintf(stderr, "[metal] setup failed: %s\n", err.localizedDescription.UTF8String);
        s.failed = true;
        return false;
    }
    s.inflight = dispatch_semaphore_create(kInFlight);
    s.vram = gpu_get_vram_ptr();
    s.ready = true;
    fprintf(stderr, "[metal] renderer ready on %s\n", s.device.name.UTF8String);
    return true;
}

id<MTLTexture> make_target(int w, int h) {
    MTLTextureDescriptor *t = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatR16Uint
                                                                                 width:w
                                                                                height:h
                                                                             mipmapped:NO];
    t.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
    t.storageMode = MTLStorageModePrivate;
    return [st().device newTextureWithDescriptor:t];
}

// ---- native VRAM snapshots -------------------------------------------------------------------------------

double now_s() { return CACurrentMediaTime(); }

// Calls f(tile) for each 64x64 tile a VRAM rect touches (a wrapped rect: generously, the whole width / height).
template <typename F> void for_tiles(int x, int y, int w, int h, F f) {
    if (w <= 0 || h <= 0)
        return;
    int x0 = x & (kVramW - 1), y0 = y & (kVramH - 1);
    int x1 = x0 + w - 1, y1 = y0 + h - 1;
    if (x1 >= kVramW) { x0 = 0; x1 = kVramW - 1; }
    if (y1 >= kVramH) { y0 = 0; y1 = kVramH - 1; }
    for (int ty = y0 >> 6; ty <= y1 >> 6; ++ty)
        for (int tx = x0 >> 6; tx <= x1 >> 6; ++tx)
            f(ty * 16 + tx);
}

void mark_dirty(int x, int y, int w, int h) {
    State &s = st();
    for_tiles(x, y, w, h, [&](int t) { s.fresh[t] = false; });
}

void commit();

// Waits until no recording that may still read a slot is in flight; a slot the recording in progress may read is
// committed first.
void ensure_free(uint64_t used) {
    State &s = st();
    if (used == s.serial)
        commit();
    if (used > s.completed.load()) {
        s.st_stalls++;
        while (used > s.completed.load())
            usleep(100);
    }
}

// The newest snapshot's pages may be read by the recording in progress.
void mark_table_used(int slot) {
    State &s = st();
    if (s.table_used[slot] == s.serial)
        return;
    s.table_used[slot] = s.serial;
    const uint32_t *t = (const uint32_t *)s.tables.contents + (size_t)slot * kTiles;
    for (int i = 0; i < kTiles; ++i)
        s.page_used[t[i]] = s.serial;
}

void copy_tile(int tile) {
    State &s = st();
    const int page = s.page_next;
    ensure_free(s.page_used[page]);
    const int old = s.page_tile[page];
    if (old >= 0 && s.cur_table[old] == (uint32_t)page)
        s.fresh[old] = false;  // its copy goes: copied again when next sampled
    uint16_t *dst = (uint16_t *)s.pages.contents + (size_t)page * 4096;
    const uint16_t *src = s.vram + (size_t)(tile >> 4) * 64 * kVramW + (size_t)(tile & 15) * 64;
    for (int row = 0; row < 64; ++row)
        memcpy(dst + row * 64, src + (size_t)row * kVramW, 64 * 2);
    s.page_tile[page] = (int16_t)tile;
    s.cur_table[tile] = (uint32_t)page;
    s.fresh[tile] = true;
    s.page_next = (page + 1) % kPages;
    s.table_changed = true;
    s.st_tiles++;
}

// The snapshot a primitive reading native VRAM over these rects should use: the tiles it reads are brought up to
// date (copied) first.
int snapshot_for(const int (*rects)[4], int n) {
    State &s = st();
    if (!s.ready)
        return 0;
    const double t0 = now_s();
    for (int i = 0; i < n; ++i)
        for_tiles(rects[i][0], rects[i][1], rects[i][2], rects[i][3], [&](int t) {
            if (!s.fresh[t])
                copy_tile(t);
        });
    if (s.table_changed || s.snap_cur < 0) {
        const int slot = s.table_next;
        ensure_free(s.table_used[slot]);
        memcpy((uint32_t *)s.tables.contents + (size_t)slot * kTiles, s.cur_table, sizeof s.cur_table);
        s.table_used[slot] = 0;
        s.snap_cur = slot;
        s.table_next = (slot + 1) % kTables;
        s.table_changed = false;
        s.st_snaps++;
    }
    mark_table_used(s.snap_cur);
    s.st_cpu_snap += now_s() - t0;
    return s.snap_cur;
}

// The VRAM a textured primitive samples: its texture page (as wide as its depth reads) and its CLUT row.
int snapshot_for_texture(uint16_t texpage, int clut_x, int clut_y) {
    const int depth = (texpage >> 7) & 3;
    const int tpx = (texpage & 0xF) * 64, tpy = ((texpage >> 4) & 1) * 256;
    const int width = depth == 0 ? 64 : depth == 1 ? 128 : 256;
    const int clut_w = depth == 0 ? 16 : depth == 1 ? 256 : 0;
    const int rects[2][4] = {{tpx, tpy, width, 256}, {clut_x, clut_y, clut_w ? clut_w : 1, 1}};
    return snapshot_for(rects, clut_w ? 2 : 1);
}

// ---- recording -------------------------------------------------------------------------------------------

int flags_now(bool textured) {
    State &s = st();
    int f = 0;
    if (s.semi)
        f |= F_SEMI | (s.semi_mode << 1);
    if (s.mask_set) f |= F_MASK_SET;
    if (s.mask_check) f |= F_MASK_CHECK;
    if (textured && s.raw) f |= F_RAW;
    if (textured && sw_texture_filter()) f |= F_FILTER;
    return f;
}

Prim base_prim(int kind, int flags) {
    State &s = st();
    Prim p = {};
    p.kind = kind;
    p.flags = flags;
    p.snap = std::max(s.snap_cur, 0);
    p.tw_mask_x = s.tw_mask_x; p.tw_mask_y = s.tw_mask_y; p.tw_off_x = s.tw_off_x; p.tw_off_y = s.tw_off_y;
    p.mod_r = s.mod_r; p.mod_g = s.mod_g; p.mod_b = s.mod_b;
    p.lim[0] = 0; p.lim[1] = 0; p.lim[2] = 255; p.lim[3] = 255;
    return p;
}

// The clip rectangles of the two targets (gpu_sw_renderer.c rt_hires, rt_wide).
void clip_hires(Prim &p) {
    State &s = st();
    const int k = s.scale;
    p.s = k;
    p.cx1 = s.clip_x1 * k; p.cy1 = s.clip_y1 * k;
    p.cx2 = s.clip_x2 * k + (k - 1); p.cy2 = s.clip_y2 * k + (k - 1);
}
void clip_wide(Prim &p) {
    State &s = st();
    const int k = s.scale;
    p.s = k;
    p.cx1 = s.view_pad_left * k; p.cy1 = s.clip_y1 * k;
    p.cx2 = (s.wide_w - s.view_pad_right) * k - 1; p.cy2 = s.clip_y2 * k + (k - 1);
}

void push(Target &t, Prim p) {
    // the quad, clipped to the clip rect and the target
    p.bx0 = std::max({p.bx0, p.cx1, 0});
    p.by0 = std::max({p.by0, p.cy1, 0});
    p.bx1 = std::min({p.bx1, p.cx2 + 1, t.w});
    p.by1 = std::min({p.by1, p.cy2 + 1, t.h});
    if (p.bx0 >= p.bx1 || p.by0 >= p.by1)
        return;
    t.prims.push_back(p);
}

// Unclipped (fills, uploads): only the target's bounds.
void push_raw(Target &t, Prim p) {
    p.cx1 = p.cy1 = 0; p.cx2 = t.w - 1; p.cy2 = t.h - 1;
    push(t, p);
}

bool have_hires() { return st().scale > 1 && st().hires.tex; }
Target *wide_target();
// The framebuffer's primitives go to the hi-res mirror unless a wide surface takes them (and the mirror is not
// being compared against the software renderer's).
bool record_hires() {
    State &s = st();
    if (!have_hires())
        return false;
    if (wide_target() && !s.verify) {
        s.hires_stale = true;
        return false;
    }
    return true;
}
// Without Metal (no framebuffer fetch: the Simulator) the software renderer does everything, its mirror included.
bool passthrough() { return !st().ready; }
// The software renderer keeps its own mirror and wide surfaces: without Metal, or to compare against.
bool sw_mirrors() { return passthrough() || st().verify; }
Target *wide_target() {
    State &s = st();
    return s.wide_cur >= 0 && s.wide[s.wide_cur].tex ? &s.wide[s.wide_cur] : nullptr;
}

// gpu_sw_renderer.c precise_scaled / wide_dx / wide_bd_*
int precise_scaled(int axis, int vertex, int fallback, int k) {
    State &s = st();
    if (!s.precise)
        return fallback * k;
    int64_t fixed = axis ? s.py16[vertex] : s.px16[vertex];
    int64_t scaled = fixed * k;
    if (scaled >= 0) return (int)((scaled + 0x8000) >> 16);
    return -(int)((-scaled + 0x8000) >> 16);
}
int wide_dx() { State &s = st(); return s.wide_off + s.view_shift - s.wide_cur_base; }
struct Bd { int on; float scale, center; };
Bd bd_get() {
    State &s = st();
    Bd b = {0, 1.0f, 0.0f};
    if (g_ws_bd_stretch_on && s.wide_w > 0 && wide_target() && psx_ws_prim_in_backdrop()) {
        const int native_w = s.wide_w - 2 * s.wide_off;
        if (native_w > 0) {
            b.on = 1;
            b.scale = g_ws_bd_stretch_pct > 0 ? (float)g_ws_bd_stretch_pct / 100.0f : (float)s.wide_w / (float)native_w;
            b.center = (float)s.wide_cur_base + (float)native_w / 2.0f;
        }
    }
    return b;
}
int bd_x(const Bd &b, int x) {
    if (!b.on) return x;
    float v = ((float)x - b.center) * b.scale + b.center;
    return (int)(v < 0.0f ? v - 0.5f : v + 0.5f);
}
int precise_wide_x(int vertex, int fallback, int k, int dx, const Bd &bd) {
    if (st().precise)
        return precise_scaled(0, vertex, fallback, k) + dx * k;
    return (bd_x(bd, fallback) + dx) * k;
}
void precise_consumed() { st().precise = 0; st().perspective = 0; }

// A triangle in target space: sorted by y as the software rasterizer sorts it (vertex attributes travel along).
struct Vert { int x, y, u, v, r, g, b; float q; };
void tri_into(Prim &p, Vert a, Vert b, Vert c) {
    if (a.y > b.y) std::swap(a, b);
    if (a.y > c.y) std::swap(a, c);
    if (b.y > c.y) std::swap(b, c);
    const Vert v[3] = {a, b, c};
    for (int i = 0; i < 3; ++i) {
        p.x[i] = v[i].x; p.y[i] = v[i].y; p.u[i] = v[i].u; p.v[i] = v[i].v;
        p.r[i] = v[i].r; p.g[i] = v[i].g; p.b[i] = v[i].b; p.q[i] = v[i].q;
    }
    p.bx0 = std::min({a.x, b.x, c.x}) - 1;
    p.bx1 = std::max({a.x, b.x, c.x}) + 2;
    p.by0 = a.y;
    p.by1 = c.y;
    // gpu_sw_edges.h psx_triangle_edges_at_y's per-triangle part (a step whose edge has no height is never used)
    p.fp0 = psx_edge_fp(a.x);
    p.fp1 = psx_edge_fp(b.x);
    p.long_step = c.y != a.y ? psx_edge_step(c.x - a.x, c.y - a.y) : 0;
    p.short_step0 = b.y != a.y ? psx_edge_step(b.x - a.x, b.y - a.y) : 0;
    p.short_step1 = c.y != b.y ? psx_edge_step(c.x - b.x, c.y - b.y) : 0;
}

// Records a triangle for the hi-res mirror and the active wide surface.
void record_tri(int kind, int flags, const int xs[3], const int ys[3], const int us[3], const int vs[3],
                const int rs[3], const int gs[3], const int bs[3], Prim proto) {
    State &s = st();
    const int k = s.scale;
    if (s.perspective) proto.flags |= F_PERSPECTIVE;
    (void)kind;
    if (record_hires()) {
        Prim p = proto;
        clip_hires(p);
        Vert v[3];
        for (int i = 0; i < 3; ++i)
            v[i] = {precise_scaled(0, i, xs[i], k), precise_scaled(1, i, ys[i], k), us[i], vs[i], rs[i], gs[i], bs[i],
                    s.q[i]};
        tri_into(p, v[0], v[1], v[2]);
        if (p.y[2] != p.y[0])
            push(s.hires, p);
    }
    if (Target *w = wide_target()) {
        Prim p = proto;
        clip_wide(p);
        const int dx = wide_dx();
        const Bd bd = bd_get();
        Vert v[3];
        for (int i = 0; i < 3; ++i)
            v[i] = {precise_wide_x(i, xs[i], k, dx, bd), precise_scaled(1, i, ys[i], k), us[i], vs[i], rs[i], gs[i],
                    bs[i], s.q[i]};
        tri_into(p, v[0], v[1], v[2]);
        if (p.y[2] != p.y[0])
            push(*w, p);
    }
    (void)flags;
}

void rect_into(Prim &p, int x, int y, int w, int h) {
    p.x[0] = x; p.y[0] = y; p.x[1] = w; p.y[1] = h;
    p.bx0 = x; p.by0 = y; p.bx1 = x + w; p.by1 = y + h;
}

void tri_bbox_dirty(const int xs[3], const int ys[3]) {
    State &s = st();
    int x0 = std::max(std::min({xs[0], xs[1], xs[2]}), s.clip_x1);
    int x1 = std::min(std::max({xs[0], xs[1], xs[2]}), s.clip_x2);
    int y0 = std::max(std::min({ys[0], ys[1], ys[2]}), s.clip_y1);
    int y1 = std::min(std::max({ys[0], ys[1], ys[2]}), s.clip_y2);
    if (x0 <= x1 && y0 <= y1)
        mark_dirty(x0, y0, x1 - x0 + 1, y1 - y0 + 1);
}

void rect_dirty(int x, int y, int w, int h) {
    State &s = st();
    int x0 = std::max(x, s.clip_x1), x1 = std::min(x + w - 1, s.clip_x2);
    int y0 = std::max(y, s.clip_y1), y1 = std::min(y + h - 1, s.clip_y2);
    if (x0 <= x1 && y0 <= y1)
        mark_dirty(x0, y0, x1 - x0 + 1, y1 - y0 + 1);
}

// Raw writes of native VRAM into the hi-res mirror (transfers, single pixels, a rebuild): pixel for pixel from the
// snapshot, s*s each (gpu_sw_renderer.c sw_vram_transfer_in / sw_vram_write / hr_rebuild_from_vram).
void record_upload(int x, int y, int w, int h) {
    State &s = st();
    if (!have_hires() || w <= 0 || h <= 0)
        return;
    const int k = s.scale;
    const int rects[1][4] = {{x, y, w, h}};
    const int snap = snapshot_for(rects, 1);
    x &= kVramW - 1;
    y &= kVramH - 1;
    // split where the rect wraps
    const int xs[2][2] = {{x, std::min(w, kVramW - x)}, {0, x + w - kVramW}};
    const int ys[2][2] = {{y, std::min(h, kVramH - y)}, {0, y + h - kVramH}};
    for (auto &rx : xs)
        for (auto &ry : ys) {
            if (rx[1] <= 0 || ry[1] <= 0)
                continue;
            Prim p = base_prim(K_UPLOAD, 0);
            p.snap = snap;
            p.s = k;
            rect_into(p, rx[0] * k, ry[0] * k, rx[1] * k, ry[1] * k);
            push_raw(s.hires, p);
        }
}

// ---- the backend's entry points ----------------------------------------------------------------------------

void m_init(uint16_t *vram) {
    sw_renderer_init(vram);
    State &s = st();
    s.vram = vram;
    s.clip_x1 = s.clip_y1 = 0;
    s.clip_x2 = kVramW - 1; s.clip_y2 = kVramH - 1;
    s.semi = s.semi_mode = s.mask_set = s.mask_check = 0;
    s.tw_mask_x = s.tw_mask_y = s.tw_off_x = s.tw_off_y = 0;
    s.mod_r = s.mod_g = s.mod_b = 16;
    s.raw = 0;
    for (bool &f : s.fresh) f = false;
    record_upload(0, 0, kVramW, kVramH);
}

void m_set_scale(int scale) {
    State &s = st();
    scale = std::clamp(scale, 1, kMaxScale);
    s.verify = [NSUserDefaults.standardUserDefaults boolForKey:@"ios.metalVerify"];
    if (!ensure_ready()) {
        sw_renderer_set_scale(scale);  // passthrough: the software renderer's own mirror
        s.scale = scale;
        fprintf(stderr, "[metal] unavailable: the software renderer draws at %dx\n", scale);
        return;
    }
    sw_renderer_set_scale(s.verify ? scale : 1);  // the CPU keeps native only (and its mirror when verifying)
    commit();
    s.scale = scale;
    s.hires = Target();
    for (auto &w : s.wide) w = Target();
    s.wide_cur = -1;
    if (scale > 1) {
        s.hires.w = kVramW * scale;
        s.hires.h = kVramH * scale;
        s.hires.tex = make_target(s.hires.w, s.hires.h);
        for (bool &f : s.fresh) f = false;
        record_upload(0, 0, kVramW, kVramH);  // the mirror starts as native VRAM, as the software renderer's
    }
    fprintf(stderr, "[metal] internal scale %d\n", s.scale);
}

int m_scale(void) { return passthrough() ? sw_renderer_scale() : st().scale; }

void m_set_texture_filter(int bilinear) { sw_set_texture_filter(bilinear); }
int m_texture_filter(void) { return sw_texture_filter(); }

void m_set_semi(int enabled, int mode) {
    sw_set_semi_transparency(enabled, mode);
    st().semi = enabled;
    st().semi_mode = mode & 3;
}
void m_set_mask(int set_bit, int check_bit) {
    sw_set_mask_bits(set_bit, check_bit);
    st().mask_set = set_bit;
    st().mask_check = check_bit;
}
void m_set_tw(uint32_t raw) {
    sw_set_texture_window(raw);
    State &s = st();
    s.tw_mask_x = raw & 0x1F; s.tw_mask_y = (raw >> 5) & 0x1F;
    s.tw_off_x = (raw >> 10) & 0x1F; s.tw_off_y = (raw >> 15) & 0x1F;
}
void m_set_mod(int r, int g, int b, int raw_texture) {
    sw_set_color_modulation(r, g, b, raw_texture);
    State &s = st();
    s.mod_r = r >> 3; s.mod_g = g >> 3; s.mod_b = b >> 3;
    s.raw = raw_texture;
}
void m_set_precise(int enabled, int32_t x0, int32_t y0, int32_t x1, int32_t y1, int32_t x2, int32_t y2) {
    sw_set_precise_triangle(enabled, x0, y0, x1, y1, x2, y2);
    State &s = st();
    s.precise = enabled && !sw_faithful_authority();
    s.px16[0] = x0; s.py16[0] = y0; s.px16[1] = x1; s.py16[1] = y1; s.px16[2] = x2; s.py16[2] = y2;
}
void m_set_perspective(int enabled, float q0, float q1, float q2) {
    sw_set_perspective_triangle(enabled, q0, q1, q2);
    State &s = st();
    s.perspective = enabled && q0 > 0 && q1 > 0 && q2 > 0 && !sw_faithful_authority();
    s.q[0] = q0; s.q[1] = q1; s.q[2] = q2;
}

void m_fill_rect(int x, int y, int w, int h, uint16_t color) {
    sw_fill_rect(x, y, w, h, color);
    mark_dirty(x, y, w, h);
    State &s = st();
    if (!have_hires() || w <= 0 || h <= 0)
        return;
    const int k = s.scale;
    const int x0 = (x & (kVramW - 1)) * k, y0 = (y & (kVramH - 1)) * k, W = w * k, H = h * k;
    const int xs[2][2] = {{x0, std::min(W, s.hires.w - x0)}, {0, x0 + W - s.hires.w}};
    const int ys[2][2] = {{y0, std::min(H, s.hires.h - y0)}, {0, y0 + H - s.hires.h}};
    for (auto &rx : xs)
        for (auto &ry : ys) {
            if (rx[1] <= 0 || ry[1] <= 0)
                continue;
            Prim p = base_prim(K_FILL, 0);
            p.color = color;
            rect_into(p, rx[0], ry[0], rx[1], ry[1]);
            push_raw(s.hires, p);
        }
}

void m_copy_rect(int sx, int sy, int dx, int dy, int w, int h) {
    sw_copy_rect(sx, sy, dx, dy, w, h);
    mark_dirty(dx, dy, w, h);
    // the destination from native VRAM: the copied picture at native detail (the software renderer copies the
    // mirror's own pixels; copies are rare and this keeps the mirror coherent)
    record_upload(dx, dy, w, h);
}

void m_flat_tri(int x0, int y0, int x1, int y1, int x2, int y2, uint16_t color) {
    sw_draw_flat_triangle(x0, y0, x1, y1, x2, y2, color);
    const int xs[3] = {x0, x1, x2}, ys[3] = {y0, y1, y2}, z[3] = {};
    tri_bbox_dirty(xs, ys);
    Prim p = base_prim(K_FLAT_TRI, flags_now(false));
    p.color = color;
    record_tri(K_FLAT_TRI, p.flags, xs, ys, z, z, z, z, z, p);
    precise_consumed();
}

void m_gouraud_tri(int x0, int y0, uint16_t c0, int x1, int y1, uint16_t c1, int x2, int y2, uint16_t c2) {
    sw_draw_gouraud_triangle(x0, y0, c0, x1, y1, c1, x2, y2, c2);
    const int xs[3] = {x0, x1, x2}, ys[3] = {y0, y1, y2}, z[3] = {};
    const uint16_t c[3] = {c0, c1, c2};
    int rs[3], gs[3], bs[3];
    for (int i = 0; i < 3; ++i) { rs[i] = c[i] & 0x1F; gs[i] = (c[i] >> 5) & 0x1F; bs[i] = (c[i] >> 10) & 0x1F; }
    tri_bbox_dirty(xs, ys);
    Prim p = base_prim(K_GOURAUD_TRI, flags_now(false));
    record_tri(K_GOURAUD_TRI, p.flags, xs, ys, z, z, rs, gs, bs, p);
    precise_consumed();
}

void tex_limits_tri(Prim &p, const int xs[3], const int ys[3], const int us[3], const int vs[3]) {
    if (!(p.flags & F_FILTER))
        return;
    if (st().perspective) psx_uv_tri_world_limits(us, vs, p.lim);
    else psx_uv_tri_limits(xs, ys, us, vs, p.lim);
}

void m_tex_tri(int x0, int y0, int u0, int v0, int x1, int y1, int u1, int v1, int x2, int y2, int u2, int v2,
               uint16_t clut_x, uint16_t clut_y, uint16_t texpage) {
    const int64_t area2 = (int64_t)(x1 - x0) * (y2 - y0) - (int64_t)(x2 - x0) * (y1 - y0);
    const int snap = area2 ? snapshot_for_texture(texpage, clut_x, clut_y) : 0;  // before the CPU draws it
    sw_draw_textured_triangle(x0, y0, u0, v0, x1, y1, u1, v1, x2, y2, u2, v2, clut_x, clut_y, texpage);
    if (area2 == 0) { precise_consumed(); return; }
    const int xs[3] = {x0, x1, x2}, ys[3] = {y0, y1, y2}, us[3] = {u0, u1, u2}, vs[3] = {v0, v1, v2}, z[3] = {};
    tri_bbox_dirty(xs, ys);
    Prim p = base_prim(K_TEX_TRI, flags_now(true));
    p.snap = snap;
    p.texpage = texpage; p.clut_x = clut_x; p.clut_y = clut_y;
    tex_limits_tri(p, xs, ys, us, vs);
    record_tri(K_TEX_TRI, p.flags, xs, ys, us, vs, z, z, z, p);
    precise_consumed();
}

void m_shaded_tex_tri(int x0, int y0, int u0, int v0, uint32_t c0, int x1, int y1, int u1, int v1, uint32_t c1,
                      int x2, int y2, int u2, int v2, uint32_t c2, uint16_t clut_x, uint16_t clut_y,
                      uint16_t texpage, int raw_texture) {
    const int64_t area2 = (int64_t)(x1 - x0) * (y2 - y0) - (int64_t)(x2 - x0) * (y1 - y0);
    const int snap = area2 ? snapshot_for_texture(texpage, clut_x, clut_y) : 0;
    sw_draw_shaded_textured_triangle(x0, y0, u0, v0, c0, x1, y1, u1, v1, c1, x2, y2, u2, v2, c2, clut_x, clut_y,
                                     texpage, raw_texture);
    if (area2 == 0) { precise_consumed(); return; }
    const int xs[3] = {x0, x1, x2}, ys[3] = {y0, y1, y2}, us[3] = {u0, u1, u2}, vs[3] = {v0, v1, v2};
    const uint32_t c[3] = {c0, c1, c2};
    int rs[3], gs[3], bs[3];
    for (int i = 0; i < 3; ++i) {
        rs[i] = (int)(c[i] & 0xFF) >> 3; gs[i] = (int)((c[i] >> 8) & 0xFF) >> 3; bs[i] = (int)((c[i] >> 16) & 0xFF) >> 3;
    }
    tri_bbox_dirty(xs, ys);
    int flags = flags_now(true) & ~F_RAW;
    if (raw_texture) flags |= F_RAW;
    Prim p = base_prim(K_SHADED_TEX_TRI, flags);
    p.snap = snap;
    p.texpage = texpage; p.clut_x = clut_x; p.clut_y = clut_y;
    tex_limits_tri(p, xs, ys, us, vs);
    record_tri(K_SHADED_TEX_TRI, p.flags, xs, ys, us, vs, rs, gs, bs, p);
    precise_consumed();
}

void m_flat_rect(int x, int y, int w, int h, uint16_t color) {
    sw_draw_flat_rect(x, y, w, h, color);
    rect_dirty(x, y, w, h);
    State &s = st();
    const int k = s.scale;
    Prim proto = base_prim(K_FLAT_RECT, flags_now(false));
    proto.color = color;
    if (record_hires()) {
        Prim p = proto;
        clip_hires(p);
        rect_into(p, x * k, y * k, w * k, h * k);
        push(s.hires, p);
    }
    if (Target *t = wide_target()) {
        Prim p = proto;
        clip_wide(p);
        const int dx = wide_dx();
        const int native_w = s.wide_w - 2 * s.wide_off;
        const int lx = x - s.wide_cur_base, rx = x + w - s.wide_cur_base;
        const Bd bd = bd_get();
        if (native_w > 0 && lx <= 0 && rx >= native_w)
            rect_into(p, 0, y * k, s.wide_w * k, h * k);  // a full-screen overlay covers the margins too
        else if (bd.on) {
            const int xl = bd_x(bd, x), xr = bd_x(bd, x + w);
            rect_into(p, (xl + dx) * k, y * k, (xr - xl) * k, h * k);
        } else
            rect_into(p, (x + dx) * k, y * k, w * k, h * k);
        push(*t, p);
    }
}

void m_tex_rect(int x, int y, int w, int h, int u, int v, uint16_t clut_x, uint16_t clut_y, uint16_t texpage) {
    const int snap = snapshot_for_texture(texpage, clut_x, clut_y);
    sw_draw_textured_rect(x, y, w, h, u, v, clut_x, clut_y, texpage);
    rect_dirty(x, y, w, h);
    State &s = st();
    const int k = s.scale;
    Prim proto = base_prim(K_TEX_RECT, flags_now(true));
    proto.snap = snap;
    proto.texpage = texpage; proto.clut_x = clut_x; proto.clut_y = clut_y;
    proto.u[0] = u; proto.v[0] = v;
    if (proto.flags & F_FILTER) psx_uv_rect_limits(u, v, u + w, v + h, proto.lim);
    if (record_hires()) {
        Prim p = proto;
        clip_hires(p);
        rect_into(p, x * k, y * k, w * k, h * k);
        push(s.hires, p);
    }
    if (Target *t = wide_target()) {
        Prim p = proto;
        clip_wide(p);
        const int dx = wide_dx();
        const Bd bd = bd_get();
        if (bd.on) {  // stretched about the screen centre: the scaled sampler
            const int xl = bd_x(bd, x), xr = bd_x(bd, x + w);
            p.kind = K_TEX_RECT_SCALED;
            p.u[0] = u; p.v[0] = v; p.u[1] = u + w; p.v[1] = v + h;
            rect_into(p, (xl + dx) * k, y * k, (xr - xl) * k, h * k);
        } else
            rect_into(p, (x + dx) * k, y * k, w * k, h * k);
        push(*t, p);
    }
}

void m_tex_rect_scaled(int x, int y, int w, int h, int u0, int v0, int u1, int v1, uint16_t clut_x, uint16_t clut_y,
                       uint16_t texpage) {
    if (w <= 0 || h <= 0) return;
    const int snap = snapshot_for_texture(texpage, clut_x, clut_y);
    sw_draw_textured_rect_scaled(x, y, w, h, u0, v0, u1, v1, clut_x, clut_y, texpage);
    rect_dirty(x, y, w, h);
    State &s = st();
    const int k = s.scale;
    Prim proto = base_prim(K_TEX_RECT_SCALED, flags_now(true));
    proto.snap = snap;
    proto.texpage = texpage; proto.clut_x = clut_x; proto.clut_y = clut_y;
    proto.u[0] = u0; proto.v[0] = v0; proto.u[1] = u1; proto.v[1] = v1;
    if (proto.flags & F_FILTER) psx_uv_rect_limits(u0, v0, u1, v1, proto.lim);
    if (record_hires()) {
        Prim p = proto;
        clip_hires(p);
        rect_into(p, x * k, y * k, w * k, h * k);
        push(s.hires, p);
    }
    if (Target *t = wide_target()) {
        Prim p = proto;
        clip_wide(p);
        const int dx = wide_dx();
        const Bd bd = bd_get();
        const int xl = bd_x(bd, x), xr = bd_x(bd, x + w);
        rect_into(p, (xl + dx) * k, y * k, (xr - xl) * k, h * k);
        push(*t, p);
    }
}

// A line pixel: an s*s block in each mirror (gpu_sw_renderer.c hr_put_block_opaque / wide_put_block_opaque).
void line_block(int nx, int ny, uint16_t color, int flags) {
    State &s = st();
    const int k = s.scale;
    Prim proto = base_prim(K_BLOCK, flags);
    proto.color = color;
    if (record_hires()) {
        Prim p = proto;
        clip_hires(p);
        rect_into(p, nx * k, ny * k, k, k);
        push(s.hires, p);
    }
    if (Target *t = wide_target()) {
        Prim p = proto;
        clip_wide(p);
        rect_into(p, (nx + wide_dx()) * k, ny * k, k, k);
        push(*t, p);
    }
}

void m_line(int x0, int y0, int x1, int y1, uint16_t color) {
    sw_draw_line(x0, y0, x1, y1, color);
    const int flags = flags_now(false);
    int dx = abs(x1 - x0), dy = -abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1, err = dx + dy;
    for (;;) {
        rect_dirty(x0, y0, 1, 1);
        line_block(x0, y0, color, flags);
        if (x0 == x1 && y0 == y1) break;
        int e2 = 2 * err;
        if (e2 >= dy) { err += dy; x0 += sx; }
        if (e2 <= dx) { err += dx; y0 += sy; }
    }
}

void m_shaded_line(int x0, int y0, uint16_t c0, int x1, int y1, uint16_t c1) {
    sw_draw_shaded_line(x0, y0, c0, x1, y1, c1);
    const int flags = flags_now(false);
    int dx = abs(x1 - x0), dy = -abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1, err = dx + dy;
    int total = std::max(abs(x1 - x0), abs(y1 - y0));
    if (total == 0) total = 1;
    const int r0 = c0 & 0x1F, g0 = (c0 >> 5) & 0x1F, b0 = (c0 >> 10) & 0x1F;
    const int r1 = c1 & 0x1F, g1 = (c1 >> 5) & 0x1F, b1 = (c1 >> 10) & 0x1F;
    for (int step = 0;; ++step) {
        const int r = r0 + (r1 - r0) * step / total, g = g0 + (g1 - g0) * step / total,
                  b = b0 + (b1 - b0) * step / total;
        rect_dirty(x0, y0, 1, 1);
        line_block(x0, y0, (uint16_t)(r | (g << 5) | (b << 10)), flags);
        if (x0 == x1 && y0 == y1) break;
        int e2 = 2 * err;
        if (e2 >= dy) { err += dy; x0 += sx; }
        if (e2 <= dx) { err += dx; y0 += sy; }
    }
}

void m_vram_write(int x, int y, uint16_t pixel) {
    sw_vram_write(x, y, pixel);
    mark_dirty(x, y, 1, 1);
    record_upload(x, y, 1, 1);
}
uint16_t m_vram_read(int x, int y) { return sw_vram_read(x, y); }
void m_transfer_in(int x, int y, int w, int h, const uint16_t *data) {
    sw_vram_transfer_in(x, y, w, h, data);
    mark_dirty(x, y, w, h);
    record_upload(x, y, w, h);
}
void m_transfer_out(int x, int y, int w, int h, uint16_t *data) { sw_vram_transfer_out(x, y, w, h, data); }

void m_set_draw_area(int x1, int y1, int x2, int y2) {
    sw_set_draw_area(x1, y1, x2, y2);
    sw_get_draw_area(&st().clip_x1, &st().clip_y1, &st().clip_x2, &st().clip_y2);
}
void m_get_draw_area(int *x1, int *y1, int *x2, int *y2) { sw_get_draw_area(x1, y1, x2, y2); }
void m_set_draw_offset(int x, int y) { sw_set_draw_offset(x, y); }

int m_render_display(uint32_t *out, int pitch, int dx, int dy, int dw, int dh) {
    return sw_render_display(out, pitch, dx, dy, dw, dh);
}

// The hi-res picture: committed, and handed to the presenter as a region of the mirror (no readback).
void verify_frame(id<MTLTexture> tex, int x, int y, int w, int h, const uint32_t *cpu, int pitch);

// Every 5 s: what a frame cost, in the log (Documents/Logs/hercules.log on the device).
void stats_tick(bool force = false) {
    State &s = st();
    if (!force)
        s.st_frames++;
    const double now = now_s();
    if (s.st_window == 0)
        s.st_window = now;
    if (now - s.st_window < 5.0 && !(force && s.st_frames))
        return;
    const double n = (double)std::max<uint64_t>(s.st_frames, 1);
    const char *thermal[] = {"nominal", "fair", "serious", "critical"};
    const NSInteger th = NSProcessInfo.processInfo.thermalState;
    fprintf(stderr,
            "[metal] %.1f fps | per frame: prims %.0f hi-res + %.0f wide, snapshots %.1f, tiles %.1f, commits %.2f, "
            "cpu %.2f ms snapshots + %.2f ms commit, gpu %.2f ms | stalls %llu | scale %d | thermal %s\n",
            n / (now - s.st_window), s.st_prims_hires / n, s.st_prims_wide / n, s.st_snaps / n, s.st_tiles / n,
            s.st_commits / n, s.st_cpu_snap * 1000 / n, s.st_cpu_commit * 1000 / n,
            s.st_gpu_us.exchange(0) / 1000.0 / n, (unsigned long long)s.st_stalls, s.scale,
            thermal[std::clamp<NSInteger>(th, 0, 3)]);
    s.st_frames = s.st_prims_hires = s.st_prims_wide = s.st_snaps = s.st_tiles = s.st_stalls = s.st_commits = 0;
    s.st_cpu_snap = s.st_cpu_commit = 0;
    s.st_window = now;
}

int m_render_display_hires(uint32_t *out, int pitch, int dx, int dy, int dw, int dh) {
    State &s = st();
    if (passthrough())
        return sw_render_display_hires(out, pitch, dx, dy, dw, dh);
    if (!have_hires())
        return sw_render_display(out, pitch, dx, dy, dw, dh);
    if (s.hires_stale) {  // shown after widescreen play skipped it: the picture from native VRAM
        record_upload(dx, dy, dw, dh);
        s.hires_stale = false;
    }
    commit();
    stats_tick();
    const int k = s.scale;
    s.frame.texture = (__bridge void *)s.hires.tex;
    s.frame.x = (dx & (kVramW - 1)) * k;
    s.frame.y = (dy & (kVramH - 1)) * k;
    s.frame.w = dw * k;
    s.frame.h = dh * k;
    s.frame_pending = true;
    if (s.verify) {
        sw_render_display_hires(out, pitch, dx, dy, dw, dh);
        verify_frame(s.hires.tex, s.frame.x, s.frame.y, s.frame.w, s.frame.h, out, pitch);
    }
    return dw * k * dh * k;
}

// ---- native-wide surfaces (gpu_sw_renderer.c sw_wide_*) ----

int wide_index(int base_x, bool create) {
    State &s = st();
    if (s.wide_w <= 0 || !ensure_ready())
        return -1;
    for (int i = 0; i < kWideSurfaces; ++i)
        if (s.wide[i].tex && s.wide[i].base == base_x)
            return i;
    if (!create)
        return -1;
    for (int i = 0; i < kWideSurfaces; ++i)
        if (!s.wide[i].tex) {
            Target &t = s.wide[i];
            t.w = s.wide_w * s.scale;
            t.h = kVramH * s.scale;
            t.base = base_x;
            t.tex = make_target(t.w, t.h);
            Prim p = base_prim(K_FILL, 0);  // calloc'd: zero
            p.color = 0;
            rect_into(p, 0, 0, t.w, t.h);
            push_raw(t, p);
            return i;
        }
    return -1;
}

void free_wide() {
    State &s = st();
    commit();
    for (auto &w : s.wide) w = Target();
    s.wide_cur = -1;
}

void m_wide_configure(int wide_w, int offset) {
    if (sw_mirrors()) sw_wide_configure(wide_w, offset);
    State &s = st();
    if (wide_w <= 0) { free_wide(); s.wide_w = 0; s.wide_off = 0; return; }
    if (wide_w != s.wide_w) free_wide();
    s.wide_w = wide_w;
    s.wide_off = offset;
}
void m_wide_set_view(int enabled, int shift, int pad_left, int pad_right) {
    if (sw_mirrors()) sw_wide_set_view(enabled, shift, pad_left, pad_right);
    State &s = st();
    if (!enabled) shift = pad_left = pad_right = 0;
    s.view_enabled = enabled; s.view_shift = shift; s.view_pad_left = pad_left; s.view_pad_right = pad_right;
}
void m_wide_set_target(int base_x) {
    if (sw_mirrors()) sw_wide_set_target(base_x);
    State &s = st();
    s.wide_cur = wide_index(base_x, true);
    s.wide_cur_base = base_x;
}
void m_wide_disable_target(void) {
    if (sw_mirrors()) sw_wide_disable_target();
    st().wide_cur = -1;
}

void wide_fill(int base_x, int x0, int y0, int x1, int y1, uint16_t color) {
    const int i = wide_index(base_x, true);
    if (i < 0) return;
    Target &t = st().wide[i];
    Prim p = base_prim(K_FILL, 0);
    p.color = color;
    rect_into(p, x0, y0, x1 - x0, y1 - y0);
    push_raw(t, p);
}
void m_wide_clear(int base_x, int y, int h, uint16_t color) {
    if (sw_mirrors()) sw_wide_clear(base_x, y, h, color);
    State &s = st();
    const int k = s.scale;
    wide_fill(base_x, 0, y * k, s.wide_w * k, (y + h) * k, color);
}
void m_wide_clear_margins(int base_x, int y, int h, uint16_t color, int sides) {
    if (sw_mirrors()) sw_wide_clear_margins(base_x, y, h, color, sides);
    State &s = st();
    const int k = s.scale, W = s.wide_w * k, margin = s.wide_off * k;
    if (margin <= 0 || margin * 2 >= W) return;
    if (sides & 1) wide_fill(base_x, 0, y * k, margin, (y + h) * k, color);
    if (sides & 2) wide_fill(base_x, W - margin, y * k, W, (y + h) * k, color);
}

int m_render_wide_display(uint32_t *out, int pitch, int base_x, int disp_y, int disp_h) {
    State &s = st();
    if (passthrough())
        return sw_render_wide_display(out, pitch, base_x, disp_y, disp_h);
    const int i = wide_index(base_x, false);
    if (i < 0 || s.wide_w <= 0) return 0;
    commit();
    stats_tick();
    const int k = s.scale;
    Target &t = s.wide[i];
    s.frame.texture = (__bridge void *)t.tex;
    s.frame.x = 0;
    s.frame.y = std::clamp(disp_y * k, 0, t.h - 1);
    s.frame.w = t.w;
    s.frame.h = std::min(disp_h * k, t.h - s.frame.y);
    s.frame_pending = true;
    if (s.verify && sw_render_wide_display(out, pitch, base_x, disp_y, disp_h) > 0)
        verify_frame(t.tex, s.frame.x, s.frame.y, s.frame.w, s.frame.h, out, pitch);
    return t.w * disp_h * k;
}

int m_wide_dump_full(uint32_t *, int, int *, int *, int) { return 0; }

// ---- verify: the GPU's picture against the software renderer's, pixel for pixel ----

void verify_frame(id<MTLTexture> tex, int x, int y, int w, int h, const uint32_t *cpu, int pitch) {
    State &s = st();
    id<MTLBuffer> buf = [s.device newBufferWithLength:(NSUInteger)w * h * 2 options:MTLResourceStorageModeShared];
    id<MTLCommandBuffer> cb = [s.queue commandBuffer];
    id<MTLBlitCommandEncoder> blit = [cb blitCommandEncoder];
    [blit copyFromTexture:tex
                     sourceSlice:0
                     sourceLevel:0
                    sourceOrigin:MTLOriginMake(x, y, 0)
                      sourceSize:MTLSizeMake(w, h, 1)
                        toBuffer:buf
               destinationOffset:0
          destinationBytesPerRow:(NSUInteger)w * 2
        destinationBytesPerImage:(NSUInteger)w * h * 2];
    [blit endEncoding];
    [cb commit];
    [cb waitUntilCompleted];
    const uint16_t *gpu = (const uint16_t *)buf.contents;
    uint64_t bad = 0;
    int fx = -1, fy = -1;
    uint32_t fg = 0, fc = 0;
    for (int row = 0; row < h; ++row) {
        const uint32_t *line = (const uint32_t *)((const uint8_t *)cpu + (size_t)row * pitch);
        for (int col = 0; col < w; ++col) {
            const uint16_t p = gpu[(size_t)row * w + col];
            const int r5 = p & 31, g5 = (p >> 5) & 31, b5 = (p >> 10) & 31;
            const uint32_t argb = 0xFF000000u | (uint32_t)((r5 << 3) | (r5 >> 2)) << 16 |
                                  (uint32_t)((g5 << 3) | (g5 >> 2)) << 8 | (uint32_t)((b5 << 3) | (b5 >> 2));
            if (argb != line[col]) {
                if (!bad) { fx = col; fy = row; fg = argb; fc = line[col]; }
                ++bad;
            }
        }
    }
    s.verify_frames++;
    if (bad) { s.verify_bad_frames++; s.verify_bad_pixels += bad; }
    if (bad && s.verify_bad_frames <= 20)
        fprintf(stderr, "[metal] verify: frame %llu, %llu of %d pixels differ, first at %d,%d gpu %06x cpu %06x\n",
                (unsigned long long)s.verify_frames, (unsigned long long)bad, w * h, fx, fy, fg & 0xFFFFFF,
                fc & 0xFFFFFF);
    if (s.verify_frames % 60 == 0)
        fprintf(stderr, "[metal] verify: %llu frames, %llu differ (%llu pixels in all)\n",
                (unsigned long long)s.verify_frames, (unsigned long long)s.verify_bad_frames,
                (unsigned long long)s.verify_bad_pixels);
}

// ---- commit: replay what was recorded ----

void encode_target(id<MTLCommandBuffer> cb, Target &t) {
    State &s = st();
    if (t.prims.empty() || !t.tex)
        return;
    const size_t bytes = t.prims.size() * sizeof(Prim);
    id<MTLBuffer> prims = nil;
    for (auto &b : s.pool)
        if (b.serial <= s.completed.load() && b.buf.length >= bytes) {
            prims = b.buf;
            b.serial = s.serial;
            break;
        }
    if (!prims) {
        size_t size = 256 * 1024;
        while (size < bytes) size *= 2;
        prims = [s.device newBufferWithLength:size options:MTLResourceStorageModeShared];
        s.pool.push_back({prims, s.serial});
    }
    memcpy(prims.contents, t.prims.data(), bytes);
    (&t == &s.hires ? s.st_prims_hires : s.st_prims_wide) += t.prims.size();
    MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
    pass.colorAttachments[0].texture = t.tex;
    pass.colorAttachments[0].loadAction = MTLLoadActionLoad;
    pass.colorAttachments[0].storeAction = MTLStoreActionStore;
    id<MTLRenderCommandEncoder> enc = [cb renderCommandEncoderWithDescriptor:pass];
    [enc setRenderPipelineState:s.prim_pipe];
    const float size[2] = {(float)t.w, (float)t.h};
    [enc setVertexBuffer:prims offset:0 atIndex:0];
    [enc setVertexBytes:size length:sizeof size atIndex:1];
    [enc setFragmentBuffer:prims offset:0 atIndex:0];
    [enc setFragmentBuffer:s.pages offset:0 atIndex:1];
    [enc setFragmentBuffer:s.tables offset:0 atIndex:2];
    [enc drawPrimitives:MTLPrimitiveTypeTriangleStrip vertexStart:0 vertexCount:4 instanceCount:t.prims.size()];
    [enc endEncoding];
    t.prims.clear();
}

void commit() {
    State &s = st();
    if (!s.ready)
        return;
    bool any = !s.hires.prims.empty();
    for (auto &w : s.wide) any = any || !w.prims.empty();
    if (!any)
        return;
    const double t0 = now_s();
    dispatch_semaphore_wait(s.inflight, DISPATCH_TIME_FOREVER);
    id<MTLCommandBuffer> cb = [s.queue commandBuffer];
    encode_target(cb, s.hires);
    for (auto &w : s.wide) encode_target(cb, w);
    const uint64_t serial = s.serial++;
    dispatch_semaphore_t sem = s.inflight;
    [cb addCompletedHandler:^(id<MTLCommandBuffer> done_cb) {
      st().st_gpu_us += (uint64_t)std::max(0.0, (done_cb.GPUEndTime - done_cb.GPUStartTime) * 1e6);
      uint64_t done = st().completed.load();
      while (done < serial && !st().completed.compare_exchange_weak(done, serial)) {
      }
      dispatch_semaphore_signal(sem);
    }];
    [cb commit];
    s.st_commits++;
    s.st_cpu_commit += now_s() - t0;
}

const GpuRenderBackend kMetal = {
    .name = "metal (software native, GPU mirror)",
    .init = m_init,
    .set_scale = m_set_scale,
    .scale = m_scale,
    .set_texture_filter = m_set_texture_filter,
    .texture_filter = m_texture_filter,
    .set_semi_transparency = m_set_semi,
    .set_mask_bits = m_set_mask,
    .set_texture_window = m_set_tw,
    .set_color_modulation = m_set_mod,
    .set_precise_triangle = m_set_precise,
    .set_perspective_triangle = m_set_perspective,
    .fill_rect = m_fill_rect,
    .copy_rect = m_copy_rect,
    .draw_flat_triangle = m_flat_tri,
    .draw_gouraud_triangle = m_gouraud_tri,
    .draw_textured_triangle = m_tex_tri,
    .draw_shaded_textured_triangle = m_shaded_tex_tri,
    .draw_flat_rect = m_flat_rect,
    .draw_textured_rect = m_tex_rect,
    .draw_textured_rect_scaled = m_tex_rect_scaled,
    .draw_line = m_line,
    .draw_shaded_line = m_shaded_line,
    .render_display = m_render_display,
    .render_display_hires = m_render_display_hires,
    .vram_write = m_vram_write,
    .vram_read = m_vram_read,
    .vram_transfer_in = m_transfer_in,
    .vram_transfer_out = m_transfer_out,
    .set_draw_area = m_set_draw_area,
    .get_draw_area = m_get_draw_area,
    .set_draw_offset = m_set_draw_offset,
    .wide_configure = m_wide_configure,
    .wide_set_view = m_wide_set_view,
    .wide_set_target = m_wide_set_target,
    .wide_disable_target = m_wide_disable_target,
    .wide_clear = m_wide_clear,
    .wide_clear_margins = m_wide_clear_margins,
    .render_wide_display = m_render_wide_display,
    .wide_dump_full = m_wide_dump_full,
};

// ---- trace: every call into the backend, for replaying through the Mac test harness (tools/ios_metal_harness) ----
// HERC_TRACE=<file>. Record: int32 op, int32 argc, argc x int32, uint32 payload bytes, payload. The first record
// is native VRAM as it was; every primitive carries psx_ws_prim_in_backdrop() as its last argument.

FILE *g_trace;
void trace(int op, std::initializer_list<int32_t> args, const void *data = nullptr, uint32_t len = 0) {
    static bool started = false;
    if (!started) {
        started = true;
        const int32_t hdr[2] = {HT_VRAM, 0};
        const uint32_t n = kVramW * kVramH * 2;
        fwrite(hdr, 4, 2, g_trace);
        fwrite(&n, 4, 1, g_trace);
        fwrite(gpu_get_vram_ptr(), 1, n, g_trace);
    }
    const int32_t hdr[2] = {op, (int32_t)args.size()};
    fwrite(hdr, 4, 2, g_trace);
    fwrite(args.begin(), 4, args.size(), g_trace);
    fwrite(&len, 4, 1, g_trace);
    if (len)
        fwrite(data, 1, len, g_trace);
}
int32_t fbits(float f) { int32_t i; memcpy(&i, &f, 4); return i; }
int32_t bd() { return psx_ws_prim_in_backdrop(); }

void t_init(uint16_t *v) { m_init(v); }
void t_set_scale(int k) { trace(HT_SET_SCALE, {k}); m_set_scale(k); }
void t_set_filter(int b) { trace(HT_SET_FILTER, {b}); m_set_texture_filter(b); }
void t_set_semi(int e, int m) { trace(HT_SET_SEMI, {e, m}); m_set_semi(e, m); }
void t_set_mask(int a, int b) { trace(HT_SET_MASK, {a, b}); m_set_mask(a, b); }
void t_set_tw(uint32_t r) { trace(HT_SET_TW, {(int32_t)r}); m_set_tw(r); }
void t_set_mod(int r, int g, int b, int raw) { trace(HT_SET_MOD, {r, g, b, raw}); m_set_mod(r, g, b, raw); }
void t_set_precise(int e, int32_t a, int32_t b, int32_t c, int32_t d, int32_t f, int32_t g) {
    trace(HT_SET_PRECISE, {e, a, b, c, d, f, g}); m_set_precise(e, a, b, c, d, f, g);
}
void t_set_persp(int e, float a, float b, float c) {
    trace(HT_SET_PERSP, {e, fbits(a), fbits(b), fbits(c)}); m_set_perspective(e, a, b, c);
}
void t_fill(int x, int y, int w, int h, uint16_t c) { trace(HT_FILL, {x, y, w, h, c}); m_fill_rect(x, y, w, h, c); }
void t_copy(int a, int b, int c, int d, int w, int h) { trace(HT_COPY, {a, b, c, d, w, h}); m_copy_rect(a, b, c, d, w, h); }
void t_flat_tri(int a, int b, int c, int d, int e, int f, uint16_t col) {
    trace(HT_FLAT_TRI, {a, b, c, d, e, f, col, bd()}); m_flat_tri(a, b, c, d, e, f, col);
}
void t_gouraud(int a, int b, uint16_t c0, int c, int d, uint16_t c1, int e, int f, uint16_t c2) {
    trace(HT_GOURAUD, {a, b, c0, c, d, c1, e, f, c2, bd()}); m_gouraud_tri(a, b, c0, c, d, c1, e, f, c2);
}
void t_tex_tri(int a, int b, int c, int d, int e, int f, int g, int h, int i, int j, int k, int l, uint16_t cx,
               uint16_t cy, uint16_t tp) {
    trace(HT_TEX_TRI, {a, b, c, d, e, f, g, h, i, j, k, l, cx, cy, tp, bd()});
    m_tex_tri(a, b, c, d, e, f, g, h, i, j, k, l, cx, cy, tp);
}
void t_shaded_tex_tri(int a, int b, int c, int d, uint32_t c0, int e, int f, int g, int h, uint32_t c1, int i, int j,
                      int k, int l, uint32_t c2, uint16_t cx, uint16_t cy, uint16_t tp, int raw) {
    trace(HT_SHADED_TEX_TRI, {a, b, c, d, (int32_t)c0, e, f, g, h, (int32_t)c1, i, j, k, l, (int32_t)c2, cx, cy, tp,
                              raw, bd()});
    m_shaded_tex_tri(a, b, c, d, c0, e, f, g, h, c1, i, j, k, l, c2, cx, cy, tp, raw);
}
void t_flat_rect(int x, int y, int w, int h, uint16_t c) { trace(HT_FLAT_RECT, {x, y, w, h, c, bd()}); m_flat_rect(x, y, w, h, c); }
void t_tex_rect(int x, int y, int w, int h, int u, int v, uint16_t cx, uint16_t cy, uint16_t tp) {
    trace(HT_TEX_RECT, {x, y, w, h, u, v, cx, cy, tp, bd()}); m_tex_rect(x, y, w, h, u, v, cx, cy, tp);
}
void t_tex_rect_scaled(int x, int y, int w, int h, int a, int b, int c, int d, uint16_t cx, uint16_t cy,
                       uint16_t tp) {
    trace(HT_TEX_RECT_SCALED, {x, y, w, h, a, b, c, d, cx, cy, tp, bd()});
    m_tex_rect_scaled(x, y, w, h, a, b, c, d, cx, cy, tp);
}
void t_line(int a, int b, int c, int d, uint16_t col) { trace(HT_LINE, {a, b, c, d, col}); m_line(a, b, c, d, col); }
void t_shaded_line(int a, int b, uint16_t c0, int c, int d, uint16_t c1) {
    trace(HT_SHADED_LINE, {a, b, c0, c, d, c1}); m_shaded_line(a, b, c0, c, d, c1);
}
void t_vram_write(int x, int y, uint16_t p) { trace(HT_VRAM_WRITE, {x, y, p}); m_vram_write(x, y, p); }
void t_transfer_in(int x, int y, int w, int h, const uint16_t *d) {
    trace(HT_TRANSFER_IN, {x, y, w, h}, d, d && w > 0 && h > 0 ? (uint32_t)(w * h * 2) : 0);
    m_transfer_in(x, y, w, h, d);
}
void t_draw_area(int a, int b, int c, int d) { trace(HT_DRAW_AREA, {a, b, c, d}); m_set_draw_area(a, b, c, d); }
void t_draw_offset(int x, int y) { trace(HT_DRAW_OFFSET, {x, y}); m_set_draw_offset(x, y); }
int t_display_hires(uint32_t *o, int p, int a, int b, int c, int d) {
    trace(HT_DISPLAY_HIRES, {a, b, c, d}); return m_render_display_hires(o, p, a, b, c, d);
}
void t_wide_configure(int w, int o) { trace(HT_WIDE_CONFIGURE, {w, o}); m_wide_configure(w, o); }
void t_wide_view(int e, int s, int l, int r) { trace(HT_WIDE_VIEW, {e, s, l, r}); m_wide_set_view(e, s, l, r); }
void t_wide_target(int b) { trace(HT_WIDE_TARGET, {b}); m_wide_set_target(b); }
void t_wide_disable() { trace(HT_WIDE_DISABLE, {}); m_wide_disable_target(); }
void t_wide_clear(int b, int y, int h, uint16_t c) { trace(HT_WIDE_CLEAR, {b, y, h, c}); m_wide_clear(b, y, h, c); }
void t_wide_margins(int b, int y, int h, uint16_t c, int s) {
    trace(HT_WIDE_MARGINS, {b, y, h, c, s}); m_wide_clear_margins(b, y, h, c, s);
}
int t_display_wide(uint32_t *o, int p, int b, int y, int h) {
    trace(HT_DISPLAY_WIDE, {b, y, h}); return m_render_wide_display(o, p, b, y, h);
}

const GpuRenderBackend kTrace = [] {
    GpuRenderBackend b = kMetal;
    b.name = "metal (tracing)";
    b.init = t_init; b.set_scale = t_set_scale; b.set_texture_filter = t_set_filter;
    b.set_semi_transparency = t_set_semi; b.set_mask_bits = t_set_mask; b.set_texture_window = t_set_tw;
    b.set_color_modulation = t_set_mod; b.set_precise_triangle = t_set_precise;
    b.set_perspective_triangle = t_set_persp; b.fill_rect = t_fill; b.copy_rect = t_copy;
    b.draw_flat_triangle = t_flat_tri; b.draw_gouraud_triangle = t_gouraud; b.draw_textured_triangle = t_tex_tri;
    b.draw_shaded_textured_triangle = t_shaded_tex_tri; b.draw_flat_rect = t_flat_rect;
    b.draw_textured_rect = t_tex_rect; b.draw_textured_rect_scaled = t_tex_rect_scaled; b.draw_line = t_line;
    b.draw_shaded_line = t_shaded_line; b.render_display_hires = t_display_hires; b.vram_write = t_vram_write;
    b.vram_transfer_in = t_transfer_in; b.set_draw_area = t_draw_area; b.set_draw_offset = t_draw_offset;
    b.wide_configure = t_wide_configure; b.wide_set_view = t_wide_view; b.wide_set_target = t_wide_target;
    b.wide_disable_target = t_wide_disable; b.wide_clear = t_wide_clear; b.wide_clear_margins = t_wide_margins;
    b.render_wide_display = t_display_wide;
    return b;
}();

struct Register {
    Register() {
        NSString *pick = [NSUserDefaults.standardUserDefaults stringForKey:@"ios.renderer"];
        if ([pick isEqualToString:@"software"])
            return;
        if (const char *path = getenv("HERC_TRACE")) {
            g_trace = fopen(path, "wb");
            if (g_trace) {
                setvbuf(g_trace, nullptr, _IOFBF, 1 << 20);
                gr_register_host_software_backend(&kTrace);
                return;
            }
        }
        gr_register_host_software_backend(&kMetal);
    }
} g_register;

}  // namespace

// ---- shared Metal objects and the presenter's side ----

id<MTLDevice> herc_metal_device(void) {
    static id<MTLDevice> d = MTLCreateSystemDefaultDevice();
    return d;
}

id<MTLCommandQueue> herc_metal_queue(void) {
    static id<MTLCommandQueue> q = [herc_metal_device() newCommandQueue];
    return q;
}

int herc_metal_take_frame(HercMetalFrame *frame) {
    State &s = st();
    if (!s.frame_pending)
        return 0;
    s.frame_pending = false;
    *frame = s.frame;
    return 1;
}

void herc_metal_decode(id<MTLCommandBuffer> cb, const HercMetalFrame *frame, id<MTLTexture> out) {
    State &s = st();
    MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
    pass.colorAttachments[0].texture = out;
    pass.colorAttachments[0].loadAction = MTLLoadActionDontCare;
    pass.colorAttachments[0].storeAction = MTLStoreActionStore;
    id<MTLRenderCommandEncoder> enc = [cb renderCommandEncoderWithDescriptor:pass];
    [enc setRenderPipelineState:s.decode_pipe];
    [enc setFragmentTexture:(__bridge id<MTLTexture>)frame->texture atIndex:0];
    const int rect[4] = {frame->x, frame->y, frame->w, frame->h};
    [enc setFragmentBytes:rect length:sizeof rect atIndex:0];
    [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
    [enc endEncoding];
}

int herc_metal_active(void) { return st().ready && st().scale > 1 ? 1 : 0; }

const GpuRenderBackend *herc_metal_backend(void) { return &kMetal; }

void herc_metal_finish(void) {
    if (g_trace) fflush(g_trace);
    commit();
    id<MTLCommandBuffer> cb = [st().queue commandBuffer];
    [cb commit];
    [cb waitUntilCompleted];
    stats_tick(true);
}
