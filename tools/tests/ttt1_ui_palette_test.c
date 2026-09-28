/* Exercise native palette animation and loader writes around a menu. */
#include <assert.h>
#include <stdio.h>
#include "../../src/tekken3_ttt1_ui_palette.h"
static uint16_t vram[512][256];
void gr_vram_transfer_in(int x,int y,int w,int h,const uint16_t *p) {
    assert(x==0 && w==256 && h==1);memcpy(vram[y],p,512);
}
void gr_vram_transfer_out(int x,int y,int w,int h,uint16_t *p) {
    assert(x==0 && w==256 && h==1);memcpy(p,vram[y],512);
}
int main(void) {
    Ttt1UiPalette selector={0},loading={0};
    uint16_t portrait[256],thumbnail[256];
    for(unsigned i=0;i<256;i++) {
        vram[502][i]=i;vram[503][i]=1000+i;
        portrait[i]=2000+i;thumbnail[i]=3000+i;
    }
    ttt1_ui_palette_upload(&selector,502,portrait);
    ttt1_ui_palette_upload(&loading,503,thumbnail);
    assert(vram[502][79]==2079 && vram[503][79]==3079);
    /* A native animated effect updates its CLUT during loading. */
    vram[503][4]=9999;
    ttt1_ui_palette_upload(&loading,503,thumbnail);
    assert(vram[503][4]==3004);
    /* A final native upload after the last menu frame must also survive. */
    vram[503][5]=9998;
    ttt1_ui_palette_release(&selector,502);
    ttt1_ui_palette_release(&loading,503);
    assert(vram[503][4]==9999 && vram[503][5]==9998);
    for(unsigned i=0;i<256;i++) {
        assert(vram[502][i]==i);
        if(i!=4 && i!=5)assert(vram[503][i]==1000+i);
    }
    /* Repeated release is inert; another match captures the new native row. */
    vram[503][79]=0;
    ttt1_ui_palette_release(&loading,503);
    ttt1_ui_palette_upload(&loading,503,thumbnail);
    ttt1_ui_palette_release(&loading,503);
    assert(vram[503][79]==0);
    puts("PASS: menu palette restoration preserves native effects and updates");
}
