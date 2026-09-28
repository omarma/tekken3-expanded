/* Host gallery: stock punch/kick/Start costume paths, per-player cosmetics. */
#include "tekken3_outfits.h"
#include "mod_plugins.h"
#include "gpu.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
static const Tekken3OutfitEntry defaults[] = {
 {"nina-purple","PURPLE ASSASSIN","nina-purple",5,-1,0x8000},
 {"nina-crimson","CRIMSON LEATHER","nina-crimson",5,-1,0x4000},
 {"nina-white","WHITE SATIN","nina-white",5,T3_SKIN_NINA,0x4000},
 {"xiaoyu-red","RED & GOLD","xiaoyu-red",7,-1,0x8000},
 {"xiaoyu-blue","BLUE RIBBON","xiaoyu-blue",7,-1,0x4000},
 {"xiaoyu-school","SCHOOL UNIFORM","xiaoyu-school",7,-1,0x0008},
 {"xiaoyu-pink","CHERRY BLOSSOM","xiaoyu-pink",7,T3_SKIN_XIAOYU,0x8000},
 {"anna-red","SCARLET SILK","anna-red",18,-1,0x8000},
 {"anna-blue","MIDNIGHT SILK","anna-blue",18,-1,0x4000},
 {"anna-tiger","WHITE TIGER","anna-tiger",18,-1,0x0008},
 {"anna-jessica","JESSICA RABBIT","anna-jessica",18,T3_SKIN_ANNA,0x8000},
 {"kuma-brown","BROWN BEAR","kuma-brown",11,-1,0x8000},
 {"kuma-panda","PANDA","kuma-panda",11,-1,0x4000},
 {"kuma-polar","POLAR BEAR","kuma-polar",11,T3_SKIN_KUMA,0x8000},
 {"eddy-original-1","ORIGINAL OUTFIT 1","eddy-original-1",8,-1,0x8000},
 {"eddy-original-2","ORIGINAL OUTFIT 2","eddy-original-2",8,-1,0x4000},
 {"eddy-tiger","TIGER JACKSON","eddy-tiger",8,-1,0x0008},
 {"eddy-monochrome","MONOCHROME","eddy-monochrome",8,T3_SKIN_EDDY,0x8000},
 {"julia-original-1","ORIGINAL OUTFIT 1","julia-original-1",10,-1,0x8000},
 {"julia-original-2","ORIGINAL OUTFIT 2","julia-original-2",10,-1,0x4000},
 {"julia-blue","BLUE TURQUOISE","julia-blue",10,T3_SKIN_JULIA,0x8000},
 {"heihachi-original-1","ORIGINAL OUTFIT 1","heihachi-original-1",13,-1,0x8000},
 {"heihachi-original-2","ORIGINAL OUTFIT 2","heihachi-original-2",13,-1,0x4000},
 {"heihachi-tiger-coat","TIGER COAT","heihachi-tiger-coat",13,T3_SKIN_HEIHACHI,0x4000}
};
static Tekken3OutfitEntry *catalog;
static int catalog_count,available[T3_SKIN_COUNT];
static const int skin_characters[T3_SKIN_COUNT]={5,7,18,11,8,10,13};
static int selecting,character[2]={-1,-1},connected[2],locked[2];
static int choice[2][24],committed[2]={-1,-1},pending[2];
static uint16_t confirmation[2],previous[2]={0xffff,0xffff},suppress[2];
static int menu=-1,before_menu;
static uint32_t borrowed_flags;
static int valid_entry(const Tekken3OutfitEntry *e) {
 if(e->character<0 || e->character>=24 || e->skin < -1 || e->skin>=T3_SKIN_COUNT)return 0;
 if(e->skin>=0 && skin_characters[e->skin]!=e->character)return 0;
 if(e->confirm!=0x8000 && e->confirm!=0x4000 && e->confirm!=8)return 0;
 if(!e->id[0] || !e->name[0])return 0;
 for(const char *p=e->id;*p;p++)if(!isalnum((unsigned char)*p) && *p!='-' && *p!='_')return 0;
 for(const char *p=e->art;*p;p++)if(!isalnum((unsigned char)*p) && *p!='-' && *p!='_')return 0;
 for(const char *p=e->name;*p;p++)if(!isalnum((unsigned char)*p) && !strchr(" -&'.",*p))return 0;
 return 1;
}
int tekken3_outfits_load_catalog(const char *path) {
 if(selecting || menu>=0)return 0;
 FILE *f=path?fopen(path,"r"):NULL;Tekken3OutfitEntry *rows=NULL;int count=0;
 if(f) {
  char line[512];
  while(fgets(line,sizeof line,f)) {
   Tekken3OutfitEntry e={0};unsigned mask=0;int end=0;
   if(line[0]=='#' || line[0]=='\n' || line[0]=='\r')continue;
   if(sscanf(line,"%47[^|]|%d|%39[^|]|%x|%d|%63[^\r\n]%n",e.id,&e.character,e.name,&mask,&e.skin,e.art,&end)!=6 || !end || (line[end] && line[end]!='\r' && line[end]!='\n') || mask>65535)continue;
   e.confirm=(uint16_t)mask;if(!valid_entry(&e))continue;
   int duplicate=0;for(int i=0;i<count;i++)if(!strcmp(rows[i].id,e.id))duplicate=1;
   if(duplicate)continue;
   Tekken3OutfitEntry *next=(Tekken3OutfitEntry*)realloc(rows,(size_t)(count+1)*sizeof *rows);
   if(!next)break;rows=next;rows[count++]=e;
  }
  fclose(f);
 }
 free(catalog);catalog=rows;catalog_count=count;memset(choice,0,sizeof choice);return count;
}
const Tekken3OutfitEntry *tekken3_outfits_entry(int cid,int index) {
 const Tekken3OutfitEntry *rows=catalog_count?catalog:defaults;
 int n=catalog_count?catalog_count:(int)(sizeof defaults/sizeof *defaults);
 if(index<0)return NULL;
 for(int i=0;i<n;i++)if(rows[i].character==cid && (rows[i].skin<0 || available[rows[i].skin]))if(!index--)return &rows[i];
 return NULL;
}
int tekken3_outfits_count(int cid) {int n=0;while(tekken3_outfits_entry(cid,n))n++;return n;}
void tekken3_outfits_set_available(int skin,int on) {if(skin>=0 && skin<T3_SKIN_COUNT)available[skin]=!!on;}
int tekken3_outfits_available(void) {
 for(int i=0;i<T3_SKIN_COUNT;i++)if(available[i])return 1;
 return 0;
}
void tekken3_outfits_update(int active,int c1,int c2) {
 active=!!active && tekken3_outfits_available();
 if(active && !selecting)for(int p=0;p<2;p++){locked[p]=0;committed[p]=-1;pending[p]=0;}
 if(!active){menu=-1;pending[0]=pending[1]=0;}selecting=active;
 if(active) {
  int ids[2]={c1,c2};
  for(int p=0;p<2;p++) {
   if(ids[p]!=character[p]){locked[p]=0;pending[p]=0;if(menu==p)menu=-1;}
   character[p]=ids[p];
   if(ids[p]>=0 && ids[p]<24 && choice[p][ids[p]]>=tekken3_outfits_count(ids[p]))choice[p][ids[p]]=0;
  }
 }
}
void tekken3_outfits_sync(void) {
 if(!tekken3_outfits_available())return;
 tekken3_outfits_update(gpu_tekken3_selector_active(),psx_mod_read_byte(0x80098106u),psx_mod_read_byte(0x80098107u));
 /* SLUS-00402 selector 8010DAE0 tests bit(character) at 80097EF4 for
  * Start/costume 2. Borrow just that bit and restore it after selection. */
 uint32_t flags=psx_mod_read_word(0x80097ef4u);
 if(selecting) {
  for(int p=0;p<2;p++)if(pending[p] && confirmation[p]==8 && character[p]>=0 && character[p]<24){uint32_t bit=1u<<character[p];borrowed_flags|=bit & ~flags;flags|=bit;}
  if(flags!=psx_mod_read_word(0x80097ef4u))psx_mod_write_word(0x80097ef4u,flags);
 }else if(borrowed_flags){psx_mod_write_word(0x80097ef4u,flags & ~borrowed_flags);borrowed_flags=0;}
}
void tekken3_outfits_connect(int p,int on) {
 if(p<0 || p>1)return;connected[p]=!!on;
 if(!on){previous[p]=0xffff;if(menu==p)tekken3_outfits_close(0);}
}
void tekken3_outfits_tick(void) {
 for(int p=0;p<2;p++)if(pending[p]>0)pending[p]--;
}
int tekken3_outfits_open(int p) {
 if(p<0 || p>1 || menu>=0 || !selecting || !connected[p] || locked[p] || !tekken3_outfits_count(character[p]))return 0;
 menu=p;before_menu=choice[p][character[p]];return 1;
}
int tekken3_outfits_menu_player(void){return menu;}
int tekken3_outfits_cycle(int p,int direction) {
 if(p!=menu || p<0 || !direction)return 0;
 int n=tekken3_outfits_count(character[p]);if(!n)return 0;
 int *c=&choice[p][character[p]];*c=(*c+(direction>0?1:n-1))%n;return 1;
}
void tekken3_outfits_close(int accept) {
 int p=menu;if(p<0)return;
 if(accept){const Tekken3OutfitEntry *e=tekken3_outfits_entry(character[p],choice[p][character[p]]);if(e){committed[p]=e->skin;confirmation[p]=e->confirm;pending[p]=24;locked[p]=1;}}
 else choice[p][character[p]]=before_menu;
 suppress[p]|=(uint16_t)~previous[p];menu=-1;
}
uint16_t tekken3_outfits_input(int p,uint16_t buttons) {
 if(p<0 || p>1)return buttons;
 uint16_t pressed=(uint16_t)~buttons,edges=previous[p]&pressed;previous[p]=buttons;suppress[p]&=pressed;
 if(!selecting || !connected[p])return buttons;
 if(menu>=0){
  if(menu==p){
   if(edges & (0x0400|0x2000))tekken3_outfits_close(0);
   else if(edges & (0x8000|0x4000|0x0008))tekken3_outfits_close(1);
   else if((edges & 0x00a0)==0x0080)tekken3_outfits_cycle(p,-1);
   else if((edges & 0x00a0)==0x0020)tekken3_outfits_cycle(p,1);
  }
  return 0xffff;
 }
 if(pending[p]>0)return (uint16_t)~confirmation[p];
 buttons|=suppress[p];
 if(!locked[p] && (edges & 0x0400) && !(suppress[p]&0x0400) && tekken3_outfits_open(p))return 0xffff;
 if(tekken3_outfits_count(character[p])){
  if(!locked[p] && ((uint16_t)~buttons & 0xf008)){committed[p]=-1;locked[p]=1;}
  buttons|=0x0400;
 }
 return buttons;
}
Tekken3OutfitView tekken3_outfits_view(int p) {
 Tekken3OutfitView v={0,-1,0,0,0,"ORIGINAL",0,0,0};if(p<0 || p>1)return v;
 v.character=character[p];v.visible=selecting && connected[p];v.locked=locked[p];v.menu=menu==p;
 v.count=tekken3_outfits_count(v.character);v.has_extra=v.count>0;
 if(v.character>=0 && v.character<24)v.index=choice[p][v.character];
 const Tekken3OutfitEntry *e=tekken3_outfits_entry(v.character,v.index);if(e){v.name=e->name;v.custom=e->skin>=0;}return v;
}
int tekken3_outfits_skin_enabled(int skin,int cy) {
 if(skin<0 || skin>=T3_SKIN_COUNT || !available[skin])return 0;
 /* Each fighter owns four CLUT rows; some costumes use more than two. */
 int p=cy>=504 && cy<=507?0:cy>=508 && cy<=511?1:-1;return p>=0 && committed[p]==skin;
}
