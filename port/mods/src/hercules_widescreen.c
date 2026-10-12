/* Widescreen for Hercules (SCES-00893).
 *
 * PSXRecomp keeps PSX titles at 4:3 until a trusted plugin opts in. With the
 * native-wide renderer the 4:3 picture stays exact and the extra width is
 * drawn on a separate host surface ([widescreen] gte_game_mode in game.toml
 * marks level frames as gameplay). The game's own culls still assume 320
 * pixels (psxrecomp/docs/WIDESCREEN.md).
 *
 * HUD: every HUD piece is one SPRT built by a small helper (ENGINE1
 * func_80049F9C, ENGINE3 func_80046D50: GetClut(0x160, 0x20 + n), x in $s5,
 * caller's $ra at sp+0x2C). Packets come from the shared, double-buffered
 * primitive pool, so their addresses change every frame; the helper's
 * closing `sw $a0, 0($s0)` is hooked and each packet built for the HUD
 * routine (ENGINE1 func_80049128 / func_80049D64, ENGINE3 func_800465B0) is
 * anchored to the left or right screen edge by its x. Other callers (menus)
 * stay centred.
 */
#include "mod_plugins.h"
#include "cpu_state.h"

#define REG_S0 16
#define REG_S5 21
#define REG_SP 29
#define SW_A0_0_S0 0xAE040000u   /* sw $a0, 0x0($s0) */
#define HUD_SPLIT_X 200          /* left cluster ends ~180, right starts 236 */

typedef struct {
    const char* name;
    uint32_t site;               /* the packet's closing tag store */
    uint32_t check_addr, check_word; /* GetClut call inside the helper */
    uint32_t hud_lo, hud_hi;     /* callers that draw the in-game HUD */
} HudHelper;

static const HudHelper k_helpers[] = {
    {"ENGINE1", 0x8004A050u, 0x80049FE8u, 0x0C005F43u, 0x80049128u, 0x80049F9Cu},
    {"ENGINE3", 0x80046E04u, 0x80046D9Cu, 0x0C005F43u, 0x800465B0u, 0x80046D50u},
};
#define HELPER_COUNT (sizeof(k_helpers) / sizeof(k_helpers[0]))

static void on_hud_sprite(struct CPUState* cpu, uint32_t address) {
    const HudHelper* h = NULL;
    for (uint32_t i = 0; i < HELPER_COUNT; i++)
        if ((k_helpers[i].site & 0x1FFFFFFFu) == (address & 0x1FFFFFFFu)) h = &k_helpers[i];
    /* Both engines load at the same address: confirm the helper is resident. */
    if (!h || psx_mod_read_word(h->check_addr) != h->check_word) return;
    const uint32_t ra = psx_mod_read_word(cpu->gpr[REG_SP] + 0x2Cu);
    if (ra < h->hud_lo || ra >= h->hud_hi) return;
    const int16_t x = (int16_t)cpu->gpr[REG_S5];
    psx_mod_anchor_hud_primitive(cpu->gpr[REG_S0], x < HUD_SPLIT_X ? -1 : +1);
    psx_mod_counter_add("hercules.widescreen.hud_anchor", 1);
}

static void on_activate(void) {
    if (!psx_mod_set_fixed_display_aspect(16, 9))
        psx_mod_counter_add("hercules.widescreen.aspect_refused", 1);
}

PSX_MOD_CONSTRUCTOR(hercules_register_widescreen) {
    (void)psx_mod_register_activation_plugin("hercules.widescreen", on_activate);
    for (uint32_t i = 0; i < HELPER_COUNT; i++)
        (void)psx_mod_register_instruction_plugin("hercules.widescreen", k_helpers[i].site,
                                                  SW_A0_0_S0, on_hud_sprite);
}
