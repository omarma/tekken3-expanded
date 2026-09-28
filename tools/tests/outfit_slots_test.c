#include "tekken3_outfits.h"
#include <assert.h>
#include <stdio.h>
static int active;static uint8_t ids[2];static uint32_t flags=0x50002;
int gpu_tekken3_selector_active(void){return active;}
uint8_t psx_mod_read_byte(uint32_t address){return ids[address==0x80098107u];}
uint32_t psx_mod_read_word(uint32_t address){assert(address==0x80097ef4u);return flags;}
void psx_mod_write_word(uint32_t address,uint32_t value){assert(address==0x80097ef4u);flags=value;}
static void enter(int c1,int c2){active=0;tekken3_outfits_sync();active=1;ids[0]=(uint8_t)c1;ids[1]=(uint8_t)c2;tekken3_outfits_sync();tekken3_outfits_input(0,0xffff);tekken3_outfits_input(1,0xffff);}
static void tap(int p,uint16_t button){tekken3_outfits_input(p,(uint16_t)~button);tekken3_outfits_input(p,0xffff);}
int main(void){
 for(int s=0;s<T3_SKIN_COUNT;s++)tekken3_outfits_set_available(s,1);
 tekken3_outfits_connect(0,1);tekken3_outfits_connect(1,1);
 assert(tekken3_outfits_count(5)==3 && tekken3_outfits_count(18)==4);
 enter(5,18);
 assert(tekken3_outfits_input(0,0xfbff)==0xffff && tekken3_outfits_menu_player()==0);
 for(int i=0;i<20;i++)tekken3_outfits_input(0,0xfbff);
 assert(tekken3_outfits_menu_player()==0);
 tekken3_outfits_input(0,0xffff);tap(0,0x80);
 assert(tekken3_outfits_view(0).index==2);
 tap(1,0x20);assert(tekken3_outfits_view(0).index==2);
 tap(0,0x400);assert(tekken3_outfits_menu_player()==-1 && tekken3_outfits_view(0).index==0);
 tap(0,0x400);tap(0,0x80);
 tekken3_outfits_close(1);
 assert(tekken3_outfits_skin_enabled(T3_SKIN_NINA,504));
 assert(!tekken3_outfits_skin_enabled(T3_SKIN_NINA,508));
 for(int i=0;i<24;i++){
  for(int poll=0;poll<10;poll++)assert(tekken3_outfits_input(0,0xffff)==0xbfff);
  tekken3_outfits_tick();
 }
 assert(tekken3_outfits_input(0,0xffff)==0xffff);
 assert(!tekken3_outfits_open(0));
 active=0;tekken3_outfits_sync();
 for(unsigned word=0;word<65536;word++)for(int p=0;p<2;p++)assert(tekken3_outfits_input(p,(uint16_t)word)==word);
 enter(5,18);
 assert(tekken3_outfits_input(0,0xdfff)==0xdfff); /* stock Circle remains kick */
 assert(!tekken3_outfits_skin_enabled(T3_SKIN_NINA,504));
 assert(tekken3_outfits_open(1));tekken3_outfits_cycle(1,-1);tekken3_outfits_close(1);
 assert(tekken3_outfits_input(1,0xffff)==0x7fff && tekken3_outfits_skin_enabled(T3_SKIN_ANNA,509));
 enter(7,18);assert(tekken3_outfits_open(0));tekken3_outfits_cycle(0,1);tekken3_outfits_cycle(0,1);tekken3_outfits_close(1);
 uint32_t before=flags;tekken3_outfits_sync();assert(flags==(before|0x80));
 assert(tekken3_outfits_input(0,0xffff)==0xfff7);
 active=0;tekken3_outfits_sync();assert(flags==before);
 enter(5,18);assert(tekken3_outfits_open(1));tekken3_outfits_connect(1,0);assert(tekken3_outfits_menu_player()==-1);
 tekken3_outfits_set_available(T3_SKIN_NINA,0);assert(tekken3_outfits_count(5)==2);
 /* Kuma's stock punch/kick costumes and independent white-fur slot. */
 tekken3_outfits_connect(1,1);
 assert(tekken3_outfits_count(11)==3);
 enter(11,11);assert(tekken3_outfits_open(0));tekken3_outfits_close(1);
 assert(tekken3_outfits_input(0,0xffff)==0x7fff);
 assert(!tekken3_outfits_skin_enabled(T3_SKIN_KUMA,504));
 enter(11,11);assert(tekken3_outfits_open(0));tekken3_outfits_cycle(0,1);tekken3_outfits_close(1);
 assert(tekken3_outfits_input(0,0xffff)==0xbfff);
 assert(!tekken3_outfits_skin_enabled(T3_SKIN_KUMA,504));
 enter(11,11);assert(tekken3_outfits_open(0));tekken3_outfits_cycle(0,1);tekken3_outfits_close(1);
 assert(tekken3_outfits_input(0,0xffff)==0x7fff);
 assert(tekken3_outfits_skin_enabled(T3_SKIN_KUMA,504));
 assert(!tekken3_outfits_skin_enabled(T3_SKIN_KUMA,508));
 assert(tekken3_outfits_open(1));tekken3_outfits_cycle(1,-1);tekken3_outfits_close(1);
 assert(tekken3_outfits_skin_enabled(T3_SKIN_KUMA,508));
 /* Ordinary kick after a custom choice returns to untouched Panda. */
 enter(11,11);assert(tekken3_outfits_input(0,0xbfff)==0xbfff);
 assert(!tekken3_outfits_skin_enabled(T3_SKIN_KUMA,504));
 for(int s=0;s<T3_SKIN_COUNT;s++)tekken3_outfits_set_available(s,0);
 assert(!tekken3_outfits_available() && tekken3_outfits_count(11)==2);
 tekken3_outfits_set_available(T3_SKIN_KUMA,1);
 assert(tekken3_outfits_available() && tekken3_outfits_count(11)==3);
 enter(11,11);assert(tekken3_outfits_open(0));tekken3_outfits_close(0);
 tekken3_outfits_set_available(T3_SKIN_XIAOYU,1);tekken3_outfits_set_available(T3_SKIN_ANNA,1);
 active=0;tekken3_outfits_sync();
 FILE *f=fopen("out/outfit-slots/catalog-test.txt","w");assert(f);
 fputs("# valid additional options, malformed/duplicate rows are ignored\n",f);
 for(int i=0;i<19;i++)fprintf(f,"variant-%d|5|VARIANT %d|8000|-1|missing-art\n",i,i);
 fputs("variant-0|5|DUPLICATE|8000|-1|missing-art\nbad|25|BAD|8000|-1|missing-art\nbad2|5|WRONG PACK|8000|2|missing-art\nbad3|5|BAD MASK|800000|-1|missing-art\n",f);fclose(f);
 assert(tekken3_outfits_load_catalog("out/outfit-slots/catalog-test.txt")==19 && tekken3_outfits_count(5)==19);
 enter(5,18);assert(tekken3_outfits_open(0));tekken3_outfits_cycle(0,-1);assert(tekken3_outfits_view(0).index==18);
 tekken3_outfits_close(0);active=0;tekken3_outfits_sync();
 assert(tekken3_outfits_load_catalog("missing-file")==0 && tekken3_outfits_count(5)==2);
 puts("PASS: modal edges, wrap, cancel, owner isolation, stock/custom confirmation, temporary third-costume unlock, disconnect, availability, extensible catalog and all 131072 gameplay inputs");
}
