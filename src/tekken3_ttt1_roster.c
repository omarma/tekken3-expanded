/* SLUS-00402's opt-in extra roster entry. 21 remains the Force enemies,
 * 22 remains the empty-selection sentinel; Jun owns character ID 23 and
 * model ID 52. Private guest tables extend the stock tables without moving
 * their neighbours. Original disc data is never changed. */
#include "mod_plugins.h"
#include "psx_runtime.h"
#include "gpu_render.h"
#include "psx_sha256.h"
#include "tekken3_ttt1_assets.h"
#include "tekken3_ttt1_ui_palette.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* Widest name bitmap, in halfwords: 19 is the widest stock name (YOSHIMITSU, 76px). */
enum { NAME_MAX_HALFWORDS=19 };
/* Movesets a guest may draw at random (Tetsujin, Unknown):
 * <data prefix>-donors.txt, one "<Donor> <TTT1 moveset key>" per line
 * (tools/ttt1_import.py --moveset); each donor's combat, tables, idle and
 * sound files are <Name>@<Donor>-TTT1-*. A line "switch button" makes the
 * draw happen on L1 in the fight (Unknown) instead of at each round start
 * (Tetsujin). Unknown has 23 donors. */
enum { DONOR_MAX=24 };
/* A TTT1 guest: files, interface, name and moveset key. Every guest of the
 * roster is its own character, ID 23 + its roster index, with its own
 * selector cell on the Tag page. A player's identity is a copy of the roster
 * entry under their cursor (then in their fight); the interface pack stays
 * owned by the roster. `generation` changes with a player's identity: the
 * other modules compare it with the one they loaded and reload on their own. */
typedef struct {
    char key[32],prefix[48],data_prefix[48],label[48],name[48];
    unsigned generation,catalog_index,name_halfwords,moveset;
    unsigned arena_owner;         /* Tekken 3 fighter whose arena it takes; NO_ARENA: the donor's (Jin's) */
    char hands[2];                /* grip of its two hands: F fist, O open, D follows the attacks, else the engine's own */
    int third_costume;            /* <data prefix>-arcade-P3.3dm exists: Start picks it */
    /* `moves_generation` changes with the identity and with each moveset
     * drawn; `donor` is 0 for the guest's own moveset, else donor k+1. */
    unsigned moves_generation,donor_count,donor,previous_donor;
    int on_button;                /* draws on L1 in the fight, not at round start */
    char donor_prefix[DONOR_MAX][48];unsigned donor_moveset[DONOR_MAX];
    unsigned char *ui;
    uint32_t ui_size,ui_offsets[5],ui_lengths[5];
    uint16_t name_pixels[NAME_MAX_HALFWORDS*16];
    uint16_t loading_pixels[16*58];
} Tekken3Guest;
static Tekken3Guest guests[2];
/* TTT1 catalogue: <asset root>/guests.txt lists one imported guest per line
 * (tools/ttt1_stage_roster.py). Read only when no guest is forced at launch; each line
 * may carry the guest's TTT1 moveset key, then the Tekken 3 fighter whose
 * arena it takes. */
enum { CATALOG_MAX=32, NO_MOVESET=32, JUN_MOVESET=28, NO_ARENA=0xff, STOCK_FIGHTERS=22 };
static char catalog[CATALOG_MAX][32];
static unsigned catalog_moveset[CATALOG_MAX],catalog_arena[CATALOG_MAX],catalog_count;
static char catalog_hands[CATALOG_MAX][2];
/* The Tag page holds 18 cells: 8 x 2, then a ninth column of two (see
 * tag_place), so 18 guests: IDs 23..40. */
enum { GUEST_MAX=18 };
static Tekken3Guest roster[GUEST_MAX];
static unsigned roster_count;
static int load_ui(Tekken3Guest *g);
int tekken3_guest_character(unsigned id);
extern void tekken3_ttt1_moved_tiles_hide(void);
static void write_grid_page(void);
/* The stock grid, as the game has it: seven columns by three rows, 21
 * fighters, read from its own table (0x80022768) at start. The game finds a
 * cell as y * 7 + x (compiled in), so the Tag page keeps seven columns for
 * the game and only looks like the Tag page: guest k is the game's cell k,
 * drawn and navigated where tag_place puts it. */
enum { GRID_COLS=7, STOCK_GRID_CELLS=21 };
/* Tag page layout of the cabinet selector: the first sixteen guests on
 * eight columns by two rows, in catalogue order; the guests past them (Wang,
 * Unknown) make a ninth column, one per row. Guest IDs keep the catalogue
 * order whatever the layout. */
enum { TAG_BASE=16, TAG_BASE_COLS=8 };
static unsigned tag_cols(void){return roster_count>TAG_BASE?TAG_BASE_COLS+1:TAG_BASE_COLS;}
static void tag_place(unsigned k,unsigned *col,unsigned *row) {
    if(k<TAG_BASE){*col=k%TAG_BASE_COLS;*row=k/TAG_BASE_COLS;}
    else {*col=TAG_BASE_COLS;*row=k-TAG_BASE;}
}
/* The guest drawn at (col, row) on the Tag page, else -1. */
static int tag_guest_at(unsigned col,unsigned row) {
    for(unsigned k=0;k<roster_count;k++) {
        unsigned c,r;tag_place(k,&c,&r);
        if(c==col && r==row)return (int)k;
    }
    return -1;
}
/* Cells in row `row` of the Tag page: they fill it from column 0. */
static unsigned tag_width(unsigned row) {
    unsigned n=0;
    while(n<tag_cols() && tag_guest_at(n,row)>=0)n++;
    return n;
}
static unsigned team_order[STOCK_GRID_CELLS];
/* Any guest built by tools/ttt1_import.py: its files are named after it
 * ("kunimitsu" -> Kunimitsu-T3-ui.jui, Kunimitsu-TTT1-*), and the name bitmap
 * width comes from its file. Selector text: <Name>-T3-label.txt written by the
 * importer ("P.JACK", "ARMOR KING"), else the upper-case name;
 * TEKKEN3_GUEST_LABEL overrides both. */
static int describe(Tekken3Guest *g,const char *e) {
    size_t n=strlen(e);
    if(!n || n>=sizeof g->key){fprintf(stderr,"TTT1 characters: guest name %s too long\n",e);return 0;}
    memcpy(g->key,e,n+1);
    for(size_t i=0;i<n;i++){
        char c=e[i];
        char lower=(char)(c>='A' && c<='Z'?c-'A'+'a':c);
        g->prefix[i]=i?lower:(char)(lower>='a' && lower<='z'?lower-'a'+'A':lower);
        g->label[i]=(char)(c>='a' && c<='z'?c-'a'+'A':c);
    }
    g->prefix[n]=g->label[n]=0;
    memcpy(g->data_prefix,g->prefix,n+1);
    strcat(g->prefix,"-T3");strcat(g->data_prefix,"-TTT1");
    const char *root=tekken3_ttt1_asset_root(),*l=getenv("TEKKEN3_GUEST_LABEL");
    char path[4096];
    if(root && snprintf(path,sizeof path,"%s/%s-label.txt",root,g->prefix)<(int)sizeof path) {
        FILE *f=fopen(path,"rb");
        if(f){char text[sizeof g->label];size_t k=fread(text,1,sizeof text-1,f);fclose(f);
            while(k && (text[k-1]=='\n' || text[k-1]=='\r'))k--;
            if(k){memcpy(g->label,text,k);g->label[k]=0;}}
    }
    if(l && *l){strncpy(g->label,l,sizeof g->label-1);g->label[sizeof g->label-1]=0;}
    /* The label in ordinary case for the console: "Michelle", "P.Jack". */
    size_t i=0;
    for(;g->label[i] && i<sizeof g->name-1;i++) {
        char c=g->label[i],before=i?g->label[i-1]:0;
        int letter_before=(before>='A' && before<='Z') || (before>='a' && before<='z');
        if(c>='A' && c<='Z' && letter_before)c=(char)(c-'A'+'a');
        else if(c>='a' && c<='z' && !letter_before)c=(char)(c-'a'+'A');
        g->name[i]=c;
    }
    g->name[i]=0;
    g->name_halfwords=0;
    /* TTT1 costumes (tools/ttt1_import.py): -arcade-P1 on punch, -P2 on
     * kick, -P3 on Start for the guests that have a third one. */
    if(root && snprintf(path,sizeof path,"%s/%s-arcade-P3.3dm",root,g->data_prefix)<(int)sizeof path) {
        FILE *f=fopen(path,"rb");
        if(f){g->third_costume=1;fclose(f);}
    }
    g->donor_count=0;g->on_button=0;
    if(root && snprintf(path,sizeof path,"%s/%s-donors.txt",root,g->data_prefix)<(int)sizeof path) {
        FILE *f=fopen(path,"rb");char line[64];
        while(f && g->donor_count<DONOR_MAX && fgets(line,sizeof line,f)) {
            char donor[32];unsigned key;
            if(!strncmp(line,"switch button",13)){g->on_button=1;continue;}
            if(sscanf(line,"%31s %u",donor,&key)!=2 || key>=NO_MOVESET)continue;
            char *prefix=g->donor_prefix[g->donor_count];
            if(snprintf(prefix,sizeof *g->donor_prefix,"%.*s@%s-TTT1",(int)n,g->prefix,donor)>=(int)sizeof *g->donor_prefix)continue;
            char combat[4096];FILE *c;
            if(snprintf(combat,sizeof combat,"%s/%s-combat.jmv",root,prefix)>=(int)sizeof combat || !(c=fopen(combat,"rb")))continue;
            fclose(c);g->donor_moveset[g->donor_count++]=key;
        }
        if(f)fclose(f);
    }
    /* The catalogue tells the moveset key; Jun's is 28 when launched alone. */
    g->moveset=!strcmp(e,"jun")?JUN_MOVESET:NO_MOVESET;
    g->arena_owner=NO_ARENA;
    for(unsigned i=0;i<catalog_count;i++)if(!strcmp(catalog[i],e)){g->moveset=catalog_moveset[i];g->arena_owner=catalog_arena[i];memcpy(g->hands,catalog_hands[i],2);}
    return 1;
}
/* TTT1 catalogue: see above. */
static void read_catalog(void) {
    static int read;
    if(read)return;read=1;
    const char *e=getenv("TEKKEN3_GUEST"),*root=tekken3_ttt1_asset_root();
    char path[4096];
    if((e && *e) || !root || snprintf(path,sizeof path,"%s/guests.txt",root)>=(int)sizeof path)return;
    FILE *f=fopen(path,"rb");if(!f)return;
    char line[64];
    while(catalog_count<CATALOG_MAX && fgets(line,sizeof line,f)) {
        size_t n=strcspn(line," \t\r\n");
        if(!n || n>=sizeof *catalog)continue;
        memcpy(catalog[catalog_count],line,n);catalog[catalog_count][n]=0;
        /* Second column: TTT1 moveset key, '-' or absent when unknown.
         * Third: the Tekken 3 fighter whose arena the guest takes. */
        char *p=line+n,*end=NULL;
        p+=strspn(p," \t");
        unsigned long key=strtoul(p,&end,10);
        catalog_moveset[catalog_count]=end!=p && key<32?(unsigned)key:NO_MOVESET;
        p+=strcspn(p," \t\r\n");p+=strspn(p," \t");
        unsigned long owner=strtoul(p,&end,10);
        catalog_arena[catalog_count]=end!=p && owner<STOCK_FIGHTERS?(unsigned)owner:NO_ARENA;
        /* Fourth: the grip of its two hands, e.g. FD (see Tekken3Guest). */
        p+=strcspn(p," \t\r\n");p+=strspn(p," \t");
        for(unsigned h=0;h<2;h++)catalog_hands[catalog_count][h]=(p[h]=='F'||p[h]=='O'||p[h]=='D')?p[h]:0;
        catalog_count++;
    }
    fclose(f);
    if(catalog_count)fprintf(stderr,"TTT1 characters: %u guests in %s\n",catalog_count,path);
}
int tekken3_guest_catalog_mode(void){read_catalog();return catalog_count>0;}
static int roster_index(const char *key) {
    for(unsigned i=0;i<roster_count;i++)if(!strcmp(roster[i].key,key))return (int)i;
    return -1;
}
static void add_guest(const char *key) {
    if(roster_index(key)>=0)return;
    if(roster_count>=GUEST_MAX){fprintf(stderr,"TTT1 characters: %s left out, the Tag page holds %u guests\n",key,(unsigned)GUEST_MAX);return;}
    Tekken3Guest *g=&roster[roster_count];
    memset(g,0,sizeof *g);
    if(!describe(g,key) || !load_ui(g)){
        fprintf(stderr,"TTT1 characters: %s left out, its interface files failed validation\n",key);
        free(g->ui);memset(g,0,sizeof *g);return;
    }
    g->catalog_index=roster_count++;
}
/* The roster: the catalogue, else the guests forced at launch (TEKKEN3_GUEST,
 * TEKKEN3_GUEST_P2), else Jun. Player 1 starts as TEKKEN3_GUEST or the first
 * guest, player 2 as TEKKEN3_GUEST_P2 or player 1's guest; both then follow
 * the guest cell under their cursor. */
static int set_identity(unsigned player,unsigned index) {
    if(index>=roster_count)return 0;
    unsigned generation=guests[player].generation,moves_generation=guests[player].moves_generation;
    guests[player]=roster[index];
    guests[player].generation=generation+1;
    guests[player].moves_generation=moves_generation+1;
    return 1;
}
static void select_guest(void) {
    static int done;
    if(done)return;done=1;
    const char *e=getenv("TEKKEN3_GUEST"),*e2=getenv("TEKKEN3_GUEST_P2");
    if(tekken3_guest_catalog_mode())for(unsigned i=0;i<catalog_count;i++)add_guest(catalog[i]);
    if(e && *e)add_guest(e);
    if(e2 && *e2)add_guest(e2);
    if(!roster_count)add_guest("jun");
    int first=e && *e?roster_index(e):0,second=e2 && *e2?roster_index(e2):-1;
    set_identity(0,first<0?0u:(unsigned)first);
    set_identity(1,second<0?guests[0].catalog_index:(unsigned)second);
}
/* A native fighter on its TTT1 moveset (chosen at the selector, tekken3_native_moves.c):
 * its moves, tables, idle stance and move sounds are <Name>-TTT1-*, read
 * through the same identity as a guest's; the model and the cries stay the
 * native's. `native_id` is the character it holds for, NO_NATIVE when off.
 * The two identities of a player move their generations together, so a
 * change either way reloads everything that depends on them. */
enum { NO_NATIVE=0xffff };
static Tekken3Guest natives[2];
static unsigned native_id[2]={NO_NATIVE,NO_NATIVE};
/* Devil Jin on his TTT1 moves (tekken3_devil_jin_moves, tekken3_ttt1_mod.c):
 * his moves, tables, idle stance and move sounds are DevilJin-TTT1-*, read
 * through the same identity as a guest's. His model, name plate and cries
 * are the easter egg's and Jin's, found elsewhere. */
extern int tekken3_devil_jin_moves(unsigned player);
static Tekken3Guest devil_moves[2];
static int devil_moves_on[2];
/* A player's three identities (guest, native on TTT1 moves, Devil Jin) move
 * their generations together: a change of any reloads what depends on them. */
static void bump(unsigned player) {
    Tekken3Guest *all[3]={&guests[player],&natives[player],&devil_moves[player]};
    unsigned generation=0,moves=0;
    for(unsigned i=0;i<3;i++) {
        if(all[i]->generation>generation)generation=all[i]->generation;
        if(all[i]->moves_generation>moves)moves=all[i]->moves_generation;
    }
    for(unsigned i=0;i<3;i++){all[i]->generation=generation+1;all[i]->moves_generation=moves+1;}
}
int tekken3_native_moves_set(unsigned player,unsigned id,const char *key,unsigned moveset) {
    if(player>1)return 0;
    select_guest();
    if(!key) {
        if(native_id[player]==NO_NATIVE)return 1;
        native_id[player]=NO_NATIVE;bump(player);
        fprintf(stderr,"TTT1 characters: P%u back to the native moveset\n",player+1);
        return 1;
    }
    if(native_id[player]==id && !strcmp(natives[player].key,key))return 1;
    Tekken3Guest g;memset(&g,0,sizeof g);
    if(!describe(&g,key))return 0;
    g.moveset=moveset;g.generation=natives[player].generation;g.moves_generation=natives[player].moves_generation;
    natives[player]=g;native_id[player]=id;bump(player);
    fprintf(stderr,"TTT1 characters: P%u %s on the TTT1 moveset (%s, moveset %u)\n",player+1,g.name,g.data_prefix,moveset);
    return 1;
}
unsigned tekken3_native_moves_id(unsigned player){return player<2?native_id[player]:NO_NATIVE;}
static const Tekken3Guest *guest(unsigned player) {
    select_guest();
    if(player>1)player=0;
    int on=tekken3_devil_jin_moves(player)!=0;
    if(on!=devil_moves_on[player]) {
        Tekken3Guest *d=&devil_moves[player];
        if(on) {
            memset(d,0,sizeof *d);
            strcpy(d->key,"deviljin");strcpy(d->prefix,"Jin-T3");strcpy(d->data_prefix,"DevilJin-TTT1");
            strcpy(d->label,"DEVIL JIN");strcpy(d->name,"Devil Jin");
            d->moveset=9;                  /* TTT1 Jin's: the rules his moves test */
        }
        devil_moves_on[player]=on;bump(player);
    }
    if(on)return &devil_moves[player];
    return native_id[player]!=NO_NATIVE?&natives[player]:&guests[player];
}
const char *tekken3_guest_data_prefix_for(unsigned player){return guest(player)->data_prefix;}
const char *tekken3_guest_ui_prefix_for(unsigned player){return guest(player)->prefix;}
const char *tekken3_guest_label_for(unsigned player){return guest(player)->label;}
const char *tekken3_guest_name_for(unsigned player){return guest(player)->name;}
unsigned tekken3_guest_generation(unsigned player){return guest(player)->generation;}
extern int tekken3_devil_jin_player(unsigned player);
/* Each player's costume, 0 punch, 1 kick, 2 Start, as the game keeps it for
 * any fighter: the team entry's low bits (ID * 4 + costume), copied to
 * 0x800ADD98 + 2 * player for the loading screen and to the actor's +0x14. */
static unsigned costumes[2];
unsigned tekken3_guest_costume(unsigned player){return player<2?costumes[player]:0;}
static void follow_costume(unsigned player,unsigned costume) {
    if(costume>2)costume=0;
    if(costume==costumes[player])return;
    costumes[player]=costume;
    fprintf(stderr,"TTT1 characters: P%u costume %u\n",player+1,costume+1);
}
unsigned tekken3_guest_moveset(unsigned player) {
    const Tekken3Guest *g=guest(player);
    return g->donor?g->donor_moveset[g->donor-1]:g->moveset;
}
/* Combat, tables, idle stance and move sounds: the drawn donor's, else the
 * guest's own. Model, voices and hit effect keep the guest's data prefix. */
const char *tekken3_guest_moves_prefix_for(unsigned player) {
    const Tekken3Guest *g=guest(player);
    return g->donor?g->donor_prefix[g->donor-1]:g->data_prefix;
}
unsigned tekken3_guest_moves_generation(unsigned player){return guest(player)->moves_generation;}
/* Round start, where T3 draws Mokujin's moveset (0x8004F2DC, character 15
 * only) and TTT1 Tetsujin's (0x801293F0, also on each tag entry): a guest
 * with donors draws one of them, repeats allowed, as both games do.
 * TEKKEN3_TETSUJIN_MOVESET=<donor> forces it. Returns 1 when it changed. */
static uint32_t draw_state;
static unsigned draw(unsigned count) {
    if(!draw_state)draw_state=(uint32_t)time(NULL)*2654435761u|1u;
    draw_state^=draw_state<<13;draw_state^=draw_state>>17;draw_state^=draw_state<<5;
    return draw_state%count;
}
/* TEKKEN3_TETSUJIN_MOVESET=<donor>: that donor's index + 1, else 0. */
static unsigned forced_donor(const Tekken3Guest *g) {
    const char *forced=getenv("TEKKEN3_TETSUJIN_MOVESET");
    if(forced && *forced)for(unsigned k=0;k<g->donor_count;k++) {
        const char *d=strchr(g->donor_prefix[k],'@')+1,*f=forced;
        while(*f && (*d|32)==(*f|32)){d++;f++;}
        if(!*f && *d=='-')return k+1;
    }
    return 0;
}
int tekken3_guest_draw_moveset(unsigned player) {
    if(player>1 || tekken3_guest_character(psx_mod_read_half(0x800a9240+player*0x188c))<0)return 0;
    select_guest();
    Tekken3Guest *g=&guests[player];
    if(!g->donor_count || g->on_button)return 0;
    unsigned pick=draw(g->donor_count),forced=forced_donor(g);
    if(forced)pick=forced-1;
    g->donor=pick+1;g->moves_generation++;
    const char *at=strchr(g->donor_prefix[pick],'@');
    fprintf(stderr,"TTT1 characters: P%u %s draws %.*s at round start (moveset %u)\n",player+1,g->name,
            (int)(strlen(at+1)-5),at+1,g->donor_moveset[pick]);
    return 1;
}
/* Unknown (TTT1: a cancel rule on the Tag button from her neutral moves,
 * 0x800B, bits 7..12 = 35, drawn by 0x80101198): L1 in the fight takes
 * another of her movesets at random, never the one she has. She starts each
 * fight with her own (Jun's, the TTT1 key 28). */
int tekken3_guest_switches_on_button(unsigned player) {
    if(player>1 || tekken3_guest_character(psx_mod_read_half(0x800a9240+player*0x188c))<0)return 0;
    return guest(player)->on_button && guest(player)->donor_count>1;
}
int tekken3_guest_switch_moveset(unsigned player) {
    if(!tekken3_guest_switches_on_button(player))return 0;
    Tekken3Guest *g=&guests[player];
    unsigned current=tekken3_guest_moveset(player),others=0;
    for(unsigned k=0;k<g->donor_count;k++)if(g->donor_moveset[k]!=current)others++;
    if(!others)return 0;
    unsigned n=draw(others),pick=0;
    for(unsigned k=0;k<g->donor_count;k++)if(g->donor_moveset[k]!=current && !n--){pick=k;break;}
    g->previous_donor=g->donor;g->donor=pick+1;g->moves_generation++;
    const char *at=strchr(g->donor_prefix[pick],'@');
    fprintf(stderr,"TTT1 characters: P%u %s switches to %.*s (moveset %u)\n",player+1,g->name,
            (int)(strlen(at+1)-5),at+1,g->donor_moveset[pick]);
    return 1;
}
/* The drawn moveset did not load: the one before it again. */
int tekken3_guest_switch_undo(unsigned player) {
    if(!tekken3_guest_switches_on_button(player))return 0;
    Tekken3Guest *g=&guests[player];
    g->donor=g->previous_donor;g->moves_generation++;
    return 1;
}
/* A new fight starts on the guest's own moveset, or on the one
 * TEKKEN3_TETSUJIN_MOVESET forces (tools/ttt1/combos.py probes Unknown's). */
static void reset_button_donor(unsigned player) {
    Tekken3Guest *g=&guests[player];
    unsigned start=forced_donor(g);
    if(!g->on_button || g->donor==start)return;
    g->donor=start;g->moves_generation++;
    if(start)fprintf(stderr,"TTT1 characters: P%u %s starts on %s\n",player+1,g->name,g->donor_prefix[start-1]);
    else fprintf(stderr,"TTT1 characters: P%u %s back to her own moveset\n",player+1,g->name);
}
const char *tekken3_guest_data_prefix(void){return tekken3_guest_data_prefix_for(0);}
const char *tekken3_guest_ui_prefix(void){return tekken3_guest_ui_prefix_for(0);}
const char *tekken3_guest_label(void){return tekken3_guest_label_for(0);}
const char *tekken3_guest_name(void){return tekken3_guest_name_for(0);}
/* Guest data that must follow the identity lives in one reserved area per
 * player of the mod memory, emptied when that player's guest changes: the
 * allocator never frees, and one guest's combat data takes up to 333 KiB
 * (Tetsujin) plus its per-player tables. */
enum { POOL_SIZE=0x88000 };
/* A guest that switches moves in the fight (Unknown) loads the new pack
 * while the fighter still plays the old one, whose records and clips the
 * engine keeps pointing at: each player has two areas, used in turn
 * (tekken3_guest_pool_flip), the second allocated on the first switch. */
static uint32_t pool[2][2],pool_used[2];static unsigned pool_side[2];
uint32_t tekken3_guest_pool_alloc(unsigned slot,uint32_t size,uint32_t alignment) {
    if(slot>1)return 0;
    uint32_t *area=&pool[slot][pool_side[slot]];
    if(!*area && !(*area=psx_mod_alloc_guest_memory(POOL_SIZE,16))){
        fprintf(stderr,"TTT1 characters: guest pool allocation failed\n");return 0;
    }
    if(!alignment)alignment=1;
    uint32_t start=(pool_used[slot]+alignment-1)&~(alignment-1);
    if(start>POOL_SIZE || size>POOL_SIZE-start){
        fprintf(stderr,"TTT1 characters: P%u guest pool full (%u + %u of %u bytes)\n",slot+1,start,size,(unsigned)POOL_SIZE);
        return 0;
    }
    pool_used[slot]=start+size;
    for(uint32_t i=0;i<size;i+=4)psx_mod_write_word(*area+start+i,0);
    return *area+start;
}
void tekken3_guest_pool_reset(unsigned slot){if(slot<2)pool_used[slot]=0;}
void tekken3_guest_pool_flip(unsigned slot){if(slot<2){pool_side[slot]^=1;pool_used[slot]=0;}}
/* Guest k is character GUEST_ID+k. All of them share model 52: its file is
 * loaded per player. */
enum { GUEST_ID=23, GUEST_MODEL=52, STOCK_CELLS=21,
       /* The menu's unused fighter-texture scratch, outside the font atlas
        * at x=896..943. Native fighter loading restores this area before play. */
       ICON_X=448, ICON_Y=160, ICON_PAGE=0x87,
       /* Tag page tiles (8bpp, 32x58): texture page (384,0), eight per row
        * from y=16; one 256-colour palette each at (0,480+k). Both areas are
        * empty while the selector runs, and the fighters' loading replaces
        * them before play. */
       TILE_X=384, TILE_Y=16, TILE_PAGE=0x86, TILE_PALETTE_Y=480,
       /* Loading-screen card palettes: rows 496 and 497 are empty there
        * (x 0..255). The stock loading screen draws its background with row
        * 502 and uses row 503: a card palette there shows through it. */
       LOADING_PALETTE_Y=496 };
/* 92 = 23 characters x 4 descriptor entries; each guest adds 4. The selector
 * overlay and the descriptor code test "ID < 22" (0x16): guest IDs pass up to
 * GUEST_ID+roster_count. */
static unsigned team_bound(void){return GUEST_ID+roster_count;}
static unsigned desc_bound(void){return 92+4*roster_count;}
static unsigned select_bound(void){return GUEST_ID+roster_count;}

/* Tag page grid on the cabinet selector: the stock ten-column grid (35px
 * pitch from x=11, rows 62px apart), eight columns from its second slot,
 * the ninth column (tag_place) on its last slot, where Jin stands on the
 * stock page. The 16:9 view knows the grid by those ten slots. 22 (0x16)
 * is the stock "no neighbour" value; the Tag page never reaches 22 cells. */
enum { GRID_PITCH_X=35, GRID_PITCH_Y=62, TAG_X0=11+GRID_PITCH_X, GRID_NONE=0x16 };
/* Guest k for a character ID, else -1. */
extern void tekken3_ranking_tick(void);
extern int tekken3_ranking_guest_slot(unsigned id);
int tekken3_guest_character(unsigned id) {
    return id>=GUEST_ID && id<GUEST_ID+roster_count?(int)(id-GUEST_ID):-1;
}
/* Grip of a guest's hand (0 first, 1 second: rows 13 and 17 of its model): 'F' fist,
 * 'O' open, 'D' follows the attacks, 0 when the engine's own applies. */
char tekken3_guest_hand(unsigned id,unsigned hand) {
    int k=tekken3_guest_character(id);
    return k<0||hand>1?0:roster[k].hands[hand];
}
/* Character ID of a guest key, else -1. */
int tekken3_guest_id(const char *key) {
    for(unsigned k=0;key && k<roster_count;k++)if(!strcmp(roster[k].key,key))return (int)(GUEST_ID+k);
    return -1;
}
/* Guest key (tools/data/ttt1_characters.json) for a character ID, else NULL. */
const char *tekken3_guest_key(unsigned id) {
    int k=tekken3_guest_character(id);
    return k<0?NULL:roster[k].key;
}
/* Imported guests carry no frozen digest: every loader keeps its structural
 * checks and skips only the identity comparison. */
int tekken3_guest_digests_frozen(void){return 0;}

static uint32_t metadata,model_map,model_sizes,team_table,ui_color,body_profiles,desc,name_table;
static Ttt1UiPalette loading_palette[2];
/* Rows 496/497 hold arena palettes during the fight (Paul's floor, among
 * others), and the fight's last picture stays on screen for the first
 * frames of state 11: the OpenGL renderer draws it again from VRAM, so a
 * card palette put up then darkens the floor. It goes up when the loading
 * screen first asks for the card, the fight gone. */
static int loading_card_drawn[2];
static uint32_t stock_icon_uv,stock_icon_page;
/* Selector names. The overlay draws a character's name from the name atlas
 * (texture page 704,0) at u = (ID & 16) * 8, v = (ID & 15) * 16 (0x8010E8B4):
 * two columns of sixteen. 32..38 would wrap onto PAUL..HWOARANG, and the
 * second column has only rows 6..15 free. That computation is replaced by a
 * lookup in name_table[ID]; each player's hovered guest gets row 7 (player 1)
 * or 8 (player 2) of the second column, where its name is uploaded. */
enum { NAME_X=736, NAME_ROW=7, NAME_TABLE_IDS=64 };
static void patch_name_lookup(void) {
    static const uint32_t stock[5]={0x000310c0,0x30420080,0x3063000f,0x00031b00,0x00431025};
    for(unsigned i=0;i<5;i++)if(psx_mod_read_word(0x8010e8b4+i*4)!=stock[i])return;
    /* sll v1,v1,2 ; lui v0,hi ; addu v0,v0,v1 ; lw v0,lo(v0) ; nop */
    uint32_t hi=(name_table+0x8000)>>16,lo=name_table&0xffff;
    const uint32_t lookup[5]={0x00031880,0x3c020000|hi,0x00431021,0x8c420000|lo,0};
    for(unsigned i=0;i<5;i++)psx_mod_write_code_word(0x8010e8b4+i*4,lookup[i]);
}
static void write_names(void) {
    for(unsigned id=0;id<NAME_TABLE_IDS;id++)
        psx_mod_write_word(name_table+id*4,((id<<3)&0x80)|((id&15)<<12));
    unsigned shown[2]={~0u,~0u};
    for(unsigned p=0;p<2;p++) {
        unsigned id=psx_mod_read_word(0x80118668+p*0x7c);
        int k=tekken3_guest_character(id);
        if(k<0)continue;
        unsigned row=NAME_ROW+p;
        if(p==1 && shown[0]==id)row=NAME_ROW;   /* the same guest: one row */
        else gr_vram_transfer_in(NAME_X,row*16,roster[k].name_halfwords,16,roster[k].name_pixels);
        psx_mod_write_word(name_table+id*4,0x80|(row<<12));
        shown[p]=id;
    }
}
static int initialized,attempted,enabled=-1;
extern void tekken3_ttt1_select(int enabled);
extern void __real_func_80052938(CPUState*);
extern void __real_func_80052940(CPUState*);
extern void __real_func_8004B790(CPUState*);
extern void __real_func_8004B928(CPUState*);
extern void __real_func_80031BFC(CPUState*);
extern void __real_func_80052AD0(CPUState*);
extern void __real_func_80052958(CPUState*);
extern void __real_func_80052990(CPUState*);
extern void __real_func_8006BF20(CPUState*);
extern void __real_func_8003626C(CPUState*);
extern void __real_func_80036294(CPUState*);
extern void __real_func_800362C4(CPUState*);
extern void __real_func_8003F044(CPUState*);
extern void __real_func_8002D1DC(CPUState*);
extern void __real_func_8004F3B0(CPUState*);

/* TEKKEN3_TTT1_ROSTER=0 (or its former name TEKKEN3_JUN_ROSTER=0) keeps the
 * stock selector. */
static int roster_setting(void) {
    const char *p=getenv("TEKKEN3_TTT1_ROSTER");
    if(!p || !*p)p=getenv("TEKKEN3_JUN_ROSTER");
    return !p || strcmp(p,"0");
}
int tekken3_ttt1_roster_enabled(void) {
    if(enabled<0)enabled=roster_setting();
    return enabled && initialized;
}
static uint32_t u32(const unsigned char *p) {return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static uint16_t u16(const unsigned char *p) {return p[0]|(uint16_t)p[1]<<8;}
static void copy_guest(uint32_t dst,uint32_t src,unsigned n) {
    for(unsigned i=0;i<n;i++)psx_mod_write_byte(dst+i,psx_mod_read_byte(src+i));
}
static void copy_host(uint32_t dst,const unsigned char *src,unsigned n) {
    for(unsigned i=0;i<n;i++)psx_mod_write_byte(dst+i,src[i]);
}
static void patch(uint32_t address,uint32_t expected,uint32_t replacement) {
    uint32_t actual=psx_mod_read_word(address);
    if(actual==expected)psx_mod_write_code_word(address,replacement);
}
static void indirect(uint32_t address,uint32_t expected) {
    unsigned offset=expected&65535;
    uint32_t target=offset==0x7d40?metadata:offset==0x58c4?model_map:offset==0x5a9c?model_sizes:team_table;
    /* A LUI replaces ADDIU without introducing a MIPS load-delay hazard.
     * Each extended table therefore has a 64 KiB aligned guest address. */
    patch(address,expected,0x3c000000u|(expected&0x001f0000u)|(target>>16));
}
static void immediate(uint32_t address,unsigned expected,unsigned replacement) {
    uint32_t op=psx_mod_read_word(address);
    if((op&65535)==expected)patch(address,op,(op&0xffff0000)|replacement);
}
/* Table bounds are rewritten ABSOLUTELY, not incrementally. immediate() only
 * fires when the operand still holds the stock value, so replaying it after a
 * first guest is a silent no-op - the classic way a second character ends up
 * reading past a table with no error at all. This variant accepts anything
 * from the stock value up to the target, and is idempotent at the target. */
static void bound(uint32_t address,unsigned stock,unsigned target) {
    uint32_t op=psx_mod_read_word(address);
    unsigned cur=op&65535;
    if(cur==target || cur<stock || cur>target)return;
    patch(address,op,(op&0xffff0000)|target);
}
/* The interface pack (<prefix>-ui.jui) alone: portrait, tiles, loading card. */
static int load_ui_pack(Tekken3Guest *g) {
    const char *root=tekken3_ttt1_asset_root();char path[4096];
    g->ui=NULL;
    if(!root || snprintf(path,sizeof path,"%s/%s-ui.jui",root,g->prefix)>=(int)sizeof path)return 0;
    FILE *f=fopen(path,"rb");if(!f){fprintf(stderr,"%s interface: missing %s\n",g->name,path);return 0;}
    unsigned char h[56];int ok=fread(h,1,sizeof h,f)==sizeof h;
    /* The pack size comes from its own header; the five payload checks
     * below pin the geometry. */
    if(!ok || u32(h)!=0x3149554a || u32(h+4)!=1 || u32(h+8)!=5 ||
       u32(h+12)<56){fclose(f);return 0;}
    g->ui_size=u32(h+12);g->ui=malloc(g->ui_size);if(!g->ui){fclose(f);return 0;}
    memcpy(g->ui,h,sizeof h);ok=fread(g->ui+56,1,g->ui_size-56,f)==g->ui_size-56 && fgetc(f)==EOF;fclose(f);
    for(unsigned i=0;ok && i<5;i++) {
        unsigned o=u32(h+16+i*8),n=u32(h+20+i*8);
        static const unsigned widths[5]={126,32,32,32,32},heights[5]={252,68,58,34,29};
        ok=o>=56 && o<=g->ui_size && n<=g->ui_size-o && n==544+widths[i]*heights[i] &&
           u32(g->ui+o)==16 && u32(g->ui+o+4)==9 && u32(g->ui+o+8)==524 &&
           u16(g->ui+o+540)==widths[i]/2 && u16(g->ui+o+542)==heights[i];
        g->ui_offsets[i]=o;g->ui_lengths[i]=n;
    }
    if(!ok){free(g->ui);g->ui=NULL;return 0;}
    /* Arcade loading thumbnails have half-height pixels. The PS1's framed
     * team cards use 58 rows, so preserve their aspect ratio. */
    const unsigned char *small=g->ui+g->ui_offsets[4]+544;
    for(unsigned y=0;y<58;y++)memcpy(g->loading_pixels+y*16,small+(y/2)*32,32);
    return 1;
}
static int load_ui(Tekken3Guest *g) {
    const char *root=tekken3_ttt1_asset_root();char path[4096];
    if(!load_ui_pack(g))return 0;
    if(snprintf(path,sizeof path,"%s/%s-name.4bpp",root,g->prefix)>=(int)sizeof path)return 0;
    FILE *f=fopen(path,"rb");if(!f){fprintf(stderr,"%s interface: missing %s\n",g->name,path);free(g->ui);g->ui=NULL;return 0;}
    /* 16 rows of 4bpp, so the width is size / 32. */
    long size=(fseek(f,0,SEEK_END)==0)?ftell(f):-1;rewind(f);
    if(size<=0 || size%32 || size/32<1 || size/32>NAME_MAX_HALFWORDS){
        fprintf(stderr,"%s interface: name bitmap of %ld bytes, at most %u halfwords wide\n",g->name,size,(unsigned)NAME_MAX_HALFWORDS);
        fclose(f);free(g->ui);g->ui=NULL;return 0;
    }
    g->name_halfwords=(unsigned)(size/32);
    unsigned name_bytes=g->name_halfwords*16*2;   /* halfwords x 16 rows */
    int ok=fread(g->name_pixels,1,name_bytes,f)==name_bytes && fgetc(f)==EOF;fclose(f);
    if(!ok){free(g->ui);g->ui=NULL;return 0;}
    return 1;
}
/* Panda (Kuma, ID 11, kick costume) and Tiger (Eddy, ID 8, third costume):
 * the PS1 game only changes their name, and keeps Kuma's and Eddy's faces.
 * TTT1's loading portraits give them their own (tools/ttt1_panda_tiger.py,
 * Panda-T3-ui.jui and Tiger-T3-ui.jui, the guests' pack format). They show
 * once the costume is confirmed, like the name: the cell under the cursor
 * stays Kuma's or Eddy's. */
enum { ALT_FACES=2 };
static Tekken3Guest alt_faces[ALT_FACES];
static const unsigned alt_face_id[ALT_FACES]={11,8},alt_face_costume[ALT_FACES]={1,2};
static void alt_faces_load(void) {
    static int loaded;
    if(loaded)return;loaded=1;
    static const char *const prefix[ALT_FACES]={"Panda-T3","Tiger-T3"};
    for(unsigned i=0;i<ALT_FACES;i++) {
        Tekken3Guest *g=&alt_faces[i];
        strcpy(g->prefix,prefix[i]);strcpy(g->name,i?"Tiger":"Panda");
        if(!load_ui_pack(g))fprintf(stderr,"TTT1 characters: no %s portrait, %s keeps %s's\n",g->name,g->name,i?"Eddy":"Kuma");
    }
}
/* The face for character `id` in `costume` (0 punch, 1 kick, 2 Start), or NULL. */
static const Tekken3Guest *alt_face(unsigned id,unsigned costume) {
    for(unsigned i=0;i<ALT_FACES;i++)
        if(alt_faces[i].ui && id==alt_face_id[i] && costume==alt_face_costume[i])return &alt_faces[i];
    return NULL;
}
static int alt_face_character(unsigned id){return id==alt_face_id[0] || id==alt_face_id[1];}
/* Survival's results (state 14) list the fighters beaten by character, ID
 * * 4 with no costume, and a count each. The CPU's fighter of each fight
 * won is noted here (survival_tick): a character beaten only as Panda or
 * Tiger shows that face; beaten in both, it keeps the stock one, the
 * screen having a single cell for the two. */
enum { BEATEN_STOCK=1, BEATEN_ALT=2 };
static uint8_t survival_beaten[23];
static int survival_end(unsigned state) {
    return state==14 && psx_mod_read_word(0x800afa88)==4;
}
static const Tekken3Guest *survival_face(unsigned id) {
    if(id>=sizeof survival_beaten || survival_beaten[id]!=BEATEN_ALT)return NULL;
    for(unsigned a=0;a<ALT_FACES;a++)if(alt_face_id[a]==id)return alt_face(id,alt_face_costume[a]);
    return NULL;
}
/* Guest k's descriptor: 12 bytes copied from Jin's, then its label. */
enum { DESC_STRIDE=80 };
static uint32_t guest_desc(unsigned k){return desc+k*DESC_STRIDE;}
/* The guests' extended descriptor table, and a guest's descriptor for a
 * character ID (0 for a stock fighter). */
uint32_t tekken3_descriptor_table(void){return metadata;}
uint32_t tekken3_guest_descriptor(unsigned id){int k=tekken3_guest_character(id);return k<0?0:guest_desc((unsigned)k);}
static void write_label(unsigned k) {
    const Tekken3Guest *g=&roster[k];
    uint32_t d=guest_desc(k);
    unsigned n=(unsigned)strlen(g->label)+1;
    if(n>DESC_STRIDE-12)n=DESC_STRIDE-12;
    copy_host(d+12,(const unsigned char*)g->label,n);
    psx_mod_write_byte(d+DESC_STRIDE-1,0);
    /* Octet 5 = largeur du nom en PIXELS, pas une constante : JUN fait 24 px
     * (6 demi-mots de 4 px) et le stock y mettait 24 en dur, ce qui tronquait
     * KAZUYA -- 48 px de bitmap -- a ses trois premieres lettres. Les noms
     * natifs comme YOSHIMITSU tiennent parce que le jeu lit cette largeur et
     * une chaine terminee par un zero, sans borne fixe. */
    psx_mod_write_byte(d+5,(unsigned char)(g->name_halfwords*4));
}
static void initialize(void) {
    if(attempted)return;attempted=1;
    select_guest();
    if(!roster_count){fprintf(stderr,"TTT1 characters: no guest passed interface validation\n");return;}
    uint32_t allocation=psx_mod_alloc_guest_memory(0x41000,16);
    if(!allocation){fprintf(stderr,"TTT1 characters: roster allocation failed\n");return;}
    uint32_t area=(allocation+65535u)&~65535u;
    metadata=area;model_map=area+0x10000;model_sizes=area+0x20000;team_table=area+0x30000;ui_color=area+0x30100;
    desc=area+0x30120;name_table=area+0x30800;
    stock_icon_uv=psx_mod_read_word(0x8002152c+21*8);
    stock_icon_page=psx_mod_read_word(0x8002152c+21*8+4);
    copy_guest(metadata,0x80097d40,92*4);
    copy_guest(model_map,0x800958c4,92);
    copy_guest(model_sizes,0x80095a9c,52*12);
    copy_guest(model_sizes+52*12,0x80095a9c+18*12,12);
    /* Body separation has its own eight-sphere table, independent of the
     * fourteen damage hurtboxes. The stock table ends at character 21;
     * indexing it with Jun's ID read 0x0000000e as a profile pointer. */
    body_profiles=model_sizes+0x1000;
    copy_guest(body_profiles,0x80096f60,22*4);
    for(unsigned k=0;k<roster_count;k++) {
        uint32_t d=guest_desc(k);
        psx_mod_write_word(body_profiles+(GUEST_ID+k)*4,psx_mod_read_word(0x80096f60+9*4));
        copy_guest(d,0x80022274,12);
        /* Le mot 0 du descripteur est un POINTEUR vers une chaine terminee par
         * un zero, pas un champ de taille fixe : c'est ainsi que YOSHIMITSU
         * tient a l'ecran. */
        psx_mod_write_word(d,d+12);
        psx_mod_write_byte(d+4,(unsigned char)(GUEST_ID+k));psx_mod_write_byte(d+9,(unsigned char)(GUEST_ID+k));
        /* Byte 10 is the arena, byte 11 the music: those of the fighter the
         * catalogue names, read from that fighter's own record, for the
         * readers that follow the extended table (0x8004F3B0 does not; see
         * __wrap_func_8004F3B0). */
        if(roster[k].arena_owner<STOCK_FIGHTERS) {
            uint32_t owner=psx_mod_read_word(0x80097d40+roster[k].arena_owner*16);
            psx_mod_write_byte(d+10,psx_mod_read_byte(owner+10));
            psx_mod_write_byte(d+11,psx_mod_read_byte(owner+11));
        }
        write_label(k);
        for(unsigned c=0;c<4;c++) {
            psx_mod_write_word(metadata+((GUEST_ID+k)*4+c)*4,d);
            psx_mod_write_byte(model_map+(GUEST_ID+k)*4+c,GUEST_MODEL);
        }
    }
    psx_mod_write_word(ui_color,0xead8b395); /* original portrait index 21, warm pale tint */
    for(unsigned i=0;i<STOCK_GRID_CELLS;i++)team_order[i]=psx_mod_read_byte(0x80022768+i*6+4);
    write_grid_page();
    alt_faces_load();
    initialized=1;
    fprintf(stderr,"TTT1 characters: %u guests registered as character 23 to %u / model 52; P1 %s, P2 %s\n",
            roster_count,GUEST_ID+roster_count-1,guests[0].name,guests[1].name);
}

/* The VS / Team Battle / Tekken Ball grid (state 10): each cell's character
 * from team_table (x, y, ID * 4). The stock page has seven columns by three
 * rows; its Tag page puts the guests on rows of six (18 guests: six by
 * three), the user's choice once Wang and Unknown came. R2 / L2 switch
 * pages, like the cabinet selector's. The game keeps its seven-column cell
 * numbering (y * 7 + x = guest k); the page is drawn and navigated at
 * (k % 6, k / 6). */
enum { VS_TAG_COLS=6 };
static int grid_page;
/* Cells past the guests are drawn off screen: the grid draws its 22 cells
 * whatever the page, and an empty one shows a "?" tile. */
static void write_grid_page(void) {
    for(unsigned i=0;i<24;i++) {
        /* Cells past 21 are never drawn on the stock page either; cell 21
         * parks a confirmed player's cursor off screen (grid_switch). */
        int shown=grid_page?i<roster_count:i<STOCK_GRID_CELLS;
        unsigned id=grid_page?(i<roster_count?(GUEST_ID+i)*4:0x58):(i<STOCK_GRID_CELLS?team_order[i]:0x58);
        unsigned cols=grid_page?VS_TAG_COLS:GRID_COLS,col=i%cols,row=i/cols;
        /* Centred on the 36px pitch: seven columns from x=57, six 18 pixels
         * further right, as the runtime's 16:9 selector fingerprints expect
         * of those grids. */
        unsigned x0=grid_page?75:57;
        psx_mod_write_half(team_table+i*6,shown?x0+col*36:0x400);
        psx_mod_write_half(team_table+i*6+2,shown?67+row*63:0x400);
        psx_mod_write_half(team_table+i*6+4,id);
    }
}
/* The fighter in a cell of the state-10 grid (index y * 7 + x, the
 * cursor's column and row), whatever the page: 22 for none. Without the
 * TTT1 characters, the stock table (0x80022768, the same layout). */
unsigned tekken3_ttt1_grid_character(unsigned cell) {
    if(cell>=22)return 22;
    if(!tekken3_ttt1_roster_enabled() || !team_table)return psx_mod_read_byte(0x80022768+cell*6+4)/4;
    return psx_mod_read_half(team_table+cell*6+4)/4;
}
/* Row count and width of row y on the current grid page, as drawn. */
static unsigned grid_cols(void){return grid_page?VS_TAG_COLS:GRID_COLS;}
static unsigned grid_rows(void){return grid_page?(roster_count+VS_TAG_COLS-1)/VS_TAG_COLS:3;}
/* Switch grid pages. A player who has confirmed (block state 4: VS,
 * Tekken Ball) keeps the choice, but their frame would sit on whatever the
 * other page has in that cell: it goes to cell 21 (0,3), drawn off screen,
 * and comes back when its page returns. So does a player who has also set
 * VS's handicap (state 12). The player blocks are 172 bytes apart from
 * 0x800B8D70: +0 state, +8 x, +12 y. */
enum { GRID_BLOCK=0x800b8d70, GRID_BLOCK_STRIDE=172, GRID_CONFIRMED=4, GRID_HANDICAP_SET=12 };
static int grid_confirmed_page[2]={-1,-1};
static unsigned grid_confirmed_x[2],grid_confirmed_y[2];
static void grid_availability(void);
static void grid_switch(void) {
    grid_page=!grid_page;write_grid_page();grid_availability();
    for(unsigned p=0;p<2;p++) {
        uint32_t b=GRID_BLOCK+p*GRID_BLOCK_STRIDE;
        unsigned st=psx_mod_read_word(b);
        if(st!=GRID_CONFIRMED && st!=GRID_HANDICAP_SET)continue;
        if(grid_confirmed_page[p]<0) {
            grid_confirmed_page[p]=!grid_page;
            grid_confirmed_x[p]=psx_mod_read_word(b+8);grid_confirmed_y[p]=psx_mod_read_word(b+12);
        }
        if(grid_confirmed_page[p]==grid_page) {
            psx_mod_write_word(b+8,grid_confirmed_x[p]);psx_mod_write_word(b+12,grid_confirmed_y[p]);
            grid_confirmed_page[p]=-1;
        } else {psx_mod_write_word(b+8,0);psx_mod_write_word(b+12,3);}
    }
}
/* Each player block's availability mask (+36) has one bit per fighter,
 * bit (ID & 31), cleared when the fighter joins the team. Guests 32..38
 * share bits 0..6 with stock fighters 0..6, so choosing Paul used to lock
 * P.Jack out and the reverse. Each page shows only its own fighters: while
 * the grid is open, give the bits the meaning of the page on screen, from
 * the members chosen so far (+44 count, +56 choices, ID * 4 + costume). */
static void grid_availability(void) {
    uint32_t unlocked=psx_mod_read_word(0x80097ef0);
    for(unsigned p=0;p<2;p++) {
        uint32_t b=GRID_BLOCK+p*GRID_BLOCK_STRIDE;
        unsigned st=psx_mod_read_word(b),n=psx_mod_read_word(b+44);
        if(st<2 || st>3 || n>8)continue;
        uint32_t mask=unlocked;
        for(unsigned i=0;i<n;i++) {
            unsigned id=psx_mod_read_word(b+56+i*4)>>2;
            int guest=tekken3_guest_character(id)>=0;
            if(guest==grid_page)mask&=~(1u<<(id&31));
        }
        if(grid_page)
            for(unsigned k=0;k<roster_count;k++) {
                unsigned id=GUEST_ID+k;int chosen=0;
                for(unsigned i=0;i<n;i++)if(psx_mod_read_word(b+56+i*4)>>2==id)chosen=1;
                if(chosen)mask&=~(1u<<(id&31));else mask|=1u<<(id&31);
            }
        if(psx_mod_read_word(b+36)!=mask)psx_mod_write_word(b+36,mask);
    }
}
/* While a team's size is being picked (block state 1) the cursor holds
 * x = 0x8080. The grid still draws that cell's frame, y * 7 + x entries into
 * the table: past the stock table it lands off screen, past team_table in
 * zeroed memory, so a frame was drawn at (0, 0), in the border above the
 * picture, where nothing ever clears it (it stayed through the fights).
 * Park that cursor on cell 21, off screen on both pages.
 * Opening the grid does the same for one frame: the game sets the blocks
 * up (state 3) and draws the grid in the same frame, but x and y still hold
 * whatever that memory held before (text, from the modes menu) until the
 * navigation stores the cursor's cell the next frame. That frame's lookup
 * lands anywhere, here on (0, 0) (VS, 2026-09-27). Put such a cursor on
 * cell 0 as the state 10 starts, where the navigation puts it anyway. A
 * confirmed player parked on cell 21 (y = 3) keeps it. */
static void grid_park_prompt_cursor(void) {
    for(unsigned p=0;p<2;p++) {
        uint32_t b=GRID_BLOCK+p*GRID_BLOCK_STRIDE;
        unsigned st=psx_mod_read_word(b);
        if(st==GRID_CONFIRMED || st==GRID_HANDICAP_SET)continue;
        if(psx_mod_read_word(b+8)<GRID_COLS && psx_mod_read_word(b+12)<3)continue;
        if(st==1)psx_mod_write_word(b+8,21);
        else {psx_mod_write_word(b+8,0);psx_mod_write_word(b+12,0);}
    }
}
static unsigned grid_width(unsigned y) {
    unsigned cells=grid_page?roster_count:STOCK_GRID_CELLS,left=cells-y*grid_cols();
    return left>grid_cols()?grid_cols():left;
}
/* Availability bits. The game shifts by the ID modulo 32: guests 32..38
 * land on stock fighters 0..6, which are always available. */
enum { OPTIONS_STATE=5 };
static uint32_t guest_bits(void) {
    uint32_t bits=0;
    for(unsigned k=0;k<roster_count && GUEST_ID+k<32;k++)bits|=1u<<(GUEST_ID+k);
    return bits;
}
static void patch_tables(void) {
    patch(0x8003ec64,0x3c038009,0x3c030000|(body_profiles>>16));
    patch(0x8003ec68,0x24636f60,0x34630000|(body_profiles&65535));
    static const uint32_t descriptors[]={0x8004efd8,0x8004f008,0x8004f29c,0x8004f374,0x8004f478,0x8004f580,0x8004f5e4,0x8004f648,0x8004f70c};
    for(unsigned i=0;i<sizeof descriptors/sizeof *descriptors;i++)
        indirect(descriptors[i],descriptors[i]==0x8004f648?0x24427d40:0x24637d40);
    indirect(0x8003618c,0x244258c4);indirect(0x800361c4,0x246358c4);
    indirect(0x800361f8,0x244658c4);indirect(0x8003623c,0x246358c4);
    bound(0x800361b0,0x5c,desc_bound());bound(0x80036214,0x5c,desc_bound());
    bound(0x80036228,0x5c,desc_bound());
    /* The ID clamp behind actor+0x16 lets 23 through; __wrap_func_8002D1DC
     * hands it 23 for every guest. */
    bound(0x8002d1e8,21,24);
    indirect(0x800363a0,0x26315a9c);
    for(uint32_t a=0x8004efb0;a<0x8004f750;a+=4) {
        uint32_t w=psx_mod_read_word(a),op=w>>26;
        unsigned imm=w&65535;
        if(op==10 || op==11) {
            if(imm==0x5d)patch(a,w,(w&0xffff0000)|desc_bound());
            else if(imm==0x16)patch(a,w,(w&0xffff0000)|select_bound());
        }
    }
    /* OPTION MODE (state 5) is the one screen that counts the set bits of this
     * word: RECORDS sizes its CHARACTER USAGE list with a population count
     * and sorts that many {ID, games} pairs from a stack array of 22, copying
     * as many IDs back; with the guests' bits (23..31) the count passed 22
     * and the overrun ended the game at PC 0 (B01). The screen never offers a
     * guest, so the bits are taken off there and put back outside it. */
    {
        uint32_t word=psx_mod_read_word(0x80097ef0),bits=guest_bits();
        word=psx_mod_read_word(0x800ae204)==OPTIONS_STATE?word&~bits:word|bits;
        if(word!=psx_mod_read_word(0x80097ef0))psx_mod_write_word(0x80097ef0,word);
    }
    /* Every reference to the grid table is redirected to team_table, whose
     * characters follow the page. The grid itself stays the stock one:
     * seven columns, index y * 7 + x. */
    static const uint32_t positions[]={0x80052e24,0x800531b4,0x800532d0,0x800533a4,0x800534d0,0x800535d0,0x80053704,0x8005427c,0x80054414,0x8005449c,0x80054858,0x80054d10,0x80054e6c};
    for(unsigned i=0;i<sizeof positions/sizeof *positions;i++) {
        uint32_t w=psx_mod_read_word(positions[i]);
        if(w>>26==9 && (w&65535)==0x2768)indirect(positions[i],w);
    }
    /* Existing generated entry supplies a small host navigation helper.
     * RA distinguishes this call from real descriptor lookups. */
    patch(0x80053c08,0x3c02800b,0x0c014a4e);patch(0x80053c0c,0x2442df00,0);
    patch(0x8005387c,0x3c02800b,0x0c014a4e);patch(0x80053880,0x2442df00,0);
    patch(0x80052de4,0x27bdffe0,0x08014a50);patch(0x80052de8,0xafb10014,0);
    for(uint32_t a=0x80052de4;a<0x80054ee0;a+=4) {
        uint32_t w=psx_mod_read_word(a),op=w>>26;
        if((op==10 || op==11) && (w&65535)==0x58)patch(a,w,(w&0xffff0000)|team_bound()*4);
    }
}
/* Tag page tiles and palettes. The areas are saved when first covered and
 * given back when the selector closes, pixel by pixel where they still hold
 * what was uploaded (the fighters' loading may already have replaced some).
 * Two areas of each: the first sixteen guests fill the tiles at (384,16)
 * and the palette rows 480..495; the guests past them take the tiles at
 * (384,144), same texture page, and the rows 498 and 499 (x 0..255). Both
 * measured empty at the selector (2026-09-25); the loading screen keeps
 * 496/497 for its cards and 502/503 for its background.
 * Panda's and Tiger's tiles (alt_faces) follow the extra guests' at
 * (416,144); their palettes have 128 colours, one row each at (384,136),
 * then their grey copies (rows 138, 139). x 384..447 x y 136..201 measured
 * empty at the Team Battle grid and its first FIGHT screen (2026-10-01);
 * the loading cards start at x 448 (ICON_X). */
enum { TILE_W=16, TILE_H=58, AREA_W=TAG_BASE_COLS*TILE_W, AREA_H=2*TILE_H,
       EXTRA_Y=144, EXTRA_PALETTE_Y=498, EXTRA_MAX=GUEST_MAX-TAG_BASE,
       ALT_TILE_X=TILE_X+EXTRA_MAX*TILE_W, ALT_PALETTE_X=384, ALT_PALETTE_Y=136, ALT_COLOURS=128 };
typedef struct { unsigned x,y,w,h; } VramArea;
static const VramArea tile_areas[2]={{TILE_X,TILE_Y,AREA_W,AREA_H},{TILE_X,EXTRA_Y,(EXTRA_MAX+ALT_FACES)*TILE_W,TILE_H}};
static const VramArea palette_areas[3]={{0,TILE_PALETTE_Y,256,TAG_BASE},{0,EXTRA_PALETTE_Y,256,EXTRA_MAX},
                                        {ALT_PALETTE_X,ALT_PALETTE_Y,ALT_COLOURS,2*ALT_FACES}};
/* Guest k's tile (x, y in VRAM) and palette row. */
static unsigned tile_x(unsigned k){return TILE_X+(k<TAG_BASE?k%TAG_BASE_COLS:k-TAG_BASE)*TILE_W;}
static unsigned tile_y(unsigned k){return k<TAG_BASE?TILE_Y+(k/TAG_BASE_COLS)*TILE_H:EXTRA_Y;}
static unsigned tile_palette_y(unsigned k){return k<TAG_BASE?TILE_PALETTE_Y+k:EXTRA_PALETTE_Y+k-TAG_BASE;}
/* The icon word of guest k's tile: u | v << 8 | palette << 16, texture page TILE_PAGE. */
static uint32_t tile_uv(unsigned k) {
    return ((uint32_t)(tile_palette_y(k)<<6)<<16)|(tile_y(k)<<8)|((tile_x(k)-TILE_X)*2);
}
static uint16_t tile_pixels[2][AREA_H*AREA_W],tile_backup[2][AREA_H*AREA_W];
/* Palettes share the tiles' buffer size: one helper moves either. */
static uint16_t palette_pixels[3][AREA_H*AREA_W],palette_backup[3][AREA_H*AREA_W];
static int tiles_active;
/* Palette row lent to guest k's grey icon, 0 if none (grey_palette_row). */
static int grey_row[GUEST_MAX];
static unsigned grey_rows_used;
static void areas_in(const VramArea *a,uint16_t (*pixels)[AREA_H*AREA_W],unsigned n) {
    for(unsigned i=0;i<n;i++)gr_vram_transfer_in(a[i].x,a[i].y,a[i].w,a[i].h,pixels[i]);
}
static void areas_out(const VramArea *a,uint16_t (*pixels)[AREA_H*AREA_W],unsigned n) {
    for(unsigned i=0;i<n;i++)gr_vram_transfer_out(a[i].x,a[i].y,a[i].w,a[i].h,pixels[i]);
}
static int alt_faces_present(void){return alt_faces[0].ui || alt_faces[1].ui;}
/* Areas in use: the second only when there are guests past sixteen, or
 * Panda's and Tiger's tiles; their palettes are the third. */
static unsigned tile_area_count(void){return roster_count>TAG_BASE || alt_faces_present()?2:1;}
static unsigned palette_area_count(void){return alt_faces_present()?3:tile_area_count();}
/* Panda's or Tiger's icon word (a = 0 Panda, 1 Tiger), texture page TILE_PAGE. */
static uint32_t alt_tile_uv(unsigned a,int grey) {
    unsigned y=ALT_PALETTE_Y+(grey?ALT_FACES:0)+a;
    return ((uint32_t)((y<<6)|(ALT_PALETTE_X>>4))<<16)|(EXTRA_Y<<8)|((ALT_TILE_X+a*TILE_W-TILE_X)*2);
}
/* While the tiles are up, whatever the game writes under them (a Team
 * Battle's FIGHT screen loads the next fighters' textures into player 1's
 * band) goes into the backup: the tiles go back on top each frame, and the
 * game's content returns when they are released. */
/* Reading back costs a whole-VRAM glReadPixels on the OpenGL renderer: only
 * areas the runtime saw written since the tiles went back (gr_vram_watch) are
 * read, and only those are uploaded again. Returns the areas to upload. */
static int tile_watch[2]={-1,-1},palette_watch[3]={-1,-1,-1};
/* The selector copies a 2-pixel column (x 0..1, the whole VRAM height,
 * GP0 0x80) every frame, over colours 0 and 1 of the guest palette rows.
 * Those two columns stay out of the watch (they would flag every frame and
 * bring the readback back) and are simply put back each frame; the game
 * rewrites that column itself once the tiles are gone. */
enum { PALETTE_COPY_COLS=2 };
static void palette_copy_columns_in(unsigned n) {
    static uint16_t col[AREA_H*PALETTE_COPY_COLS];
    for(unsigned a=0;a<n;a++) {
        if(palette_areas[a].x)continue;              /* Panda's and Tiger's: away from the column */
        unsigned h=palette_areas[a].h;
        for(unsigned y=0;y<h;y++)for(unsigned x=0;x<PALETTE_COPY_COLS;x++)
            col[y*PALETTE_COPY_COLS+x]=palette_pixels[a][y*palette_areas[a].w+x];
        gr_vram_transfer_in(palette_areas[a].x,palette_areas[a].y,PALETTE_COPY_COLS,h,col);
    }
}
static void tiles_watch_clear(unsigned n,unsigned pn) {
    for(unsigned a=0;a<n;a++)gr_vram_watch_take(tile_watch[a]);
    for(unsigned a=0;a<pn;a++)gr_vram_watch_take(palette_watch[a]);
}
static unsigned tiles_merge(void) {
    unsigned n=tile_area_count(),pn=palette_area_count(),dirty=0;
    static uint16_t now[AREA_H*AREA_W];
    for(unsigned a=0;a<n;a++)
        if(gr_vram_watch_take(tile_watch[a])) {
            gr_vram_transfer_out(tile_areas[a].x,tile_areas[a].y,tile_areas[a].w,tile_areas[a].h,now);
            for(unsigned i=0;i<tile_areas[a].w*tile_areas[a].h;i++)if(now[i]!=tile_pixels[a][i])tile_backup[a][i]=now[i];
            dirty|=1u<<a;
        }
    for(unsigned a=0;a<pn;a++) {
        if(gr_vram_watch_take(palette_watch[a])) {
            gr_vram_transfer_out(palette_areas[a].x,palette_areas[a].y,palette_areas[a].w,palette_areas[a].h,now);
            for(unsigned i=0;i<palette_areas[a].w*palette_areas[a].h;i++)if(now[i]!=palette_pixels[a][i])palette_backup[a][i]=now[i];
            dirty|=4u<<a;
        }
    }
    return dirty;
}
/* A palette greyed as the stock grey ramp is (see grey_palette_row). */
static void grey_colours(const unsigned char *p,uint16_t *grey,unsigned n) {
    for(unsigned i=0;i<n;i++) {
        unsigned c=p[i*2]|(unsigned)p[i*2+1]<<8,r=c&31,g=(c>>5)&31,b=(c>>10)&31;
        unsigned l=(r*299+g*587+b*114)*77/100000,lb=l?l+1:0;
        grey[i]=(uint16_t)((c&0x8000)|l|l<<5|lb<<10);
        if(c && !grey[i])grey[i]=0x8000;          /* black, not transparent */
    }
}
static void tiles_upload(void) {
    unsigned n=tile_area_count(),pn=palette_area_count();
    for(unsigned a=0;a<2;a++)if(tile_watch[a]<0)
        tile_watch[a]=gr_vram_watch(tile_areas[a].x,tile_areas[a].y,tile_areas[a].w,tile_areas[a].h);
    for(unsigned a=0;a<3;a++)if(palette_watch[a]<0) {
        unsigned skip=palette_areas[a].x?0:PALETTE_COPY_COLS;
        palette_watch[a]=gr_vram_watch(palette_areas[a].x+skip,palette_areas[a].y,palette_areas[a].w-skip,palette_areas[a].h);
    }
    if(!tiles_active) {
        for(unsigned k=0;k<GUEST_MAX;k++)grey_row[k]=0;
        grey_rows_used=0;
        areas_out(tile_areas,tile_backup,n);areas_out(palette_areas,palette_backup,pn);
        memcpy(tile_pixels,tile_backup,sizeof tile_pixels);memcpy(palette_pixels,palette_backup,sizeof palette_pixels);
        for(unsigned k=0;k<roster_count;k++) {
            const unsigned char *p=roster[k].ui+roster[k].ui_offsets[2];
            unsigned a=k>=TAG_BASE,x=tile_x(k)-tile_areas[a].x,y0=tile_y(k)-tile_areas[a].y;
            memcpy(&palette_pixels[a][(tile_palette_y(k)-palette_areas[a].y)*256],p+20,512);
            for(unsigned y=0;y<TILE_H;y++)
                memcpy(&tile_pixels[a][(y0+y)*tile_areas[a].w+x],p+544+y*TILE_W*2,TILE_W*2);
        }
        for(unsigned a=0;a<ALT_FACES;a++) {
            if(!alt_faces[a].ui)continue;
            const unsigned char *p=alt_faces[a].ui+alt_faces[a].ui_offsets[2];
            unsigned x=ALT_TILE_X+a*TILE_W-tile_areas[1].x,w=tile_areas[1].w;
            memcpy(&palette_pixels[2][a*ALT_COLOURS],p+20,ALT_COLOURS*2);
            grey_colours(p+20,&palette_pixels[2][(ALT_FACES+a)*ALT_COLOURS],ALT_COLOURS);
            for(unsigned y=0;y<TILE_H;y++)
                memcpy(&tile_pixels[1][y*w+x],p+544+y*TILE_W*2,TILE_W*2);
        }
        tiles_active=1;
    } else {
        unsigned dirty=tiles_merge();
        for(unsigned a=0;a<n;a++)
            if(dirty&1u<<a)gr_vram_transfer_in(tile_areas[a].x,tile_areas[a].y,tile_areas[a].w,tile_areas[a].h,tile_pixels[a]);
        for(unsigned a=0;a<pn;a++)
            if(dirty&4u<<a)gr_vram_transfer_in(palette_areas[a].x,palette_areas[a].y,palette_areas[a].w,palette_areas[a].h,palette_pixels[a]);
        palette_copy_columns_in(pn);
        tiles_watch_clear(n,pn);
        return;
    }
    areas_in(tile_areas,tile_pixels,n);areas_in(palette_areas,palette_pixels,pn);
    tiles_watch_clear(n,pn);
}
/* A defeated team member's icon (Team Battle's FIGHT screen and results):
 * the icon routine's flag 0x20 swaps its palette for the stock grey ramp
 * (256, 501), which follows the order of the stock palettes, not a guest's:
 * a guest came out black. Its icon keeps its own palette, greyed as the
 * ramp is (about 0.77 of the luminance, blue one step up), in the palette
 * row of a guest in neither team (the tiles' rows are all taken outside the
 * Team screens), and the flag goes. None free: the colours stay. */
static int team_member_guest(unsigned k) {
    for(unsigned p=0;p<2;p++)for(unsigned i=0;i<8;i++)
        if((psx_mod_read_byte(0x800afae1+13*p+i)>>2)==GUEST_ID+k)return 1;
    return 0;
}
static void palette_row_set(unsigned y,const uint16_t *colours) {
    for(unsigned a=0;a<tile_area_count();a++)
        if(y>=palette_areas[a].y && y<palette_areas[a].y+palette_areas[a].h)
            memcpy(&palette_pixels[a][(y-palette_areas[a].y)*256],colours,512);
    gr_vram_transfer_in(0,y,256,1,colours);
}
static int grey_palette_row(unsigned k) {
    if(grey_row[k])return grey_row[k];
    for(unsigned f=0;f<roster_count;f++) {
        unsigned y=tile_palette_y(f);
        int taken=team_member_guest(f);
        for(unsigned g=0;g<roster_count && !taken;g++)taken=grey_row[g]==(int)y;
        if(taken)continue;
        uint16_t grey[256];
        grey_colours(roster[k].ui+roster[k].ui_offsets[2]+20,grey,256);
        palette_row_set(y,grey);
        grey_row[k]=(int)y;grey_rows_used=1;
        return (int)y;
    }
    return 0;
}
/* Back to each guest's own colours in the rows lent (the grid shows them). */
static void grey_rows_release(void) {
    if(!grey_rows_used)return;
    for(unsigned k=0;k<roster_count;k++)grey_row[k]=0;
    if(tiles_active)for(unsigned f=0;f<roster_count;f++)
        palette_row_set(tile_palette_y(f),(const uint16_t*)(roster[f].ui+roster[f].ui_offsets[2]+20));
    grey_rows_used=0;
}
/* Time Attack's end: TIME ATTACK CLEAR and YOUR TIME (state 13), then the
 * name entry (16). Their icons of the player and of the fighters beaten are
 * the stock sheet's, by ID: a guest's comes from its Tag page tile, put up
 * at the first such icon (as on Team Battle's loading screen) and kept
 * until the end. */
static int time_attack_end(unsigned state) {
    return (state==13 || state==16) && psx_mod_read_word(0x800afa88)==3;
}
/* Team Battle's FIGHT screen (FIGHT 1, 2...: the teams lined up): a few
 * frames of state 11, then state 8 before the fight's own phases (phase 3
 * there, 6 and on once the fighters show). */
static int team_screen(unsigned state) {
    return psx_mod_read_word(0x800afa88)==2 &&
        (state==11 || (state==8 && psx_mod_read_half(0x800ae224)<6));
}
/* The tiles' areas are the runtime's while they are up: player 2's strong-hit
 * pack (x 496, tekken3_ttt1_combat.c) under Panda's and Tiger's palettes
 * waits for tiles_release, which hands it back. */
int tekken3_ttt1_tiles_up(void){return tiles_active;}
static void tiles_release(void) {
    if(!tiles_active)return;
    unsigned n=tile_area_count();
    tiles_merge();
    areas_in(tile_areas,tile_backup,n);areas_in(palette_areas,palette_backup,palette_area_count());
    tiles_active=0;
}
/* The attract CHARACTERS ranking lists a guest under a stock fighter's slot
 * (tekken3_ttt1_records.c) and draws that slot's icon: 8bpp, 32 x 58, at the
 * page, u, v and palette of the game's icon table (0x8002152C + 8 * slot;
 * page (896, 0), palette (256, 480 + ID) for the stock fighters). While the
 * ranking is up, the guest's Tag page tile and palette take that icon's
 * place in VRAM; the stock icon comes back after. */
enum { RANKING_FACE_SLOTS=22 };
static uint16_t face_backup[RANKING_FACE_SLOTS][TILE_H*TILE_W],face_palette_backup[RANKING_FACE_SLOTS][256];
static int face_lent[RANKING_FACE_SLOTS];
static int icon_place(unsigned slot,unsigned *x,unsigned *y,unsigned *cx,unsigned *cy) {
    uint32_t w=psx_mod_read_word(0x8002152c+slot*8),page=psx_mod_read_word(0x8002152c+slot*8+4)&0xffff;
    if(((page>>7)&3)!=1)return 0;
    *x=(page&15)*64+(w&255)/2;*y=((page>>4)&1)*256+((w>>8)&255);
    *cx=((w>>16)&63)*16;*cy=(w>>22)&511;
    return *x+TILE_W<=1024 && *y+TILE_H<=512 && *cx+256<=1024;
}
/* A slot can lend its icon only if no other stock icon shares any of its
 * rows: True Ogre's (20, v 0) and Paul's (0, v 24) overlap on the sheet,
 * and the lower half of a guest put there showed Paul. */
int tekken3_ranking_face_ok(unsigned slot) {
    unsigned x,y,cx,cy;
    if(slot>=RANKING_FACE_SLOTS || !icon_place(slot,&x,&y,&cx,&cy))return 0;
    for(unsigned o=0;o<RANKING_FACE_SLOTS;o++) {
        unsigned ox,oy,ocx,ocy;
        if(o==slot || !icon_place(o,&ox,&oy,&ocx,&ocy))continue;
        if(ox<x+TILE_W && x<ox+TILE_W && oy<y+TILE_H && y<oy+TILE_H)return 0;
        if(ocx==cx && ocy==cy)return 0;
    }
    return 1;
}
/* Face g's tile and palette over stock icon `slot`. */
static void face_lend(unsigned slot,const Tekken3Guest *g) {
    unsigned x,y,cx,cy;
    if(!g || !g->ui || slot>=RANKING_FACE_SLOTS || !icon_place(slot,&x,&y,&cx,&cy))return;
    if(!face_lent[slot]) {
        gr_vram_transfer_out(x,y,TILE_W,TILE_H,face_backup[slot]);
        gr_vram_transfer_out(cx,cy,256,1,face_palette_backup[slot]);
        face_lent[slot]=1;
    }
    const unsigned char *p=g->ui+g->ui_offsets[2];
    gr_vram_transfer_in(x,y,TILE_W,TILE_H,(const uint16_t*)(p+544));
    gr_vram_transfer_in(cx,cy,256,1,(const uint16_t*)(p+20));
}
void tekken3_ranking_face(unsigned slot,unsigned id) {
    int k=tekken3_guest_character(id);
    if(k>=0)face_lend(slot,&roster[k]);
}
/* Set while Time Attack's end screens lend icons (time_attack_beaten). */
static int faces_held;
void tekken3_ranking_faces_restore(void) {
    if(faces_held)return;
    for(unsigned slot=0;slot<RANKING_FACE_SLOTS;slot++) {
        unsigned x,y,cx,cy;
        if(!face_lent[slot])continue;
        face_lent[slot]=0;
        if(!icon_place(slot,&x,&y,&cx,&cy))continue;
        gr_vram_transfer_in(x,y,TILE_W,TILE_H,face_backup[slot]);
        gr_vram_transfer_in(cx,cy,256,1,face_palette_backup[slot]);
    }
}
/* The stock icons' palettes (a 256 x 1 row each, (256, 480 + slot)) are
 * crossed by player 1's texture band (x 384..447): a guest's costume writes
 * over their entries 184..191 in the fight. The selector reloads them when a
 * mode opens it, not when Practice's PLAYER SELECT comes back to it from the
 * fight, and the stock icons showed spots. They are saved on a selector that
 * the game has just set up, and put back when it reopens after a fight. */
static uint16_t icon_palettes[RANKING_FACE_SLOTS][256];
static int icon_palettes_saved;
static void icon_palettes_move(int save) {
    for(unsigned slot=0;slot<21;slot++) {
        unsigned x,y,cx,cy;
        if(!icon_place(slot,&x,&y,&cx,&cy))continue;
        if(save)gr_vram_transfer_out(cx,cy,256,1,icon_palettes[slot]);
        else gr_vram_transfer_in(cx,cy,256,1,icon_palettes[slot]);
    }
    if(save)icon_palettes_saved=1;
}
/* A player's identity follows the guest character they point at: the cell
 * under the cursor, then the confirmed choice, then the actor. */
static void follow(unsigned player,unsigned id) {
    int k=tekken3_guest_character(id);
    if(k<0 || (unsigned)k==guests[player].catalog_index)return;
    set_identity(player,(unsigned)k);
    fprintf(stderr,"TTT1 characters: P%u guest is now %s (%d/%u)\n",player+1,guests[player].name,k+1,roster_count);
}
/* The attract-mode Embu casts guests without a selector. */
void tekken3_guest_follow(unsigned player,unsigned id,unsigned costume) {
    if(player>1)return;
    follow(player,id);follow_costume(player,costume);
}
static int selector_open(void) {
    return psx_mod_read_word(0x800ae204)==9 && psx_mod_read_word(0x8010ff4c)==0x27bdffd0 &&
           psx_mod_read_half(0x800ae224)<=1;
}
/* The cabinet selector's state per player (player 2's block follows player
 * 1's by 0x7C): the cursor's cell, and the character under it (22 while the
 * player has not joined). The byte at 0x80098106 + player is no use here: it
 * reads 21 for every character without an icon of its own. */
static unsigned cursor_cell(int player){return psx_mod_read_word(0x80118650+(unsigned)player*0x7c);}
static unsigned cursor_character(int player){return psx_mod_read_word(0x80118668+(unsigned)player*0x7c);}

/* Two pages share the selector: the stock grid (page 0), saved as the game
 * built it, and the Tag page (1), the guests. The grid is one for both
 * players, so the page is too. */
enum { GRID=0x801296c8, GRID_COUNT=0x80118648, CELL_IDS=0x800b9018, GRID_BYTES=22*12 };
static int page,stock_saved;
/* The page the selector last closed on: it reopens there after a fight. The
 * game keeps each cursor's cell index, so the cursor comes back to the same
 * guest. */
static int closed_on_tag,reopened;
static unsigned char stock_grid[GRID_BYTES],stock_ids[22];
static void write_tag_page(void) {
    for(unsigned k=0;k<roster_count;k++) {
        uint32_t n=GRID+k*12;
        unsigned col,row;tag_place(k,&col,&row);
        /* A row may be short; left/right wrap inside it. */
        unsigned width=tag_width(row);
        int above=row?tag_guest_at(col,row-1):-1,below=tag_guest_at(col,row+1);
        psx_mod_write_byte(n,(unsigned char)k);
        psx_mod_write_byte(n+1,above>=0?(unsigned char)above:GRID_NONE);
        psx_mod_write_byte(n+2,below>=0?(unsigned char)below:GRID_NONE);
        psx_mod_write_byte(n+3,(unsigned char)tag_guest_at((col+width-1)%width,row));
        psx_mod_write_byte(n+4,(unsigned char)tag_guest_at((col+1)%width,row));
        psx_mod_write_byte(n+5,1);
        psx_mod_write_half(n+6,GUEST_ID+k);
        psx_mod_write_half(n+8,TAG_X0+GRID_PITCH_X*col);
        psx_mod_write_half(n+10,row*GRID_PITCH_Y);
        psx_mod_write_byte(CELL_IDS+k,(unsigned char)(GUEST_ID+k));
    }
    /* The selector draws its 22 entries whatever the count: the rest are
     * made like the stock grid's locked Gon cell (unavailable, at 0,0). */
    for(unsigned k=roster_count;k<22;k++) {
        uint32_t n=GRID+k*12;
        psx_mod_write_byte(n,(unsigned char)k);
        for(unsigned i=1;i<5;i++)psx_mod_write_byte(n+i,GRID_NONE);
        psx_mod_write_byte(n+5,0);
        psx_mod_write_half(n+8,0);psx_mod_write_half(n+10,0);
    }
    psx_mod_write_word(GRID_COUNT,roster_count);
    psx_mod_write_word(0x80118644,psx_mod_read_word(0x80118644)|guest_bits());
}
static void write_stock_page(void) {
    copy_host(GRID,stock_grid,GRID_BYTES);copy_host(CELL_IDS,stock_ids,sizeof stock_ids);
    psx_mod_write_word(GRID_COUNT,STOCK_CELLS);
}

/* R2 / L2, either player: switch between the stock grid and the Tag page.
 * L1 stays with the outfit gallery at the selector; in a fight it switches
 * Unknown's moveset (tekken3_guest_switch_request). */
enum { PAD_L2=0x0100, PAD_R2=0x0200, PAD_L1=0x0400, ABSENT=22 };
/* L1 pressed in a fight by a player whose guest switches on it: frames left
 * for the switch to happen, which it does once the fighter is in stance
 * (tools: tekken3_ttt1_combat_tick). The game never sees that L1. */
enum { SWITCH_WINDOW=8 };
static unsigned switch_request[2];
int tekken3_guest_switch_request(unsigned player) {
    if(player>1 || !switch_request[player])return 0;
    switch_request[player]--;
    return 1;
}
void tekken3_guest_switch_done(unsigned player){if(player<2)switch_request[player]=0;}
/* Unknown played by the CPU. TTT1's CPU switches her on the Tag button when
 * it is under pressure: measured at the Arcade final (TIPS.md section 28,
 * tools/ttt1_unknown_cpu_switches.lua), never against an idle player, even
 * with her life taken away, and about once every 1,300 frames under attack,
 * hit or guarding, never twice within ~300 frames. Here: pressure = she
 * lost life or guarded (tekken3_guest_note_guard) in the last PRESSURE
 * frames; past MIN_GAP frames since her last switch, each frame under
 * pressure switches with a chance of 1 / HAZARD (mean gap MIN_GAP + HAZARD).
 * The request then waits up to CPU_WINDOW frames for her stance.
 * TEKKEN3_UNKNOWN_CPU_SWITCH="min_gap,hazard,pressure" overrides. */
enum { CPU_WINDOW=120 };
static unsigned cpu_min_gap=300,cpu_hazard=1000,cpu_pressure=300;
static unsigned fight_frame,pressure_until[2],last_switch[2],last_life[2];
static int cpu_player(unsigned p){return psx_mod_read_half(0x800ae1f8+p*2)==0;}
void tekken3_guest_note_guard(unsigned defender) {
    if(defender<2)pressure_until[defender]=fight_frame+cpu_pressure;
}
static void cpu_switch_tick(void) {
    static int configured;
    if(!configured) {
        configured=1;
        const char *e=getenv("TEKKEN3_UNKNOWN_CPU_SWITCH");
        unsigned a,b,c;
        if(e && sscanf(e,"%u,%u,%u",&a,&b,&c)==3 && b){cpu_min_gap=a;cpu_hazard=b;cpu_pressure=c;}
    }
    fight_frame++;
    int fighting=psx_mod_read_word(0x800ae204)==8 && psx_mod_read_half(0x800ae224)>=6;
    for(unsigned p=0;p<2;p++) {
        uint32_t actor=0x800a9228+p*0x188c;
        unsigned life=psx_mod_read_half(actor+0x3f6);
        if(!fighting || !tekken3_guest_switches_on_button(p) || !cpu_player(p)) {
            last_life[p]=life;last_switch[p]=fight_frame;pressure_until[p]=0;continue;
        }
        if(life<last_life[p])pressure_until[p]=fight_frame+cpu_pressure;
        last_life[p]=life;
        if(switch_request[p] || fight_frame>=pressure_until[p] || fight_frame-last_switch[p]<cpu_min_gap)continue;
        if(draw(cpu_hazard))continue;
        switch_request[p]=CPU_WINDOW;last_switch[p]=fight_frame;
        fprintf(stderr,"TTT1 characters: P%u %s (CPU) switches under pressure\n",p+1,guest(p)->name);
    }
}
/* A player who has already confirmed keeps their choice (the character is
 * stored apart from the cell), but their frame would sit on whatever the
 * other page has in that cell. Their cursor goes to HIDDEN_CELL, drawn off
 * screen, and comes back to its cell when their page returns. */
enum { PLAYER_STATE=0x8011864c, CHOOSING=1, CHOOSING_CPU=3, HIDDEN_CELL=21, OFF_SCREEN=0x200,
       SHOWN_CHARACTER=0x80118660, NO_CHARACTER=0xff };
static int confirmed_page[2]={-1,-1};
static unsigned confirmed_cell[2];
/* Practice: once player 1 has chosen, player 1's pad picks the CPU in player
 * 2's block, whose state is then 3, not 1 (measured). */
static int confirmed(int p) {
    unsigned state=psx_mod_read_word(PLAYER_STATE+(unsigned)p*0x7c);
    return state!=CHOOSING && state!=CHOOSING_CPU;
}
static void hide_hidden_cell(void) {
    uint32_t n=GRID+HIDDEN_CELL*12;
    psx_mod_write_byte(n+5,0);psx_mod_write_half(n+8,OFF_SCREEN);psx_mod_write_half(n+10,OFF_SCREEN);
}
static void switch_page(void) {
    page=!page;
    if(page)write_tag_page();else write_stock_page();
    hide_hidden_cell();
    for(int p=0;p<2;p++) {
        if(cursor_character(p)>=select_bound() || cursor_character(p)==ABSENT || !confirmed(p))continue;
        uint32_t cell=0x80118650+(unsigned)p*0x7c;
        if(confirmed_page[p]<0){confirmed_page[p]=!page;confirmed_cell[p]=psx_mod_read_word(cell);}
        if(confirmed_page[p]==page){psx_mod_write_word(cell,confirmed_cell[p]);confirmed_page[p]=-1;}
        else psx_mod_write_word(cell,HIDDEN_CELL);
    }
    for(int p=0;p<2;p++) {
        if(confirmed(p))continue;
        /* Joined players only: 22 is "not joined", and right after the
         * overlay loads the block still holds unrelated values. */
        if(cursor_character(p)>=select_bound() || cursor_character(p)==ABSENT)continue;
        /* A new page starts on its first cell (Xiaoyu, Kazuya): the cells
         * of the two pages do not line up. */
        psx_mod_write_word(0x80118650+(unsigned)p*0x7c,0);
        /* The selector reloads the big portrait, the name and the tile when
         * the character under the cursor (+0x1C) differs from the one it
         * shows (+0x14), which it then copies. Make them differ, with no
         * cursor move and so no cursor sound. */
        psx_mod_write_word(SHOWN_CHARACTER+(unsigned)p*0x7c,NO_CHARACTER);
    }
    fprintf(stderr,"TTT1 characters: %s page\n",page?"Tag":"Tekken 3");
}
uint16_t tekken3_guest_selector_input(int player,uint16_t buttons) {
    static uint16_t previous[2]={0xffff,0xffff};
    if(player<0 || player>1 || !tekken3_ttt1_roster_enabled())return buttons;
    uint16_t edges=previous[player]&(uint16_t)~buttons;previous[player]=buttons;
    if(psx_mod_read_word(0x800ae204)==8 && tekken3_guest_switches_on_button((unsigned)player)) {
        if((edges&PAD_L1) && psx_mod_read_half(0x800ae224)>=6)switch_request[player]=SWITCH_WINDOW;
        return buttons|PAD_L1;
    }
    if(psx_mod_read_word(0x800ae204)==10) {
        if(edges&(PAD_R2|PAD_L2)) {
            grid_switch();
            fprintf(stderr,"TTT1 characters: %s grid page\n",grid_page?"Tag":"Tekken 3");
        }
        return buttons|PAD_L2|PAD_R2;
    }
    if(!selector_open())return buttons;
    if((edges&(PAD_R2|PAD_L2)) && stock_saved)switch_page();
    return buttons|PAD_L2|PAD_R2;
}
/* The page on screen, for the CHARACTER SELECT card
 * (tekken3_native_moves.c): 0 the Tekken 3 page, 1 the Tag page, -1 where
 * R2 / L2 switch nothing. */
int tekken3_ttt1_selector_page(void) {
    if(!tekken3_ttt1_roster_enabled())return -1;
    if(psx_mod_read_word(0x800ae204)==10)return grid_page;
    return selector_open() && stock_saved?page:-1;
}
/* Start alone picks a third costume: the overlay's handler (0x8010DAB8)
 * tests bit(ID & 31) of 0x80097EF4, the stock unlock mask, and while that
 * bit is set takes Start or triangle (0x810, at 0x8010DAF4) for costume 3.
 * A guest takes it on Start only, like in TTT1: while a player's cursor is
 * on a guest, the handler looks at Start alone, the bit is lent to a guest
 * with a third costume and hidden from one without (IDs of 32 and above
 * share a stock fighter's bit: Devil, 33, would take Paul's unlocked
 * costume, gold name plate included). Only the bits changed are restored. */
static void lend_third_costume_bits(int cabinet) {
    static uint32_t lent,hidden;
    uint32_t want=0,hide=0;int guest=0;
    for(unsigned p=0;cabinet && p<2;p++) {
        unsigned id=cursor_character((int)p);
        int k=tekken3_guest_character(id);
        if(k<0)continue;
        guest=1;
        if(roster[k].third_costume)want|=1u<<(id&31);else hide|=1u<<(id&31);
    }
    hide&=~want;
    if(cabinet && psx_mod_read_word(0x8010dadc)==0x8e04001cu) {
        if(guest)patch(0x8010daf4,0x24050810,0x24050800);
        else patch(0x8010daf4,0x24050800,0x24050810);
    }
    if(!want && !lent && !hide && !hidden)return;
    uint32_t flags=psx_mod_read_word(0x80097ef4),old=flags;
    uint32_t add=want&~flags,drop=lent&~want;
    uint32_t mask=hide&flags&~lent,back=hidden&~hide;
    flags=(flags|add|back)&~drop&~mask;
    lent=(lent|add)&~drop;hidden=(hidden|mask)&~back;
    if(flags!=old)psx_mod_write_word(0x80097ef4,flags);
}
/* Strong-hit effect length. At round start (0x8007641C) each player's
 * effect entry (0x800A35C8 + 16 * player) points at a six-byte header in a
 * per-character table, 0x80027950 + ID * 6, whose first halfword is the
 * number of images of its pack (Jin 22, Xiaoyu 30), followed by a colour
 * (R, G, B bytes: Jin's blue, Paul's orange). The table stops after the
 * stock fighters: a guest's header fell in the data that follows, 0 for
 * Jun, so its animation died after one frame, and some other count
 * elsewhere. A guest gets the stock header with its own pack's length (30,
 * 22 for the Mishima, as in TTT1; issue #14: every guest had Jin's 22, and
 * the end of the TTT1 effects was cut) and the colour nearest its palette;
 * Jin's without a pack. */
enum { EFFECT_HEADERS=0x80027950, EFFECT_HEADER=6, EFFECT_STOCK=22, EFFECT_ROWS=0x800a35c8, JIN_ID=9 };
extern unsigned tekken3_ttt1_hit_effect_frames(unsigned player,unsigned rgb[3]);
static uint32_t effect_header(unsigned row) {
    uint32_t best=EFFECT_HEADERS+JIN_ID*EFFECT_HEADER;
    unsigned rgb[3],frames=row<2?tekken3_ttt1_hit_effect_frames(row,rgb):0,far=~0u;
    for(unsigned id=0;frames && id<EFFECT_STOCK;id++) {
        uint32_t h=EFFECT_HEADERS+id*EFFECT_HEADER;
        if(psx_mod_read_half(h)!=frames)continue;
        unsigned d=0;
        for(unsigned k=0;k<3;k++){int e=(int)psx_mod_read_byte(h+2+k)-(int)rgb[k];d+=(unsigned)(e*e);}
        if(d<far){far=d;best=h;}
    }
    return best;
}
static void effect_headers(void) {
    if(psx_mod_read_half(EFFECT_HEADERS+JIN_ID*EFFECT_HEADER)!=22)return;
    for(unsigned row=0;row<3;row++) {
        uint32_t at=EFFECT_ROWS+row*16,ptr=psx_mod_read_word(at);
        if(ptr<EFFECT_HEADERS+GUEST_ID*EFFECT_HEADER || (ptr-EFFECT_HEADERS)%EFFECT_HEADER)continue;
        if(tekken3_guest_character((ptr-EFFECT_HEADERS)/EFFECT_HEADER)>=0)psx_mod_write_word(at,effect_header(row));
    }
}
/* The Embu (state 6) sets the headers itself, Jin's for player 1 and
 * Yoshimitsu's for player 2 (0x8007644C), and loads their packs. The
 * header's colour is the impact's light (0x80039F0C: a GTE point light at
 * the hit for 48 frames), which lit Kunimitsu standing in for Yoshimitsu in
 * his green (issue #29). A guest playing that native's part takes the
 * header and pack it has in a fight. */
extern int tekken3_ttt1_embu_native(unsigned player);
extern void tekken3_ttt1_embu_hit_effect(unsigned player);
static void embu_effect_headers(unsigned state) {
    static const int owner[2]={JIN_ID,4};   /* Yoshimitsu */
    for(unsigned row=0;state==6 && row<2;row++) {
        if(tekken3_ttt1_embu_native(row)!=owner[row])continue;
        uint32_t at=EFFECT_ROWS+row*16,header=effect_header(row);
        if(psx_mod_read_word(at)!=header)psx_mod_write_word(at,header);
        tekken3_ttt1_embu_hit_effect(row);
    }
}
/* TEAM BATTLE RESULTS history (overlay loaded in state 12): each fight's
 * two fighters are read from the team lists and clamped to 88, "?"
 * (0x800EE368 / 0x800EE374); the icon routine (0x800F0CFC) then takes IDs
 * of 22 and above down its several-strip "?" path (0x800F0E50) and reads a
 * 22-entry icon table at 0x800B9158 (lui 0x800C + addiu -0x6EA8; 8 bytes:
 * u | v << 8 | palette << 16, then the texture page),
 * each icon a 32 x 58 tile drawn at half size. Let the guests through: no
 * clamp, only 22 itself on the "?" path, and a copy of the table extended
 * with each guest's Tag page tile, which state 12 keeps in VRAM.
 * The routine gets ID * 4 + costume (s4) and looks up ID: the copy has an
 * entry per costume instead (sll v1,s4,3), so that Panda and Tiger get
 * their tiles, and a second table follows with each entry's defeated
 * (flag 0x20) icon, read in place of the stock grey ramp's palette
 * (0x7D50, kept for all but Panda and Tiger, whose palettes have grey
 * copies of their own). */
static uint32_t results_icons;
static int results_overlay_stock(void) {
    return psx_mod_read_word(0x800ee368)==0x24060058 && psx_mod_read_word(0x800ee374)==0x24120058 &&
        psx_mod_read_word(0x800f0e50)==0x28820016 && psx_mod_read_word(0x800f0e1c)==0x3c02800c &&
        psx_mod_read_word(0x800f0e20)==0x24429158;
}
static int results_overlay_patched(void) {
    return results_icons && psx_mod_read_word(0x800f0e1c)==(0x3c020000|(results_icons>>16));
}
/* The same overlay draws Time Attack's end (state 13 on): TIME ATTACK
 * CLEAR's beaten fighters come from the opponent list (0x800AFB18, 4 bytes
 * per stage: ID, costume, stage), where cpu-guests puts guests, and are
 * drawn from the stock icon sheet by ID. That overlay runs compiled: reads
 * of the mod's memory (0x9F...) come back all ones there, and the Tag page
 * tiles' VRAM holds part of the screen's own picture. So each guest on the
 * list borrows a stock fighter the list does not show, as in the attract
 * rankings: the guest's tile and palette lie over that fighter's icon, and
 * the list names that fighter until the end screens are gone. The run is
 * over, the list only feeds these screens by then. */
enum { TA_LIST=0x800afb18, TA_STAGES=10 };
static int ta_beaten_active,sv_beaten_active;
static uint8_t ta_beaten_list[TA_STAGES],ta_beaten_costume[TA_STAGES],ta_beaten_slot[TA_STAGES];
/* The face a list entry shows on its own: a guest's, or Panda's or Tiger's
 * (the CPU fights in a costume too), else none. */
static const Tekken3Guest *ta_beaten_face(unsigned i) {
    int k=tekken3_guest_character(ta_beaten_list[i]);
    return k>=0?&roster[k]:alt_face(ta_beaten_list[i],ta_beaten_costume[i]);
}
static void time_attack_beaten(unsigned state) {
    int end=time_attack_end(state) && results_overlay_stock();
    if(!end) {
        if(!ta_beaten_active)return;
        for(unsigned i=0;i<TA_STAGES;i++)if(ta_beaten_slot[i])psx_mod_write_byte(TA_LIST+i*4,ta_beaten_list[i]);
        ta_beaten_active=0;faces_held=sv_beaten_active;if(!faces_held)tekken3_ranking_faces_restore();
        return;
    }
    if(!ta_beaten_active) {
        int used[GUEST_ID]={0},any=0;
        for(unsigned i=0;i<TA_STAGES;i++) {
            unsigned id=psx_mod_read_byte(TA_LIST+i*4);
            if(id<GUEST_ID)used[id]=1;
            ta_beaten_slot[i]=0;ta_beaten_list[i]=psx_mod_read_byte(TA_LIST+i*4);
            ta_beaten_costume[i]=psx_mod_read_byte(TA_LIST+i*4+1);
            any|=ta_beaten_face(i)!=NULL;
        }
        unsigned player=psx_mod_read_byte(0x800afb14);
        if(player<GUEST_ID)used[player]=1;
        if(!any)return;
        /* From 19 down: the icon routine draws 20 (True Ogre) and 21
         * (Crow / Hawk) its own way. */
        int next=19;
        for(unsigned i=0;i<TA_STAGES;i++) {
            if(!ta_beaten_face(i))continue;
            while(next>=0 && (used[next] || !tekken3_ranking_face_ok((unsigned)next)))next--;
            if(next<0)break;
            used[next]=1;ta_beaten_slot[i]=(uint8_t)(next+1);
            psx_mod_write_byte(TA_LIST+i*4,(uint8_t)next);
        }
        ta_beaten_active=1;faces_held=1;
    }
    /* Every frame, as the rankings do: the screen may reload its sheet. */
    for(unsigned i=0;i<TA_STAGES;i++)
        if(ta_beaten_slot[i])face_lend(ta_beaten_slot[i]-1u,ta_beaten_face(i));
}
/* SURVIVAL RESULTS (state 14 in Survival, mode 4) shows each fighter beaten
 * with how many times, from the run's counters (0x800AFA88 + 0x60 + 2 * ID,
 * a halfword each), and totals them: it walks IDs 0..21 only, so a guest
 * beaten (its counter past the table) was neither shown nor counted. Each
 * such guest borrows a stock fighter not beaten in the run (counter 0): the
 * guest's count goes in that fighter's counter and the guest's tile over
 * its icon, as on TIME ATTACK CLEAR, until the screen is gone. */
enum { SURVIVAL_MODE=4, SURVIVAL_RESULTS_STATE=14, SURVIVAL_COUNTS=0x800afa88+0x60 };
static uint8_t sv_lent_to[GUEST_ID];                 /* stock slot -> guest ID + 1 */
static uint16_t sv_guest_wins[GUEST_MAX];            /* fights won against each guest, this run */
static void survival_guests_beaten(unsigned state) {
    int on=state==SURVIVAL_RESULTS_STATE && psx_mod_read_word(0x800afa88)==SURVIVAL_MODE;
    if(!on) {
        if(!sv_beaten_active)return;
        for(unsigned s=0;s<GUEST_ID;s++)if(sv_lent_to[s]) {
            if(psx_mod_read_word(0x800afa88)==SURVIVAL_MODE)psx_mod_write_half(SURVIVAL_COUNTS+s*2,0);
            sv_lent_to[s]=0;
        }
        sv_beaten_active=0;faces_held=ta_beaten_active;if(!faces_held)tekken3_ranking_faces_restore();
        return;
    }
    if(!sv_beaten_active) {
        memset(sv_lent_to,0,sizeof sv_lent_to);
        int next=19;
        for(unsigned id=GUEST_ID;id<GUEST_ID+roster_count;id++) {
            unsigned n=sv_guest_wins[id-GUEST_ID];
            if(!n)continue;
            while(next>=0 && (psx_mod_read_half(SURVIVAL_COUNTS+next*2) || !tekken3_ranking_face_ok((unsigned)next)))next--;
            if(next<0)break;
            psx_mod_write_half(SURVIVAL_COUNTS+next*2,(uint16_t)n);
            sv_lent_to[next]=(uint8_t)(id+1);next--;
        }
        sv_beaten_active=1;faces_held=1;
    }
    for(unsigned s=0;s<GUEST_ID;s++)if(sv_lent_to[s])tekken3_ranking_face(s,sv_lent_to[s]-1u);
}
static void results_history_patch(void) {
    if(psx_mod_read_word(0x800afa88)!=2 || !roster_count)return;
    int stock=results_overlay_stock(),patched=results_overlay_patched();
    if(!stock && !patched)return;
    enum { RESULT_ICONS=GUEST_ID+GUEST_MAX, RESULT_ENTRIES=RESULT_ICONS*4, GREY_TABLE=RESULT_ENTRIES*8,
           GREY_RAMP=0x7d50 };
    if(!results_icons && !(results_icons=psx_mod_alloc_guest_memory(2*GREY_TABLE,16)))return;
    /* The overlay's table is its own copy of the game's icon table
     * (0x8002152C), filled after the overlay loads: take the stock table,
     * with entry 21 as it was before __wrap_func_8004B928 borrowed it. */
    for(unsigned v=0;v<RESULT_ENTRIES;v++) {
        /* 0x59 (22 * 4 + 1) reads ID 23's entry (0x800F0E0C). */
        unsigned id=v==0x59?GUEST_ID:v>>2;
        uint32_t uv,page;
        const Tekken3Guest *alt=alt_face(id,v&3);
        if(alt){unsigned a=(unsigned)(alt-alt_faces);uv=alt_tile_uv(a,0);page=TILE_PAGE;}
        else if(id>=GUEST_ID){int k=tekken3_guest_character(id);uv=k<0?stock_icon_uv:tile_uv((unsigned)k);page=k<0?stock_icon_page:TILE_PAGE;}
        else if(id==21){uv=stock_icon_uv;page=stock_icon_page;}
        else {uv=psx_mod_read_word(0x8002152c+id*8);page=psx_mod_read_word(0x8002152c+id*8+4);}
        uint32_t e=results_icons+v*8;
        psx_mod_write_word(e,uv);psx_mod_write_word(e+4,page);
        psx_mod_write_word(e+GREY_TABLE,alt?alt_tile_uv((unsigned)(alt-alt_faces),1):(uv&0xffff)|(uint32_t)GREY_RAMP<<16);
        psx_mod_write_word(e+GREY_TABLE+4,page);
    }
    patch(0x800ee368,0x24060058,0);                 /* no "?" clamp for player 1 */
    patch(0x800ee374,0x24120058,0);                 /* nor for player 2 */
    patch(0x800f0e50,0x28820016,0x38820016);        /* slti -> xori: only 22 is "?" */
    patch(0x800f0e24,0x000418c0,0x001418c0);        /* sll v1,a0,3 -> sll v1,s4,3 */
    /* andi v0,s3,0x20; lw s4,0(v1); then: beq v0,zero,+4; lhu s3,4(v1);
     * lw s4,GREY_TABLE(v1); nop; nop (was lui v0,0x7D50; or s4,v1,v0). */
    if(psx_mod_read_word(0x800f0e44)==0x0062a025) {
        patch(0x800f0e34,0x94730004,0x10400004);
        patch(0x800f0e38,0x10400003,0x94730004);
        patch(0x800f0e3c,0x3283ffff,0x8c740000|GREY_TABLE);
        patch(0x800f0e40,0x3c027d50,0);
        patch(0x800f0e44,0x0062a025,0);
    }
    patch(0x800f0e1c,0x3c02800c,0x3c020000|(results_icons>>16));
    patch(0x800f0e20,0x24429158,0x34420000|(results_icons&65535));
}
/* Devil Jin easter egg (tekken3_ttt1_mod.c): while a player has asked for
 * it, Jin's punch-costume descriptor (entry 9 * 4 of the table the game reads
 * through metadata) becomes a copy named DEVIL JIN, with the width of its
 * name bitmap (Jin-T3-devil-name.4bpp, tools/ttt1_devil_jin.py), and the
 * bitmap replaces Jin's name above that player's life bar. */
extern int tekken3_devil_jin_requested(unsigned player);
enum { JIN_PUNCH_ENTRY=9*4 };
static uint16_t devil_name[NAME_MAX_HALFWORDS*16];
static unsigned devil_name_halfwords;
static uint32_t devil_desc,jin_desc_stock;
static void devil_jin_load(void) {
    static int read;
    if(read)return;read=1;
    const char *root=tekken3_ttt1_asset_root();char path[4096];
    if(!root || snprintf(path,sizeof path,"%s/Jin-T3-devil-name.4bpp",root)>=(int)sizeof path)return;
    FILE *f=fopen(path,"rb");if(!f)return;
    long size=(fseek(f,0,SEEK_END)==0)?ftell(f):-1;rewind(f);
    if(size>0 && size%32==0 && size/32<=NAME_MAX_HALFWORDS &&
       fread(devil_name,1,(size_t)size,f)==(size_t)size)devil_name_halfwords=(unsigned)(size/32);
    fclose(f);
    if(!devil_name_halfwords)return;
    jin_desc_stock=psx_mod_read_word(metadata+JIN_PUNCH_ENTRY*4);
    devil_desc=guest_desc(GUEST_MAX);
    for(unsigned i=0;i<12;i++)psx_mod_write_byte(devil_desc+i,psx_mod_read_byte(jin_desc_stock+i));
    copy_host(devil_desc+12,(const unsigned char*)"DEVIL JIN",10);
    /* +0 points at the name string the stage loading screen spells in its
     * chrome letters: Jin's copy still pointed at "JIN". */
    psx_mod_write_word(devil_desc,devil_desc+12);
    psx_mod_write_byte(devil_desc+5,(unsigned char)(devil_name_halfwords*4));
}
static void devil_jin_name(unsigned state) {
    devil_jin_load();
    if(!devil_name_halfwords)return;
    int wanted=tekken3_devil_jin_requested(0) || tekken3_devil_jin_requested(1);
    uint32_t entry=metadata+JIN_PUNCH_ENTRY*4,target=wanted?devil_desc:jin_desc_stock;
    if(psx_mod_read_word(entry)!=target)psx_mod_write_word(entry,target);
    if(state==8)for(unsigned p=0;p<2;p++)
        if(tekken3_devil_jin_player(p))gr_vram_transfer_in(464,p*256,devil_name_halfwords,16,devil_name);
}
/* At the selector the name switches as soon as the request is made, as
 * Eddy's does to TIGER on Start. The overlay draws each player's name from
 * that player's block: atlas index at 0x80118674 and width in pixels at
 * 0x80118678 (+0x7C for player 2); Start on Eddy turns P1's 8 (EDDY, 33)
 * into 21 (TIGER, 37) and leaves P2 alone. The requesting player gets index
 * DEVIL_NAME_ID + p, pointed at his row of the atlas (free, since he is on
 * Jin), so a second Jin keeps his own name. */
enum { SELECTOR_NAME_ID=0x80118674, DEVIL_NAME_ID=40 };
static void devil_jin_selector_name(void) {
    if(!devil_name_halfwords)return;
    for(unsigned p=0;p<2;p++) {
        if(!tekken3_devil_jin_requested(p) || psx_mod_read_word(0x80118668+p*0x7c)!=JIN_PUNCH_ENTRY/4)continue;
        unsigned row=NAME_ROW+p,id=DEVIL_NAME_ID+p;
        gr_vram_transfer_in(NAME_X,row*16,devil_name_halfwords,16,devil_name);
        psx_mod_write_word(name_table+id*4,0x80|(row<<12));
        psx_mod_write_word(SELECTOR_NAME_ID+p*0x7c,id);
        psx_mod_write_word(SELECTOR_NAME_ID+4+p*0x7c,devil_name_halfwords*4);
    }
}
/* The selector loads the big portrait when the character under the cursor
 * differs from the one shown (+0x14): once a player confirms Panda or
 * Tiger, or cancels them, mark it as none so the portrait loads again,
 * through the decoder (__wrap_func_80031BFC). */
static int alt_face_shown[2];
static void alt_face_selector(void) {
    for(unsigned p=0;p<2;p++) {
        uint32_t block=PLAYER_STATE+p*0x7c;
        int want=confirmed((int)p) && alt_face(cursor_character((int)p),psx_mod_read_word(block+0x20));
        if(want==alt_face_shown[p])continue;
        alt_face_shown[p]=want;
        psx_mod_write_word(SHOWN_CHARACTER+p*0x7c,NO_CHARACTER);
    }
}
/* The loading screen's card of player p: their guest's, or Panda's or
 * Tiger's for the costume they fight in; NULL for any other fighter. */
static const Tekken3Guest *card_face(unsigned p) {
    unsigned id=psx_mod_read_half(0x800add5c+p*2);
    if(tekken3_guest_character(id)>=0)return &guests[p];
    return alt_face(id,psx_mod_read_half(0x800add98+p*2));
}
static void loading_card_palette(unsigned p) {
    const Tekken3Guest *g=card_face(p);
    if(!g)return;
    ttt1_ui_palette_upload(&loading_palette[p],LOADING_PALETTE_Y+p,(const uint16_t*)(g->ui+g->ui_offsets[4]+20));
}
static void arena_tick(unsigned state);
static void opponents_tick(unsigned state);
static void team_tick(unsigned state);
static void portraits_tick(unsigned state);
/* The CPU's fighter of the current Survival fight (ID * 4 + costume), noted
 * as beaten when the next fight loads. A new run starts at the selector. */
static void survival_tick(unsigned state) {
    static int current=-1;
    if(psx_mod_read_word(0x800afa88)!=4){current=-1;return;}
    /* The wins above the health bars (0x800AFACC) is the sum of the counters
     * of IDs 0..21, set when a fight is won (0x800B16A8): a guest's win goes
     * in a counter past the table and is left out. The bottom line and the
     * ranking read the stage count (0x800AFAAC), which is right. */
    if(psx_mod_read_word(0x800afacc)!=psx_mod_read_word(0x800afaac))psx_mod_write_word(0x800afacc,psx_mod_read_word(0x800afaac));
    if(state==9){memset(survival_beaten,0,sizeof survival_beaten);memset(sv_guest_wins,0,sizeof sv_guest_wins);current=-1;return;}
    if(state==8 && psx_mod_read_half(0x800ae224)>=6) {
        for(unsigned p=0;p<2;p++)if(!psx_mod_read_half(0x800ae1f8+p*2))
            current=(int)(psx_mod_read_half(0x800add5c+p*2)*4+(psx_mod_read_half(0x800add98+p*2)&3));
    } else if(state==11 && current>=0) {
        unsigned id=(unsigned)current>>2;
        if(id<sizeof survival_beaten)survival_beaten[id]|=alt_face(id,(unsigned)current&3)?BEATEN_ALT:BEATEN_STOCK;
        else if(id-GUEST_ID<GUEST_MAX)sv_guest_wins[id-GUEST_ID]++;
        current=-1;
    }
}
void tekken3_ttt1_roster_tick(void) {
    if(enabled<0)enabled=roster_setting();
    if(!enabled)return;
    if(!initialized)initialize();if(!initialized)return;
    patch_tables();
    unsigned state=psx_mod_read_word(0x800ae204);
    arena_tick(state);
    cpu_switch_tick();
    opponents_tick(state);
    team_tick(state);
    portraits_tick(state);
    devil_jin_name(state);
    int cabinet=state==9 && psx_mod_read_word(0x8010ff4c)==0x27bdffd0;
    tekken3_ranking_tick();
    static int was_cabinet;
    /* A fight since the modes menu (Practice's PLAYER SELECT goes 8, 1, 9;
     * a new mode 4, 9): the selector did not reload its palettes. */
    static unsigned cabinet_frames;
    static int fought,from_fight;
    if(state==8)fought=1;
    if(state==4)fought=0;
    if(!was_cabinet && cabinet){from_fight=fought;cabinet_frames=0;}
    if(cabinet && ++cabinet_frames==10) {
        if(from_fight && icon_palettes_saved)icon_palettes_move(0);
        else if(!from_fight)icon_palettes_move(1);
    }
    if(was_cabinet && !cabinet)closed_on_tag=page;
    was_cabinet=cabinet;
    if(!cabinet){page=stock_saved=reopened=0;confirmed_page[0]=confirmed_page[1]=-1;alt_face_shown[0]=alt_face_shown[1]=0;}
    /* Reopening on the Tag page is for coming back to the selector from a
     * fight (Practice's player select, a continue), not for a new mode. */
    if(state==4)closed_on_tag=0;
    /* Confirming passes through one frame of state 8, then the loading (11),
     * and all that while the 16:9 view keeps showing the selector's
     * composition: its tiles must still be there. */
    static unsigned away;
    away=(cabinet || state==10 || state==11 || team_screen(state) ||
          (state==12 && psx_mod_read_word(0x800afa88)==2) || time_attack_end(state) ||
          (survival_end(state) && tiles_active))?0:away+1;
    survival_tick(state);
    if(away>=3)tiles_release();
    if(state==10){grid_availability();grid_park_prompt_cursor();grey_rows_release();}
    if(state!=10){
        if(grid_page){grid_page=0;write_grid_page();}
        grid_confirmed_page[0]=grid_confirmed_page[1]=-1;
    }
    for(unsigned p=0;p<2;p++)if(state!=11) {
        ttt1_ui_palette_release(&loading_palette[p],LOADING_PALETTE_Y+p);
        loading_card_drawn[p]=0;
    }
    if(cabinet) {
        /* The overlay's "ID < 22" tests and its availability mask. */
        immediate(0x8010d5f0,0x1f,(0x1fffffu|guest_bits())>>16);
        immediate(0x8010d9b4,22,select_bound());immediate(0x8010da30,22,select_bound());
        immediate(0x8010db38,23,select_bound());
        immediate(0x8010dc0c,22,select_bound());immediate(0x8010f7b0,22,select_bound());
        if(!stock_saved && psx_mod_read_word(GRID_COUNT)==STOCK_CELLS) {
            for(unsigned i=0;i<GRID_BYTES;i++)stock_grid[i]=psx_mod_read_byte(GRID+i);
            for(unsigned i=0;i<sizeof stock_ids;i++)stock_ids[i]=psx_mod_read_byte(CELL_IDS+i);
            stock_saved=1;
        }
        /* Reopen the Tag page once the selector has settled: choosing
         * phase, player 1's cursor on a real character, for 15 frames. */
        static unsigned settled;
        if(!stock_saved || reopened || psx_mod_read_half(0x800ae224)!=1 ||
           cursor_character(0)>=select_bound() || cursor_character(0)==ABSENT)settled=0;
        else if(++settled>=15) {
            reopened=1;
            if(closed_on_tag && !page)switch_page();
        }
        if(page && psx_mod_read_half(0x800ae224)<=1){write_tag_page();hide_hidden_cell();}
        for(unsigned p=0;p<2;p++)follow(p,cursor_character((int)p));
        patch_name_lookup();
        write_names();
        devil_jin_selector_name();
        alt_face_selector();
    }
    lend_third_costume_bits(cabinet);
    if(cabinet || state==10)tiles_upload();
    /* A Team Battle's FIGHT screens (state 11 for a few frames, then state 8
     * before phase 6) line up the teams again, but the tiles went back at
     * the fight: they go up again when the screen first asks for a guest's
     * icon (__wrap_func_8004B928). Not as the screen starts: the fight's
     * last picture is still on screen then, drawn with player 1's texture
     * band and the arena palettes of rows 480.. that the tiles take. The
     * screen loads the next fighters into that band meanwhile: the tiles go
     * back on top each frame, and tiles_release returns the game's content. */
    else if(state==12 && psx_mod_read_word(0x800afa88)==2 && !tiles_active)tiles_upload();
    else if(team_screen(state) && tiles_active)tiles_upload();
    time_attack_beaten(state);
    survival_guests_beaten(state);
    if(state==12 && tiles_active)results_history_patch();
    if(state==8)effect_headers();
    embu_effect_headers(state);
    if(state==11) {
        /* Arcade loading thumbnails have half-height pixels. The PS1's framed
         * team cards use 58 rows, so preserve their aspect ratio. One card
         * per player who chose a guest: player 1's at ICON_X, player 2's
         * beside it. */
        for(unsigned p=0;p<2;p++) {
            unsigned id=psx_mod_read_half(0x800add5c+p*2);
            if(tekken3_guest_character(id)<0) {
                const Tekken3Guest *alt=card_face(p);
                if(!alt)continue;
                if(loading_card_drawn[p])loading_card_palette(p);
                gr_vram_transfer_in(ICON_X+p*16,ICON_Y,16,58,alt->loading_pixels);
                continue;
            }
            follow(p,id);
            follow_costume(p,psx_mod_read_half(0x800add98+p*2));
            reset_button_donor(p);
            const Tekken3Guest *g=&guests[p];
            if(loading_card_drawn[p])loading_card_palette(p);
            gr_vram_transfer_in(ICON_X+p*16,ICON_Y,16,58,g->loading_pixels);
        }
    }
    /* Selection identity: the actor carries its guest's own ID. */
    if(state==8) {
        static int selected=-1;int wanted=0;
        for(unsigned p=0;p<2;p++) {
            unsigned id=psx_mod_read_half(0x800a9240+p*0x188c);
            if(id==native_id[p]){wanted=1;continue;}
            if(tekken3_guest_character(id)<0)continue;
            /* The loading screen already chose from 0x800ADD5C. In a team
             * battle the actor still carries the previous member for the
             * first frames of the next round: follow it only once the
             * round runs. */
            if(psx_mod_read_half(0x800ae224)>=6) {
                follow(p,id);
                follow_costume(p,psx_mod_read_half(0x800a923c+p*0x188c)&3);
            }
            wanted=1;gr_vram_transfer_in(464,p*256,guests[p].name_halfwords,16,guests[p].name_pixels);
        }
        for(unsigned p=0;p<2;p++)if(tekken3_devil_jin_player(p))wanted=1;
        if(wanted!=selected){tekken3_ttt1_select(wanted);selected=wanted;}
    }
}

void __wrap_func_80052938(CPUState *cpu) {
    if(tekken3_ttt1_roster_enabled() && (cpu->gpr[31]==0x80053c10 || cpu->gpr[31]==0x80053884)) {
        int primary=cpu->gpr[31]==0x80053884;
        unsigned b=psx_mod_read_half(0x800adf00+cpu->gpr[primary?19:20]*2);
        unsigned state=cpu->gpr[16];int x=psx_mod_read_word(state+8),y=psx_mod_read_word(state+12);
        /* The player block holds the game's seven-column cell; move on the
         * page as drawn, then store the game's cell back. */
        if(grid_page && x>=0 && y>=0){int k=y*GRID_COLS+x;x=k%VS_TAG_COLS;y=k/VS_TAG_COLS;}
        int rows=(int)grid_rows();
        if(y<0 || y>=rows)y=0;if(x<0 || x>=(int)grid_width((unsigned)y))x=0;
        int dx=((b>>13)&1)-((b>>15)&1),dy=((b>>14)&1)-((b>>12)&1);
        if(dx){int n=(int)grid_width((unsigned)y);x=(x+dx+n)%n;}
        else {y+=dy;if(y<0)y=0;if(y>=rows)y=rows-1;if(x>=(int)grid_width((unsigned)y))x=(int)grid_width((unsigned)y)-1;}
        if(grid_page){int k=y*VS_TAG_COLS+x;x=k%GRID_COLS;y=k/GRID_COLS;}
        cpu->gpr[17]=x;cpu->gpr[primary?18:19]=y;cpu->pc=primary?0x80053910:0x80053c9c;return;
    }
    __real_func_80052938(cpu);
}
void __wrap_func_80052940(CPUState *cpu) {
    if(tekken3_ttt1_roster_enabled() && (cpu->gpr[31]==0x80053a1c || cpu->gpr[31]==0x80053d90)) {
        uint32_t root=cpu->gpr[4],state=cpu->gpr[5],input=cpu->gpr[6];
        unsigned x=psx_mod_read_word(state+8),y=psx_mod_read_word(state+12),n=psx_mod_read_word(state+44);
        cpu->gpr[29]-=32;psx_mod_write_word(cpu->gpr[29]+20,cpu->gpr[17]);
        unsigned cell=y*GRID_COLS+x;
        unsigned id=grid_page && cell<roster_count?GUEST_ID+cell:0;
        /* Every grid mode (VS 1, Team Battle 2, Tekken Ball 7): the native
         * path rejects IDs of 22 and above with a compiled-in bound
         * (0x80052EB0) that a code patch does not reach. */
        /* Punch or kick, like any fighter; Start for a third costume, or
         * triangle in Team Battle, where the game takes Start first
         * (0x80053968, a random team) and triangle gives a native its
         * third costume. */
        uint32_t third_key=psx_mod_read_word(0x800afa88)==2?0x10:0x800;
        int third=id && (input&third_key) && roster[id-GUEST_ID].third_costume;
        if(id && ((input&0xf0) || third) && n<8 &&
           (psx_mod_read_word(state+36)&(1u<<(id&31)))) {
            /* Append the guest to the real native choice array;
             * continue through the game's availability, sound and completion
             * code with the same saved-register layout as its prologue. */
            psx_mod_write_word(cpu->gpr[29]+16,cpu->gpr[16]);
            psx_mod_write_word(cpu->gpr[29]+24,cpu->gpr[18]);
            psx_mod_write_word(cpu->gpr[29]+28,cpu->gpr[31]);
            cpu->gpr[17]=root;cpu->gpr[16]=state;cpu->gpr[18]=n;
            cpu->gpr[6]=id*4+(third?2:!!(input&0x60));
            psx_mod_write_word(state+56+n*4,cpu->gpr[6]);
            cpu->pc=0x80052f98;return;
        }
        cpu->pc=0x80052dec;return;
    }
    __real_func_80052940(cpu);
}
void __wrap_func_8004B790(CPUState *cpu) {
    if(tekken3_ttt1_roster_enabled() && (cpu->pc==0 || cpu->pc==0x8004b790) && tekken3_guest_character(cpu->gpr[4])>=0) {
        cpu->gpr[2]=ui_color;cpu->pc=cpu->gpr[31];return;
    }
    __real_func_8004B790(cpu);
}
void __wrap_func_8004B928(CPUState *cpu) {
    if(tekken3_ttt1_roster_enabled() && (cpu->pc==0 || cpu->pc==0x8004b928)) {
        /* Player 2's moved tiles lie over the stock icons (mod.c). */
        if(psx_mod_read_word(0x800ae204)!=8 || psx_mod_read_half(0x800ae224)<6)tekken3_ttt1_moved_tiles_hide();
        uint32_t slot=cpu->gpr[29]+16;
        /* The grid's per-player small portrait (call returning to
         * 0x8005431C) turns any ID of 22 and above into 88, "?", with a
         * bound compiled into the recompiled code. Take the ID from the
         * player's cell instead: x at s1-28, y at s1-24. */
        /* The same call draws every member of the team panel (s0 = member,
         * s1 = player block + 36: availability mask, then +8 the count
         * chosen). Chosen members keep their own ID. In Team Battle the
         * others, the one being chosen included, stay "?" until the choice
         * is confirmed, as on the stock page; elsewhere the member being
         * chosen shows the cell under the cursor while it is still free. */
        if(cpu->gpr[31]==0x8005431c && cpu->gpr[16]<psx_mod_read_word(cpu->gpr[17]+8) &&
           cpu->gpr[16]<8) {
            /* A member already chosen: its ID came clamped to 88 like any ID
             * of 22 and above. The choices follow at +56 of the block. */
            unsigned member=psx_mod_read_word(cpu->gpr[17]+20+cpu->gpr[16]*4);
            if(tekken3_guest_character(member>>2)>=0)psx_mod_write_word(slot,member&~3u);
        } else if(cpu->gpr[31]==0x8005431c && grid_page && psx_mod_read_word(0x800afa88)!=2 &&
           cpu->gpr[16]==psx_mod_read_word(cpu->gpr[17]+8)) {
            unsigned x=psx_mod_read_word(cpu->gpr[17]-28),y=psx_mod_read_word(cpu->gpr[17]-24);
            if(x<GRID_COLS && y<3) {
                unsigned cell_id=psx_mod_read_byte(team_table+(y*GRID_COLS+x)*6+4);
                if(tekken3_guest_character(cell_id>>2)>=0 &&
                   (psx_mod_read_word(cpu->gpr[17])&(1u<<((cell_id>>2)&31))))
                    psx_mod_write_word(slot,cell_id);
            }
        }
        /* Team Battle's FIGHT screen (overlay call returning to 0x800B33D0)
         * lines up each team's other members, starting after the fighter on
         * stage and wrapping round: those still to fight, then the defeated
         * (checked, flags 0x68). s1 is the sprite's rank in the screen's
         * list: player 1's members from 0, three other sprites, then player
         * 2's (10..16 for teams of eight, 6..8 for teams of four). A guest's
         * ID comes clamped to 88 ("?"), like a CPU member still to fight.
         * Teams: 13 bytes from 0x800AFAE1 per player, ID * 4 + costume, +8
         * the member on stage, +12 the size. The game shows a player's whole
         * team but only the CPU's defeated members, the others "?": a guest
         * shows under the same rule. */
        if(cpu->gpr[31]==0x800b33d0 && psx_mod_read_word(0x800afa88)==2 &&
           psx_mod_read_word(slot)==88) {
            unsigned size1=psx_mod_read_byte(0x800afae1+12);
            if(!size1 || size1>8)size1=8;
            unsigned s1=cpu->gpr[17],p=s1>=size1+2,j=p?s1-(size1+2):s1;
            uint32_t team=0x800afae1+13*p;
            unsigned size=psx_mod_read_byte(team+12),stage=psx_mod_read_byte(team+8);
            if(!size || size>8)size=8;
            unsigned m=(stage+1+j)%size;
            /* A player's own picks (team + 10 of them) show; the places the game
             * drew for the Random fill stay "?" until fought, like the stock
             * fighters drawn there. */
            unsigned picked=psx_mod_read_half(0x800ae1f8+p*2)?psx_mod_read_byte(team+10):0;
            if(j+1<size && (m<picked || m<stage)) {
                unsigned member=psx_mod_read_byte(team+m);
                if(tekken3_guest_character(member>>2)>=0)psx_mod_write_word(slot,member&~3u);
            }
        }
        /* TEAM BATTLE RESULTS (state 12, overlay call returning to
         * 0x800EE150): s5 is the team list, s0 the member. */
        if(cpu->gpr[31]==0x800ee150 && psx_mod_read_word(slot)==88 &&
           (cpu->gpr[21]==0x800afae1 || cpu->gpr[21]==0x800afaee) && cpu->gpr[16]<8) {
            unsigned member=psx_mod_read_byte(cpu->gpr[21]+cpu->gpr[16]);
            if(tekken3_guest_character(member>>2)>=0)psx_mod_write_word(slot,member&~3u);
        }
        unsigned id=psx_mod_read_word(slot)>>2,costume=psx_mod_read_word(slot)&3;
        int k=tekken3_guest_character(id);
        /* Panda, Tiger: the icon is asked for with the costume (ID * 4 +
         * costume: the team panel, the FIGHT screen). Not in the attract
         * rankings, which list a character, not a costume. */
        const Tekken3Guest *alt=k<0 && psx_mod_read_word(0x800ae204)!=17?alt_face(id,costume):NULL;
        if(k<0 && !alt && cpu->gpr[31]==0x800f0420 && survival_end(psx_mod_read_word(0x800ae204)))alt=survival_face(id);
        /* The attract rankings (state 17): the guest's face lies over the
         * icon of a stock fighter they do not list (tekken3_ttt1_records.c). */
        if(k>=0 && psx_mod_read_word(0x800ae204)==17) {
            int lent=tekken3_ranking_guest_slot(id);
            if(lent>=0){psx_mod_write_word(slot,(uint32_t)lent*4);k=-1;id=(unsigned)lent;}
        }
        if(k>=0) {
            /* Borrow icon slot 21: the Tag page tile of guest k, or on the
             * loading screen the card of the player who chose it. */
            uint32_t uv,tpage=ICON_PAGE;
            if((team_screen(psx_mod_read_word(0x800ae204)) ||
                time_attack_end(psx_mod_read_word(0x800ae204))) && !tiles_active)
                tiles_upload();
            /* Team Battle's FIGHT screen lines up the team's members: the
             * Tag page tiles are still in VRAM there (tiles_release waits). */
            int team_loading=(team_screen(psx_mod_read_word(0x800ae204)) || psx_mod_read_word(0x800ae204)==12) &&
                psx_mod_read_word(0x800afa88)==2 && tiles_active;
            if(psx_mod_read_word(0x800ae204)==11 && !team_loading) {
                unsigned p=psx_mod_read_half(0x800add5c)==id?0:1;
                if(!loading_card_drawn[p]){loading_card_drawn[p]=1;loading_card_palette(p);}
                uv=((uint32_t)((LOADING_PALETTE_Y+p)<<6)<<16)|(ICON_Y<<8)|(p*32);
            } else {
                uv=tile_uv(k);
                tpage=TILE_PAGE;
                uint32_t flags=psx_mod_read_word(cpu->gpr[29]+20);
                int grey=team_loading && (flags&0x20)?grey_palette_row((unsigned)k):0;
                if(grey) {
                    uv=(uv&0xffff)|((uint32_t)(grey<<6)<<16);
                    psx_mod_write_word(cpu->gpr[29]+20,flags&~0x20u);
                }
            }
            psx_mod_write_word(slot,21*4);
            psx_mod_write_word(0x8002152c+21*8,uv);
            psx_mod_write_half(0x8002152c+21*8+4,tpage);
        } else if(alt) {
            /* Slot 21 as for a guest: Panda's or Tiger's tile beside the
             * guests' (tiles_upload), greyed in its own palette row for a
             * defeated member; on the loading screen, the player's card. */
            unsigned a=(unsigned)(alt-alt_faces),state=psx_mod_read_word(0x800ae204);
            if((team_screen(state) || time_attack_end(state) || survival_end(state)) && !tiles_active)tiles_upload();
            int team_loading=(team_screen(state) || state==12) && psx_mod_read_word(0x800afa88)==2 && tiles_active;
            uint32_t uv=0,tpage=TILE_PAGE;
            if(state==11 && !team_loading) {
                unsigned p=psx_mod_read_half(0x800add5c)==id && psx_mod_read_half(0x800add98)==costume?0:1;
                if(card_face(p)==alt) {
                    if(!loading_card_drawn[p]){loading_card_drawn[p]=1;loading_card_palette(p);}
                    uv=((uint32_t)((LOADING_PALETTE_Y+p)<<6)<<16)|(ICON_Y<<8)|(p*32);
                    tpage=ICON_PAGE;
                }
            } else if(tiles_active) {
                uint32_t flags=psx_mod_read_word(cpu->gpr[29]+20);
                int grey=team_loading && (flags&0x20);
                if(grey)psx_mod_write_word(cpu->gpr[29]+20,flags&~0x20u);
                uv=alt_tile_uv(a,grey);
            }
            if(uv) {
                psx_mod_write_word(slot,21*4);
                psx_mod_write_word(0x8002152c+21*8,uv);
                psx_mod_write_half(0x8002152c+21*8+4,tpage);
            }
        } else if(id==21) {
            psx_mod_write_word(0x8002152c+21*8,stock_icon_uv);
            psx_mod_write_word(0x8002152c+21*8+4,stock_icon_page);
        }
    }
    __real_func_8004B928(cpu);
}
void __wrap_func_80031BFC(CPUState *cpu) {
    if(tekken3_ttt1_roster_enabled() && (cpu->pc==0 || cpu->pc==0x80031bfc) &&
       ((cpu->gpr[31]==0x8010e574 && tekken3_guest_character(psx_mod_read_word(cpu->gpr[16]+0x1c))>=0) ||
        (cpu->gpr[31]==0x8004c814 && cpu->gpr[20]<2 &&
         tekken3_guest_character(psx_mod_read_half(0x800add5c+cpu->gpr[20]*2))>=0))) {
        /* Selector: the guest of the cell. Loading screen: the player's choice. */
        unsigned id=cpu->gpr[31]==0x8004c814?psx_mod_read_half(0x800add5c+cpu->gpr[20]*2):
                    psx_mod_read_word(cpu->gpr[16]+0x1c);
        const Tekken3Guest *g=&roster[tekken3_guest_character(id)];
        copy_host(cpu->gpr[5],g->ui+g->ui_offsets[0],g->ui_lengths[0]);
        cpu->gpr[2]=g->ui_lengths[0];cpu->pc=cpu->gpr[31];return;
    }
    /* Panda, Tiger: the stock portrait (Kuma's, Eddy's) was read and goes
     * through the decoder; the confirmed costume's face comes out instead.
     * Selector: s0 is the player block (+0 state, +0x1C character, +0x20
     * costume); loading screen: s4 is the player. */
    if(tekken3_ttt1_roster_enabled() && (cpu->pc==0 || cpu->pc==0x80031bfc)) {
        const Tekken3Guest *g=NULL;
        if(cpu->gpr[31]==0x8010e574) {
            unsigned state=psx_mod_read_word(cpu->gpr[16]);
            if(state!=CHOOSING && state!=CHOOSING_CPU)
                g=alt_face(psx_mod_read_word(cpu->gpr[16]+0x1c),psx_mod_read_word(cpu->gpr[16]+0x20));
        } else if(cpu->gpr[31]==0x8004c814 && cpu->gpr[20]<2)
            g=alt_face(psx_mod_read_half(0x800add5c+cpu->gpr[20]*2),psx_mod_read_half(0x800add98+cpu->gpr[20]*2));
        if(g) {
            copy_host(cpu->gpr[5],g->ui+g->ui_offsets[0],g->ui_lengths[0]);
            cpu->gpr[2]=g->ui_lengths[0];cpu->pc=cpu->gpr[31];return;
        }
    }
    __real_func_80031BFC(cpu);
}
/* Loading-screen portrait is the same native banded TIM. */
void __wrap_func_80052AD0(CPUState *cpu) {
    if(tekken3_ttt1_roster_enabled() && (cpu->pc==0 || cpu->pc==0x80052ad0) &&
       cpu->gpr[31]==0x80052770 && cpu->gpr[20]<2 &&
       tekken3_guest_character(psx_mod_read_half(0x800add5c+cpu->gpr[20]*2))>=0) {
        /* The loader expects compressed input. Its decoder wrapper supplies
         * the validated TIM; never feed a raw TIM into the native LZ decoder. */
        psx_mod_write_byte(cpu->gpr[4],0);
        cpu->gpr[2]=0;cpu->pc=cpu->gpr[31];return;
    }
    __real_func_80052AD0(cpu);
}
void __wrap_func_80052958(CPUState *cpu) {
    if(tekken3_ttt1_roster_enabled() && (cpu->pc==0 || cpu->pc==0x80052958) && tekken3_guest_character(cpu->gpr[5])>=0)cpu->gpr[5]=9;
    __real_func_80052958(cpu);
}
void __wrap_func_80052990(CPUState *cpu) {
    if(tekken3_ttt1_roster_enabled() && (cpu->pc==0 || cpu->pc==0x80052990) && tekken3_guest_character(cpu->gpr[5])>=0)cpu->gpr[5]=9;
    __real_func_80052990(cpu);
}
void __wrap_func_8006BF20(CPUState *cpu) {
    if(tekken3_ttt1_roster_enabled() && (cpu->pc==0 || cpu->pc==0x8006bf20) && cpu->gpr[4]>=303 && cpu->gpr[4]<=306)
        cpu->gpr[4]-=(GUEST_MODEL-18)*4;
    __real_func_8006BF20(cpu);
}
void __wrap_func_8003626C(CPUState *cpu) {
    if(tekken3_ttt1_roster_enabled() && (cpu->pc==0 || cpu->pc==0x8003626c) && cpu->gpr[4]==GUEST_MODEL)cpu->gpr[4]=18;
    __real_func_8003626C(cpu);
}
void __wrap_func_80036294(CPUState *cpu) {
    if(tekken3_ttt1_roster_enabled() && (cpu->pc==0 || cpu->pc==0x80036294) && psx_mod_read_half(cpu->gpr[4]+28)==GUEST_MODEL) {
        cpu->gpr[2]=psx_mod_read_byte(0x80095950+18);cpu->pc=cpu->gpr[31];return;
    }
    __real_func_80036294(cpu);
}
void __wrap_func_800362C4(CPUState *cpu) {
    if(tekken3_ttt1_roster_enabled() && (cpu->pc==0 || cpu->pc==0x800362c4) && psx_mod_read_half(cpu->gpr[4]+28)==GUEST_MODEL) {
        cpu->gpr[2]=psx_mod_read_byte(0x80095984+18);cpu->pc=cpu->gpr[31];return;
    }
    __real_func_800362C4(cpu);
}
void __wrap_func_8003F044(CPUState *cpu) {
    if(tekken3_ttt1_roster_enabled() && (cpu->pc==0 || cpu->pc==0x8003f044) &&
       tekken3_guest_character(psx_mod_read_half(cpu->gpr[4]+24))>=0) {
        /* TTT1's Jun radius profile (80194C20[28] -> 800112DC) is byte-for-
         * byte identical to SLUS-00402's standard human profile. The stock
         * lookup has only 22 entries and ID 23 otherwise reads a null pointer. */
        uint32_t profile=psx_mod_read_word(0x80096ff0+9*4);
        for(unsigned i=0;i<14;i++) {
            unsigned radius=psx_mod_read_half(profile+i*2);
            psx_mod_write_half(cpu->gpr[4]+0x218+i*20,radius);
            psx_mod_write_word(cpu->gpr[4]+0x21c+i*20,radius*radius);
        }
        cpu->pc=cpu->gpr[31];return;
    }
    __real_func_8003F044(cpu);
}
/* SLUS 0x8004F3B0 picks the fight's arena and music (record bytes 10 and
 * 11) from one player's fighter, by mode (jump table 0x800223E8), and stores
 * them at 0x800ADC84 / 0x800AFAA2 and 0x800ADD08 / 0x800AFAA3. Its compiled
 * code keeps the stock record table, so a guest (ID * 4 + costume >= 92)
 * read past its end: a null record, arena 0 (Paul's street) for every
 * guest. The routine leaves through its jump table and finishes elsewhere,
 * so its result is corrected afterwards: here, the player whose fighter
 * decides, found as the routine finds it; roster_tick writes the arena and
 * music of the fighter the guest takes them from (guests.txt, third column;
 * Jin's when none) until the fight begins. */
enum { ARENA=0x800adc84, ARENA_COPY=0x800afaa2, MUSIC=0x800add08, MUSIC_COPY=0x800afaa3 };
static int arena_pending;
static unsigned arena_value,music_value;
static int arena_player(const CPUState *cpu) {
    uint32_t a=cpu->gpr[4];
    unsigned mode=psx_mod_read_word(a),who=psx_mod_read_byte(a+28),chooser=psx_mod_read_byte(0x800b053e);
    switch(mode) {
    case 1: case 2: case 5: return (int)chooser;                 /* VS, Team Battle, Practice */
    case 7: case 8: return -1;                                   /* Tekken Ball, Tekken Force */
    default:                                                     /* Arcade, Time Attack, Survival... */
        return who==1?(int)psx_mod_read_byte(a+31):who==0?0:who==2?(int)chooser:(int)cpu->gpr[5];
    }
}
void __wrap_func_8004F3B0(CPUState *cpu) {
    if((cpu->pc==0 || cpu->pc==0x8004f3b0) && tekken3_ttt1_roster_enabled()) {
        int p=arena_player(cpu),k=p==0 || p==1?tekken3_guest_character(psx_mod_read_half(0x800add5c+p*2)):-1;
        arena_pending=k>=0;
        if(k>=0) {
            unsigned owner=roster[k].arena_owner<STOCK_FIGHTERS?roster[k].arena_owner:9;
            uint32_t record=psx_mod_read_word(0x80097d40+owner*16);
            arena_value=psx_mod_read_byte(record+10);music_value=psx_mod_read_byte(record+11);
        }
    }
    __real_func_8004F3B0(cpu);
}
/* Guests as the CPU's opponents in Arcade and Time Attack (user's choice,
 * 2026-09-25; PASSATION.md objective 5). 0x800B1FCC draws the ten stock
 * opponents at the player's validation into 0x800AFB18 (4 bytes: fighter,
 * costume, stage number; TIPS.md section 25): stages 1-4 among the first
 * ten fighters, 5-8 among the rest, 9 Heihachi (Jin for a Heihachi player),
 * 10 Ogre. Its masks are 32-bit words and stop at ID 21, so the list is
 * rewritten afterwards, once per list, while the loading screen shows
 * stage 1: 1 or 2 guests take the place of drawn fighters at stages 5-8,
 * and one game in BOSS_ONE_IN, Devil, Angel or Unknown replaces the stage 9
 * boss. Never the player's own fighter. TEKKEN3_CPU_GUESTS="min,max,boss"
 * overrides (0,0,0: no guest). */
enum { OPPONENTS=0x800afb18, OPPONENT_COUNT=10, STAGE_INDEX=0x800afaac, GAME_MODE=0x800afa88 };
static unsigned guests_min=1,guests_max=2,boss_one_in=4;
static int hidden_boss(unsigned k) {
    const char *n=roster[k].key;
    return !strcmp(n,"devil") || !strcmp(n,"angel") || !strcmp(n,"unknown");
}
/* Mokujin (15) is the one stock fighter the game's own draws leave out of
 * Time Attack, Survival, Tekken Ball and the CPU's Team Battle team: they
 * may swap a drawn fighter for him as for a guest (pool entry NO_GUEST),
 * once he is unlocked (bit 15 of the available fighters, 0x80097EF0). */
enum { MOKUJIN=15, AVAILABLE=0x80097ef0, NO_GUEST=0xff };
static int mokujin_unlocked(void){return (psx_mod_read_word(AVAILABLE)>>MOKUJIN&1)!=0;}
static const char *fighter_name(unsigned id) {
    static const char *stock[STOCK_FIGHTERS]={"Paul","Law","Lei","King","Yoshimitsu","Nina","Hwoarang","Xiaoyu",
        "Eddy","Jin","Julia","Kuma","Bryan","Heihachi","Ogre","Mokujin","Gun Jack","Gon","Anna","Dr. Bosconovitch",
        "True Ogre","Crow"};
    int k=tekken3_guest_character(id);
    return k>=0?roster[k].name:id<STOCK_FIGHTERS?stock[id]:"?";
}
static void opponents_tick(unsigned state) {
    static unsigned char written[OPPONENT_COUNT*4];
    static int configured;
    if(!configured) {
        configured=1;
        const char *e=getenv("TEKKEN3_CPU_GUESTS");
        unsigned a,b,c;
        if(e && sscanf(e,"%u,%u,%u",&a,&b,&c)==3 && a<=b && b<=4){guests_min=a;guests_max=b;boss_one_in=c;}
    }
    unsigned mode=psx_mod_read_word(GAME_MODE);
    if(state!=11 || (mode!=0 && mode!=3) || psx_mod_read_word(STAGE_INDEX)!=0)return;
    unsigned char list[OPPONENT_COUNT*4];
    for(unsigned i=0;i<sizeof list;i++)list[i]=psx_mod_read_byte(OPPONENTS+i);
    if(list[9*4]!=14 || !memcmp(list,written,sizeof list))return;      /* not built yet, or ours */
    unsigned human=psx_mod_read_half(0x800ae1f8)?0:1,player=psx_mod_read_half(0x800add5c+human*2);
    unsigned pool[GUEST_MAX+1],bosses[GUEST_MAX],n=0,nb=0;
    for(unsigned k=0;k<roster_count;k++) {
        if(GUEST_ID+k==player)continue;
        if(hidden_boss(k))bosses[nb++]=k;else pool[n++]=k;
    }
    if(mode==3 && player!=MOKUJIN && mokujin_unlocked())pool[n++]=NO_GUEST;   /* Arcade's own draw has him */
    unsigned count=guests_max>guests_min?guests_min+draw(guests_max-guests_min+1):guests_min;
    unsigned stages[4]={4,5,6,7};
    for(unsigned i=0;i<count && n;i++) {
        unsigned s=i+draw(4-i),tmp=stages[i];stages[i]=stages[s];stages[s]=tmp;   /* a stage not yet taken */
        unsigned g=draw(n),k=pool[g];pool[g]=pool[--n];                             /* a guest not yet taken */
        unsigned id=k==NO_GUEST?MOKUJIN:GUEST_ID+k;
        list[stages[i]*4]=(unsigned char)id;
        fprintf(stderr,"TTT1 characters: %s is the CPU's stage %u opponent\n",fighter_name(id),stages[i]+1);
    }
    if(nb && boss_one_in && !draw(boss_one_in)) {
        unsigned k=bosses[draw(nb)];
        list[8*4]=(unsigned char)(GUEST_ID+k);
        fprintf(stderr,"TTT1 characters: %s replaces the stage 9 boss\n",roster[k].name);
    }
    for(unsigned i=0;i<sizeof list;i++)psx_mod_write_byte(OPPONENTS+i,list[i]);
    memcpy(written,list,sizeof list);
}
/* Guests in Survival. After each win 0x800B0B84 draws the next opponent
 * (0x800B26D0: a pool that widens with the stage number, +0x24: the first
 * ten under 7, everyone but Ogre and True Ogre under 17, then everyone; the
 * last four opponents left out; TIPS.md section 25), stores it in the CPU's
 * choice (0x800ADD5C + 2 * player) and calls 0x8004F0E4, whose return
 * address there is 0x800B0C00: before that call, a guest may take the drawn
 * fighter's place, as the unlocked fighters come in, from 7 wins, one fight
 * in GUEST_ONE_IN, and Devil, Angel or Unknown with Ogre, from 17, one
 * fight in BOSS_ONE_IN. Never the player's fighter nor one of the last four
 * guests. TEKKEN3_SURVIVAL_GUESTS="guest,boss" overrides (0 = never). */
static uint32_t ball_choice;                      /* Tekken Ball: s1 + 0x70 of a draw just made */
enum { TEKKEN_BALL=7, BALL_SWAP_RETURN=0x800b4848 };
static void ball_swap(unsigned player);
/* The loading screen reloads a player's portrait only when the one asked
 * for (a byte per player, 0x800B8D5A + player) differs from the one held
 * (0x80098106 + player; the selector's cursor byte). Every guest asks for
 * 21, the stock "guest" portrait, and 21 is also what the byte holds for a
 * player 2 who never joined the grid, or after an earlier guest: the load
 * was skipped and the CPU's guest showed a silhouette (Tekken Ball), or the
 * previous guest's face. Outside the selector and the grid, a guest's held
 * portrait is marked as none (0xFF), so it always reloads, from the guest's
 * own files (__wrap_func_80031BFC). */
enum { HELD_PORTRAIT=0x80098106, GUEST_PORTRAIT=21, NO_PORTRAIT=0xff };
static void portrait_reload(unsigned player) {
    if(psx_mod_read_byte(HELD_PORTRAIT+player)==GUEST_PORTRAIT)psx_mod_write_byte(HELD_PORTRAIT+player,NO_PORTRAIT);
}
static void portraits_tick(unsigned state) {
    if(state==9 || state==10)return;
    for(unsigned p=0;p<2;p++) {
        unsigned id=psx_mod_read_half(0x800add5c+p*2);
        if(tekken3_guest_character(id)>=0)portrait_reload(p);
        /* Kuma and Panda, Eddy and Tiger ask for the same portrait: always
         * reload theirs, so the costume's face comes out (alt_face). Not
         * during the loading screen itself, which would load it again. */
        else if(state!=11 && alt_face_character(id))psx_mod_write_byte(HELD_PORTRAIT+p,NO_PORTRAIT);
    }
}
enum { SURVIVAL=4, SURVIVAL_DRAW_RETURN=0x800b0c00, SURVIVAL_GUESTS_FROM=7, SURVIVAL_BOSSES_FROM=17 };
static unsigned survival_guest_one_in=4,survival_boss_one_in=8;
extern void __real_func_8004F0E4(CPUState*);
void __wrap_func_8004F0E4(CPUState *cpu) {
    static int recent[4]={-1,-1,-1,-1},configured;
    static unsigned next_recent;
    if(!configured) {
        configured=1;
        const char *e=getenv("TEKKEN3_SURVIVAL_GUESTS");
        unsigned a,b;
        if(e && sscanf(e,"%u,%u",&a,&b)==2){survival_guest_one_in=a;survival_boss_one_in=b;}
    }
    unsigned player=cpu->gpr[4];
    /* Tekken Ball: the draw just made (__wrap_func_8004CE54) was stored in
     * the CPU's choice, and 0x8004F0E4 follows it (return 0x800B4848) in the
     * same frame, before any loading: see ball_swap. */
    if((cpu->pc==0 || cpu->pc==0x8004f0e4) && player<2 && cpu->gpr[31]==BALL_SWAP_RETURN &&
       ball_choice && psx_mod_read_word(GAME_MODE)==TEKKEN_BALL && tekken3_ttt1_roster_enabled())
        ball_swap(player);
    if((cpu->pc==0 || cpu->pc==0x8004f0e4) && player<2 && cpu->gpr[31]==SURVIVAL_DRAW_RETURN &&
       psx_mod_read_word(GAME_MODE)==SURVIVAL && tekken3_ttt1_roster_enabled() && roster_count) {
        unsigned stage=psx_mod_read_word(STAGE_INDEX),mine=psx_mod_read_half(0x800add5c+(player^1)*2);
        unsigned pool[GUEST_MAX+1],n=0;
        int boss=stage>=SURVIVAL_BOSSES_FROM && survival_boss_one_in && !draw(survival_boss_one_in);
        int guest=!boss && stage>=SURVIVAL_GUESTS_FROM && survival_guest_one_in && !draw(survival_guest_one_in);
        for(unsigned k=0;k<roster_count && (boss || guest);k++) {
            int seen=0;
            for(unsigned r=0;r<4;r++)if(recent[r]==(int)k)seen=1;
            if(GUEST_ID+k!=mine && !seen && hidden_boss(k)==boss)pool[n++]=k;
        }
        if(guest && mine!=MOKUJIN && mokujin_unlocked()) {
            int seen=0;
            for(unsigned r=0;r<4;r++)if(recent[r]==(int)NO_GUEST)seen=1;
            if(!seen)pool[n++]=NO_GUEST;
        }
        if(n) {
            unsigned k=pool[draw(n)],id=k==NO_GUEST?MOKUJIN:GUEST_ID+k;
            psx_mod_write_half(0x800add5c+player*2,(uint16_t)id);
            recent[next_recent++%4]=(int)k;
            fprintf(stderr,"TTT1 characters: %s is the CPU's Survival opponent (stage %u)\n",fighter_name(id),stage+1);
        }
    }
    __real_func_8004F0E4(cpu);
}
/* Team Battle teams. 0x800B0808 builds both teams when the grid is left
 * (0x800B225C fills the places nobody picked): at 0x800AFA88 + 89 + 13 *
 * player, bytes 0..7 the members (ID * 4 + costume, 88 empty), +10 how many
 * the player picked by hand, +11 costume, +12 size. A CPU team picks
 * nothing; a human's Start with an incomplete team (the Random fill) leaves
 * the rest to the game, whose pool is the stock fighters but Mokujin (mask
 * 0x1F7FFF) and, in the CPU's case, never a guest. Right after 0x800B0808
 * returns, before the loading screen copies the first members to the
 * fighters (0x800ADD5C), this takes over the places the game filled:
 *  - a human's Random fill redraws each place over everything, guests (all
 *    of them, Devil, Angel and Unknown too) and Mokujin included, in
 *    proportion to the stock fighters left, so a place is as likely to be
 *    a guest as any one fighter is;
 *  - the CPU's team keeps its stock fighters, each place having a chance
 *    of 1 / TEAM_ONE_IN to be a guest (not Devil, Angel, Unknown) or
 *    Mokujin, at most TEAM_MAX such places.
 * No fighter is twice in either team; the costume stays. Every native left
 * in a filled place (the CPU's, a Random fill's) tosses its moves, Tekken 3
 * or TTT1, kept for the match (tekken3_native_moves_assign). Mokujin is
 * subject to his unlock. TEKKEN3_TEAM_GUESTS="one_in,max" sets the CPU's
 * rate (max 0 = never). */
enum { TEAM_BATTLE=2, TEAMS=0x800afa88+89, TEAM_STRIDE=13, TEAM_EMPTY=88, RANDOM_FILL_POOL=0x1f7fff };
extern int tekken3_native_moves_assign(unsigned slot,unsigned id,int ttt1);
static unsigned team_one_in=4,team_max=2;
static void team_tick(unsigned state) {
    static unsigned char written[2][8];
    static int built;
    static int configured;
    if(!configured) {
        configured=1;
        const char *e=getenv("TEKKEN3_TEAM_GUESTS");
        unsigned a,b;
        if(e && sscanf(e,"%u,%u",&a,&b)==2 && a){team_one_in=a;team_max=b;}
    }
    if(state==10){built=0;return;}
    if(state!=11 || psx_mod_read_word(GAME_MODE)!=TEAM_BATTLE || !tekken3_ttt1_roster_enabled())return;
    if(built){
        int same=1;
        for(unsigned p=0;p<2;p++)for(unsigned i=0;i<8;i++)if(psx_mod_read_byte(TEAMS+p*TEAM_STRIDE+i)!=written[p][i])same=0;
        if(same)return;
    }
    for(unsigned p=0;p<2;p++) {
        int human=psx_mod_read_half(0x800ae1f8+p*2)!=0;
        uint32_t team=TEAMS+p*TEAM_STRIDE;
        unsigned size=psx_mod_read_byte(team+12),chosen=human?psx_mod_read_byte(team+10):0;
        if(size<1 || size>8 || chosen>=size)continue;                    /* nothing left to the game */
        unsigned char members[8];
        for(unsigned i=0;i<8;i++)members[i]=psx_mod_read_byte(team+i);
        unsigned placed=0;
        for(unsigned i=chosen;i<size;i++) {
            if(members[i]==TEAM_EMPTY)continue;
            /* Who is in either team, this place left out. */
            unsigned stock_taken=0;
            unsigned char guest_taken[GUEST_MAX]={0};
            for(unsigned q=0;q<2;q++)for(unsigned j=0;j<8;j++) {
                uint32_t b=TEAMS+q*TEAM_STRIDE;
                unsigned m=(q==p && j==i)?TEAM_EMPTY:q==p?members[j]:psx_mod_read_byte(b+j);
                if(m==TEAM_EMPTY)continue;
                int g=tekken3_guest_character(m>>2);
                if(g>=0)guest_taken[g]=1;else if((m>>2)<32)stock_taken|=1u<<(m>>2);
            }
            unsigned extras[GUEST_MAX+1],n=0;
            for(unsigned k=0;k<roster_count;k++)
                if(!guest_taken[k] && (human || !hidden_boss(k)))extras[n++]=k;
            if(!(stock_taken>>MOKUJIN&1) && mokujin_unlocked())extras[n++]=NO_GUEST;
            unsigned stock_left=0;
            for(uint32_t pool=psx_mod_read_word(AVAILABLE)&RANDOM_FILL_POOL&~stock_taken;pool;pool&=pool-1)stock_left++;
            int swap;
            if(human)swap=n && draw(n+stock_left)<n;
            else swap=n && placed<team_max && !draw(team_one_in);
            if(!swap)continue;
            unsigned k=extras[draw(n)],id=k==NO_GUEST?MOKUJIN:GUEST_ID+k;
            members[i]=(unsigned char)(id*4+(members[i]&3));
            psx_mod_write_byte(team+i,members[i]);placed++;
            /* The loading screen has copied the first member already. */
            if(i==0){psx_mod_write_half(0x800add5c+p*2,(uint16_t)id);psx_mod_write_half(0x800add98+p*2,(uint16_t)(members[i]&3));}
            fprintf(stderr,"TTT1 characters: %s joins %s P%u's team (member %u)\n",fighter_name(id),
                    human?"Random fill, ":"the CPU's team, ",p+1,i+1);
        }
        for(unsigned i=chosen;i<size;i++) {
            unsigned id=members[i]>>2;
            if(members[i]==TEAM_EMPTY || id>=STOCK_FIGHTERS)continue;
            if(tekken3_native_moves_assign(p,id,(int)draw(2)))
                fprintf(stderr,"Native moves: P%u's %s fights on TTT1 moves (toss)\n",p+1,fighter_name(id));
        }
    }
    for(unsigned p=0;p<2;p++)for(unsigned i=0;i<8;i++)written[p][i]=psx_mod_read_byte(TEAMS+p*TEAM_STRIDE+i);
    built=1;
}
/* Guests as the CPU's Tekken Ball opponent. The grid overlay draws it
 * (0x800B4DC8, TIPS.md section 25): Gon, and nobody else, on a save's very
 * first match, then a rotation among the stock fighters, whose draw calls
 * 0x8004CE54 (return address 0x800B4EBC, s1 = the overlay's structure) and
 * stores ID * 4 + costume at s1 + 0x70, copies it to the CPU's choice and
 * calls 0x8004F0E4 (return 0x800B4848), all in one frame, before any
 * loading: there a guest takes that fighter's place one match in
 * BALL_ONE_IN, costume kept, in time for the loading screen's portrait.
 * Gon's first match does not draw, so is never touched; never
 * the player's fighter, nor Devil, Angel or Unknown (the game leaves Ogre
 * and True Ogre out too). The arena does not follow the fighter here.
 * TEKKEN3_BALL_GUESTS="one_in" overrides (0 = never). */
enum { BALL_DRAW_RETURN=0x800b4ebc, BALL_CHOICE=0x70 };
static unsigned ball_one_in=4;
extern void __real_func_8004CE54(CPUState*);
void __wrap_func_8004CE54(CPUState *cpu) {
    if((cpu->pc==0 || cpu->pc==0x8004ce54) && cpu->gpr[31]==BALL_DRAW_RETURN &&
       psx_mod_read_word(GAME_MODE)==TEKKEN_BALL)ball_choice=cpu->gpr[17]+BALL_CHOICE;
    __real_func_8004CE54(cpu);
}
static void ball_swap(unsigned player) {
    static int configured;
    if(!configured) {
        configured=1;
        const char *e=getenv("TEKKEN3_BALL_GUESTS");
        unsigned a;
        if(e && sscanf(e,"%u",&a)==1)ball_one_in=a;
    }
    uint32_t slot=ball_choice;ball_choice=0;
    unsigned drawn=psx_mod_read_word(slot),mine=psx_mod_read_half(0x800add5c+(player^1)*2);
    if(!ball_one_in || (drawn>>2)>=STOCK_FIGHTERS || draw(ball_one_in))return;
    unsigned pool[GUEST_MAX+1],n=0;
    for(unsigned k=0;k<roster_count;k++)if(GUEST_ID+k!=mine && !hidden_boss(k))pool[n++]=k;
    if(mine!=MOKUJIN && mokujin_unlocked())pool[n++]=NO_GUEST;
    if(!n)return;
    unsigned k=pool[draw(n)],id=k==NO_GUEST?MOKUJIN:GUEST_ID+k;
    psx_mod_write_word(slot,id*4+(drawn&3));
    psx_mod_write_half(0x800add5c+player*2,(uint16_t)id);
    portrait_reload(player);
    fprintf(stderr,"TTT1 characters: %s is the CPU's Tekken Ball opponent\n",fighter_name(id));
}
static void arena_tick(unsigned state) {
    if(!arena_pending)return;
    if(state==8){arena_pending=0;return;}
    psx_mod_write_half(ARENA,(uint16_t)arena_value);psx_mod_write_byte(ARENA_COPY,(uint8_t)arena_value);
    psx_mod_write_half(MUSIC,(uint16_t)music_value);psx_mod_write_byte(MUSIC_COPY,(uint8_t)music_value);
}
/* SLUS 0x8002D1DC clamps a character ID to the stock range for actor+0x16,
 * the key of the shared move headers and hit rules: "v0 = a0; if a0 >= 24
 * (21 in stock) v0 = 20". Every guest must keep 23 there, the key the guest
 * tables were built and verified with. The function's entry is not reached
 * through this wrapper, but its "return 20" block (0x8002D1F4) is, with the
 * original ID still in v0. */
void __wrap_func_8002D1DC(CPUState *cpu) {
    if(tekken3_ttt1_roster_enabled()) {
        if((cpu->pc==0 || cpu->pc==0x8002d1dc) && tekken3_guest_character((uint16_t)cpu->gpr[4])>=0)
            cpu->gpr[4]=GUEST_ID;
        else if(cpu->pc==0x8002d1f4 && tekken3_guest_character((uint16_t)cpu->gpr[2])>=0) {
            cpu->gpr[2]=GUEST_ID;cpu->pc=cpu->gpr[31];return;
        }
    }
    __real_func_8002D1DC(cpu);
}
