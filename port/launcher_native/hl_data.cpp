// Disc reading and art decoding for the Hercules launcher (see hl_data.h).
#include "hl_data.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <regex>
#include <set>

namespace hl {

// ------------------------------------------------------------------- Image
Image Image::crop(int x0, int y0, int x1, int y1) const {
    x0 = std::max(0, x0); y0 = std::max(0, y0);
    x1 = std::min(w, x1); y1 = std::min(h, y1);
    Image o = make(std::max(0, x1 - x0), std::max(0, y1 - y0));
    for (int y = 0; y < o.h; ++y)
        std::memcpy(o.at(0, y), at(x0, y0 + y), size_t(o.w) * 4);
    return o;
}

Image Image::crop_alpha() const {
    int x0 = w, y0 = h, x1 = -1, y1 = -1;
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x)
            if (at(x, y)[3]) {
                x0 = std::min(x0, x); x1 = std::max(x1, x);
                y0 = std::min(y0, y); y1 = std::max(y1, y);
            }
    if (x1 < 0) return *this;
    return crop(x0, y0, x1 + 1, y1 + 1);
}

// -------------------------------------------------------------------- Disc
static uint32_t le32(const uint8_t* p) { return p[0] | p[1] << 8 | p[2] << 16 | uint32_t(p[3]) << 24; }
static uint16_t le16(const uint8_t* p) { return uint16_t(p[0] | p[1] << 8); }

bool Disc::open(const std::filesystem::path& path, std::string* error) {
    std::filesystem::path bin = path;
    std::string ext = path.extension().string();
    std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
    if (ext == ".cue") {
        std::ifstream cue(path);
        std::string text((std::istreambuf_iterator<char>(cue)), {});
        std::smatch m;
        if (!std::regex_search(text, m, std::regex("FILE\\s+\"([^\"]+)\""))) {
            if (error) *error = "no FILE line in the cue sheet";
            return false;
        }
        bin = path.parent_path() / std::filesystem::u8path(m[1].str());
        if (std::regex_search(text, std::regex("MODE1/2352"))) { sector_size_ = 2352; data_offset_ = 16; }
        else if (std::regex_search(text, std::regex("MODE1/2048"))) { sector_size_ = 2048; data_offset_ = 0; }
    } else if (ext == ".iso") {
        sector_size_ = 2048; data_offset_ = 0;
    }
    std::FILE* f = nullptr;
#ifdef _WIN32
    f = _wfopen(bin.wstring().c_str(), L"rb");
#else
    f = std::fopen(bin.string().c_str(), "rb");
#endif
    if (!f) {
        if (error) *error = "cannot open " + bin.u8string();
        return false;
    }
    f_.reset(f, std::fclose);
    uint8_t pvd[2048];
    if (!sector(16, pvd) || std::memcmp(pvd + 1, "CD001", 5) != 0) {
        if (error) *error = "no ISO 9660 volume on the disc image";
        return false;
    }
    files_.clear();
    walk(le32(pvd + 156 + 2), le32(pvd + 156 + 10), "", 0);
    return !files_.empty();
}

bool Disc::sector(uint32_t lba, uint8_t* out) const {
    if (!f_) return false;
#ifdef _WIN32
    if (_fseeki64(f_.get(), int64_t(lba) * sector_size_ + data_offset_, SEEK_SET) != 0) return false;
#else
    if (fseeko(f_.get(), off_t(lba) * sector_size_ + data_offset_, SEEK_SET) != 0) return false;
#endif
    return std::fread(out, 1, 2048, f_.get()) == 2048;
}

void Disc::walk(uint32_t lba, uint32_t size, const std::string& prefix, int depth) {
    if (depth > 8) return;
    std::vector<uint8_t> buf((size + 2047) / 2048 * 2048);
    for (uint32_t i = 0; i < buf.size() / 2048; ++i)
        if (!sector(lba + i, &buf[i * 2048])) return;
    for (size_t pos = 0; pos < buf.size();) {
        const uint8_t n = buf[pos];
        if (n == 0) { pos = (pos / 2048 + 1) * 2048; continue; }
        const uint8_t* r = &buf[pos];
        const uint8_t nlen = r[32];
        std::string name(reinterpret_cast<const char*>(r + 33), nlen);
        if (name != std::string(1, '\0') && name != std::string(1, '\1')) {
            name = name.substr(0, name.find(';'));
            if (r[25] & 2) walk(le32(r + 2), le32(r + 10), prefix + name + "/", depth + 1);
            else files_[prefix + name] = {le32(r + 2), le32(r + 10)};
        }
        pos += n;
    }
}

bool Disc::read(const std::string& path, std::vector<uint8_t>& out) const {
    auto it = files_.find(path);
    if (it == files_.end()) return false;
    const uint32_t n = (it->second.size + 2047) / 2048;
    out.resize(size_t(n) * 2048);
    for (uint32_t i = 0; i < n; ++i)
        if (!sector(it->second.lba + i, &out[size_t(i) * 2048])) return false;
    out.resize(it->second.size);
    return true;
}

std::vector<std::string> Disc::list(const std::string& dir) const {
    std::vector<std::string> out;
    const std::string pre = dir.empty() ? "" : dir + "/";
    for (const auto& [p, e] : files_)
        if (p.rfind(pre, 0) == 0 && p.find('/', pre.size()) == std::string::npos)
            out.push_back(p.substr(pre.size()));
    return out;
}

// ------------------------------------------------------------- full-screen
static uint8_t expand5(unsigned v) { return uint8_t((v << 3) | (v >> 2)); }

std::vector<Image> decode_fullscreen(const std::vector<uint8_t>& blob) {
    std::vector<Image> out;
    size_t off = 0;
    while (off + 18 <= blob.size()) {
        const int w = le16(&blob[off + 12]), h = le16(&blob[off + 14]);
        const size_t size = size_t(w) * h * 2;
        if (!w || !h || off + 18 + size > blob.size()) break;
        Image img = Image::make(w, h);
        const uint8_t* p = &blob[off + 18];
        for (int i = 0; i < w * h; ++i) {
            const unsigned c = le16(p + 2 * i);
            uint8_t* d = &img.rgba[size_t(i) * 4];
            d[0] = expand5(c & 31); d[1] = expand5((c >> 5) & 31); d[2] = expand5((c >> 10) & 31); d[3] = 255;
        }
        out.push_back(std::move(img));
        off += 18 + size;
    }
    return out;
}

// ----------------------------------------------------------------- sprites
// Port of hercules/tools/sprites.py (ENGINE1 func_8003FF1C and the cell
// handling of func_8003F9D4 / func_8003EA78).
namespace {
constexpr uint32_t ENGINE1_BASE = 0x80038350, DIST_TABLE = 0x8006AB3B;

struct Decoder {
    const std::vector<uint8_t>& data;
    const uint8_t* dist;
    const uint8_t* run;
    size_t pos;
    std::vector<uint8_t> out;
    size_t out_len;
    int dist_sel;
    bool bad = false;

    unsigned word() {
        if (pos + 2 > data.size()) { bad = true; return 0; }
        const unsigned w = data[pos] | data[pos + 1] << 8;
        pos += 2;
        return w;
    }
    void put(unsigned v) { out.push_back(uint8_t(v & 0xFF)); }
    int control(unsigned c) {                    // returns next control byte or -1
        if (c & 0x80) {
            const unsigned v = run[(c >> 4) & 7];
            for (unsigned k = 0; k < (c & 0xF) + 3; ++k) put(v);
        } else if (c & 0x40) {
            if (c & 0x20) {
                for (unsigned k = 0; k < (c & 0x1F) + 4; ++k) put(0);
            } else {
                for (unsigned k = 0; k < (c & 0x1F); ++k) {
                    const unsigned w = word();
                    put(w); put(w >> 6); put(w >> 11);
                }
                const unsigned t = word();
                put(t);
                if (t & 0x20) {
                    if (t & 0x40) {
                        if (out.size() < out_len) return int((t >> 8) & 0xFF);
                    } else {
                        put(t >> 8);
                    }
                } else {
                    put(t >> 6); put(t >> 11);
                }
            }
        } else {
            const unsigned d = dist[dist_sel + (c & 0xFC)];
            if (d == 0 || d > out.size()) { bad = true; return -1; }
            const size_t src = out.size() - d;
            for (unsigned k = 0; k < (c & 3) + 3; ++k) out.push_back(out[src + k]);
        }
        return -1;
    }
    void process(int c) {
        while (c >= 0 && !bad) c = control(unsigned(c));
    }
    bool run_all() {
        while (out.size() < out_len && !bad) {
            const unsigned w = word();
            if (bad) break;
            process(int(w & 0xFF));
            if (out.size() >= out_len) break;
            process(int(w >> 8));
        }
        if (out.size() < out_len) bad = true;
        out.resize(out_len);
        return !bad;
    }
};

struct Cell { uint8_t desc[4]; int w, h; bool has_pixels; std::vector<uint8_t> pixels; };
}  // namespace

std::vector<int> SpriteFrames::order() const {
    std::vector<int> o;
    for (const auto& [k, v] : frames) o.push_back(k);
    return o;
}

bool decode_sprites(const std::vector<uint8_t>& data, const std::vector<uint8_t>& engine1,
                    SpriteFrames& out, std::string* error) {
    const size_t doff = DIST_TABLE - ENGINE1_BASE + 0x800;
    if (data.size() < 16 || std::memcmp(data.data(), "i1.4", 4) != 0 || engine1.size() < doff + 0x48) {
        if (error) *error = "not a sprite file";
        return false;
    }
    const uint8_t* dist = &engine1[doff];
    const unsigned n = le16(&data[4]), m = le16(&data[6]);
    std::vector<uint32_t> entries(n);
    for (unsigned k = 0; k < n; ++k) entries[k] = le32(&data[4 + 4 * (k + 1)]);
    const uint8_t* run = &data[8 + 4 * n];
    // palettes: 32 colours each, colour word 0 = transparent
    std::vector<std::array<uint8_t, 128>> pals;
    const size_t table = 16 + 4 * size_t(n);
    for (unsigned i = 0; i < m; ++i) {
        const size_t base = 4 + le16(&data[table + 2 * i]) + 4;
        std::array<uint8_t, 128> p{};
        for (int j = 0; j < 32; ++j) {
            const unsigned c = le16(&data[base + 2 * j]);
            p[j * 4 + 0] = expand5(c & 31); p[j * 4 + 1] = expand5((c >> 5) & 31);
            p[j * 4 + 2] = expand5((c >> 10) & 31); p[j * 4 + 3] = c == 0 ? 0 : 255;
        }
        pals.push_back(p);
    }
    std::set<std::vector<uint8_t>> seen;
    for (unsigned k = 0; k < n; ++k) {
        const uint32_t e = entries[k];
        if (!(e >> 8)) continue;
        const size_t off = 4 + (e >> 8);
        const unsigned pal_index = e & 0xFF;
        const unsigned count = data[off];
        const int extra = int8_t(data[off + 1]);
        const size_t cells_at = off + 8 + 6 * size_t(std::max(extra, 0));
        size_t pos = cells_at + 4 * size_t(count);
        std::vector<Cell> cells;
        bool bad = false;
        for (unsigned i = 0; i < count && !bad; ++i) {
            Cell c{};
            std::memcpy(c.desc, &data[cells_at + 4 * i], 4);
            const uint8_t b = c.desc[0];
            c.w = ((b & 3) + 1) * 8;
            c.h = (((b & 0xC) >> 2) + 1) * 8;
            c.has_pixels = !(b & 0x80);
            if (c.has_pixels) {
                Decoder d{data, dist, run, pos, {}, size_t(c.w) * c.h, (b & 3) + 1};
                if (!d.run_all()) { bad = true; break; }
                c.pixels = std::move(d.out);
                pos = d.pos;
            }
            cells.push_back(std::move(c));
        }
        if (bad) continue;
        std::vector<uint8_t> key(data.begin() + off, data.begin() + pos);
        key.push_back(uint8_t(pal_index));
        if (!seen.insert(key).second) continue;      // same frame as an earlier one
        // assemble (func_8003EA78)
        const auto& pal = pals.empty() ? std::array<uint8_t, 128>{} : pals[pal_index % pals.size()];
        const int x0 = int8_t(data[cells_at - 2]), y0 = int8_t(data[cells_at - 1]);
        struct Piece { int x, y, w, h; const Cell* atlas; int u, v; };
        std::vector<Piece> pieces;
        const Cell* atlas = nullptr;
        for (const Cell& c : cells) {
            const uint8_t size = c.desc[0], dsz = c.desc[1];
            const int dw = (dsz & 0xF) * 8;
            const int dh = ((((dsz >> 4) ^ 8)) - 8) * 8;
            const int x = x0 + 2 * int8_t(c.desc[2]), y = y0 + 2 * int8_t(c.desc[3]);
            int u = 0, v = 0;
            if (c.has_pixels) atlas = &c;
            else { u = (size & 0xF) * 8; v = ((size >> 4) & 7) * 8; }
            if (!atlas || dw <= 0 || dh <= 0) continue;
            const int pw = std::min(dw, atlas->w - u), ph = std::min(dh, atlas->h - v);
            if (pw > 0 && ph > 0) pieces.push_back({x, y, pw, ph, atlas, u, v});
        }
        if (pieces.empty()) continue;
        int xs0 = 1 << 30, ys0 = 1 << 30, xs1 = -(1 << 30), ys1 = -(1 << 30);
        for (const auto& p : pieces) {
            xs0 = std::min(xs0, p.x); ys0 = std::min(ys0, p.y);
            xs1 = std::max(xs1, p.x + p.w); ys1 = std::max(ys1, p.y + p.h);
        }
        Image img = Image::make(xs1 - xs0, ys1 - ys0);
        for (const auto& p : pieces)
            for (int yy = 0; yy < p.h; ++yy)
                for (int xx = 0; xx < p.w; ++xx) {
                    const unsigned idx = p.atlas->pixels[size_t(p.v + yy) * p.atlas->w + p.u + xx] & 0x1F;
                    if (!idx) continue;
                    std::memcpy(img.at(p.x - xs0 + xx, p.y - ys0 + yy), &pal[idx * 4], 4);
                }
        out.frames[int(k + 1)] = std::move(img);
    }
    return true;
}

// -------------------------------------------------------------------- font
// Port of build_assets.py font(): letters cut from the HUD page, the rest
// (V X Y Q, digits, accents, punctuation, pad symbols) drawn in their style.
namespace {
using Px = std::array<uint8_t, 4>;

struct Glyph {
    int w = 0, h = 0;
    std::vector<Px> px;
    Px& at(int x, int y) { return px[size_t(y) * w + x]; }
    const Px& at(int x, int y) const { return px[size_t(y) * w + x]; }
    static Glyph blank(int w, int h) { Glyph g; g.w = w; g.h = h; g.px.assign(size_t(w) * h, Px{0, 0, 0, 0}); return g; }
};

int round_half_even(double v) { return int(std::nearbyint(v)); }
}  // namespace

bool build_font(const std::vector<uint8_t>& stp, Font& font, std::string* error) {
    if (stp.size() < 64 * 2 * 96) { if (error) *error = "HUD strip too short"; return false; }
    auto word = [&](int x, int y) { return unsigned(le16(&stp[(size_t(y) * 64 + x) * 2])); };
    // 4-bit texels of rows 0..95 (256 wide), palettes at words x 32..47, rows 32..39
    constexpr int PW = 256, PH = 96;
    std::vector<uint8_t> idx(PW * PH);
    for (int y = 0; y < PH; ++y)
        for (int x = 0; x < 64; ++x) {
            const unsigned w = word(x, y);
            for (int i = 0; i < 4; ++i) idx[size_t(y) * PW + x * 4 + i] = (w >> (4 * i)) & 15;
        }
    auto clut = [&](int p, int i) { return word(32 + i, 32 + p); };
    auto colour = [&](int p, int i) {
        const unsigned c = clut(p, i);
        return Px{expand5(c & 31), expand5((c >> 5) & 31), expand5((c >> 10) & 31), uint8_t(c == 0 ? 0 : 255)};
    };
    auto mask = [&](int x, int y) { return clut(3, idx[size_t(y) * PW + x]) != 0; };

    auto segment = [&](int y0, int y1, int x0, int x1) {
        std::vector<std::pair<int, int>> boxes;
        int start = -1;
        for (int x = x0; x <= x1; ++x) {
            bool on = false;
            if (x < x1) for (int y = y0; y < y1; ++y) on |= mask(x, y);
            if (on && start < 0) start = x;
            else if (!on && start >= 0) { boxes.push_back({start, x}); start = -1; }
        }
        return boxes;
    };
    auto band = [&](int x0, int x1, int yf, int yt) {
        int a = -1, b = -1;
        for (int y = yf; y < yt; ++y) {
            bool on = false;
            for (int x = x0; x < x1; ++x) on |= mask(x, y);
            if (on) { if (a < 0) a = y; b = y; }
        }
        return std::pair<int, int>{a, b + 1};
    };

    struct Box { int x0, y0, x1, y1; };
    std::map<char32_t, Box> boxes;
    const struct { const char32_t* text; int yf, yt, xr; } rows[] = {
        {U"ABCDEFGHIJKL?", 42, 59, 232}, {U"MNOPRSTUWZ1", 59, 76, 238}};
    for (const auto& r : rows) {
        const auto [y0, y1] = band(96, r.xr, r.yf, r.yt);
        std::vector<std::pair<int, int>> bs;
        for (auto b : segment(y0, y1, 96, r.xr)) if (b.second - b.first >= 3) bs.push_back(b);
        const size_t want = std::char_traits<char32_t>::length(r.text);
        while (bs.size() < want) {                 // touching letters: split the widest
            size_t i = 0;
            for (size_t k = 1; k < bs.size(); ++k)
                if (bs[k].second - bs[k].first > bs[i].second - bs[i].first) i = k;
            const auto [a, b] = bs[i];
            int best = -1, cut = a + 4;
            for (int x = a + 4; x < b - 4; ++x) {
                int ink = 0;
                for (int y = y0; y < y1; ++y) ink += mask(x, y);
                if (best < 0 || ink < best) { best = ink; cut = x; }
            }
            bs.erase(bs.begin() + long(i));
            bs.insert(bs.begin() + long(i), {{a, cut}, {cut + 1, b}});
        }
        if (bs.size() != want) { if (error) *error = "font: unexpected glyph count"; return false; }
        for (size_t i = 0; i < want; ++i) boxes[r.text[i]] = {bs[i].first, y0, bs[i].second, y1};
    }
    int height = 0;
    for (const auto& [c, b] : boxes) height = std::max(height, b.y1 - b.y0);
    const int TOP = 6, BOT = 3, H = TOP + height + BOT;

    auto build = [&](int palette) {
        std::map<char32_t, Glyph> g;
        for (const auto& [ch, b] : boxes) {
            Glyph gl = Glyph::blank(b.x1 - b.x0, H);
            const int bh = b.y1 - b.y0;
            for (int y = 0; y < bh; ++y)
                for (int x = 0; x < gl.w; ++x)
                    gl.at(x, H - BOT - bh + y) = colour(palette, idx[size_t(b.y0 + y) * PW + b.x0 + x]);
            g[ch] = gl;
        }
        const Glyph& A = g[U'A'];
        int top = -1, bottom = -1;
        for (int y = 0; y < H; ++y)
            for (int x = 0; x < A.w; ++x)
                if (A.at(x, y)[3]) { if (top < 0) top = y; bottom = y; }
        const int mid = (top + bottom) / 2;
        Px fill{};
        for (int x = 0; x < A.w; ++x) if (A.at(x, bottom)[3]) { fill = A.at(x, bottom); break; }
        std::map<uint32_t, int> counts;
        for (const Px& p : A.px)
            if (p[3]) counts[p[0] | p[1] << 8 | p[2] << 16 | uint32_t(p[3]) << 24]++;
        std::vector<std::pair<uint32_t, int>> cs(counts.begin(), counts.end());
        std::stable_sort(cs.begin(), cs.end(), [](auto& a, auto& b) { return a.second > b.second; });
        Px face{};
        int best = -1;
        for (size_t i = 0; i < cs.size() && i < 4; ++i) {
            const uint32_t k = cs[i].first;
            const int l = int(k & 255) * 3 + int((k >> 8) & 255) * 6 + int((k >> 16) & 255);
            if (l > best) { best = l; face = Px{uint8_t(k), uint8_t(k >> 8), uint8_t(k >> 16), uint8_t(k >> 24)}; }
        }

        auto paint = [&](const std::vector<uint8_t>& m, int w) {
            Glyph G = Glyph::blank(w, H);
            for (int y = 0; y < H; ++y)
                for (int x = 0; x < w; ++x) {
                    bool edge = false;               // np.roll dilation (wraps around)
                    for (int oy = -1; oy <= 1 && !edge; ++oy)
                        for (int ox = -1; ox <= 1 && !edge; ++ox)
                            edge = m[size_t((y - oy + H) % H) * w + (x - ox + w) % w];
                    if (m[size_t(y) * w + x]) G.at(x, y) = face;
                    else if (edge) G.at(x, y) = fill;
                }
            return G;
        };
        using Line = std::vector<std::pair<double, double>>;
        auto stroke = [&](int w, const std::vector<Line>& lines, int t = 3, int y0 = -1000, int y1 = -1000) {
            const int r0 = -(t / 2), r1 = t - t / 2;
            if (y0 == -1000) y0 = top - r0;
            if (y1 == -1000) y1 = bottom - r1 + 1;
            const double xa_ = 1 - r0, xb_ = w - 1 - r1;
            std::vector<uint8_t> m(size_t(w) * H, 0);
            for (const Line& line : lines) {
                std::vector<std::pair<double, double>> pts;
                for (auto [u, v] : line) pts.push_back({xa_ + (xb_ - xa_) * u, y0 + (y1 - y0) * v});
                for (size_t s = 0; s + 1 < pts.size(); ++s) {
                    const auto [xa, ya] = pts[s];
                    const auto [xb, yb] = pts[s + 1];
                    const int n = int(std::max(std::fabs(xb - xa), std::fabs(yb - ya)) * 3) + 1;
                    for (int i = 0; i < n; ++i) {
                        const double tt = n > 1 ? double(i) / (n - 1) : 0.0;
                        const double cx = xa + (xb - xa) * tt, cy = ya + (yb - ya) * tt;
                        for (int oy = r0; oy < r1; ++oy)
                            for (int ox = r0; ox < r1; ++ox) {
                                const int yy = round_half_even(cy + oy), xx = round_half_even(cx + ox);
                                if (yy >= 0 && yy < H && xx >= 0 && xx < w) m[size_t(yy) * w + xx] = 1;
                            }
                    }
                }
            }
            return paint(m, w);
        };
        auto marks = [&](int w, const std::vector<std::pair<int, int>>& pts) {
            std::vector<uint8_t> m(size_t(w) * H, 0);
            for (auto [yy, xx] : pts)
                if (yy >= 0 && yy < H && xx >= 0 && xx < w) m[size_t(yy) * w + xx] = 1;
            return paint(m, w);
        };
        auto pmax = [](Glyph a, const Glyph& b) {
            for (size_t i = 0; i < a.px.size(); ++i)
                for (int c = 0; c < 4; ++c) a.px[i][c] = std::max(a.px[i][c], b.px[i][c]);
            return a;
        };
        auto roll_rows = [&](const Glyph& s, int shift) {
            Glyph o = Glyph::blank(s.w, H);
            for (int y = 0; y < H; ++y)
                for (int x = 0; x < s.w; ++x) o.at(x, ((y + shift) % H + H) % H) = s.at(x, y);
            return o;
        };
        auto flip = [&](const Glyph& s, bool fx, bool fy) {
            Glyph o = Glyph::blank(s.w, H);
            for (int y = 0; y < H; ++y)
                for (int x = 0; x < s.w; ++x) o.at(x, y) = s.at(fx ? s.w - 1 - x : x, fy ? H - 1 - y : y);
            return o;
        };

        const int w = A.w;
        g[U'V'] = stroke(w, {{{0, 0}, {0.5, 1}, {1, 0}}});
        g[U'X'] = stroke(w, {{{0, 0}, {1, 1}}, {{1, 0}, {0, 1}}});
        g[U'Y'] = stroke(w, {{{0, 0}, {0.5, 0.5}, {1, 0}}, {{0.5, 0.5}, {0.5, 1}}});
        const int aw = w - 2;
        g[U'<'] = stroke(aw, {{{1, 0.1}, {0, 0.5}, {1, 0.9}}});
        g[U'>'] = stroke(aw, {{{0, 0.1}, {1, 0.5}, {0, 0.9}}});
        g[U'/'] = stroke(aw, {{{1, 0}, {0, 1}}});
        {
            const Glyph& O = g[U'O'];
            Glyph Q = O;
            for (int y = bottom - 3; y <= bottom; ++y)
                for (int i = 0; i < 5; ++i) {
                    Px& d = Q.at(O.w - 5 + i, y);
                    const Px& s = O.at(4 - i, y);
                    for (int c = 0; c < 4; ++c) d[c] = std::max(d[c], s[c]);
                }
            g[U'Q'] = Q;
        }
        const double c = 0.25;
        const Line box = {{c, 0}, {1 - c, 0}, {1, c}, {1, 1 - c}, {1 - c, 1}, {c, 1}, {0, 1 - c}, {0, c}, {c, 0}};
        const std::map<char32_t, std::vector<Line>> digits = {
            {U'0', {box}},
            {U'1', {{{0.15, 0.25}, {0.55, 0}}, {{0.55, 0}, {0.55, 1}}, {{0.15, 1}, {0.95, 1}}}},
            {U'2', {{{0, c}, {c, 0}, {1 - c, 0}, {1, c}, {1, 0.35}, {0, 1}, {1, 1}}}},
            {U'3', {{{0, 0}, {1, 0}, {0.4, 0.42}, {1 - c, 0.42}, {1, 0.42 + c}, {1, 1 - c}, {1 - c, 1}, {0, 1}}}},
            {U'4', {{{0.75, 1}, {0.75, 0}, {0, 0.68}, {1, 0.68}}}},
            {U'5', {{{1, 0}, {0, 0}, {0, 0.42}, {1 - c, 0.42}, {1, 0.42 + c}, {1, 1 - c}, {1 - c, 1}, {0, 1}}}},
            {U'6', {{{1, 0}, {c, 0}, {0, c}, {0, 1 - c}, {c, 1}, {1 - c, 1}, {1, 1 - c}, {1, 0.45 + c},
                     {1 - c, 0.45}, {0, 0.45}}}},
            {U'7', {{{0, 0}, {1, 0}, {0.3, 1}}}},
            {U'8', {{{c, 0.45}, {0, 0.45 - c}, {0, c}, {c, 0}, {1 - c, 0}, {1, c}, {1, 0.45 - c}, {1 - c, 0.45},
                     {c, 0.45}, {0, 0.45 + c}, {0, 1 - c}, {c, 1}, {1 - c, 1}, {1, 1 - c}, {1, 0.45 + c},
                     {1 - c, 0.45}}}},
            {U'9', {{{0, 1}, {1 - c, 1}, {1, 1 - c}, {1, c}, {1 - c, 0}, {c, 0}, {0, c}, {0, 0.55 - c},
                     {c, 0.55}, {1, 0.55}}}},
        };
        for (const auto& [d, lines] : digits) g[d] = stroke(w, lines, 2);

        g[U' '] = Glyph::blank(9, H);
        const std::vector<std::pair<int, int>> dot = {{bottom - 1, 1}, {bottom - 1, 2}, {bottom, 1}, {bottom, 2}};
        auto plus = [](std::vector<std::pair<int, int>> a, const std::vector<std::pair<int, int>>& b) {
            a.insert(a.end(), b.begin(), b.end());
            return a;
        };
        g[U'.'] = marks(4, dot);
        g[U','] = marks(5, plus(dot, {{bottom + 1, 2}, {bottom + 2, 1}}));
        g[U':'] = marks(4, plus(dot, {{mid - 2, 1}, {mid - 2, 2}, {mid - 1, 1}, {mid - 1, 2}}));
        g[U'\''] = marks(4, {{top, 1}, {top, 2}, {top + 1, 1}, {top + 1, 2}, {top + 2, 1}});
        {
            std::vector<std::pair<int, int>> bar;
            for (int y = top; y < bottom - 3; ++y) { bar.push_back({y, 1}); bar.push_back({y, 2}); }
            g[U'!'] = marks(4, plus(dot, bar));
        }
        const int shift = (top + bottom) - (H - 1);
        g[U'¡'] = roll_rows(flip(g[U'!'], false, true), shift);
        g[U'¿'] = roll_rows(flip(g[U'?'], true, true), shift);
        {
            std::vector<std::pair<int, int>> p;
            for (int x = 1; x < 6; ++x) p.push_back({mid, x});
            g[U'-'] = marks(7, p);
        }
        {
            auto ring = [](int y0, int x0) {
                return std::vector<std::pair<int, int>>{{y0, x0}, {y0, x0 + 1}, {y0 + 1, x0}, {y0 + 1, x0 + 1}};
            };
            g[U'%'] = pmax(stroke(w, {{{1, 0.05}, {0, 0.95}}}, 1), marks(w, plus(ring(top + 1, 2), ring(bottom - 2, w - 4))));
        }
        {
            std::vector<std::pair<int, int>> p;
            for (int x = 1; x < 8; ++x) p.push_back({mid, x});
            for (int y = mid - 3; y < mid + 4; ++y) p.push_back({y, 4});
            g[U'+'] = marks(9, p);
        }
        g[U'△'] = stroke(w, {{{0.5, 0}, {1, 1}, {0, 1}, {0.5, 0}}}, 1);
        g[U'□'] = stroke(w, {{{0.08, 0.08}, {0.92, 0.08}, {0.92, 1}, {0.08, 1}, {0.08, 0.08}}}, 1);
        g[U'○'] = stroke(w, {{{0.3, 0}, {0.7, 0}, {1, 0.3}, {1, 0.7}, {0.7, 1}, {0.3, 1}, {0, 0.7}, {0, 0.3}, {0.3, 0}}}, 1);

        const std::map<std::string, std::vector<std::pair<int, int>>> ACC = {
            {"acute", {{0, 3}, {0, 4}, {1, 2}, {1, 3}, {2, 1}, {2, 2}}},
            {"grave", {{0, 1}, {0, 2}, {1, 2}, {1, 3}, {2, 3}, {2, 4}}},
            {"circ", {{0, 2}, {0, 3}, {1, 1}, {1, 4}, {2, 0}, {2, 5}}},
            {"tilde", {{1, 1}, {1, 2}, {1, 5}, {2, 0}, {2, 3}, {2, 4}}},
        };
        auto accent = [&](char32_t base, const std::string& kind) {
            Glyph G = g[base];
            const int bw = G.w;
            if (kind == "uml") {
                for (int dx : {bw / 3 - 1, 2 * bw / 3 - 1})
                    for (int y = top - 4; y < top - 2; ++y)
                        for (int x = dx; x < dx + 3; ++x) {
                            if (x < 0 || x >= bw || y < 0) continue;
                            G.at(x, y) = (y == top - 4 && x == dx + 1) ? face : fill;
                        }
                return G;
            }
            const auto& pts = ACC.at(kind);
            int mw = 0;
            for (auto [yy, xx] : pts) mw = std::max(mw, xx);
            mw += 3;
            const int wd = std::max(bw, mw);
            Glyph out = Glyph::blank(wd, H);
            const int ox = (wd - bw) / 2;
            for (int y = 0; y < H; ++y)
                for (int x = 0; x < bw; ++x) out.at(ox + x, y) = G.at(x, y);
            const int m0 = (wd - mw) / 2 + 1;
            std::vector<std::pair<int, int>> mp;
            for (auto [yy, xx] : pts) mp.push_back({top - 5 + yy, m0 + xx});
            const Glyph mk = marks(wd, mp);
            for (size_t i = 0; i < out.px.size(); ++i) if (mk.px[i][3]) out.px[i] = mk.px[i];
            return out;
        };
        const struct { char32_t ch, base; const char* kind; } accented[] = {
            {U'Ä', U'A', "uml"}, {U'Ö', U'O', "uml"}, {U'Ü', U'U', "uml"}, {U'Ë', U'E', "uml"}, {U'Ï', U'I', "uml"},
            {U'Á', U'A', "acute"}, {U'É', U'E', "acute"}, {U'Í', U'I', "acute"}, {U'Ó', U'O', "acute"}, {U'Ú', U'U', "acute"},
            {U'À', U'A', "grave"}, {U'È', U'E', "grave"}, {U'Ì', U'I', "grave"}, {U'Ò', U'O', "grave"}, {U'Ù', U'U', "grave"},
            {U'Â', U'A', "circ"}, {U'Ê', U'E', "circ"}, {U'Î', U'I', "circ"}, {U'Ô', U'O', "circ"}, {U'Û', U'U', "circ"},
            {U'Ñ', U'N', "tilde"}};
        for (const auto& a : accented) g[a.ch] = accent(a.base, a.kind);
        {
            Glyph C = g[U'C'];
            const int cx = C.w / 2;
            const Glyph ced = marks(C.w, {{bottom + 1, cx}, {bottom + 2, cx}, {bottom + 2, cx - 1}});
            for (size_t i = 0; i < C.px.size(); ++i) if (ced.px[i][3]) C.px[i] = ced.px[i];
            g[U'Ç'] = C;
        }
        return g;
    };

    const int GAP = 2;
    auto atlas = [&](const std::map<char32_t, Glyph>& g, bool record) {
        int width = GAP;
        for (const auto& [ch, gl] : g) width += gl.w + GAP;
        Image img = Image::make(width, H);
        int x = GAP;
        for (const auto& [ch, gl] : g) {
            for (int y = 0; y < H; ++y)
                for (int xx = 0; xx < gl.w; ++xx) std::memcpy(img.at(x + xx, y), gl.at(xx, y).data(), 4);
            if (record) font.glyphs[ch] = {x, gl.w};
            x += gl.w + GAP;
        }
        return img;
    };
    font.glyphs.clear();
    font.yellow = atlas(build(3), true);
    font.orange = atlas(build(4), false);
    font.blue = font.yellow;                       // recoloured toward the menu blue by luminance
    for (size_t i = 0; i < font.blue.rgba.size(); i += 4) {
        const uint8_t* s = &font.yellow.rgba[i];
        const double lum = (0.3 * s[0] + 0.59 * s[1] + 0.11 * s[2]) / 255.0;
        const double t = std::clamp(lum * 1.25, 0.0, 1.0);
        const int lo[3] = {20, 40, 90}, hi[3] = {0x8C, 0xB9, 0xF3};
        for (int ch = 0; ch < 3; ++ch)
            font.blue.rgba[i + ch] = uint8_t(std::clamp(lo[ch] + (hi[ch] - lo[ch]) * t, 0.0, 255.0));
    }
    font.height = H;
    font.baseline = H - BOT;
    return true;
}

}  // namespace hl
