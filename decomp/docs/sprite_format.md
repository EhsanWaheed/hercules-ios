# Sprite files (`SD1/`, `SD3/`, `SD4/`) -- work in progress

All start with the tag `i1.4`. They are loaded by sector number from u16 LBA
tables: ENGINE1 `0x80069E48` (SD1, 80 files), ENGINE3 `0x80061CE8` (SD3, 9),
TITLE `0x800670E4` (SD4, 17).

## Loading (ENGINE1 `func_8003DBA0`, file number 1..80)

Descriptor table `D_8006C64C`, 0x14 bytes per file:

| off  | meaning |
|------|---------|
| 0x04 | n = number of frames (equals u16 at file +4) |
| 0x08 | file size in bytes |
| 0x0C | buffer pointer |
| 0x10 | u16 load state (2 = loading, 3 = loaded, 4 = ready) |

The buffer starts with `(n + 1) * 4` zeroed bytes (a per-frame slot table,
filled on demand), followed by the file data. Frames appear to be uploaded
to VRAM lazily when shown.

## File layout (observed)

| off | type | meaning |
|-----|------|---------|
| 0x00 | char[4] | `i1.4` |
| 0x04 | u16 | n: frame count |
| 0x06 | u16 | m: count of a second table (animations?) |
| 0x08 | u32[n] | frame offsets; byte offset = value >> 8 (low byte 0) |
| ...  | | m-dependent data, then frames |

Frame data seen in S1.6: u32, u16 width, u16 height (32x32), a 16-colour
palette (entry 0 = 0 = transparent), then compressed pixels (~140 bytes for
a 32x32 frame).

## Decompressor: ENGINE1 `func_8003FF1C(src u16*, dst u8*, out_len, dist_sel)`

Read from the asm (not yet run against data). Returns the advanced `src`.
Input is a stream of u16 words; each word carries two control bytes, low
byte first. Processing stops once `dst >= start + out_len`.

Control byte `c`:

| bits | action | bytes written |
|------|--------|---------------|
| `1nnn rrrr` | run of the byte `table8[nnn]` (8-byte table at scratchpad `0x1F800000`) | `r + 3` |
| `011r rrrr` | run of zeros | `r + 4` |
| `010k kkkk` | k literal words follow; each word `w` writes three 5-bit values: `w`, `w >> 6`, `w >> 11` (stored as bytes, upper bits not masked). Then one more word `t`: writes `t` (low byte); if `t & 0x20`: if `t & 0x40` the high byte of `t` is the **next control byte**, else write `t >> 8` as one more value; if not `t & 0x20`: write `t >> 6` and `t >> 11` (3 values in total) | `3k + 1..3` |
| `00dd ddll` | back-reference: distance = byte `D_8006AB3B[dist_sel + (c & 0xFC)]`, copy `l + 3` bytes from `dst - distance` (byte by byte, overlap allowed) | `l + 3` |

`dist_sel` = `s4 >> 1` in the caller, where `s4` is derived from the cell
width, so the distance table (4 interleaved byte tables, 16 entries each)
depends on the row width -- back-references can point at the row above.
Values are 5-bit (0..31), so the output is likely an index image into a
32-entry palette, or 4-bit data plus a flag bit; to be confirmed.

## Frame structure (from caller `func_8003F9D4`)

`func_8003F9D4(cells, cell_count, flags)`: a frame is a list of
`cell_count` 4-byte cell descriptors followed directly by the data stream
(`stream = cells + 4 * cell_count`). Each cell gets a slot in a VRAM cache
(slot table `D_80072D34`, 12 bytes per slot, 0x54 slots; LRU-style
search starting at `gp+0x58`). Descriptor byte 0: bit 7 set = skip/reuse;
bits 1 and 2 (`(b >> 1) & 1`, `(b >> 2) & 2`) give a size class 0..3
(3 = special). A cell is either copied raw (rows of `2 * s4` halfwords) or,
when `s4 * rows * 8` bytes are needed, decompressed with `func_8003FF1C`.

Open points:
- who fills the 8-byte run table at `0x1F800000` (no direct writer found in
  ENGINE1 with the usual `lui 0x1F80` pattern; maybe copied from the file)
- exact cell descriptor layout (size, VRAM placement, palette)
- how the 5-bit output values map to pixels/palette
