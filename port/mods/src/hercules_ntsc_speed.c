/* NTSC speed for the PAL releases of Hercules (SCES-00891..00895).
 *
 * Both engines step the game once every 2 VBlanks (ENGINE1 0x80038748,
 * ENGINE3 0x80038734: addiu v1,v1,2), so PAL plays at 25 steps per second
 * and the US release (SLUS-01029) at 30. The US code has the same tuning as
 * the PAL code (701 matched functions differ only in screen height), so the
 * game is simply 20 % faster there. Feature ntsc-speed runs the PAL picture
 * on NTSC timing (psx_mod_set_ntsc_timing): 60 VBlanks per second.
 *
 * Music: libsnd's sequencer runs once per VBlank (ENGINE1's VSyncCallback,
 * func_80039990 -> SsSeqCalledTbyT) and scales tempo by D_800379AC, the ticks
 * per second that SsSetTickMode(SS_NOTICK) takes from GetVideoMode(): 50 on
 * a PAL disc. Under NTSC timing that would play every song 20 % fast, so the
 * mod gives SsSetTickMode's PAL store (sw v0, D_800379AC at 0x800211E8) the
 * NTSC value 60, before any sequence reads it. Movies (CD paced) and sound
 * effects need nothing: measured on the German disc, music 1.007x, intro
 * movie length and audio unchanged.
 */
#include "mod_plugins.h"
#include "cpu_state.h"
#include "hercules_addrs.h" /* per PAL version, hercules/tools/port_version.py */

#define REG_V0 2

static void on_tick_store(struct CPUState* cpu, uint32_t address) {
    (void)address;
    if (cpu->gpr[REG_V0] == 50u) {
        cpu->gpr[REG_V0] = 60u;
        psx_mod_counter_add("hercules.ntsc-speed.ticks60", 1);
    }
}

static void on_activate(void) {
    if (!psx_mod_set_ntsc_timing(1)) psx_mod_counter_add("hercules.ntsc-speed.refused", 1);
}

PSX_MOD_CONSTRUCTOR(hercules_register_ntsc_speed) {
    (void)psx_mod_register_activation_plugin("hercules.ntsc-speed", on_activate);
    (void)psx_mod_register_instruction_plugin("hercules.ntsc-speed", HERC_SND_TICK_PAL_SITE,
                                              HERC_SND_TICK_PAL_WORD, on_tick_store);
}
