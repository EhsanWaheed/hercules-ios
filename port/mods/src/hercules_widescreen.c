/* Widescreen for Hercules (SCES-00893), first step: request a 16:9 display.
 *
 * PSXRecomp keeps PSX titles at 4:3 until a trusted plugin opts in. With the
 * native-wide renderer the 4:3 picture stays exact and the extra width is
 * drawn on a separate host surface, so this alone shows what the game
 * already renders beyond 320 pixels. Its own culls (tiles, objects, HUD
 * placement) still assume 320 and are the next step
 * (psxrecomp/docs/WIDESCREEN.md).
 */
#include "mod_plugins.h"

static void on_activate(void) {
    if (!psx_mod_set_fixed_display_aspect(16, 9))
        psx_mod_counter_add("hercules.widescreen.aspect_refused", 1);
}

PSX_MOD_CONSTRUCTOR(hercules_register_widescreen) {
    (void)psx_mod_register_activation_plugin("hercules.widescreen", on_activate);
}
