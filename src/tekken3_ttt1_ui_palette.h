/* Menu CLUTs temporarily share the resident effects rows. Preserve native
 * updates while the menu owns them, and return the rows when it closes. */
#ifndef TEKKEN3_TTT1_UI_PALETTE_H
#define TEKKEN3_TTT1_UI_PALETTE_H
#include <stdint.h>
#include <string.h>
#include "gpu_render.h"
typedef struct Ttt1UiPalette {
    uint16_t native[256], uploaded[256];
    int active;
} Ttt1UiPalette;

static void ttt1_ui_palette_upload(Ttt1UiPalette *p, unsigned y, const uint16_t *colors) {
    uint16_t current[256];
    gr_vram_transfer_out(0,y,256,1,current);
    for(unsigned i=0;i<256;i++)
        if(!p->active || current[i]!=p->uploaded[i])p->native[i]=current[i];
    memcpy(p->uploaded,colors,sizeof p->uploaded);
    p->active=1;
    gr_vram_transfer_in(0,y,256,1,colors);
}

static void ttt1_ui_palette_release(Ttt1UiPalette *p, unsigned y) {
    if(!p->active)return;
    uint16_t current[256];
    gr_vram_transfer_out(0,y,256,1,current);
    /* A loader or palette animation may already have replaced some entries.
     * Restore only pixels still owned by this menu. */
    for(unsigned i=0;i<256;i++)
        if(current[i]==p->uploaded[i])current[i]=p->native[i];
    gr_vram_transfer_in(0,y,256,1,current);
    p->active=0;
}
#endif
