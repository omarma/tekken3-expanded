/* B87 (GH#142): on a T3 arcade stage, the K.O.'s REPLAY and the winner's
 * pose follow Tekken 3 arcade's cameras, not the PS1's. The PS1 port kept
 * the arcade's routines and changed constants and a few choices; its
 * cameras come nearer and turn where the arcade's stages,
 * made for the arcade's cameras, have slits and empty cells (older frames on
 * screen: T3 never clears it). Measured in MAME and in the game (workspace
 * notes, B87 cams/REPORT.md; TIPS, B87):
 *
 *   winner's pose  the arcade always takes shot A (0x801A511C / 0x801A52A8),
 *                  never shot B; the PS1 alternates them. Shot A starts at
 *                  z * 0x1450 / 955 + 0x5A0 from the winner (PS1: 0xF71 and a
 *                  circle of 5800, 0x80046270) and comes no nearer than
 *                  z * 0x1450 / 955 (PS1: 0x9D1); its height and pitch
 *                  floor by the stage's no_pitch (PS1: 0);
 *   replay         the arcade's draws (0x801D6DA8): a half turn on a coin,
 *                  side 1 within 60 degrees of the fight's line (PS1: 30 to
 *                  150), angles on 18 bits (PS1: halfwords, which overflow),
 *                  from 2 x z * 8.2475 to z * 8.2475 (PS1: 0x2B1A to 0x113D).
 *
 * The view of the loser (YOU LOSE, CONTINUE?, GAME OVER; 0x8006875C /
 * 0x8006895C) stays the PS1's on every stage (B110, GH#156, the user's
 * choice of 2026-10-25): the arcade's, its fixed view z * 8000 / 955 up
 * instead of 0x1EAD, came nearer on the T3 arcade stages only.
 *
 * z, the arcade's zoom of the stage (H, 0x8017AB04: 550 to 800 on a screen
 * 512 wide), becomes the PS1's 500 on its 368: 500 x 512 / 368, the same
 * framing with the PS1's perspective (the user's choice, 2026-10-23). The
 * game's own draws stay as the PS1 makes them, the same count and order
 * (rand, ai_rand_range, lcg_seed): the arcade's values are taken from them,
 * and shot B's three further steps of lcg_seed are made when shot A takes its
 * place, so the rest of the game draws the same. The replay's state lives in
 * the game's (camera_replay_state, its halfwords at a quarter scale, marked
 * in its spare byte +7): save states keep it. The K.O.'s slow motion is the
 * fight's camera in both games: untouched. */
#include "tekken3_arcade_cameras.h"
#include "mod_plugins.h"
#include "tekken3_arcade_stages.h"

#define SCREEN    0x800AE204u    /* 8: a fight */
#define LCG_SEED  0x800A912Cu
#define REPLAY    0x800A04C8u    /* s32 distance, u8 side +4, active +5, restart +6, spare +7, s16 yaw +8, angle +0xE, target +0x10 */
#define REPLAY_ARCADE 0xA7u      /* +7: this replay's angles are the arcade's, at a quarter scale */

/* z x k / 955 with z = 500 x 512 / 368 */
#define ZK(k) ((int32_t)((int64_t)256000 * (k) / (368 * 955)))
#define SHOT_A_NEAR    ZK(0x1450)
#define SHOT_A_RADIUS  (ZK(0x1450) + 0x5A0)
#define REPLAY_NEAR    ((int32_t)((int64_t)256000 * 0x4B840 / (368 * 0x9280)))

/* the arcade's no_pitch by stage (0x8017AB04, +8 of each 10 bytes) */
static const uint8_t NO_PITCH[13] = {1, 1, 1, 1, 0, 2, 0, 0, 1, 1, 1, 2, 1};

static uint32_t s_cap[ARCCAP_COUNT];
static unsigned s_cap_mask;

static int stage(void) {
    if ((int16_t)psx_mod_read_half(SCREEN) != 8) return -1;
    int st = tekken3_arcade_stages_t3_stage();
    return st >= 0 && st < 13 ? st : -1;
}

static int replay_arcade(void) { return psx_mod_read_byte(REPLAY + 7) == REPLAY_ARCADE; }

uint32_t tk3_arccam_v(uint32_t value, int which) {
    switch (which) {        /* the replay: as it was started */
    case ARCREP_LOAD:  return replay_arcade() ? (uint32_t)((int32_t)value * 4) : value;
    case ARCREP_STORE: return replay_arcade() ? (uint32_t)((int32_t)value >> 2) : value;
    case ARCREP_DIST:  return replay_arcade() ? (uint32_t)REPLAY_NEAR : value;
    }
    int st = stage();
    if (st < 0) return value;
    switch (which) {
    case ARCCAM_NO_PITCH:           return NO_PITCH[st];
    case ARCCAM_SHOT_A_CIRCLE:      return 0;   /* the PS1 compares the distance squared with it */
    case ARCCAM_SHOT_A_NEAR:        return SHOT_A_NEAR;
    }
    return value;
}

uint32_t tk3_arccam_k(uint32_t value, uint32_t factor, int which) {
    if (stage() < 0) return value;
    int32_t f = (int32_t)factor;
    switch (which) {
    case ARCCAM_SHOT_A_RADIUS: return (uint32_t)(f * SHOT_A_RADIUS);
    }
    return value;
}

int tk3_arccam_bc(int taken, int which) {
    if (stage() < 0) return taken;
    if (which == ARCCAM_SCENE_START && taken) {
        /* shot B's start steps lcg_seed four times, shot A's once: three
         * more here, before shot A's, as shot B would */
        uint32_t seed = psx_mod_read_word(LCG_SEED);
        for (int i = 0; i < 3; i++) seed = (seed + 1) * 0x10DCDu;
        psx_mod_write_word(LCG_SEED, seed);
    }
    return 0;               /* shot A */
}

uint32_t tk3_arccam_cap(uint32_t value, int which) {
    if (which == ARCCAP_BASE) s_cap_mask = 0;   /* a replay start's first */
    s_cap[which] = value;
    s_cap_mask |= 1u << which;
    return value;
}

uint32_t tk3_arccam_got(int which) { return s_cap[which]; }

/* camera_replay_start, its draws made, before its first update: the
 * arcade's values from them (0x801D6DA8), or the PS1's kept and unmarked */
void tk3_arccam_replay_start(CPUState *cpu) {
    (void)cpu;
    int side = psx_mod_read_byte(REPLAY + 4);
    unsigned need = 1u << ARCCAP_BASE | 1u << ARCCAP_FLIP | 1u << ARCCAP_YAW;
    if (side == 0) need |= 1u << ARCCAP_FROM | 1u << ARCCAP_TO | 1u << ARCCAP_SIGN;
    if (stage() < 0 || (s_cap_mask & need) != need) {
        psx_mod_write_byte(REPLAY + 7, 0);
        s_cap_mask = 0;
        return;
    }
    /* the fight's line (vec_atan2, 12 bits, x 64), a half turn on the
     * PS1's otherwise unused coin, the PS1's draw of the yaw */
    int32_t yaw = ((int32_t)(s_cap[ARCCAP_BASE] << 16) >> 10) + ((s_cap[ARCCAP_FLIP] & 1) ? 0x20000 : 0)
                  + (int32_t)s_cap[ARCCAP_YAW];
    int32_t from = 0, to = 0;
    if (side == 0) {        /* from behind: 25..54 degrees one way to the other */
        yaw -= 0x71C7;
        from = ((int32_t)(s_cap[ARCCAP_FROM] + 25) << 18) / 360;
        to = -(((int32_t)(s_cap[ARCCAP_TO] + 25) << 18) / 360);
        if (s_cap[ARCCAP_SIGN] & 1) { from = -from; to = -to; }
    } else {                /* side: within 60 degrees of the fight's line */
        yaw -= 0xAAAA;
    }
    psx_mod_write_word(REPLAY, (uint32_t)(2 * REPLAY_NEAR));
    psx_mod_write_half(REPLAY + 8, (uint16_t)(yaw >> 2));
    psx_mod_write_half(REPLAY + 14, (uint16_t)(from >> 2));
    psx_mod_write_half(REPLAY + 16, (uint16_t)(to >> 2));
    psx_mod_write_byte(REPLAY + 7, REPLAY_ARCADE);
    s_cap_mask = 0;
}
