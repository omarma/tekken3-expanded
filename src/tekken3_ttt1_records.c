/* Per-character records for the TTT1 guests, kept out of the memory card.
 *
 * The game keeps four halfword counters per character in its save data,
 * 0x8009804C + 8 * (ID mod 22): +0 at 0x800513B4, +2 (winner) and +4 (loser)
 * at 0x80051458, +6 (both) at 0x80051550, each with the total at 0x80097F1C,
 * then 0x8004C390 marks the save as changed. 0x80051660 returns +0 + +4 + +6,
 * the CHARACTERS ranking's count. The modulo credited a guest to a stock
 * fighter (Jun, 38, to Gun Jack, 16). A guest's counters live here instead,
 * in ttt1-guest-records.txt beside memory card 1, one line per guest key:
 * the card itself never holds a guest ID and stays valid without the mod.
 * The total still counts the guest's games, as it counts every fighter's.
 * The recompiler starts these functions after their first three
 * instructions (the modulo's lui / ori / mult), at the stack adjustment:
 * 0x800513C0, 0x80051464, 0x8005155C. Their arguments are still intact. */
#include "mod_plugins.h"
#include "psx_runtime.h"
#include "memcard.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern int tekken3_ttt1_roster_enabled(void);
extern int tekken3_guest_character(unsigned id);
extern const char *tekken3_guest_key(unsigned id);
extern void __real_func_800513C0(CPUState*);
extern void __real_func_80051464(CPUState*);
extern void __real_func_8005155C(CPUState*);
extern void __real_func_80051660(CPUState*);
extern void __real_func_8004CD80(CPUState*);
extern void __real_func_8004BEC0(CPUState*);
extern void __real_func_8004C240(CPUState*);
extern void __real_func_8005138C(CPUState*);
extern void __real_func_8004CC08(CPUState*);
extern int tekken3_guest_id(const char *key);
extern uint32_t tekken3_guest_descriptor(unsigned id);
extern uint32_t tekken3_descriptor_table(void);
extern void tekken3_ranking_face(unsigned slot,unsigned id);
extern void tekken3_ranking_faces_restore(void);
extern int tekken3_ranking_face_ok(unsigned slot);

enum { NATIVE_RECORDS=0x8009804c, RECORD_SIZE=8, TOTAL=0x80097f1c, NATIVES=22,
       SAVE_CHANGED=0x8004c390, RECORDS_MAX=64 };
typedef struct { char key[32]; uint16_t field[4]; } GuestRecord;
static GuestRecord records[RECORDS_MAX];
static unsigned record_count;
static int loaded;

static int records_path(char *out,size_t size) {
    const char *card=NULL;
    if(memcard_debug_info(0,&card,NULL,NULL,NULL) || !card || !*card)return 0;
    const char *slash=strrchr(card,'/'),*back=strrchr(card,'\\');
    if(back && (!slash || back>slash))slash=back;
    int n=slash?(int)(slash-card):1;
    const char *dir=slash?card:".";
    return snprintf(out,size,"%.*s/ttt1-guest-records.txt",n,dir)<(int)size;
}
/* Save data that names a fighter (see the note before save_guard): the
 * guests written as Jin on the card, and which guest each such entry was. */
enum { SURVIVAL=0x80097ffc, SURVIVAL_ROWS=10, LAST_CHOICE=0x80097f0e, JIN=9 };
typedef struct { int used; char key[32]; unsigned wins; unsigned char name[4]; } SurvivalMark;
typedef struct { int used; char key[32]; unsigned costume; } ChoiceMark;
static SurvivalMark survival_marks[SURVIVAL_ROWS];
static ChoiceMark choice_marks[2];
/* A guest's Time Attack record (see time_attack_tick). */
typedef struct { char key[32]; uint32_t time; unsigned char name[4]; } TimeRecord;
static TimeRecord time_records[RECORDS_MAX];
static unsigned time_record_count;
static uint32_t survival_row(unsigned row);
static void guests_back(void);
static int guests_pending;
static void load(void) {
    if(loaded)return;
    loaded=1;
    char path[1024],line[256];
    if(!records_path(path,sizeof path))return;
    FILE *f=fopen(path,"r");
    if(!f)return;
    while(fgets(line,sizeof line,f)) {
        char key[32];unsigned v[4],row,n0,n1,n2;
        if(sscanf(line,"@survival %u %31s %u %u %u %u",&row,key,&v[0],&n0,&n1,&n2)==6 && row<SURVIVAL_ROWS) {
            SurvivalMark *m=&survival_marks[row];
            m->used=1;snprintf(m->key,sizeof m->key,"%s",key);m->wins=v[0];
            m->name[0]=(unsigned char)n0;m->name[1]=(unsigned char)n1;m->name[2]=(unsigned char)n2;m->name[3]=0;
        } else if(sscanf(line,"@time %31s %u %u %u %u",key,&v[0],&n0,&n1,&n2)==5 && time_record_count<RECORDS_MAX) {
            TimeRecord *r=&time_records[time_record_count++];
            snprintf(r->key,sizeof r->key,"%s",key);r->time=v[0];
            r->name[0]=(unsigned char)n0;r->name[1]=(unsigned char)n1;r->name[2]=(unsigned char)n2;r->name[3]=0;
        } else if(sscanf(line,"@last %u %31s %u",&row,key,&v[0])==3 && row<2) {
            choice_marks[row].used=1;snprintf(choice_marks[row].key,sizeof choice_marks[row].key,"%s",key);
            choice_marks[row].costume=v[0]&3;
        } else if(line[0]!='@' && record_count<RECORDS_MAX &&
                  sscanf(line,"%31s %u %u %u %u",key,&v[0],&v[1],&v[2],&v[3])==5) {
            GuestRecord *r=&records[record_count++];
            snprintf(r->key,sizeof r->key,"%s",key);
            for(unsigned i=0;i<4;i++)r->field[i]=(uint16_t)(v[i]>0xffff?0xffff:v[i]);
        }
    }
    fclose(f);
}
static void save(void) {
    char path[1024],tmp[1040];
    if(!records_path(path,sizeof path) || snprintf(tmp,sizeof tmp,"%s.new",path)>=(int)sizeof tmp)return;
    FILE *f=fopen(tmp,"w");
    if(!f){fprintf(stderr,"TTT1 records: cannot write %s\n",tmp);return;}
    for(unsigned i=0;i<record_count;i++)
        fprintf(f,"%s %u %u %u %u\n",records[i].key,records[i].field[0],records[i].field[1],
                records[i].field[2],records[i].field[3]);
    for(unsigned row=0;row<SURVIVAL_ROWS;row++)
        if(survival_marks[row].used)
            fprintf(f,"@survival %u %s %u %u %u %u\n",row,survival_marks[row].key,survival_marks[row].wins,
                    survival_marks[row].name[0],survival_marks[row].name[1],survival_marks[row].name[2]);
    for(unsigned p=0;p<2;p++)
        if(choice_marks[p].used)fprintf(f,"@last %u %s %u\n",p,choice_marks[p].key,choice_marks[p].costume);
    for(unsigned i=0;i<time_record_count;i++)
        fprintf(f,"@time %s %u %u %u %u\n",time_records[i].key,time_records[i].time,
                time_records[i].name[0],time_records[i].name[1],time_records[i].name[2]);
    if(fclose(f)==0)rename(tmp,path);
}
/* The guest's record, created on first use; NULL for a stock fighter. */
static GuestRecord *find_record(unsigned id) {
    const char *key=tekken3_guest_key(id);
    if(!key)return NULL;
    load();
    for(unsigned i=0;i<record_count;i++)if(!strcmp(records[i].key,key))return &records[i];
    return NULL;
}
static GuestRecord *guest_record(unsigned id) {
    if(tekken3_guest_character(id)<0)return NULL;
    const char *key=tekken3_guest_key(id);
    if(!key)return NULL;
    load();
    for(unsigned i=0;i<record_count;i++)if(!strcmp(records[i].key,key))return &records[i];
    if(record_count>=RECORDS_MAX)return NULL;
    GuestRecord *r=&records[record_count++];
    memset(r,0,sizeof *r);snprintf(r->key,sizeof r->key,"%s",key);
    return r;
}
static uint16_t bump(uint16_t v){return v==0xffff?v:(uint16_t)(v+1);}
static void bump_native(unsigned id,unsigned field) {
    uint32_t at=NATIVE_RECORDS+(id%NATIVES)*RECORD_SIZE+field*2;
    psx_mod_write_half(at,bump(psx_mod_read_half(at)));
}
static void bump_field(unsigned id,unsigned field) {
    GuestRecord *r=guest_record(id);
    if(r)r->field[field]=bump(r->field[field]);
    else bump_native(id,field);
}
static void bump_total(void){psx_mod_write_half(TOTAL,bump(psx_mod_read_half(TOTAL)));}
static int entry(CPUState *cpu,uint32_t address){return cpu->pc==0 || cpu->pc==address;}
static int guest(unsigned id){return tekken3_ttt1_roster_enabled() && tekken3_guest_character(id)>=0;}
/* Done in C: continue at 0x8004C390, which returns to the caller. */
static void finish(CPUState *cpu){save();cpu->pc=SAVE_CHANGED;}

void __wrap_func_800513C0(CPUState *cpu) {
    unsigned id=cpu->gpr[4];
    if(entry(cpu,0x800513c0) && guest(id)){bump_field(id,0);bump_total();finish(cpu);return;}
    __real_func_800513C0(cpu);
}
void __wrap_func_80051464(CPUState *cpu) {
    unsigned winner=cpu->gpr[4],loser=cpu->gpr[5];
    if(entry(cpu,0x80051464) && (guest(winner) || guest(loser))) {
        bump_field(winner,1);bump_field(loser,2);bump_total();finish(cpu);return;
    }
    __real_func_80051464(cpu);
}
void __wrap_func_8005155C(CPUState *cpu) {
    unsigned a=cpu->gpr[4],b=cpu->gpr[5];
    if(entry(cpu,0x8005155c) && (guest(a) || guest(b))) {
        bump_field(a,3);bump_total();bump_field(b,3);bump_total();finish(cpu);return;
    }
    __real_func_8005155C(cpu);
}
void __wrap_func_80051660(CPUState *cpu) {
    unsigned id=cpu->gpr[4];
    if(entry(cpu,0x80051660) && guest(id)) {
        GuestRecord *r=guest_record(id);
        cpu->gpr[2]=r?(uint32_t)r->field[0]+r->field[2]+r->field[3]:0;
        cpu->pc=cpu->gpr[31];return;
    }
    __real_func_80051660(cpu);
}

/* The attract CHARACTERS ranking (state 17 overlay) builds its list at
 * 0x800C19B8 into a fixed structure (0x800CB878): count at +12, the ranked
 * IDs at +14 (halfwords), each fighter's share per mille at +88 + 2 * ID,
 * over IDs 0..20 only (the first ten always, the others once played).
 * Guest IDs would index its shares past the structure. The list is built
 * here instead, at the builder's sort (0x8004CD80, returning to
 * 0x800C1A98): up to 22 fighters, stock and guests, ranked by games, each
 * under a slot 0..21 that stands for it in the list and the shares. The
 * row drawing (0x800C13C4) draws a slot's icon (0x8004B928, icon table
 * 0x8002152C) and name (descriptor table, read directly by the compiled
 * overlay, not through 0x8004EFF0). So a stock fighter keeps its own ID as
 * its slot, a guest takes a slot no stock fighter on the list uses, and
 * while the ranking is up that slot's descriptors point at the guest's and
 * its icon shows the guest's tile (tekken3_ranking_tick restores both). The other two
 * rankings' builder
 * sorts at 0x800C180C with their own IDs: the slots end there when it
 * fills the same structure. */
enum { RANKING_SLOTS=22, RANKING_STATE=17 };
static int ranking_map[RANKING_SLOTS],ranking_count,ranking_live;
static int in_ranking(void) {
    return tekken3_ttt1_roster_enabled() && psx_mod_read_word(0x800ae204)==RANKING_STATE;
}
/* The descriptor tables, four entries (costumes) per ID: the stock one and
 * the guests' extended copy that tekken3_ttt1_roster.c points the game's
 * code at (the compiled overlay reads either). */
enum { DESCRIPTORS=0x80097d40 };
static uint32_t lent_descriptors[2][RANKING_SLOTS][4];
static int lent[RANKING_SLOTS];
static void descriptors_lend(int slot,uint32_t descriptor) {
    uint32_t tables[2]={DESCRIPTORS,tekken3_descriptor_table()};
    if(!descriptor || !tables[1])return;
    for(unsigned t=0;t<2;t++)for(unsigned c=0;c<4;c++) {
        uint32_t at=tables[t]+((unsigned)slot*4+c)*4;
        if(!lent[slot])lent_descriptors[t][slot][c]=psx_mod_read_word(at);
        psx_mod_write_word(at,descriptor);
    }
    lent[slot]=1;
}
static void descriptors_restore(void) {
    for(int slot=0;slot<RANKING_SLOTS;slot++) {
        if(!lent[slot])continue;
        uint32_t tables[2]={DESCRIPTORS,tekken3_descriptor_table()};
        for(unsigned t=0;t<2;t++)for(unsigned c=0;c<4;c++)
            psx_mod_write_word(tables[t]+((unsigned)slot*4+c)*4,lent_descriptors[t][slot][c]);
        lent[slot]=0;
    }
}
/* Other rankings (GREATEST SURVIVORS) draw a guest by its own ID: its icon
 * is lent the icon of a stock fighter they do not list, one per guest. */
static int guest_slot[64];
static int guest_slots_set;
static void ranking_guests_reset(void){memset(guest_slot,0,sizeof guest_slot);guest_slots_set=0;}
int tekken3_ranking_guest_slot(unsigned id) {
    if(!in_ranking() || tekken3_guest_character(id)<0 || id>=64)return -1;
    if(guest_slot[id])return guest_slot[id]-1;
    int shown[RANKING_SLOTS]={0};
    for(unsigned row=0;row<SURVIVAL_ROWS;row++) {
        unsigned r=psx_mod_read_half(survival_row(row));
        if(r<RANKING_SLOTS)shown[r]=1;
    }
    for(int slot=0;ranking_live && slot<RANKING_SLOTS;slot++)if(ranking_map[slot]>=0)shown[slot]=1;
    for(unsigned g=0;g<64;g++)if(guest_slot[g])shown[guest_slot[g]-1]=1;
    for(int slot=RANKING_SLOTS-2;slot>=0;slot--) {
        if(shown[slot] || !tekken3_ranking_face_ok((unsigned)slot))continue;
        guest_slot[id]=slot+1;guest_slots_set=1;
        return slot;
    }
    return -1;
}
/* Every frame: the guests' faces over the icons of their slots while the
 * ranking is up (the overlay may reload its icon sheet); once it is gone,
 * the stock descriptors and icons come back. */
/* Time Attack keeps one best time per stock fighter, 22 rows of {u32 time,
 * name[4]} at 0x80097F4C + 8 * ID. Its results overlay records the run in
 * 0x800B46B8 (called from 0x800B157C): the fighter's ID from 0x800AFB14,
 * that row compared and, for a better time, written (time, then a blank
 * name through 0x8004CC08, called from 0x800B47A8), its address stored at
 * 0x80097F44 for the name entry. A guest's row lies past the table, over the
 * Survival ranking and the counters. For a guest, the row is lent for the
 * call: 0x8005138C, called from 0x800B1528 just before, puts the guest's
 * record (from the records file) there over the bytes it holds; a new
 * record moves to a row of our own, the bytes come back and 0x80097F44
 * points at our row, where the name entry then writes; with no new record
 * the bytes come back on the next frame. The overlay's code is untouched:
 * it runs precompiled, and a changed instruction there is not seen. */
enum { TA_MODE=3, TA_FIGHTER=0x800afb14, TA_TABLE=0x80097f4c, TA_POINTER=0x80097f44,
       TA_NO_TIME=0x57e3f };
static uint32_t ta_row,ta_lent;
static unsigned char ta_backup[8],ta_shown[8];
static unsigned ta_ticks,ta_lent_tick;
static TimeRecord *ta_record;
static TimeRecord *time_record(const char *key) {
    load();
    for(unsigned i=0;i<time_record_count;i++)if(!strcmp(time_records[i].key,key))return &time_records[i];
    if(time_record_count>=RECORDS_MAX)return NULL;
    TimeRecord *r=&time_records[time_record_count++];
    memset(r,0,sizeof *r);snprintf(r->key,sizeof r->key,"%s",key);r->time=TA_NO_TIME;
    for(unsigned i=0;i<3 && key[i];i++)r->name[i]=(unsigned char)(key[i]>='a' && key[i]<='z'?key[i]-32:key[i]);
    for(unsigned i=0;i<3;i++)if(!r->name[i])r->name[i]=' ';
    return r;
}
static void ta_give_back(void) {
    if(!ta_lent)return;
    for(unsigned i=0;i<8;i++)psx_mod_write_byte(ta_lent+i,ta_backup[i]);
    ta_lent=0;
}
void __wrap_func_8005138C(CPUState *cpu) {
    /* One call per stage from the results (a0 = stage 0..9, which also
     * copies the fighter into the mode block); the tenth goes on to record
     * the run. */
    uint32_t back=cpu->gpr[31],stage=cpu->gpr[4];
    __real_func_8005138C(cpu);
    if(back!=0x800b1530 || stage!=9 || !tekken3_ttt1_roster_enabled() ||
       psx_mod_read_word(0x800afa88)!=TA_MODE)return;
    unsigned id=psx_mod_read_byte(TA_FIGHTER);
    const char *key=tekken3_guest_key(id);
    TimeRecord *r=tekken3_guest_character(id)>=0 && key?time_record(key):NULL;
    if(!r || !ta_row)return;
    ta_give_back();
    ta_lent=TA_TABLE+id*8;ta_lent_tick=ta_ticks;ta_record=r;
    for(unsigned i=0;i<8;i++)ta_backup[i]=psx_mod_read_byte(ta_lent+i);
    psx_mod_write_word(ta_lent,r->time);
    for(unsigned i=0;i<4;i++)psx_mod_write_byte(ta_lent+4+i,i<3?r->name[i]:0);
}
void __wrap_func_8004CC08(CPUState *cpu) {
    uint32_t back=cpu->gpr[31];
    __real_func_8004CC08(cpu);
    if(back!=0x800b47a8 || cpu->pc!=back || !ta_lent || !ta_record)return;
    for(unsigned i=0;i<8;i++)psx_mod_write_byte(ta_row+i,psx_mod_read_byte(ta_lent+i));
    ta_give_back();
    psx_mod_write_word(TA_POINTER,ta_row);
    for(unsigned i=0;i<8;i++)ta_shown[i]=psx_mod_read_byte(ta_row+i);
    ta_record->time=psx_mod_read_word(ta_row);
    for(unsigned i=0;i<3;i++)ta_record->name[i]=psx_mod_read_byte(ta_row+4+i);
    save();
}
/* Every frame: the lent row back if no record took it; the name the name
 * entry writes in our row goes to the file. */
static void time_attack_tick(void) {
    ta_ticks++;
    if(!ta_row)ta_row=psx_mod_alloc_guest_memory(8,4);
    if(ta_lent && ta_ticks-ta_lent_tick>=2)ta_give_back();
    if(!ta_row || !ta_record || psx_mod_read_word(TA_POINTER)!=ta_row)return;
    int changed=0;
    for(unsigned i=0;i<8;i++)changed|=psx_mod_read_byte(ta_row+i)!=ta_shown[i];
    if(!changed)return;
    for(unsigned i=0;i<8;i++)ta_shown[i]=psx_mod_read_byte(ta_row+i);
    ta_record->time=psx_mod_read_word(ta_row);
    for(unsigned i=0;i<3;i++)ta_record->name[i]=psx_mod_read_byte(ta_row+4+i);
    save();
}
static void rx_tick(void);
void tekken3_ranking_tick(void) {
    if(guests_pending){guests_pending=0;guests_back();}
    time_attack_tick();
    rx_tick();
    if(!in_ranking()){ranking_guests_reset();ranking_live=0;descriptors_restore();tekken3_ranking_faces_restore();return;}
    for(int slot=0;slot<RANKING_SLOTS;slot++)
        if(ranking_live && ranking_map[slot]>=NATIVES)tekken3_ranking_face((unsigned)slot,(unsigned)ranking_map[slot]);
    for(unsigned g=0;g<64;g++)
        if(guest_slot[g])tekken3_ranking_face((unsigned)guest_slot[g]-1,g);
}
static unsigned games(unsigned id) {
    if(tekken3_guest_character(id)>=0) {
        GuestRecord *r=find_record(id);
        return r?(unsigned)r->field[0]+r->field[2]+r->field[3]:0;
    }
    uint32_t at=NATIVE_RECORDS+(id%NATIVES)*RECORD_SIZE;
    return (unsigned)psx_mod_read_half(at)+psx_mod_read_half(at+4)+psx_mod_read_half(at+6);
}
static void build_ranking(CPUState *cpu) {
    uint32_t list=cpu->gpr[22],pairs=cpu->gpr[4];
    int ids[RANKING_SLOTS+64];unsigned count[RANKING_SLOTS+64],total=0;int n=0;
    for(unsigned id=0;id<NATIVES;id++) {
        unsigned g=games(id);total+=g;
        if(id<=20 && (id<10 || g) && n<RANKING_SLOTS+64){ids[n]=(int)id;count[n++]=g;}
    }
    for(unsigned id=NATIVES;id<NATIVES+64;id++) {
        if(tekken3_guest_character(id)<0)continue;
        unsigned g=games(id);total+=g;
        if(g && n<RANKING_SLOTS+64){ids[n]=(int)id;count[n++]=g;}
    }
    /* Most games first; ties keep the stock order (by ID). */
    for(int i=1;i<n;i++)for(int j=i;j>0 && count[j]>count[j-1];j--) {
        int t=ids[j];ids[j]=ids[j-1];ids[j-1]=t;unsigned c=count[j];count[j]=count[j-1];count[j-1]=c;
    }
    /* Slots: stock fighters their own ID, guests the free ones among 0..20
     * (the stock fighters off the list, from the top; 21's icon is the
     * game's own special one) whose icon overlaps no other. */
    int slot[RANKING_SLOTS+64],used[RANKING_SLOTS]={0},shown=0;
    for(int i=0;i<n;i++)if(ids[i]<NATIVES){slot[i]=ids[i];used[ids[i]]=1;}
    for(int i=0,k=RANKING_SLOTS-2;i<n;i++) {
        if(ids[i]<NATIVES)continue;
        while(k>=0 && (used[k] || !tekken3_ranking_face_ok((unsigned)k)))k--;
        if(k<0){slot[i]=-1;continue;}
        slot[i]=k;used[k]=1;
    }
    descriptors_restore();tekken3_ranking_faces_restore();
    for(int i=0;i<n && shown<RANKING_SLOTS;i++) {
        if(slot[i]<0)continue;
        ids[shown]=ids[i];count[shown]=count[i];slot[shown]=slot[i];shown++;
    }
    n=shown;
    for(int i=0;i<RANKING_SLOTS;i++)ranking_map[i]=-1;
    for(int i=0;i<n;i++) {
        /* 0x8004CD20: games * 1000 / total, 1000 past the total. */
        unsigned share=total<count[i]?1000:total?count[i]*1000u/total:0;
        psx_mod_write_half(list+88+slot[i]*2,(uint16_t)share);
        psx_mod_write_word(pairs+i*8,(uint32_t)slot[i]);
        psx_mod_write_word(pairs+i*8+4,count[i]);
        ranking_map[slot[i]]=ids[i];
        if(ids[i]>=NATIVES)descriptors_lend(slot[i],tekken3_guest_descriptor((unsigned)ids[i]));
    }
    psx_mod_write_half(list+12,(uint16_t)n);
    cpu->gpr[21]=(uint32_t)n;       /* the builder copies s5 entries */
    ranking_count=n;ranking_live=1;
}
/* RECORDS (OPTION MODE, state 5) with the guests. The overlay lists each of
 * its four pages in a 0x20-byte structure {+0 scroll, +4 count, +8 ids}, so 24
 * fighters at most, and reads a row by ID from two tables (TIME ATTACK
 * 0x80097F4C, +2/+4 of the counters 0x8009804C) and a name from descriptor
 * (id mod 22) * 4. Guests have IDs 23 and up. The mod therefore patches the
 * overlay (each patch only where the original word is, so a reloaded overlay
 * is patched again and another one left alone) to read its structures and
 * tables from main RAM at RX (measured free in OPTION MODE: tools/
 * ttt1_records_probe.py), 0x40 bytes per page (56 ids), and to look names up by
 * the full ID (the descriptor tables are the guests' extended ones). The
 * overlay's sort call (0x8004CD80, return 0x800E09DC TIME ATTACK, 0x800E0A94
 * USAGE) is answered here: the list (stock and guests) is built, sorted and
 * written into the page structure, and the overlay's own copy is skipped
 * (its count register is zeroed). The loops that run before the sort write at
 * most 22 pairs to the overlay's 23-pair stack array, so nothing overruns it. */
enum { RX=0x801e0000, RX_END=RX+0x3a0, RX_TA=RX+0x100, RX_WL=RX+0x250, RX_PAGE=0x40, RX_IDS=RX_PAGE-8,
       RECORDS_STATE=5, SCREEN_STATE=0x800ae204, USAGE_TOTAL=0x800ec450 };
typedef struct { uint32_t address,original,value; } CodePatch;
static const CodePatch rx_patches[]={
    {0x800e08d0,0x3c02800f,0x3c02801e},{0x800e08d4,0x2455c458,0x24550000},   /* S1 page structures, init */
    {0x800e0ad0,0x26d60020,0x26d60040},{0x800e0adc,0x26b50020,0x26b50040},   /* S2 S3 stride */
    {0x800e0bc0,0x3c03800f,0x3c03801e},{0x800e0bc8,0x2463c458,0x24630000},   /* S4 page structures, per frame */
    {0x800e0bcc,0x00021140,0x00021180},                                      /* S5 stride (shift 5 -> 6) */
    {0x800df990,0x02042023,0x02002021},{0x800dfca8,0x02038023,0x02008021},   /* N1 N2 names: id, not id mod 22 */
    {0x800dffb8,0x02042023,0x02002021},{0x800e04d4,0x02042023,0x02002021},   /* N3 N4 */
    {0x800df8d4,0x3c028009,0x3c02801e},{0x800df8d8,0x24427f4c,0x24420100},   /* T1 TIME ATTACK rows */
    {0x800e0414,0x3c02800a,0x3c02801e},{0x800e0418,0x2442804c,0x24420250},   /* T2 WINS/LOSSES rows */
};
enum { RX_PATCHES=sizeof rx_patches/sizeof *rx_patches };
static void rx_w32(uint32_t a,uint32_t v){if(a>=RX && a+4<=RX_END)psx_mod_write_word(a,v);}
static void rx_w8(uint32_t a,unsigned v){if(a>=RX && a<RX_END)psx_mod_write_byte(a,(uint8_t)v);}
/* 0 = overlay not there (or another), 1 = stock words, 2 = patched. */
static int rx_overlay(void) {
    unsigned stock=0,patched=0;
    for(unsigned i=0;i<RX_PATCHES;i++) {
        uint32_t w=psx_mod_read_word(rx_patches[i].address);
        stock+=w==rx_patches[i].original;patched+=w==rx_patches[i].value;
    }
    return patched==RX_PATCHES?2:stock==RX_PATCHES?1:0;
}
static void rx_tick(void) {
    if(!tekken3_ttt1_roster_enabled() || psx_mod_read_word(SCREEN_STATE)!=RECORDS_STATE)return;
    if(rx_overlay()!=1)return;
    for(unsigned i=0;i<RX_PATCHES;i++)psx_mod_write_code_word(rx_patches[i].address,rx_patches[i].value);
}
typedef struct { int id; uint32_t key; } RxEntry;      /* key: what the page is sorted on */
static int rx_ascending(const void *a,const void *b) {
    const RxEntry *x=a,*y=b;
    return x->key!=y->key?(x->key<y->key?-1:1):x->id-y->id;
}
static int rx_descending(const void *a,const void *b) {
    const RxEntry *x=a,*y=b;
    return x->key!=y->key?(x->key>y->key?-1:1):x->id-y->id;
}
static const TimeRecord *rx_find_time(unsigned id) {
    const char *key=tekken3_guest_key(id);
    if(!key)return NULL;
    load();
    for(unsigned i=0;i<time_record_count;i++)if(!strcmp(time_records[i].key,key))return &time_records[i];
    return NULL;
}
static unsigned rx_publish(uint32_t page,const RxEntry *e,unsigned n) {
    if(n>RX_IDS)n=RX_IDS;
    for(unsigned i=0;i<n;i++)rx_w8(page+8+i,(unsigned)e[i].id);
    rx_w32(page+4,n);
    return n;
}
/* Returns 1 when the call was answered. */
static int rx_sort(CPUState *cpu) {
    uint32_t back=cpu->gpr[31],page=cpu->gpr[21];
    if((back!=0x800e09dc && back!=0x800e0a94 && back!=0x800e0304) || !tekken3_ttt1_roster_enabled() ||
       psx_mod_read_word(SCREEN_STATE)!=RECORDS_STATE || rx_overlay()!=2)return 0;
    if(page<RX || page>=RX+4*RX_PAGE)return 0;
    RxEntry list[RX_IDS+8];unsigned n=0;
    if(back==0x800e0304) {                                     /* wins / losses page */
        /* The overlay's own pairs {id, key} (stock fighters of the mask in s4) are
         * on the stack at a0; the guests' keys are made the way it makes them. */
        unsigned stock=cpu->gpr[19];
        for(unsigned i=0;i<stock && i<22 && n<RX_IDS;i++) {
            list[n].id=(int)psx_mod_read_word(cpu->gpr[4]+i*8);list[n++].key=psx_mod_read_word(cpu->gpr[4]+i*8+4);
        }
        for(unsigned id=0;id<NATIVES;id++)
            for(unsigned i=0;i<8;i++)rx_w8(RX_WL+id*8+i,psx_mod_read_byte(NATIVE_RECORDS+id*8+i));
        for(unsigned id=NATIVES;id<NATIVES+64 && id*8+8<=0x150;id++) {
            for(unsigned i=0;i<8;i++)rx_w8(RX_WL+id*8+i,0);
            if(tekken3_guest_character(id)<0)continue;
            const GuestRecord *r=find_record(id);
            for(unsigned f=0;r && f<4;f++){rx_w8(RX_WL+id*8+f*2,r->field[f]&0xff);rx_w8(RX_WL+id*8+f*2+1,r->field[f]>>8);}
            unsigned a=r?r->field[1]:0,b=r?r->field[2]:0,sum=a+b,pct=0;
            if(sum)pct=a*1000/sum;
            if(n<RX_IDS){list[n].id=(int)id;list[n++].key=(pct<<20)+sum;}
        }
        qsort(list,n,sizeof *list,rx_descending);
        rx_publish(page,list,n);
        cpu->gpr[19]=0;
    } else if(back==0x800e09dc) {                                     /* TIME ATTACK */
        for(unsigned id=0;id<NATIVES;id++) {
            uint32_t row=TA_TABLE+id*8,time=psx_mod_read_word(row);
            for(unsigned i=0;i<8;i++)rx_w8(RX_TA+id*8+i,psx_mod_read_byte(row+i));
            if(id!=21 && (id<10 || time<TA_NO_TIME) && n<RX_IDS){list[n].id=(int)id;list[n++].key=time;}
        }
        for(unsigned id=NATIVES;id<NATIVES+64 && id*8+8<=0x150;id++) {
            for(unsigned i=0;i<8;i++)rx_w8(RX_TA+id*8+i,0);
            if(tekken3_guest_character(id)<0)continue;
            const TimeRecord *r=rx_find_time(id);
            rx_w32(RX_TA+id*8,r?r->time:TA_NO_TIME);
            for(unsigned i=0;i<4;i++)rx_w8(RX_TA+id*8+4+i,r?r->name[i]:0);
            if(r && r->time<TA_NO_TIME && n<RX_IDS){list[n].id=(int)id;list[n++].key=r->time;}
        }
        qsort(list,n,sizeof *list,rx_ascending);
        rx_publish(page,list,n);
        cpu->gpr[17]=0;                                        /* the overlay's copy is skipped */
    } else {                                                   /* USAGE */
        uint32_t mask=cpu->gpr[19];uint32_t total=psx_mod_read_word(USAGE_TOTAL);
        for(unsigned id=0;id<NATIVES;id++)
            if(id!=21 && (mask>>id&1) && n<RX_IDS){list[n].id=(int)id;list[n++].key=games(id);}
        for(unsigned id=NATIVES;id<NATIVES+64;id++) {
            if(tekken3_guest_character(id)<0)continue;
            unsigned g=games(id);total+=g;
            if(n<RX_IDS){list[n].id=(int)id;list[n++].key=g;}
        }
        qsort(list,n,sizeof *list,rx_descending);
        rx_publish(page,list,n);
        psx_mod_write_word(USAGE_TOTAL,total);                 /* the overlay's own variable: guests' games added */
        cpu->gpr[18]=0;
    }
    cpu->pc=back;
    return 1;
}
void __wrap_func_8004CD80(CPUState *cpu) {
    if(entry(cpu,0x8004cd80) && rx_sort(cpu))return;
    if(entry(cpu,0x8004cd80) && in_ranking()) {
        /* s3 = the structure it fills: the other rankings share it only
         * when they are the ones on screen. */
        if(cpu->gpr[31]==0x800c180c && cpu->gpr[19]==0x800cb878u)ranking_live=0;
        else if(cpu->gpr[31]==0x800c1a98 && psx_mod_read_word(0x800c1a98)==0x12a0000au &&
                cpu->gpr[22]==0x800cb878u) {
            build_ranking(cpu);cpu->pc=cpu->gpr[31];return;
        }
    }
    __real_func_8004CD80(cpu);
}

/* The card itself. The game writes its save from two blocks, 0x48 bytes at
 * 0x80097EF0 and 0x1B0 at 0x80097F4C (0x8004BEC0), and reads them back at
 * 0x8004C240. Two places there name a fighter by ID: the GREATEST SURVIVORS
 * rows (0x80097FFC, ten of {u16 ID, u16 wins, 3 letters + 0}) and each
 * player's last choice (0x80097F0E / F, ID * 4 + costume). A guest's ID must
 * not reach the card: the game without the mod would read an ID it does not
 * know. Just before the card is written, a guest there becomes Jin (9), the
 * fighter the guests are built on, and ttt1-guest-records.txt keeps which
 * guest it was with what identifies the entry (wins and letters, costume);
 * the RAM gets the guests back right after. After the card is read, the
 * entries that still match get their guest back. Without the mod, the rows
 * read as Jin. */
static uint32_t survival_row(unsigned row){return SURVIVAL+row*8;}
static int save_guard(void) {
    int changed=0;
    load();
    for(unsigned row=0;row<SURVIVAL_ROWS;row++) {
        uint32_t at=survival_row(row);unsigned id=psx_mod_read_half(at);
        SurvivalMark *m=&survival_marks[row];
        m->used=0;
        const char *key=tekken3_guest_key(id);
        if(!key)continue;
        m->used=1;snprintf(m->key,sizeof m->key,"%s",key);m->wins=psx_mod_read_half(at+2);
        for(unsigned i=0;i<4;i++)m->name[i]=psx_mod_read_byte(at+4+i);
        psx_mod_write_half(at,JIN);changed=1;
    }
    for(unsigned p=0;p<2;p++) {
        unsigned v=psx_mod_read_byte(LAST_CHOICE+p);
        const char *key=tekken3_guest_key(v>>2);
        choice_marks[p].used=0;
        if(!key)continue;
        choice_marks[p].used=1;snprintf(choice_marks[p].key,sizeof choice_marks[p].key,"%s",key);
        choice_marks[p].costume=v&3;
        psx_mod_write_byte(LAST_CHOICE+p,(uint8_t)(JIN*4+(v&3)));changed=1;
    }
    save();
    return changed;
}
/* Jin entries that match a mark take their guest back. */
static void guests_back(void) {
    load();
    for(unsigned row=0;row<SURVIVAL_ROWS;row++) {
        SurvivalMark *m=&survival_marks[row];
        if(!m->used)continue;
        int id=tekken3_guest_id(m->key);
        if(id<0)continue;
        /* The row the guest was on, else the first Jin row that matches. */
        for(unsigned k=0;k<=SURVIVAL_ROWS;k++) {
            unsigned r=k==0?row:k-1;uint32_t at=survival_row(r);
            if(psx_mod_read_half(at)!=JIN || psx_mod_read_half(at+2)!=m->wins)continue;
            int same=1;
            for(unsigned i=0;i<3;i++)same&=psx_mod_read_byte(at+4+i)==m->name[i];
            if(!same)continue;
            psx_mod_write_half(at,(uint16_t)id);break;
        }
    }
    for(unsigned p=0;p<2;p++) {
        int id=choice_marks[p].used?tekken3_guest_id(choice_marks[p].key):-1;
        if(id>=0 && psx_mod_read_byte(LAST_CHOICE+p)==JIN*4+choice_marks[p].costume)
            psx_mod_write_byte(LAST_CHOICE+p,(uint8_t)(id*4+choice_marks[p].costume));
    }
}
/* The guests come back once the write has copied its blocks: at once when
 * the call returns, else on the next frame (tekken3_ranking_tick). */
void __wrap_func_8004BEC0(CPUState *cpu) {
    uint32_t back=cpu->gpr[31];
    int guarded=tekken3_ttt1_roster_enabled() && entry(cpu,0x8004bec0) && save_guard();
    __real_func_8004BEC0(cpu);
    if(guarded) {
        if(cpu->pc==back)guests_back();
        else guests_pending=1;
    }
}
/* The load reads the card over several dispatches: the first call gives
 * the game back mid-read, and later ones resume inside the function. It is
 * done when a dispatch returns to the first call's return address, with v0
 * 0 on success. The boot's load finishes before the roster is up (no guest
 * has an ID yet): the guests then come back on the roster's first frame. */
static uint32_t load_back;
void __wrap_func_8004C240(CPUState *cpu) {
    if(entry(cpu,0x8004c240))load_back=cpu->gpr[31];
    __real_func_8004C240(cpu);
    if(!load_back || cpu->pc!=load_back)return;
    load_back=0;
    if(cpu->gpr[2]!=0)return;
    if(tekken3_ttt1_roster_enabled())guests_back();
    else guests_pending=1;
}
