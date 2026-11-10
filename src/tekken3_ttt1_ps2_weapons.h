/* Unknown's PS2 weapons (F29, GH#120, TIPS.md sections 226 and 227): her own
 * katana (Yoshimitsu's style) and dagger (Kunimitsu's) of Tekken Tag Tournament
 * PS2, read on the player's disc by the setup (tools/ps2/ttt_weapons.py) and
 * drawn in her hand instead of the arcade's energy blade under PS2 EFFECTS
 * (src/tekken3_ttt1_ps2_weapons.c; the geometry, src/tekken3_ttt1_renderer.c). */
#ifndef TEKKEN3_TTT1_PS2_WEAPONS_H
#define TEKKEN3_TTT1_PS2_WEAPONS_H
#include <stdint.h>

enum { TEKKEN3_PS2_WEAPON_POINTS = 128, TEKKEN3_PS2_WEAPON_POLYGONS = 128,
       TEKKEN3_PS2_WEAPON_PACKET_BYTES = TEKKEN3_PS2_WEAPON_POLYGONS * 40 };
/* A polygon ready for the GPU: 3 or 4 corners (POLY_FT3 / FT4 order), the
 * word after each corner's position (UV, with the palette after the first and
 * the texture page after the second), additive or opaque. */
typedef struct {
    uint8_t corners, additive, point[4];
    uint32_t uv[4];
} Tekken3Ps2WeaponPolygon;
typedef struct {
    unsigned bone, points, polygons;
    const int16_t (*point)[3];
    const Tekken3Ps2WeaponPolygon *polygon;
} Tekken3Ps2Weapon;
/* Player p's PS2 weapon for the moveset it fights with (4: the katana, 26:
 * the dagger): PS2 EFFECTS on, the pack read, its images placed; gives the
 * weapon and player p's packet block for display buffer `buffer` (0 or 1),
 * declared to the upper half. 0: the arcade's energy blade and hilt. */
int tekken3_ps2_weapon_frame(unsigned p, unsigned moveset, unsigned buffer, const Tekken3Ps2Weapon **weapon,
                             uint32_t *packets);
/* For the other users of the upper half (the PS2 lasers): whether rectangle
 * x, y, w, h overlaps the weapons' images or palettes once placed. */
int tekken3_ps2_weapons_high_vram_used(int x, int y, int w, int h);
#endif
