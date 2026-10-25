/* Devil's and Angel's lasers drawn as Tekken Tag Tournament on the PS2 draws
 * them: the textures and the PS2 EFFECTS row (src/tekken3_ttt1_ps2_laser.c); the
 * beam's geometry is the renderer's (src/tekken3_ttt1_renderer.c). */
#ifndef TEKKEN3_TTT1_PS2_LASER_H
#define TEKKEN3_TTT1_PS2_LASER_H
#include <stdint.h>

/* An image in the upper VRAM half: its texture page and palette words (the
 * upper-half bits set, additive) and its top left texel in the page. */
typedef struct { uint16_t tpage, clut; uint8_t u, v; } Tekken3Ps2LaserImage;
enum {
    TEKKEN3_PS2_LASER_ORBS = 15,          /* images 0..14: the orb, one a frame */
    TEKKEN3_PS2_LASER_A = 15,             /* 15..22: the beam's body, A0..A7 (64 x 32) */
    TEKKEN3_PS2_LASER_B = 23,             /* 23..30: its tip, B0..B7 */
    TEKKEN3_PS2_LASER_IMAGES = 31,
    TEKKEN3_PS2_LASER_PACKET_BYTES = 1024 /* a player's packets for one display buffer */
};
/* 1 when player p's laser is drawn the PS2 way: PS2 EFFECTS on, the pack read,
 * its images placed this fight. Gives the images (Angel's palettes for Angel's
 * moves, Devil's otherwise) and player p's packet block for display buffer
 * `buffer` (0 or 1), declared to the upper half. 0: the arcade's yellow beam. */
int tekken3_ps2_laser_frame(unsigned p, unsigned buffer, const Tekken3Ps2LaserImage **images,
                            uint32_t *packets);
/* PS2 EFFECTS on, with a pack read and an upper half drawn. */
int tekken3_ps2_effects_on(void);
/* The pack's folder (mods/ttt-ps2-laser, or TEKKEN3_TTT_PS2_LASER_DIR). */
const char *tekken3_ps2_effects_dir(void);
#endif
