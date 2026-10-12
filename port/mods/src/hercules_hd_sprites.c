/* HD sprites for Hercules (SCES-00893), ENGINE1 sprite cache.
 *
 * The game decodes sprite blocks (8..32 px, 8-bit indices) into 16x16
 * quadrants of 32x32 VRAM fields and uploads whole fields, merged into
 * 32-pixel-wide columns, with one LoadImage per run (func_8004023C). The
 * quadrants it did not touch keep stale data, so an upload hash almost never
 * repeats (see hercules/docs/sprite_format.md, "VRAM sprite cache").
 *
 * This plugin records every block as it is decoded and, right after the
 * game's column upload, uploads each block once more as its own w x h
 * rectangle. VRAM ends up with the same bytes, but the HD texture pack now
 * tracks one upload per block, so a DuckStation-format replacement named
 * after the block (hercules/tools/sprite_texpack.py) matches whenever it is
 * drawn. It also owns the pack folder, like the builtin psx.hd-textures.
 */
#include "mod_plugins.h"
#include "cpu_state.h"

#include <string.h>

/* ENGINE1 (loaded at 0x80038350; ENGINE3/TITLE share the range, so every
 * hook checks the instruction words first). */
#define DECODE_SITE     0x8003FD7Cu /* lw $a0, 0x290C($gp): staging base */
#define DECODE_WORD     0x8F84290Cu
#define FLUSH_FUNC      0x8004023Cu
#define FLUSH_WORD0     0x8F82005Cu /* lw $v0, 0x5C($gp) */
#define FLUSH_CALL      0x80040304u /* jal LoadImage */
#define FLUSH_CALL_WORD 0x0C00632Bu
#define UPLOAD_QUEUE    0x80072A6Cu /* u16 field ids */
#define DRAW_SYNC       0x800189E8u /* PsyQ DrawSync (main executable) */

#define REG_T1 9
#define REG_S1 17
#define REG_GP 28
#define REG_FP 30
#define REG_RA 31

#define MAX_BLOCKS 256 /* 0x20 queued fields x 4 quadrants, with room */

typedef struct {
    uint32_t src;   /* staging address of the block's top-left byte */
    uint16_t x, y;  /* VRAM position in halfwords / rows */
    uint8_t w, h;   /* pixels (bytes) */
} Block;

static Block s_blocks[MAX_BLOCKS];
static uint8_t s_pixels[MAX_BLOCKS][32 * 32];
static uint32_t s_count;
static int s_in_flush;

static int option_true(const char* id, int fallback) {
    char value[16] = "";
    if (!psx_mod_current_option_value(id, value, sizeof(value))) return fallback;
    return strcmp(value, "true") == 0;
}

/* Before func_8003F9D4 decodes a cell: $t1 = queue index, $s1 = quadrant
 * (bit 0 right, bit 1 bottom), $fp = cell record (byte 0: size). */
static void on_decode(struct CPUState* cpu, uint32_t address) {
    (void)address;
    if (s_count >= MAX_BLOCKS) {
        psx_mod_counter_add("hercules.hd-sprites.overflow", 1);
        return;
    }
    const uint32_t queue_index = cpu->gpr[REG_T1];
    const uint32_t quadrant = cpu->gpr[REG_S1] & 3u;
    const uint8_t size = psx_mod_read_byte(cpu->gpr[REG_FP]);
    const uint16_t field = psx_mod_read_half(UPLOAD_QUEUE + 2u * queue_index);
    const uint32_t staging = psx_mod_read_word(cpu->gpr[REG_GP] + 0x290Cu);

    Block* b = &s_blocks[s_count++];
    b->src = staging + (queue_index << 10) + ((quadrant & 2u) << 8) + ((quadrant & 1u) << 4);
    b->x = (uint16_t)(0x300u + 16u * (field >> 4) + 8u * (quadrant & 1u));
    b->y = (uint16_t)(32u * (field & 0xFu) + 16u * (quadrant >> 1));
    b->w = (uint8_t)(((size & 3u) + 1u) * 8u);
    b->h = (uint8_t)((((size >> 2) & 3u) + 1u) * 8u);
}

/* LoadImage needs its source in main RAM. After the flush the staging
 * buffer is dead (the next batch overwrites it before uploading), so each
 * block is packed at the start of the staging buffer and uploaded from
 * there; all blocks are read out first because they share that space. */
static void upload_blocks(uint32_t staging) {
    for (uint32_t i = 0; i < s_count; i++) {
        const Block* b = &s_blocks[i];
        for (uint32_t row = 0; row < b->h; row++)
            for (uint32_t col = 0; col < b->w; col++)
                s_pixels[i][row * b->w + col] = psx_mod_read_byte(b->src + row * 32u + col);
    }
    for (uint32_t i = 0; i < s_count; i++) {
        const Block* b = &s_blocks[i];
        if (!psx_mod_host_write_ram(staging, s_pixels[i], (uint32_t)b->w * b->h) ||
            !psx_mod_psyq_load_image(b->x, b->y, b->w / 2u, b->h, staging))
            psx_mod_counter_add("hercules.hd-sprites.upload_failed", 1);
    }
    psx_mod_counter_add("hercules.hd-sprites.blocks", s_count);
    s_count = 0;
}

/* func_8004023C: run the game's flush, wait for its LoadImages, then add
 * the per-block uploads. */
static void on_flush(struct CPUState* cpu, uint32_t address) {
    (void)address;
    if (s_in_flush) return; /* our own nested call runs the original body */
    if (psx_mod_read_word(FLUSH_FUNC) != FLUSH_WORD0 ||
        psx_mod_read_word(FLUSH_CALL) != FLUSH_CALL_WORD) {
        psx_mod_counter_add("hercules.hd-sprites.foreign_code", 1);
        return;
    }
    const uint32_t ra = cpu->gpr[REG_RA];
    s_in_flush = 1;
    (void)psx_mod_call_guest(cpu, FLUSH_FUNC, ra, 0, 0, 0, 0);
    s_in_flush = 0;
    if (s_count) {
        (void)psx_mod_call_guest(cpu, DRAW_SYNC, ra, 0, 0, 0, 0);
        upload_blocks(psx_mod_read_word(cpu->gpr[REG_GP] + 0x290Cu));
    }
    (void)psx_mod_finish_function(cpu);
}

static void on_activate(void) {
    s_count = 0;
    s_in_flush = 0;
    (void)psx_mod_set_hd_texture_pack("pack", option_true("replacements", 1),
                                      option_true("dump", 0));
}

static void on_savestate(void) {
    s_count = 0; /* recorded blocks belong to the abandoned timeline */
    s_in_flush = 0;
}

PSX_MOD_CONSTRUCTOR(hercules_register_hd_sprites) {
    (void)psx_mod_register_activation_plugin("hercules.hd-sprites", on_activate);
    (void)psx_mod_register_savestate_plugin("hercules.hd-sprites", on_savestate);
    (void)psx_mod_register_instruction_plugin("hercules.hd-sprites", DECODE_SITE,
                                              DECODE_WORD, on_decode);
    (void)psx_mod_register_function_entry_plugin("hercules.hd-sprites", FLUSH_FUNC,
                                                 on_flush);
}
