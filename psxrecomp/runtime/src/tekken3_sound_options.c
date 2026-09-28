/* SLUS-00402's native Options renderer consumes data-only menu descriptors.
 * Reuse that renderer/input code for Sounds; no guest instructions or pad
 * routing are replaced. Navigation actions keep their original page IDs. */
#include "mod_memory.h"
#include "tekken3_sound_options.h"
#include "mod_plugins.h"
#include "spu.h"
#include <stdio.h>
#include <string.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif

#define DESC 0x800EAD24u
#define ROWS 0x800B8FC8u
#define PAGE 0x800EC020u
#define ARENA_SIZE 1024u
enum { ROOT_ROWS=0, SOUND_ROWS=160, CHOICES=240, ACTION=324,
       MUSIC=325, SFX=326, SAVE_LABEL=336, STRINGS=352 };
static int enabled, panel, saved_music=100, saved_sfx=100;
static int preview_music=100, preview_sfx=100;
static uint32_t arena;
static char save_path[2048];
static uint32_t sound_title;

static uint32_t rd(uint32_t p) { return psx_mod_read_word(p); }
static void wr(uint32_t p, uint32_t v) { psx_mod_write_word(p,v); }
static void wb(uint32_t p, unsigned v) { psx_mod_write_byte(p,(uint8_t)v); }
static void copy_guest(uint32_t dst,uint32_t src,unsigned n) {
    for(unsigned i=0;i<n;i++) wb(dst+i,psx_mod_read_byte(src+i));
}
static uint32_t put_string(uint32_t *cursor,const char *s) {
    uint32_t result=*cursor;
    do { wb((*cursor)++, (unsigned char)*s); } while(*s++);
    return result;
}
static void label(const char *s) {
    uint32_t p=arena+SAVE_LABEL;
    put_string(&p,s);
}
static void apply_volume(void) {
    spu_set_host_mix_volume(preview_sfx,preview_music);
}

void tekken3_sound_options_configure(const char *game_id,const char *path) {
    enabled=game_id && !strcmp(game_id,"SLUS-00402");
    panel=0;
    saved_music=saved_sfx=100;
    save_path[0]=0;
    if(enabled && path && strlen(path)<sizeof save_path-5) {
        strcpy(save_path,path);
        FILE *f=fopen(path,"r");
        if(f) {
            char line[160], key[40], tail; int value;
            while(fgets(line,sizeof line,f)) {
                if(sscanf(line," %39[a-z_] = %d %c",key,&value,&tail)!=2 ||
                   value<0 || value>100 || value%5) continue;
                if(!strcmp(key,"music_volume")) saved_music=value;
                if(!strcmp(key,"sfx_volume")) saved_sfx=value;
            }
            fclose(f);
        }
    }
    preview_music=saved_music; preview_sfx=saved_sfx;
    apply_volume();
}

static int save_volume(void) {
    if(!save_path[0]) return 0;
    char tmp[sizeof save_path+5];
    snprintf(tmp,sizeof tmp,"%s.tmp",save_path);
    FILE *f=fopen(tmp,"w");
    if(!f) return 0;
    int ok=fprintf(f,"# Tekken 3 Sounds (0-100)\nmusic_volume=%d\nsfx_volume=%d\n",
                   preview_music,preview_sfx)>0;
    if(fclose(f)!=0) ok=0;
    if(ok) {
#ifdef _WIN32
        ok=MoveFileExA(tmp,save_path,MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)!=0;
#else
        ok=rename(tmp,save_path)==0;
#endif
    }
    if(!ok) { remove(tmp); return 0; }
    saved_music=preview_music; saved_sfx=preview_sfx;
    return 1;
}

static void action_row(uint32_t row,uint32_t text,unsigned action) {
    wr(row,arena+ACTION); wr(row+4,text); wr(row+8,0);
    wr(row+12,0x00010000u|(action<<24)); wr(row+16,1);
}
static void volume_row(uint32_t row,uint32_t text,uint32_t value) {
    wr(row,value); wr(row+4,text); wr(row+8,arena+CHOICES);
    wr(row+12,0x00001501u); wr(row+16,2);
}
static int build_tables(void) {
    if(!arena) arena=psx_mod_alloc_guest_memory(ARENA_SIZE,16);
    if(!arena) return 0;
    for(unsigned i=0;i<ARENA_SIZE;i++) wb(arena+i,0);
    uint32_t p=arena+STRINGS;
    sound_title=put_string(&p,"SOUNDS");
    copy_guest(arena+ROOT_ROWS,ROWS,20);
    action_row(arena+20,sound_title,1);
    copy_guest(arena+40,ROWS+20,100);
    volume_row(arena+SOUND_ROWS,put_string(&p,"MUSIC VOLUME"),arena+MUSIC);
    volume_row(arena+SOUND_ROWS+20,put_string(&p,"SFX VOLUME"),arena+SFX);
    action_row(arena+SOUND_ROWS+40,arena+SAVE_LABEL,2);
    action_row(arena+SOUND_ROWS+60,put_string(&p,"BACK"),3);
    for(unsigned i=0;i<=20;i++) {
        char s[8]; snprintf(s,sizeof s,"%u",i*5);
        wr(arena+CHOICES+i*4,put_string(&p,s));
    }
    label("SAVE");
    return 1;
}
static void show_root(unsigned cursor) {
    panel=0;
    wr(DESC,cursor); wr(DESC+4,0);
    wr(DESC+8,113); wr(DESC+12,40);
    wr(DESC+16,20); wr(DESC+20,100); wr(DESC+24,34);
    wr(DESC+28,324); wr(DESC+32,arena+ROOT_ROWS);
    wr(DESC+36,0x800B9298u); wr(DESC+40,7);
    wr(DESC+44,PAGE); wb(DESC+48,1); wb(DESC+49,6);
    wb(arena+ACTION,0);
}
static void show_sounds(void) {
    panel=1;
    preview_music=saved_music; preview_sfx=saved_sfx;
    wb(arena+MUSIC,preview_music/5); wb(arena+SFX,preview_sfx/5);
    wb(arena+ACTION,0); label("SAVE");
    wr(DESC,0); wr(DESC+4,0);
    wr(DESC+8,144); wr(DESC+12,40);
    wr(DESC+20,145); wr(DESC+24,48);
    wr(DESC+32,arena+SOUND_ROWS); wr(DESC+36,sound_title);
    wr(DESC+40,4); wr(DESC+44,arena+ACTION); wb(DESC+49,3);
}
static void discard_preview(void) {
    panel=0; preview_music=saved_music; preview_sfx=saved_sfx;
    apply_volume();
}
static int read_volume(uint32_t p,int before) {
    unsigned v=psx_mod_read_byte(p);
    /* Native enum input wraps. Volume stops at the two ends instead. */
    if(v>20 || (before==0 && v==20) || (before==100 && v==0)) v=(unsigned)before/5;
    wb(p,v); return (int)v*5;
}
void tekken3_sound_options_tick(void) {
    if(!enabled) return;
    /* Overlay code + table signatures avoid touching reused battle RAM. */
    int overlay=rd(0x800DC804u)==0x27BDFFD8u &&
        rd(ROWS)==PAGE && rd(ROWS+4)==0x800B9080u &&
        rd(ROWS+100)==PAGE && rd(ROWS+104)==0x800B9040u;
    /* Main dispatcher 80028C64 selects case 5 (80028CE4 -> Options).
     * AE220 is the flashing highlight counter, not the current screen. */
    int active=overlay && psx_mod_read_half(0x800AE204u)==5 &&
        psx_mod_read_half(0x800AE224u)==1;
    if(!active) {
        if(panel) {
            discard_preview();
            if(overlay && arena && rd(DESC+32)==arena+SOUND_ROWS) show_root(1);
        }
        return;
    }
    uint32_t rows=rd(DESC+32);
    /* Expansion memory is host-owned, so a state loaded in a fresh process
     * may contain our descriptor but no allocation yet. Recognize the full
     * descriptor shape and rebuild from the intact original navigation rows. */
    int foreign_arena=rows>=PSX_MOD_GUEST_MEMORY_BASE &&
        rows<PSX_MOD_GUEST_MEMORY_BASE+PSX_MOD_GUEST_MEMORY_SIZE &&
        (!arena || (rows!=arena+ROOT_ROWS && rows!=arena+SOUND_ROWS));
    int restored_root=foreign_arena && rd(DESC+40)==7 &&
        rd(DESC+36)==0x800B9298u && rd(DESC+44)==PAGE && rd(DESC+24)==34;
    int restored_sounds=foreign_arena && rd(DESC+40)==4 &&
        rd(DESC+36)==rows+STRINGS-SOUND_ROWS &&
        rd(DESC+44)==rows+ACTION-SOUND_ROWS && rd(DESC+24)==48;
    if((rows==ROWS && rd(DESC+40)==6) || restored_root || restored_sounds) {
        if(panel) discard_preview();
        unsigned cursor=rd(DESC);
        if(!build_tables()) return;
        show_root(restored_sounds ? 1 : restored_root ? (cursor<7 ? cursor : 0) :
                  cursor<6 ? (cursor ? cursor+1 : 0) : 0);
        rows=arena+ROOT_ROWS;
    } else if(!arena || (rows!=arena+ROOT_ROWS && rows!=arena+SOUND_ROWS)) {
        if(panel) discard_preview();
        return;
    }
    if(psx_mod_read_byte(PAGE)!=0) {
        if(panel) { discard_preview(); show_root(1); }
        return;
    }
    /* A loaded state can restore the guest submenu without its host preview. */
    if(rows==arena+SOUND_ROWS && !panel) show_sounds();
    else if(rows==arena+ROOT_ROWS && panel) discard_preview();
    unsigned action=psx_mod_read_byte(arena+ACTION);
    wb(arena+ACTION,0);
    if(!panel) { if(action==1) show_sounds(); return; }
    int music=read_volume(arena+MUSIC,preview_music);
    int sfx=read_volume(arena+SFX,preview_sfx);
    if(music!=preview_music || sfx!=preview_sfx) {
        preview_music=music; preview_sfx=sfx; apply_volume(); label("SAVE");
    }
    if(action==2) label(save_volume() ? "SAVED" : "SAVE FAILED");
    else if(action==3) { discard_preview(); show_root(1); }
}
