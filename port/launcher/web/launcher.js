/* Hercules launcher stage: title-menu look of the 1997 game (design.md).
 * Screens: main menu, PASSWÖRTER (start level, Meg's room), OPTIONEN,
 * SPIEL LADEN. Talks to hercules_launcher.py through the WebKit message
 * handler "herc"; without it (plain browser) it runs on demo data. */
"use strict";

const A = window.HERC_ASSETS;
const W = 320, H = 256;
const scene = document.getElementById("scene");
const stage = document.getElementById("stage");

/* ------------------------------------------------------------------ bridge */
const bridge = (() => {
  const native = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.herc;
  let next = 1;
  const waiting = new Map();
  const listeners = {};
  window.hercBridge = {
    reply(id, data) { const f = waiting.get(id); waiting.delete(id); if (f) f(data); },
    event(name, data) { (listeners[name] || []).forEach(f => f(data)); },
  };
  const demo = {
    cfg: { start_level: "off", internal_resolution: "1080p", aspect_ratio: "16:9", fullscreen: 0,
           vsync: "on", hd_sprites: true, hd_levels: true, hd_hud: true, texture_filtering: "nearest",
           antialiasing: false, perspective_texturing: false, geometry_correction: false,
           crt_sim: false, crt_mask: 0.5, crt_bloom: 0.35, scanlines: false, scanline_strength: 0.35,
           crt_filter: "raw", frequency: 48000, spu_hq: true, auto_skip_fmv: false, rewind: true },
    states: [{ slot: 2, name: "", when: "12.10.2026 20:48", thumb: "" },
             { slot: 1, name: "LEVEL 2 ANFANG", when: "12.10.2026 20:47", thumb: "" }],
    selected_slot: null,
  };
  function call(cmd, args = {}) {
    if (!native) {
      if (cmd === "state") return Promise.resolve(JSON.parse(JSON.stringify(demo)));
      if (cmd === "set") { demo.cfg[args.key] = args.value; return Promise.resolve({ ok: true }); }
      if (cmd === "delete") { demo.states = demo.states.filter(s => s.slot !== args.slot); return Promise.resolve({ ok: true }); }
      return Promise.resolve({ ok: true, demo: true });
    }
    const id = next++;
    return new Promise(res => {
      waiting.set(id, res);
      native.postMessage(JSON.stringify({ id, cmd, args }));
    });
  }
  return { call, on(name, f) { (listeners[name] = listeners[name] || []).push(f); } };
})();

/* ---------------------------------------------------------------- drawing */
function img(src, x, y, cls) {
  const el = document.createElement("img");
  el.src = "assets/" + src;
  el.alt = "";
  el.style.left = x + "px";
  el.style.top = y + "px";
  if (cls) el.className = cls;
  scene.appendChild(el);
  return el;
}
function bg(key, cls = "bg") { return img(A.bg[key], 0, 0, cls); }

const fontImg = {};
for (const [k, f] of Object.entries(A.font.files)) { const i = new Image(); i.src = "assets/" + f; fontImg[k] = i; }

/* Text in the game's pause-menu font; color: yellow | orange | blue. */
function textWidth(s) {
  let w = 0;
  for (const ch of s.toUpperCase()) { const g = A.font.glyphs[ch] || A.font.glyphs[" "]; w += g[1] + 1; }
  return Math.max(0, w - 1);
}
function text(s, x, y, color = "yellow", align = "left") {
  s = s.toUpperCase();
  const w = textWidth(s), h = A.font.height;
  const c = document.createElement("canvas");
  c.width = Math.max(1, w); c.height = h;
  const draw = () => {
    const g2 = c.getContext("2d");
    g2.imageSmoothingEnabled = false;
    let cx = 0;
    for (const ch of s) {
      const g = A.font.glyphs[ch] || A.font.glyphs[" "];
      g2.drawImage(fontImg[color], g[0], 0, g[1], h, cx, 0, g[1], h);
      cx += g[1] + 1;
    }
  };
  fontImg[color].complete ? draw() : fontImg[color].addEventListener("load", draw, { once: true });
  c.style.left = (align === "center" ? Math.round(x - w / 2) : align === "right" ? x - w : x) + "px";
  c.style.top = y + "px";
  c.setAttribute("aria-label", s);
  scene.appendChild(c);
  return c;
}
function hit(x, y, w, h, onHover, onClick, label) {
  const d = document.createElement("div");
  d.className = "hit";
  Object.assign(d.style, { left: x + "px", top: y + "px", width: w + "px", height: h + "px" });
  if (label) { d.setAttribute("role", "button"); d.setAttribute("aria-label", label); }
  d.addEventListener("mouseenter", onHover);
  d.addEventListener("click", onClick);
  scene.appendChild(d);
  return d;
}
function centered(src, y) {
  const i = img(src, 0, y);
  const place = () => { i.style.left = Math.round((W - i.naturalWidth) / 2) + "px"; };
  i.complete ? place() : i.addEventListener("load", place, { once: true });
  return i;
}

/* sprite loops at a low, period frame rate */
let timers = [];
function animate(el, frames, fps = 8) {
  let n = 0;
  const t = setInterval(() => { n = (n + 1) % frames.length; el.src = "assets/" + frames[n]; }, 1000 / fps);
  timers.push(t);
}
function clear() {
  timers.forEach(clearInterval); timers = [];
  scene.textContent = "";
}

function fit() {
  const r = stage.getBoundingClientRect();
  scene.style.transform = `scale(${r.width / W}, ${r.height / H})`;
}
window.addEventListener("resize", fit);

/* ------------------------------------------------------------------ state */
let S = null;                 // {cfg, states, selected_slot, ...} from Python
let screen = null;            // current screen object {render, key}
const history = [];

function go(next, push = true) {
  if (push && screen) history.push(screen);
  screen = next;
  render();
}
function back() { if (history.length) { screen = history.pop(); render(); } }
function render() { clear(); screen.render(); fit(); }
async function set(key, value) { S.cfg[key] = value; await bridge.call("set", { key, value }); }

/* ------------------------------------------------------------- main menu */
const MENU = ["SPIEL STARTEN", "PASSWÖRTER", "OPTIONEN", "SPIEL LADEN"];
const mainMenu = {
  sel: 0,
  render() {
    bg("menu");
    const left = img(A.sprite.muse_a[0], 6, 100), left2 = img(A.sprite.muse_b[0], 40, 104);
    const right = img(A.sprite.muse_c[0], 258, 100), right2 = img(A.sprite.muse_a[3], 224, 104);
    right2.style.transform = "scaleX(-1)";
    animate(left, A.sprite.muse_a, 7); animate(left2, A.sprite.muse_b, 6);
    animate(right, A.sprite.muse_c, 7); animate(right2, A.sprite.muse_a, 5);
    img(A.sprite.menu[this.sel], 52, 98);
    MENU.forEach((label, i) => hit(70, 98 + i * 26, 180, 25,
      () => { if (this.sel !== i) { this.sel = i; render(); } }, () => this.activate(), label));
    if (S.cfg.start_level !== "off" && A.sprite.level_name[S.cfg.start_level])
      centered(A.sprite.level_name[S.cfg.start_level], 6);
  },
  key(k) {
    if (k === "up") { this.sel = (this.sel + 3) % 4; render(); }
    else if (k === "down") { this.sel = (this.sel + 1) % 4; render(); }
    else if (k === "ok") this.activate();
  },
  activate() {
    if (this.sel === 0) play(null);
    else if (this.sel === 1) go(levelScreen);
    else if (this.sel === 2) go(optionsScreen);
    else go(loadScreen);
  },
};

/* --------------------------------------------- PASSWÖRTER: start level */
const LEVELS = ["off", "0", "2", "3", "5", "6", "7", "8", "9", "10", "11"];
const FRESCO = { off: "6", 0: "9", 2: "5", 3: "4", 5: "1", 6: "11", 7: "2", 8: "3", 9: "10", 10: "8", 11: "7" };
const levelScreen = {
  render() {
    bg("room");
    bg("beams", "bg beams");
    const lv = S.cfg.start_level;
    text("WÄHLE DIE EBENE", W / 2, 6, "blue", "center");
    const f = A.fresco[FRESCO[lv]];
    if (f) {
      const fw = 128, fh = 102, fx = (W - fw) / 2, fy = 28;
      const frame = document.createElement("div");
      frame.className = "fresco-frame";
      Object.assign(frame.style, { left: fx + "px", top: fy + "px", width: fw + "px", height: fh + "px" });
      scene.appendChild(frame);
      const p = img(f, fx, fy); p.style.width = fw + "px"; p.style.height = fh + "px";
    }
    const name = A.sprite.level_name[lv === "off" ? "1" : lv];
    if (name) centered(name, 136);
    text(lv === "off" ? "NORMALER START" : "EBENE " + lv, W / 2, 152, "yellow", "center");
    const meg = img(A.sprite.meg[0], 22, 96);
    animate(meg, A.sprite.meg, 6);
    text("<", 84, 72, "blue"); text(">", 228, 72, "blue");
    hit(70, 28, 30, 102, () => {}, () => this.key("left"), "Vorherige Ebene");
    hit(222, 28, 30, 102, () => {}, () => this.key("right"), "Nächste Ebene");
    hit(96, 28, 128, 102, () => {}, () => this.key("ok"), "Spiel in dieser Ebene starten");
    centered(A.sprite.caption.back_help, 238);
  },
  key(k) {
    const i = LEVELS.indexOf(S.cfg.start_level);
    if (k === "left" || k === "right") {
      const n = (i + (k === "left" ? -1 : 1) + LEVELS.length) % LEVELS.length;
      set("start_level", LEVELS[n]).then(render);
    } else if (k === "ok") play(null);
    else if (k === "back") back();
  },
};

/* --------------------------------------------------------------- options */
const onoff = [[true, "AN"], [false, "AUS"]];
const PAGES = [
  ["BILD", [
    ["internal_resolution", "AUFLÖSUNG", [["native", "ORIGINAL"], ["720p", "720P"], ["1080p", "1080P"], ["1440p", "1440P"], ["4k", "4K"]]],
    ["aspect_ratio", "FORMAT", [["4:3", "4 ZU 3"], ["16:9", "16 ZU 9"]]],
    ["fullscreen", "ANZEIGE", [[0, "FENSTER"], [1, "VOLLBILD"], [2, "EXKLUSIV"]]],
    ["vsync", "BILDSYNC", [["on", "AN"], ["adaptive", "ADAPTIV"], ["vrr", "VRR"], ["off", "AUS"]]],
    ["preset", "STIL", [["original", "ALT"], ["hd", "NEU UND HD"], ["custom", "EIGENE"]]],
  ]],
  ["GRAFIK", [
    ["hd_sprites", "HD FIGUREN", onoff],
    ["hd_levels", "HD LANDSCHAFT", onoff],
    ["hd_hud", "HD ANZEIGEN", onoff],
    ["texture_filtering", "TEXTUREN", [["nearest", "SCHARF"], ["bilinear", "WEICH"], ["xbr", "XBR"]]],
    ["antialiasing", "GLÄTTEN", onoff],
    ["perspective_texturing", "PERSPEKTIVE", onoff],
    ["geometry_correction", "GEOMETRIE", onoff],
  ]],
  ["FILTER", [
    ["crt_sim", "RÖHRENBILD", onoff],
    ["crt_mask", "MASKE", [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1].map(v => [v, String(Math.round(v * 100))])],
    ["crt_bloom", "LEUCHTEN", [0, 0.1, 0.2, 0.3, 0.35, 0.4, 0.5, 0.6, 0.8, 1].map(v => [v, String(Math.round(v * 100))])],
    ["scanlines", "ZEILEN", onoff],
    ["scanline_strength", "ZEILENSTÄRKE", [0.1, 0.2, 0.3, 0.35, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1].map(v => [v, String(Math.round(v * 100))])],
    ["crt_filter", "FARBEN", [["raw", "ROH"], ["crt", "RÖHRE"], ["composite", "COMPOSITE"], ["trinitron", "TRINITRON"]]],
  ]],
  ["TON", [
    ["frequency", "FREQUENZ", [[48000, "48000"], [44100, "44100"], [32000, "32000"]]],
    ["spu_hq", "TONQUALITÄT", [[true, "HOCH"], [false, "NORMAL"]]],
    ["auto_skip_fmv", "VIDEOS", [[false, "ZEIGEN"], [true, "ÜBERSPRINGEN"]]],
    ["rewind", "ZURÜCKSPULEN", onoff],
  ]],
];
const optionsScreen = {
  page: 0, row: 0,
  render() {
    bg("plaster");
    const [title, rows] = PAGES[this.page];
    text("OPTIONEN", W / 2, 8, "yellow", "center");
    text("< " + title + " >", W / 2, 32, this.row === 0 ? "blue" : "orange", "center");
    hit(60, 30, 200, 18, () => { this.row = 0; render(); }, () => this.step(1), "Seite " + title);
    rows.forEach(([key, label, choices], i) => {
      const y = 58 + i * 20, active = this.row === i + 1;
      text(label, 20, y, active ? "blue" : "yellow");
      text(this.valueLabel(key, choices), 300, y, active ? "blue" : "orange", "right");
      hit(14, y - 2, 292, 18, () => { if (!active) { this.row = i + 1; render(); } },
          () => { this.row = i + 1; this.step(1); }, label);
    });
    centered(A.sprite.caption.back_help, 238);
  },
  current(key) {
    if (key === "preset") return S.preset || "custom";
    return S.cfg[key];
  },
  valueLabel(key, choices) {
    const v = this.current(key);
    let best = choices[0];
    for (const c of choices) if (c[0] === v) best = c;
    if (typeof v === "number" && !choices.some(c => c[0] === v))
      best = choices.reduce((a, c) => Math.abs(c[0] - v) < Math.abs(a[0] - v) ? c : a);
    return best[1];
  },
  async step(d) {
    if (this.row === 0) {
      this.page = (this.page + d + PAGES.length) % PAGES.length;
      return render();
    }
    const [key, , choices] = PAGES[this.page][1][this.row - 1];
    const v = this.current(key);
    let i = choices.findIndex(c => c[0] === v);
    if (i < 0) i = 0;
    const nv = choices[(i + d + choices.length) % choices.length][0];
    if (key === "preset") {
      if (nv !== "custom") { const r = await bridge.call("preset", { name: nv }); S = r.state || S; }
    } else {
      await set(key, nv);
      S = await bridge.call("state");
    }
    render();
  },
  key(k) {
    const n = PAGES[this.page][1].length + 1;
    if (k === "up") { this.row = (this.row + n - 1) % n; render(); }
    else if (k === "down") { this.row = (this.row + 1) % n; render(); }
    else if (k === "left") this.step(-1);
    else if (k === "right" || k === "ok") this.step(1);
    else if (k === "back") back();
  },
};

/* ------------------------------------------------------------ SPIEL LADEN */
const loadScreen = {
  i: 0, confirm: false, yes: false,
  render() {
    bg("plaster2");
    centered(A.sprite.caption.load, 8);
    const st = S.states;
    if (!st.length) {
      centered(A.sprite.caption.empty, 110);
      centered(A.sprite.caption.back_help, 238);
      return;
    }
    this.i = Math.min(this.i, st.length - 1);
    const show = (k, x, y, w, h, on) => {
      const s = st[k];
      const f = document.createElement("div");
      f.className = "thumb-frame" + (on ? "" : " off");
      Object.assign(f.style, { left: x + "px", top: y + "px", width: w + "px", height: h + "px" });
      scene.appendChild(f);
      if (s.thumb) { const t = img("", x, y); t.src = s.thumb; t.style.width = w + "px"; t.style.height = h + "px"; if (!on) t.style.opacity = 0.55; }
      hit(x, y, w, h, () => {}, () => { if (k === this.i) this.key("ok"); else { this.i = k; render(); } },
          "Spielstand " + (s.name || "Platz " + (s.slot + 1)));
    };
    if (this.i > 0) show(this.i - 1, 12, 74, 64, 48, false);
    if (this.i < st.length - 1) show(this.i + 1, 244, 74, 64, 48, false);
    show(this.i, 96, 50, 128, 96, true);
    const s = st[this.i];
    text(s.name || "PLATZ " + (s.slot + 1), W / 2, 154, "blue", "center");
    text(s.when, W / 2, 172, "yellow", "center");
    text((this.i + 1) + " VON " + st.length, W / 2, 190, "orange", "center");
    centered(A.sprite.caption.load_help, 212);
    if (this.confirm) {
      const d = document.createElement("div"); d.className = "dim"; scene.appendChild(d);
      text("LÖSCHEN?", W / 2, 96, "yellow", "center");
      text("JA", 120, 124, this.yes ? "blue" : "yellow", "center");
      text("NEIN", 200, 124, this.yes ? "yellow" : "blue", "center");
      hit(100, 120, 40, 20, () => { this.yes = true; render(); }, () => this.answer(true), "Ja, löschen");
      hit(176, 120, 48, 20, () => { this.yes = false; render(); }, () => this.answer(false), "Nein");
    }
  },
  async answer(yes) {
    this.confirm = false;
    if (yes) { await bridge.call("delete", { slot: S.states[this.i].slot }); S = await bridge.call("state"); }
    render();
  },
  key(k) {
    if (this.confirm) {
      if (k === "left" || k === "right") { this.yes = !this.yes; render(); }
      else if (k === "ok") this.answer(this.yes);
      else if (k === "back") { this.confirm = false; render(); }
      return;
    }
    const n = S.states.length;
    if (k === "left" && n) { this.i = (this.i + n - 1) % n; render(); }
    else if (k === "right" && n) { this.i = (this.i + 1) % n; render(); }
    else if (k === "ok" && n) play(S.states[this.i].slot);
    else if (k === "delete" && n) { this.confirm = true; this.yes = false; render(); }
    else if (k === "back") back();
  },
};

/* ----------------------------------------------------------- play / wait */
let running = false;
async function play(slot) {
  if (running) return;
  running = true;
  const r = await bridge.call("play", { slot });
  if (!r || !r.ok) { running = false; showMessage((r && r.error) || "START FEHLGESCHLAGEN"); }
}
bridge.on("game_ended", async d => {
  running = false;
  S = await bridge.call("state");
  if (d && d.code) showMessage("SPIEL MIT FEHLER " + d.code + " BEENDET");
  else render();
});
function showMessage(msg) {
  render();
  const d = document.createElement("div"); d.className = "dim"; scene.appendChild(d);
  const words = msg.toUpperCase().replace(/[^A-ZÄÖÜ0-9 .:?<>-]/g, " ").split(/\s+/);
  let line = "", y = 96;
  for (const w of words) {
    if (textWidth(line + " " + w) > 280) { text(line, W / 2, y, "yellow", "center"); y += 18; line = w; }
    else line = line ? line + " " + w : w;
  }
  if (line) text(line, W / 2, y, "yellow", "center");
}

/* ------------------------------------------------------------------ input */
const KEYS = {
  ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right",
  Enter: "ok", " ": "ok", x: "ok", X: "ok",
  Escape: "back", Backspace: "back",
  Delete: "delete", q: "delete", Q: "delete",
};
document.addEventListener("keydown", e => {
  const k = KEYS[e.key];
  if (!k || running) return;
  e.preventDefault();
  dispatch(k);
});
function dispatch(k) { screen.key(k); }
/* gamepad: d-pad / left stick, Cross or Start = ok, Triangle / Circle = back, Square = delete */
let padPrev = {};
function pollPad() {
  const pads = navigator.getGamepads ? navigator.getGamepads() : [];
  for (const p of pads) {
    if (!p) continue;
    const now = {
      up: p.buttons[12]?.pressed || p.axes[1] < -0.6, down: p.buttons[13]?.pressed || p.axes[1] > 0.6,
      left: p.buttons[14]?.pressed || p.axes[0] < -0.6, right: p.buttons[15]?.pressed || p.axes[0] > 0.6,
      ok: p.buttons[0]?.pressed || p.buttons[9]?.pressed, back: p.buttons[3]?.pressed || p.buttons[1]?.pressed,
      delete: p.buttons[2]?.pressed,
    };
    for (const [k, v] of Object.entries(now)) if (v && !padPrev[k] && !running) dispatch(k);
    padPrev = now;
  }
  requestAnimationFrame(pollPad);
}
requestAnimationFrame(pollPad);

/* ------------------------------------------------------------------- boot */
(async () => {
  if (!A) return;
  S = await bridge.call("state");
  screen = mainMenu;
  render();
  fit();
})();
