// ios_touch.mm - the on-screen controls: Liquid Glass buttons in the PS1 pad's layout over the game, as the NFSMW
// port's glass controls (kit/host/controls). A D-pad disc (8 ways, the finger may slide), the face buttons in their
// PlayStation colours, L1/L2 and R1/R2, Select and Start, and an eye that hides them.
//
// They reach the game through psx_host_pad_register (psx_game_launcher.h): merged into player 1's pad beside the
// controller and the keyboard, so nothing switches devices. Auto (the default) shows them while no controller or
// keyboard is connected and hides them when one connects. The layout can be edited from the settings panel: drag a
// control; the positions are kept per control (ios.touchLayout), as fractions of the safe area.
#include "ios_touch.h"

#include "psx_game_launcher.h"

#import <GameController/GameController.h>
#import <UIKit/UIKit.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <vector>

namespace {

NSUserDefaults *defaults() { return NSUserDefaults.standardUserDefaults; }

// The PSX pad word's bits (psx_keybinds.c PSXKB_BIT_*).
enum : uint16_t {
    kSelect = 1u << 0, kStart = 1u << 3, kUp = 1u << 4, kRight = 1u << 5, kDown = 1u << 6, kLeft = 1u << 7,
    kL2 = 1u << 8, kR2 = 1u << 9, kL1 = 1u << 10, kR1 = 1u << 11,
    kTriangle = 1u << 12, kCircle = 1u << 13, kCross = 1u << 14, kSquare = 1u << 15,
};

std::atomic<uint16_t> g_pressed{0};  // the buttons held on screen (active high)

uint16_t touch_pad(int player) { return player == 1 ? (uint16_t)~g_pressed.load() : 0xFFFF; }

struct Register {
    Register() { psx_host_pad_register(&touch_pad); }
} g_register;

enum Kind { kDpad, kRound, kShoulder, kPill, kEye };

struct Control {
    NSString *key;     // ios.touchLayout's key
    Kind kind;
    uint16_t bits;
    CGPoint home;      // default centre, fractions of the safe area
    CGSize size;       // points at medium
    NSString *symbol;  // SF Symbol, or nil for `label`
    NSString *label;
    UIColor *tint;
};

UIColor *rgb(int r, int g, int b) { return [UIColor colorWithRed:r / 255.0 green:g / 255.0 blue:b / 255.0 alpha:1]; }

std::vector<Control> controls() {
    return {
        {@"dpad", kDpad, 0, {0.14, 0.68}, {150, 150}, nil, nil, UIColor.whiteColor},
        {@"triangle", kRound, kTriangle, {0.87, 0.50}, {60, 60}, @"triangle", nil, rgb(64, 226, 160)},
        {@"circle", kRound, kCircle, {0.945, 0.68}, {60, 60}, @"circle", nil, rgb(255, 102, 102)},
        {@"cross", kRound, kCross, {0.87, 0.86}, {60, 60}, @"xmark", nil, rgb(124, 176, 255)},
        {@"square", kRound, kSquare, {0.795, 0.68}, {60, 60}, @"square", nil, rgb(255, 128, 200)},
        // the shoulders in a row above each thumb's controls, clear of the game's HUD in the top corners
        {@"l2", kShoulder, kL2, {0.06, 0.33}, {72, 36}, nil, @"L2", UIColor.whiteColor},
        {@"l1", kShoulder, kL1, {0.17, 0.33}, {72, 36}, nil, @"L1", UIColor.whiteColor},
        {@"r1", kShoulder, kR1, {0.83, 0.33}, {72, 36}, nil, @"R1", UIColor.whiteColor},
        {@"r2", kShoulder, kR2, {0.94, 0.33}, {72, 36}, nil, @"R2", UIColor.whiteColor},
        {@"select", kPill, kSelect, {0.43, 0.93}, {74, 30}, nil, @"SELECT", UIColor.whiteColor},
        {@"start", kPill, kStart, {0.57, 0.93}, {74, 30}, nil, @"START", UIColor.whiteColor},
        {@"eye", kEye, 0, {0.5, 0.05}, {44, 30}, @"eye.slash", nil, UIColor.whiteColor},
    };
}

UIVisualEffect *glass(BOOL interactive) {
    if (@available(iOS 26.0, *)) {
        UIGlassEffect *g = [UIGlassEffect effectWithStyle:UIGlassEffectStyleClear];
        g.interactive = interactive;
        return g;
    }
    return [UIBlurEffect effectWithStyle:UIBlurEffectStyleSystemUltraThinMaterialDark];
}

}  // namespace

// ---- one control's view ------------------------------------------------------------------------------------

@interface HercTouchControl : UIView
@property(nonatomic) NSInteger index;
@property(nonatomic) UIVisualEffectView *body;
@property(nonatomic) NSArray<UIImageView *> *arrows;  // the D-pad's up, right, down, left
@property(nonatomic) UIView *glyph;
@property(nonatomic) BOOL pressed;
@end

@implementation HercTouchControl

- (instancetype)initWithControl:(const Control &)c index:(NSInteger)index {
    if (!(self = [super initWithFrame:CGRectMake(0, 0, c.size.width, c.size.height)]))
        return nil;
    self.index = index;
    self.userInteractionEnabled = NO;  // the layer view tracks every finger
    self.body = [[UIVisualEffectView alloc] initWithEffect:glass(YES)];
    self.body.frame = self.bounds;
    self.body.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    self.body.overrideUserInterfaceStyle = UIUserInterfaceStyleDark;
    self.body.clipsToBounds = YES;
    self.body.layer.cornerCurve = kCACornerCurveContinuous;
    self.body.layer.borderWidth = 0.75;
    self.body.layer.borderColor = [UIColor colorWithWhite:1 alpha:0.28].CGColor;
    [self addSubview:self.body];

    UIImageSymbolConfiguration *cfg =
        [UIImageSymbolConfiguration configurationWithPointSize:c.kind == kRound ? 24 : 15 weight:UIImageSymbolWeightBold];
    if (c.kind == kDpad) {
        NSMutableArray *arrows = [NSMutableArray array];
        for (NSString *s in @[ @"arrowtriangle.up.fill", @"arrowtriangle.right.fill", @"arrowtriangle.down.fill",
                               @"arrowtriangle.left.fill" ]) {
            UIImageView *a = [[UIImageView alloc] initWithImage:[UIImage systemImageNamed:s withConfiguration:cfg]];
            a.tintColor = [UIColor colorWithWhite:1 alpha:0.85];
            [self.body.contentView addSubview:a];
            [arrows addObject:a];
        }
        self.arrows = arrows;
    } else if (c.symbol) {
        UIImageView *g = [[UIImageView alloc] initWithImage:[UIImage systemImageNamed:c.symbol withConfiguration:cfg]];
        g.tintColor = c.tint;
        g.contentMode = UIViewContentModeCenter;
        self.glyph = g;
    } else {
        UILabel *l = [UILabel new];
        l.text = c.label;
        l.textColor = [UIColor colorWithWhite:1 alpha:0.9];
        l.font = [UIFont systemFontOfSize:c.kind == kPill ? 11 : 15 weight:UIFontWeightBold];
        l.textAlignment = NSTextAlignmentCenter;
        self.glyph = l;
    }
    if (self.glyph) {
        self.glyph.frame = self.bounds;
        self.glyph.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
        [self.body.contentView addSubview:self.glyph];
    }
    return self;
}

- (void)layoutSubviews {
    [super layoutSubviews];
    const CGSize s = self.bounds.size;
    self.body.layer.cornerRadius = std::min(s.width, s.height) / 2;
    if (self.arrows) {
        const CGFloat r = s.width * 0.33;
        const CGPoint c = CGPointMake(s.width / 2, s.height / 2);
        const CGPoint at[4] = {{c.x, c.y - r}, {c.x + r, c.y}, {c.x, c.y + r}, {c.x - r, c.y}};
        for (int i = 0; i < 4; ++i) {
            [self.arrows[i] sizeToFit];
            self.arrows[i].center = at[i];
        }
    }
}

// Pressed: a little smaller and brighter; the D-pad lights the directions held.
- (void)showPressed:(BOOL)pressed directions:(uint16_t)dirs {
    if (self.arrows) {
        const uint16_t bit[4] = {kUp, kRight, kDown, kLeft};
        for (int i = 0; i < 4; ++i)
            self.arrows[i].tintColor = (dirs & bit[i]) ? UIColor.whiteColor : [UIColor colorWithWhite:1 alpha:0.6];
    }
    if (pressed == self.pressed)
        return;
    self.pressed = pressed;
    [UIView animateWithDuration:pressed ? 0.06 : 0.14
                     animations:^{
                       self.transform = pressed && !self.arrows ? CGAffineTransformMakeScale(0.9, 0.9)
                                                                : CGAffineTransformIdentity;
                       self.body.backgroundColor = pressed ? [UIColor colorWithWhite:1 alpha:0.22] : UIColor.clearColor;
                     }];
}
@end

// ---- the layer over the game ---------------------------------------------------------------------------------

@interface HercTouchView : UIView
@property(nonatomic) NSMutableArray<HercTouchControl *> *views;
@property(nonatomic) BOOL panelOpen;
@property(nonatomic) BOOL editing;
@property(nonatomic) UIVisualEffectView *editBar;
@property(nonatomic) UIImpactFeedbackGenerator *haptic;
@end

@implementation HercTouchView {
    std::vector<Control> _controls;
    NSMapTable<UITouch *, NSNumber *> *_owner;  // finger -> control index
    NSMapTable<UITouch *, NSValue *> *_dragFrom;  // editing: finger -> start offset
}

- (instancetype)initWithFrame:(CGRect)frame {
    if (!(self = [super initWithFrame:frame]))
        return nil;
    self.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    self.multipleTouchEnabled = YES;
    self.backgroundColor = UIColor.clearColor;
    _controls = controls();
    _owner = [NSMapTable weakToStrongObjectsMapTable];
    _dragFrom = [NSMapTable weakToStrongObjectsMapTable];
    self.views = [NSMutableArray array];
    for (size_t i = 0; i < _controls.size(); ++i) {
        HercTouchControl *v = [[HercTouchControl alloc] initWithControl:_controls[i] index:(NSInteger)i];
        [self addSubview:v];
        [self.views addObject:v];
    }
    self.haptic = [[UIImpactFeedbackGenerator alloc] initWithStyle:UIImpactFeedbackStyleLight];
    for (NSNotificationName n in @[ GCControllerDidConnectNotification, GCControllerDidDisconnectNotification,
                                     GCKeyboardDidConnectNotification, GCKeyboardDidDisconnectNotification ])
        [NSNotificationCenter.defaultCenter addObserver:self selector:@selector(devicesChanged:) name:n object:nil];
    [self refresh];
    return self;
}

- (void)devicesChanged:(NSNotification *)n {
    dispatch_async(dispatch_get_main_queue(), ^{
      [self refresh];
    });
}

- (CGFloat)scale {
    const int s = herc_touch_size();
    return s == 0 ? 0.85 : s == 2 ? 1.2 : 1.0;
}

- (CGPoint)centreOf:(size_t)i {
    NSDictionary *layout = [defaults() dictionaryForKey:@"ios.touchLayout"];
    NSArray *p = layout[_controls[i].key];
    const CGPoint f = p.count == 2 ? CGPointMake([p[0] doubleValue], [p[1] doubleValue]) : _controls[i].home;
    const CGRect safe = UIEdgeInsetsInsetRect(self.bounds, self.safeAreaInsets);
    return CGPointMake(safe.origin.x + f.x * safe.size.width, safe.origin.y + f.y * safe.size.height);
}

- (void)layoutSubviews {
    [super layoutSubviews];
    const CGFloat k = [self scale];
    for (size_t i = 0; i < _controls.size(); ++i) {
        HercTouchControl *v = self.views[i];
        const CGSize s = _controls[i].kind == kEye ? _controls[i].size
                                                    : CGSizeMake(_controls[i].size.width * k, _controls[i].size.height * k);
        v.transform = CGAffineTransformIdentity;
        v.bounds = CGRectMake(0, 0, s.width, s.height);
        v.center = [self centreOf:i];
    }
    if (self.editBar)
        self.editBar.center = CGPointMake(self.bounds.size.width / 2, self.safeAreaInsets.top + 34);
}

// Shown: per mode, unless the panel is open; the eye alone while the player hid them; everything while editing.
- (void)refresh {
    const int mode = herc_touch_mode();
    const BOOL device = GCController.controllers.count > 0 || GCKeyboard.coalescedKeyboard != nil;
    const BOOL wanted = self.editing || (!self.panelOpen && (mode == 1 || (mode == 0 && !device)));
    const BOOL hidden = !self.editing && [defaults() boolForKey:@"ios.touchHidden"];
    const CGFloat alpha = herc_touch_opacity() == 0 ? 0.35 : herc_touch_opacity() == 2 ? 0.9 : 0.65;
    self.hidden = !wanted;
    for (size_t i = 0; i < _controls.size(); ++i) {
        HercTouchControl *v = self.views[i];
        const BOOL eye = _controls[i].kind == kEye;
        v.hidden = (eye && self.editing) || (!eye && hidden);
        v.alpha = eye ? (hidden ? 0.5 : alpha * 0.8) : alpha;
        if (eye)
            ((UIImageView *)v.glyph).image = [UIImage systemImageNamed:hidden ? @"eye" : @"eye.slash"];
    }
    if (!wanted || hidden)
        [self releaseAll];
    [self setNeedsLayout];
}

- (void)releaseAll {
    [_owner removeAllObjects];
    g_pressed = 0;
    for (HercTouchControl *v in self.views)
        [v showPressed:NO directions:0];
}

// ---- touches ----

- (BOOL)pointInside:(CGPoint)point withEvent:(UIEvent *)event {
    if (self.editing)
        return YES;
    for (HercTouchControl *v in self.views)
        if (!v.hidden && CGRectContainsPoint(CGRectInset(v.frame, -14, -14), point))
            return YES;
    return NO;
}

// The control under a point (frames grown a little), or -1.
- (NSInteger)controlAt:(CGPoint)p {
    NSInteger best = -1;
    CGFloat bestDist = CGFLOAT_MAX;
    for (HercTouchControl *v in self.views) {
        if (v.hidden || !CGRectContainsPoint(CGRectInset(v.frame, -14, -14), p))
            continue;
        const CGFloat d = hypot(p.x - v.center.x, p.y - v.center.y);
        if (d < bestDist) {
            bestDist = d;
            best = v.index;
        }
    }
    return best;
}

// The D-pad's directions for a finger at `p`: 8 ways, a dead centre.
- (uint16_t)dpadBits:(CGPoint)p {
    HercTouchControl *v = self.views[0];
    const CGFloat dx = p.x - v.center.x, dy = p.y - v.center.y;
    if (hypot(dx, dy) < v.bounds.size.width * 0.12)
        return 0;
    const double a = atan2(-dy, dx) * 180 / M_PI;  // 0 right, 90 up
    uint16_t b = 0;
    if (a > 22.5 && a < 157.5) b |= kUp;
    if (a < -22.5 && a > -157.5) b |= kDown;
    if (fabs(a) < 67.5) b |= kRight;
    if (fabs(a) > 112.5) b |= kLeft;
    return b;
}

- (void)recompute {
    uint16_t bits = 0, dirs = 0;
    std::vector<bool> held(_controls.size(), false);
    for (UITouch *t in _owner) {
        const NSInteger i = [_owner objectForKey:t].integerValue;
        if (i < 0)
            continue;
        held[(size_t)i] = true;
        if (_controls[(size_t)i].kind == kDpad)
            dirs |= [self dpadBits:[t locationInView:self]];
        else
            bits |= _controls[(size_t)i].bits;
    }
    const uint16_t before = g_pressed.load();
    g_pressed = (uint16_t)(bits | dirs);
    if ((bits | dirs) & ~before)
        [self.haptic impactOccurred];
    for (size_t i = 0; i < _controls.size(); ++i)
        [self.views[i] showPressed:held[i] directions:_controls[i].kind == kDpad ? dirs : 0];
}

- (void)touchesBegan:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event {
    for (UITouch *t in touches) {
        const CGPoint p = [t locationInView:self];
        const NSInteger i = [self controlAt:p];
        if (self.editing) {
            if (i >= 0) {
                HercTouchControl *v = self.views[(size_t)i];
                [_owner setObject:@(i) forKey:t];
                [_dragFrom setObject:[NSValue valueWithCGPoint:CGPointMake(v.center.x - p.x, v.center.y - p.y)] forKey:t];
            }
            continue;
        }
        if (i >= 0 && _controls[(size_t)i].kind == kEye) {
            [defaults() setBool:![defaults() boolForKey:@"ios.touchHidden"] forKey:@"ios.touchHidden"];
            [self.haptic impactOccurred];
            [self refresh];
            continue;
        }
        [_owner setObject:@(i) forKey:t];
    }
    if (!self.editing)
        [self recompute];
}

- (void)touchesMoved:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event {
    for (UITouch *t in touches) {
        NSNumber *owner = [_owner objectForKey:t];
        if (!owner)
            continue;
        const CGPoint p = [t locationInView:self];
        if (self.editing) {
            const CGPoint off = [[_dragFrom objectForKey:t] CGPointValue];
            self.views[(size_t)owner.integerValue].center = CGPointMake(p.x + off.x, p.y + off.y);
            continue;
        }
        // A finger on the D-pad keeps it; one on a button may slide to the next (across the face buttons).
        if (owner.integerValue >= 0 && _controls[(size_t)owner.integerValue].kind == kDpad)
            continue;
        const NSInteger now = [self controlAt:p];
        if (now != owner.integerValue && (now < 0 || _controls[(size_t)now].kind != kDpad))
            [_owner setObject:@(now) forKey:t];
    }
    if (!self.editing)
        [self recompute];
}

- (void)touchesEnded:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event {
    for (UITouch *t in touches) {
        if (self.editing) {
            NSNumber *owner = [_owner objectForKey:t];
            if (owner)
                [self saveCentre:(size_t)owner.integerValue];
            [_dragFrom removeObjectForKey:t];
        }
        [_owner removeObjectForKey:t];
    }
    if (!self.editing)
        [self recompute];
}

- (void)touchesCancelled:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event {
    [self touchesEnded:touches withEvent:event];
}

// ---- layout editing ----

- (void)saveCentre:(size_t)i {
    const CGRect safe = UIEdgeInsetsInsetRect(self.bounds, self.safeAreaInsets);
    const CGPoint c = self.views[i].center;
    const double fx = std::clamp((c.x - safe.origin.x) / safe.size.width, 0.0, 1.0);
    const double fy = std::clamp((c.y - safe.origin.y) / safe.size.height, 0.0, 1.0);
    NSMutableDictionary *layout = [[defaults() dictionaryForKey:@"ios.touchLayout"] mutableCopy] ?: [NSMutableDictionary dictionary];
    layout[_controls[i].key] = @[ @(fx), @(fy) ];
    [defaults() setObject:layout forKey:@"ios.touchLayout"];
    [self setNeedsLayout];
}

- (void)beginEdit {
    self.editing = YES;
    [self releaseAll];
    UIVisualEffectView *bar = [[UIVisualEffectView alloc] initWithEffect:glass(NO)];
    bar.overrideUserInterfaceStyle = UIUserInterfaceStyleDark;
    bar.layer.cornerRadius = 24;
    bar.layer.cornerCurve = kCACornerCurveContinuous;
    bar.clipsToBounds = YES;
    UILabel *hint = [UILabel new];
    hint.text = @"Drag the controls";
    hint.textColor = UIColor.whiteColor;
    hint.font = [UIFont systemFontOfSize:15 weight:UIFontWeightSemibold];
    UIButtonConfiguration *(^config)(NSString *, BOOL) = ^UIButtonConfiguration *(NSString *title, BOOL prominent) {
      UIButtonConfiguration *c = prominent ? UIButtonConfiguration.filledButtonConfiguration
                                           : UIButtonConfiguration.grayButtonConfiguration;
      if (@available(iOS 26.0, *))
          c = prominent ? UIButtonConfiguration.prominentGlassButtonConfiguration
                        : UIButtonConfiguration.glassButtonConfiguration;
      c.title = title;
      c.cornerStyle = UIButtonConfigurationCornerStyleCapsule;
      c.buttonSize = UIButtonConfigurationSizeSmall;
      if (prominent)
          c.baseBackgroundColor = UIColor.systemOrangeColor;
      return c;
    };
    UIButton *reset = [UIButton buttonWithConfiguration:config(@"Reset", NO) primaryAction:nil];
    [reset addTarget:self action:@selector(resetTapped) forControlEvents:UIControlEventTouchUpInside];
    UIButton *done = [UIButton buttonWithConfiguration:config(@"Done", YES) primaryAction:nil];
    [done addTarget:self action:@selector(endEdit) forControlEvents:UIControlEventTouchUpInside];
    UIStackView *s = [[UIStackView alloc] initWithArrangedSubviews:@[ hint, reset, done ]];
    s.spacing = 14;
    s.alignment = UIStackViewAlignmentCenter;
    s.frame = CGRectMake(18, 8, 320, 32);
    [bar.contentView addSubview:s];
    bar.bounds = CGRectMake(0, 0, 350, 48);
    [self addSubview:bar];
    self.editBar = bar;
    for (HercTouchControl *v in self.views) {
        v.body.layer.borderColor = UIColor.systemOrangeColor.CGColor;
        v.body.layer.borderWidth = 1.5;
    }
    [self refresh];
}

- (void)resetTapped {
    [defaults() removeObjectForKey:@"ios.touchLayout"];
    [UIView animateWithDuration:0.25
                     animations:^{
                       [self setNeedsLayout];
                       [self layoutIfNeeded];
                     }];
}

- (void)endEdit {
    self.editing = NO;
    [_owner removeAllObjects];
    [self.editBar removeFromSuperview];
    self.editBar = nil;
    for (HercTouchControl *v in self.views) {
        v.body.layer.borderColor = [UIColor colorWithWhite:1 alpha:0.28].CGColor;
        v.body.layer.borderWidth = 0.75;
    }
    [self refresh];
}

// The edit bar's buttons are its own: hit them before the drag tracking.
- (UIView *)hitTest:(CGPoint)point withEvent:(UIEvent *)event {
    if (self.editBar && CGRectContainsPoint(self.editBar.frame, point))
        return [self.editBar hitTest:[self convertPoint:point toView:self.editBar] withEvent:event];
    return [super hitTest:point withEvent:event];
}
@end

// ---------------------------------------------------------------------------

namespace {
HercTouchView *g_view;

int setting(NSString *key, int fallback, int hi) {
    id v = [defaults() objectForKey:key];
    return v ? std::clamp((int)[v integerValue], 0, hi) : fallback;
}
}  // namespace

void herc_touch_install(void *uiwindow) {
    UIWindow *w = (__bridge UIWindow *)uiwindow;
    if (g_view || !w)
        return;
    g_view = [[HercTouchView alloc] initWithFrame:w.bounds];
    [w addSubview:g_view];
}

void herc_touch_set_panel_open(int open) {
    g_view.panelOpen = open != 0;
    [g_view refresh];
}

void herc_touch_begin_edit(void) { [g_view beginEdit]; }
int herc_touch_editing(void) { return g_view.editing ? 1 : 0; }

int herc_touch_mode(void) { return setting(@"ios.touchMode", 0, 2); }
void herc_touch_set_mode(int mode) {
    [defaults() setInteger:mode forKey:@"ios.touchMode"];
    [g_view refresh];
}
int herc_touch_size(void) { return setting(@"ios.touchSize", 1, 2); }
void herc_touch_set_size(int size) {
    [defaults() setInteger:size forKey:@"ios.touchSize"];
    [g_view setNeedsLayout];
}
int herc_touch_opacity(void) { return setting(@"ios.touchOpacity", 1, 2); }
void herc_touch_set_opacity(int opacity) {
    [defaults() setInteger:opacity forKey:@"ios.touchOpacity"];
    [g_view refresh];
}
void herc_touch_reset_layout(void) {
    [defaults() removeObjectForKey:@"ios.touchLayout"];
    [g_view setNeedsLayout];
}
