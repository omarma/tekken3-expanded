/* Tekken 5 DR Content (mods/local-packages/tekken3.character.dr): the mod's
 * one feature, on or off in the mods menu, PC and Android. On, the Dark
 * Resurrection content the setup imported from the player's PSP disc is in
 * the game (for now Jin's DR moveset, natives.txt's "dr" lines, PSP-DR.md A4);
 * off, or without the package, none of it is: natives.txt's "dr" lines are
 * left out (src/tekken3_native_moves.c), so the MOVESET card, CPU MOVESET and
 * the loads never see a <Name>-DR-* file. The runtime calls the activation
 * at boot when the feature is on: a change takes a restart, as TTT Stages. */
#include "mod_plugins.h"
#include <stdio.h>

static int enabled;
static void activate(void) {
    if(!enabled)fprintf(stderr,"Tekken 5 DR Content: on\n");
    enabled=1;
}
int tekken3_dr_content_enabled(void) { return enabled; }
PSX_MOD_CONSTRUCTOR(register_dr_content) {
    (void)psx_mod_register_activation_plugin("tekken3.dr-content",activate);
}
