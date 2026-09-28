#pragma once
#include <stdint.h>
#include "cpu_state.h"

/* The fight camera's horizontal fit uses a virtual focal length. The GTE
 * still receives the original focal length, so models retain their shape. */
static inline uint32_t tekken3_fight_focal_policy(uint32_t focal, int enabled,
                                                int margin, uint32_t mode,
                                                uint32_t camera_index)
{
    /* Modes 0..5 are regular battles (5 = Practice); exclude modes 6/7.
     * Camera 1 is the alternate/cinematic camera and keeps its authored fit. */
    if (!enabled || margin <= 0 || margin > 61 || mode > 5 ||
        camera_index != 0 || focal == 0 || focal > 32767)
        return focal;
    return (uint32_t)(((uint64_t)focal * 368u + (368u + 2u * margin) / 2u) /
                      (368u + 2u * margin));
}

uint32_t tekken3_fight_camera_focal(CPUState* cpu);
void tekken3_fight_camera_capture_yaw(CPUState* cpu);
int32_t tekken3_fight_camera_yaw(void);
