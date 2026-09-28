/* Standalone contract checks for the renderer's guarded host texture map. */
#include "gpu_hd_texture_match.h"
#include <assert.h>

static uint16_t vram[512*1024];
static void fixture(const char *path, int bad) {
    FILE *f=fopen(path,"wb"); assert(f);
    uint32_t count=1, bounds[6]={560,64,16,64,224,499}, kind=2;
    uint64_t hashes[2]={hd_hash_rect(vram,560,64,16,64),hd_hash_rect(vram,224,499,16,1)};
    float transform[6]={1.0f/63,0,-2240.0f/63,0,1.0f/63,-64.0f/63};
    if (bad==1) bounds[0]=1020;
    if (bad==2) transform[0]=NAN;
    fwrite("HDMAP001",1,8,f); fwrite(&count,4,1,f); fwrite(bounds,4,6,f);
    if (bad!=3) {
        fwrite(hashes,8,2,f); fwrite(transform,4,6,f); fwrite(&kind,4,1,f);
    }
    fclose(f);
}
int main(int argc,char **argv) {
    assert(argc==2);
    for(int i=0;i<512*1024;++i) vram[i]=(uint16_t)(i*13+7);
    HdTextureMap map={0}; int u[3]={192,255,192},v[3]={64,64,127};
    fixture(argv[1],0); assert(hd_map_load(&map,argv[1]));
    assert(hd_map_find(&map,vram,512,0,0,224,499,u,v));
    assert(!hd_map_find(&map,vram,512,0,1,224,499,u,v));
    assert(!hd_map_find(&map,vram,512,0,0,240,499,u,v));
    u[1]=256; assert(!hd_map_find(&map,vram,512,0,0,224,499,u,v));u[1]=255;
    /* Another stage using the same VRAM placement must not match. */
    vram[64*1024+560]^=1; ++map.generation;
    assert(!hd_map_find(&map,vram,512,0,0,224,499,u,v));
    vram[64*1024+560]^=1; ++map.generation;
    assert(hd_map_find(&map,vram,512,0,0,224,499,u,v));
    vram[499*1024+239]^=1; ++map.generation;
    assert(!hd_map_find(&map,vram,512,0,0,224,499,u,v));
    for(int bad=1;bad<=3;++bad) {fixture(argv[1],bad);assert(!hd_map_load(&map,argv[1]));assert(!map.count);}
    hd_map_clear(&map); remove(argv[1]);
    puts("HD texture map: bounds, texture identity, shared palette, invalidation and malformed-file checks passed");
    return 0;
}
