/* Skip the boot sequence of Hercules (SCES-00893).
 *
 * TITLE runs its screens as tasks in a 16-slot table at D_80065CB8 (0x18
 * bytes each: +0 handler, +4 step, +8 frames until the next call; dispatcher
 * func_80041CF0, spawn func_80041A18). On a cold boot slot 0 runs the intro
 * handler func_8003EF94 through these steps (traced with the debug server):
 *
 *   0x33-0x35  piracy notice          0x36, 0x3D-0x40  "SCEE presents"
 *   0x26/0x27  Disney Interactive FMV 0x25 Eurocom FMV  0x24 Hercules logo FMV
 *   0xE7       spawns the memory card check (func_8004EAA4), waits for it
 *   0xE6       "LADEN" screen, loads the title menu (func_80042E88)
 *
 * The skipped steps only draw pictures and play movies. Feature skip-intro
 * moves the first notice step (0x33, only reached on a cold boot) on to 0xE7;
 * feature skip-memcard moves 0xE7 on to 0xE6, so the card check task is never
 * spawned (the title menu reads the card itself when a game is loaded).
 */
#include "mod_plugins.h"

#define TITLE_SITE    0x8005418Cu /* lw $a0, 0x3ACC($gp) in TITLE */
#define TITLE_WORD    0x8F843ACCu
#define TASK0_HANDLER 0x80065CB8u
#define TASK0_STEP    0x80065CBCu
#define TASK0_WAIT    0x80065CC0u
#define INTRO_HANDLER 0x8003EF94u
#define STEP_NOTICE   0x33u
#define STEP_MEMCARD  0xE7u
#define STEP_LOADING  0xE6u

static int s_skip_intro;
static int s_skip_memcard;

static void on_vblank(void) {
    if (psx_mod_read_word(TITLE_SITE) != TITLE_WORD) return;
    if (psx_mod_read_word(TASK0_HANDLER) != INTRO_HANDLER) return;
    const uint32_t step = psx_mod_read_word(TASK0_STEP);
    uint32_t next = step;
    if (s_skip_intro && step == STEP_NOTICE)
        next = s_skip_memcard ? STEP_LOADING : STEP_MEMCARD;
    else if (s_skip_memcard && step == STEP_MEMCARD)
        next = STEP_LOADING;
    if (next == step) return;
    psx_mod_write_word(TASK0_STEP, next);
    psx_mod_write_word(TASK0_WAIT, 1);
    psx_mod_counter_add(next == STEP_LOADING ? "hercules.skip-intro.to_loading"
                                             : "hercules.skip-intro.to_memcard", 1);
}

static void on_activate_intro(void) { s_skip_intro = 1; }
static void on_activate_memcard(void) { s_skip_memcard = 1; }

PSX_MOD_CONSTRUCTOR(hercules_register_skip_intro) {
    (void)psx_mod_register_activation_plugin("hercules.skip-intro", on_activate_intro);
    (void)psx_mod_register_vblank_plugin("hercules.skip-intro", on_vblank);
    (void)psx_mod_register_activation_plugin("hercules.skip-memcard", on_activate_memcard);
    (void)psx_mod_register_vblank_plugin("hercules.skip-memcard", on_vblank);
}
