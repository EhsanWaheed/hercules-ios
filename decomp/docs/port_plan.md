# PC port plan

## Decisions (2026-10-11)

| Topic | Decision | Notes |
|-------|----------|-------|
| Output | 1080p, **4:3** with pillarbox | 16:9 later as an option (needs FOV change, wider culling, HUD layout) |
| Textures | **Sharp pixels** (nearest filtering) | Keep a stable texture ID scheme so replacement textures can be added later |
| Fog | **Original**: 31 discrete depth levels via CLUT rows | Row = clamp(depth / 32, 1, 29), see `docs/level_format.md` |
| Frame rate | 50 Hz (PAL timing of SCES-00893) | Game logic is tuned to 50 Hz; higher rates would need interpolation |

## Rendering precision

The GTE projects vertices to integer 320x256 screen coordinates, which causes
the PS1 vertex wobble and affine texture warping. At 1080p the port must keep
sub-pixel (float) projected positions and per-vertex depth for perspective-
correct texturing (PGXP-style). Plan: replace the GTE-using functions below
with float implementations in the port layer; the matching decomp keeps the
original code.

Faces are still drawn in ordering-table order (no z-buffer) to match the
original, including its sorting artefacts. PS1 dithering is dropped (render
in 24/32-bit colour).

## Texture IDs

A texture is identified by `(texpage & 0x1FF, CLUT column bits, UV rect)`,
the same key the exporter uses for `tpXXX_clXXXX.png`. The CLUT row is not
part of the ID because it is the fog level chosen at draw time. Replacement
textures, if added later, are looked up by this key.

## GTE call sites in ENGINE1

27 functions use GTE instructions; `rtps`/`rtpt` project vertices,
`nclip` is the back-face test. ENGINE3 and the overlays still need the same
survey.

| Function | Instructions | GTE ops |
|----------|-------------:|---------|
| `func_80039D34` | 276 | nclip:2 swc2:5
 |
| `func_8003A184` | 35 | lwc2:2 rtps:1 swc2:4
 |
| `func_8003A210` | 40 | lwc2:2 rtps:1 swc2:2
 |
| `func_8003A308` | 85 | lwc2:2 rtps:1 swc2:4
 |
| `func_8003A45C` | 103 | lwc2:2 rtps:1 swc2:2
 |
| `func_8003A6F8` | 28 | lwc2:2 rtps:1 swc2:1
 |
| `func_8003A764` | 44 | lwc2:2 rtps:1 swc2:1
 |
| `func_8003AB14` | 33 | swc2:2
 |
| `func_8003AB94` | 157 | lwc2:2 rtps:1 swc2:2
 |
| `func_8003AE04` | 432 | lwc2:4 rtps:1
 |
| `func_8003B638` | 71 | lwc2:2 rtps:1 swc2:4
 |
| `func_8003B754` | 25 | lwc2:2 rtps:1 swc2:1
 |
| `func_8003B7B8` | 26 | lwc2:2 rtps:1 swc2:2
 |
| `func_8003C70C` | 75 | lwc2:2 rtps:1 swc2:2
 |
| `func_8003C838` | 90 | lwc2:2 rtps:1 swc2:2
 |
| `func_80040D30` | 85 | lwc2:2 rtps:1 swc2:1
 |
| `func_80044214` | 222 | lwc2:8 rtps:1 rtpt:1 swc2:5
 |
| `func_80044588` | 245 | lwc2:8 rtps:1 rtpt:1 swc2:4
 |
| `func_800459C0` | 373 | nclip:2 swc2:8
 |
| `func_80045F90` | 221 | lwc2:4 rtps:2 swc2:2
 |
| `func_80046304` | 56 | lwc2:4 rtps:2 swc2:2
 |
| `func_800463E4` | 63 | lwc2:4 rtps:2 swc2:2
 |
| `func_800464DC` | 247 | lwc2:2 rtps:1 swc2:1
 |
| `func_800468B8` | 226 | lwc2:8 rtps:4 swc2:4
 |
| `func_80046C40` | 167 | lwc2:4 rtps:2 swc2:2
 |
| `func_80047140` | 116 | lwc2:4 rtps:2 swc2:2
 |
| `func_80047310` | 374 | lwc2:8 rtps:4 swc2:4
 |

Known roles: `func_8003A184` = render mode 0 vertex transform (table
`D_80069CDC` holds 8 modes), `func_80039D34` = model draw (face setup,
`nclip`, CLUT row from depth). Culling candidate for widescreen:
`func_8003AA08` (uses the model's size byte).
