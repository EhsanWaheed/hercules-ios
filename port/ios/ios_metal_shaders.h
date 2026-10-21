// ios_metal_shaders.h - the Metal renderer's shaders (ios_metal_renderer.mm), as source compiled at start.
//
// Each primitive is one instanced quad over its bounding box; the fragment shader repeats, per pixel, what the
// software renderer's scaled pass computes (gpu_sw_renderer.c raster_*): the PS1 edge DDA (gpu_sw_edges.h), the
// float interpolation in the same order, texel_fetch / texel_fetch_bilinear, modulation, the four semi-transparency
// modes and the mask bit, reading the destination pixel itself (framebuffer fetch). Textures come from a snapshot
// of native VRAM as it was when the primitive was drawn.
#pragma once

static const char *kHercMetalShaders = R"MSL(
#include <metal_stdlib>
using namespace metal;

struct Prim {
    int kind, flags, snap, s;
    int cx1, cy1, cx2, cy2;
    int bx0, by0, bx1, by1;
    int x[3], y[3];
    int u[3], v[3];
    int r[3], g[3], b[3];
    float q[3];
    int texpage, clut_x, clut_y, color;
    int tw_mask_x, tw_mask_y, tw_off_x, tw_off_y;
    int mod_r, mod_g, mod_b, pad0;
    int lim[4];
};

enum { K_FLAT_TRI, K_GOURAUD_TRI, K_TEX_TRI, K_SHADED_TEX_TRI, K_FLAT_RECT, K_TEX_RECT, K_TEX_RECT_SCALED,
       K_BLOCK, K_FILL, K_UPLOAD };
enum { F_SEMI = 1, F_MASK_SET = 8, F_MASK_CHECK = 16, F_RAW = 32, F_PERSPECTIVE = 64, F_FILTER = 128 };

struct VO { float4 pos [[position]]; uint id [[flat]]; };

vertex VO prim_vs(uint vid [[vertex_id]], uint iid [[instance_id]], const device Prim *prims [[buffer(0)]],
                  constant float2 &size [[buffer(1)]]) {
    const device Prim &p = prims[iid];
    float x = (vid & 1) ? float(p.bx1) : float(p.bx0);
    float y = (vid & 2) ? float(p.by1) : float(p.by0);
    VO o;
    o.pos = float4(x / size.x * 2.0 - 1.0, 1.0 - y / size.y * 2.0, 0.0, 1.0);
    o.id = iid;
    return o;
}

struct FO { ushort c [[color(0)]]; };

// ---- gpu_sw_edges.h ----
static long edge_fp(int x) { return (long(x) << 32) + ((1L << 32) - (1 << 11)); }
static long edge_step(int dx, int dy) {
    long rounding = dx < 0 ? -long(dy - 1) : (dx > 0 ? long(dy - 1) : 0L);
    return ((long(dx) << 32) + rounding) / long(dy);
}
static int edge_unfp(long fp) { return int(ulong(fp) >> 32); }
static void edges_at_y(int x0, int y0, int x1, int y1, int x2, int y2, int y, thread int &lx, thread int &sx) {
    long long_step = edge_step(x2 - x0, y2 - y0);
    lx = edge_unfp(edge_fp(x0) + long_step * long(y - y0));
    if (y < y1) {
        long short_step = edge_step(x1 - x0, y1 - y0);
        sx = edge_unfp(edge_fp(x0) + short_step * long(y - y0));
    } else {
        long short_step = edge_step(x2 - x1, y2 - y1);
        sx = edge_unfp(edge_fp(x1) + short_step * long(y - y1));
    }
}

static float fdiv(float a, float b) { return precise::divide(a, b); }

// ---- texels (native VRAM snapshot) ----
static ushort vram_get(const device ushort *vram, int snap, int x, int y) {
    return vram[uint(snap) * 524288u + uint(y & 511) * 1024u + uint(x & 1023)];
}

static ushort texel_fetch(const device Prim &p, const device ushort *vram, int u, int v) {
    if ((p.tw_mask_x | p.tw_mask_y) != 0) {
        u = (u & ~(p.tw_mask_x * 8)) | ((p.tw_off_x & p.tw_mask_x) * 8);
        v = (v & ~(p.tw_mask_y * 8)) | ((p.tw_off_y & p.tw_mask_y) * 8);
    }
    int tpx = (p.texpage & 0xF) * 64;
    int tpy = ((p.texpage >> 4) & 1) * 256;
    int depth = (p.texpage >> 7) & 3;
    if (depth == 0) {
        ushort w = vram_get(vram, p.snap, tpx + u / 4, tpy + v);
        int index = (w >> ((u & 3) * 4)) & 0xF;
        return vram_get(vram, p.snap, p.clut_x + index, p.clut_y);
    }
    if (depth == 1) {
        ushort w = vram_get(vram, p.snap, tpx + u / 2, tpy + v);
        int index = (w >> ((u & 1) * 8)) & 0xFF;
        return vram_get(vram, p.snap, p.clut_x + index, p.clut_y);
    }
    return vram_get(vram, p.snap, tpx + u, tpy + v);
}

static ushort bl_fetch(const device Prim &p, const device ushort *vram, int u, int v) {
    u &= 0xFF; v &= 0xFF;
    if ((p.tw_mask_x | p.tw_mask_y) == 0) {
        if (u < p.lim[0]) u = p.lim[0]; else if (u > p.lim[2]) u = p.lim[2];
        if (v < p.lim[1]) v = p.lim[1]; else if (v > p.lim[3]) v = p.lim[3];
    }
    return texel_fetch(p, vram, u, v);
}

static ushort texel_fetch_bilinear(const device Prim &p, const device ushort *vram, float fu, float fv) {
    int iu = int(floor(fu)), iv = int(floor(fv));
    int fx = int((fu - float(iu)) * 256.0f) - 128;
    int fy = int((fv - float(iv)) * 256.0f) - 128;
    int su = fx < 0 ? -1 : 1, sv = fy < 0 ? -1 : 1;
    if (fx < 0) fx = -fx;
    if (fy < 0) fy = -fy;
    if (fx > 128) fx = 128;
    if (fy > 128) fy = 128;
    ushort c00 = bl_fetch(p, vram, iu, iv);
    if (c00 == 0) return 0;
    ushort c10 = bl_fetch(p, vram, iu + su, iv);
    ushort c01 = bl_fetch(p, vram, iu, iv + sv);
    ushort c11 = bl_fetch(p, vram, iu + su, iv + sv);
    int w00 = (c00 ? 1 : 0) * (256 - fx) * (256 - fy);
    int w10 = (c10 ? 1 : 0) * fx * (256 - fy);
    int w01 = (c01 ? 1 : 0) * (256 - fx) * fy;
    int w11 = (c11 ? 1 : 0) * fx * fy;
    int opac = w00 + w10 + w01 + w11;
    int r = (int(c00 & 0x1F) * w00 + int(c10 & 0x1F) * w10 + int(c01 & 0x1F) * w01 + int(c11 & 0x1F) * w11) / opac;
    int g = (int((c00 >> 5) & 0x1F) * w00 + int((c10 >> 5) & 0x1F) * w10 + int((c01 >> 5) & 0x1F) * w01 +
             int((c11 >> 5) & 0x1F) * w11) / opac;
    int b = (int((c00 >> 10) & 0x1F) * w00 + int((c10 >> 10) & 0x1F) * w10 + int((c01 >> 10) & 0x1F) * w01 +
             int((c11 >> 10) & 0x1F) * w11) / opac;
    bool stp = (int((c00 >> 15) & 1) * w00 + int((c10 >> 15) & 1) * w10 + int((c01 >> 15) & 1) * w01 +
                int((c11 >> 15) & 1) * w11) * 2 >= opac;
    return ushort(r | (g << 5) | (b << 10) | (stp ? 0x8000 : 0));
}

static float bilinear_shift(int s) { return 0.5f / float(s > 0 ? s : 1) - 1.0f / 64.0f; }

static ushort tex(const device Prim &p, const device ushort *vram, float fu, float fv) {
    if (p.flags & F_FILTER) {
        float sh = bilinear_shift(p.s);
        return texel_fetch_bilinear(p, vram, fu + sh, fv + sh);
    }
    return texel_fetch(p, vram, int(fu) & 0xFF, int(fv) & 0xFF);
}

// ---- writes ----
static ushort blend(ushort back, ushort front, int mode) {
    int br = back & 0x1F, bg = (back >> 5) & 0x1F, bb = (back >> 10) & 0x1F;
    int fr = front & 0x1F, fg = (front >> 5) & 0x1F, fb = (front >> 10) & 0x1F;
    int r, g, b;
    if (mode == 0) { r = (br + fr) >> 1; g = (bg + fg) >> 1; b = (bb + fb) >> 1; }
    else if (mode == 1) { r = min(br + fr, 31); g = min(bg + fg, 31); b = min(bb + fb, 31); }
    else if (mode == 2) { r = max(br - fr, 0); g = max(bg - fg, 0); b = max(bb - fb, 0); }
    else { r = min(br + (fr >> 2), 31); g = min(bg + (fg >> 2), 31); b = min(bb + (fb >> 2), 31); }
    return ushort(r | (g << 5) | (b << 10));
}

static FO put_opaque(const device Prim &p, ushort dst, ushort color) {
    if ((p.flags & F_MASK_CHECK) && (dst & 0x8000)) discard_fragment();
    if (p.flags & F_SEMI) color = blend(dst, color, (p.flags >> 1) & 3);
    if (p.flags & F_MASK_SET) color |= 0x8000;
    FO o; o.c = color; return o;
}

static FO put_textured(const device Prim &p, ushort dst, ushort texel, int mr, int mg, int mb) {
    if (texel == 0) discard_fragment();
    if ((p.flags & F_MASK_CHECK) && (dst & 0x8000)) discard_fragment();
    ushort color;
    if (!(p.flags & F_RAW)) {
        int r = min((int(texel & 0x1F) * mr) >> 4, 31);
        int g = min((int((texel >> 5) & 0x1F) * mg) >> 4, 31);
        int b = min((int((texel >> 10) & 0x1F) * mb) >> 4, 31);
        color = ushort(r | (g << 5) | (b << 10));
    } else {
        color = texel & 0x7FFF;
    }
    if ((p.flags & F_SEMI) && (texel & 0x8000)) color = blend(dst, color, (p.flags >> 1) & 3);
    if (p.flags & F_MASK_SET) color |= 0x8000;
    FO o; o.c = color; return o;
}

static bool in_clip(const device Prim &p, int x, int y) {
    return x >= p.cx1 && x <= p.cx2 && y >= p.cy1 && y <= p.cy2;
}

fragment FO prim_fs(VO in [[stage_in]], ushort dst [[color(0)]], const device Prim *prims [[buffer(0)]],
                    const device ushort *vram [[buffer(1)]]) {
    const device Prim &p = prims[in.id];
    const int px = int(in.pos.x), py = int(in.pos.y);

    if (p.kind == K_FILL) { FO o; o.c = ushort(p.color); return o; }
    if (p.kind == K_UPLOAD) {
        FO o; o.c = vram_get(vram, p.snap, px / p.s, py / p.s); return o;
    }

    if (p.kind <= K_SHADED_TEX_TRI) {
        const int x0 = p.x[0], y0 = p.y[0], x1 = p.x[1], y1 = p.y[1], x2 = p.x[2], y2 = p.y[2];
        if (py < y0 || py >= y2 || py < p.cy1 || py > p.cy2) discard_fragment();
        const int dy_total = y2 - y0;
        int xa, xb;
        edges_at_y(x0, y0, x1, y1, x2, y2, py, xa, xb);
        if (p.kind == K_FLAT_TRI) {
            if (xa > xb) { int t = xa; xa = xb; xb = t; }
            if (px < max(xa, p.cx1) || px >= min(xb, p.cx2 + 1)) discard_fragment();
            return put_opaque(p, dst, ushort(p.color));
        }
        const bool second_half = py >= y1;
        int seg_height = second_half ? (y2 - y1) : (y1 - y0);
        if (seg_height == 0) seg_height = 1;
        const float alpha = fdiv(float(py - y0), float(dy_total));
        const float beta = second_half ? fdiv(float(py - y1), float(seg_height)) : fdiv(float(py - y0), float(seg_height));
        const int a0 = 0, a1 = second_half ? 1 : 0, a2 = second_half ? 2 : 1;  // edge b runs a1 -> a2

        if (p.kind == K_GOURAUD_TRI) {
            int ra = p.r[0] + int(float(p.r[2] - p.r[0]) * alpha);
            int ga = p.g[0] + int(float(p.g[2] - p.g[0]) * alpha);
            int ba = p.b[0] + int(float(p.b[2] - p.b[0]) * alpha);
            int rb = p.r[a1] + int(float(p.r[a2] - p.r[a1]) * beta);
            int gb = p.g[a1] + int(float(p.g[a2] - p.g[a1]) * beta);
            int bb = p.b[a1] + int(float(p.b[a2] - p.b[a1]) * beta);
            if (xa > xb) {
                int t;
                t = xa; xa = xb; xb = t; t = ra; ra = rb; rb = t; t = ga; ga = gb; gb = t; t = ba; ba = bb; bb = t;
            }
            if (px < max(xa, p.cx1) || px >= min(xb, p.cx2 + 1)) discard_fragment();
            const int span = xb - xa;
            ushort color;
            if (span > 0) {
                const float tf = fdiv(float(px - xa), float(span));
                int r = clamp(ra + int(float(rb - ra) * tf), 0, 31);
                int g = clamp(ga + int(float(gb - ga) * tf), 0, 31);
                int b = clamp(ba + int(float(bb - ba) * tf), 0, 31);
                color = ushort(r | (g << 5) | (b << 10));
            } else {
                color = ushort(ra | (ga << 5) | (ba << 10));
            }
            return put_opaque(p, dst, color);
        }

        // textured (flat modulation) or shaded textured
        const float u0 = float(p.u[0]), v0 = float(p.v[0]);
        float ua = float(p.u[0]) + float(p.u[2] - p.u[0]) * alpha;
        float va = float(p.v[0]) + float(p.v[2] - p.v[0]) * alpha;
        float qa = p.q[0] + (p.q[2] - p.q[0]) * alpha;
        float uqa = u0 * p.q[0] + (float(p.u[2]) * p.q[2] - u0 * p.q[0]) * alpha;
        float vqa = v0 * p.q[0] + (float(p.v[2]) * p.q[2] - v0 * p.q[0]) * alpha;
        float ub = float(p.u[a1]) + float(p.u[a2] - p.u[a1]) * beta;
        float vb = float(p.v[a1]) + float(p.v[a2] - p.v[a1]) * beta;
        float qb = p.q[a1] + (p.q[a2] - p.q[a1]) * beta;
        float uqb = float(p.u[a1]) * p.q[a1] + (float(p.u[a2]) * p.q[a2] - float(p.u[a1]) * p.q[a1]) * beta;
        float vqb = float(p.v[a1]) * p.q[a1] + (float(p.v[a2]) * p.q[a2] - float(p.v[a1]) * p.q[a1]) * beta;
        float ra = 0, ga = 0, ba = 0, rb = 0, gb = 0, bb = 0;
        if (p.kind == K_SHADED_TEX_TRI) {
            ra = float(p.r[0]) + float(p.r[2] - p.r[0]) * alpha;
            ga = float(p.g[0]) + float(p.g[2] - p.g[0]) * alpha;
            ba = float(p.b[0]) + float(p.b[2] - p.b[0]) * alpha;
            rb = float(p.r[a1]) + float(p.r[a2] - p.r[a1]) * beta;
            gb = float(p.g[a1]) + float(p.g[a2] - p.g[a1]) * beta;
            bb = float(p.b[a1]) + float(p.b[a2] - p.b[a1]) * beta;
        }
        (void)a0;
        if (xa > xb) {
            int t = xa; xa = xb; xb = t;
            float f;
            f = ua; ua = ub; ub = f; f = va; va = vb; vb = f; f = qa; qa = qb; qb = f;
            f = uqa; uqa = uqb; uqb = f; f = vqa; vqa = vqb; vqb = f;
            f = ra; ra = rb; rb = f; f = ga; ga = gb; gb = f; f = ba; ba = bb; bb = f;
        }
        if (px < max(xa, p.cx1) || px >= min(xb, p.cx2 + 1)) discard_fragment();
        int span = xb - xa;
        if (span == 0) span = 1;
        const float t_val = fdiv(float(px - xa), float(span));
        float fu = ua + (ub - ua) * t_val;
        float fv = va + (vb - va) * t_val;
        if (p.flags & F_PERSPECTIVE) {
            float q = qa + (qb - qa) * t_val;
            if (q > 1.0e-12f) {
                fu = fdiv(uqa + (uqb - uqa) * t_val, q);
                fv = fdiv(vqa + (vqb - vqa) * t_val, q);
            }
        }
        const ushort texel = tex(p, vram, fu, fv);
        if (p.kind == K_SHADED_TEX_TRI) {
            int mr = clamp(int(ra + (rb - ra) * t_val), 0, 31);
            int mg = clamp(int(ga + (gb - ga) * t_val), 0, 31);
            int mb = clamp(int(ba + (bb - ba) * t_val), 0, 31);
            return put_textured(p, dst, texel, mr, mg, mb);
        }
        return put_textured(p, dst, texel, p.mod_r, p.mod_g, p.mod_b);
    }

    // rectangles: x[0],y[0] origin, x[1],y[1] size
    if (!in_clip(p, px, py)) discard_fragment();
    const int rx = p.x[0], ry = p.y[0], rw = p.x[1], rh = p.y[1];
    if (px < rx || px >= rx + rw || py < ry || py >= ry + rh) discard_fragment();
    const int row = py - ry, col = px - rx;
    if (p.kind == K_FLAT_RECT || p.kind == K_BLOCK) return put_opaque(p, dst, ushort(p.color));
    if (p.kind == K_TEX_RECT) {
        const int s = p.s;
        ushort texel;
        if (p.flags & F_FILTER) {
            float fv = float(p.v[0]) + fdiv(float(row), float(s));
            float fu = float(p.u[0]) + fdiv(float(col), float(s));
            float sh = bilinear_shift(s);
            texel = texel_fetch_bilinear(p, vram, fu + sh, fv + sh);
        } else {
            texel = texel_fetch(p, vram, (p.u[0] + col / s) & 0xFF, (p.v[0] + row / s) & 0xFF);
        }
        return put_textured(p, dst, texel, p.mod_r, p.mod_g, p.mod_b);
    }
    // K_TEX_RECT_SCALED: u[0],v[0] -> u[1],v[1] across the rect
    const int du = p.u[1] - p.u[0], dv = p.v[1] - p.v[0];
    ushort texel;
    if (p.flags & F_FILTER) {
        float fv = float(p.v[0]) + fdiv(float(dv) * float(row), float(rh));
        float fu = float(p.u[0]) + fdiv(float(du) * float(col), float(rw));
        float sh = bilinear_shift(p.s);
        texel = texel_fetch_bilinear(p, vram, fu + sh, fv + sh);
    } else {
        int tv = int(long(p.v[0]) + (long(dv) * long(row)) / long(rh)) & 0xFF;
        int tu = int(long(p.u[0]) + (long(du) * long(col)) / long(rw)) & 0xFF;
        texel = texel_fetch(p, vram, tu, tv);
    }
    return put_textured(p, dst, texel, p.mod_r, p.mod_g, p.mod_b);
}

// ---- display: a 15-bit region to BGRA (rgb555_to_argb) ----
struct DO { float4 pos [[position]]; float2 uv; };
vertex DO decode_vs(uint vid [[vertex_id]]) {
    float2 p = float2((vid << 1) & 2, vid & 2);
    DO o; o.pos = float4(p * 2.0 - 1.0, 0.0, 1.0); o.uv = float2(p.x, 1.0 - p.y);
    return o;
}
fragment float4 decode_fs(DO in [[stage_in]], texture2d<ushort, access::read> src [[texture(0)]],
                          constant int4 &rect [[buffer(0)]]) {
    uint2 at = uint2(int2(in.pos.xy) + rect.xy);
    at.x = min(at.x, src.get_width() - 1);
    at.y = min(at.y, src.get_height() - 1);
    ushort pix = src.read(at).r;
    int r5 = pix & 0x1F, g5 = (pix >> 5) & 0x1F, b5 = (pix >> 10) & 0x1F;
    return float4(float((r5 << 3) | (r5 >> 2)), float((g5 << 3) | (g5 >> 2)), float((b5 << 3) | (b5 >> 2)), 255.0) / 255.0;
}
)MSL";
