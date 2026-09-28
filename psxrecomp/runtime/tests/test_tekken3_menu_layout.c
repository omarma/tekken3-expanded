#include "tekken3_selector_layout.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static const Tekken3SelectorPacket team_capture[] = {
#include "fixtures/tekken3_team_packets.inc"
};
static const Tekken3SelectorPacket menu_capture[] = {
#include "fixtures/tekken3_menu_packets.inc"
};

static void verify(const Tekken3SelectorPacket *captured, size_t count,
                   int kind, int address_delta) {
    Tekken3SelectorPacket packets[512];
    Tekken3SelectorFrame frame;
    assert(count <= 512);
    memcpy(packets, captured, count * sizeof(*packets));
    for (size_t i=0; i<count; i++) packets[i].source_addr += address_delta;
    assert(tekken3_selector_analyze_frame(packets,count,368,480,&frame));
    assert(frame.layout_kind == kind);
    assert(tekken3_selector_can_retain_frame(&frame,NULL,0,368,480));
    assert(!tekken3_selector_can_retain_frame(&frame,NULL,0,320,240));
    Tekken3SelectorPacket foreign = {0x180000,0x40,10,10,1,10};
    assert(!tekken3_selector_can_retain_frame(&frame,&foreign,1,368,480));
    assert(tekken3_selector_place(&frame,&foreign,61).role == TEKKEN3_SELECTOR_NONE);
    int portrait_parts=0, bevels=0, backgrounds=0, bar=0;
    for (size_t i=0; i<count; i++) {
        const Tekken3SelectorPacket *p = &packets[i];
        Tekken3SelectorPlacement wide=tekken3_selector_place(&frame,p,61);
        Tekken3SelectorPlacement original=tekken3_selector_place(&frame,p,0);
        assert(!original.sidecar_dx && !original.expand_backdrop &&
               !original.unclipped_sidecar && !original.suppress_sidecar);
        if (kind == 1 && p->opcode == 0x65 && p->height >= 32) {
            assert(wide.sidecar_dx == 0 && !wide.expand_backdrop);
            backgrounds++;
        }
        if (kind == 1 && p->opcode == 0x38) {
            assert(wide.expand_backdrop);
            bar++;
        }
        if (kind == 2 && p->y >= 67 && p->y+p->height <= 257 &&
            (p->opcode == 0x40 || (p->opcode == 0x65 && p->width == 32))) {
            assert(wide.role == TEKKEN3_SELECTOR_ROSTER);
            /* Every vertical bevel lies on its portrait's anchor, including
             * the rightmost edge only one pixel from the next original cell. */
            int cell = (p->x + p->width/2 - 57) / 36;
            assert(wide.group_id == 4u+(unsigned)cell);
            assert(wide.sidecar_dx == 0);
            if (p->opcode == 0x40) bevels++; else portrait_parts++;
        }
    }
    if (kind == 1) assert(backgrounds == 24 && bar == 6);
    else assert(portrait_parts == 23 && bevels == 210);
    if (kind == 1) {
        /* Real navigation frames omit all six highlight quads. Their logo,
         * glyphs and fade masks still establish the menu in either buffer. */
        Tekken3SelectorPacket navigation[512];
        size_t used = 0;
        for (size_t i=0; i<count; i++)
            if (packets[i].opcode != 0x38) navigation[used++] = packets[i];
        assert(tekken3_selector_analyze_frame(navigation,used,368,480,&frame));
        assert(frame.layout_kind == 1);
        for (size_t i=0; i<used; i++)
            if (navigation[i].opcode == 0x3A) navigation[i].height = 27;
        assert(!tekken3_selector_analyze_frame(navigation,used,368,480,&frame));
    }
    /* Incomplete tile coverage or absent roster must not claim another UI. */
    assert(!tekken3_selector_analyze_frame(packets,1,368,480,&frame));
    assert(!tekken3_selector_analyze_frame(packets,count,320,480,&frame));
    for (size_t i=0; i<count; i++) packets[i].source_addr = 0x190000;
    assert(!tekken3_selector_analyze_frame(packets,count,368,480,&frame));
}

static void verify_expanded_team(int buffer) {
    uint32_t base=0xb8000+buffer*0x3c00;
    Tekken3SelectorPacket packets[25]={
        {base,0x60,0,0,368,480},
        {base+0x20,0x38,0,277,368,128},
        {base+0x40,0x38,0,405,368,75}
    };
    for(int i=0;i<22;i++)
        packets[3+i]=(Tekken3SelectorPacket){base+0x60+i*0x20,0x65,43+(i%8)*36,70+(i/8)*63,32,58};
    Tekken3SelectorFrame frame;
    assert(tekken3_selector_analyze_frame(packets,25,368,480,&frame));
    assert(frame.layout_kind==2 && frame.roster_columns==8);
    for(int i=0;i<22;i++) {
        Tekken3SelectorPlacement face=tekken3_selector_place(&frame,&packets[i+3],61);
        Tekken3SelectorPacket bevel={base+0x800,0x40,41+(i%8)*36,67+(i/8)*63,36,1};
        Tekken3SelectorPlacement border=tekken3_selector_place(&frame,&bevel,61);
        assert(face.role==TEKKEN3_SELECTOR_ROSTER && border.group_id==face.group_id);
        assert(face.sidecar_dx==border.sidecar_dx);
        assert(face.sidecar_dx==0);
        assert(tekken3_selector_place(&frame,&packets[i+3],0).sidecar_dx==0);
    }
    assert(!tekken3_selector_analyze_frame(packets,24,368,480,&frame));
}

/* The TTT1 guests' Tag page: rows of six from x=77, as many cells as guests. */
static void verify_six_page(int buffer, int guests) {
    uint32_t base=0xb8000+buffer*0x3c00;
    Tekken3SelectorPacket packets[21]={
        {base,0x60,0,0,368,480},
        {base+0x20,0x38,0,277,368,128},
        {base+0x40,0x38,0,405,368,75}
    };
    for(int i=0;i<guests;i++)
        packets[3+i]=(Tekken3SelectorPacket){base+0x60+i*0x20,0x65,77+(i%6)*36,70+(i/6)*63,32,58};
    Tekken3SelectorFrame frame;
    assert(tekken3_selector_analyze_frame(packets,3+guests,368,480,&frame));
    assert(frame.layout_kind==2 && frame.roster_columns==6);
    /* A hole in the page is not a page. */
    packets[3+1].x=77+5*36; packets[3+1].y=70+2*63;
    assert(!tekken3_selector_analyze_frame(packets,3+guests,368,480,&frame));
}

int main(void) {
    int held = tekken3_gameplay_retain(0,1,1,1,0,368,480,0);
    assert(held);
    /* Gameplay state expires during a CD wait, but no picture replaces it.
     * This must remain independent of elapsed frames or classifier age. */
    for (int i=0; i<600; i++) {
        held = tekken3_gameplay_retain(held,1,0,0,0,368,480,0);
        assert(held);
    }
    assert(!tekken3_gameplay_retain(0,1,0,0,0,368,480,0));
    assert(!tekken3_gameplay_retain(held,1,1,0,0,368,480,0));
    assert(!tekken3_gameplay_retain(held,1,0,0,1,368,480,0));
    assert(!tekken3_gameplay_retain(held,1,0,0,0,368,480,1));
    assert(!tekken3_gameplay_retain(held,1,0,0,0,320,480,0));
    assert(!tekken3_gameplay_retain(held,1,0,0,0,368,240,0));
    assert(!tekken3_gameplay_retain(held,0,1,1,0,368,480,0));
    for (int buffer=0; buffer<2; buffer++) {
        verify_expanded_team(buffer);
        verify_six_page(buffer,18);
        verify_six_page(buffer,8);
        verify(team_capture,sizeof(team_capture)/sizeof(*team_capture),2,buffer*0x3C00);
        verify(menu_capture,sizeof(menu_capture)/sizeof(*menu_capture),1,-buffer*0x3C00);
    }
    puts("PASS: main menu and Team Battle captures, both buffers, bevels and 4:3 guards");
    return 0;
}
