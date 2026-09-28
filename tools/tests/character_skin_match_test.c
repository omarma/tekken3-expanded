/* Check independently loaded skin maps against a local VRAM capture. */
#include "gpu_hd_texture_match.h"
#include <assert.h>
static uint16_t vram[512*1024];
static const HdTextureTile *find_tile(HdTextureMap *m, const HdTextureTile *t) {
    int factor=t->depth ? 2 : 4;
    int tx=(int)t->x/64*64,ty=(int)t->y/256*256;
    int u[3]={(int)(t->x-tx)*factor,(int)(t->x+t->w-tx)*factor-1,(int)(t->x-tx)*factor};
    int v[3]={(int)t->y-ty,(int)t->y-ty,(int)(t->y+t->h)-ty-1};
    return hd_map_find(m,vram,tx,ty,(int)t->depth,(int)t->cx,(int)t->cy,u,v);
}
int main(int argc,char **argv) {
    assert(argc==4);HdTextureMap active={0},other={0};
    FILE *f=fopen(argv[3],"rb");assert(f);
    assert(fread(vram,2,512*1024,f)==512*1024);fclose(f);
    assert(hd_map_load(&active,argv[1]));assert(hd_map_load(&other,argv[2]));
    assert(active.count>0 && !(active.count%2));
    unsigned half=active.count/2;
    for(unsigned i=0;i<half;i++) assert(find_tile(&active,&active.tiles[i]));
    for(unsigned i=half;i<active.count;i++) assert(!find_tile(&active,&active.tiles[i]));
    for(unsigned i=0;i<other.count;i++) assert(!find_tile(&other,&other.tiles[i]));
    /* Relocation follows the game's verified player-slot texture layout. */
    for(int y=0;y<224;y++) memcpy(&vram[(y+256)*1024+384],&vram[y*1024+384],64*2);
    for(int y=0;y<2;y++) memcpy(&vram[(508+y)*1024],&vram[(504+y)*1024],256*2);
    ++active.generation;++other.generation;
    for(unsigned i=0;i<active.count;i++) assert(find_tile(&active,&active.tiles[i]));
    for(unsigned i=0;i<other.count;i++) assert(!find_tile(&other,&other.tiles[i]));
    /* Changing one skin's state must not mutate the other map. */
    unsigned other_count=other.count;
    HdTextureTile *first=&active.tiles[0];assert(first->depth==0 || first->depth==1);
    unsigned last_color=first->depth==0 ? 15 : 255;
    vram[first->cy*1024+first->cx+last_color]^=1;++active.generation;
    assert(!find_tile(&active,first));assert(find_tile(&active,&active.tiles[half]));
    vram[first->cy*1024+first->cx+last_color]^=1;++active.generation;
    assert(find_tile(&active,first));
    vram[first->y*1024+first->x]^=1;++active.generation;
    assert(!find_tile(&active,first));
    hd_map_clear(&active);assert(other.count==other_count);
    hd_map_clear(&other);
    puts("Character skins: both player placements, 4/8bpp guards, cross-skin rejection and independent invalidation passed");
    return 0;
}
