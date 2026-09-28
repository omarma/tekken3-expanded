/* Character select countdown: 99 seconds instead of 20, on the cabinet
 * selector (Arcade, Time Attack, Survival, Practice, Tekken Force).
 * The selector overlay (0x8010FF4C) sets its timer to 20 * tick_rate frames
 * and shows ceil(frames / tick_rate). Only that initializer is replaced, by
 * 99 * tick_rate; the decrement loop is untouched. The overlay is
 * interpreted, so the code words take effect. From upstream v0.1.3, where it
 * lives in the costume carousel. */
#include "mod_plugins.h"

static void tekken3_selector_timer(void)
{
    if (!psx_mod_game_started() || psx_mod_read_half(0x800ae204u) != 9 ||
        psx_mod_read_word(0x8010ff4cu) != 0x27bdffd0u ||
        psx_mod_read_word(0x8010ff50u) != 0x3c028012u)
        return;
    if (psx_mod_read_word(0x8010dd48u) != 0x00031080u ||   /* sll v0,v1,2 */
        psx_mod_read_word(0x8010dd4cu) != 0x00431021u ||   /* addu v0,v0,v1 */
        psx_mod_read_word(0x8010dd50u) != 0x00021080u)     /* sll v0,v0,2 */
        return;
    psx_mod_write_code_word(0x8010dd48u, 0x24020063u);     /* li v0,99 */
    psx_mod_write_code_word(0x8010dd4cu, 0x00430018u);     /* mult v0,v1 */
    psx_mod_write_code_word(0x8010dd50u, 0x00001012u);     /* mflo v0 */
    /* The first VBlank can come just after the overlay started its timer. */
    uint32_t rate = psx_mod_read_word(0x80118640u), left = psx_mod_read_word(0x8011863cu);
    if (rate >= 60 && rate <= 120 && left > 0 && left <= rate * 20)
        psx_mod_write_word(0x8011863cu, rate * 99);
}

PSX_MOD_CONSTRUCTOR(tekken3_register_selector_timer)
{
    (void)psx_mod_register_vblank_plugin("tekken3.selector-timer", tekken3_selector_timer);
}
