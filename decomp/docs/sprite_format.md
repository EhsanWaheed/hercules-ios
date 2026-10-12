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

## Decompressor candidate: ENGINE1 `func_8003FF1C(src u16*, dst u8*, len, table_sel)`

LZ/RLE hybrid driven by control bytes (two per u16 read):
- `c & 0x80`: run of `2 + (c & 0xF)` copies of a byte from an 8-entry table
  in the scratchpad (`0x1F800000 + ((c >> 4) & 7)`)
- `c & 0x60 == 0x60`: run of `3 + (c & 0x1F)` zero bytes
- `c & 0x40` (else): `c & 0x1F` literal u16 words, each expanding to 3 bytes
- otherwise: back-reference, distance from table `D_8006AB3B[table_sel + (c & 0xFC)]`,
  length `2 + (c & 3)`

Not yet verified against the data; exact bit layout of the literal words and
the scratchpad byte table setup still to be read from the asm.
