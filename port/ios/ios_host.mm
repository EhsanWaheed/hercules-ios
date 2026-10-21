// ios_host.mm - what the game needs from iOS before it starts (ios.cmake).
//
// The runtime resolves every file next to its executable (game.toml, bios/,
// mods/, settings, saves) and writes some of them. On iOS the app bundle is
// read-only, so the runtime runs from a writable root instead,
// Library/Application Support/Hercules, where each bundled file is linked
// back into the bundle (the links are remade every start: an app update
// moves the bundle). Saves live in Documents/Saves, where the Files app shows
// them.
//
// The launcher (ios_launcher.mm) calls herc_ios_prepare_runtime first.
#include "ios_host.h"

#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>

#include <cstdio>
#include <cstdlib>
#include <string>
#include <unistd.h>

namespace {

NSFileManager *fm() { return NSFileManager.defaultManager; }

NSString *documents_dir() {
    return NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES).firstObject;
}

NSString *runtime_root() {
    NSString *support =
        NSSearchPathForDirectoriesInDomains(NSApplicationSupportDirectory, NSUserDomainMask, YES).firstObject;
    return [support stringByAppendingPathComponent:@"Hercules"];
}

// Links `name` in `dir` to the same name in `target`, replacing a link from an earlier install. A real file or folder
// the runtime made there is kept.
void link_item(NSString *dir, NSString *target, NSString *name) {
    NSString *link = [dir stringByAppendingPathComponent:name];
    NSDictionary *attrs = [fm() attributesOfItemAtPath:link error:nil];
    if (attrs && ![attrs.fileType isEqualToString:NSFileTypeSymbolicLink])
        return;
    [fm() removeItemAtPath:link error:nil];
    [fm() createSymbolicLinkAtPath:link withDestinationPath:[target stringByAppendingPathComponent:name] error:nil];
}

// Links every bundled runtime file into the root. mods/ is a real folder of links instead, because the launcher
// writes the mod selection (mods/state.toml) there; game.toml is written by the launcher for each start
// (herc_ios_write_game_config).
void link_bundle_into(NSString *root, NSString *exe_name) {
    NSString *bundle = NSBundle.mainBundle.bundlePath;
    NSSet<NSString *> *skip = [NSSet setWithArray:@[
        exe_name, @"Info.plist", @"PkgInfo", @"_CodeSignature", @"embedded.mobileprovision", @"game",
        @"LauncherArt.png", @"Frameworks", @"game.toml", @"mods"
    ]];
    for (NSString *name in [fm() contentsOfDirectoryAtPath:bundle error:nil]) {
        if ([skip containsObject:name] || [name hasSuffix:@".lproj"] || [name hasSuffix:@".car"] ||
            [name hasPrefix:@"AppIcon"])
            continue;
        link_item(root, bundle, name);
    }
    NSString *mods = [root stringByAppendingPathComponent:@"mods"];
    NSDictionary *attrs = [fm() attributesOfItemAtPath:mods error:nil];
    if ([attrs.fileType isEqualToString:NSFileTypeSymbolicLink])
        [fm() removeItemAtPath:mods error:nil];  // an earlier build linked the whole folder
    [fm() createDirectoryAtPath:mods withIntermediateDirectories:YES attributes:nil error:nil];
    NSString *bundled_mods = [bundle stringByAppendingPathComponent:@"mods"];
    for (NSString *name in [fm() contentsOfDirectoryAtPath:bundled_mods error:nil])
        link_item(mods, bundled_mods, name);

    NSString *saves = [documents_dir() stringByAppendingPathComponent:@"Saves"];
    [fm() createDirectoryAtPath:saves withIntermediateDirectories:YES attributes:nil error:nil];
    // remade each start: an app update moves the data container
    NSString *saves_link = [root stringByAppendingPathComponent:@"saves"];
    NSDictionary *saves_attrs = [fm() attributesOfItemAtPath:saves_link error:nil];
    if (!saves_attrs || [saves_attrs.fileType isEqualToString:NSFileTypeSymbolicLink]) {
        [fm() removeItemAtPath:saves_link error:nil];
        [fm() createSymbolicLinkAtPath:saves_link withDestinationPath:saves error:nil];
    }
}

std::string g_exe_path;  // argv[0] for the rest of the run

}  // namespace

std::string herc_ios_runtime_root() { return runtime_root().UTF8String; }

// The runtime's output (and the iOS host's own lines) into Documents/Logs/hercules.log, the previous run's kept as
// hercules-prev.log: under LiveContainer nothing else sees stdout or stderr.
static void redirect_output() {
    NSString *logs = [documents_dir() stringByAppendingPathComponent:@"Logs"];
    [fm() createDirectoryAtPath:logs withIntermediateDirectories:YES attributes:nil error:nil];
    NSString *log = [logs stringByAppendingPathComponent:@"hercules.log"];
    NSString *prev = [logs stringByAppendingPathComponent:@"hercules-prev.log"];
    [fm() removeItemAtPath:prev error:nil];
    [fm() moveItemAtPath:log toPath:prev error:nil];
    if (freopen(log.fileSystemRepresentation, "w", stdout))
        setvbuf(stdout, nullptr, _IOLBF, 0);
    if (freopen(log.fileSystemRepresentation, "a", stderr))
        setvbuf(stderr, nullptr, _IOLBF, 0);
}

void herc_ios_prepare_runtime(char **argv) {
    @autoreleasepool {
        if (!getenv("HERC_LOG_CONSOLE"))  // development: keep the console (simctl --console-pty)
            redirect_output();
        NSString *root = runtime_root();
        [fm() createDirectoryAtPath:root withIntermediateDirectories:YES attributes:nil error:nil];
        NSString *exe_name = [NSString stringWithUTF8String:argv[0]].lastPathComponent;
        link_bundle_into(root, exe_name);
        g_exe_path = [root stringByAppendingPathComponent:exe_name].UTF8String;
        argv[0] = (char *)g_exe_path.c_str();
        chdir(root.fileSystemRepresentation);
        setenv("PSX_P1_KEYBOARD_TOO", "1", 0);  // a keyboard plays player 1 beside the controller
    }
}

// gpu_gl_renderer.c calls glClearDepth directly; OpenGLES has only
// glClearDepthf. The GL renderer never starts on iOS (ios.cmake), so this is
// unreachable.
extern "C" void glClearDepth(double) {
    std::fprintf(stderr, "hercules-ios: glClearDepth called, but iOS has no OpenGL renderer\n");
    std::abort();
}

// ---- the settings the game reads at start --------------------------------------------------------------------
// The settings panel (ios.* in NSUserDefaults) decides; these turn them into the runtime's own files, as the desktop
// launcher does (launcher_native/hl_launcher.cpp write_mod_state).

std::string herc_ios_aspect() {
    NSString *v = [NSUserDefaults.standardUserDefaults stringForKey:@"ios.aspect"];
    return v ? v.UTF8String : "screen";  // the screen's own shape: no bars, nothing cropped
}

std::string herc_ios_render_lines() {
    NSString *v = [NSUserDefaults.standardUserDefaults stringForKey:@"ios.renderLines"];
    return v ? v.UTF8String : "480";  // 2x the PS1's 240 lines: sharper text and edges into MetalFX
}

static void write_file(NSString *path, const std::string &text) {
    NSDictionary *attrs = [fm() attributesOfItemAtPath:path error:nil];
    if ([attrs.fileType isEqualToString:NSFileTypeSymbolicLink])
        [fm() removeItemAtPath:path error:nil];
    [@(text.c_str()) writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];
}

void herc_ios_write_game_config() {
    @autoreleasepool {
        NSString *bundled = [NSBundle.mainBundle.bundlePath stringByAppendingPathComponent:@"game.toml"];
        NSMutableString *t = [[NSString stringWithContentsOfFile:bundled encoding:NSUTF8StringEncoding error:nil]
            mutableCopy];
        if (!t)
            return;
        NSRegularExpression *re = [NSRegularExpression regularExpressionWithPattern:@"internal_resolution = \"[^\"]*\""
                                                                            options:0
                                                                              error:nil];
        NSString *line = [NSString stringWithFormat:@"internal_resolution = \"%s\"", herc_ios_render_lines().c_str()];
        [re replaceMatchesInString:t options:0 range:NSMakeRange(0, t.length) withTemplate:line];
        // Player 1 on the first controller (a release build's default is the keyboard: the desktop launcher assigns
        // the pad, and iOS has none of its own). A keyboard plays player 1 too (PSX_P1_KEYBOARD_TOO, set at start):
        // an iPad's Magic Keyboard, or a phone's Bluetooth one.
        [t replaceOccurrencesOfString:@"[controller]\n"
                           withString:@"[controller]\np1_device = \"gamepad\"\n"
                              options:0
                                range:NSMakeRange(0, t.length)];
        write_file([runtime_root() stringByAppendingPathComponent:@"game.toml"], t.UTF8String);
    }
}

void herc_ios_write_mod_state() {
    std::string t = "format_version = 2\n";
    for (const char *p : {"hercules.hd-sprites", "psx.enhancement.hd-textures", "hercules.level-select",
                          "hercules.widescreen", "hercules.skip-intro", "psx.enhancement.cd-speed",
                          "hercules.frame-blend"})
        t += std::string("\n[[package]]\nid = \"") + p + "\"\n";
    auto feature = [&](const char *pkg, const char *id, bool on) {
        t += std::string("\n[[feature]]\npackage_id = \"") + pkg + "\"\nid = \"" + id + "\"\nenabled = " +
             (on ? "true" : "false") + "\n";
    };
    feature("hercules.hd-sprites", "hd-sprites", false);  // no HD pack on iOS yet
    feature("psx.enhancement.hd-textures", "hd-textures", false);
    feature("hercules.level-select", "level-select", false);
    t += "\n[feature.values]\nlevel = \"off\"\n";
    feature("hercules.widescreen", "widescreen", true);  // 4:3 too: the in-game menu switches live
    t += "\n[feature.values]\naspect = \"" + herc_ios_aspect() + "\"\n";
    // ios.skipIntro (the panel): straight to the title screen. ios.directStart (hidden, for testing): straight into
    // the first level, as the desktop launcher's level pick, movies skipped.
    const bool direct = [NSUserDefaults.standardUserDefaults boolForKey:@"ios.directStart"];
    const bool skip = direct || [NSUserDefaults.standardUserDefaults boolForKey:@"ios.skipIntro"];
    feature("hercules.skip-intro", "skip-intro", skip);
    feature("hercules.skip-intro", "skip-memcard", skip);
    feature("hercules.skip-intro", "skip-fmv", direct);
    feature("hercules.ntsc-speed", "ntsc-speed", true);  // the desktop default since 0.5.5: US speed
    feature("hercules.skip-intro", "direct-start", direct);
    t += "\n[feature.values]\nlevel = \"1\"\n";
    feature("psx.enhancement.cd-speed", "cd-speed", false);
    t += "\n[feature.values]\nmultiplier = \"4\"\n";
    feature("hercules.frame-blend", "frame-blend", false);
    t += "\n[feature.values]\nblend = \"linear\"\n";
    @autoreleasepool {
        write_file([runtime_root() stringByAppendingPathComponent:@"mods/state.toml"], t);
    }
}
