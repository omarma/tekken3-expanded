#ifndef TEKKEN3_OUTFITS_H
#define TEKKEN3_OUTFITS_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
enum { T3_SKIN_NINA, T3_SKIN_XIAOYU, T3_SKIN_ANNA, T3_SKIN_KUMA,
       T3_SKIN_EDDY, T3_SKIN_JULIA, T3_SKIN_HEIHACHI, T3_SKIN_COUNT };
typedef struct Tekken3OutfitEntry {
    char id[48], name[40], art[64];
    int character, skin;
    uint16_t confirm;
} Tekken3OutfitEntry;
typedef struct Tekken3OutfitView {
    int visible, character, custom, locked, has_extra;
    const char *name;
    int index, count, menu;
} Tekken3OutfitView;
void tekken3_outfits_set_available(int skin, int available);
int tekken3_outfits_available(void);
int tekken3_outfits_load_catalog(const char *path);
const Tekken3OutfitEntry *tekken3_outfits_entry(int character, int index);
int tekken3_outfits_count(int character);
void tekken3_outfits_update(int selecting, int character1, int character2);
void tekken3_outfits_sync(void);
void tekken3_outfits_tick(void); /* exactly once per guest VBlank */
void tekken3_outfits_connect(int player, int connected);
uint16_t tekken3_outfits_input(int player, uint16_t buttons);
int tekken3_outfits_open(int player);
int tekken3_outfits_menu_player(void);
int tekken3_outfits_cycle(int player, int direction);
void tekken3_outfits_close(int accept);
Tekken3OutfitView tekken3_outfits_view(int player);
int tekken3_outfits_skin_enabled(int skin, int clut_y);
#ifdef __cplusplus
}
#endif
#endif
