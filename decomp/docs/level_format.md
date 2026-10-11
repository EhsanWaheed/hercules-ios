# Level files (`LV/L*.1`)

Findings from ENGINE1's loader (`func_80039084`) and header parser
(`func_80039848`). Applies to the `i2.x` files; the `i1.a` files (L2, L8, L10)
belong to ENGINE3 and use a different layout (not yet analysed).

## Locating a level

- `SCES_008.93` holds a u16 LBA table at `0x800282F4`: `LV/L0.1` .. `LV/L11.1`,
  followed directly by `OV/OV0` .. `OV/OV11` (one code overlay per level).
- ENGINE1's level table at `0x8006C228`, 28-byte entries indexed by the current
  level (`D_80035048`):

  | off  | meaning                                               |
  |------|-------------------------------------------------------|
  | 0x00 | pointer to the level's u16 LBA in the boot table      |
  | 0x04 | same pointer                                          |
  | 0x08 | bytes to load (equals header field `+0x04`)           |
  | 0x0C | 0                                                     |
  | 0x10 | three pointers above ENGINE1's image (overlay area)   |

  ENGINE1 has entries for levels 0, 1, 3, 4, 5, 6, 7, 9 and 11.

## Loading

1. Allocate `((size >> 11) + 2) << 11` bytes, read `size` bytes from the LBA.
2. Compare the first word (the version tag, e.g. `i2.5`) with the expected value
   in `D_800350D4`; on mismatch the game spins forever.
3. Parse the header (below), upload the VRAM blocks, then shrink the buffer to
   the RAM part: everything from the CLUT block onward is freed after upload.

## Header

All `rel` fields are offsets relative to the field's own position.

| off  | type | meaning                                                         |
|------|------|-----------------------------------------------------------------|
| 0x00 | char[4] | version tag (`i2.5`, `i2.4`)                                 |
| 0x04 | u32  | bytes loaded into RAM (rest of the file is not read here)      |
| 0x14 | rel  | texture block 1 -> VRAM (384, 0), 384x512, 0x60000 bytes        |
| 0x18 | rel  | texture block 2 -> VRAM (768, 256), 256x224, 0x1C000 bytes      |
| 0x1C | rel  | CLUT block -> VRAM (768, 480), 256x32, 0x4000 bytes; also the end of the RAM part |
| 0x20 | rel  | 0x200-byte table passed to `func_80040A78(p, 0x7654, 0x100, 5)` (palette lookup); zeroed first in level 9 |
| 0x24 | rel  | points to the CLUT block as well (end of RAM part)             |

### RAM part header (parsed by ENGINE1 `func_8004834C`)

| off  | type | meaning                                                   | global       |
|------|------|-----------------------------------------------------------|--------------|
| 0x08 | u16  | n: number of rel pointers at 0x30 (1 in every level)      | `D_80073DC4` |
| 0x0A | u16  | count of table group E                                    | `D_80073DC7` |
| 0x0C | u16  | count of table group A                                    |              |
| 0x0E | u16  | count of table group B = **models**                       | `D_80073DC1` |
| 0x10 | u16  | count of table group C                                    | `D_80073DC5` |
| 0x12 | u16  | count of table group D                                    | `D_80073DC6` |
| 0x24 | rel  | end of RAM part / CLUT block                              | `D_80073C1C` |
| 0x28 | rel  | data block (used by `func_80039D34`, `func_800459C0`)     | `D_80073C24` |
| 0x2C | u8[3]| RGB colour (`4D 4D 4D` in L0) -- ambient or background    | `D_80073BE4..6` |
| 0x30 | rel[n] | n pointers                                              | `D_80073C50..` |
| +0   | rel  | after the n pointers: four more                            | `D_80073C4C`, `C48`, `C44`, `C38` |
| +16  | i32[] | table: groups A, B, C, D, E back to back, each entry a byte offset relative to the entry itself | `C28` (A), `C20` (B, 1-based), `C2C` (C), `C30` (D), `C40` (E), `C34` (end) |

Counts per level (A / models / C / D / E):
L0 49/0/2/0/0, L1 651/89/0/6/0, L3 668/23/2/1/0, L4 318/4/3/0/0,
L5 588/27/0/0/0, L6 171/78/0/0/0, L7 53/16/1/0/0, L9 527/18/0/0/2,
L11 154/1/0/1/0.

### Models (group B)

Game objects carry a 1-based model index at `+0x34`; `func_80039BEC` loads
GTE rotation/translation (`ctc2`) and draws the model through a render
function picked from `D_80069CDC[obj->+0x23]`. Model records are 4-byte
aligned and packed back to back. Known so far: `+0x02` u8 is used as
`n` with an `n*8`-byte block after which `+0x0A` holds an s16 count; `+0x03`
u8 goes to `func_8003AA08` (likely a size/radius for culling). The inner
layout (vertices/primitives) is not decoded yet -- next: `func_80039D34`
and the render table at `D_80069CDC`.

### CLUT block

32 rows of 256 entries. Each row holds 16 palettes of 16 colours; entry 0 of
every palette is 0 (transparent), so the textures are **4-bit indexed**.
Row 31 is not a palette (the field `0x20` table overlaps it), leaving
31 x 16 = 496 candidate palettes. Simple levels (L1, L6, L7, L11) appear to
use only row 0; L3, L4, L5 and L9 use many rows (heuristic result from
`tools/guess_palettes.py`; the real assignment is in the RAM part).

Observed order in the file: RAM part, CLUT block (its last 0x100 bytes overlap
the `0x20` table), texture block 1, texture block 2.

Open points:
- Data past the loaded size (e.g. 0x30800 bytes in L1) is loaded elsewhere.
- In L7 texture block 2 extends past the loaded size (0x83558 vs 0x6F800).
- The RAM part (object layout, collision, ...) is still to be decoded.
