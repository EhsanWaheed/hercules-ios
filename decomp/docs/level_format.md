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
| 0x28.. | | further rel offsets into the RAM part (not yet identified)       |
| 0x2C | u32  | looks like an RGB colour (`0x4D4D4D` in L0) -- ambient/fog?     |
| 0x44 | u32  | entry count (69 in L0) for the u16-pair table that follows     |

Observed order in the file: RAM part, CLUT block (its last 0x100 bytes overlap
the `0x20` table), texture block 1, texture block 2.

Open points:
- Data past the loaded size (e.g. 0x30800 bytes in L1) is loaded elsewhere.
- In L7 texture block 2 extends past the loaded size (0x83558 vs 0x6F800).
- The RAM part (object layout, collision, ...) is still to be decoded.
