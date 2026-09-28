#include "tekken3_fight_camera.h"
#include "mod_plugins.h"
#include <string.h>

static int wide_fights_enabled;
static int32_t fight_yaw;

void tekken3_fight_camera_capture_yaw(CPUState* cpu)
{
    /* Camera 0 is the combat view; camera 1 is the throw/replay inset. */
    if (psx_mod_read_word(cpu->gpr[29]+0x120)==0)
        fight_yaw=(int32_t)cpu->gpr[7];
}
int32_t tekken3_fight_camera_yaw(void) { return fight_yaw; }

static void activate_fight_camera(void)
{
    char option[16];
    wide_fights_enabled = 1;
    if (psx_mod_option_value("tekken3.enhancement.true-widescreen",
                            "true-widescreen", "wide-fights",
                            option, sizeof(option)))
        wide_fights_enabled = strcmp(option, "false") != 0 && strcmp(option, "0") != 0;
}

uint32_t tekken3_fight_camera_focal(CPUState* cpu)
{
    return tekken3_fight_focal_policy(cpu->gpr[18], wide_fights_enabled,
        psx_mod_widescreen_x_margin(), psx_mod_read_word(0x800AFA88u),
        cpu->gpr[12]);
}

PSX_MOD_CONSTRUCTOR(register_fight_camera)
{
    (void)psx_mod_register_activation_plugin("tekken3.fight-camera",
                                            activate_fight_camera);
}
