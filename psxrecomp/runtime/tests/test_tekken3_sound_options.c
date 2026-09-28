/* Native menu records + persistence, with isolated guest RAM and save file. */
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "../src/tekken3_sound_options.c"
static unsigned char ram[2*1024*1024], expansion[1024];
static int heard_music,heard_sfx;
static unsigned char *ptr(uint32_t p) {
    if(p>=0x9f000000u && p<0x9f000400u) return expansion+p-0x9f000000u;
    assert((p&0x1fffffffu)<sizeof ram); return ram+(p&0x1fffffffu);
}
uint8_t psx_mod_read_byte(uint32_t p) { return *ptr(p); }
uint16_t psx_mod_read_half(uint32_t p) { return *ptr(p)|(*ptr(p+1)<<8); }
uint32_t psx_mod_read_word(uint32_t p) { return psx_mod_read_half(p)|((uint32_t)psx_mod_read_half(p+2)<<16); }
void psx_mod_write_byte(uint32_t p,uint8_t v) { *ptr(p)=v; }
void psx_mod_write_word(uint32_t p,uint32_t v) { for(int i=0;i<4;i++) *ptr(p+i)=(uint8_t)(v>>(i*8)); }
uint32_t psx_mod_alloc_guest_memory(uint32_t n,uint32_t a) { assert(n==1024 && a==16);return 0x9f000000u; }
void spu_set_host_mix_volume(int sfx,int music) { heard_music=music;heard_sfx=sfx; }
static void tick(void) { tekken3_sound_options_tick(); }
static void action(int v) { wb(arena+ACTION,v);tick(); }
int main(int argc,char **argv) {
    assert(argc==2);
    const char *path=argv[1]; remove(path);
    tekken3_sound_options_configure("SLUS-00402",path);
    tick();assert(!arena && heard_music==100 && heard_sfx==100);
    wr(0x800DC804u,0x27BDFFD8u);wr(0x800AE204u,5);wr(0x800AE224u,1);
    unsigned ids[6]={1,4,2,5,3,6};
    for(unsigned i=0;i<6;i++) {
        wr(ROWS+i*20,PAGE);wr(ROWS+i*20+4,0x800B9000u+i*4);
        wr(ROWS+i*20+12,0x10000u|(ids[i]<<24));wr(ROWS+i*20+16,1);
    }
    wr(ROWS+4,0x800B9080u);wr(ROWS+104,0x800B9040u);
    wr(DESC+32,ROWS);wr(DESC+40,6);tick();
    assert(rd(DESC+40)==7 && rd(DESC+32)==arena);
    for(unsigned i=0;i<6;i++) {
        uint32_t dest=arena+(i ? i+1 : 0)*20;
        for(unsigned b=0;b<20;b++)assert(*ptr(dest+b)==*ptr(ROWS+i*20+b));
    }
    action(1);assert(panel && rd(DESC+40)==4);
    /* Highlight animation must never reset submenu or volume edits. */
    for(unsigned i=0;i<16;i++) { wr(0x800AE220u,i);tick();assert(panel); }
    wb(arena+MUSIC,19);wb(arena+SFX,18);tick();
    assert(heard_music==95 && heard_sfx==90);
    action(2);assert(!strcmp((char*)ptr(arena+SAVE_LABEL),"SAVED"));
    wb(arena+MUSIC,18);tick();assert(heard_music==90);
    action(3);assert(!panel && rd(DESC)==1 && heard_music==95);
    tekken3_sound_options_configure("SLUS-00402",path);
    assert(heard_music==95 && heard_sfx==90);
    action(1);
    for(unsigned i=19;i>0;i--) { wb(arena+MUSIC,i-1);tick(); }
    assert(heard_music==0);
    wb(arena+MUSIC,20);tick();assert(heard_music==0);
    for(unsigned i=1;i<=20;i++) { wb(arena+MUSIC,i);tick(); }
    wb(arena+MUSIC,0);tick();assert(heard_music==100);
    /* A screen change cancels preview, a stale overlay does not consume it. */
    wr(0x800AE204u,4);tick();assert(!panel && heard_music==95);
    wr(0x800AE204u,5);wr(DESC+32,ROWS);wr(DESC+40,6);tick();
    assert(rd(DESC+32)==arena && rd(DESC+40)==7);
    action(1);snprintf(save_path,sizeof save_path,"%s/missing.ini",path);action(2);
    assert(!strcmp((char*)ptr(arena+SAVE_LABEL),"SAVE FAILED"));
    FILE *f=fopen(path,"w");assert(f);
    fputs("music_volume=105\nsfx_volume=-5\nmusic_volume=foo\nsfx_volume=75oops\n",f);fclose(f);
    tekken3_sound_options_configure("SLUS-00402",path);
    assert(heard_music==100 && heard_sfx==100);
    /* A savestate's injected descriptor is recoverable in a fresh process. */
    arena=0;tick();assert(arena && rd(DESC+32)==arena && rd(DESC+40)==7);
    action(1);panel=0;arena=0;tick();assert(arena && !panel && rd(DESC)==1);
    tekken3_sound_options_configure("OTHER",path);
    wr(DESC+40,99);tick();assert(rd(DESC+40)==99);
    remove(path);
    puts("Sounds: native navigation, independent preview, limits, save/reload, cancel and guards passed");
    return 0;
}
