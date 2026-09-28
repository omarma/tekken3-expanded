#pragma once
#include <stdint.h>
/* Explicit preview override, otherwise the private pack beside the executable. */
const char *tekken3_ttt1_asset_root(void);

/* Identity of the character currently occupying the guest slot. The asset
 * files are named "<prefix>-...": "Jun-TTT1-combat.jmv", "Kazuya-T3-ui.jui".
 * Two prefixes because the arcade data and the PS1 interface artwork come
 * from different sources and keep different names. */
const char *tekken3_guest_data_prefix(void);   /* "Jun-TTT1"  */
const char *tekken3_guest_ui_prefix(void);     /* "Jun-T3"    */

/* Zero while a character's output hashes are not frozen yet. Loaders then
 * keep every structural check and skip only the identity comparison, which is
 * what iterating on a new import needs - freezing them too early turns each
 * asset rebuild into a failed launch. */
int tekken3_guest_digests_frozen(void);

/* TTT1 catalogue (guests.txt in the asset root): the guest slot's identity is
 * switched at the selector. Zero when a single guest is chosen at launch. */
int tekken3_guest_catalog_mode(void);
const char *tekken3_guest_label(void);          /* "KAZUYA", "P.JACK"      */
const char *tekken3_guest_name(void);           /* "Kazuya", "P.Jack": logs */

/* Per player (0 or 1): the guest that player has chosen. The generation
 * changes with the identity, so a module reloads when it differs from the one
 * it loaded. The functions without a player are player 1's. */
const char *tekken3_guest_data_prefix_for(unsigned player);
const char *tekken3_guest_ui_prefix_for(unsigned player);
const char *tekken3_guest_label_for(unsigned player);
const char *tekken3_guest_name_for(unsigned player);
unsigned tekken3_guest_generation(unsigned player);
/* 0 punch, 1 kick, 2 Start: selects <data prefix>-arcade-P1/P2/P3. */
unsigned tekken3_guest_costume(unsigned player);
/* The guest's TTT1 moveset key (0x29EF00), 32 when unknown: what the other
 * guest's opponent-specific hit rules test. */
unsigned tekken3_guest_moveset(unsigned player);
/* Moveset drawn at random (Tetsujin): files and generation of the moves. */
const char *tekken3_guest_moves_prefix_for(unsigned player);
unsigned tekken3_guest_moves_generation(unsigned player);
int tekken3_guest_draw_moveset(unsigned player);
/* Moveset switched on L1 in the fight (Unknown): whether the player's guest
 * does it, a pending request (consumed a frame at a time), the switch. */
int tekken3_guest_switches_on_button(unsigned player);
int tekken3_guest_switch_request(unsigned player);
void tekken3_guest_switch_done(unsigned player);
int tekken3_guest_switch_moveset(unsigned player);
int tekken3_guest_switch_undo(unsigned player);

/* Guest memory of one player's guest, emptied when that guest changes. */
uint32_t tekken3_guest_pool_alloc(unsigned slot, uint32_t size, uint32_t alignment);
void tekken3_guest_pool_reset(unsigned slot);
/* The player's other area, emptied: the moves switched in the fight (Unknown). */
void tekken3_guest_pool_flip(unsigned slot);
