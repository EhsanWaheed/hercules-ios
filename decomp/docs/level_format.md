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

### Tiles (group A)

The level is a grid of 64-unit tiles in several depth layers (collision:
ENGINE1 `func_800489D4`, drawing: `func_800459C0`). A map cell is a u32:
bit 0 = horizontal flip, bits 1-10 = 1-based tile index into group A,
bits 11+ (`>> 11`) index a 4-byte record in `D_80073C48` (u16 lighting/
vertex-colour set, u16 render flags).

Group A entry i (1-based) at `table + (i-1)*4`: s16 offset in words to the
tile definition (`entry + 4*s16`), s16 to a collision height profile.

Tile definition:

| off | type | meaning |
|-----|------|---------|
| 0x00 | s16 | type (-1 most common, also 0, 1, 4, 5) |
| 0x02 | u8 | vertex count |
| 0x03 | u8 | face count |
| 0x04 | u32[] | vertices, packed like model vertices |
| ... | u32 | (unknown) |
| ... | 8 bytes each | faces as in models, but flag bit 7 = flat face and the texture word's top byte is an ordering-table depth bias; texture-record offset = low 16 bits |

Vertices span about x -32..32 (one tile), y/z up to about +-128.
2855 of 2861 tiles parse; the other 6 are empty placeholders (0 vertices).
Models + tiles cover 75-93% of the non-empty texture data in L1/L3/L5/L6/
L7/L9 (about 43% in L0 and L11); the rest is presumably sprites/HUD.

### Models (group B)

Decoded from ENGINE1 `func_80039D34` (draw) and `func_8003A184` (vertex
transform, render mode 0); parser: `tools/level_models.py`.

Game objects carry a 1-based model index at `+0x34`; `func_80039BEC` loads
GTE rotation/translation and calls the draw function, which picks a vertex
transform from `D_80069CDC[obj->+0x23]` (8 render modes).

Model record (4-byte aligned):

| off  | type | meaning                                                     |
|------|------|-------------------------------------------------------------|
| 0x00 | u16  | start of the model's faces in the face pool, in 4-byte words |
| 0x02 | u8   | n: count of 8-byte records at +0x0A (per-part data, undecoded) |
| 0x03 | u8   | size for culling (`func_8003AA08`)                           |
| 0x04 | u16  | animation/matrix parameter (`func_8003A5F4`); 0 = static     |
| 0x0A | n*8  | records                                                      |
| ...  |      | per part: s16 vertex count (1..64), then u32 packed vertices; 2 bytes between parts |

Packed vertex: bits 0-7 z (s8), 8-23 x (s16), 24-31 y (s8). The GTE result
goes to the scratchpad at `0x1F800018 + 8*index`.

Face pool (header rel 0x24), per part:
- u16 face count, u16 info (high byte: extra index bytes copied to an
  attachment buffer, low byte: non-zero = another part follows)
- faces, 8 bytes each:
  - u32: four 6-bit vertex indices (bits 0-23) + flags (bits 24-31);
    bit 3 = quad, other bits select back-face handling
  - u32: if the top byte is 0, a byte offset into the texture-record block
    (header rel 0x28); otherwise a flat face
- `info >> 8` extra bytes, then align to 4

Texture record (12 bytes) -> GPU `POLY_FT4` (code 0x09 words):
u16 uv0, u16 CLUT column bits; u16 uv1, u16 texpage; u16 uv2, u16 uv3.
The CLUT row is **not** stored: the draw code ORs `(shade << 6) + 0x7830`
(VRAM 768,480 + shade rows) into the CLUT field, shade = clamp(depth >> 5,
1, 29). So CLUT rows 0..30 are depth-fog levels of the same palettes (row 1 =
closest; in some levels far rows fade to a bright fog colour), and a face's
palette is selected by the column bits in its record. Texture pages use
both 4-bit (16-colour palette) and 8-bit (whole 256-entry row) modes; e.g.
most faces in L6 use 8-bit pages 0xA6/0xB6. Textured export:
`tools/level_models_tex.py` (OBJ + MTL + one RGBA PNG per page/palette).

Parse result: 244 of 256 models (all of L3, L5, L6, L7, L9, L11; 81/89 in
L1). L1 models 42-49 are 8-16 byte records (not meshes). L4 (`i2.4`) uses a
different model layout.
