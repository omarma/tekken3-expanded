/* Reject Panda and preserve Kuma's accessories while replacing only fur. */
#include "gpu_hd_texture_match.h"
#include <assert.h>
static uint16_t vram[512*1024];
static const HdTextureTile *find(HdTextureMap *m,const HdTextureTile *t) {
 int tx=t->x/64*64,ty=t->y/256*256;
 int u[3]={(t->x-tx)*4,(t->x+t->w-tx)*4-1,(t->x-tx)*4};
 int v[3]={t->y-ty,t->y-ty,t->y+t->h-ty-1};
 return hd_map_find(m,vram,tx,ty,0,t->cx,t->cy,u,v);
}
int main(int argc,char **argv) {
 assert(argc==4);HdTextureMap m={0};assert(hd_map_load(&m,argv[1]));assert(m.count==22);
 for(int costume=0;costume<2;costume++) {
  FILE *f=fopen(argv[2+costume],"rb");assert(f);
  assert(fread(vram,2,512*1024,f)==512*1024);fclose(f);++m.generation;
  for(unsigned i=0;i<m.count;i++)assert(!!find(&m,&m.tiles[i])==(costume==0 && i<11));
  /* Real triangles for the bandana, claw tile, cuff and stud remain stock. */
  const unsigned parts[5][6]={{384,0,8,64,0,504},{400,64,2,16,48,504},
   {384,192,16,32,0,504},{400,96,2,16,112,504},{400,112,4,16,128,504}};
  for(int i=0;i<5;i++) {
   HdTextureTile t={0};t.x=parts[i][0];t.y=parts[i][1];t.w=parts[i][2];t.h=parts[i][3];t.cx=parts[i][4];t.cy=parts[i][5];
   assert(!find(&m,&t));
  }
 }
 hd_map_clear(&m);puts("PASS: 11 Kuma fur tiles match; all Panda tiles and original accessories stay stock");
}
