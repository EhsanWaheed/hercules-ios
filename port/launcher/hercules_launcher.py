#!/usr/bin/env python3
"""Hercules Recompiled launcher (GTK 4 / libadwaita).

The runtime is built without PSXRecomp's ImGui launcher (no recomp-ui), but
it still reads everything a launcher would write:

- <exe-dir>/settings.toml   video / audio settings (layered over game.toml)
- <exe-dir>/mods/state.toml which mod features are on (HD pack = hercules.hd-sprites)
- PSX_LOAD_SLOT=N           load save-state slot N right after boot

This tool edits those files, then starts the game with --no-launcher and
waits for it. Its own choices (preset, slot names) live in
<exe-dir>/launcher.json.

HD sprites and HD level textures share one pack (replacements/sprites and
replacements/levels). The pack loader does not follow directory symlinks,
so "only one of them" uses a variant pack made of hard links
(SCES-00893.launcher-sprites / -levels), rebuilt when the main pack changes.

    python3 launcher/hercules_launcher.py [--build build-release]
"""
import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent          # HerculesRecomp
GAME_ID = "SCES-00893"
EXE_NAME = "Hercules_Recompiled"
SLOTS = 12                                             # SAVESTATE_SLOTS
HD_PACKAGE, HD_FEATURE = "hercules.hd-sprites", "hd-sprites"
GENERIC_PACKAGE, GENERIC_FEATURE = "psx.enhancement.hd-textures", "hd-textures"

# (value written to settings.toml, label)
RESOLUTIONS = [("native", "Original (320×240)"), ("720p", "720p"), ("1080p", "1080p"),
               ("1440p", "1440p"), ("4k", "4K")]
WINDOW_SIZES = [(0, "Automatisch"), (960, "960 × 720"), (1280, "1280 × 960"),
                (1440, "1440 × 1080"), (1920, "1920 × 1440")]
DISPLAY_MODES = [(0, "Fenster"), (1, "Vollbild (randlos)"), (2, "Vollbild (exklusiv)")]
ASPECTS = [("4:3", "4:3 (original)"), ("16:9", "16:9 (gestreckt, breitere Sicht – experimentell)")]
VSYNC = [("on", "An"), ("adaptive", "Adaptiv"), ("vrr", "VRR / FreeSync"), ("off", "Aus")]
TEX_FILTERS = [("nearest", "Scharf (Pixel)"), ("bilinear", "Weich (bilinear)"),
               ("xbr", "Geglättet (xBR)")]
SCREENS = [("raw", "Roh (exakte Farben)"), ("crt", "Röhrenfernseher"),
           ("composite", "Composite-Kabel"), ("trinitron", "Trinitron")]
AUDIO_FREQS = [(48000, "48 000 Hz"), (44100, "44 100 Hz"), (32000, "32 000 Hz")]

DEFAULTS = {
    "internal_resolution": "1080p", "window_width": 0, "fullscreen": 0,
    "aspect_ratio": "4:3", "vsync": "on", "texture_filtering": "nearest",
    "antialiasing": False, "crt_filter": "raw", "scanlines": False,
    "scanline_strength": 0.35, "perspective_texturing": False,
    "geometry_correction": False, "auto_skip_fmv": False, "rewind": True,
    "frequency": 48000, "spu_hq": True, "hd_sprites": True, "hd_levels": True,
}
PRESETS = {
    "original": dict(internal_resolution="native", texture_filtering="nearest",
                     antialiasing=False, crt_filter="crt", scanlines=True,
                     scanline_strength=0.35, hd_sprites=False, hd_levels=False,
                     perspective_texturing=False),
    "hd": dict(internal_resolution="1080p", texture_filtering="nearest",
               antialiasing=False, crt_filter="raw", scanlines=False,
               hd_sprites=True, hd_levels=True),
}
VIDEO_KEYS = ["internal_resolution", "window_width", "fullscreen", "aspect_ratio", "vsync",
              "texture_filtering", "antialiasing", "crt_filter", "scanlines",
              "scanline_strength", "perspective_texturing", "geometry_correction",
              "auto_skip_fmv", "rewind"]
AUDIO_KEYS = ["frequency", "spu_hq"]


# ---------------------------------------------------------------- TOML out
def _toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list) and all(not isinstance(x, dict) for x in v):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise TypeError(f"cannot write {v!r} as TOML")


def toml_dumps(doc, prefix=""):
    """Small TOML writer for what settings.toml / mods/state.toml use."""
    out, tables, arrays = [], [], []
    for k, v in doc.items():
        if isinstance(v, dict):
            tables.append((k, v))
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            arrays.append((k, v))
        else:
            out.append(f"{k} = {_toml_value(v)}")
    for k, v in tables:
        out += ["", f"[{prefix}{k}]", toml_dumps(v, f"{prefix}{k}.")]
    for k, items in arrays:
        for item in items:
            out += ["", f"[[{prefix}{k}]]", toml_dumps(item, f"{prefix}{k}.")]
    return "\n".join(x for x in out if x is not None).strip("\n") + ("\n" if not prefix else "")


def read_toml(path):
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


def write_atomic(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# --------------------------------------------------------------- savestates
class SaveState:
    def __init__(self, slot, pst, mtime, thumb):
        self.slot, self.pst, self.mtime, self.thumb = slot, pst, mtime, thumb


def saves_dir():
    """Slots live in <memcard_dir>/openbios; memcard_dir comes from game.toml."""
    game = read_toml(ROOT / "game.toml")
    base = ROOT / game.get("runtime", {}).get("memcard_dir", "saves")
    return base / "openbios"


def entry_pc():
    game = read_toml(ROOT / "game.toml")
    return int(game.get("game", {}).get("entry_pc", "0x80013710"), 16)


def slot_path(slot, ext):
    return saves_dir() / f"state_{entry_pc():08X}_slot{slot:02d}.{ext}"


def read_thumb(path):
    """PSTH header (magic, u32 w, u32 h) + w*h ARGB words, little endian."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < 12 or data[:4] != b"PSTH":
        return None
    w, h = struct.unpack_from("<II", data, 4)
    if len(data) < 12 + w * h * 4:
        return None
    return Gdk.MemoryTexture.new(w, h, Gdk.MemoryFormat.B8G8R8A8,
                                 GLib.Bytes.new(data[12:12 + w * h * 4]), w * 4)


def list_states():
    states = []
    for slot in range(SLOTS):
        pst = slot_path(slot, "pst")
        if pst.exists():
            states.append(SaveState(slot, pst, pst.stat().st_mtime,
                                    read_thumb(slot_path(slot, "thumb"))))
    return states


def is_state_file(path):
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return False
    return len(head) >= 16 and struct.unpack_from("<I", head)[0] == 0x50535842  # PSXB


# ------------------------------------------------------------------ HD pack
def pack_for(build, sprites, levels):
    """Pack root for the chosen HD parts, or None for none."""
    base = build / "mods" / "texture-packs" / GAME_ID
    if not (sprites or levels):
        return None
    if sprites and levels:
        return base
    part = "sprites" if sprites else "levels"
    return base.with_name(f"{GAME_ID}.launcher-{part}")


def variant_stale(build, part):
    base = build / "mods" / "texture-packs" / GAME_ID
    variant = base.with_name(f"{GAME_ID}.launcher-{part}")
    src = base / "replacements" / part
    try:
        st = src.stat()
        marker = json.loads((variant / "launcher-source.json").read_text())
    except (OSError, ValueError):
        return True
    return marker != {"ino": st.st_ino, "mtime": st.st_mtime}


def build_variant(build, part):
    """Hard-link replacements/<part> of the main pack into its own pack."""
    base = build / "mods" / "texture-packs" / GAME_ID
    variant = base.with_name(f"{GAME_ID}.launcher-{part}")
    src = base / "replacements" / part
    tmp = variant.with_name(variant.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "replacements").mkdir(parents=True)
    (tmp / "dumps").mkdir()
    for name in ("config.yaml",):
        if (base / name).exists():
            shutil.copy2(base / name, tmp / name)
    subprocess.run(["cp", "-al", str(src), str(tmp / "replacements" / part)], check=True)
    st = src.stat()
    (tmp / "launcher-source.json").write_text(json.dumps({"ino": st.st_ino, "mtime": st.st_mtime}))
    shutil.rmtree(variant, ignore_errors=True)
    os.replace(tmp, variant)


def write_mod_state(build, pack):
    path = build / "mods" / "state.toml"
    doc = read_toml(path) or {"format_version": 2}
    pkgs = doc.setdefault("package", [])
    feats = doc.setdefault("feature", [])
    for pid in (HD_PACKAGE, GENERIC_PACKAGE):
        if not any(p.get("id") == pid for p in pkgs):
            pkgs.append({"id": pid})

    def feature(pid, fid):
        for f in feats:
            if f.get("package_id") == pid and f.get("id") == fid:
                return f
        f = {"package_id": pid, "id": fid, "enabled": False}
        feats.append(f)
        return f

    hd = feature(HD_PACKAGE, HD_FEATURE)
    hd["enabled"] = pack is not None
    if pack is not None:
        hd.setdefault("resources", {})["pack"] = str(pack)
    # The generic loader would load the same pack a second time.
    feature(GENERIC_PACKAGE, GENERIC_FEATURE)["enabled"] = False
    write_atomic(path, toml_dumps(doc))


def write_settings(build, cfg):
    path = build / "settings.toml"
    doc = read_toml(path)
    video = doc.setdefault("video", {})
    audio = doc.setdefault("audio", {})
    for k in VIDEO_KEYS:
        if k == "window_width" and not cfg[k]:
            video.pop(k, None)              # 0 = let the runtime fit the display
        else:
            video[k] = cfg[k]
    video["renderer"] = "opengl"            # HD replacements need OpenGL
    for k in AUDIO_KEYS:
        audio[k] = cfg[k]
    doc.setdefault("launcher", {})["skip_launcher"] = True
    write_atomic(path, toml_dumps(doc))


# ----------------------------------------------------------------------- UI
def combo(title, subtitle, items, value, on_change):
    row = Adw.ComboRow(title=title, subtitle=subtitle or "")
    row.set_model(Gtk.StringList.new([label for _, label in items]))
    values = [v for v, _ in items]
    row.set_selected(values.index(value) if value in values else 0)
    row.connect("notify::selected", lambda r, _p: on_change(values[r.get_selected()]))
    return row


def switch(title, subtitle, value, on_change):
    row = Adw.SwitchRow(title=title, subtitle=subtitle or "")
    row.set_active(bool(value))
    row.connect("notify::active", lambda r, _p: on_change(r.get_active()))
    return row


class Launcher(Adw.Application):
    def __init__(self, build):
        super().__init__(application_id="de.obaid.HerculesLauncher",
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.build = build
        self.exe = build / EXE_NAME
        self.store_path = build / "launcher.json"
        try:
            self.store = json.loads(self.store_path.read_text())
        except (OSError, ValueError):
            self.store = {}
        self.cfg = dict(DEFAULTS, **self.store.get("settings", {}))
        self.names = self.store.get("slot_names", {})
        self.selected_slot = self.store.get("last_slot")   # None = new game
        self.updating = False
        self.game = None

    # -- persistence
    def save_store(self):
        self.store.update(settings=self.cfg, slot_names=self.names, last_slot=self.selected_slot)
        write_atomic(self.store_path, json.dumps(self.store, indent=2, ensure_ascii=False))

    def slot_name(self, st):
        n = self.names.get(str(st.slot))
        # A name belongs to one save; the game may have overwritten the slot.
        if n and abs(n.get("mtime", 0) - st.mtime) < 1:
            return n.get("name")
        return None

    # -- window
    def do_activate(self):
        self.win = Adw.ApplicationWindow(application=self, title="Hercules Recompiled",
                                         default_width=860, default_height=760)
        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.stack = Adw.ViewStack()
        header.set_title_widget(Adw.ViewSwitcher(stack=self.stack,
                                                 policy=Adw.ViewSwitcherPolicy.WIDE))
        view.add_top_bar(header)

        self.stack.add_titled_with_icon(self.page_play(), "play", "Spielen",
                                        "media-playback-start-symbolic")
        self.stack.add_titled_with_icon(self.page_video(), "video", "Grafik",
                                        "video-display-symbolic")
        self.stack.add_titled_with_icon(self.page_filter(), "filter", "Bildfilter",
                                        "applications-graphics-symbolic")
        self.stack.add_titled_with_icon(self.page_system(), "system", "Ton & System",
                                        "audio-speakers-symbolic")
        self.toasts.set_child(self.stack)
        view.set_content(self.toasts)

        bar = Gtk.Box(spacing=12, margin_start=16, margin_end=16, margin_top=10, margin_bottom=10)
        self.summary = Gtk.Label(xalign=0, hexpand=True, wrap=True)
        self.summary.add_css_class("dim-label")
        self.play_btn = Gtk.Button(label="Spielen")
        self.play_btn.add_css_class("suggested-action")
        self.play_btn.add_css_class("pill")
        self.play_btn.connect("clicked", lambda _b: self.start_game())
        bar.append(self.summary)
        bar.append(self.play_btn)
        view.add_bottom_bar(bar)

        self.win.set_content(view)
        self.refresh_summary()
        if not self.exe.exists():
            self.play_btn.set_sensitive(False)
            self.toast(f"{self.exe} fehlt – erst bauen")
        self.win.present()

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=4))

    def set(self, key, value):
        self.cfg[key] = value
        if not self.updating:
            if key in {"internal_resolution", "texture_filtering", "antialiasing", "crt_filter",
                       "scanlines", "scanline_strength", "hd_sprites", "hd_levels",
                       "perspective_texturing"}:
                self.sync_preset_row()
            self.save_store()
            self.refresh_summary()

    # -- page: play
    def page_play(self):
        page = Adw.PreferencesPage()
        style = Adw.PreferencesGroup(title="Stil",
                                     description="Voreinstellung; einzelne Punkte lassen sich "
                                                 "unter Grafik und Bildfilter anpassen.")
        self.preset_row = Adw.ToggleGroup(homogeneous=True, margin_bottom=4)
        self.preset_row.add_css_class("round")
        for name, label in (("original", "Alt & pixelig"), ("hd", "Neu & HD"),
                            ("custom", "Eigene")):
            self.preset_row.add(Adw.Toggle(name=name, label=label))
        self.preset_row.connect("notify::active-name", self.on_preset)
        style.add(self.preset_row)
        self.preset_hint = Gtk.Label(xalign=0, wrap=True, margin_top=6)
        self.preset_hint.add_css_class("dim-label")
        style.add(self.preset_hint)
        page.add(style)
        self.sync_preset_row()

        self.saves_group = Adw.PreferencesGroup(
            title="Spielstand",
            description="Savestates des Spiels (im Spiel mit F7 anlegen). "
                        "Stände einer älteren Programmversion lehnt das Spiel ab.")
        imp = Gtk.Button(icon_name="document-open-symbolic", valign=Gtk.Align.CENTER,
                         tooltip_text="Savestate-Datei (.pst) importieren")
        imp.add_css_class("flat")
        imp.connect("clicked", lambda _b: self.import_state())
        self.saves_group.set_header_suffix(imp)
        page.add(self.saves_group)
        self.save_rows = []
        self.fill_saves()
        return page

    def fill_saves(self):
        for r in self.save_rows:
            self.saves_group.remove(r)
        self.save_rows = []
        states = list_states()
        if self.selected_slot is not None and not any(s.slot == self.selected_slot for s in states):
            self.selected_slot = None
        group_btn = None

        def add(row, check):
            row.set_activatable_widget(check)
            self.saves_group.add(row)
            self.save_rows.append(row)

        new = Adw.ActionRow(title="Neues Spiel", subtitle="Start vom Titelbild")
        group_btn = Gtk.CheckButton(valign=Gtk.Align.CENTER, active=self.selected_slot is None)
        group_btn.connect("toggled", lambda b: b.get_active() and self.pick_slot(None))
        new.add_prefix(group_btn)
        add(new, group_btn)

        for st in sorted(states, key=lambda s: -s.mtime):
            when = time.strftime("%d.%m.%Y %H:%M", time.localtime(st.mtime))
            name = self.slot_name(st)
            row = Adw.ActionRow(title=GLib.markup_escape_text(name or f"Platz {st.slot + 1}"),
                                subtitle=f"Platz {st.slot + 1} · {when}" if name else when)
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER, group=group_btn,
                                    active=self.selected_slot == st.slot)
            check.connect("toggled", lambda b, s=st.slot: b.get_active() and self.pick_slot(s))
            if st.thumb is not None:
                pic = Gtk.Picture.new_for_paintable(st.thumb)
                pic.set_size_request(128, 96)
                pic.set_content_fit(Gtk.ContentFit.CONTAIN)
                pic.set_margin_top(6)
                pic.set_margin_bottom(6)
                pic.add_css_class("card")
                row.add_prefix(pic)
            row.add_prefix(check)       # add_prefix prepends: the radio ends up first
            ren = Gtk.Button(icon_name="document-edit-symbolic", valign=Gtk.Align.CENTER,
                             tooltip_text="Umbenennen")
            ren.add_css_class("flat")
            ren.connect("clicked", lambda _b, s=st: self.rename_state(s))
            rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                            tooltip_text="Löschen")
            rm.add_css_class("flat")
            rm.connect("clicked", lambda _b, s=st: self.delete_state(s))
            row.add_suffix(ren)
            row.add_suffix(rm)
            add(row, check)
        self.refresh_summary()

    def pick_slot(self, slot):
        self.selected_slot = slot
        self.save_store()
        self.refresh_summary()

    def rename_state(self, st):
        entry = Gtk.Entry(text=self.slot_name(st) or "", activates_default=True,
                          placeholder_text="z. B. Level 2, Anfang")
        dlg = Adw.AlertDialog(heading="Spielstand benennen", extra_child=entry)
        dlg.add_response("cancel", "Abbrechen")
        dlg.add_response("ok", "Speichern")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("ok")

        def done(_d, resp):
            if resp != "ok":
                return
            text = entry.get_text().strip()
            if text:
                self.names[str(st.slot)] = {"name": text, "mtime": st.mtime}
            else:
                self.names.pop(str(st.slot), None)
            self.save_store()
            self.fill_saves()
        dlg.connect("response", done)
        dlg.present(self.win)

    def delete_state(self, st):
        dlg = Adw.AlertDialog(heading="Spielstand löschen?",
                              body=f"„{self.slot_name(st) or f'Platz {st.slot + 1}'}“ wird "
                                   "endgültig gelöscht.")
        dlg.add_response("cancel", "Abbrechen")
        dlg.add_response("delete", "Löschen")
        dlg.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def done(_d, resp):
            if resp != "delete":
                return
            for ext in ("pst", "thumb", "hdres"):
                slot_path(st.slot, ext).unlink(missing_ok=True)
            self.names.pop(str(st.slot), None)
            self.save_store()
            self.fill_saves()
        dlg.connect("response", done)
        dlg.present(self.win)

    def import_state(self):
        dlg = Gtk.FileDialog(title="Savestate importieren")
        filt = Gtk.FileFilter(name="PSXRecomp-Savestate (*.pst)")
        filt.add_pattern("*.pst")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(filt)
        dlg.set_filters(store)

        def done(d, res):
            try:
                f = d.open_finish(res)
            except GLib.Error:
                return
            src = Path(f.get_path())
            if not is_state_file(src):
                self.toast("Keine PSXRecomp-Savestate-Datei")
                return
            used = {s.slot for s in list_states()}
            free = [i for i in range(SLOTS) if i not in used]
            if not free:
                self.toast("Alle 12 Plätze belegt – erst einen löschen")
                return
            slot = free[0]
            saves_dir().mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, slot_path(slot, "pst"))
            for ext in ("thumb", "hdres"):
                side = src.with_suffix("." + ext)
                if side.exists():
                    shutil.copy2(side, slot_path(slot, ext))
            st = os.stat(slot_path(slot, "pst"))
            self.names[str(slot)] = {"name": src.stem, "mtime": st.st_mtime}
            self.selected_slot = slot
            self.save_store()
            self.fill_saves()
            self.toast(f"Importiert nach Platz {slot + 1}")
        dlg.open(self.win, None, done)

    # -- presets
    def current_preset(self):
        for key in ("original", "hd"):
            if all(self.cfg.get(k) == v for k, v in PRESETS[key].items()):
                return key
        return "custom"

    def sync_preset_row(self):
        if hasattr(self, "preset_row"):
            self.updating = True
            name = self.current_preset()
            self.preset_row.set_active_name(name)
            self.preset_hint.set_text({
                "original": "Originalauflösung, Originalgrafik, Röhrenfernseher mit Scanlines.",
                "hd": "1080p mit HD-Figuren und HD-Landschaft, scharfe Pixel.",
                "custom": "Eigene Mischung – unter Grafik und Bildfilter eingestellt."}[name])
            self.updating = False

    def on_preset(self, row, _p):
        name = row.get_active_name()
        if self.updating or name not in PRESETS:
            if not self.updating:
                self.sync_preset_row()      # "Eigene" is a result, not a choice
            return
        self.cfg.update(PRESETS[name])
        self.updating = True
        for key, widget in self.widgets.items():
            self.apply_widget(key, widget)
        self.updating = False
        self.sync_preset_row()
        self.save_store()
        self.refresh_summary()

    def apply_widget(self, key, widget):
        value = self.cfg[key]
        if isinstance(widget, Adw.ComboRow):
            widget.set_selected(widget.values.index(value) if value in widget.values else 0)
        elif isinstance(widget, Adw.SwitchRow):
            widget.set_active(bool(value))
        elif isinstance(widget, Gtk.Scale):
            widget.set_value(value * 100)

    # -- settings pages
    def row(self, kind, key, title, subtitle=None, items=None):
        if kind == "combo":
            w = combo(title, subtitle, items, self.cfg[key], lambda v, k=key: self.set(k, v))
            w.values = [v for v, _ in items]
        else:
            w = switch(title, subtitle, self.cfg[key], lambda v, k=key: self.set(k, v))
        self.widgets[key] = w
        return w

    def page_video(self):
        self.widgets = getattr(self, "widgets", {})
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup(title="Bild")
        g.add(self.row("combo", "internal_resolution", "Interne Auflösung",
                       "Wie fein 3D-Landschaft und Figuren gerechnet werden", RESOLUTIONS))
        g.add(self.row("combo", "fullscreen", "Anzeige", None, DISPLAY_MODES))
        g.add(self.row("combo", "window_width", "Fenstergröße", "Nur im Fenstermodus",
                       WINDOW_SIZES))
        g.add(self.row("combo", "aspect_ratio", "Seitenverhältnis", None, ASPECTS))
        g.add(self.row("combo", "vsync", "Bildsynchronisation (VSync)", None, VSYNC))
        page.add(g)

        hd = Adw.PreferencesGroup(title="HD-Grafiken",
                                  description="Hochskalierte Ersatzgrafiken aus dem Texture-Pack")
        hd.add(self.row("switch", "hd_sprites", "HD-Figuren",
                        "Herkules, Gegner, Gegenstände (4× hochskaliert)"))
        hd.add(self.row("switch", "hd_levels", "HD-Landschaft",
                        "Bäume, Boden, Gebäude der Level"))
        page.add(hd)

        t = Adw.PreferencesGroup(title="Texturen")
        t.add(self.row("combo", "texture_filtering", "Texturfilter",
                       "Wie Texturen beim Vergrößern aussehen", TEX_FILTERS))
        t.add(self.row("switch", "antialiasing", "Weiche Bildskalierung",
                       "Aus = scharfe Pixelkanten beim Skalieren auf die Fenstergröße"))
        t.add(self.row("switch", "perspective_texturing", "Perspektivkorrektur",
                       "Verhindert das PS1-typische Verzerren von Bodentexturen"))
        t.add(self.row("switch", "geometry_correction", "Geometriekorrektur (PGXP)",
                       "Gegen wackelnde Polygone – experimentell"))
        page.add(t)
        return page

    def page_filter(self):
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup(title="Bildschirm",
                                 description="Imitiert einen alten Fernseher. Scanlines lassen "
                                             "sich im Spiel mit F6 umschalten.")
        g.add(self.row("combo", "crt_filter", "Farbwiedergabe", None, SCREENS))
        g.add(self.row("switch", "scanlines", "Scanlines", "Dunkle Zeilen wie auf einer Röhre"))
        strength = Adw.ActionRow(title="Stärke der Scanlines")
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 5, 100, 5)
        scale.set_hexpand(True)
        scale.set_size_request(240, -1)
        scale.set_value(self.cfg["scanline_strength"] * 100)
        scale.set_draw_value(True)
        scale.set_format_value_func(lambda _s, v: f"{v:.0f} %")
        scale.connect("value-changed",
                      lambda s: self.set("scanline_strength", round(s.get_value() / 100, 2)))
        strength.add_suffix(scale)
        self.widgets["scanline_strength"] = scale
        g.add(strength)
        page.add(g)
        return page

    def page_system(self):
        page = Adw.PreferencesPage()
        a = Adw.PreferencesGroup(title="Ton")
        a.add(self.row("combo", "frequency", "Ausgabefrequenz", None, AUDIO_FREQS))
        a.add(self.row("switch", "spu_hq", "Hochwertige Tonberechnung",
                       "Genauere Interpolation des Soundchips"))
        page.add(a)
        s = Adw.PreferencesGroup(title="Spiel")
        s.add(self.row("switch", "auto_skip_fmv", "Videos überspringen",
                       "Zwischensequenzen automatisch überspringen"))
        s.add(self.row("switch", "rewind", "Zurückspulen",
                       "Im Spiel mit F8 die letzten Sekunden zurückspulen"))
        page.add(s)
        k = Adw.PreferencesGroup(title="Tasten im Spiel")
        for key, what in [("F7", "Savestate-Menü (speichern / laden)"), ("F8", "Zurückspulen"),
                          ("F6", "Scanlines an/aus"), ("F9 / Tab", "Schneller Vorlauf"),
                          ("Alt+Enter", "Vollbild an/aus"), ("F3 / F4", "Statistik / Inspektor")]:
            r = Adw.ActionRow(title=what)
            lbl = Gtk.Label(label=key)
            lbl.add_css_class("dim-label")
            r.add_suffix(lbl)
            k.add(r)
        page.add(k)
        return page

    def refresh_summary(self):
        if not hasattr(self, "summary"):
            return
        res = dict(RESOLUTIONS)[self.cfg["internal_resolution"]]
        hd = [n for k, n in (("hd_sprites", "HD-Figuren"), ("hd_levels", "HD-Landschaft"))
              if self.cfg[k]]
        start = "Neues Spiel"
        if self.selected_slot is not None:
            st = next((s for s in list_states() if s.slot == self.selected_slot), None)
            start = (self.slot_name(st) if st else None) or f"Platz {self.selected_slot + 1}"
        parts = [start, res, " + ".join(hd) or "Originalgrafik"]
        if self.cfg["scanlines"]:
            parts.append("Scanlines")
        self.summary.set_text(" · ".join(parts))

    # -- start
    def start_game(self):
        if self.game is not None:
            return
        self.play_btn.set_sensitive(False)
        need = [p for p, on in (("sprites", self.cfg["hd_sprites"]), ("levels", self.cfg["hd_levels"]))
                if on and not (self.cfg["hd_sprites"] and self.cfg["hd_levels"])
                and variant_stale(self.build, p)]
        if need:
            self.play_btn.set_label("HD-Pack wird vorbereitet …")

            def work():
                err = None
                try:
                    build_variant(self.build, need[0])
                except (OSError, subprocess.CalledProcessError) as e:
                    err = str(e)
                GLib.idle_add(self.after_prepare, err)
            threading.Thread(target=work, daemon=True).start()
        else:
            self.after_prepare(None)

    def after_prepare(self, err):
        self.play_btn.set_label("Spielen")
        if err:
            self.play_btn.set_sensitive(True)
            self.toast(f"HD-Pack: {err}")
            return False
        pack = pack_for(self.build, self.cfg["hd_sprites"], self.cfg["hd_levels"])
        if pack is not None and not (pack / "replacements").is_dir():
            self.toast(f"Texture-Pack fehlt: {pack}")
            pack = None
        write_settings(self.build, self.cfg)
        write_mod_state(self.build, pack)

        env = dict(os.environ)
        env.pop("PSX_LOAD_SLOT", None)
        if self.selected_slot is not None:
            env["PSX_LOAD_SLOT"] = str(self.selected_slot)
        log = open(self.build / "launcher_last_run.log", "w")
        try:
            self.game = subprocess.Popen([str(self.exe), "--no-launcher"], cwd=self.build,
                                         env=env, stdout=log, stderr=subprocess.STDOUT)
        except OSError as e:
            log.close()
            self.play_btn.set_sensitive(True)
            self.toast(f"Start fehlgeschlagen: {e}")
            return False
        self.started = time.monotonic()
        self.win.set_visible(False)
        threading.Thread(target=self.wait_game, args=(log,), daemon=True).start()
        return False

    def wait_game(self, log):
        code = self.game.wait()
        log.close()
        GLib.idle_add(self.after_game, code)

    def after_game(self, code):
        self.game = None
        self.win.set_visible(True)
        self.win.present()
        self.play_btn.set_sensitive(True)
        self.fill_saves()
        if code != 0:
            tail = (self.build / "launcher_last_run.log").read_text(errors="replace")[-1500:]
            dlg = Adw.AlertDialog(heading=f"Spiel beendet mit Fehler {code}",
                                  body="Letzte Ausgabe (vollständig in "
                                       "launcher_last_run.log):")
            view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.CHAR)
            view.get_buffer().set_text(tail)
            sw = Gtk.ScrolledWindow(min_content_height=220, min_content_width=520, child=view)
            dlg.set_extra_child(sw)
            dlg.add_response("ok", "OK")
            dlg.present(self.win)
        return False


def main():
    ap = argparse.ArgumentParser(description="Hercules Recompiled launcher")
    ap.add_argument("--build", default="build-release",
                    help="build folder with Hercules_Recompiled (default build-release)")
    args, rest = ap.parse_known_args()
    build = Path(args.build)
    if not build.is_absolute():
        build = ROOT / build
    sys.exit(Launcher(build.resolve()).run([sys.argv[0]] + rest))


if __name__ == "__main__":
    main()
