/* A character change in the middle of a cinematic (`swap`, docs/CINE-FORMAT.md):
 * the files of every character a cinematic changes to, kept on the host, so
 * that the game's own loader puts one in place within a single frame.
 *
 * What a load costs (measured 2026-10-20 on the scene of Armor King's ending):
 * the fighter loader 0x80036310 (actor, &o1, &o2) queues the character's four
 * files (index 4 * file + 95 .. 98, file = actor + 0x1C: the model, two more,
 * and the moves if the move table 0x800A0510 wants them) on the CD queue
 * 0x8006BF20 (file, destination, 0), starts it (0x8006C084) and waits on it
 * (0x8006C23C, the busy flag 0x800A069F): about 31 game frames a character,
 * nothing drawn meanwhile; everything else it does (textures and palettes in
 * the side's VRAM band, the hit-effect pack, the sound bank, the model rows)
 * takes no frame at all. The CD's speed changes nothing (instant disc speed:
 * the same 31 frames).
 *
 * So the engine loads each character once while the cinematic's start is
 * black (src/tekken3_cine.c, the pre-roll), the reads as the game makes them,
 * and keeps each file's bytes as they arrived (before the loaders' own fix-ups,
 * the moves relocated in place). At the change, the same loader
 * runs again and each read it queues is served from those bytes at once
 * instead: the queue stays empty, the wait ends at its first look. A file
 * does not depend on the side it is loaded for: one character kept serves
 * both actors. Guests (TTT1) load Jin's stock files (src/tekken3_ttt1_roster.c
 * maps them) and are grafted on them at once (tekken3_ttt1_guest_now).
 *
 * The first load of a character, in the black, reads its files from the disc
 * image on the host instead (cdrom_host_read_sector, outside the emulated
 * drive), as the drive delivers them: the same bytes (the drive's reads checked
 * against them, TEKKEN3_CINE_SWAP_CHECK=1), no frame waited. The TTT Embu's
 * seven characters read ahead took 554 frames through the drive (~80 a
 * character, at any disc speed), the black ~14 s. */
#include "mod_plugins.h"
#include "psx_runtime.h"
#include "cdrom.h"
#include "tekken3_host_clock.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { FILES_MAX=64, PENDING_MAX=8, FILE_ENTRY=0x80098574, FILE_TABLE=0x80024400, FILE_SIZE_MAX=1<<20 };
static struct { unsigned file; uint32_t size; uint8_t *bytes; } kept[FILES_MAX];
static int kept_count, loading, served, from_disc, read;
static double began;                /* ms, the wall time a load takes (the journal) */
static double now_ms(void) { return tekken3_host_ns()/1e6; }
/* The loader's third file goes through a staging buffer (0x8009BD48, the
 * screen overlay's place 0x800B8D58), whose ~100 KB run over the display
 * buffer 0x800C9758 and both sides' packet areas just under it (the table
 * 0x800AE040, 28 bytes a display buffer: +0 / +4 each side's packets, +0xC /
 * +0x10 more of them, laid out by 0x800799B0): at the start of a fight
 * nothing is drawn yet, but in the middle of a cinematic the other side's
 * packets and the last frame's display list are there. Its bytes are put
 * back once the new model's packets are built (0x80035CE8 reads it too), but
 * for this side's packet areas, which that has just filled; meanwhile the
 * loader holds the drawing (0x80029638(1)). */
enum { STAGING=0x8009bd48, DISPLAY_BUFFERS=0x800ae040, DISPLAY_BUFFER_SIZE=28 };
static uint8_t *under; static uint32_t under_at, under_size;
static struct { unsigned file; uint32_t destination; } pending[PENDING_MAX];
static int pending_count;

static int kept_index(unsigned file) {
    for(int i=0;i<kept_count;i++) if(kept[i].file==file) return i;
    return -1;
}
/* A file's size in bytes: its entry (0x80098574 + 2 * file) in the disc's
 * table 0x80024400 (8 bytes: first sector, size), as 0x8006BF20 reads it. */
static uint32_t file_size(unsigned file) {
    unsigned entry=psx_mod_read_half(FILE_ENTRY+2*file);
    return psx_mod_read_word(FILE_TABLE+8*entry+4);
}

/* Inside one of this side's packet areas, which the new model has just filled. */
static int side_packets(unsigned side,uint32_t a) {
    for(uint32_t b=0;b<2;b++) {
        uint32_t t=DISPLAY_BUFFERS+b*DISPLAY_BUFFER_SIZE;
        for(uint32_t k=0;k<0x10;k+=0xc) {
            uint32_t from=psx_mod_read_word(t+k+4*side),size=psx_mod_read_word(t+k+4)-psx_mod_read_word(t+k);
            if(a>=from && a-from<size) return 1;
        }
    }
    return 0;
}
/* The engine's load of one actor begins / ends (src/tekken3_cine.c). */
void tekken3_cine_swap_loading(int on,unsigned side) {
    loading=on;
    if(on) { pending_count=0; served=from_disc=read=0; began=now_ms(); return; }
    if(under) {
        for(uint32_t i=0;i<under_size;i++) if(!side_packets(side,under_at+i)) psx_mod_write_byte(under_at+i,under[i]);
        free(under); under=NULL;
    }
    fprintf(stderr,"Cine swap: %d files from the kept ones, %d from the disc image, %d read by the drive, %.1f ms\n",
            served,from_disc,read,now_ms()-began);
}
/* What a file about to land in the staging buffer covers, kept to be put back. */
static void keep_under(uint32_t to,uint32_t n) {
    if(under || to!=psx_mod_read_word(STAGING) || !n || n>FILE_SIZE_MAX || !(under=malloc(n))) return;
    under_at=to; under_size=n;
    for(uint32_t i=0;i<n;i++) under[i]=psx_mod_read_byte(to+i);
}
/* Every file kept goes (a cinematic over). */
void tekken3_cine_swap_forget(void) {
    for(int i=0;i<kept_count;i++) free(kept[i].bytes);
    kept_count=0;
}

/* A file's bytes from the disc image: its entry (first sector, size), the
 * sector counted from TEKKEN3.BNS, whose position the game keeps at
 * 0x800A05E0 (minute, second, sector in BCD, DsSearchFile's), as 0x8006BE80
 * adds them; the sectors read on the host. NULL if it cannot be read. */
enum { BNS_POSITION=0x800a05e0 };
static unsigned bcd(uint8_t b) { return (b>>4)*10+(b&15); }
static uint8_t *disc_file(unsigned file,uint32_t *size) {
    unsigned entry=psx_mod_read_half(FILE_ENTRY+2*file);
    uint32_t bns=(bcd(psx_mod_read_byte(BNS_POSITION))*60+bcd(psx_mod_read_byte(BNS_POSITION+1)))*75+bcd(psx_mod_read_byte(BNS_POSITION+2));
    if(bns<150) return NULL;
    uint32_t lba=bns-150+psx_mod_read_word(FILE_TABLE+8*entry),n=psx_mod_read_word(FILE_TABLE+8*entry+4);
    uint8_t *b=n && n<=FILE_SIZE_MAX?malloc((n+2047)&~2047u):NULL;
    for(uint32_t s=0;b && s*2048<n;s++) if(!cdrom_host_read_sector(lba+s,b+s*2048)) { free(b); b=NULL; }
    if(b) *size=n;
    return b;
}
/* TEKKEN3_CINE_SWAP_CHECK=1: the drive reads every file as before, each one
 * compared with the disc image's bytes when it arrives. */
static int checking(void) {
    static int on=-1;
    if(on<0) { const char *e=getenv("TEKKEN3_CINE_SWAP_CHECK"); on=e && *e=='1'; }
    return on;
}

/* 0x8006BF20 (file, destination, ...), its file already mapped for a guest
 * (src/tekken3_ttt1_roster.c): 1 when served here (the call is then skipped),
 * 0 to let the game queue the read, noted to be kept when it arrives. */
int tekken3_cine_swap_read(CPUState *cpu) {
    if(!loading) return 0;
    unsigned file=cpu->gpr[4]&0xffff; uint32_t to=cpu->gpr[5];
    int k=kept_index(file),fresh=0;
    if(k<0 && !checking() && kept_count<FILES_MAX) {
        uint32_t n; uint8_t *b=disc_file(file,&n);
        if(b) { kept[kept_count].file=file; kept[kept_count].size=n; kept[k=kept_count++].bytes=b; fresh=1; }
    }
    keep_under(to,k>=0?kept[k].size:file_size(file));
    if(k>=0) {
        const uint8_t *b=kept[k].bytes; uint32_t n=kept[k].size,i=0;
        for(;i+4<=n;i+=4) psx_mod_write_word(to+i,(uint32_t)b[i]|(uint32_t)b[i+1]<<8|(uint32_t)b[i+2]<<16|(uint32_t)b[i+3]<<24);
        for(;i<n;i++) psx_mod_write_byte(to+i,b[i]);
        if(fresh) from_disc++; else served++;
        cpu->pc=cpu->gpr[31];
        return 1;
    }
    if(pending_count<PENDING_MAX) { pending[pending_count].file=file; pending[pending_count++].destination=to; }
    read++;
    return 0;
}

/* The reads have arrived: each one kept as it is. */
void tekken3_cine_swap_arrived(void) {
    for(int i=0;i<pending_count;i++) {
        unsigned file=pending[i].file; uint32_t n=file_size(file),from=pending[i].destination;
        if(kept_index(file)>=0) continue;
        if(!n || n>FILE_SIZE_MAX || kept_count==FILES_MAX) {
            fprintf(stderr,"Cine swap: file %u (%u bytes) not kept\n",file,n);
            continue;
        }
        uint8_t *b=malloc(n);
        if(!b) continue;
        for(uint32_t j=0;j<n;j++) b[j]=psx_mod_read_byte(from+j);
        kept[kept_count].file=file; kept[kept_count].size=n; kept[kept_count++].bytes=b;
        fprintf(stderr,"Cine swap: file %u kept (%u bytes)\n",file,n);
        if(checking()) {
            uint32_t m=0,at=0; uint8_t *d=disc_file(file,&m);
            while(d && m==n && at<n && d[at]==b[at]) at++;
            if(!d) fprintf(stderr,"Cine swap: check, file %u not read from the disc image\n",file);
            else if(m!=n || at<n) fprintf(stderr,"Cine swap: check, file %u differs from the disc image at byte %u of %u\n",file,at,n);
            else fprintf(stderr,"Cine swap: check, file %u as on the disc image\n",file);
            free(d);
        }
    }
    pending_count=0;
}
/* The reads have arrived when the wait on the queue (0x8006C23C, the busy
 * flag) says done after it said busy: before the fighter loader relocates
 * its moves (0x80069EA4) or the move-table loader 0x80069F74 its own, in
 * place. The start of the queue (0x8006C084) asks it too, before raising the
 * flag: that "done" is the previous reads', not these. */
extern void __real_func_8006C23C(CPUState *cpu);
void __wrap_func_8006C23C(CPUState *cpu) {
    static int busy;
    __real_func_8006C23C(cpu);
    if(cpu->gpr[2]) busy=1;
    else if(busy) { busy=0; if(loading && pending_count) tekken3_cine_swap_arrived(); }
}
