/* Built only without the TTT1 characters mod (-DTEKKEN3_TTT1_CHARACTERS=OFF,
 * a setup without tektagt.zip): what the always-built code calls in the mod's
 * sources, answered as the mod would with nothing staged.
 * tools/test_ttt1_off_link.py fails when a new call has no answer here. */
#include "tekken3_cine_scene.h"

/* No cinematic engine: the pace stays the player's (psxrecomp main.cpp). */
int tekken3_cine_scene_turbo(void) { return 0; }
