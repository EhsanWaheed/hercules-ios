# Sprite files (`SD1/`, `SD3/`, `SD4/`)

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

## Decoder status (tools/sprites.py)

`sprites.py check` decodes 10696 of 10697 non-empty frames exactly (the cell
stream ends where the next frame starts); the exception is S4.1 frame 1.
`sprites.py dump` writes one RGBA PNG per unique frame plus `meta.json`.

Confirmed/assumed layout:
- frame table entry k (1-based) at file+4+4k: `entry >> 8` = byte offset of
  the frame from file+4 (0 = empty slot); low byte = **palette index**
  (< palette count in 98.9% of frames; 120 outliers flagged in meta.json)
- after the 8-byte run table: `m` u16 palette offsets (from file+4); each
  palette = `20 00 20 00` + 32 colours, colour 0 = transparent
- frame: u8 cell count, s8 X, 6 header bytes, X*6 extra bytes, cells (4 bytes
  each), then the compressed stream for all cells in order
- the draw list (ENGINE1 `func_8003EA78`) starts 2 bytes before the cell
  records: s8 x0, s8 y0 = frame offset from the object position
- cell record: byte 0 size (bits 0-1 width/8-1, bits 2-3 height/8-1 of the
  decoded block; bit 7 = no own pixels), byte 1 drawn size (low nibble
  width/8, high nibble signed height/8), s8 dx, s8 dy in **2-pixel units**
  (cell at x0 + 2*dx, y0 + 2*dy)
- a bit-7 cell draws a sub-rectangle of the last decoded block at
  u = (size & 0xF) * 8, v = ((size >> 4) & 7) * 8 -- one decoded 32x32 block
  acts as a small atlas for several pieces
- pixel bytes: palette index in the low 5 bits

Validation: with this placement all 10536 unique frames assemble with zero
overlapping opaque pixels (the first version, which used dx/dy as 1-pixel
offsets of the following cell and skipped bit-7 cells, produced scrambled
frames). Still open: the 6 bytes per X block and the 4-byte box before the
draw list (likely bounding/hit boxes, used by `func_8004495C`), palette
outliers, animation tables.
