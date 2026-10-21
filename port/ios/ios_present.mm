// ios_present.mm - the iOS presenter for the software renderer's frames
// (psx_host_present_register): the PS1 picture is uploaded to a Metal
// texture, upscaled with MetalFX (spatial) to the size it is shown at, and
// drawn letterboxed into the CAMetalLayer SDL made for the window.
//
// Upscalers (ios.upscaler, the settings panel):
//   0 MetalFX spatial  - edge-aware upscale to ios.fxRows (720/900/1080p, 0 the size shown)
//   1 Sharp bilinear   - integer prescale then linear: square pixels, no shimmer
//   2 Nearest          - raw pixels
// A device without MetalFX (the Simulator, older GPUs) uses sharp bilinear.
//
// Screen (ios.screenFit): Fit (the game's aspect, bars), Fill (no bars, the overhang cropped; with the game's own
// 16:9 widescreen that is a sliver on a phone and nothing on a 16:9 screen) or Stretch.
#include "ios_present.h"
#include "ios_overlay.h"
#include "ios_metal_renderer.h"
#include "psx_game_launcher.h"

#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#if HERC_HAVE_METALFX
#import <MetalFX/MetalFX.h>
#endif
#import <QuartzCore/CAMetalLayer.h>
#import <UIKit/UIKit.h>

#include <SDL3/SDL.h>

#include <algorithm>
#include <cmath>
#include <cstdio>

namespace {

const char *kShaders = R"(
#include <metal_stdlib>
using namespace metal;
struct V { float4 pos [[position]]; float2 uv; };
// uvr: the part of the picture the viewport shows (offset xy, size zw); Fill crops with it.
vertex V vs(uint vid [[vertex_id]], constant float4 &uvr [[buffer(0)]]) {
    float2 p = float2((vid << 1) & 2, vid & 2);
    V o; o.pos = float4(p * 2.0 - 1.0, 0.0, 1.0); o.uv = uvr.xy + float2(p.x, 1.0 - p.y) * uvr.zw;
    return o;
}
fragment float4 fs_plain(V in [[stage_in]], texture2d<float> t [[texture(0)]], sampler s [[sampler(0)]]) {
    return float4(t.sample(s, in.uv).rgb, 1.0);
}
// Sharp bilinear: each source texel is a flat square of `scale` output pixels
// with a one-pixel linear blend at its edges.
fragment float4 fs_sharp(V in [[stage_in]], texture2d<float> t [[texture(0)]], sampler s [[sampler(0)]],
                         constant float2 &scale [[buffer(0)]]) {
    float2 size = float2(t.get_width(), t.get_height());
    float2 texel = in.uv * size;
    float2 region = 0.5 - 0.5 / scale;
    float2 d = fract(texel) - 0.5;
    float2 f = (d - clamp(d, -region, region)) * scale + 0.5;
    return float4(t.sample(s, (floor(texel) + f) / size).rgb, 1.0);
}
)";

struct Presenter {
    id<MTLDevice> device;
    id<MTLCommandQueue> queue;
    CAMetalLayer *layer;
    id<MTLRenderPipelineState> plain, sharp;
    id<MTLSamplerState> linear, nearest;
    id<MTLTexture> input;       // the PS1 frame
    id<MTLTexture> upscaled;    // MetalFX output
    id<MTLTexture> decoded;     // the Metal renderer's frame as BGRA
#if HERC_HAVE_METALFX
    id<MTLFXSpatialScaler> fx;
#endif
    bool fx_supported = false;
    double last_exit = 0, game_s = 0, present_s = 0, wait_s = 0;  // timing, logged every 5 s
    int log_frames = 0;
    double fps = 0;  // frames presented per second, over the last second
    bool failed = false;
};

Presenter g;

int setting_int(NSString *key, int fallback) {
    id v = [NSUserDefaults.standardUserDefaults objectForKey:key];
    return v ? (int)[v integerValue] : fallback;
}

CAMetalLayer *find_layer() {
    int count = 0;
    SDL_Window **windows = SDL_GetWindows(&count);
    CAMetalLayer *found = nil;
    for (int i = 0; windows && i < count && !found; ++i) {
        SDL_Renderer *r = SDL_GetRenderer(windows[i]);
        if (r)
            found = (__bridge CAMetalLayer *)SDL_GetRenderMetalLayer(r);
    }
    SDL_free(windows);
    return found;
}

bool init() {
    if (g.layer)
        return true;
    if (g.failed)
        return false;
    g.layer = find_layer();
    if (!g.layer) {
        g.failed = true;
        std::fprintf(stderr, "hercules-ios: no Metal layer from SDL, presenting through SDL\n");
        return false;
    }
    // The Metal renderer's device and queue: its frames are drawn before this presents them, in queue order.
    g.device = herc_metal_device();
    g.layer.device = g.device;
    g.layer.pixelFormat = MTLPixelFormatBGRA8Unorm;
    g.queue = herc_metal_queue();
    NSError *err = nil;
    id<MTLLibrary> lib = [g.device newLibraryWithSource:@(kShaders) options:nil error:&err];
    if (!lib) {
        std::fprintf(stderr, "hercules-ios: presenter shaders: %s\n", err.localizedDescription.UTF8String);
        g.failed = true;
        g.layer = nil;
        return false;
    }
    MTLRenderPipelineDescriptor *d = [MTLRenderPipelineDescriptor new];
    d.vertexFunction = [lib newFunctionWithName:@"vs"];
    d.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm;
    d.fragmentFunction = [lib newFunctionWithName:@"fs_plain"];
    g.plain = [g.device newRenderPipelineStateWithDescriptor:d error:&err];
    d.fragmentFunction = [lib newFunctionWithName:@"fs_sharp"];
    g.sharp = [g.device newRenderPipelineStateWithDescriptor:d error:&err];
    MTLSamplerDescriptor *s = [MTLSamplerDescriptor new];
    s.sAddressMode = s.tAddressMode = MTLSamplerAddressModeClampToEdge;
    s.minFilter = s.magFilter = MTLSamplerMinMagFilterLinear;
    g.linear = [g.device newSamplerStateWithDescriptor:s];
    s.minFilter = s.magFilter = MTLSamplerMinMagFilterNearest;
    g.nearest = [g.device newSamplerStateWithDescriptor:s];
#if HERC_HAVE_METALFX
    g.fx_supported = [MTLFXSpatialScalerDescriptor supportsDevice:g.device];
#endif
    NSLog(@"[present] layer %.0fx%.0f pt at %.1fx (screen %.1fx)", g.layer.bounds.size.width,
          g.layer.bounds.size.height, g.layer.contentsScale, UIScreen.mainScreen.nativeScale);
    std::fprintf(stderr, "hercules-ios: Metal presenter on %s, MetalFX spatial %s\n", g.device.name.UTF8String,
                 g.fx_supported ? "available" : "not available");
    return g.plain && g.sharp;
}

// The PS1 frame as a texture (BGRA: 0xAARRGGBB in little-endian memory).
id<MTLTexture> upload(const uint32_t *argb, int w, int h, int stride) {
    if (!g.input || (int)g.input.width != w || (int)g.input.height != h) {
        MTLTextureDescriptor *t = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm
                                                                                     width:w
                                                                                    height:h
                                                                                 mipmapped:NO];
        t.usage = MTLTextureUsageShaderRead;
        t.storageMode = MTLStorageModeShared;
        g.input = [g.device newTextureWithDescriptor:t];
    }
    [g.input replaceRegion:MTLRegionMake2D(0, 0, w, h) mipmapLevel:0 withBytes:argb bytesPerRow:(NSUInteger)stride * 4];
    return g.input;
}

// MetalFX from the frame to (ow, oh); nil when it cannot.
#if HERC_HAVE_METALFX
id<MTLTexture> metalfx(id<MTLCommandBuffer> cb, id<MTLTexture> in, int ow, int oh) {
    if (!g.fx || (int)g.fx.inputWidth != (int)in.width || (int)g.fx.inputHeight != (int)in.height ||
        (int)g.fx.outputWidth != ow || (int)g.fx.outputHeight != oh) {
        MTLFXSpatialScalerDescriptor *d = [MTLFXSpatialScalerDescriptor new];
        d.inputWidth = in.width;
        d.inputHeight = in.height;
        d.outputWidth = ow;
        d.outputHeight = oh;
        d.colorTextureFormat = MTLPixelFormatBGRA8Unorm;
        d.outputTextureFormat = MTLPixelFormatBGRA8Unorm;
        d.colorProcessingMode = MTLFXSpatialScalerColorProcessingModePerceptual;
        g.fx = [d newSpatialScalerWithDevice:g.device];
        if (!g.fx)
            return nil;
        MTLTextureDescriptor *t = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm
                                                                                     width:ow
                                                                                    height:oh
                                                                                 mipmapped:NO];
        t.usage = g.fx.outputTextureUsage | MTLTextureUsageShaderRead;
        t.storageMode = MTLStorageModePrivate;
        g.upscaled = [g.device newTextureWithDescriptor:t];
    }
    g.fx.colorTexture = in;
    g.fx.outputTexture = g.upscaled;
    g.fx.inputContentWidth = in.width;
    g.fx.inputContentHeight = in.height;
    [g.fx encodeToCommandBuffer:cb];
    return g.upscaled;
}
#else
id<MTLTexture> metalfx(id<MTLCommandBuffer>, id<MTLTexture>, int, int) { return nil; }
#endif

int present(const uint32_t *argb, int w, int h, int stride, float aspect, int depth24) {
    if (w <= 0 || h <= 0 || !init())
        return 0;
    herc_overlay_frame();  // the settings panel: installed on the first frame, and holds the game while open
    const double entered = CACurrentMediaTime();
    {
        // The presented rate, and where a frame's time goes, in the log every 5 s: "game" is the CPU between two
        // presents (the recompiled game and the native picture), "present" this presenter, "wait" its drawable wait.
        static double since = entered, logged = entered;
        static int frames = 0;
        ++frames;
        if (g.last_exit > 0) g.game_s += entered - g.last_exit;
        if (entered - since >= 1.0) {
            g.fps = frames / (entered - since);
            since = entered;
            frames = 0;
        }
        if (entered - logged >= 5.0) {
            const double n = std::max(1, g.log_frames);
            const char *thermal[] = {"nominal", "fair", "serious", "critical"};
            fprintf(stderr, "[present] %.1f fps, %dx%d | per frame: game %.2f ms, present %.2f ms (wait %.2f ms) | thermal %s\n",
                    g.fps, w, h, g.game_s * 1000 / n, g.present_s * 1000 / n, g.wait_s * 1000 / n,
                    thermal[std::clamp<NSInteger>(NSProcessInfo.processInfo.thermalState, 0, 3)]);
            g.game_s = g.present_s = g.wait_s = 0;
            g.log_frames = 0;
            logged = entered;
        }
        g.log_frames++;
    }
    @autoreleasepool {
        // The layer at the screen's own pixels: SDL makes it at 1x (points) unless the window asks for high pixel
        // density, which left every frame (and the Metal HUD drawn into it) at a third of the resolution, stretched
        // up by Core Animation, and capped MetalFX's output at 440 lines on a phone.
        // The game's view fills its window, whatever a trip to the Home Screen did: under LiveContainer the window
        // rotates back from portrait on return, and the SDL view kept a stale frame (the picture sat off to the
        // left). Any change of the geometry is logged.
        UIView *view = (UIView *)g.layer.delegate;
        UIWindow *window = view.window;
        if (window && view.superview && !CGRectEqualToRect(view.frame, view.superview.bounds))
            view.frame = view.superview.bounds;
        {
            static CGRect last[3];
            const CGRect now[3] = {window.frame, view.frame, g.layer.frame};
            if (!CGRectEqualToRect(now[0], last[0]) || !CGRectEqualToRect(now[1], last[1]) ||
                !CGRectEqualToRect(now[2], last[2])) {
                int ww = 0, wh = 0;
                int count = 0;
                SDL_Window **ws = SDL_GetWindows(&count);
                if (ws && count > 0)
                    SDL_GetWindowSize(ws[0], &ww, &wh);
                SDL_free(ws);
                fprintf(stderr, "[present] geometry: window %s, view %s, layer %s, SDL window %dx%d\n",
                        NSStringFromCGRect(now[0]).UTF8String, NSStringFromCGRect(now[1]).UTF8String,
                        NSStringFromCGRect(now[2]).UTF8String, ww, wh);
                for (int i = 0; i < 3; ++i)
                    last[i] = now[i];
            }
        }
        const CGFloat native = UIScreen.mainScreen.nativeScale;
        const CGSize want = CGSizeMake(std::round(g.layer.bounds.size.width * native),
                                       std::round(g.layer.bounds.size.height * native));
        if (g.layer.contentsScale != native || !CGSizeEqualToSize(g.layer.drawableSize, want)) {
            g.layer.contentsScale = native;
            g.layer.drawableSize = want;
            NSLog(@"[present] drawable %.0fx%.0f at %.1fx", want.width, want.height, native);
        }
        const CGSize ds = g.layer.drawableSize;
        if (ds.width < 1 || ds.height < 1)
            return 1;
        // The picture's size on screen (sw x sh) and the part of it the viewport shows (uvr).
        //   Fit:     the display aspect, as large as fits (bars at the sides or top and bottom)
        //   Fill:    the display aspect, as small as covers the screen (the overhang is cropped)
        //   Stretch: the screen's own shape
        const int fit = herc_present_screen_fit();
        double sw = ds.width, sh = ds.width / aspect;
        if (fit == HERC_FIT_STRETCH) {
            sh = ds.height;
        } else if ((sh > ds.height) == (fit == HERC_FIT_FIT)) {
            sh = ds.height;
            sw = ds.height * aspect;
        }
        float uvr[4] = {0, 0, 1, 1};
        MTLViewport vp = {std::floor((ds.width - sw) / 2), std::floor((ds.height - sh) / 2), std::floor(sw),
                          std::floor(sh), 0, 1};
        if (fit == HERC_FIT_FILL) {
            uvr[2] = (float)(ds.width / sw);
            uvr[3] = (float)(ds.height / sh);
            uvr[0] = (1.0f - uvr[2]) / 2;
            uvr[1] = (1.0f - uvr[3]) / 2;
            vp = {0, 0, ds.width, ds.height, 0, 1};
        }

        id<MTLCommandBuffer> cb = [g.queue commandBuffer];
        // The Metal renderer's frame stays on the GPU: decoded from its 15-bit target. Otherwise the CPU's pixels.
        id<MTLTexture> src;
        HercMetalFrame mf;
        if (herc_metal_take_frame(&mf) && mf.w > 0 && mf.h > 0) {
            if (!g.decoded || (int)g.decoded.width != mf.w || (int)g.decoded.height != mf.h) {
                MTLTextureDescriptor *t =
                    [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm
                                                                       width:mf.w
                                                                      height:mf.h
                                                                   mipmapped:NO];
                t.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
                t.storageMode = MTLStorageModePrivate;
                g.decoded = [g.device newTextureWithDescriptor:t];
            }
            herc_metal_decode(cb, &mf, g.decoded);
            src = g.decoded;
            w = mf.w;
            h = mf.h;
        } else {
            src = upload(argb, w, h, stride);
        }
        int mode = herc_present_upscaler();
        if (mode == HERC_UPSCALER_METALFX && (!g.fx_supported || depth24))
            mode = HERC_UPSCALER_SHARP;  // movies: their own soft picture, no edge pass
        if (mode == HERC_UPSCALER_METALFX) {
            // MetalFX's output: the chosen height (ios.fxRows; 0 the picture's full size on screen), the picture's
            // aspect, then a plain linear stretch to the screen. Below 1.2x MetalFX leaves a fine grid at the ratio's
            // beat (the NFSMW port's finding at 9/8), so a step that close goes to the full size, and a picture
            // already about that large skips MetalFX.
            const int rows = herc_present_fx_rows();
            double oh = rows > 0 && rows < sh ? rows : sh;
            if (oh < h * 1.2)
                oh = sh;
            if (oh < h * 1.2) {
                mode = HERC_UPSCALER_SHARP;
            } else {
                id<MTLTexture> up = metalfx(cb, src, (int)std::lround(oh * sw / sh), (int)std::lround(oh));
                if (up)
                    src = up;
                else
                    mode = HERC_UPSCALER_SHARP;
            }
        }

        const double wait0 = CACurrentMediaTime();
        id<CAMetalDrawable> drawable = [g.layer nextDrawable];
        g.wait_s += CACurrentMediaTime() - wait0;
        if (!drawable) {
            [cb commit];
            return 1;
        }
        MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
        pass.colorAttachments[0].texture = drawable.texture;
        pass.colorAttachments[0].loadAction = MTLLoadActionClear;
        pass.colorAttachments[0].clearColor = MTLClearColorMake(0, 0, 0, 1);
        pass.colorAttachments[0].storeAction = MTLStoreActionStore;
        id<MTLRenderCommandEncoder> enc = [cb renderCommandEncoderWithDescriptor:pass];
        [enc setViewport:vp];
        [enc setVertexBytes:uvr length:sizeof uvr atIndex:0];
        [enc setFragmentTexture:src atIndex:0];
        if (mode == HERC_UPSCALER_SHARP) {
            const float scale[2] = {std::max(1.0f, std::floor((float)sw / (float)w)),
                                    std::max(1.0f, std::floor((float)sh / (float)h))};
            [enc setRenderPipelineState:g.sharp];
            [enc setFragmentBytes:scale length:sizeof scale atIndex:0];
            [enc setFragmentSamplerState:g.linear atIndex:0];
        } else {
            [enc setRenderPipelineState:g.plain];
            [enc setFragmentSamplerState:mode == HERC_UPSCALER_NEAREST ? g.nearest : g.linear atIndex:0];
        }
        [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
        [enc endEncoding];
        [cb presentDrawable:drawable];
        [cb commit];
    }
    g.last_exit = CACurrentMediaTime();
    g.present_s += g.last_exit - entered;
    return 1;
}

struct Register {
    Register() { psx_host_present_register(&present); }
} g_register;

}  // namespace

int herc_present_upscaler(void) {
    return std::clamp(setting_int(@"ios.upscaler", HERC_UPSCALER_METALFX), 0, 2);
}

void herc_present_set_upscaler(int mode) {
    [NSUserDefaults.standardUserDefaults setInteger:mode forKey:@"ios.upscaler"];
}

int herc_present_fx_rows(void) {
    return std::max(0, setting_int(@"ios.fxRows", 0));
}

void herc_present_set_fx_rows(int rows) {
    [NSUserDefaults.standardUserDefaults setInteger:rows forKey:@"ios.fxRows"];
}

int herc_present_screen_fit(void) {
    return std::clamp(setting_int(@"ios.screenFit", HERC_FIT_FIT), 0, 2);
}

void herc_present_set_screen_fit(int fit) {
    [NSUserDefaults.standardUserDefaults setInteger:fit forKey:@"ios.screenFit"];
}

double herc_present_fps(void) {
    return g.fps;
}

int herc_present_metalfx_available(void) {
    return g.fx_supported ? 1 : 0;
}
