/* Validate real costume fingerprints and player relocation against a local
 * VRAM capture. No retail bytes are embedded in the test. */
#include "gpu_hd_texture_match.h"
#include <assert.h>
static uint16_t vram[512*1024];
static const HdTextureTile *find_tile(HdTextureMap *m, const HdTextureTile *t) {
    int factor=t->depth ? 2 : 4;
    int tx=(int)t->x/64*64, ty=(int)t->y/256*256;
    int u[3]={(int)(t->x-tx)*factor,(int)(t->x+t->w-tx)*factor-1,(int)(t->x-tx)*factor};
    int v[3]={(int)t->y-ty,(int)t->y-ty,(int)(t->y+t->h)-ty-1};
    return hd_map_find(m,vram,tx,ty,(int)t->depth,(int)t->cx,(int)t->cy,u,v);
}
int main(int argc,char **argv) {
    assert(argc==3); HdTextureMap map={0};
    FILE *f=fopen(argv[2],"rb"); assert(f);
    assert(fread(vram,2,512*1024,f)==512*1024); fclose(f);
    assert(hd_map_load(&map,argv[1])); assert(map.count==26);
    for(unsigned i=0;i<13;i++) assert(find_tile(&map,&map.tiles[i]));
    /* Yoshimitsu currently occupies P2: no Nina replacements there. */
    for(unsigned i=13;i<26;i++) assert(!find_tile(&map,&map.tiles[i]));
    /* The second player's loader relocates the same tiles by 256 rows and
     * palettes by four rows. Check every mapped tile in that placement. */
    for(int y=0;y<224;y++) memcpy(&vram[(y+256)*1024+384],&vram[y*1024+384],64*2);
    for(int y=0;y<2;y++) memcpy(&vram[(508+y)*1024],&vram[(504+y)*1024],256*2);
    ++map.generation;
    for(unsigned i=0;i<26;i++) assert(find_tile(&map,&map.tiles[i]));
    /* 8bpp checks all 256 palette words, including an unused last entry. */
    vram[504*1024+255]^=1; ++map.generation;
    assert(!find_tile(&map,&map.tiles[0]));
    assert(find_tile(&map,&map.tiles[13]));
    vram[504*1024+255]^=1; ++map.generation;
    assert(find_tile(&map,&map.tiles[0]));
    vram[384]^=1; ++map.generation;
    assert(!find_tile(&map,&map.tiles[0]));
    hd_map_clear(&map);
    puts("Nina skin: 4/8bpp identity, both player placements, other-fighter rejection and invalidation passed");
    return 0;
}
