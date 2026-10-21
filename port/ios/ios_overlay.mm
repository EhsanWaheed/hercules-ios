// ios_overlay.mm - the iOS settings panel over the game, and the controller bubble. Modelled on the NFSMW iOS port's
// panel (kit/host/sdl/ios_overlay.mm): Liquid Glass on iOS 26+, opened with L3+R3 on a controller, Cmd+S on a
// keyboard, or a three-finger tap or hold.
//
// Display: the aspect (Fit screen, 16:9, 4:3) and the render resolution are read by the game when it starts, so
// changing them offers a restart (the NFSMW restart card); the picture fit, the upscaler and MetalFX's output height
// apply at once (ios_present.mm). The resolution steps follow the NFSMW panel's, made simpler: the PS1 picture is
// drawn at 1x to 4x its 240 lines, and MetalFX takes it to 720p, 900p, 1080p or the screen's own height.
//
// The game is paused while the panel is open: its frame waits in herc_overlay_frame, which turns the run loop the
// way SDL's event pump does until the panel closes.
#include "ios_overlay.h"

#include "ios_host.h"
#include "ios_present.h"
#include "ios_touch.h"

#import <GameController/GameController.h>
#import <UIKit/UIKit.h>

#include <SDL3/SDL.h>

#include <algorithm>
#include <cmath>
#include <string>
#include <vector>

namespace {

NSUserDefaults *defaults() { return NSUserDefaults.standardUserDefaults; }

// The connected controller's family: 1 PlayStation, 2 any other (ios_launcher.mm herc_pad_family, per controller).
int controller_kind(GCController *c) {
    if (!c)
        return 0;
    NSString *cat = c.productCategory ?: @"";
    if ([cat isEqualToString:GCProductCategoryDualSense] || [cat isEqualToString:GCProductCategoryDualShock4])
        return 1;
    GCExtendedGamepad *pad = c.extendedGamepad;
    if ([pad isKindOfClass:GCDualSenseGamepad.class] || [pad isKindOfClass:GCDualShockGamepad.class])
        return 1;
    NSString *name = [NSString stringWithFormat:@"%@ %@", c.vendorName ?: @"", cat].lowercaseString;
    for (NSString *word in @[ @"playstation", @"dualsense", @"dualshock", @"ps5", @"ps4" ])
        if ([name containsString:word])
            return 1;
    return 2;
}

UIVisualEffect *glass_effect(BOOL tinted) {
    if (@available(iOS 26.0, *)) {
        UIGlassEffect *g = [UIGlassEffect effectWithStyle:UIGlassEffectStyleRegular];
        if (tinted)
            g.tintColor = [UIColor colorWithWhite:0.05 alpha:0.45];  // readable over a busy game
        return g;
    }
    return [UIBlurEffect effectWithStyle:UIBlurEffectStyleSystemMaterialDark];
}

void round_corners(UIVisualEffectView *v, CGFloat radius) {
    if (@available(iOS 26.0, *)) {
        v.cornerConfiguration = [UICornerConfiguration configurationWithUniformRadius:[UICornerRadius fixedRadius:radius]];
    } else {
        v.layer.cornerRadius = radius;
        v.layer.cornerCurve = kCACornerCurveContinuous;
        v.clipsToBounds = YES;
    }
}

// The render resolution's steps (game.toml internal_resolution: lines, "native" 240) and MetalFX's output heights.
const char *const kRenderLines[] = {"native", "480", "720", "960"};
NSString *const kRenderTitles[] = {@"240p · 1×", @"480p · 2×", @"720p · 3×", @"960p · 4×"};
const char *const kAspects[] = {"screen", "16:9", "4:3"};
const int kFxSteps[] = {720, 900, 1080};

int render_rows(const std::string &lines) { return lines == "native" ? 240 : std::max(240, atoi(lines.c_str())); }

}  // namespace

// ---- the controller bubble --------------------------------------------------------------------------------

@interface HercBubble : NSObject
@property(nonatomic, weak) UIWindow *window;
@property(nonatomic) UIVisualEffectView *view;
@property(nonatomic) UIImageView *icon;
@property(nonatomic) UILabel *title;
@property(nonatomic) UILabel *detail;
@property(nonatomic) NSUInteger serial;
@end

@implementation HercBubble

+ (instancetype)shared {
    static HercBubble *b;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
      b = [HercBubble new];
      NSNotificationCenter *nc = NSNotificationCenter.defaultCenter;
      [nc addObserver:b selector:@selector(connected:) name:GCControllerDidConnectNotification object:nil];
      [nc addObserver:b selector:@selector(disconnected:) name:GCControllerDidDisconnectNotification object:nil];
    });
    return b;
}

- (void)attach:(UIWindow *)window {
    [self.view removeFromSuperview];
    self.window = window;
    UIVisualEffectView *b = [[UIVisualEffectView alloc] initWithEffect:glass_effect(NO)];
    b.translatesAutoresizingMaskIntoConstraints = NO;
    b.userInteractionEnabled = NO;
    b.overrideUserInterfaceStyle = UIUserInterfaceStyleDark;
    if (@available(iOS 26.0, *))
        b.cornerConfiguration = [UICornerConfiguration capsuleConfiguration];
    else {
        b.layer.cornerRadius = 28;
        b.clipsToBounds = YES;
    }
    b.alpha = 0;
    self.icon = [[UIImageView alloc] initWithImage:[UIImage systemImageNamed:@"gamecontroller.fill"]];
    self.icon.tintColor = UIColor.whiteColor;
    self.icon.contentMode = UIViewContentModeScaleAspectFit;
    self.icon.preferredSymbolConfiguration =
        [UIImageSymbolConfiguration configurationWithPointSize:24 weight:UIImageSymbolWeightSemibold];
    self.title = [UILabel new];
    self.title.font = [UIFont preferredFontForTextStyle:UIFontTextStyleHeadline];
    self.title.textColor = UIColor.labelColor;
    self.title.lineBreakMode = NSLineBreakByTruncatingMiddle;
    self.detail = [UILabel new];
    self.detail.font = [UIFont preferredFontForTextStyle:UIFontTextStyleCaption1];
    self.detail.textColor = UIColor.secondaryLabelColor;
    for (UILabel *l in @[ self.title, self.detail ])
        [l setContentCompressionResistancePriority:UILayoutPriorityRequired - 1 forAxis:UILayoutConstraintAxisHorizontal];
    UIStackView *text = [[UIStackView alloc] initWithArrangedSubviews:@[ self.title, self.detail ]];
    text.axis = UILayoutConstraintAxisVertical;
    text.spacing = 1;
    UIStackView *s = [[UIStackView alloc] initWithArrangedSubviews:@[ self.icon, text ]];
    s.alignment = UIStackViewAlignmentCenter;
    s.spacing = 12;
    s.translatesAutoresizingMaskIntoConstraints = NO;
    [b.contentView addSubview:s];
    [window addSubview:b];
    [NSLayoutConstraint activateConstraints:@[
        [b.topAnchor constraintEqualToAnchor:window.safeAreaLayoutGuide.topAnchor constant:10],
        [b.centerXAnchor constraintEqualToAnchor:window.centerXAnchor],
        [b.widthAnchor constraintLessThanOrEqualToAnchor:window.widthAnchor multiplier:0.6],
        [s.topAnchor constraintEqualToAnchor:b.contentView.topAnchor constant:10],
        [s.bottomAnchor constraintEqualToAnchor:b.contentView.bottomAnchor constant:-10],
        [s.leadingAnchor constraintEqualToAnchor:b.contentView.leadingAnchor constant:18],
        [s.trailingAnchor constraintEqualToAnchor:b.contentView.trailingAnchor constant:-22],
        [self.icon.widthAnchor constraintEqualToConstant:32],
    ]];
    self.view = b;
}

- (void)show:(GCController *)c connected:(BOOL)connected {
    if (!self.view || !self.window)
        return;
    NSString *detail = connected ? @"Connected" : @"Disconnected";
    if (connected) {
        GCDeviceBattery *bat = c.battery;
        if (bat && bat.batteryLevel > 0)
            detail = [NSString stringWithFormat:@"Connected · %d%%", (int)lround(bat.batteryLevel * 100)];
    }
    NSString *symbol = @"gamecontroller.fill";
    const int kind = controller_kind(c);
    if (kind == 1 && [UIImage systemImageNamed:@"playstation.logo"])
        symbol = @"playstation.logo";
    else if (kind == 2 && [c.productCategory isEqualToString:GCProductCategoryXboxOne] &&
             [UIImage systemImageNamed:@"xbox.logo"])
        symbol = @"xbox.logo";
    self.icon.image = [UIImage systemImageNamed:symbol];
    self.icon.tintColor = connected ? UIColor.whiteColor : UIColor.secondaryLabelColor;
    self.title.text = c.vendorName.length ? c.vendorName : @"Controller";
    self.detail.text = detail;
    [self.window bringSubviewToFront:self.view];
    const NSUInteger serial = ++self.serial;
    self.view.transform = CGAffineTransformMakeTranslation(0, -24);
    [UIView animateWithDuration:0.45
                          delay:0
         usingSpringWithDamping:0.75
          initialSpringVelocity:0.5
                        options:UIViewAnimationOptionBeginFromCurrentState
                     animations:^{
                       self.view.alpha = 1;
                       self.view.transform = CGAffineTransformIdentity;
                     }
                     completion:nil];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(3.0 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
      if (serial != self.serial)
          return;  // a newer bubble is showing
      [UIView animateWithDuration:0.35
                       animations:^{
                         self.view.alpha = 0;
                         self.view.transform = CGAffineTransformMakeTranslation(0, -24);
                       }];
    });
}

- (void)connected:(NSNotification *)note {
    GCController *c = note.object;
    dispatch_async(dispatch_get_main_queue(), ^{
      [self show:c connected:YES];
    });
}

- (void)disconnected:(NSNotification *)note {
    GCController *c = note.object;
    dispatch_async(dispatch_get_main_queue(), ^{
      [self show:c connected:NO];
    });
}
@end

// ---- the panel --------------------------------------------------------------------------------------------

@interface HercOverlay : NSObject
@property(nonatomic, weak) UIWindow *window;
@property(nonatomic) UIView *root;
@property(nonatomic) UISegmentedControl *tabs;
@property(nonatomic) UIScrollView *scroll;
@property(nonatomic) UIStackView *display;
@property(nonatomic) UIStackView *controller;
@property(nonatomic) UISegmentedControl *aspect, *fit, *render, *upscaler, *fxRows;
@property(nonatomic) UILabel *chain;
@property(nonatomic) UILabel *speed;
@property(nonatomic) UISwitch *skipIntro;
@property(nonatomic) UISegmentedControl *renderer;
@property(nonatomic) UISwitch *verify;
@property(nonatomic) UIView *notice;
@property(nonatomic) NSTimer *poll;
@property(nonatomic) BOOL comboHeld, shortcutHeld;
@property(nonatomic) BOOL open;
@end

@implementation HercOverlay {
    std::vector<int> _fxSteps;   // MetalFX heights offered (0 the screen's)
    int _screenRows;             // the screen's shorter side in pixels
    std::string _launchAspect;   // as the game started (a change needs a restart)
    std::string _launchRender;
    BOOL _launchSkipIntro;
    BOOL _launchSoftware, _launchVerify;
}

- (instancetype)initWithWindow:(UIWindow *)window {
    if (!(self = [super init]))
        return nil;
    _window = window;
    UIScreen *screen = window.windowScene.screen ?: UIScreen.mainScreen;
    const CGSize px = screen.nativeBounds.size;
    _screenRows = (int)std::min(px.width, px.height);
    for (int r : kFxSteps)
        if (r < _screenRows)
            _fxSteps.push_back(r);
    _fxSteps.push_back(0);
    _launchAspect = herc_ios_aspect();
    _launchRender = herc_ios_render_lines();
    _launchSkipIntro = [defaults() boolForKey:@"ios.skipIntro"];
    _launchSoftware = [[defaults() stringForKey:@"ios.renderer"] isEqualToString:@"software"];
    _launchVerify = [defaults() boolForKey:@"ios.metalVerify"];
    herc_touch_install((__bridge void *)window);  // under the panel
    [self buildPanel];
    [self installTriggers];
    [[HercBubble shared] attach:window];
    return self;
}

// ---- building blocks (as the NFSMW panel's) ----

- (UILabel *)label:(NSString *)text style:(UIFontTextStyle)style {
    UILabel *l = [UILabel new];
    l.text = text;
    l.font = [UIFont preferredFontForTextStyle:style];
    l.adjustsFontForContentSizeCategory = YES;
    l.textColor = UIColor.labelColor;
    l.numberOfLines = 0;
    [l setContentCompressionResistancePriority:UILayoutPriorityDefaultLow forAxis:UILayoutConstraintAxisHorizontal];
    return l;
}

- (UILabel *)note:(NSString *)text {
    UILabel *l = [self label:text style:UIFontTextStyleCaption1];
    l.textColor = UIColor.secondaryLabelColor;
    return l;
}

- (UILabel *)section:(NSString *)title {
    UILabel *l = [self label:title.uppercaseString style:UIFontTextStyleFootnote];
    l.textColor = UIColor.systemOrangeColor;
    return l;
}

// A title (and a note below it) on the left, a control on the right.
- (UIView *)row:(NSString *)title note:(NSString *)note control:(UIView *)control {
    UIView *left = [self label:title style:UIFontTextStyleBody];
    if (note) {
        UIStackView *s = [[UIStackView alloc] initWithArrangedSubviews:@[ left, [self note:note] ]];
        s.axis = UILayoutConstraintAxisVertical;
        s.spacing = 2;
        left = s;
    }
    UIStackView *s = [[UIStackView alloc] initWithArrangedSubviews:control ? @[ left, control ] : @[ left ]];
    s.alignment = UIStackViewAlignmentCenter;
    s.spacing = 16;
    [left setContentHuggingPriority:UILayoutPriorityDefaultLow forAxis:UILayoutConstraintAxisHorizontal];
    [left setContentCompressionResistancePriority:UILayoutPriorityDefaultLow forAxis:UILayoutConstraintAxisHorizontal];
    if (control) {
        [control setContentHuggingPriority:UILayoutPriorityDefaultHigh + 1 forAxis:UILayoutConstraintAxisHorizontal];
        [control setContentCompressionResistancePriority:UILayoutPriorityDefaultHigh + 1
                                                 forAxis:UILayoutConstraintAxisHorizontal];
    }
    return s;
}

- (UIButton *)button:(NSString *)title action:(SEL)action prominent:(BOOL)prominent {
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
    UIButton *b = [UIButton buttonWithConfiguration:c primaryAction:nil];
    [b addTarget:self action:action forControlEvents:UIControlEventTouchUpInside];
    return b;
}

- (UISegmentedControl *)segments:(NSArray<NSString *> *)items selected:(NSInteger)i action:(SEL)action {
    UISegmentedControl *s = [[UISegmentedControl alloc] initWithItems:items];
    s.apportionsSegmentWidthsByContent = YES;
    s.selectedSegmentIndex = i;
    [s addTarget:self action:action forControlEvents:UIControlEventValueChanged];
    return s;
}

- (UIStackView *)column:(NSArray<UIView *> *)views {
    UIStackView *s = [[UIStackView alloc] initWithArrangedSubviews:views];
    s.axis = UILayoutConstraintAxisVertical;
    s.spacing = 12;
    return s;
}

// ---- the panel ----

- (void)buildPanel {
    UIView *root = [[UIView alloc] initWithFrame:self.window.bounds];
    root.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    root.backgroundColor = [UIColor colorWithWhite:0 alpha:0.2];
    root.hidden = YES;
    UITapGestureRecognizer *outside = [[UITapGestureRecognizer alloc] initWithTarget:self action:@selector(tapOutside:)];
    outside.cancelsTouchesInView = NO;
    [root addGestureRecognizer:outside];

    UIVisualEffectView *panel = [[UIVisualEffectView alloc] initWithEffect:glass_effect(YES)];
    panel.translatesAutoresizingMaskIntoConstraints = NO;
    panel.overrideUserInterfaceStyle = UIUserInterfaceStyleDark;
    round_corners(panel, 32);
    [root addSubview:panel];

    self.tabs = [[UISegmentedControl alloc] initWithItems:@[ @"Display", @"Controller" ]];
    self.tabs.selectedSegmentIndex = 0;
    [self.tabs addTarget:self action:@selector(tabChanged:) forControlEvents:UIControlEventValueChanged];
    UIButton *done = [self button:@"Done" action:@selector(close) prominent:YES];
    UIStackView *header = [[UIStackView alloc] initWithArrangedSubviews:@[ self.tabs, done ]];
    header.alignment = UIStackViewAlignmentCenter;
    header.spacing = 12;

    [self buildDisplay];
    self.controller = [self column:@[]];
    self.controller.hidden = YES;
    UIStackView *body = [[UIStackView alloc] initWithArrangedSubviews:@[ self.display, self.controller ]];
    body.axis = UILayoutConstraintAxisVertical;
    body.translatesAutoresizingMaskIntoConstraints = NO;
    self.scroll = [UIScrollView new];
    self.scroll.alwaysBounceVertical = YES;
    [self.scroll addSubview:body];

    UIStackView *column = [[UIStackView alloc] initWithArrangedSubviews:@[ header, self.scroll ]];
    column.axis = UILayoutConstraintAxisVertical;
    column.spacing = 14;
    column.translatesAutoresizingMaskIntoConstraints = NO;
    [panel.contentView addSubview:column];

    UILayoutGuide *safe = root.safeAreaLayoutGuide;
    NSLayoutConstraint *preferredWidth = [panel.widthAnchor constraintEqualToConstant:700];
    preferredWidth.priority = UILayoutPriorityRequired - 1;
    NSLayoutConstraint *fitHeight = [self.scroll.heightAnchor constraintEqualToAnchor:body.heightAnchor];
    fitHeight.priority = UILayoutPriorityDefaultLow;
    [NSLayoutConstraint activateConstraints:@[
        [panel.centerXAnchor constraintEqualToAnchor:safe.centerXAnchor],
        [panel.centerYAnchor constraintEqualToAnchor:safe.centerYAnchor],
        preferredWidth,
        [panel.widthAnchor constraintLessThanOrEqualToConstant:700],
        [panel.widthAnchor constraintLessThanOrEqualToAnchor:safe.widthAnchor constant:-24],
        [panel.heightAnchor constraintLessThanOrEqualToAnchor:safe.heightAnchor constant:-16],
        fitHeight,
        [column.topAnchor constraintEqualToAnchor:panel.contentView.topAnchor constant:16],
        [column.bottomAnchor constraintEqualToAnchor:panel.contentView.bottomAnchor constant:-16],
        [column.leadingAnchor constraintEqualToAnchor:panel.contentView.leadingAnchor constant:20],
        [column.trailingAnchor constraintEqualToAnchor:panel.contentView.trailingAnchor constant:-20],
        [body.topAnchor constraintEqualToAnchor:self.scroll.contentLayoutGuide.topAnchor],
        [body.bottomAnchor constraintEqualToAnchor:self.scroll.contentLayoutGuide.bottomAnchor],
        [body.leadingAnchor constraintEqualToAnchor:self.scroll.contentLayoutGuide.leadingAnchor],
        [body.trailingAnchor constraintEqualToAnchor:self.scroll.contentLayoutGuide.trailingAnchor],
        [body.widthAnchor constraintEqualToAnchor:self.scroll.frameLayoutGuide.widthAnchor],
    ]];
    [self.window addSubview:root];
    self.root = root;
}

- (void)buildDisplay {
    NSInteger aspect = 0;
    for (int i = 0; i < 3; ++i)
        if (_launchAspect == kAspects[i])
            aspect = i;
    self.aspect = [self segments:@[ @"Fit screen", @"16:9", @"4:3" ] selected:aspect action:@selector(aspectChanged:)];
    self.fit = [self segments:@[ @"Fit", @"Fill", @"Stretch" ]
                     selected:herc_present_screen_fit()
                       action:@selector(fitChanged:)];

    NSInteger render = 1;
    for (int i = 0; i < 4; ++i)
        if (_launchRender == kRenderLines[i])
            render = i;
    self.render = [self segments:@[ kRenderTitles[0], kRenderTitles[1], kRenderTitles[2], kRenderTitles[3] ]
                        selected:render
                          action:@selector(renderChanged:)];
    self.upscaler = [self segments:@[ @"MetalFX", @"Sharp", @"Nearest" ]
                          selected:herc_present_upscaler()
                            action:@selector(upscalerChanged:)];
    NSMutableArray *fx = [NSMutableArray array];
    NSInteger fxSel = (NSInteger)_fxSteps.size() - 1;
    for (size_t i = 0; i < _fxSteps.size(); ++i) {
        const int r = _fxSteps[i];
        [fx addObject:r ? [NSString stringWithFormat:@"%dp", r] : [NSString stringWithFormat:@"Screen · %dp", _screenRows]];
        if (r == herc_present_fx_rows())
            fxSel = (NSInteger)i;
    }
    self.fxRows = [self segments:fx selected:fxSel action:@selector(fxRowsChanged:)];
    self.chain = [self note:@""];
    self.speed = [self note:@""];
    self.renderer = [self segments:@[ @"Metal GPU", @"Software CPU" ]
                          selected:_launchSoftware ? 1 : 0
                            action:@selector(rendererChanged:)];
    self.verify = [UISwitch new];
    self.verify.on = _launchVerify;
    [self.verify addTarget:self action:@selector(verifyChanged:) forControlEvents:UIControlEventValueChanged];
    self.skipIntro = [UISwitch new];
    self.skipIntro.on = _launchSkipIntro;
    [self.skipIntro addTarget:self action:@selector(skipIntroChanged:) forControlEvents:UIControlEventValueChanged];

    self.display = [self column:@[
        [self section:@"Picture"],
        [self row:@"Aspect"
              note:@"Fit screen: the game draws out to the screen's own shape, the HUD in its corners: no bars, "
                   @"nothing cropped. Movies stay 4:3. Next launch."
           control:self.aspect],
        [self row:@"Picture fit"
              note:@"For 16:9 and 4:3 on a wider screen: Fit keeps bars, Fill crops the overhang, Stretch widens it."
           control:self.fit],
        [self section:@"Resolution"],
        [self row:@"Render resolution"
              note:@"The PS1 picture drawn at more lines before upscaling: sharper text and edges. The Metal renderer "
                   @"draws it on the GPU; with the software renderer 3× and 4× can slow the game down. Next launch."
           control:self.render],
        [self row:@"Upscaler"
              note:@"MetalFX: edge-aware upscaling. Sharp: square pixels with smooth edges. Nearest: raw pixels."
           control:self.upscaler],
        [self row:@"MetalFX output" note:nil control:self.fxRows],
        self.chain,
        self.speed,
        [self row:@"Renderer"
              note:@"Metal: the CPU draws the PS1's own picture, the GPU the high-resolution one (cooler, any "
                   @"resolution). Software: the CPU draws both. Next launch."
           control:self.renderer],
        [self row:@"Check against software"
              note:@"Diagnostic: each frame the Metal picture is compared with the software one and the differences "
                   @"are logged (Documents/Logs). Slower. Next launch."
           control:self.verify],
        [self section:@"Game"],
        [self row:@"Skip intro" note:@"Straight to the title screen (the logos and opening movie). Next launch."
           control:self.skipIntro],
    ]];
    [self refreshChain];
}

// The resolution chain as it runs now, under the MetalFX row: "480p → MetalFX 1080p → screen 1320p".
- (void)refreshChain {
    const int render = render_rows(_launchRender);
    const int mode = herc_present_upscaler();
    const BOOL fxOk = herc_present_metalfx_available();
    self.fxRows.enabled = mode == HERC_UPSCALER_METALFX && fxOk;
    NSString *text;
    if (mode == HERC_UPSCALER_METALFX && !fxOk) {
        text = @"MetalFX is not available on this device: Sharp is used instead.";
    } else if (mode == HERC_UPSCALER_METALFX) {
        int out = herc_present_fx_rows();
        if (!out || out >= _screenRows || out < render * 1.2)
            out = _screenRows;
        text = out < render * 1.2
                   ? [NSString stringWithFormat:@"%dp is already close to the screen's %dp: shown without MetalFX.", render,
                                                _screenRows]
                   : [NSString stringWithFormat:@"%dp → MetalFX %dp → screen %dp. Steps under 1.2× the render go to the "
                                                @"screen's height (finer ratios leave a grid).",
                                                render, out, _screenRows];
    } else {
        text = [NSString stringWithFormat:@"%dp → %@ → screen %dp", render,
                                          mode == HERC_UPSCALER_SHARP ? @"sharp bilinear" : @"nearest", _screenRows];
    }
    self.chain.text = text;
    [self refreshSpeed];
}

// The game's speed as it ran before the panel paused it: full speed is 60 frames a second (US timing).
- (void)refreshSpeed {
    const double fps = herc_present_fps();
    if (fps <= 0) {
        self.speed.text = @"";
        return;
    }
    const BOOL slow = fps < 57;
    self.speed.text = slow ? [NSString stringWithFormat:@"Running at %.0f fps of 60: the game and its music are "
                                                        @"slower than they should be. Choose a lower render "
                                                        @"resolution.", fps]
                           : [NSString stringWithFormat:@"Running at %.0f fps: full speed.", fps];
    self.speed.textColor = slow ? UIColor.systemOrangeColor : UIColor.secondaryLabelColor;
}

// The connected controller as a card: its family's logo, its name, and its own button glyphs (the symbols iOS gives
// each element: cross and circle on a DualSense or a Backbone One PlayStation Edition, A and B on an Xbox pad).
- (UIView *)controllerCard:(GCController *)c {
    const int kind = controller_kind(c);
    NSString *logo = kind == 1 ? @"playstation.logo"
                     : [c.productCategory containsString:@"Xbox"] ? @"xbox.logo" : @"gamecontroller.fill";
    UIImageView *icon = [[UIImageView alloc] initWithImage:[UIImage systemImageNamed:logo]
                                                              ?: [UIImage systemImageNamed:@"gamecontroller.fill"]];
    icon.tintColor = UIColor.whiteColor;
    icon.contentMode = UIViewContentModeScaleAspectFit;
    icon.preferredSymbolConfiguration = [UIImageSymbolConfiguration configurationWithPointSize:30];
    [icon.widthAnchor constraintEqualToConstant:44].active = YES;
    [icon.heightAnchor constraintEqualToConstant:44].active = YES;
    NSString *detail = kind == 1 ? @"PlayStation buttons" : @"Xbox buttons";
    GCDeviceBattery *bat = c.battery;
    if (bat && bat.batteryLevel > 0)
        detail = [NSString stringWithFormat:@"%@ · battery %d%%", detail, (int)lround(bat.batteryLevel * 100)];
    // Its own glyphs, in the PlayStation colours on a PlayStation pad.
    UIStackView *glyphs = [UIStackView new];
    glyphs.spacing = 8;
    GCExtendedGamepad *pad = c.extendedGamepad;
    if (pad) {
        NSArray<GCControllerElement *> *els = @[
            pad.buttonA, pad.buttonB, pad.buttonX, pad.buttonY, pad.leftShoulder, pad.rightShoulder, pad.leftTrigger,
            pad.rightTrigger, pad.buttonOptions ?: pad.buttonMenu, pad.buttonMenu
        ];
        NSArray<UIColor *> *ps = @[
            [UIColor colorWithRed:0.49 green:0.69 blue:1 alpha:1], [UIColor colorWithRed:1 green:0.4 blue:0.4 alpha:1],
            [UIColor colorWithRed:1 green:0.5 blue:0.78 alpha:1], [UIColor colorWithRed:0.25 green:0.89 blue:0.63 alpha:1]
        ];
        NSMutableSet *seen = [NSMutableSet set];
        for (NSUInteger i = 0; i < els.count; ++i) {
            NSString *name = els[i].sfSymbolsName;
            if (!name || [seen containsObject:name])
                continue;
            [seen addObject:name];
            UIImageView *g = [[UIImageView alloc] initWithImage:[UIImage systemImageNamed:name]];
            g.preferredSymbolConfiguration = [UIImageSymbolConfiguration configurationWithPointSize:20];
            g.tintColor = kind == 1 && i < 4 ? ps[i] : [UIColor colorWithWhite:1 alpha:0.85];
            [glyphs addArrangedSubview:g];
        }
    }
    UIStackView *text = [[UIStackView alloc] initWithArrangedSubviews:@[
        [self label:c.vendorName ?: @"Controller" style:UIFontTextStyleHeadline], [self note:detail], glyphs
    ]];
    text.axis = UILayoutConstraintAxisVertical;
    text.spacing = 4;
    text.alignment = UIStackViewAlignmentLeading;
    UIStackView *card = [[UIStackView alloc] initWithArrangedSubviews:@[ icon, text ]];
    card.alignment = UIStackViewAlignmentCenter;
    card.spacing = 14;
    return card;
}

- (void)buildController {
    for (UIView *v in self.controller.arrangedSubviews)
        [v removeFromSuperview];
    [self.controller addArrangedSubview:[self section:@"Controller"]];
    if (GCController.controllers.count == 0)
        [self.controller addArrangedSubview:[self row:@"No controller connected"
                                                 note:@"Pair one in Settings > General > Game Controller, or plug one "
                                                      @"in. The touch controls play until then."
                                              control:nil]];
    for (GCController *c in GCController.controllers)
        [self.controller addArrangedSubview:[self controllerCard:c]];
    if (GCKeyboard.coalescedKeyboard)
        [self.controller addArrangedSubview:[self row:@"Keyboard"
                                                 note:@"Plays too: arrows move, X cross, S circle, Z square, A "
                                                      @"triangle, Return Start, right Shift Select."
                                              control:nil]];

    [self.controller addArrangedSubview:[self section:@"Touch controls"]];
    [self.controller addArrangedSubview:[self row:@"Show"
                                             note:@"Auto: while no controller or keyboard is connected. The eye at the "
                                                  @"top hides them."
                                          control:[self segments:@[ @"Auto", @"Always", @"Off" ]
                                                        selected:herc_touch_mode()
                                                          action:@selector(touchModeChanged:)]]];
    [self.controller addArrangedSubview:[self row:@"Size"
                                             note:nil
                                          control:[self segments:@[ @"Small", @"Medium", @"Large" ]
                                                        selected:herc_touch_size()
                                                          action:@selector(touchSizeChanged:)]]];
    [self.controller addArrangedSubview:[self row:@"Opacity"
                                             note:nil
                                          control:[self segments:@[ @"Low", @"Medium", @"High" ]
                                                        selected:herc_touch_opacity()
                                                          action:@selector(touchOpacityChanged:)]]];
    [self.controller addArrangedSubview:[self row:@"Layout"
                                             note:@"Drag each control where your thumbs rest; Reset puts them back."
                                          control:[self button:@"Edit layout…" action:@selector(editLayout) prominent:NO]]];

    [self.controller addArrangedSubview:[self section:@"Shortcuts"]];
    [self.controller addArrangedSubview:[self row:@"This panel"
                                             note:@"L3 + R3, a three-finger tap, or Cmd+S on a keyboard."
                                          control:nil]];
    [self.controller addArrangedSubview:[self row:@"The game's own menu"
                                             note:@"Select + Start (Esc on a keyboard): volume, CRT picture, controls."
                                          control:nil]];
}

- (void)touchModeChanged:(UISegmentedControl *)s {
    herc_touch_set_mode((int)s.selectedSegmentIndex);
}
- (void)touchSizeChanged:(UISegmentedControl *)s {
    herc_touch_set_size((int)s.selectedSegmentIndex);
}
- (void)touchOpacityChanged:(UISegmentedControl *)s {
    herc_touch_set_opacity((int)s.selectedSegmentIndex);
}
- (void)editLayout {
    [self close];
    herc_touch_begin_edit();
}

// ---- changes ----

- (void)aspectChanged:(UISegmentedControl *)s {
    [defaults() setObject:@(kAspects[s.selectedSegmentIndex]) forKey:@"ios.aspect"];
    [self restartIfChanged];
}
- (void)fitChanged:(UISegmentedControl *)s {
    herc_present_set_screen_fit((int)s.selectedSegmentIndex);
}
- (void)renderChanged:(UISegmentedControl *)s {
    [defaults() setObject:@(kRenderLines[s.selectedSegmentIndex]) forKey:@"ios.renderLines"];
    [self restartIfChanged];
}
- (void)upscalerChanged:(UISegmentedControl *)s {
    herc_present_set_upscaler((int)s.selectedSegmentIndex);
    [self refreshChain];
}
- (void)fxRowsChanged:(UISegmentedControl *)s {
    herc_present_set_fx_rows(_fxSteps[(size_t)s.selectedSegmentIndex]);
    [self refreshChain];
}
- (void)rendererChanged:(UISegmentedControl *)s {
    [defaults() setObject:s.selectedSegmentIndex == 1 ? @"software" : @"metal" forKey:@"ios.renderer"];
    [self restartIfChanged];
}
- (void)verifyChanged:(UISwitch *)s {
    [defaults() setBool:s.on forKey:@"ios.metalVerify"];
    [self restartIfChanged];
}
- (void)skipIntroChanged:(UISwitch *)s {
    [defaults() setBool:s.on forKey:@"ios.skipIntro"];
    [self restartIfChanged];
}
- (void)tabChanged:(UISegmentedControl *)s {
    self.display.hidden = s.selectedSegmentIndex != 0;
    self.controller.hidden = s.selectedSegmentIndex != 1;
    if (s.selectedSegmentIndex == 1)
        [self buildController];
}

// A setting the game reads when it starts differs from the one it started with: the restart card.
- (void)restartIfChanged {
    const bool pending = herc_ios_aspect() != _launchAspect || herc_ios_render_lines() != _launchRender ||
                         (bool)[defaults() boolForKey:@"ios.skipIntro"] != (bool)_launchSkipIntro ||
                         (bool)[[defaults() stringForKey:@"ios.renderer"] isEqualToString:@"software"] !=
                             (bool)_launchSoftware ||
                         (bool)[defaults() boolForKey:@"ios.metalVerify"] != (bool)_launchVerify;
    if (pending && !self.notice)
        [self showRestartNotice];
    else if (!pending && self.notice)
        [self dismissNotice];
}

- (void)showRestartNotice {
    UIView *dim = [[UIView alloc] initWithFrame:self.window.bounds];
    dim.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    dim.backgroundColor = [UIColor colorWithWhite:0 alpha:0.25];
    UIVisualEffectView *card = [[UIVisualEffectView alloc] initWithEffect:glass_effect(NO)];
    card.translatesAutoresizingMaskIntoConstraints = NO;
    card.overrideUserInterfaceStyle = UIUserInterfaceStyleDark;
    round_corners(card, 30);
    UIImageView *icon = [[UIImageView alloc] initWithImage:[UIImage systemImageNamed:@"arrow.counterclockwise.circle.fill"]];
    icon.tintColor = UIColor.systemOrangeColor;
    icon.preferredSymbolConfiguration = [UIImageSymbolConfiguration configurationWithPointSize:44];
    icon.contentMode = UIViewContentModeScaleAspectFit;
    UILabel *title = [self label:@"Restart to apply" style:UIFontTextStyleTitle2];
    title.textAlignment = NSTextAlignmentCenter;
    UILabel *body = [self label:@"The game reads this when it starts: close it and open it again. Your progress since "
                                @"the last save is lost."
                          style:UIFontTextStyleBody];
    body.textAlignment = NSTextAlignmentCenter;
    body.textColor = UIColor.secondaryLabelColor;
    UIButton *close = [self button:@"Close game now" action:@selector(closeForRestart) prominent:YES];
    UIButton *later = [self button:@"Later" action:@selector(dismissNotice) prominent:NO];
    UIStackView *buttons = [[UIStackView alloc] initWithArrangedSubviews:@[ later, close ]];
    buttons.spacing = 12;
    buttons.distribution = UIStackViewDistributionFillEqually;
    UIStackView *stack = [[UIStackView alloc] initWithArrangedSubviews:@[ icon, title, body, buttons ]];
    stack.axis = UILayoutConstraintAxisVertical;
    stack.spacing = 14;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [card.contentView addSubview:stack];
    [dim addSubview:card];
    [NSLayoutConstraint activateConstraints:@[
        [card.centerXAnchor constraintEqualToAnchor:dim.centerXAnchor],
        [card.centerYAnchor constraintEqualToAnchor:dim.centerYAnchor],
        [card.widthAnchor constraintEqualToConstant:380],
        [stack.topAnchor constraintEqualToAnchor:card.contentView.topAnchor constant:26],
        [stack.bottomAnchor constraintEqualToAnchor:card.contentView.bottomAnchor constant:-22],
        [stack.leadingAnchor constraintEqualToAnchor:card.contentView.leadingAnchor constant:24],
        [stack.trailingAnchor constraintEqualToAnchor:card.contentView.trailingAnchor constant:-24],
    ]];
    [self.window addSubview:dim];
    self.notice = dim;
    dim.alpha = 0;
    card.transform = CGAffineTransformMakeScale(0.9, 0.9);
    [UIView animateWithDuration:0.4
                          delay:0
         usingSpringWithDamping:0.8
          initialSpringVelocity:0.5
                        options:0
                     animations:^{
                       dim.alpha = 1;
                       card.transform = CGAffineTransformIdentity;
                     }
                     completion:nil];
}

- (void)dismissNotice {
    UIView *n = self.notice;
    self.notice = nil;
    [UIView animateWithDuration:0.25
        animations:^{
          n.alpha = 0;
        }
        completion:^(BOOL) {
          [n removeFromSuperview];
        }];
}

// iOS has no relaunch: the settings are saved and the player opens the game again (Home Screen or LiveContainer).
- (void)closeForRestart {
    [defaults() synchronize];
    exit(0);
}

// ---- opening and closing ----

- (void)tapOutside:(UITapGestureRecognizer *)g {
    if ([self.root hitTest:[g locationInView:self.root] withEvent:nil] == self.root)
        [self close];
}

- (void)show {
    if (self.open)
        return;
    [self.window bringSubviewToFront:self.root];
    self.root.hidden = NO;
    self.open = YES;
    herc_touch_set_panel_open(1);
    [self refreshChain];
    if (self.tabs.selectedSegmentIndex == 1)
        [self buildController];
}

- (void)close {
    self.root.hidden = YES;
    self.open = NO;
    herc_touch_set_panel_open(0);
}

- (void)toggle {
    self.open ? [self close] : [self show];
}

- (void)installTriggers {
    UILongPressGestureRecognizer *hold = [[UILongPressGestureRecognizer alloc] initWithTarget:self action:@selector(held:)];
    hold.numberOfTouchesRequired = 3;
    hold.minimumPressDuration = 0.6;
    hold.cancelsTouchesInView = YES;
    [self.window addGestureRecognizer:hold];
    UITapGestureRecognizer *tap = [[UITapGestureRecognizer alloc] initWithTarget:self action:@selector(tapped3:)];
    tap.numberOfTouchesRequired = 3;
    tap.cancelsTouchesInView = YES;
    [tap requireGestureRecognizerToFail:hold];
    [self.window addGestureRecognizer:tap];
    // Controllers and the keyboard are polled, not observed: SDL owns their change handlers.
    self.poll = [NSTimer timerWithTimeInterval:1.0 / 30 target:self selector:@selector(pollInputs:) userInfo:nil repeats:YES];
    [NSRunLoop.mainRunLoop addTimer:self.poll forMode:NSRunLoopCommonModes];
}

- (void)tapped3:(UITapGestureRecognizer *)g {
    if (g.state == UIGestureRecognizerStateRecognized)
        [self toggle];
}

- (void)held:(UILongPressGestureRecognizer *)g {
    if (g.state == UIGestureRecognizerStateBegan)
        [self toggle];
}

- (void)pollInputs:(NSTimer *)t {
    // L3+R3 on any controller: an edge, so holding both toggles once.
    BOOL combo = NO;
    for (GCController *c in GCController.controllers) {
        GCExtendedGamepad *pad = c.extendedGamepad;
        if (pad && pad.leftThumbstickButton.isPressed && pad.rightThumbstickButton.isPressed)
            combo = YES;
    }
    if (combo && !self.comboHeld)
        [self toggle];
    self.comboHeld = combo;
    BOOL shortcut = NO;
    if (GCKeyboardInput *k = GCKeyboard.coalescedKeyboard.keyboardInput) {
        const BOOL cmd = [k buttonForKeyCode:GCKeyCodeLeftGUI].isPressed || [k buttonForKeyCode:GCKeyCodeRightGUI].isPressed;
        shortcut = cmd && [k buttonForKeyCode:GCKeyCodeKeyS].isPressed;
    }
    if (shortcut && !self.shortcutHeld)
        [self toggle];
    self.shortcutHeld = shortcut;
    // B / circle closes, as in a system sheet.
    if (self.open)
        for (GCController *c in GCController.controllers)
            if (c.extendedGamepad.buttonB.isPressed) {
                [self close];
                break;
            }
}
@end

// ---------------------------------------------------------------------------

namespace {
HercOverlay *g_overlay;

UIWindow *game_window() {
    int count = 0;
    SDL_Window **windows = SDL_GetWindows(&count);
    UIWindow *w = nil;
    if (windows && count > 0)
        w = (__bridge UIWindow *)SDL_GetPointerProperty(SDL_GetWindowProperties(windows[0]),
                                                       SDL_PROP_WINDOW_UIKIT_WINDOW_POINTER, nullptr);
    SDL_free(windows);
    return w;
}
}  // namespace

void herc_overlay_frame(void) {
    if (!g_overlay) {
        UIWindow *w = game_window();
        if (!w)
            return;
        g_overlay = [[HercOverlay alloc] initWithWindow:w];
        // development: the panel without a controller (Simulator screenshots), after HERC_OPEN_PANEL seconds
        if (const char *e = getenv("HERC_OPEN_PANEL")) {
            HercOverlay *o = g_overlay;
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(atof(e) * NSEC_PER_SEC)), dispatch_get_main_queue(),
                           ^{
                             [o show];
                           });
        }
    }
    // Paused while the panel is open: the run loop turns here (as SDL's UIKit_PumpEvents) until it closes.
    while (g_overlay.open || herc_touch_editing()) {
        @autoreleasepool {
            SInt32 r;
            do
                r = CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.000002, true);
            while (r == kCFRunLoopRunHandledSource);
            do
                r = CFRunLoopRunInMode((CFStringRef)UITrackingRunLoopMode, 0.000002, true);
            while (r == kCFRunLoopRunHandledSource);
        }
        [NSThread sleepForTimeInterval:1.0 / 120.0];
    }
}

void herc_bubble_attach(void *uiwindow) {
    [[HercBubble shared] attach:(__bridge UIWindow *)uiwindow];
}
