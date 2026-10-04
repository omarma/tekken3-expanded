/* A native fighter may fight on its TTT1 moveset (Paul's Turn Thruster...)
 * with its own Tekken 3 model, cries and name. At the character selector of
 * Arcade, VS, Time Attack, Survival and Practice, R1 switches the native
 * under a player's cursor between its Tekken 3 and Tekken Tag Tournament
 * moves, shown on the MOVESET card under the selector's clock; the choice
 * holds from the confirmation to the fight. Guests and natives without TTT1
 * moves have no card.
 *
 * The TTT1 moves of the natives are <Name>-TTT1-combat.jmv, -tables.jst,
 * -idle.poses, -sfx.jus in the TTT1 catalogue, listed in natives.txt: one
 * "<T3 character ID> <key> <TTT1 moveset key>" per line
 * (tools/ttt1_stage_roster.py). In the fight, motion mode 4
 * (tekken3_ttt1_mod.c) runs them through the guests' combat adapter. */
#include "mod_plugins.h"
#include "psx_runtime.h"
#include "tekken3_ttt1_assets.h"
#include "gpu.h"
#include "memcard.h"
#include "tekken3_moveset_draw.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

extern int tekken3_native_moves_set(unsigned player,unsigned id,const char *key,unsigned moveset);
extern unsigned tekken3_native_moves_id(unsigned player);
extern int tekken3_devil_jin_requested(unsigned player);

enum { SCREEN=0x800ae204, PHASE=0x800ae224, MODE=0x800afa88, TEAM_BATTLE=2,
       PRACTICE=5, SELECT=9, LOADING=11, MENU=4, ABSENT=22, CHOOSING=1,
       CHOOSING_CPU=3, NATIVES=21 };
/* Pad bits, active low. */
enum { PAD_SELECT=0x0001, PAD_START=0x0008, PAD_RIGHT=0x0020, PAD_LEFT=0x0080,
       PAD_TRIANGLE=0x1000, PAD_CIRCLE=0x2000, PAD_CROSS=0x4000, PAD_SQUARE=0x8000,
       PICK=PAD_START|PAD_TRIANGLE|PAD_CIRCLE|PAD_CROSS|PAD_SQUARE,
       CARD_KEYS=PICK|PAD_SELECT|PAD_LEFT|PAD_RIGHT, INJECT_POLLS=3 };

/* A native's other movesets, one per line of natives.txt: its source (the
 * optional fourth column, "ttt1" without) is a value of the Options menu's
 * CPU MOVESET row and a share of the CPU's draw. */
enum { MAX_ALT=4, MAX_SOURCES=4 };
static char sources[MAX_SOURCES][24];
static unsigned source_count;
static struct { unsigned count;struct { char key[32];unsigned moveset;int source; } alt[MAX_ALT]; } natives[NATIVES];
static int source_of(const char *name) {
    for(unsigned i=0;i<source_count;i++)if(!strcmp(sources[i],name))return (int)i;
    if(source_count>=MAX_SOURCES)return -1;
    snprintf(sources[source_count],sizeof sources[0],"%s",name);
    return (int)source_count++;
}
static void read_natives(void) {
    static int read;
    if(read)return;read=1;
    const char *root=tekken3_ttt1_asset_root();
    char path[4096];
    if(!root || snprintf(path,sizeof path,"%s/natives.txt",root)>=(int)sizeof path)return;
    FILE *f=fopen(path,"rb");if(!f)return;
    char line[96];unsigned count=0;
    while(fgets(line,sizeof line,f)) {
        unsigned id,moveset;char key[32],source[24]="ttt1";
        int fields=sscanf(line,"%u %31s %u %23s",&id,key,&moveset,source);
        if(fields<3 || id>=NATIVES || natives[id].count>=MAX_ALT)continue;
        /* The combat file must be there: a line without it is left out. */
        char name[32],tag[24];snprintf(name,sizeof name,"%s",key);snprintf(tag,sizeof tag,"%s",source);
        if(name[0]>='a' && name[0]<='z')name[0]=(char)(name[0]-'a'+'A');
        for(char *c=tag;*c;c++)if(*c>='a' && *c<='z')*c=(char)(*c-'a'+'A');
        char combat[4096];FILE *c;
        if(snprintf(combat,sizeof combat,"%s/%s-%s-combat.jmv",root,name,tag)>=(int)sizeof combat ||
           !(c=fopen(combat,"rb")))continue;
        fclose(c);
        int src=source_of(source);
        if(src<0)continue;
        unsigned at=natives[id].count++;
        snprintf(natives[id].alt[at].key,sizeof natives[id].alt[at].key,"%s",key);
        natives[id].alt[at].moveset=moveset;natives[id].alt[at].source=src;count++;
    }
    fclose(f);
    fprintf(stderr,"Native moves: %u other movesets for native fighters, %u source(s)\n",count,source_count);
}
int tekken3_native_moves_available(unsigned id) {
    read_natives();
    return id<NATIVES && natives[id].count;
}

/* Arcade, VS, Team Battle (a card for each member picked), Time Attack,
 * Survival, Practice. Tekken Force and Tekken Ball keep the game's moves. */
static int active(void) {
    return psx_mod_read_word(MODE)<=PRACTICE;
}
/* Test benches pick natives at the grid without a card:
 * TEKKEN3_NATIVE_MOVES=0 keeps them on T3 moves, =1 puts every native in
 * the fight on its TTT1 moves (the CPU's too). Unset, the card asks. */
static int bench(void) {
    static int value=-2;
    if(value==-2) {
        const char *e=getenv("TEKKEN3_NATIVE_MOVES");
        value=e && *e?(*e!='0'):-1;
    }
    return value;
}
/* Each slot's choice, kept from one pick to the next of the same session. */
static int want[2];
static int wants(unsigned p){return want[p];}
/* card[slot]: the button that picked the native while its card is open, 0
 * when closed. inject/injecting: that button, handed to the game for a few
 * polls once the card is taken. hold[pad]: the card's buttons stay away from
 * the game until that pad lets go of them. picked[slot][fighter]: the moves
 * a card was taken with for that fighter (-1 none), one per member of a
 * team, kept from the pick to the fights. */
static uint16_t card[2],injecting[2],hold[2];
static int inject[2];
static signed char picked[2][NATIVES];
static void forget_picks(void){memset(picked,-1,sizeof picked);}

/* The Arcade grid (Arcade, Time Attack, Survival, Practice): screen 9,
 * player blocks at 0x8011864C + 0x7C * player (state, cursor's fighter). */
static int arcade_grid(void) {
    return psx_mod_read_word(SCREEN)==SELECT && psx_mod_read_word(0x8010ff4c)==0x27bdffd0 &&
           psx_mod_read_half(PHASE)<=1;
}
/* VS BATTLE SELECT: screen 10, a 7 x 3 grid, player blocks at 0x800B8D70 +
 * 172 * player: +0 state (3 choosing, 4 chosen, 12 handicap taken), +8
 * column, +12 row, +56 fighter * 4 + costume once chosen. The fighter
 * under the cursor is the grid table's (cell y * 7 + x). */
enum { VS_BLOCKS=0x800b8d70, VS_STRIDE=172, VS_CHOOSING=3, TEAM_SIZE=1, TEAM_MEMBERS=2 };
extern unsigned tekken3_ttt1_grid_character(unsigned cell);
            /* Hwoarang Dr.B Bryan Gon Gun-Jack Anna Eddy */
static int vs_grid_open(void) {
    unsigned s=psx_mod_read_word(VS_BLOCKS);
    return psx_mod_read_word(SCREEN)==10 && psx_mod_read_word(MODE)==1 && (s==3 || s==4 || s==12);
}
/* TEAM BATTLE SELECT: the same screen and grid; each player sets the team
 * size (state 1), then picks its members (state 2), 10 once the team is
 * full. */
enum { TEAM_FULL=10 };
static int team_grid_open(void) {
    unsigned s=psx_mod_read_word(VS_BLOCKS);
    return psx_mod_read_word(SCREEN)==10 && psx_mod_read_word(MODE)==TEAM_BATTLE && s>=1 && s<=TEAM_FULL;
}
static int grid10_open(void){return vs_grid_open() || team_grid_open();}
static int selector_open(void){return arcade_grid() || grid10_open();}
static unsigned cursor_character(unsigned p) {
    if(!grid10_open())return psx_mod_read_word(0x80118668+p*0x7c);
    /* The grid's own table (tekken3_ttt1_roster.c): its Tag page holds the
     * guests in the same cells. */
    uint32_t block=VS_BLOCKS+p*VS_STRIDE;
    unsigned x=psx_mod_read_word(block+8),y=psx_mod_read_word(block+12);
    return x<7 && y<4?tekken3_ttt1_grid_character(y*7+x):ABSENT;
}
/* Practice: once player 1 has chosen, player 1's pad picks the CPU in player
 * 2's block, whose state is then 3 (src/tekken3_ttt1_roster.c). */
static unsigned state(unsigned p){return psx_mod_read_word(0x8011864c+p*0x7c);}
static int confirmed(unsigned p) {
    if(vs_grid_open())return psx_mod_read_word(VS_BLOCKS+p*VS_STRIDE)!=VS_CHOOSING;
    if(team_grid_open())return psx_mod_read_word(VS_BLOCKS+p*VS_STRIDE)!=2;
    return state(p)!=CHOOSING && state(p)!=CHOOSING_CPU;
}
static unsigned driven_by(unsigned pad) {
    return !grid10_open() && pad==0 && confirmed(0) && state(1)==CHOOSING_CPU?1:pad;
}

/* What the MOVESET card shows for slot p: -1 nothing, else 1 for the TTT1
 * moves, 0 for Tekken 3's. */
static int card_state(unsigned p) {
    if(p>1 || !card[p] || !active() || !selector_open())return -1;
    return wants(p);
}

static void close_cards(void){card[0]=card[1]=0;inject[0]=inject[1]=0;}
uint16_t tekken3_native_moves_input(int player,uint16_t buttons) {
    static uint16_t previous[2]={0xffff,0xffff};
    if(player<0 || player>1)return buttons;
    unsigned p=(unsigned)player;
    uint16_t edges=previous[p]&(uint16_t)~buttons;previous[p]=buttons;
    if(bench()>=0 || !active() || !selector_open()){close_cards();hold[p]=0;return buttons;}
    unsigned slot=driven_by(p);
    if(inject[slot]>0) {                           /* the pick, as pressed */
        inject[slot]--;
        return (uint16_t)~injecting[slot];
    }
    if(card[slot] && confirmed(slot)) {            /* the clock picked for it */
        fprintf(stderr,"Native moves: P%u picked by the clock, %s moves\n",slot+1,wants(slot)?"TTT1":"T3");
        unsigned id=cursor_character(slot);
        if(id<NATIVES)picked[slot][id]=(signed char)wants(slot);
        card[slot]=0;
    }
    /* Jin confirmed with both punches is Devil Jin (tekken3_ttt1_selector.c,
     * on the raw pad): his own moves, no card; the pick goes to the game. */
    if(card[slot] && tekken3_devil_jin_requested(p)) {
        unsigned id=cursor_character(slot);
        if(id<NATIVES)picked[slot][id]=0;
        injecting[slot]=card[slot];inject[slot]=INJECT_POLLS;card[slot]=0;hold[p]=CARD_KEYS;
        fprintf(stderr,"Native moves: P%u picks Devil Jin, no card\n",slot+1);
        return 0xffff;
    }
    if(card[slot]) {
        if(edges&(PAD_LEFT|PAD_RIGHT)) {
            want[slot]=!wants(slot);
            fprintf(stderr,"Native moves: P%u highlights %s moves\n",slot+1,want[slot]?"TTT1":"T3");
        }
        if(edges&(PAD_CROSS|PAD_START)) {
            unsigned id=cursor_character(slot);
            if(id<NATIVES)picked[slot][id]=(signed char)wants(slot);
            injecting[slot]=card[slot];inject[slot]=INJECT_POLLS;card[slot]=0;hold[p]=CARD_KEYS;
            fprintf(stderr,"Native moves: P%u takes %s moves\n",slot+1,wants(slot)?"TTT1":"T3");
        } else if(edges&(PAD_CIRCLE|PAD_SELECT)) {
            card[slot]=0;hold[p]=CARD_KEYS;
            fprintf(stderr,"Native moves: P%u back to the grid\n",slot+1);
        }
        return 0xffff;                             /* the grid stays still */
    }
    hold[p]&=(uint16_t)~buttons;                   /* held keys, still down */
    /* Start with Select held leaves the mode: the game's, not a pick. */
    int leaving=!(buttons&PAD_SELECT) && (edges&PAD_START);
    if((uint16_t)~buttons&PAD_SQUARE && (uint16_t)~buttons&PAD_TRIANGLE)leaving=1;   /* Devil Jin */
    /* Start picks a costume only for a native with a third costume (its bit
     * in the unlock mask, 0x8010DAE0): the game ignores it for the others,
     * and so does the card. In Team Battle Start is never a pick: the game
     * reads it first (0x80053968) and draws a random team; triangle takes
     * the third costume there. */
    uint16_t picks=edges&PICK;
    unsigned under=cursor_character(slot);
    if(team_grid_open() || (under<NATIVES && !(psx_mod_read_word(0x80097ef4)>>(under&31)&1)))
        picks&=(uint16_t)~PAD_START;
    if(!confirmed(slot) && picks && !leaving && tekken3_native_moves_available(under)) {
        uint16_t pick=picks;
        card[slot]=(uint16_t)(pick&-pick);         /* one button: its costume */
        hold[p]=CARD_KEYS;
        fprintf(stderr,"Native moves: P%u opens the MOVESET card\n",slot+1);
        return 0xffff;
    }
    return buttons|hold[p];
}

/* A native the game drew for a Team Battle team (the player's Random fill,
 * the CPU's team) takes the moves the caller tossed for it, kept for the
 * match like a card's pick. Returns 1 when it fights on its TTT1 moves, 0
 * on Tekken 3's (also when it has no TTT1 moves, or a test bench decides). */
int tekken3_native_moves_assign(unsigned slot,unsigned id,int ttt1) {
    if(slot>1 || id>=NATIVES)return 0;
    if(bench()>=0)return bench();
    ttt1=ttt1 && tekken3_native_moves_available(id);
    picked[slot][id]=(signed char)ttt1;
    return ttt1;
}

/* The CPU's moves. In the modes where the CPU has no card (Arcade, Time
 * Attack, Survival, Team Battle; Practice lets the player pick the CPU's, VS
 * has none), a native with other movesets imported draws the ones it fights
 * on, once per fight, each choice with the same chance (its own Tekken 3
 * moves are one): the Options menu's CPU MOVESET row sets ORIGINAL, one
 * source, or RANDOM. TEKKEN3_CPU_MOVESET (original, random or a source)
 * overrides the menu, TEKKEN3_CPU_MOVESET_SEED fixes the draw (benches). */
enum { OPTIONS=5, DESCRIPTOR=0x800ead78, ROWS=0x800b908c, ROW_COUNT=9, ROW_SIZE=20,
       MENU_ITEMS=10, CPU_MODES=0x1d };
static uint64_t draw_state;
static int cpu_setting=-2;                 /* -1 original, 0.. a source, -2 not read, RANDOM below */
enum { RANDOM=99 };
static uint32_t menu_byte,menu_rows;
static void setting_path(char *out,size_t size) {
    const char *card=NULL;out[0]=0;
    if(memcard_debug_info(0,&card,NULL,NULL,NULL) || !card || !*card)return;
    const char *slash=strrchr(card,'/'),*back=strrchr(card,'\\');
    if(back && (!slash || back>slash))slash=back;
    int n=slash?(int)(slash-card):1;
    snprintf(out,size,"%.*s/ttt1-cpu-moveset.txt",n,slash?card:".");
}
static int parse_setting(const char *word) {
    if(!strcmp(word,"original"))return -1;
    if(!strcmp(word,"random"))return RANDOM;
    for(unsigned i=0;i<source_count;i++)if(!strcmp(word,sources[i]))return (int)i;
    return RANDOM;
}
static const char *setting_word(int value) {
    return value==-1?"original":value==RANDOM?"random":sources[value];
}
static int menu_value(void) {                  /* the menu's byte: 0 original, 1.. sources, then random */
    unsigned v=psx_mod_read_byte(menu_byte);
    return v==0?-1:v<=source_count?(int)v-1:RANDOM;
}
static void saved_setting(int store,int *value) {
    char path[4096];setting_path(path,sizeof path);
    if(!path[0])return;
    if(store) {
        FILE *f=fopen(path,"wb");if(!f)return;
        fprintf(f,"%s\n",setting_word(*value));fclose(f);
    } else {
        FILE *f=fopen(path,"rb");char word[32]="";
        if(f){if(fscanf(f,"%31s",word)==1)*value=parse_setting(word);fclose(f);}
    }
}
static int cpu_choice_setting(void) {
    read_natives();
    if(cpu_setting==-2) {
        cpu_setting=RANDOM;
        const char *e=getenv("TEKKEN3_CPU_MOVESET");
        if(e && *e)cpu_setting=parse_setting(e);
        else saved_setting(0,&cpu_setting);
        const char *seed=getenv("TEKKEN3_CPU_MOVESET_SEED");
        tekken3_moveset_seed(&draw_state,seed && *seed?strtoull(seed,NULL,0):(uint64_t)time(NULL)*1000003u+(uint64_t)clock()+(uint64_t)(uintptr_t)&draw_state);
    }
    return cpu_setting;
}
/* The alternative a CPU fighter fights on: -1 its own Tekken 3 moves. */
static int draw_alternative(unsigned id) {
    unsigned n=natives[id].count;
    int setting=cpu_choice_setting();
    if(!n || setting==-1)return -1;
    if(setting!=RANDOM) {
        for(unsigned k=0;k<n;k++)if(natives[id].alt[k].source==setting)return (int)k;
        return -1;
    }
    return (int)tekken3_moveset_draw(n+1,&draw_state)-1;
}
static int cpu_slot(unsigned p) {
    unsigned mode=psx_mod_read_word(MODE);
    return !psx_mod_read_half(0x800ae1f8+p*2) && mode<PRACTICE;
}

/* The CPU MOVESET row: the game's GAME OPTION page is a table of ten
 * 20-byte entries (nine rows, then EXIT) named by a page descriptor
 * (DESCRIPTOR: entries, title, item count); the table is followed by other
 * data, so a copy with one row more, before EXIT, is made in guest memory and
 * the descriptor pointed at it. Rows are
 * copied again every frame (the difficulty mod edits its row in the original). */
static uint32_t labels_for_menu(void) {
    char label[MAX_SOURCES+2][32];unsigned n=0;
    snprintf(label[n++],sizeof label[0],"ORIGINAL");
    for(unsigned i=0;i<source_count;i++) {
        if(!strcmp(sources[i],"ttt1"))snprintf(label[n],sizeof label[0],"TEKKEN TAG TOURNAMENT");
        else {
            snprintf(label[n],sizeof label[0],"%s",sources[i]);
            for(char *c=label[n];*c;c++){if(*c>='a' && *c<='z')*c=(char)(*c-'a'+'A');if(*c=='_')*c=' ';}
        }
        n++;
    }
    snprintf(label[n++],sizeof label[0],"RANDOM");
    uint32_t size=n*4+16;
    for(unsigned i=0;i<n;i++)size+=(uint32_t)strlen(label[i])+1;
    uint32_t list=psx_mod_alloc_guest_memory(size,4);
    if(!list)return 0;
    uint32_t text=list+n*4;
    for(unsigned i=0;i<n;i++) {
        psx_mod_write_word(list+i*4,text);
        for(const char *c=label[i];;c++){psx_mod_write_byte(text++,(uint8_t)*c);if(!*c)break;}
    }
    return list;
}
static void options_row(void) {
    read_natives();
    if(!source_count)return;
    uint32_t rows=psx_mod_read_word(DESCRIPTOR);
    if(rows!=ROWS && rows!=menu_rows)return;
    if(rows==ROWS && psx_mod_read_word(DESCRIPTOR+8)!=MENU_ITEMS)return;
    /* The table of the game's overlay: first row the difficulty, last the
     * speaker (value bytes 0x80097F06 and 0x80097F04). */
    if(psx_mod_read_word(ROWS)!=0x80097f06 || psx_mod_read_word(ROWS+(ROW_COUNT-1)*ROW_SIZE)!=0x80097f04)return;
    if(!menu_rows) {
        uint32_t list=labels_for_menu();
        menu_rows=psx_mod_alloc_guest_memory((ROW_COUNT+2)*ROW_SIZE,4);
        menu_byte=psx_mod_alloc_guest_memory(4,4);
        uint32_t name=psx_mod_alloc_guest_memory(16,4);
        if(!list || !menu_rows || !menu_byte || !name){menu_rows=0;return;}
        const char *title="CPU MOVESET";
        for(unsigned i=0;i<=strlen(title);i++)psx_mod_write_byte(name+i,(uint8_t)title[i]);
        int saved=cpu_choice_setting();
        unsigned value=saved==-1?0:saved==RANDOM?source_count+1:(unsigned)saved+1;
        psx_mod_write_word(menu_byte,value);
        uint32_t row=menu_rows+ROW_COUNT*ROW_SIZE;
        psx_mod_write_word(row,menu_byte);
        psx_mod_write_word(row+4,name);
        psx_mod_write_word(row+8,list);
        psx_mod_write_word(row+12,1u|(source_count+2)<<8);       /* as BGM SELECT: one byte, its values */
        psx_mod_write_word(row+16,((uint32_t)CPU_MODES<<16)|2u);  /* modes lit in the box on the right */
        fprintf(stderr,"Native moves: CPU MOVESET row added to GAME OPTION (%u values)\n",source_count+2);
    }
    /* Entry 9 of the game's table is EXIT: it goes after our row. */
    for(unsigned i=0;i<ROW_COUNT*ROW_SIZE/4;i++) {
        uint32_t w=psx_mod_read_word(ROWS+i*4);
        if(psx_mod_read_word(menu_rows+i*4)!=w)psx_mod_write_word(menu_rows+i*4,w);
    }
    for(unsigned i=0;i<ROW_SIZE/4;i++) {
        uint32_t w=psx_mod_read_word(ROWS+ROW_COUNT*ROW_SIZE+i*4);
        uint32_t at=menu_rows+(ROW_COUNT+1)*ROW_SIZE+i*4;
        if(psx_mod_read_word(at)!=w)psx_mod_write_word(at,w);
    }
    if(rows!=menu_rows) {
        psx_mod_write_word(DESCRIPTOR,menu_rows);
        psx_mod_write_word(DESCRIPTOR+8,MENU_ITEMS+1);
    }
    /* The player's choice, kept beside the memory card. */
    int shown=menu_value();
    if(shown!=cpu_setting && !getenv("TEKKEN3_CPU_MOVESET")){cpu_setting=shown;saved_setting(1,&cpu_setting);}
}

/* The moves a player fights on, chosen for character `id`: a slot whose
 * card was taken for this fighter fights on the moves it chose, a CPU slot
 * on the moves it drew (once per fighter it loads); any other (a guest)
 * keeps its own. */
static int drawn_id[2]={-1,-1},drawn_alt[2],chosen_id[2]={-1,-1};
static void choose(unsigned p,unsigned id) {
    int alt=-1;
    if(bench()>=0)alt=bench() && id<NATIVES && natives[id].count?0:-1;
    else if(id<NATIVES && cpu_slot(p)) {
        if(drawn_id[p]!=(int)id) {
            drawn_id[p]=(int)id;drawn_alt[p]=draw_alternative(id);
            if(natives[id].count)
                fprintf(stderr,"Native moves: CPU P%u fighter %u draws %u choice(s) -> %s\n",p+1,id,natives[id].count+1,
                        drawn_alt[p]<0?"T3":sources[natives[id].alt[drawn_alt[p]].source]);
        }
        alt=drawn_alt[p];
    } else if(id<NATIVES && picked[p][id]==1 && natives[id].count)alt=0;
    if(tekken3_devil_jin_requested(p))alt=-1;      /* his own moves */
    if(active() && alt>=0)
        tekken3_native_moves_set(p,id,natives[id].alt[alt].key,natives[id].alt[alt].moveset);
    else tekken3_native_moves_set(p,0,NULL,0);
    chosen_id[p]=(int)id;
}
/* A fighter reloaded in the fight, without a loading screen (0x8002A40C:
 * True Ogre after Ogre's cutscene, our endings' partner): the choice made
 * for the one it replaces is made again for it, before its moves load. */
void tekken3_native_moves_reload(unsigned p,unsigned id) {
    if(p>1 || (int)id==chosen_id[p])return;
    drawn_id[p]=-1;
    choose(p,id);
}

/* The loading screen names the fighters (0x800ADD5C + 2 * player). */
void tekken3_native_moves_tick(void) {
    unsigned screen=psx_mod_read_word(SCREEN);
    /* A new visit of a selector starts without picks. */
    static int was_open;
    int open=selector_open();
    if(open && !was_open)forget_picks();
    was_open=open;
    /* The CPU draws once per loading of a fight. */
    if(screen!=LOADING)drawn_id[0]=drawn_id[1]=-1;
    if(screen==OPTIONS)options_row();
    if(screen==MENU) {
        for(unsigned p=0;p<2;p++){want[p]=0;tekken3_native_moves_set(p,0,NULL,0);chosen_id[p]=-1;}
        forget_picks();
        close_cards();
        return;
    }
    if(screen!=LOADING)return;
    for(unsigned p=0;p<2;p++)choose(p,psx_mod_read_half(0x800add5c+p*2));
}

/* The MOVESET card, drawn by the game's GPU over the top of the portrait
 * of the player who chooses: a dark band, MOVESET small, then TEKKEN 3 or
 * TEKKEN TAG / TOURNAMENT in the selector's own title font (the letters of
 * PRACTICE!), between two arrows that sway, all in the colour of that
 * player's cursor frame.
 *
 * The title font: page (832,0) 4 bpp, palette (336,505), cells of 14 x 24
 * from u 172, six to a row: 1..9, A..Z, !. The game draws it every 13 px.
 * Its letters run from (248,168,0) down to darker oranges with a dark
 * outline: a sprite's colour multiplies them (128 = as is), which tints the
 * letters and keeps the outline. The cursor frames' palettes (row 498):
 * player 1 red (512,498) from (248,136,96) to (232,0,0), player 2 yellow
 * (528,498) from (248,232,96) to (232,144,0), the CPU chosen in Practice
 * green (656,498) from (144,232,120) to (48,152,16). */
enum { FONT_PAGE=832/64, FONT_CLUT=(505<<6)|(336/16), FONT_U=172, GLYPH_W=14, GLYPH_H=24,
       ADVANCE=13, CARD_TOP=24, VS_CARD_TOP=392, TEAM_CARD_TOP=345, CARD_H=56, CARD_W=136, OUTLINE=0x101010, PACKET_WORDS=255 };
/* The middle of each portrait (33..159, 209..335). In native 16:9 the
 * Arcade grid's own packets get a wide layout that takes the portraits to
 * the edges by the reveal (half the growth) per side; ours are only
 * centred, so they move by that much themselves. */
static int portrait_x(unsigned p) {
    /* VS BATTLE SELECT keeps its 4:3 layout in 16:9, centred like ours. */
    if(vs_grid_open())return p?283:86;             /* under the small portraits */
    /* Team Battle: over the player's team panel (13..155, 213..355), which
     * the 16:9 layout takes to the edges like the Arcade grid's portraits. */
    if(team_grid_open()) {
        int reveal=ws_native_wide_active()?ws_nw_extra()/2:0;
        return p?284+reveal:84-reveal;
    }
    int reveal=ws_native_wide_active()?ws_nw_extra()/2:0;
    return p?272+reveal:96-reveal;
}
typedef struct { uint32_t tint,arrow; } Colours;   /* 0xBBGGRR */
static const Colours colours[3]={
    {0x00317c,0x3040f0},                           /* player 1: (240,64,48) */
    {0x009880,0x38c8f8},                           /* player 2: (248,200,56) */
    {0x009236,0x48c068}};                          /* the CPU: (104,192,72) */
static int glyph(char c) {
    if(c>='1' && c<='9')return c-'1';
    if(c>='A' && c<='Z')return 9+c-'A';
    return c=='!'?35:-1;
}
static uint32_t xy(int x,int y){return ((uint32_t)(y&0xffff)<<16)|(uint32_t)(x&0xffff);}
/* u is 8 bits: the last column's right edge (256) stops at 255. */
static uint32_t uv(int i,int du,int dv) {
    int u=FONT_U+i%6*GLYPH_W+du;
    return (uint32_t)(u>255?255:u)|(uint32_t)(i/6*GLYPH_H+dv)<<8;
}

/* A card's primitives, in as many linked packets as they need (a packet
 * holds 255 words at most). Each primitive asks room() for its words. */
typedef struct { uint32_t head,at,end;unsigned words; } Packet;
static void begin(Packet *k,uint32_t base,uint32_t bytes){k->head=base;k->at=base+4;k->end=base+bytes;k->words=0;}
static void room(Packet *k,unsigned n) {
    if(k->words+n<=PACKET_WORDS || k->at+4+n*4>k->end)return;
    psx_mod_write_word(k->head,(uint32_t)k->words<<24|(k->at&0xffffff));
    k->head=k->at;k->at+=4;k->words=0;
}
static void put(Packet *k,uint32_t word){if(k->at<k->end){psx_mod_write_word(k->at,word);k->at+=4;k->words++;}}
static uint32_t finish(Packet *k,uint32_t base,uint32_t link) {
    psx_mod_write_word(k->head,(uint32_t)k->words<<24|link);
    return base&0xffffff;
}
/* A line of the font centred on cx, scaled by num/den, tinted, in the
 * title's orange palette or (WHITE_CLUT) the white one of the VS names. */
enum { WHITE_CLUT=(505<<6)|(352/16) };
static void text_in(Packet *k,const char *s,int cx,int y,int num,int den,uint32_t tint,uint32_t clut) {
    int n=(int)strlen(s),advance=ADVANCE*num/den,w=GLYPH_W*num/den,h=GLYPH_H*num/den;
    int x=cx-(n*advance+(w-advance))/2;
    for(;*s;s++,x+=advance) {
        int i=glyph(*s);
        if(i<0)continue;
        room(k,9);
        put(k,0x2c000000|tint);                    /* textured quad, tinted */
        put(k,xy(x,y));put(k,uv(i,0,0)|clut<<16);
        put(k,xy(x+w,y));put(k,uv(i,GLYPH_W,0)|(uint32_t)FONT_PAGE<<16);
        put(k,xy(x,y+h));put(k,uv(i,0,GLYPH_H));
        put(k,xy(x+w,y+h));put(k,uv(i,GLYPH_W,GLYPH_H));
    }
}
static void text(Packet *k,const char *s,int cx,int y,int num,int den,uint32_t tint) {
    text_in(k,s,cx,y,num,den,tint,FONT_CLUT);
}
static void triangle(Packet *k,uint32_t colour,int x0,int y0,int x1,int y1,int x2,int y2) {
    room(k,4);put(k,0x20000000|colour);put(k,xy(x0,y0));put(k,xy(x1,y1));put(k,xy(x2,y2));
}
/* An arrow, its tip at x pointing left (dir>0) or right (dir<0), outlined. */
static void arrow(Packet *k,int x,int y,int dir,uint32_t colour) {
    triangle(k,OUTLINE,x-2*dir,y,x+10*dir,y-9,x+10*dir,y+9);
    triangle(k,colour,x,y,x+8*dir,y-6,x+8*dir,y+6);
}
static void card_packet(Packet *k,unsigned p,int ttt1,unsigned frame) {
    const Colours *c=&colours[p && !grid10_open() && state(1)==CHOOSING_CPU?2:p];
    /* VS: under the small portrait (y 325..385). */
    int cx=portrait_x(p),top=vs_grid_open()?VS_CARD_TOP:team_grid_open()?TEAM_CARD_TOP:CARD_TOP;
    room(k,4);
    put(k,0xe1000600|FONT_PAGE);                   /* semi-transparency B/2 + F/2 */
    put(k,0x62000000);put(k,xy(cx-CARD_W/2,top));put(k,xy(CARD_W,CARD_H));
    int t=(int)(frame%60),sway=(t<30?t:60-t)/8;    /* out and back once a second */
    arrow(k,cx-CARD_W/2+4-sway,top+36,1,c->arrow);
    arrow(k,cx+CARD_W/2-4+sway,top+36,-1,c->arrow);
    text(k,"MOVESET",cx,top+4,1,2,c->tint);
    if(ttt1){text(k,"TEKKEN TAG",cx,top+18,3,4,c->tint);text(k,"TOURNAMENT",cx,top+36,3,4,c->tint);}
    else text(k,"TEKKEN 3",cx,top+27,3,4,c->tint);
}

/* The CHARACTER SELECT card: the page on screen, TEKKEN 3 or TEKKEN TAG
 * TOURNAMENT, between the triggers that switch it, L2 and R2, drawn like
 * the COMMAND LIST's buttons (dark, a light grey rim, white label). Centred:
 * at the top of the Arcade grid (under the MOVESET cards while one is open
 * over a portrait), at the bottom of VS BATTLE SELECT and the other grids of
 * its kind (Team Battle, Tekken Ball), where the MOVESET cards take that
 * room: none while one is open. Shown while a player still browses the
 * grid; gone once all have chosen, and for the player whose MOVESET card is
 * open. */
enum { PAGE_W=224, PAGE_H=38, PAGE_TOP=22, PAGE_UNDER_CARDS=CARD_TOP+CARD_H+4, PAGE_GRID_TOP=428, CENTRE_X=184,
       RIM=0xc8c8c8, BUTTON=0x202020, TRIGGER_W=22, TRIGGER_H=20 };
extern int tekken3_ttt1_selector_page(void);
static void flat(Packet *k,uint32_t colour,int x,int y,int w,int h) {
    room(k,3);put(k,0x60000000|colour);put(k,xy(x,y));put(k,xy(w,h));
}
/* A trigger as on the pad: an arch on straight sides, flat at the base,
 * its name low on it. Rows of the arch, then the sides in one piece. */
static void arch(Packet *k,uint32_t colour,int cx,int y,int r,int h) {
    for(int j=0;j<r;j++) {
        int d=r-j,half=0;
        while((half+1)*(half+1)<=r*r-d*d)half++;
        if(half)flat(k,colour,cx-half,y+j,2*half,1);
    }
    flat(k,colour,cx-r,y+r,2*r,h-r);
}
static void trigger(Packet *k,int x,int y,const char *label) {
    int cx=x+TRIGGER_W/2,r=TRIGGER_W/2;
    arch(k,RIM,cx,y,r,TRIGGER_H);
    arch(k,BUTTON,cx,y+1,r-1,TRIGGER_H-2);
    text_in(k,label,cx,y+TRIGGER_H-13,1,2,0x808080,WHITE_CLUT);
}
/* A player still browsing the grid. On the Arcade grid, only once its
 * portrait shows (0x80118660, 22 before): the TEKKEN 3 logo that comes
 * first is a loading screen, and a card drawn over it held it there. */
static int browsing(unsigned p) {
    if(card[p])return 0;
    /* Team Battle: the team size in state 1, then the members in state 2;
     * R2 / L2 switch the page in both. */
    if(psx_mod_read_word(SCREEN)==10) {
        unsigned state=psx_mod_read_word(VS_BLOCKS+p*VS_STRIDE);
        return psx_mod_read_word(MODE)==TEAM_BATTLE?state==TEAM_SIZE || state==TEAM_MEMBERS:state==VS_CHOOSING;
    }
    return arcade_grid() && cursor_character(p)!=ABSENT && !confirmed(p) &&
           psx_mod_read_word(0x80118660+p*0x7c)!=ABSENT;
}
static int page_state(void) {
    int page=tekken3_ttt1_selector_page();
    if(psx_mod_read_word(SCREEN)==10 && (card[0] || card[1]))return -1;
    return page>=0 && (browsing(0) || browsing(1))?page:-1;
}
static void page_packet(Packet *k,int page) {
    int grid=psx_mod_read_word(SCREEN)==10,cards=card_state(0)>=0 || card_state(1)>=0;
    /* VS: a player who has chosen sets the handicap on a LIFE bar at the
     * bottom; the card goes up to the title while the other one browses. */
    int handicap=vs_grid_open() && (psx_mod_read_word(VS_BLOCKS)!=VS_CHOOSING ||
                                    psx_mod_read_word(VS_BLOCKS+VS_STRIDE)!=VS_CHOOSING);
    /* Team Battle: while a player sets the team size, its panel takes the
     * bottom: the card goes up to the title too. */
    if(grid && psx_mod_read_word(MODE)==TEAM_BATTLE &&
       (psx_mod_read_word(VS_BLOCKS)==TEAM_SIZE || psx_mod_read_word(VS_BLOCKS+VS_STRIDE)==TEAM_SIZE))handicap=1;
    int top=grid && !handicap?PAGE_GRID_TOP:grid || !cards?PAGE_TOP:PAGE_UNDER_CARDS,left=CENTRE_X-PAGE_W/2;
    room(k,4);
    put(k,0xe1000600|FONT_PAGE);                   /* semi-transparency B/2 + F/2 */
    put(k,0x62000000);put(k,xy(left,top));put(k,xy(PAGE_W,PAGE_H));
    text_in(k,"CHARACTER SELECT",CENTRE_X,top+3,1,2,0x808080,WHITE_CLUT);
    text(k,page?"TEKKEN TAG TOURNAMENT":"TEKKEN 3",CENTRE_X,top+19,3,5,0x808080);
    trigger(k,left+6,top+PAGE_H-TRIGGER_H-2,"L2");
    trigger(k,left+PAGE_W-6-TRIGGER_W,top+PAGE_H-TRIGGER_H-2,"R2");
}

/* 8007E0B8 hands the GPU the display list (a0) of a frame. With a card
 * open, the cards are linked after its last packet: drawn over the rest,
 * in the drawing area the list leaves. The selector keeps packets from one
 * frame to the next, in lists that take turns, so that link can outlive
 * the card: it is cut in the lists of the next frames once no card is open.
 * Two buffers, one per list in flight. */
extern void __real_func_8007E0B8(CPUState *cpu);
enum { CARD_BYTES=1024*4, BUFFER_BYTES=3*CARD_BYTES };
static uint32_t buffers[2];
static int ours(uint32_t at) {
    return buffers[0] && ((at>=buffers[0] && at<buffers[0]+BUFFER_BYTES) ||
                          (at>=buffers[1] && at<buffers[1]+BUFFER_BYTES));
}
/* The packet whose link ends the game's part of the list. */
static uint32_t list_tail(uint32_t at) {
    uint32_t tail=0;
    for(unsigned n=0;n<16384 && !ours(at);n++) {
        tail=at;
        uint32_t next=psx_mod_read_word(at)&0xffffff;
        if(next==0xffffff)break;
        at=next|0x80000000;
    }
    return tail;
}
void __wrap_func_8007E0B8(CPUState *cpu) {
    static unsigned flip,frame,linked;
    int state[2]={card_state(0),card_state(1)},page=page_state();
    int open=state[0]>=0 || state[1]>=0 || page>=0;
    if((cpu->pc==0 || cpu->pc==0x8007e0b8) && (open || linked)) {
        if(!buffers[0])
            for(unsigned b=0;b<2;b++)buffers[b]=psx_mod_alloc_gpu_dma_memory(BUFFER_BYTES,16);
        uint32_t tail=buffers[0] && buffers[1]?list_tail(cpu->gpr[4]|0x80000000):0;
        if(tail) {
            uint32_t link=0xffffff,base=buffers[flip^=1];
            if(page>=0) {                              /* drawn last */
                uint32_t pkt=base+2*CARD_BYTES;
                Packet k;begin(&k,pkt,CARD_BYTES);
                page_packet(&k,page);
                link=finish(&k,pkt,link);
            }
            for(int p=1;open && p>=0;p--) {            /* built last to first */
                if(state[p]<0)continue;
                uint32_t pkt=base+(uint32_t)p*CARD_BYTES;
                Packet k;begin(&k,pkt,CARD_BYTES);
                card_packet(&k,(unsigned)p,state[p],frame);
                link=finish(&k,pkt,link);
            }
            psx_mod_write_word(tail,(psx_mod_read_word(tail)&0xff000000)|link);
            linked=open?8:linked-1;frame++;
        }
    }
    __real_func_8007E0B8(cpu);
}
