/* Level select for Hercules (SCES-00893): start a new game in any level.
 *
 * The current level is the byte D_80035048 in the main executable's data
 * (hercules/docs/level_format.md). On the title screen it reads 0; choosing
 * "Spiel starten" sets it to 1, then the main loop loads ENGINE1 (or ENGINE3
 * for levels 2, 8, 10) for that level. The attract demo sets level 1 as
 * well, but together with the demo flags D_8003504E..D_80035050 = 1, which
 * stay 0 for a real game (traced with the debug server).
 *
 * While TITLE is resident this plugin waits until a real game start has set
 * level 1 for two VBlanks, then keeps the level at the chosen value until
 * TITLE is gone. Every later level (and a continue from the memory card,
 * which sets another level) is left alone.
 */
#include "mod_plugins.h"
#include "hercules_addrs.h" /* per PAL version, hercules/tools/port_version.py */

#include <stdlib.h>

#define LEVEL        HERC_LEVEL
#define DEMO_FLAG_A  HERC_DEMO_FLAG_A
#define DEMO_FLAG_B  HERC_DEMO_FLAG_B
#define TITLE_SITE   HERC_TI_DECODE_SITE /* TITLE's sprite decode */
#define TITLE_WORD   HERC_TI_DECODE_WORD
#define NEW_GAME     1
#define SETTLE       2           /* VBlanks a real start must hold level 1 */

static int s_target = -1; /* -1 = off */
static int s_seen;
static int s_forcing;

static void reset(void) {
    s_seen = 0;
    s_forcing = 0;
}

static void on_activate(void) {
    char value[16] = "";
    s_target = -1;
    if (psx_mod_current_option_value("level", value, sizeof(value)) && value[0] != 'o') {
        const int level = atoi(value);
        if (level >= 0 && level <= 11) s_target = level;
    }
    reset();
}

static void on_vblank(void) {
    if (s_target < 0) return;
    if (psx_mod_read_word(TITLE_SITE) != TITLE_WORD) {
        reset();
        return;
    }
    const uint8_t level = psx_mod_read_byte(LEVEL);
    if (s_forcing) {
        if (level != (uint8_t)s_target) psx_mod_write_byte(LEVEL, (uint8_t)s_target);
        return;
    }
    const int demo = psx_mod_read_byte(DEMO_FLAG_A) | psx_mod_read_byte(DEMO_FLAG_B);
    if (level != NEW_GAME || demo) {
        s_seen = 0;
        return;
    }
    if (++s_seen >= SETTLE) {
        s_forcing = 1;
        psx_mod_write_byte(LEVEL, (uint8_t)s_target);
        psx_mod_counter_add("hercules.level-select.forced", 1);
    }
}

PSX_MOD_CONSTRUCTOR(hercules_register_level_select) {
    (void)psx_mod_register_activation_plugin("hercules.level-select", on_activate);
    (void)psx_mod_register_savestate_plugin("hercules.level-select", reset);
    (void)psx_mod_register_vblank_plugin("hercules.level-select", on_vblank);
}
