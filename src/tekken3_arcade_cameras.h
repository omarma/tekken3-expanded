#pragma once
/* B87: Tekken 3 arcade's end-of-round cameras on its stages (Arcade Stages),
 * the loser's view excepted (B110).
 * Hooks of the routines tools/build_arcade_cameras.py rebuilds from the
 * recompiled source: each returns the PS1's operand unchanged unless a T3
 * arcade stage is drawn in a fight (or, for the replay, the replay was
 * started with the arcade's camera), then the arcade's. */
#include <stdint.h>
#include "cpu_state.h"

enum {
    ARCCAM_NO_PITCH,            /* camera_work_no_pitch read: the stage's, from the arcade's table */
    ARCCAM_SHOT_A_CIRCLE,       /* the PS1's circle of 5800 around the winner (the arcade has none) */
    ARCCAM_SHOT_A_RADIUS,       /* shot A's start distance, x sin / cos */
    ARCCAM_SHOT_A_NEAR,         /* shot A comes no nearer */
    ARCCAM_SCENE_START,         /* camera_end_scene_start: shot B taken (the arcade: shot A always) */
    ARCCAM_SCENE_UPDATE,
    ARCREP_LOAD,                /* replay angles: halfwords at a quarter scale */
    ARCREP_STORE,
    ARCREP_DIST,                /* the distance the replay camera eases to */
};

enum { ARCCAP_BASE, ARCCAP_FLIP, ARCCAP_YAW, ARCCAP_FROM, ARCCAP_TO, ARCCAP_SIGN, ARCCAP_COUNT };

uint32_t tk3_arccam_v(uint32_t value, int which);
uint32_t tk3_arccam_k(uint32_t value, uint32_t factor, int which);
int tk3_arccam_bc(int taken, int which);
uint32_t tk3_arccam_cap(uint32_t value, int which);
uint32_t tk3_arccam_got(int which);
void tk3_arccam_replay_start(CPUState *cpu);
