#include "tekken3_anna_skin_match.h"
#include <assert.h>
static uint16_t vram[512*1024], blue[512*1024];
static const HdTextureTile *find_tile(HdTextureMap *m, unsigned i, int guarded) {
    const HdTextureTile *t = &m->tiles[i];
    int factor=t->depth ? 2 : 4,tx=(int)t->x/64*64,ty=(int)t->y/256*256;
    int u[3]={(int)(t->x-tx)*factor,(int)(t->x+t->w-tx)*factor-1,(int)(t->x-tx)*factor};
    int v[3]={(int)t->y-ty,(int)t->y-ty,(int)(t->y+t->h)-ty-1};
    return (guarded ? tekken3_anna_skin_find : hd_map_find)(m,vram,tx,ty,(int)t->depth,
                                                         (int)t->cx,(int)t->cy,u,v);
}
int main(int argc,char **argv) {
    assert(argc==4); HdTextureMap m={0};
    FILE *f=fopen(argv[2],"rb");assert(f);assert(fread(vram,2,512*1024,f)==512*1024);fclose(f);
    f=fopen(argv[3],"rb");assert(f);assert(fread(blue,2,512*1024,f)==512*1024);fclose(f);
    assert(hd_map_load(&m,argv[1]));assert(m.count==32);
    for(unsigned i=0;i<16;i++) assert(find_tile(&m,i,1));
    for(int y=0;y<224;y++) memcpy(&vram[(y+256)*1024+384],&vram[y*1024+384],64*2);
    for(int y=0;y<2;y++) memcpy(&vram[(508+y)*1024],&vram[(504+y)*1024],256*2);
    ++m.generation;
    for(unsigned i=0;i<32;i++) assert(find_tile(&m,i,1));
    /* Real blue costume data in P1, red remains in P2. Hair still has the same
     * identity, but the additional costume check must reject ALL P1 edits. */
    for(int y=0;y<224;y++) memcpy(&vram[y*1024+384],&blue[y*1024+384],64*2);
    for(int y=0;y<2;y++) memcpy(&vram[(504+y)*1024],&blue[(504+y)*1024],256*2);
    ++m.generation;
    assert(find_tile(&m,13,0)); assert(find_tile(&m,12,0));
    for(unsigned i=0;i<16;i++) assert(!find_tile(&m,i,1));
    for(unsigned i=16;i<32;i++) assert(find_tile(&m,i,1));
    hd_map_clear(&m);
    puts("Anna: red gown matches both slots; shared hair/legs in blue gown rejected independently");
    return 0;
}
