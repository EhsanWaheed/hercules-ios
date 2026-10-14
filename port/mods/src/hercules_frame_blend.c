/* hercules.frame-blend: present the game's 25 fps (every other PAL VBlank,
 * a fixed 2-VBlank wait in both engines' main loops) at the display refresh
 * by crossfading between real frames. Presentation only: guest timing, logic
 * and audio are untouched. FLIP as the source spreads one crossfade over the
 * whole 2-VBlank game frame. True in-between positions would need render
 * passes (psxrecomp docs/RENDER_PASSES.md); the framework's generic smooth
 * motion finds no GTE-projected world in Hercules ("no projections"). */
#include <string.h>
#include "mod_plugins.h"

static void on_activate(void) {
    char blend[16] = "";
    const int adaptive = psx_mod_current_option_value("blend", blend, sizeof(blend)) &&
                         strcmp(blend, "adaptive") == 0;
    psx_mod_set_frame_interpolation_source(PSX_MOD_FRAME_SOURCE_FLIP);
    psx_mod_set_frame_interpolation_blend(adaptive ? PSX_MOD_FRAME_INTERPOLATION_MOTION_ADAPTIVE
                                                   : PSX_MOD_FRAME_INTERPOLATION_LINEAR);
    if (!psx_mod_set_frame_interpolation(0))          /* 0 = the display's refresh rate */
        psx_mod_counter_add("hercules.frame-blend.refused", 1);
}

PSX_MOD_CONSTRUCTOR(hercules_register_frame_blend) {
    (void)psx_mod_register_activation_plugin("hercules.frame-blend", on_activate);
}
