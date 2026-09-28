/* Default roster unlock for the exact SLUS-00402 executable in the manifest.
 * The game reads its character availability mask from 0x80097EF0 and the
 * Doctor's Tekken Force progress byte from +6. The adjacent costume/movie
 * flags are separate; modes/movies have their own default-enabled feature.
 * See the package README for the original address research.
 */
#include "mod_plugins.h"

static void tekken3_unlock_characters(void)
{
    const uint32_t roster_address = 0x80097EF0u;
    const uint32_t roster_mask = 0x001FFFFFu;
    const uint32_t doctor_progress_address = 0x80097EF6u;
    if (!psx_mod_game_started()) return;

    uint32_t roster = psx_mod_read_word(roster_address);
    if ((roster & roster_mask) != roster_mask)
        psx_mod_write_word(roster_address, roster | roster_mask);
    if (psx_mod_read_byte(doctor_progress_address) < 5u)
        psx_mod_write_byte(doctor_progress_address, 5u);
}

static void tekken3_unlock_modes_movies(void)
{
    if (!psx_mod_game_started()) return;
    /* SLUS-00402 native menu: mode 7 reads progress+0x36, mode 10
     * reads +0x37. State 3 means available without the NEW-mode blink.
     * Theatre's resolver (BNS 301, 0x801004a8) reads the two ending
     * masks at +8/+12; alternate bits are Eddy/Tiger, Kuma/Panda and
     * the two Doctor endings. Do not touch costume bits at +4. */
    const uint32_t addresses[] = {0x80097EF8u, 0x80097EFCu};
    const uint32_t masks[] = {0x001FFFFFu, 0x00010900u};
    for (unsigned i = 0; i < 2; ++i) {
        uint32_t value = psx_mod_read_word(addresses[i]);
        if ((value & masks[i]) != masks[i])
            psx_mod_write_word(addresses[i], value | masks[i]);
    }
    for (uint32_t address = 0x80097F26u; address <= 0x80097F27u; ++address)
        if (psx_mod_read_byte(address) < 3u)
            psx_mod_write_byte(address, 3u);
}

PSX_MOD_CONSTRUCTOR(tekken3_register_unlock_characters)
{
    (void)psx_mod_register_vblank_plugin(
        "tekken3.unlock-all-characters", tekken3_unlock_characters);
    (void)psx_mod_register_vblank_plugin(
        "tekken3.unlock-modes-movies", tekken3_unlock_modes_movies);
}
