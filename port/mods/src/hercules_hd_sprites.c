/* HD sprites for Hercules (SCES-00893): sprite caches of ENGINE1, ENGINE3
 * and TITLE.
 *
 * The game decodes sprite blocks (8..32 px, 8-bit indices) into 16x16
 * quadrants of 32x32 VRAM fields and uploads whole fields, merged into
 * 32-pixel-wide columns, with one LoadImage per run (ENGINE1 func_8004023C).
 * The quadrants it did not touch keep stale data, so an upload hash almost
 * never repeats (see hercules/docs/sprite_format.md, "VRAM sprite cache").
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
#include "hercules_addrs.h" /* per PAL version, hercules/tools/port_version.py */

#include <string.h>

#define FLUSH_CALL_OFF  0xC8u       /* jal LoadImage inside the flush */
#define FLUSH_CALL_WORD 0x0C00632Bu
#define DRAW_SYNC       HERC_DRAW_SYNC /* PsyQ DrawSync (main executable) */

/* All three files load at 0x80038350 and carry the same two functions,
 * relinked (tools/find_func.py): only data addresses and gp offsets differ.
 * Every hook checks instruction words, since another file may be resident. */
typedef struct {
    const char* name;
    uint32_t decode_site;  /* lw $a0, staging($gp) before a cell is decoded */
    uint32_t decode_word;
    uint32_t staging_gp;   /* gp offset of the staging buffer pointer */
    uint32_t queue;        /* u16 field ids queued for upload */
    uint32_t flush;        /* column upload function */
    uint32_t flush_word0;  /* lw $v0, count($gp) */
} Module;

static const Module k_modules[] = {
    {"ENGINE1", HERC_E1_DECODE_SITE, HERC_E1_DECODE_WORD, HERC_E1_STAGING_GP, HERC_E1_QUEUE,
     HERC_E1_FLUSH_SITE, HERC_E1_FLUSH_WORD},
    {"ENGINE3", HERC_E3_DECODE_SITE, HERC_E3_DECODE_WORD, HERC_E3_STAGING_GP, HERC_E3_QUEUE,
     HERC_E3_FLUSH_SITE, HERC_E3_FLUSH_WORD},
    {"TITLE",   HERC_TI_DECODE_SITE, HERC_TI_DECODE_WORD, HERC_TI_STAGING_GP, HERC_TI_QUEUE,
     HERC_TI_FLUSH_SITE, HERC_TI_FLUSH_WORD},
};
#define MODULE_COUNT (sizeof(k_modules) / sizeof(k_modules[0]))

#define REG_T1 9
#define REG_S1 17
#define REG_SP 29
#define REG_GP 28
#define REG_FP 30
#define REG_RA 31

/* The decode function (ENGINE1 func_8003F9D4) is called from the per-object
 * draw (func_8003E5D8, $s0 = object) and from a per-file preload. Its frame
 * saves the caller's $s0 at sp+0x40 and $ra at sp+0x64; the instruction
 * after the object path's jal is `addu $v1, $v0, $zero`. */
#define DECODE_FRAME_S0   0x40u
#define DECODE_FRAME_RA   0x64u
#define OBJECT_CALL_AFTER 0x00401821u
#define OBJ_FLAGS         0x54u
#define OBJ_FLAG_SEMI     0x4u /* func_80045098: sets the primitive's ABE bit */

#define MAX_BLOCKS 256 /* 0x20 queued fields x 4 quadrants, with room */

typedef struct {
    uint32_t src;   /* staging address of the block's top-left byte */
    uint16_t x, y;  /* VRAM position in halfwords / rows */
    uint8_t w, h;   /* pixels (bytes) */
} Block;

/* Objects seen drawn opaque. The game also draws Hercules semi-transparent
 * for a while after a hit (the post-hit flash); an object that was opaque
 * before is no effect, so its blocks keep getting HD. */
#define OPAQUE_SEEN 64
static uint32_t s_opaque[OPAQUE_SEEN];
static uint32_t s_opaque_next;

static int seen_opaque(uint32_t obj) {
    for (uint32_t i = 0; i < OPAQUE_SEEN; i++)
        if (s_opaque[i] == obj) return 1;
    return 0;
}

static Block s_blocks[MAX_BLOCKS];
static uint8_t s_pixels[MAX_BLOCKS][32 * 32];
static uint32_t s_count;
static const Module* s_owner; /* module the recorded blocks belong to */
static int s_in_flush;

static int option_true(const char* id, int fallback) {
    char value[16] = "";
    if (!psx_mod_current_option_value(id, value, sizeof(value))) return fallback;
    return strcmp(value, "true") == 0;
}

/* Before a cell is decoded: $t1 = queue index, $s1 = quadrant (bit 0 right,
 * bit 1 bottom), $fp = cell record (byte 0: size). The runtime has already
 * checked the instruction word, so the module is resident. */
static void on_decode(struct CPUState* cpu, uint32_t address) {
    const Module* m = NULL;
    for (uint32_t i = 0; i < MODULE_COUNT; i++)
        if ((k_modules[i].decode_site & 0x1FFFFFFFu) == (address & 0x1FFFFFFFu)) m = &k_modules[i];
    if (!m) return;
    psx_mod_counter_add("hercules.hd-sprites.decode", 1);
    if (s_owner != m) s_count = 0; /* another file was loaded meanwhile */
    s_owner = m;
    if (s_count >= MAX_BLOCKS) {
        psx_mod_counter_add("hercules.hd-sprites.overflow", 1);
        return;
    }
    /* Effects (semi-transparent objects: sparks, flashes, shadows) keep the
     * original pixels: without a per-block upload no replacement matches.
     * The block cache is per object, so the choice sticks with the object.
     * Preloaded frames (shared by all objects: HUD symbols, coins and the
     * sparkles of SD1/S1.2) are always uploaded; tools/sprite_texpack.py
     * leaves the effect frames among them out of the pack. */
    const uint32_t sp = cpu->gpr[REG_SP];
    if (psx_mod_read_word(psx_mod_read_word(sp + DECODE_FRAME_RA)) == OBJECT_CALL_AFTER) {
        const uint32_t obj = psx_mod_read_word(sp + DECODE_FRAME_S0);
        if (!(psx_mod_read_word(obj + OBJ_FLAGS) & OBJ_FLAG_SEMI)) {
            if (!seen_opaque(obj)) {
                s_opaque[s_opaque_next] = obj;
                s_opaque_next = (s_opaque_next + 1) % OPAQUE_SEEN;
            }
        } else if (!seen_opaque(obj)) {
            psx_mod_counter_add("hercules.hd-sprites.effect_native", 1);
            return;
        } else {
            psx_mod_counter_add("hercules.hd-sprites.flash_hd", 1);
        }
    }
    const uint32_t queue_index = cpu->gpr[REG_T1];
    const uint32_t quadrant = cpu->gpr[REG_S1] & 3u;
    const uint8_t size = psx_mod_read_byte(cpu->gpr[REG_FP]);
    const uint16_t field = psx_mod_read_half(m->queue + 2u * queue_index);
    const uint32_t staging = psx_mod_read_word(cpu->gpr[REG_GP] + m->staging_gp);

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

/* Column upload: run the game's flush, wait for its LoadImages, then add
 * the per-block uploads. */
static void on_flush(struct CPUState* cpu, uint32_t address) {
    if (s_in_flush) return; /* our own nested call runs the original body */
    const Module* m = NULL;
    for (uint32_t i = 0; i < MODULE_COUNT; i++) {
        const Module* k = &k_modules[i];
        if ((k->flush & 0x1FFFFFFFu) == (address & 0x1FFFFFFFu) &&
            psx_mod_read_word(k->flush) == k->flush_word0 &&
            psx_mod_read_word(k->flush + FLUSH_CALL_OFF) == FLUSH_CALL_WORD &&
            psx_mod_read_word(k->decode_site) == k->decode_word)
            m = k;
    }
    if (!m) {
        psx_mod_counter_add("hercules.hd-sprites.foreign_code", 1);
        return;
    }
    psx_mod_counter_add("hercules.hd-sprites.flush", 1);
    const uint32_t ra = cpu->gpr[REG_RA];
    s_in_flush = 1;
    (void)psx_mod_call_guest(cpu, m->flush, ra, 0, 0, 0, 0);
    s_in_flush = 0;
    if (s_count && s_owner == m) {
        (void)psx_mod_call_guest(cpu, DRAW_SYNC, ra, 0, 0, 0, 0);
        upload_blocks(psx_mod_read_word(cpu->gpr[REG_GP] + m->staging_gp));
    }
    s_count = 0;
    (void)psx_mod_finish_function(cpu);
}

static void on_activate(void) {
    memset(s_opaque, 0, sizeof(s_opaque));
    s_count = 0;
    s_owner = NULL;
    s_in_flush = 0;
    (void)psx_mod_set_hd_texture_pack("pack", option_true("replacements", 1),
                                      option_true("dump", 0));
}

static void on_savestate(void) {
    s_count = 0; /* recorded blocks belong to the abandoned timeline */
    s_owner = NULL;
    s_in_flush = 0;
}

PSX_MOD_CONSTRUCTOR(hercules_register_hd_sprites) {
    (void)psx_mod_register_activation_plugin("hercules.hd-sprites", on_activate);
    (void)psx_mod_register_savestate_plugin("hercules.hd-sprites", on_savestate);
    for (uint32_t i = 0; i < MODULE_COUNT; i++) {
        (void)psx_mod_register_instruction_plugin("hercules.hd-sprites",
                                                  k_modules[i].decode_site,
                                                  k_modules[i].decode_word, on_decode);
        (void)psx_mod_register_function_entry_plugin("hercules.hd-sprites",
                                                     k_modules[i].flush, on_flush);
    }
}
