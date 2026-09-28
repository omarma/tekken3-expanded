#ifndef PSX_STICK_H
#define PSX_STICK_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Convert one SDL stick vector to the two unsigned DualShock axis bytes.
 *
 * deadzone and anti_deadzone use SDL's 0..32767 radial magnitude scale.
 * Values inside deadzone are centred. Outside it, magnitude is remapped from
 * anti_deadzone to full travel while direction is preserved. anti_deadzone=0
 * is an ordinary rescaled radial deadzone.
 */
void psx_stick_to_dualshock(int16_t x, int16_t y,
                            int deadzone, int anti_deadzone,
                            uint8_t *out_x, uint8_t *out_y);

#ifdef __cplusplus
}
#endif

#endif
