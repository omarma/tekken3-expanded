/* Local, opt-in import probe. Assets are loaded from an explicit private
 * directory and never embedded in or distributed with the executable. */
#include "mod_plugins.h"
#include "psx_runtime.h"
#include "gpu_render.h"
#include "psx_sha256.h"
#include "psx_sdl.h"
#include "tekken3_ttt1_assets.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Each player's guest model: host copy of its files (sized for the largest
 * guest, the real lengths kept alongside), its guest memory, and its format
 * offsets: first block (word 0 of row 0), to recognise a replaced header, and
 * data start (+16). `generation` and `costume` are the identity and the
 * costume it was read for. */
enum { FACE_MAX=5 };      /* expressions 1..5: bytes 3..7 of TTT1's 0x801945D8 */
typedef struct {
    unsigned generation,costume;
    unsigned char file[65536];unsigned size;
    uint32_t relocation[512];unsigned reloc_count;
    unsigned char textures[65536];unsigned textures_size;
    uint32_t memory,first_block,payload;
    /* Face expressions of the costume (.face, tools/ttt1_import.py faces()): the
     * image the model shows, (face_x, face_y) in the .tim, and the offsets in
     * `textures` of the pixels of expression 0 (that image) to face_count. */
    unsigned face_x,face_y,face_w,face_h,face_blink,face_count,face_flag[2];
    unsigned face_image[FACE_MAX+1];
} GuestModel;
static GuestModel models[2];
static uint32_t control;
static uint32_t arena[2];
static unsigned arena_half[2];
static int attempted;
static uint32_t original_header[2][384], original_base[2];
static int initializing;
static int face_variant[2]={-1,-1};     /* expression whose image is in VRAM, -1 unknown */
static struct { unsigned expression,timer; } face_state[2];
uint32_t tekken3_ttt1_guest_skeleton(unsigned player);
/* Easter egg: Jin confirmed with both punch buttons fights with his native
 * moves but is drawn with the converted TTT1 arcade Jin, whose Devil face and
 * tattooed forehead replace the images the model shows
 * (tools/ttt1_devil_jin.py). The selector latches the request; it only takes
 * effect for a player whose actor is Jin (ID 9) in his punch costume. */
enum { JIN_ID=9, DEVIL_JIN_GENERATION=0x4a494e00u };
static int devil_jin[2];
void tekken3_devil_jin_set(unsigned player,int on) {
    if(player>1 || devil_jin[player]==!!on)return;
    devil_jin[player]=!!on;
    fprintf(stderr,"Devil Jin: P%u %s\n",player+1,on?"requested (both punches)":"cleared");
}
int tekken3_devil_jin_requested(unsigned player) {return player<2 && devil_jin[player];}
int tekken3_devil_jin_player(unsigned player) {
    return player<2 && devil_jin[player] &&
        psx_mod_read_half(0x800a9240+player*0x188c)==JIN_ID &&
        (psx_mod_read_half(0x800a923c+player*0x188c)&3)==0;
}
/* His moves: TTT1 Jin's with Devil's grafted on (DevilJin-TTT1-*,
 * tools/ttt1_devil_jin_moves.py), played like a guest's (mode 2) once the
 * pack is staged; TEKKEN3_DEVIL_JIN_MOVES=0 keeps Jin's native moves (mode
 * 3). The loading choice (0x800ADD5C, costume 0x800ADD98) must be Jin in his
 * punch costume, so a request made on another fighter changes nothing. */
int tekken3_devil_jin_moves(unsigned player) {
    static int available=-1;
    if(available<0) {
        const char *e=getenv("TEKKEN3_DEVIL_JIN_MOVES"),*root=tekken3_ttt1_asset_root();
        char path[4096];FILE *f=NULL;
        if((!e || strcmp(e,"0")) && root &&
           snprintf(path,sizeof path,"%s/DevilJin-TTT1-combat.jmv",root)<(int)sizeof path)f=fopen(path,"rb");
        available=f!=NULL;if(f)fclose(f);
        fprintf(stderr,"Devil Jin: %s\n",available?"TTT1 moves with Devil's grafted (DevilJin-TTT1)":"Jin's native moves");
    }
    return available && player<2 && devil_jin[player] &&
        psx_mod_read_half(0x800add5c+player*2)==JIN_ID && psx_mod_read_half(0x800add98+player*2)==0;
}
static const char *data_prefix(unsigned player) {
    return player<2 && devil_jin[player]?"Jin-TTT1":tekken3_guest_data_prefix_for(player);
}
static const char *name_for(unsigned player) {
    return player<2 && devil_jin[player]?"Devil Jin":tekken3_guest_name_for(player);
}
/* TRACE COMPARATIVE, sous TEKKEN3_GUEST_TRACE=1 (KAZUYA-TRACE.md).
 * Emet une ligne de forme IDENTIQUE pour les deux invites, a chaque etape du
 * chargement, pour que deux executions se comparent ligne a ligne. Le prefixe
 * `TRACE|` isole ces lignes du reste du journal. */
static int trace_on=-1;
static int tracing(void) {
    if(trace_on<0) trace_on=getenv("TEKKEN3_GUEST_TRACE")?1:0;
    return trace_on;
}
#define TRACE(...) do{ if(tracing()) fprintf(stderr,"TRACE|" __VA_ARGS__); }while(0)
static int disabled_part(unsigned part) {
    static char list[256]; static int read;
    if(!read) { read=1; const char *e=getenv("TEKKEN3_GUEST_DISABLE_PARTS");
                if(e) snprintf(list,sizeof list,",%s,",e); }
    if(!list[0]) return 0;
    char needle[8]; snprintf(needle,sizeof needle,",%u,",part);
    return strstr(list,needle)!=NULL;
}
const char *tekken3_ttt1_asset_root(void) {
    /* TEKKEN3_TTT1_ASSETS, or its former name TEKKEN3_JUN_ASSETS. */
    const char *override=getenv("TEKKEN3_TTT1_ASSETS");
    if(!override || !*override)override=getenv("TEKKEN3_JUN_ASSETS");
    if(override && *override)return override;
    static char path[4096];
    if(!path[0]) {
        const char *base=SDL_GetBasePath();
        if(!base)return NULL;
        /* The TTT1 catalogue staged beside the executable. */
        int n=snprintf(path,sizeof path,"%smods/ttt1",base);
#if !defined(PSX_SDL3)
        SDL_free((void*)base);
#endif
        if(n<0 || n>=(int)sizeof path){path[0]=0;return NULL;}
    }
    return path;
}
extern void tekken3_ttt1_combat_tick(void);
extern void tekken3_ttt1_selector_tick(void);
extern void tekken3_ttt1_voices_tick(void);
extern int tekken3_ttt1_roster_enabled(void);
extern int tekken3_guest_character(unsigned id);
extern unsigned tekken3_native_moves_id(unsigned player);
static int guest_player(unsigned player) {
    if(tekken3_devil_jin_player(player))return 1;
    return tekken3_ttt1_roster_enabled()?tekken3_guest_character(psx_mod_read_half(0x800a9240+player*0x188c))>=0:
        player==0 && psx_mod_read_byte(0x80098106)==9;
}
void tekken3_ttt1_select(int enabled) {
    if(!control)return;
    psx_mod_write_byte(control,enabled?1:0);
    psx_mod_write_byte(control+12,enabled?2:0);
    if(!enabled)tekken3_ttt1_combat_tick();
    fprintf(stderr,"TTT1 characters: %s\n",enabled?"guest in the fight":"no guest in the fight");
}

void tekken3_ttt1_before_init(uint32_t model) {
    initializing++;
    /* Any guest of this player, not only the current one: in a team battle
     * the next member is another guest in the same Jin envelope, which the
     * game does not reload, so the header still points into the previous
     * guest's layout. */
    for(unsigned p=0;p<2;p++)if (model==original_base[p] && models[p].memory &&
                                  psx_mod_read_word(model+24)-models[p].memory<sizeof models[p].file) {
        for(unsigned i=0;i<384;i++) psx_mod_write_word(model+i*4,original_header[p][i]);
        fprintf(stderr,"%s model: restored stock header before actor initialization\n",name_for(p));
    }
}
void tekken3_ttt1_after_init(void) { if(initializing>0) initializing--; }

/* A cutscene of ours (src/tekken3_embu_scenes.c) may draw a player with
 * other model files than its guest's own, changing from one of its frames
 * on (TEKKEN3_EMBU_MODEL_P1 / _P2: "Prefix@frame,..."): Jin, then Devil Jin,
 * in Kazuya's TTT ending. */
typedef struct { int frame; char prefix[40]; } ModelStep;
static ModelStep model_steps[2][8];
static int model_step_count[2]={-1,-1};
extern int tekken3_cine_frame(void);
extern int tekken3_cine_pending(void);
static const char *embu_model(unsigned player) {
    if(model_step_count[player]<0) {
        model_step_count[player]=0;
        const char *e=getenv(player?"TEKKEN3_EMBU_MODEL_P2":"TEKKEN3_EMBU_MODEL_P1");
        char list[512];
        if(e && snprintf(list,sizeof list,"%s",e)<(int)sizeof list)
            for(char *s=strtok(list,",");s && model_step_count[player]<8;s=strtok(NULL,",")) {
                char *at=strchr(s,'@');if(!at)continue;*at=0;
                ModelStep *m=&model_steps[player][model_step_count[player]++];
                snprintf(m->prefix,sizeof m->prefix,"%s",s);m->frame=atoi(at+1);
                fprintf(stderr,"TTT1 Embu: P%u drawn with %s from frame %d\n",player+1,m->prefix,m->frame);
            }
    }
    int frame=tekken3_cine_frame();
    /* The fight an ending cutscene of ours plays in loads its guests with
     * the first model files already: the cutscene then changes only
     * textures. */
    if(frame<0 && psx_mod_read_word(0x800ae204)!=6 && tekken3_cine_pending())frame=0;
    if(!model_step_count[player] || frame<0)return NULL;
    const char *out=NULL;
    for(int i=0;i<model_step_count[player];i++)if(frame>=model_steps[player][i].frame)out=model_steps[player][i].prefix;
    return out;
}
static const char *model_prefix(unsigned player) {
    const char *m=player<2?embu_model(player):NULL;
    return m?m:data_prefix(player);
}
static uint32_t word(const unsigned char *p) {
    return (uint32_t)p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24;
}
/* Reads "<root>/<data prefix>-<suffix>" whatever its length, up to `max`, and
 * returns the byte count. The old form demanded one character's exact size. */
static size_t read_asset(unsigned player, const char *root, const char *suffix, void *data, size_t max) {
    char path[4096];
    if (snprintf(path,sizeof(path),"%s/%s-%s",root,model_prefix(player),suffix)
        >=(int)sizeof(path)) return 0;
    FILE *f=fopen(path,"rb");
    if (!f) { fprintf(stderr,"%s model: missing %s\n",name_for(player),path); return 0; }
    size_t n=fread(data,1,max,f);
    int complete = fgetc(f)==EOF;          /* else the file exceeds the buffer */
    fclose(f);
    if (!complete) fprintf(stderr,"%s model: %s exceeds %zu bytes\n",name_for(player),path,max);
    return complete ? n : 0;
}
static uint16_t half(const unsigned char *p);
/* Offset in the .tim of the pixels of the w x h image at (x, y), 0 if none. */
static unsigned tim_image(const GuestModel *m,unsigned x,unsigned y,unsigned w,unsigned h) {
    for(unsigned o=0;o+8<m->textures_size;) {
        if(word(m->textures+o)!=16)return 0;
        unsigned flags=word(m->textures+o+4);o+=8;
        if(flags&8)o+=word(m->textures+o);
        unsigned n=word(m->textures+o);
        if(half(m->textures+o+4)==x && half(m->textures+o+6)==y && half(m->textures+o+8)==w &&
           half(m->textures+o+10)==h && o+12+w*h*2<=m->textures_size)return o+12;
        o+=n;
    }
    return 0;
}
/* The costume's face expressions, if it has any (no file: Kunimitsu, the Jacks...). */
static void read_face(unsigned player,const char *root,unsigned costume) {
    GuestModel *m=&models[player];
    unsigned char b[4+2*(6+2*FACE_MAX+2)];
    char path[4096];
    m->face_count=0;m->face_image[0]=0;
    if(snprintf(path,sizeof path,"%s/%s-arcade-P%u.face",root,data_prefix(player),costume)>=(int)sizeof path)return;
    FILE *f=fopen(path,"rb");
    if(!f)return;
    size_t n=fread(b,1,sizeof b,f);fclose(f);
    if(n<16 || memcmp(b,"FACE",4))return;
    unsigned count=half(b+14);
    if(count>FACE_MAX || n<16+4*count)return;
    m->face_x=half(b+4);m->face_y=half(b+6);m->face_w=half(b+8);m->face_h=half(b+10);m->face_blink=half(b+12);
    /* Then the flags' expressions; a file from before them has none (FACE_MAX+1: nothing). */
    for(unsigned k=0;k<2;k++)m->face_flag[k]=n>=16+4*count+2*k+2?half(b+16+4*count+2*k):FACE_MAX+1;
    for(unsigned e=0;e<=count;e++) {
        unsigned x=e?half(b+16+4*(e-1)):m->face_x,y=e?half(b+18+4*(e-1)):m->face_y;
        if(!(m->face_image[e]=tim_image(m,x,y,m->face_w,m->face_h))) {
            fprintf(stderr,"%s model: face expression %u image (%u,%u) not in the textures\n",name_for(player),e,x,y);
            m->face_image[0]=0;return;
        }
    }
    m->face_count=count;
}
/* Reads and checks a player's guest model, relocations and textures into
 * the host buffers. Returns 0 and leaves the buffers unusable on failure. */
static int read_model(unsigned player) {
    GuestModel *m=&models[player];
    const char *root=tekken3_ttt1_asset_root();
    if (!root || !*root) return 0;
    size_t reloc_bytes;
    /* The chosen costume's files, else costume 1's: a costume the importer
     * could not convert has none. */
    char model[32],relocs[32],textures[32];
    unsigned costume=m->costume+1;
    snprintf(model,sizeof model,"arcade-P%u.3dm",costume);
    FILE *probe=NULL;char path[4096];
    if(costume>1 && (snprintf(path,sizeof path,"%s/%s-%s",root,model_prefix(player),model)>=(int)sizeof path ||
                     !(probe=fopen(path,"rb")))) {
        fprintf(stderr,"%s model: no costume %u, costume 1 instead\n",name_for(player),costume);
        costume=1;snprintf(model,sizeof model,"arcade-P1.3dm");
    }
    if(probe)fclose(probe);
    snprintf(relocs,sizeof relocs,"arcade-P%u.relocs",costume);
    snprintf(textures,sizeof textures,"arcade-P%u.tim",costume);
    if (!(m->size=read_asset(player,root,model,m->file,sizeof(m->file))) ||
        !(reloc_bytes=read_asset(player,root,relocs,m->relocation,sizeof(m->relocation))) ||
        !(m->textures_size=read_asset(player,root,textures,m->textures,sizeof(m->textures)))) return 0;
    if (m->size%4 || reloc_bytes%4) return 0;
    m->reloc_count=(unsigned)(reloc_bytes/4);
    read_face(player,root,costume);
    /* PS1 model converted by tools/ttt1_import.py: 27 rows. */
    if (word(m->file)!=27 || word(m->file+8)!=0x4b4d4433 || word(m->file+16)!=0x5f8) return 0;
    m->first_block=word(m->file+24); m->payload=word(m->file+16);
    fprintf(stderr,"%s model: costume %u, %u B, m->textures %u B, %u relocations\n",
            name_for(player),costume,m->size,m->textures_size,m->reloc_count);
    TRACE("T1|model_bytes=%u|texture_bytes=%u|m->reloc_count=%u\n",
          m->size,m->textures_size,m->reloc_count);
    TRACE("T2|rows=%u|scale=%u|magic=%08X|word4=%08X\n",
          word(m->file),word(m->file+4),word(m->file+8),word(m->file+16));
    if(tracing()) for(unsigned r=0;r<30;r++) {
        const unsigned char *p=m->file+16+r*56;
        TRACE("T2row|row=%2u|w0=%08X|w1=%08X|w2=%08X|w3=%08X|w4=%08X|w5=%08X|"
              "w6=%08X|w7=%08X|w8=%08X|w9=%08X|w10=%08X|w11=%08X|w12=%08X|w13=%08X\n",
              r,word(p),word(p+4),word(p+8),word(p+12),word(p+16),word(p+20),word(p+24),
              word(p+28),word(p+32),word(p+36),word(p+40),word(p+44),word(p+48),word(p+52));
    }
    if(tracing()) {
        unsigned lo=0xffffffff,hi=0;
        for(unsigned i=0;i<m->reloc_count;i++){ if(m->relocation[i]<lo)lo=m->relocation[i];
                                             if(m->relocation[i]>hi)hi=m->relocation[i]; }
        TRACE("T3|reloc_count=%u|reloc_lo=%u|reloc_hi=%u\n",m->reloc_count,lo,hi);
    }
    for (unsigned i=0;i<m->reloc_count;i++) {
        uint32_t r=m->relocation[i];
        if ((r&3) || r>m->size-4 || word(m->file+r)>=m->size) return 0;
    }
    return 1;
}
/* Copies the host model into guest memory with its pointers relocated. The
 * area is sized for the largest m->memory, so a switch rewrites it in place. */
static void install_model(unsigned player) {
    GuestModel *m=&models[player];
    for (unsigned i=0;i<m->size;i+=4) psx_mod_write_word(m->memory+i,word(m->file+i));
    for (unsigned i=0;i<m->reloc_count;i++) {
        uint32_t r=m->relocation[i];
        psx_mod_write_word(m->memory+r,word(m->file+r)+m->memory);
    }
    TRACE("T4|control=%08X|guest=%08X|arena0=%08X|arena1=%08X|model_bytes=%u\n",
          control,m->memory,arena[0],arena[1],m->size);
}
static void load_assets(void) {
    control=psx_mod_alloc_guest_memory(32,16);
    arena[0]=psx_mod_alloc_gpu_dma_memory(262144,16);
    arena[1]=psx_mod_alloc_gpu_dma_memory(262144,16);
    for(unsigned p=0;p<2;p++)models[p].memory=psx_mod_alloc_guest_memory(sizeof models[p].file,16);
    if (!control || !arena[0] || !arena[1] || !models[0].memory || !models[1].memory) { control=0; return; }
    fprintf(stderr,"TTT1 characters: control=%08X, models at %08X and %08X\n",control,models[0].memory,models[1].memory);
}
/* A player's guest changed at the selector, or none was read yet: the next
 * fight's Jin envelope of that player is replaced by the new model. A model
 * that fails its checks is reported and never matched; the staged catalogue
 * only holds imports that passed them. */
static void follow_models(void) {
    for(unsigned p=0;p<2;p++) {
        unsigned generation=devil_jin[p]?DEVIL_JIN_GENERATION:tekken3_guest_generation(p),
                 costume=devil_jin[p]?0:tekken3_guest_costume(p);
        if(!control || (models[p].generation==generation && models[p].costume==costume))continue;
        /* A native on its TTT1 moves keeps its own model. */
        if(tekken3_native_moves_id(p)<23)continue;
        models[p].generation=generation;models[p].costume=costume;
        /* original_base / original_header stay: they are Jin's stock header,
         * whatever the guest, and before_init needs them to put it back when
         * the game keeps the envelope loaded between two guests. */
        face_variant[p]=-1;face_state[p].expression=face_state[p].timer=0;
        if(read_model(p))install_model(p);
        else {models[p].first_block=0;fprintf(stderr,"%s model: rejected\n",name_for(p));}
    }
}
/* Motion modes: 0 native, 1 neutral-only reference, 2 guest (its model in
 * Jin's envelope, its TTT1 moves), 4 native fighter on its TTT1 moves (its
 * own model and skeleton: tekken3_native_moves.c). */
static int native_moves_player(unsigned player) {
    unsigned id=tekken3_native_moves_id(player);
    /* Ogre's cutscene (state 8, phases 16 and 17) plays his T3 move
     * numbers: on his TTT1 alias table they fell to his stance, and he
     * stood in guard while Heihachi was lifted. */
    unsigned phase=psx_mod_read_half(0x800ae224);
    if(psx_mod_read_word(0x800ae204)==8 && (phase==16 || phase==17))return 0;
    return id<23 && psx_mod_read_half(0x800a9240+player*0x188c)==id;
}
unsigned tekken3_ttt1_player_motion_mode(unsigned player) {
    if(player<2 && control && psx_mod_read_byte(control)==1 && !initializing && native_moves_player(player))
        return 4;
    return player<2 && control && models[player].first_block && original_base[player] &&
        psx_mod_read_byte(control)==1 && !initializing && guest_player(player) &&
        psx_mod_read_word(0x8009bd28u+player*4)==original_base[player] &&
        psx_mod_read_word(original_base[player]+24)==models[player].memory+models[player].first_block
        ? (tekken3_devil_jin_player(player)?(tekken3_devil_jin_moves(player)?2u:3u):psx_mod_read_byte(control+12)) : 0;
}
unsigned tekken3_ttt1_motion_mode(void) {return tekken3_ttt1_player_motion_mode(0);}
static uint16_t half(const unsigned char *p) { return p[0] | (uint16_t)p[1]<<8; }
/* Player 2's band is VRAM rows 256..511, and its last rows hold palettes
 * at x 384..447: the HUD's in 504..511 (the round markers read theirs at
 * (400,508)), the loading screen's portraits' (502 for player 1, 503 for
 * player 2, x 256..511; kept from stage to stage, player 1's portrait lost
 * colours after a fight against a guest: a magenta band on Jin's face) and,
 * above them, the selector icons' (256, 480 + ID), which no screen reloads:
 * overwritten, the VS grid showed its portraits speckled after a fight.
 * Tiles of player 2 that reach band rows 224..255 therefore move to
 * x 960..1023, rows 0..255, a texture page that no arena reads or writes
 * during a fight (tools/ttt1_fight_vram_usage.py, the 15 arenas from round
 * intro to K.O.; Practice, Tekken Ball, Tekken Force too); every costume
 * fits. make_packets_native() points their faces there. x 800..863, used
 * before, is read by the arenas: the tiles spoiled their scenery.
 * Two 32-wide columns in the one page; the first stops at row 224, where
 * player 1's command icons go (icon_tick); every costume still fits. */
enum { BAND_ROWS=224, MOVE_X0=960, MOVE_Y0=0, MOVE_Y1=256, MOVE_ICONS_Y=224, MOVE_MAX=32 };
typedef struct { unsigned bx,by,w,h,nx,ny; } MovedTile;
static MovedTile moved[2][MOVE_MAX];
static unsigned moved_count[2];
static void plan_moves(unsigned player) {
    moved_count[player]=0;
    if(player!=1)return;
    unsigned column_y[2]={MOVE_Y0,MOVE_Y0};
    for(unsigned o=0;o+8<models[player].textures_size;) {
        if(word(models[player].textures+o)!=16)return;
        unsigned flags=word(models[player].textures+o+4);o+=8;
        if(flags&8)o+=word(models[player].textures+o);
        unsigned n=word(models[player].textures+o);
        unsigned x=half(models[player].textures+o+4),y=half(models[player].textures+o+6);
        unsigned w=half(models[player].textures+o+8),h=half(models[player].textures+o+10);
        o+=n;
        if(x+w>128 || y+h>128 || x/64!=(x+w-1)/64)continue;
        unsigned by=y+(x>=64?128:0);
        if(by+h<=BAND_ROWS)continue;
        /* Shelf per column: tiles stack downwards; a column is 32 wide. */
        int placed=0;
        for(unsigned c=0;c<2 && !placed;c++) {
            if(w>32 || column_y[c]+h>(c?MOVE_Y1:MOVE_ICONS_Y) || moved_count[player]>=MOVE_MAX)continue;
            moved[player][moved_count[player]++]=(MovedTile){x%64,by,w,h,MOVE_X0+c*32,column_y[c]};
            column_y[c]+=h;placed=1;
        }
        if(!placed)fprintf(stderr,"%s model: no room to move the tile at (%u,%u) %ux%u off the HUD palettes\n",
                           name_for(player),x,y,w,h);
    }
}
static const MovedTile *moved_tile(unsigned player,unsigned bx,unsigned by,unsigned bx1,unsigned by1) {
    for(unsigned i=0;i<moved_count[player];i++) {
        const MovedTile *t=&moved[player][i];
        if(bx>=t->bx && bx1<t->bx+t->w && by>=t->by && by1<t->by+t->h)return t;
    }
    return NULL;
}
/* That page is free during a fight only: it is also the right half of the
 * selector's 8bpp icon sheet (page (896, 0)), where the stock fighters 0..15
 * and 20 have their icons (x 960..1023, y 0..255). Arcade's selector reloads
 * the sheet, but a Team Battle loads it once at the grid, then draws its
 * icons on every FIGHT screen, on the results and back on the grid: each
 * guest of the CPU's team left its tiles over them, worse fight after fight.
 * What lies under the two columns is kept when the tiles first go up, and
 * put back as soon as a screen other than the fight shows (a first icon
 * asked for, tekken3_ttt1_moved_tiles_hide, or three frames outside the
 * fight and loading states), except where something else wrote since. The
 * tiles go up again when the fight shows (state 8, phase 6 on). */
typedef struct { unsigned x,y,w,h; } MoveArea;
static const MoveArea move_areas[2]={{MOVE_X0,MOVE_Y0,32,MOVE_ICONS_Y-MOVE_Y0},{MOVE_X0+32,MOVE_Y0,32,MOVE_Y1-MOVE_Y0}};
static uint16_t move_under[2][32*256],move_written[2][32*256];
static int moved_up;
static void moved_save_under(void) {
    for(unsigned a=0;a<2;a++)gr_vram_transfer_out(move_areas[a].x,move_areas[a].y,move_areas[a].w,move_areas[a].h,move_under[a]);
}
static void moved_note_written(void) {
    for(unsigned a=0;a<2;a++)gr_vram_transfer_out(move_areas[a].x,move_areas[a].y,move_areas[a].w,move_areas[a].h,move_written[a]);
    moved_up=1;
}
void tekken3_ttt1_moved_tiles_hide(void) {
    if(!moved_up)return;
    static uint16_t now[32*256];
    for(unsigned a=0;a<2;a++) {
        gr_vram_transfer_out(move_areas[a].x,move_areas[a].y,move_areas[a].w,move_areas[a].h,now);
        for(unsigned i=0;i<move_areas[a].w*move_areas[a].h;i++)if(now[i]==move_written[a][i])now[i]=move_under[a][i];
        gr_vram_transfer_in(move_areas[a].x,move_areas[a].y,move_areas[a].w,move_areas[a].h,now);
    }
    moved_up=0;
}
/* The COMMAND LIST (Start in any fight) and COMBO TRAINING's row of inputs
 * draw their button and arrow icons from a sheet the game keeps in player 1's
 * texture band, VRAM (384..413, 224..255): buttons u 0..39, arrows
 * u 40..119, 4bpp, CLUTs x 768..1023, y 508..510 (COMBO TRAINING's
 * blue arrows read x 848). Most guest costumes cover
 * it, and COMBO TRAINING shows the row while player 1 fights, so the sheet
 * cannot come back to its place. It is saved before player 1's costume first
 * lands, copied to (960, 224), under player 2's moved tiles in the page no
 * fight uses (plan_moves), and the GPU reads the icons there while player 1
 * is a guest: same page row, so v does not move. (896, 288), used before, is
 * no arena's but is the common hit spark's texture (0x800766B4, table
 * 0x800279EC: (896, 256), 64 x 256 texels, CLUT (32, 503)): every hit drew
 * the icons in the spark's red. The spot is also part of the selector's
 * 8bpp icon sheet (page (896, 0), x 896..1023), which the selector does not
 * always reload (Start + Select reset from a fight, back to Arcade): what
 * lies under it is kept and put back as soon as the fight ends. Reserving
 * the area in the
 * costume fold instead costs every guest colours, and Kunimitsu no longer
 * fits at all. */
enum { ICON_X=384, ICON_Y=224, ICON_W=30, ICON_H=32, ICON_NX=MOVE_X0, ICON_NY=MOVE_ICONS_Y };
static uint16_t icon_sheet[ICON_W*ICON_H], icon_costume[ICON_W*ICON_H], icon_under[ICON_W*ICON_H];
static int icon_saved, icon_moved;
static void icon_release(void) {
    if(!icon_moved)return;
    psx_mod_gpu_texture_alias(0,0,0,0,0,0,0,0,0,0,0,0);
    gr_vram_transfer_in(ICON_NX,ICON_NY,ICON_W,ICON_H,icon_under);
    icon_moved=0;
}
static void icon_before_upload(unsigned player) {
    if(player!=0)return;
    icon_release();
    if(!icon_saved)gr_vram_transfer_out(ICON_X,ICON_Y,ICON_W,ICON_H,icon_sheet);
}
static void icon_after_upload(unsigned player) {
    if(player!=0 || icon_saved)return;
    /* A re-upload in the same fight reads back the costume, not the sheet:
     * the sheet is the one the game left there, so keep it only if the
     * costume changed the area. */
    gr_vram_transfer_out(ICON_X,ICON_Y,ICON_W,ICON_H,icon_costume);
    icon_saved=memcmp(icon_sheet,icon_costume,sizeof icon_sheet)!=0;
}
/* Start + Select from the COMMAND LIST changes the state at once, but the list
 * is still drawn for a few frames: letting the alias go then shows the costume
 * under the icons (B02). The alias is kept for this many frames out of the
 * fight (TEKKEN3_ICON_HOLD overrides it); the reset takes ~70 frames to reach
 * the title, long before the selector needs the spot back. */
static unsigned icon_hold(void) {
    static unsigned v=~0u;
    if(v==~0u) {
        const char *e=getenv("TEKKEN3_ICON_HOLD");
        v=e?(unsigned)strtoul(e,NULL,10):8u;
    }
    return v;
}
static void icon_tick(void) {
    static unsigned away;
    unsigned state=psx_mod_read_word(0x800ae204);
    int on=icon_saved && state==8 && guest_player(0) && original_base[0];
    if(on || state==8)away=0;
    if(icon_moved && !on && state!=8 && guest_player(0) && ++away<=icon_hold())return;
    if(on && !icon_moved) {
        /* Rewritten at each fight: loading screens may use the spot. */
        gr_vram_transfer_out(ICON_NX,ICON_NY,ICON_W,ICON_H,icon_under);
        gr_vram_transfer_in(ICON_NX,ICON_NY,ICON_W,ICON_H,icon_sheet);
        psx_mod_gpu_texture_alias(1,ICON_X/64,0,ICON_Y,ICON_W*4-1,ICON_Y+ICON_H-1,768,508,1023,510,
                                  ICON_NX/64,ICON_NY-ICON_Y);
        icon_moved=1;
    } else if(!on)icon_release();
}
/* The COMMAND LIST itself: each player's list is a 0x1A0-byte buffer from
 * 0x800A3628 (one count byte, then "name\0command\0" pairs), filled from the
 * fighter's file, so a guest shows Jin's. tools/ttt1/movelist.py writes the
 * guest's own list, taken from the Tekken wiki, as <prefix>-movelist.bin; it
 * goes into the buffer whenever the buffer holds anything else, in every
 * mode's fights: each one fills the buffer from the fighter's file. */
enum { MOVELIST_BASE=0x800a3628u, MOVELIST_SIZE=0x1a0 };
static unsigned char movelist[2][MOVELIST_SIZE];
static size_t movelist_size[2];
static char movelist_prefix[2][64];
static int movelist_valid(const unsigned char *d, size_t n) {
    if(n<1 || n>MOVELIST_SIZE)return 0;
    size_t p=1;
    for(unsigned e=0;e<2u*d[0];e++) {
        while(p<n && d[p])p++;
        if(p++>=n)return 0;
    }
    return 1;
}
/* A native fighter on its TTT1 moves (mode 4) shows its TTT1 list too. */
static int native_ttt1(unsigned player){return tekken3_ttt1_player_motion_mode(player)==4;}
static void movelist_tick(unsigned player) {
    /* Devil Jin fights with Jin's native list; a native on its TTT1 moves
     * (mode 4) shows its TTT1 list. */
    if(psx_mod_read_word(0x800ae204)!=8)return;
    if(!native_ttt1(player) && (!guest_player(player) || tekken3_devil_jin_player(player) || !original_base[player]))return;
    /* The list of the moves in use: a donor's (Unknown's switch), else the
     * guest's own. */
    const char *prefix=tekken3_guest_moves_prefix_for(player);
    if(strcmp(prefix,movelist_prefix[player])) {
        snprintf(movelist_prefix[player],sizeof movelist_prefix[player],"%s",prefix);
        const char *root=tekken3_ttt1_asset_root();
        char path[4096];FILE *f=NULL;
        if(root && snprintf(path,sizeof path,"%s/%s-movelist.bin",root,prefix)<(int)sizeof path)f=fopen(path,"rb");
        if(f) {
            movelist_size[player]=fread(movelist[player],1,MOVELIST_SIZE,f);
            if(fgetc(f)!=EOF)movelist_size[player]=0;
            fclose(f);
        } else movelist_size[player]=root?read_asset(player,root,"movelist.bin",movelist[player],MOVELIST_SIZE):0;
        if(movelist_size[player] && !movelist_valid(movelist[player],movelist_size[player])) {
            fprintf(stderr,"%s: move list rejected\n",name_for(player));
            movelist_size[player]=0;
        } else if(movelist_size[player])
            fprintf(stderr,"%s: move list of %u entries\n",name_for(player),movelist[player][0]);
    }
    if(!movelist_size[player])return;
    uint32_t base=MOVELIST_BASE+player*MOVELIST_SIZE;
    size_t i=0;
    while(i<movelist_size[player] && psx_mod_read_byte(base+(uint32_t)i)==movelist[player][i])i++;
    if(i==movelist_size[player])return;
    for(i=0;i<movelist_size[player];i++)psx_mod_write_byte(base+(uint32_t)i,movelist[player][i]);
}
/* COMBO TRAINING (Practice). The Practice overlay keeps each character's
 * combos in a table at 0x800B25F8: 8 bytes per move-set key (first combo,
 * count), 20 keys, read through actor +0x16. A combo is 12 bytes: its inputs
 * (buttons, directions, frames; the demo plays them), the expected list
 * (halfword count, then move numbers, compared with actor +0xA0 as the player
 * attacks), the input count and the list's halfword count. Every guest has
 * key 23, past the table's end: the count read there is negative and the mode
 * stays shut.
 * tools/ttt1/combos.py writes <prefix>-combos.bin (u16 count; per combo u16
 * inputs, u16 moves, the inputs, the moves as guest graph indices). The table
 * is copied to guest memory with key 23 holding the combos of the COMBO
 * PLAYER's guest (Practice block +0x7B), moves rebased on that player's
 * graph, and the overlay's five readers are pointed at the copy. */
enum { COMBO_TABLE=0x800b25f8u, COMBO_STOCK_KEYS=20, COMBO_KEYS=24, COMBO_GUEST_KEY=23,
       COMBO_MAX=7, COMBO_INPUTS=50, COMBO_MOVES=48, COMBO_FILE=4096,
       COMBO_MEMORY=COMBO_KEYS*8+COMBO_MAX*12+COMBO_MAX*(COMBO_INPUTS*4+(COMBO_MOVES+1)*2+4) };
static const uint32_t combo_site[5][2]={{0x800b7954,0x800b7958},{0x800b79c8,0x800b79d0},
    {0x800b7b1c,0x800b7b24},{0x800b7b3c,0x800b7b40},{0x800b7fbc,0x800b7fc4}};
static unsigned char combo_file[2][COMBO_FILE];
static size_t combo_size[2];
static char combo_prefix[2][64];
static unsigned combo_generation[2];
static uint32_t combo_memory;
static int combos_valid(const unsigned char *d, size_t n) {
    if(n<2)return 0;
    unsigned count=d[0]|d[1]<<8;
    size_t p=2;
    if(count>COMBO_MAX)return 0;
    for(unsigned c=0;c<count;c++) {
        if(p+4>n)return 0;
        unsigned inputs=d[p]|d[p+1]<<8,moves=d[p+2]|d[p+3]<<8;
        if(!inputs || inputs>COMBO_INPUTS || !moves || moves>COMBO_MOVES)return 0;
        p+=4+inputs*4+moves*2;
    }
    return p==n;
}
/* The overlay's readers form the table's address with lui + addiu. */
static int combo_sites(uint32_t table) {
    for(unsigned i=0;i<5;i++) {
        uint32_t lui=psx_mod_read_word(combo_site[i][0]),add=psx_mod_read_word(combo_site[i][1]);
        if((lui&0xffe0ffff)!=(0x3c000000|((table+0x8000)>>16)) || (add&0xfc00ffff)!=(0x24000000|(table&0xffff)) ||
           (lui>>16&31)!=(add>>21&31))return 0;
    }
    return 1;
}
static void combo_point(uint32_t table) {
    for(unsigned i=0;i<5;i++) {
        uint32_t lui=psx_mod_read_word(combo_site[i][0]),add=psx_mod_read_word(combo_site[i][1]);
        psx_mod_write_code_word(combo_site[i][0],(lui&0xffff0000)|((table+0x8000)>>16));
        psx_mod_write_code_word(combo_site[i][1],(add&0xffff0000)|(table&0xffff));
    }
}
/* The combos of the moves in use, as Mokujin's follow the character T3 draws
 * for him: a donor's (Tetsujin's draw, Unknown's switch) from
 * <Guest>@<Donor>-combos.bin, else the guest's own. */
static void combo_load(unsigned player) {
    /* Devil Jin fights with Jin's native combos. */
    const char *prefix=(guest_player(player) && !tekken3_devil_jin_player(player)) || native_ttt1(player)?
        tekken3_guest_moves_prefix_for(player):"";
    if(!strcmp(prefix,combo_prefix[player]))return;
    snprintf(combo_prefix[player],sizeof combo_prefix[player],"%s",prefix);
    combo_generation[player]++;
    const char *root=tekken3_ttt1_asset_root();
    char path[4096];FILE *f=NULL;
    combo_size[player]=0;
    if(*prefix && root && snprintf(path,sizeof path,"%s/%s-combos.bin",root,prefix)<(int)sizeof path &&
       (f=fopen(path,"rb"))) {
        combo_size[player]=fread(combo_file[player],1,COMBO_FILE,f);
        if(fgetc(f)!=EOF)combo_size[player]=0;
        fclose(f);
    } else if(*prefix && root)combo_size[player]=read_asset(player,root,"combos.bin",combo_file[player],COMBO_FILE);
    if(combo_size[player] && !combos_valid(combo_file[player],combo_size[player])) {
        fprintf(stderr,"%s: training combos rejected\n",tekken3_guest_name_for(player));
        combo_size[player]=0;
    } else if(combo_size[player])
        fprintf(stderr,"%s: %u training combos (%s)\n",tekken3_guest_name_for(player),combo_file[player][0],prefix);
}
/* The combos of `player`'s guest go under key 23, the one every guest
 * fights with; a native on its TTT1 moves keeps its own key, so its TTT1
 * combos go under that one, the others back to the overlay's own. */
static unsigned combo_key=COMBO_GUEST_KEY;
static void combo_install(int player) {
    uint32_t records=combo_memory+COMBO_KEYS*8,data=records+COMBO_MAX*12;
    for(unsigned i=0;i<COMBO_STOCK_KEYS*2;i++)
        psx_mod_write_word(combo_memory+i*4,psx_mod_read_word(COMBO_TABLE+i*4));
    combo_key=COMBO_GUEST_KEY;
    if(player>=0 && native_ttt1((unsigned)player)) {
        unsigned key=psx_mod_read_half(0x800a9228+(unsigned)player*0x188c+0x16);
        if(key<COMBO_STOCK_KEYS)combo_key=key;
    }
    unsigned count=0;
    if(player>=0 && combo_size[player]) {
        const unsigned char *d=combo_file[player];
        unsigned base=8192+(unsigned)player*4096;
        size_t p=2;
        count=d[0]|d[1]<<8;
        for(unsigned c=0;c<count;c++) {
            unsigned inputs=d[p]|d[p+1]<<8,moves=d[p+2]|d[p+3]<<8;
            uint32_t in=data,list=data+inputs*4;
            p+=4;
            for(unsigned i=0;i<inputs*4;i++)psx_mod_write_byte(in+i,d[p+i]);
            p+=inputs*4;
            psx_mod_write_half(list,(uint16_t)moves);
            for(unsigned i=0;i<moves;i++,p+=2)psx_mod_write_half(list+2+i*2,(uint16_t)(base+(d[p]|d[p+1]<<8)));
            psx_mod_write_word(records+c*12,in);
            psx_mod_write_word(records+c*12+4,list);
            psx_mod_write_word(records+c*12+8,inputs|(moves+1)<<16);
            data=(list+2+moves*2+3)&~3u;
        }
    }
    if(combo_key!=COMBO_GUEST_KEY) {                 /* key 23: none */
        psx_mod_write_word(combo_memory+COMBO_GUEST_KEY*8,records);
        psx_mod_write_word(combo_memory+COMBO_GUEST_KEY*8+4,0);
    }
    psx_mod_write_word(combo_memory+combo_key*8,records);
    psx_mod_write_word(combo_memory+combo_key*8+4,count);
}
/* The overlay shows a combo from copies: its inputs at 0x800B8C10 (the demo
 * and the icon row; last index at 0x800B8D48 + 4 * player), the demo cursor
 * at 0x800B8CD8, the log of the moves at 0x800B8CE0. It fills them when the
 * menu changes the combo number (0x800B515C: 0x800B744C, 0x800B7C24,
 * 0x800B7994; 50 inputs, 50 logged moves), never when the table changes. Do what it does there, for the
 * same number (Practice block +0x7C) in the new table, while COMBO TRAINING
 * is the mode (block +0x77 = 2). */
enum { COMBO_INPUT_COPY=0x800b8c10u, COMBO_LAST_INPUT=0x800b8d48u, COMBO_DELAY=0x800b8b4cu,
       COMBO_CURSOR=0x800b8cd8u, COMBO_LOG=0x800b8ce0u, COMBO_LOG_SIZE=50 };
static void combo_reshow(uint32_t block,unsigned player) {
    if(psx_mod_read_byte(block+0x77)!=2)return;
    uint32_t key=combo_memory+combo_key*8;
    unsigned count=psx_mod_read_word(key+4),number=psx_mod_read_byte(block+0x7c);
    if(count && number>=count)psx_mod_write_byte(block+0x7c,(uint8_t)(number=count-1));
    /* 0x800B744C */
    for(unsigned i=0;i<COMBO_LOG_SIZE;i++)
        psx_mod_write_word(COMBO_INPUT_COPY+i*4,psx_mod_read_word(COMBO_INPUT_COPY+i*4)&0x80000000u);
    psx_mod_write_word(COMBO_LAST_INPUT+player*4,0);
    psx_mod_write_word(COMBO_DELAY+player*4,30);
    /* 0x800B7C24, the last input index being 0 */
    psx_mod_write_word(COMBO_CURSOR,0);
    psx_mod_write_word(COMBO_CURSOR+4,psx_mod_read_word(COMBO_INPUT_COPY));
    psx_mod_write_word(COMBO_LOG,0);
    for(unsigned i=0;i<COMBO_LOG_SIZE;i++)psx_mod_write_half(COMBO_LOG+4+i*2,0);
    /* 0x800B7994 */
    unsigned inputs=0;
    if(count) {
        uint32_t record=psx_mod_read_word(key)+number*12,in=psx_mod_read_word(record);
        inputs=psx_mod_read_half(record+8);
        if(inputs>COMBO_LOG_SIZE)inputs=COMBO_LOG_SIZE;
        for(unsigned i=0;i<inputs;i++)psx_mod_write_word(COMBO_INPUT_COPY+i*4,psx_mod_read_word(in+i*4));
        if(inputs)psx_mod_write_word(COMBO_LAST_INPUT+player*4,inputs-1);
    }
    fprintf(stderr,"%s: COMBO TRAINING shows combo %u of the new moves\n",tekken3_guest_name_for(player),number+1);
}
static void combo_tick(void) {
    static int shown=-2;
    static unsigned shown_generation;
    if(psx_mod_read_word(0x800ae204)!=8 || psx_mod_read_byte(0x800afa88)!=5)return;
    if(!combo_memory && !(combo_memory=psx_mod_alloc_guest_memory(COMBO_MEMORY,16)))return;
    for(unsigned p=0;p<2;p++)combo_load(p);
    if(combo_sites(COMBO_TABLE)) {
        /* The overlay was (re)loaded: copy its table, keys 20..23 empty. */
        for(unsigned i=0;i<COMBO_STOCK_KEYS*2;i++)
            psx_mod_write_word(combo_memory+i*4,psx_mod_read_word(COMBO_TABLE+i*4));
        for(unsigned k=COMBO_STOCK_KEYS;k<COMBO_KEYS;k++) {
            psx_mod_write_word(combo_memory+k*8,combo_memory+COMBO_KEYS*8);
            psx_mod_write_word(combo_memory+k*8+4,0);
        }
        combo_point(combo_memory);
        shown=-2;
    } else if(!combo_sites(combo_memory))return;
    uint32_t block=psx_mod_read_word(0x800b8a2c);
    int player=-1;
    if(block>=0x80000000u && block<0x80200000u) {
        unsigned p=psx_mod_read_byte(block+0x7b)&1;
        if((guest_player(p) && !tekken3_devil_jin_player(p)) || native_ttt1(p))player=(int)p;
    }
    unsigned generation=player>=0?combo_generation[player]:0;
    if(player!=shown || generation!=shown_generation) {
        combo_install(player);
        /* The same guest drew other moves (Unknown's switch, Tetsujin's
         * round): the combo on screen belongs to the old ones. */
        if(player>=0 && player==shown && block>=0x80000000u && block<0x80200000u)combo_reshow(block,(unsigned)player);
        shown=player;shown_generation=generation;
    }
}
/* ATTACK DATA (Practice): the label over a hit is drawn from the attacker's
 * hit code (actor +0x64, record +0x08), looked up among eight exact values
 * at 0x800B6598 (0x412 HIGH; 0x217, 0x31F, 0x51F MID; 0x10F LOW; 0x607,
 * 0x706 "!"; 0x800 none); any other code falls on HIGH. Guarding reads the
 * code's bits instead (0x80044AEC: victim +0x66, 0x10 standing guard, 0x08
 * crouching guard, against the code): TTT1's Air Inferno, 0x907, has
 * neither and cannot be guarded, yet showed HIGH. The lookup is replaced by
 * the same bits, which give the stock label for the eight codes: no posture
 * hit (bits 0..2) none, no guard bit "!", 0x08 alone LOW, both MID, 0x10
 * alone MID when it hits crouching (bit 0), else HIGH. Same registers out:
 * a0 x, v1 y, a3 code, a2 label (4: none), then back to 0x800B6648. */
enum { LABEL_SITE=0x800b6598u, LABEL_WORDS=19 };
static const uint32_t label_stock[LABEL_WORDS]={
    0x94640004,0x84670000,0x94630006,0x10e20028,0x00003021,0x28e20413,0x1040000e,0x24020217,0x10e2001e,
    0x28e20218,0x10400005,0x2402010f,0x10e20018,0x24020004,0x0802d993,0x00000000,0x2402031f,0x10e20015,
    0x24020004};
static const uint32_t label_bits[LABEL_WORDS]={
    0x94640004,   /* lhu  a0, 4(v1)          x */
    0x84670000,   /* lh   a3, 0(v1)          code */
    0x94630006,   /* lhu  v1, 6(v1)          y */
    0x30e20007,   /* andi v0, a3, 7          postures hit */
    0x1040000b,   /* beqz v0, none */
    0x30e20018,   /*  andi v0, a3, 0x18      guards that block it */
    0x1040000a,   /* beqz v0, done */
    0x24060003,   /*  li  a2, 3              "!" */
    0x24060008,   /* li   a2, 8 */
    0x10460007,   /* beq  v0, a2, done */
    0x24060002,   /*  li  a2, 2              LOW */
    0x24060018,   /* li   a2, 0x18 */
    0x10460004,   /* beq  v0, a2, done */
    0x24060001,   /*  li  a2, 1              MID */
    0x0802d977,   /* j    done */
    0x30e60001,   /*  andi a2, a3, 1         MID if it hits crouching, else HIGH */
    0x24060004,   /* none: li a2, 4 */
    0x0802d992,   /* done: j 0x800B6648 */
    0x00000000};
static void attack_label_tick(void) {
    if(psx_mod_read_word(0x800ae204)!=8 || psx_mod_read_byte(0x800afa88)!=5)return;
    for(unsigned i=0;i<LABEL_WORDS;i++)
        if(psx_mod_read_word(LABEL_SITE+i*4)!=label_stock[i])return;   /* patched, or not this overlay */
    for(unsigned i=0;i<LABEL_WORDS;i++)psx_mod_write_code_word(LABEL_SITE+i*4,label_bits[i]);
}
static void upload_textures_now(unsigned player);
static void upload_textures(unsigned player) {
    face_variant[player]=-1;
    icon_before_upload(player);
    if(player==1 && !moved_up)moved_save_under();
    upload_textures_now(player);
    if(player==1)moved_note_written();
    icon_after_upload(player);
}
/* Player 2's moved tiles again, after a screen put the icon sheet back. */
static void moved_show(void) {
    moved_save_under();
    for(unsigned o=0;o+8<models[1].textures_size;) {
        if(word(models[1].textures+o)!=16)break;
        unsigned flags=word(models[1].textures+o+4);o+=8;
        if(flags&8)o+=word(models[1].textures+o);
        unsigned n=word(models[1].textures+o);
        unsigned x=half(models[1].textures+o+4),y=half(models[1].textures+o+6);
        unsigned w=half(models[1].textures+o+8),h=half(models[1].textures+o+10);
        const MovedTile *t=x+w>128 || y+h>128 || x/64!=(x+w-1)/64?NULL:
            moved_tile(1,x%64,y+(x>=64?128:0),x%64+w-1,y+(x>=64?128:0)+h-1);
        if(t)gr_vram_transfer_in(t->nx,t->ny,w,h,(const uint16_t*)(models[1].textures+o+12));
        o+=n;
    }
    moved_note_written();
}
/* The Embu (state 6) draws player 2's guest from the moved tiles too; no
 * Embu texture reads that page otherwise (only the stage, 512..703, and the
 * costume bands). Hidden there, Kunimitsu, Lee or Kazuya on player 2 lost
 * those tiles (B23). */
static int embu_guest_on(unsigned player);
static void moved_tick(void) {
    unsigned state=psx_mod_read_word(0x800ae204);
    static unsigned away;
    away=state==8 || state==11 || (state==6 && embu_guest_on(1))?0:away+1;
    if(away>=3)tekken3_ttt1_moved_tiles_hide();
    if(!moved_up && moved_count[1] && state==8 && psx_mod_read_half(0x800ae224)>=6 &&
       !initializing && psx_mod_read_byte(control) && guest_player(1) && original_base[1] &&
       psx_mod_read_word(original_base[1]+24)==models[1].memory+models[1].first_block)
        moved_show();
}
static void upload_textures_now(unsigned player) {
    plan_moves(player);
    TRACE("T9start|player=%u|texture_bytes=%u\n",player+1,models[player].textures_size);
    for (unsigned o=0;o+8<models[player].textures_size;) {
        if (word(models[player].textures+o)!=16) return;
        unsigned flags=word(models[player].textures+o+4);o+=8;
        /* The palette precedes its pixels in the stream. Hold it back instead
         * of uploading straight away: a tile we end up skipping must not leave
         * its CLUT behind, or it overwrites the palette another tile is using
         * and the fighter comes out in one flat colour. */
        unsigned clut=0;
        if (flags&8) { clut=o; o+=word(models[player].textures+o); }
        unsigned n=word(models[player].textures+o);
        unsigned x=half(models[player].textures+o+4), y=half(models[player].textures+o+6);
        unsigned w=half(models[player].textures+o+8), h=half(models[player].textures+o+10);
        /* The donor's 128x128 texture space is FOLDED into a 64x256 VRAM band
         * per player: x 0..63 goes to y+0, x 64..127 to y+128. 128x128 and
         * 64x256 are both 16384 halfwords, so the fold is exactly full - there
         * is no room for a third band. A tile past x=128 would alias onto the
         * second band and shred the textures already there, which is what a
         * Kazuya fight looked like: blue garbage instead of a fighter.
         *
         * Skipping such a tile costs that patch of skin and nothing else.
         * Kazuya loses his toes and a cloth fringe; giving them a real home
         * needs either a repack of the donor atlas with its UVs rewritten, or
         * a separate VRAM allocation. */
        if (x+w>128 || y+h>128 || x/64!=(x+w-1)/64) {
            static int warned;
            if(!warned) {
                warned=1;
                fprintf(stderr,"%s model: texture tile at (%u,%u) %ux%u does not "
                        "fit the 128x128 costume fold; skipped to protect the rest\n",
                        name_for(player),x,y,w,h);
            }
            TRACE("T9|x=%3u|y=%3u|w=%3u|h=%3u|clut=%u|verdict=skip\n",x,y,w,h,clut?1:0);
            o+=n; continue;
        }
        TRACE("T9|x=%3u|y=%3u|w=%3u|h=%3u|clut=%u|verdict=ok\n",x,y,w,h,clut?1:0);
        if (clut)
            gr_vram_transfer_in(half(models[player].textures+clut+4),504+player*4+half(models[player].textures+clut+6),
                half(models[player].textures+clut+8),half(models[player].textures+clut+10),
                (const uint16_t*)(models[player].textures+clut+12));
        const MovedTile *t=moved_tile(player,x%64,y+(x>=64?128:0),x%64+w-1,y+(x>=64?128:0)+h-1);
        if(t)gr_vram_transfer_in(t->nx,t->ny,w,h,(const uint16_t*)(models[player].textures+o+12));
        else gr_vram_transfer_in(384+(x%64),player*256+y+(x>=64?128:0),
            w,h,(const uint16_t*)(models[player].textures+o+12));
        o+=n;
    }
}
/* Face expressions, as TTT1's 80104C64: expression e copies its image over the one
 * the model shows (0 puts that one back) and holds `duration` frames; then
 * 80105978 goes back to neutral for 1..255 frames at random, and to the costume's
 * blink expression (0x801949C0) for 3. TTT1's copies its images in VRAM; the
 * guest's are in the .tim. A move's properties start an expression
 * (tekken3_ttt1_combat.c); `advanced` is 0 when the game did not (pause).
 * `flag` 1 or 2: the move's record carries flag A or B (80105904: TTT1 record
 * +0x24 & 0x800, else +4 & 4 without +0x24 bit 22), which holds the costume's
 * expression for it (0x80194A40 / 0x80194AC0: eyes shut) 2 frames, every frame. */
static void face_set(unsigned player,unsigned expression,unsigned duration) {
    face_state[player].timer=duration;
    /* An expression the costume lacks changes nothing, as 80104CE0. */
    if(expression<=models[player].face_count)face_state[player].expression=expression;
}
void tekken3_ttt1_face_tick(unsigned player,int advanced,int expression,unsigned duration,unsigned flag) {
    GuestModel *m=&models[player];
    if(player>1 || !control || !m->face_image[0])return;
    if(advanced) {
        static uint32_t seed=0x3039;
        if(expression>=0)face_set(player,(unsigned)expression,duration);
        if((flag==1 || flag==2) && m->face_flag[flag-1]<=FACE_MAX)face_set(player,m->face_flag[flag-1],2);
        if(face_state[player].timer)face_state[player].timer--;
        else if(face_state[player].expression) {
            seed=seed*0x41c64e6d+0x3039;
            face_set(player,0,((seed>>16)&0xfe)|1);
        } else face_set(player,m->face_blink,3);
    }
    unsigned e=face_state[player].expression;
    if(face_variant[player]==(int)e)return;
    unsigned x=m->face_x,y=m->face_y,w=m->face_w,h=m->face_h;
    if(x+w>128 || y+h>128 || x/64!=(x+w-1)/64)return;
    unsigned by=y+(x>=64?128:0);
    const MovedTile *t=moved_tile(player,x%64,by,x%64+w-1,by+h-1);
    gr_vram_transfer_in(t?t->nx:384+x%64,t?t->ny:player*256+by,w,h,(const uint16_t*)(m->textures+m->face_image[e]));
    face_variant[player]=(int)e;
}
/* Paquets modeles pour le renderer NATIF, depuis le bloc de textures PS1 (mot 2) :
 * u16 decalage de la table d'UV, materiaux u16 (palette | 0x8000 si 8 bits),
 * UV deja replies dans la bande costume. Le moteur ecrit lui-meme sommets,
 * couleurs et commande ; le modele ne fournit que UV, palette et page. */
static uint32_t make_packets_native(uint32_t bundle,uint32_t out,unsigned player) {
    uint32_t m=psx_mod_read_word(bundle+16);
    uint32_t uv=m+psx_mod_read_half(m);
    uint32_t src=uv+psx_mod_read_half(uv);
    static const unsigned size[4]={32,40,40,52};
    static const unsigned opcode[4]={0x24,0x2c,0x34,0x3c};
    static const unsigned voff[4][4]={{12,20,28,0},{12,20,28,36},{12,24,36,0},{12,24,36,48}};
    for(unsigned kind=0;kind<4;kind++) {
        unsigned count=psx_mod_read_byte(src++),nv=(kind&1)?4:3;
        for(unsigned i=0;i<count;i++) {
            unsigned mat=psx_mod_read_half(m+2+psx_mod_read_byte(src++)*2);
            for(unsigned j=0;j<size[kind];j+=4) psx_mod_write_word(out+j,0);
            psx_mod_write_word(out+4,(opcode[kind]<<24)|0x808080);
            if(kind>=2) {
                psx_mod_write_word(out+16,0x808080);psx_mod_write_word(out+28,0x808080);
                if(nv==4) psx_mod_write_word(out+40,0x808080);
            }
            uint32_t v[4];
            unsigned bx0=255,by0=255,bx1=0,by1=0,shift=mat&0x8000?1:2;  /* pixels per halfword: 2 (8bpp) or 4 */
            for(unsigned j=0;j<nv;j++) {
                v[j]=psx_mod_read_half(uv+2+psx_mod_read_byte(src++)*2);
                unsigned bx=(v[j]&255)>>shift,by=v[j]>>8;
                if(bx<bx0)bx0=bx;if(bx>bx1)bx1=bx;if(by<by0)by0=by;if(by>by1)by1=by;
            }
            unsigned tpage=(mat&0x8000?0x86u:0x06u)+player*16;
            const MovedTile *t=moved_count[player]?moved_tile(player,bx0,by0,bx1,by1):NULL;
            if(t) {
                /* Same place inside the tile, in its new page. */
                for(unsigned j=0;j<nv;j++) {
                    unsigned u=v[j]&255,row=v[j]>>8;
                    unsigned nu=u-(t->bx<<shift)+((t->nx&63)<<shift),nv_=row-t->by+t->ny;
                    v[j]=(nv_<<8)|nu;
                }
                tpage=(t->nx>>6)|(mat&0x8000?0x80u:0);
            }
            for(unsigned j=0;j<nv;j++) {
                if(j==0) v[j]|=(0x7e00u+(mat&0x7fff)+player*256)<<16;
                if(j==1) v[j]|=tpage<<16;
                psx_mod_write_word(out+voff[kind][j],v[j]);
            }
            out+=size[kind];
        }
    }
    return out;
}
static int32_t mul12(int32_t a,int32_t b) { return (a*b)>>12; }
static void accessory_rotation(uint32_t destination,uint32_t row) {
    int32_t s[3],c[3];
    for(unsigned i=0;i<3;i++) {
        unsigned angle=psx_mod_read_word(row+28+i*4);
        uint32_t table=0x8001e8c4+((angle>>3)&0x1ffe);
        s[i]=(int16_t)psx_mod_read_half(table);
        c[i]=(int16_t)psx_mod_read_half(table+0x800);
    }
    int32_t a=mul12(c[0],c[2]),b=mul12(c[0],s[2]);
    int32_t d=mul12(s[0],c[2]),e=mul12(s[0],s[2]);
    int32_t matrix[9]={mul12(c[1],c[2]),mul12(d,s[1])-b,e+mul12(a,s[1]),
        mul12(c[1],s[2]),a+mul12(e,s[1]),mul12(b,s[1])-d,
        -s[1],mul12(s[0],c[1]),mul12(c[0],c[1])};
    for(unsigned i=0;i<9;i++) psx_mod_write_half(destination+i*2,(uint16_t)matrix[i]);
}
/* The engine's own face expressions (0x800343C0, actor +4750/+4752) index
 * 0x800959CC by the actor's model: four bytes per model, byte 3 = -1 for no
 * expression. The stock table stops at model 51, so a guest's model 52 reads
 * the next table and queues a VRAM copy from nonsense - 36 x 4 pixels of
 * player 1's band landed at (44, 1), in the border above the fight. Guests
 * change expression through tekken3_ttt1_face_tick(), so drop the engine's queued
 * copy (0x800293BC) when it comes from that routine for a model past the
 * table: from both its paths, 0x80034478 and 0x800342DC (the latter queued
 * its copy at x 1068, y -32767: the strip at (44, 1) above the fight, the
 * rankings and SURVIVAL RESULTS). */
enum { FACE_TABLE_MODELS=52 };
/* Wings. Row 1 of a model (torso) may carry a table of poses (row word 13) that the engine
 * plays as wings: True Ogre's flap, a state machine in the per-fighter part update
 * (0x80034970) that runs only when the fighter's character is 20. The state lives in the
 * actor: +0x128A the trigger (set from the airborne flag, 0x80040784), +0x128B the position,
 * +0x128C the table (0: 0x80095888, poses 0..16 two steps a frame while airborne, falling a step
 * a frame otherwise; 1: 0x8009589C, 16..39), +0x128D the first-step flag. TTT1's Devil and Angel
 * flap the same way (one flap a jump, pose 1 to 36 in about 45 frames, back from 16 in 17,
 * measured on the arcade by tools/ttt1_hands.lua), and their model has the 37 poses, but a
 * guest's character is 23 and over, so the machine never ran. Run it after the engine's own
 * update for a guest whose row 1 has the table; the last pose repeats where the tables go past it. */
enum { WING_TABLE_A=0x80095888, WING_TABLE_B=0x8009589c, WING_LAST=0xff };
static void wings_step(uint32_t actor,unsigned player);
static void wings_step(uint32_t actor,unsigned player) {
    uint32_t model=psx_mod_read_word(0x8009bd28+player*4);
    if(model<0x80000000u || model>=0x80200000u)return;
    /* The wings are the row whose table has the most poses (Angel's and Devil's: row 1; Devil
     * Jin's grafted ones: row 21): the hands' tables have 4 (17 before the remap). */
    uint32_t slot=0,table=0;
    unsigned poses=0;
    for(unsigned r=0;r<27;r++) {
        if(r==13 || r==17)continue;
        uint32_t row=model+24+56*r,tab=psx_mod_read_word(row+52);
        /* a guest's model data lives in the mods' memory (0x9F000000...), not in the game's RAM */
        if(!(tab>=0x80000000u && tab<0x80200000u) && !(tab>=0x9f000000u && tab<0x9f400000u))continue;
        unsigned n=1;                       /* leading distinct entries: the table then repeats pose 0 */
        uint32_t first=psx_mod_read_word(tab);
        while(n<47 && psx_mod_read_word(tab+n*4)!=first)n++;
        if(n>=24 && n>poses){poses=n;slot=row+48;table=tab;}
    }
    if(!poses)return;
    uint8_t flag=psx_mod_read_byte(actor+0x128a),pos=psx_mod_read_byte(actor+0x128b),
            state=psx_mod_read_byte(actor+0x128c),first_step=psx_mod_read_byte(actor+0x128d);
    if(state==0) {
        if(flag) {
            pos+=2;
            if(psx_mod_read_byte(WING_TABLE_A+pos)==WING_LAST){state=1;pos=0;first_step=1;}
        } else if(pos)pos--;
    } else if(state==1) {
        unsigned step=first_step?2:1;
        first_step=0;
        pos+=step;
        if(psx_mod_read_byte(WING_TABLE_B+pos)==WING_LAST) {
            if(flag)pos=0;
            else{pos=16;state=0;}
        }
    }
    psx_mod_write_byte(actor+0x128b,pos);psx_mod_write_byte(actor+0x128c,state);
    psx_mod_write_byte(actor+0x128d,first_step);
    unsigned index=psx_mod_read_byte((state?WING_TABLE_B:WING_TABLE_A)+pos);
    if(index>=poses)index=poses-1;
    uint32_t pose=psx_mod_read_word(table+index*4);
    if(pose)psx_mod_write_word(slot,pose);
}
/* Hand poses. Each frame the engine picks a pose index for each hand and calls
 * 0x80034844(slot, index, actor), which stores table[index] in the hand row's
 * position pointer (row word 12; word 13 is the table). Indices 0..3 run from open
 * hand to fist (tools/ttt1/model/convert.py hand_steps) and come from a gauge per
 * hand (actor +0x127C, +0x127E) that the move scripts and the stance rules drive; a
 * guest's model (52) gets one fixed stance from them, but each TTT1 character has
 * its own: a fist or an open hand kept, or a hand that closes on the attacks (the
 * guests.txt hands column, measured on the arcade by tools/ttt1_hands.lua). */
extern char tekken3_guest_hand(unsigned id,unsigned hand);
static void wings_step(uint32_t actor,unsigned player);
extern void __real_func_80034844(CPUState *cpu);
static unsigned hand_index(int16_t gauge) {
    if(gauge>=513)return (unsigned)(gauge-509);
    unsigned i=(unsigned)(gauge>>7);
    return i?i-1:0;
}
void __wrap_func_80034844(CPUState *cpu) {
    uint32_t actor=cpu->gpr[6],slot=cpu->gpr[4];
    int wings=0;
    if(actor==0x800a9228 || actor==0x800a9228+0x188c) {
        unsigned player=actor!=0x800a9228;
        uint32_t model=psx_mod_read_word(0x8009bd28+player*4);
        int hand=slot==model+24+56*13+48?0:slot==model+24+56*17+48?1:-1;
        int guest=psx_mod_read_half(actor+0x1c)>=FACE_TABLE_MODELS;
        if(hand>=0 && guest) {
            char grip=tekken3_guest_hand(psx_mod_read_half(actor+0x18),(unsigned)hand);
            if(grip=='F')cpu->gpr[5]=3;
            else if(grip=='O')cpu->gpr[5]=0;
            else if(grip=='D' && hand==0)   /* the other hand's gauge: this one follows the attacks too */
                cpu->gpr[5]=hand_index((int16_t)psx_mod_read_half(actor+0x127e));
        }
        /* once a frame for each guest and for Devil Jin: the engine updates the hands every frame,
         * and this leaf is not resumed from a continuation as the part update (0x80034970) is */
        wings=hand==1 && (guest || tekken3_devil_jin_player(player)) &&
              !psx_mod_read_word(0x80095494) && !psx_mod_read_word(0x80095468);
    }
    __real_func_80034844(cpu);
    if(wings)wings_step(actor,actor!=0x800a9228);
}
extern void __real_func_800293BC(CPUState *cpu);
void __wrap_func_800293BC(CPUState *cpu) {
    if((cpu->pc==0 || cpu->pc==0x800293bc) &&
       (cpu->gpr[31]==0x80034478 || cpu->gpr[31]==0x800342dc)) {
        uint32_t actor=cpu->gpr[16];
        if((actor==0x800a9228 || actor==0x800a9228+0x188c) &&
           (psx_mod_read_half(actor+0x1c)>=FACE_TABLE_MODELS ||
            tekken3_devil_jin_player(actor!=0x800a9228))) {
            cpu->gpr[2]=0;cpu->pc=cpu->gpr[31];return;
        }
    }
    __real_func_800293BC(cpu);
}
extern void __real_func_80037CBC(CPUState *cpu);
void __wrap_func_80037CBC(CPUState *cpu) {
    /* The native accessory solver initializes its angles from Jin's empty
     * accessory slots and overwrites our matrices on the next frame. Jun's
     * donor hair and bow have their own rest rotations. Keep these rigid
     * until the donor's secondary-motion solver is ported. */
    if(cpu->pc==0 || cpu->pc==0x80037cbc) {
        uint32_t actor=cpu->gpr[4];unsigned bone=cpu->gpr[5];
        for(unsigned p=0;p<2;p++) if(actor==0x800a9228+p*0x188c &&
                bone>=18 && bone<=23 &&
                tekken3_ttt1_guest_skeleton(p)) {
            const uint32_t skeleton=tekken3_ttt1_guest_skeleton(p);
            unsigned row=psx_mod_read_byte(0x8001a05c+bone);
            /* Diagnostic ponctuel : le solveur d'accessoires natif est-il bien
             * detourne pour cet invite, et sur quels os ? */
            if(getenv("TEKKEN3_GUEST_ACC")) {
                static int said[2][32];
                if(bone<32 && !said[p][bone]) { said[p][bone]=1;
                    uint32_t r=skeleton+24+row*56;
                    fprintf(stderr,"%s model: accessoire P%u os %u -> ligne %u ; "
                            "angles %08X %08X %08X\n",name_for(p),p+1,bone,row,
                            psx_mod_read_word(r+28),psx_mod_read_word(r+32),psx_mod_read_word(r+36)); }
            }
            accessory_rotation(actor+0xf74+bone*32,skeleton+24+row*56);
            cpu->pc=cpu->gpr[31];return;
        }
    }
    __real_func_80037CBC(cpu);
}
static void rebuild_packets(uint32_t base,unsigned player) {
    plan_moves(player);
    const uint32_t actor=0x800a9228+player*0x188c;
    /* The arena's two halves in turn: a rebuild while the game is drawing
     * (the Embu changes guests mid-scene) must not rewrite packets that the
     * frame being drawn still links. A guest takes about 70 KB. */
    const uint32_t start=arena[player]+arena_half[player]*131072;
    arena_half[player]^=1;
    uint32_t next=start;
    if(tracing()) { static int once; if(!once){ once=1;
        for(unsigned i=0;i<24;i++) {
            uint32_t pt=actor+0x4f0+i*40;
            TRACE("T6|part=%2u|row=%2u|bone=%2u|word0=%08X|bundle0=%08X|bundle1=%08X|mat=%08X\n",
                  i,psx_mod_read_byte(0x8001a05c+i),psx_mod_read_byte(0x8001a074+i),
                  psx_mod_read_word(pt),psx_mod_read_word(pt+8),psx_mod_read_word(pt+12),
                  psx_mod_read_word(pt+4));
        } } }
    /* CABLAGE NATUREL, sous TEKKEN3_GUEST_WIRE=1.
     *
     * Les tables natives (0x8001a05c partie->ligne, 0x8001a074 partie->os, lues
     * dans SLUS_004.02) donnent a chaque partie SA ligne :
     *   partie  0  1  2  3  4 ... 18 19 20 21 22 23
     *   ligne   0  1  3  5  6 ... 21 22 23 24 25 26
     * Le jeu natif ne cable un emplacement que si le DONNEUR y a de la
     * geometrie. Jin est vide aux lignes 21, 24, 25 et 26, donc les parties 18,
     * 21, 22 et 23 restent debranchees -- alors que Kazuya, lui, y a 71, 4, 50
     * et 9 primitives. On rebranche chaque partie sur SA propre ligne ; ce n'est
     * pas une greffe arbitraire mais le retablissement de l'appariement prevu.
     *
     * Et ce n'est pas qu'une question de geometrie manquante : un emplacement
     * rempli mais SANS paquets est dessine par le moteur a travers les pointeurs
     * perimes du donneur -- ce que le commentaire de TEKKEN3_GUEST_TRIM_TAIL
     * supposait sans l'avoir verifie.
     *
     * [V] MAIS le cablage ne supprime PAS les artefacts : mesure a 297 puis 362
     * primitives trop etendues, et l'utilisateur les retrouve en parcourant
     * toutes les trames. Il ajoute de la geometrie (+5000 octets de paquets) et
     * ne casse rien, mais il reste OPT-IN tant qu'on ne sait pas s'il apporte
     * quelque chose. */
    if(getenv("TEKKEN3_GUEST_WIRE")) {
        unsigned wired=0;
        for(unsigned i=1;i<24;i++) {
            uint32_t part=actor+0x4f0+i*40;
            if(psx_mod_read_word(part)) continue;            /* deja active */
            unsigned row=psx_mod_read_byte(0x8001a05c+i);
            unsigned bone=psx_mod_read_byte(0x8001a074+i);
            /* Le bundle vaut base+16+slot*56 ; les donnees de l'emplacement,
             * elles, sont ecrites a base+24+slot*56 (decalage de 8). Le maillage
             * que make_packets lit est donc a bundle+16 = base+24+slot*56+8,
             * soit le MOT 2 de l'emplacement copie. */
            uint32_t rowaddr=base+16+row*56;
            if(!psx_mod_read_word(base+24+row*56+8)) continue;  /* emplacement vide */
            /* La partie est DESACTIVEE (mot 0 nul) parce que Jin n'a rien a
             * cette ligne, mais le maillage de l'invite y est. On l'arme. */
            psx_mod_write_word(part,2);
            psx_mod_write_word(part+4,actor+0x8f4+bone*68);
            psx_mod_write_word(part+8,rowaddr);
            psx_mod_write_word(part+12,0);
            wired++;
            static int said[24];
            if(!said[i]){said[i]=1;
                fprintf(stderr,"%s model: CABLAGE partie %u -> ligne %u "
                    "(os %u)\n",name_for(player),i,row,bone);}
        }
        (void)wired;
    }
    /* Seconds maillages : la ligne 2 (haut du corps) et la ligne 4 (bassin),
     * comme la ligne 20 pour la tete, se dessinent avec leur partie. */
    static const unsigned second[3][2]={{1,2},{2,4},{17,20}};
    for(unsigned k=0;k<3;k++) {
        uint32_t part=actor+0x4f0+second[k][0]*40;
        uint32_t r=base+24+second[k][1]*56;
        psx_mod_write_word(part+12,(psx_mod_read_word(r+40) && psx_mod_read_word(r+4))?
                           base+16+second[k][1]*56:0);
    }
    /* Os d'accessoires 18..23 (lignes 21..26) : rattaches a la matrice de
     * leur partie parente (mot 6), rotation de repos (mots 7..9). Le moteur
     * ne dessine que les parties 0..21 (0x80037A5C) : les parties 22 et 23
     * restent eteintes, leurs lignes passent en second maillage (plus bas). */
    for(unsigned i=22;i<=23;i++) psx_mod_write_word(actor+0x4f0+i*40,0);
    for(unsigned i=18;i<=21;i++) {
        unsigned row=psx_mod_read_byte(0x8001a05c+i),bone=psx_mod_read_byte(0x8001a074+i);
        uint32_t part=actor+0x4f0+i*40, r=base+24+row*56;
        if(!psx_mod_read_word(r+40) || !psx_mod_read_word(r+4)) { psx_mod_write_word(part,0); continue; }
        unsigned pp=psx_mod_read_word(r+24)&0xff;
        psx_mod_write_word(part,2);
        psx_mod_write_word(part+4,actor+0x8f4+bone*68);
        psx_mod_write_word(part+8,base+16+row*56);
        psx_mod_write_word(part+12,0);
        psx_mod_write_word(actor+0x8f4+bone*68+64,psx_mod_read_word(actor+0x4f0+pp*40+4));
        accessory_rotation(actor+0xf74+bone*32,r);
    }
    /* Lignes 25 et 26 : au-dela des parties 0..21 que le moteur dessine
     * (0x80037A5C). Le convertisseur y range des pieces a os rigide integre
     * aux sommets ; elles se dessinent en second maillage de leur partie
     * parente (mot 6), juste apres elle. Apres la boucle des accessoires,
     * qui remet leur second maillage a zero : la partie parente peut etre
     * un accessoire (cape d'Armor King : 24 -> 25 -> 26). */
    for(unsigned row=25;row<=26;row++) {
        uint32_t r=base+24+row*56;
        if(!psx_mod_read_word(r+40) || !psx_mod_read_word(r+4)) continue;
        unsigned pp=psx_mod_read_word(r+24)&0xff;
        if(pp<1 || pp>21 || psx_mod_read_word(actor+0x4f0+pp*40+12)) continue;
        psx_mod_write_word(actor+0x4f0+pp*40+12,base+16+row*56);
    }
    for(unsigned i=1;i<24;i++) {
        uint32_t part=actor+0x4f0+i*40;
        /* La position de l'os se copie POUR TOUTE partie, desactivee ou non.
         * Une partie sans primitive est desactivee (mot 0 a zero) des la
         * premiere trame, et ce `continue` la faisait ensuite sauter en entier
         * -- copie de position comprise. Or l'os reste un repere pour les
         * parties qui s'y rattachent, ce que le commentaire plus bas dit deja :
         * un os laisse a zero etire les maillages enfants. Chez Kazuya la
         * partie 1 est desactivee a chaque execution, donc l'os 1 n'etait
         * positionne qu'une seule fois. */
        {
            unsigned brow=psx_mod_read_byte(0x8001a05c+i);
            unsigned bbone=psx_mod_read_byte(0x8001a074+i);
            uint32_t bpos=actor+0xf88+bbone*32;
            psx_mod_write_word(bpos,   psx_mod_read_word(base+24+brow*56+12));
            psx_mod_write_word(bpos+4, psx_mod_read_word(base+24+brow*56+16));
            psx_mod_write_word(bpos+8, psx_mod_read_word(base+24+brow*56+20));
            TRACE("T7|part=%2u|bone=%2u|row=%2u|x=%08X|y=%08X|z=%08X\n",
                  i,bbone,brow,psx_mod_read_word(bpos),psx_mod_read_word(bpos+4),
                  psx_mod_read_word(bpos+8));
        }
        if(!psx_mod_read_word(part)) continue;
        unsigned produced=0;
        for(unsigned mesh=0;mesh<2;mesh++) {
            uint32_t bundle=psx_mod_read_word(part+8+mesh*4);
            if(!bundle) continue;
            for(unsigned frame=0;frame<2;frame++) {
                /* A mesh whose primitive stream is empty produces a ZERO-length
                 * packet block. Pointing the part at it would alias the next
                 * block, so two frame slots - and then two parts - would share
                 * storage and the display list would run into whatever follows.
                 * Jun never hits this: every active part of hers has primitives.
                 * Kazuya's donor row 1 has counts [0,0,0,0]. */
                uint32_t before=next;
                next=make_packets_native(bundle,next,player);
                if(next!=before)produced++;
                TRACE("T8|part=%2u|mesh=%u|frame=%u|bundle=%08X|m=%08X|bytes=%u|"
                      "from=%08X|to=%08X\n",i,mesh,frame,bundle,
                      psx_mod_read_word(bundle+16),next-before,before,next);
                psx_mod_write_word(part+24+mesh*8+frame*4,next==before?0:before);
            }
        }
        /* A part whose meshes yield no primitive at all must be switched OFF,
         * not merely given a null packet pointer: the engine keeps drawing an
         * enabled part, and whatever pointer it finds - the stale one from the
         * native donor, or the next part's block - puts the display list into
         * the middle of somebody else's packets. Jun never has an empty part;
         * Kazuya's part 1 is empty. */
        /* La position de l'os est copiee AVANT toute desactivation : les os
         * servent de reperes aux autres parties, et un os laisse a zero etire
         * les maillages qui s'y rattachent. */
        unsigned row=psx_mod_read_byte(0x8001a05c+i),bone=psx_mod_read_byte(0x8001a074+i);
        uint32_t pos=actor+0xf88+bone*32;
        psx_mod_write_word(pos,psx_mod_read_word(base+24+row*56+12));
        psx_mod_write_word(pos+4,psx_mod_read_word(base+24+row*56+16));
        psx_mod_write_word(pos+8,psx_mod_read_word(base+24+row*56+20));
        /* Bissection : TEKKEN3_GUEST_DISABLE_PARTS=2,6,20 desactive ces parties
         * au moment de la construction, sans toucher au modele. Retirer des
         * lignes a l'export casse la traversee du moteur (les mots 12 et 13
         * portent les pointeurs de fin de bloc), donc c'est ici qu'il faut
         * isoler une partie, pas dans prepare_kazuya_import.py. */
        if(!disabled_part(i)) { /* rien */ } else produced=0;
        /* Une piece desactivee n'est plus parcourue du tout par le moteur, donc
         * son bloc de sommets n'est jamais transforme. Les pieces voisines qui
         * s'appuient dessus lisent alors une case vierge -- (0,0) -- ou celle
         * du voisin. Sous TEKKEN3_GUEST_KEEP_EMPTY on garde la piece armee et
         * on lui reserve un bloc a elle, delie de la liste d'affichage (octet
         * de tete du lien a zero) : rien ne se dessine, mais le moteur passe. */
        if(!produced && !getenv("TEKKEN3_GUEST_DROP_EMPTY")) {
            for(unsigned mesh=0;mesh<2;mesh++) {
                if(!psx_mod_read_word(part+8+mesh*4)) continue;
                for(unsigned frame=0;frame<2;frame++) {
                    for(unsigned j=0;j<32;j+=4) psx_mod_write_word(next+j,0);
                    psx_mod_write_word(part+24+mesh*8+frame*4,next);
                    next+=32;
                }
            }
            TRACE("T8keep|part=%2u|reserve=%08X\n",i,next);
            produced=1;
        }
        if(!produced) {
            psx_mod_write_word(part,0);
            fprintf(stderr,"%s model: partie %u sans primitive, desactivee "
                    "(os %u conserve)\n",name_for(player),i,bone);
        }
    }
    TRACE("T8total|player=%u|bytes=%u\n",player+1,next-start);
    fprintf(stderr,"%s model: P%u prepared %u packet bytes\n",name_for(player),player+1,next-start);
    if(next-start>131072)fprintf(stderr,"%s model: P%u packets overflow half the arena\n",name_for(player),player+1);
    upload_textures(player);
}
static void player_tick(unsigned player) {
    if (!guest_player(player)) return;
    /* Early fight substates still use fighter VRAM as a loading scratchpad.
     * Wait for the native actor/stage initialization before installing donor
     * packets and textures, otherwise a later MoveImage copies them on screen. */
    if(psx_mod_read_word(0x800ae204)!=8 || psx_mod_read_half(0x800ae224)<6)return;
    uint32_t base=psx_mod_read_word(0x8009bd28u+player*4);
    if (base<0x80100000 || base>0x801f8000 ||
        psx_mod_read_word(base)!=27 || psx_mod_read_word(base+8)!=0x4b4d4433) return;
    if (psx_mod_read_word(base+24)==models[player].memory+models[player].first_block) {
        /* Mirror matches may share a model header, but GPU packets and VRAM
         * pages belong to the individual actor. */
        if(original_base[player]!=base) {
            original_base[player]=base;
            memcpy(original_header[player],original_header[1-player],sizeof original_header[player]);
        }
        uint32_t packet=psx_mod_read_word(0x800a9228+player*0x188c+0x4f0+40+24);
        if(packet && (packet<arena[player] || packet>=arena[player]+262144))rebuild_packets(base,player);
        return;
    }
    /* Exact Jin punch-costume envelope. No other fighter or costume qualifies. */
    if (psx_mod_read_word(base+24)!=base+0x620 ||
        psx_mod_read_word(base+80)!=base+0x98c ||
        psx_mod_read_word(base+24+19*56)!=base+0x5714) return;
    /* A Jin mirror may share one model header between both actors: replacing
     * it would redraw the plain Jin too. */
    if(tekken3_devil_jin_player(player) && !guest_player(1-player) &&
       psx_mod_read_word(0x8009bd28u+(1-player)*4)==base) {
        static int said;
        if(!said){said=1;fprintf(stderr,"Devil Jin: P%u shares Jin's model with the other player, left as is\n",player+1);}
        return;
    }
    original_base[player]=base;
    for(unsigned i=0;i<384;i++) original_header[player][i]=psx_mod_read_word(base+i*4);
    psx_mod_write_word(base+16,models[player].memory+models[player].payload);
    for (unsigned i=0;i<27;i++)
        for (unsigned j=0;j<56;j+=4)
            psx_mod_write_word(base+24+i*56+j,psx_mod_read_word(models[player].memory+24+i*56+j));
    if(tracing()) for(unsigned i=0;i<27;i++) {
        uint32_t s=base+24+i*56;
        TRACE("T5|slot=%2u|m0=%08X|m1=%08X|m2=%08X|pos=%08X,%08X,%08X\n",
              i,psx_mod_read_word(s),psx_mod_read_word(s+4),psx_mod_read_word(s+8),
              psx_mod_read_word(s+12),psx_mod_read_word(s+16),psx_mod_read_word(s+20));
    }
    /* EXPERIMENT (TEKKEN3_GUEST_TRIM_TAIL=1): rebuild_packets only walks native
     * parts 1..23, so a donor mesh landing in slot 24+ never gets packets of
     * its own - and the engine may still draw it through Jin's stale pointers.
     * Jun never hits this (her rows 26..29 are empty); Kazuya does. Blanking
     * those slots tells us whether they are the source of the stray geometry. */
    if (getenv("TEKKEN3_GUEST_TRIM_TAIL")) {
        for (unsigned i=24;i<27;i++) {
            psx_mod_write_word(base+24+i*56,0);
            psx_mod_write_word(base+24+i*56+4,0);
            psx_mod_write_word(base+24+i*56+8,0);
        }
        fprintf(stderr,"%s model: blanked native mesh slots 24..26 (experiment)\n",name_for(player));
    }
    /* TEKKEN3_GUEST_TRIM_HEAD=1 : blanchit aussi les mots 0 et 1 des memes
     * emplacements. La boucle ci-dessus ne touche que les mots 2, 3 et 4, et la
     * copie des lignes de l'invite part elle aussi du mot 2 -- donc les mots 0
     * et 1 de ces emplacements gardent les valeurs PERIMEES de Jin, que rien ne
     * recouvre. Le mot 0 est le pointeur du flux de sommets que lit le renderer
     * (`lw $24,0($4)` en 8010DCD0). C'est le seul endroit ou un pointeur mort
     * survit a tout ce qu'on a essaye. */
    if (getenv("TEKKEN3_GUEST_TRIM_HEAD")) {
        for (unsigned i=24;i<27;i++) {
            psx_mod_write_word(base+16+i*56,0);
            psx_mod_write_word(base+16+i*56+4,0);
        }
        fprintf(stderr,"%s model: blanchi les mots 0 et 1 des emplacements 24..26\n",name_for(player));
    }
    rebuild_packets(base,player);
    psx_mod_write_word(control+4,base);
    psx_mod_write_word(control+8,psx_mod_read_word(control+8)+1);
    fprintf(stderr,"%s model: P%u Jin model header replaced at %08X\n",name_for(player),player+1,base);
}
/* Attract-mode Embu (state 6) with guests. The launcher's Embu TTT feature
 * (one choice per native of the Embu) or TEKKEN3_EMBU_CAST, which wins, lists
 * native=guest pairs by key, e.g. "hwoarang=baek,jin=kazuya". The Embu keeps
 * its 13 models loaded and activates one per side with 0x80035B28
 * (0x800ADEC8 + 4 * side, relocated in place). The guest's rows are grafted
 * on whichever native model is active, as a fight grafts them on Jin's, and
 * the stock header goes back before the next activation. The Embu's own
 * clips drive the skeleton: no TTT1 motion. */
extern int tekken3_guest_id(const char *key);
extern void tekken3_guest_follow(unsigned player,unsigned id,unsigned costume);
static const char *const t3_keys[20]={"paul","law","lei","king","yoshimitsu","nina","hwoarang","xiaoyu",
    "eddy","jin","julia","kuma","bryan","heihachi","ogre","mokujin","gunjack","gon","anna","drb"};
static int embu_cast[20],embu_parsed;
static char embu_option_cast[512];
/* Activation of the Embu TTT feature: its options become the casting. */
static void activate_embu(void) {
    static const char *const natives[]={"hwoarang","paul","law","nina","xiaoyu","yoshimitsu","lei","jin","eddy","king"};
    size_t n=0;
    embu_option_cast[0]=0;
    for(unsigned i=0;i<sizeof natives/sizeof *natives;i++) {
        char guest[32];
        if(!psx_mod_option_value("tekken3.character.ttt1","ttt1-embu",natives[i],guest,sizeof guest) ||
           !strcmp(guest,"none"))continue;
        int w=snprintf(embu_option_cast+n,sizeof embu_option_cast-n,"%s%s=%s",n?",":"",natives[i],guest);
        if(w<0 || (size_t)w>=sizeof embu_option_cast-n)break;
        n+=(size_t)w;
    }
    embu_parsed=0;
}
/* embu_activated: the Embu itself activated a model on that side since state
 * 6 began. On entering state 6 after a fight (the attract demo fight, Eddy
 * against Lei), the actors still carry the fight's IDs and 0x800ADEC8 still
 * points at the fight's models, in memory the Embu is loading over: a graft
 * there, and the header put back later, wrote over the freshly loaded Embu
 * data (stage textures garbled, sometimes a crash). */
static uint32_t embu_base[2],embu_header[2][384],embu_seen[2],embu_activated[2];
static int embu_native[2];
static void embu_parse(void) {
    if(embu_parsed)return;
    embu_parsed=1;
    for(unsigned i=0;i<20;i++)embu_cast[i]=-1;
    const char *e=getenv("TEKKEN3_EMBU_CAST");
    if(!e || !*e)e=embu_option_cast;
    char list[512];
    if(!e || snprintf(list,sizeof list,"%s",e)>=(int)sizeof list)return;
    for(char *pair=strtok(list,",");pair;pair=strtok(NULL,",")) {
        char *guest=strchr(pair,'=');
        if(!guest)continue;
        *guest++=0;
        int id=tekken3_guest_id(guest);
        for(unsigned i=0;i<20;i++)if(!strcmp(pair,t3_keys[i])) {
            embu_cast[i]=id;
            fprintf(stderr,"TTT1 Embu: %s plays %s%s\n",guest,pair,id<0?" (unknown guest, ignored)":"");
        }
    }
}
static void embu_restore(unsigned player) {
    if(!embu_base[player])return;
    for(unsigned i=0;i<384;i++)psx_mod_write_word(embu_base[player]+i*4,embu_header[player][i]);
    fprintf(stderr,"TTT1 Embu: P%u stock header back at %08X\n",player+1,embu_base[player]);
    embu_base[player]=0;
}
static int embu_guest_on(unsigned player){return player<2 && embu_base[player];}
/* The native whose part the guest on that side plays, -1 without one. Not
 * the actor's ID: a new part sets it a frame before its model goes active,
 * while the previous guest is still grafted. */
int tekken3_ttt1_embu_native(unsigned player) {
    return player<2 && psx_mod_read_word(0x800ae204)==6 && embu_base[player] &&
           embu_base[player]==psx_mod_read_word(0x800adec8+player*4)?embu_native[player]:-1;
}
extern void __real_func_80035B28(CPUState *cpu);
void __wrap_func_80035B28(CPUState *cpu) {
    unsigned side=2;
    if((cpu->pc==0 || cpu->pc==0x80035b28) && psx_mod_read_word(0x800ae204)==6) {
        side=psx_mod_read_byte(cpu->gpr[4]+0x1e);
        if(side<2)embu_restore(side);
    }
    __real_func_80035B28(cpu);
    if(side<2)embu_activated[side]=1;
}
/* The model whose rows carry a player's guest skeleton, the fight's Jin
 * envelope or the Embu's active model; 0 for a native actor. Native poses
 * are converted to the guest's bone bases while it is set. */
uint32_t tekken3_ttt1_guest_skeleton(unsigned player) {
    if(player>1)return 0;
    /* A native fighter on its TTT1 moves (mode 4) keeps its own bases. */
    unsigned mode=tekken3_ttt1_player_motion_mode(player);
    if(mode)return mode!=4?original_base[player]:0;
    return psx_mod_read_word(0x800ae204)==6 && embu_base[player]==psx_mod_read_word(0x800adec8+player*4)?embu_base[player]:0;
}
/* Yoshimitsu's sword glow (0x8003172C: actor +0x18 == 4, or Mokujin on
 * his moves) follows the native ID, which an Embu guest keeps: none for a
 * guest. */
extern void __real_func_8003172C(CPUState *cpu);
void __wrap_func_8003172C(CPUState *cpu) {
    if(cpu->pc==0 || cpu->pc==0x8003172c)
        for(unsigned p=0;p<2;p++)if(cpu->gpr[4]==0x800a9228+p*0x188c && tekken3_ttt1_guest_skeleton(p)) {
            cpu->pc=cpu->gpr[31];return;
        }
    __real_func_8003172C(cpu);
}
extern void tekken3_embu_scenes_tick(void);
extern void tekken3_ttt1_embu_effects(void);
extern void tekken3_ttt1_embu_light(int embu);
static void embu_tick(void) {
    tekken3_embu_scenes_tick();
    /* The lightning pack and light of a cinematic: the Embu's or a fight's
     * cutscene of ours. */
    int cine=tekken3_cine_frame()>=0;
    if(cine)tekken3_ttt1_embu_effects();
    tekken3_ttt1_embu_light(cine);
    embu_parse();
    /* A fight's cutscene of ours (tekken3_embu_scenes.c) draws the fight's
     * guests themselves: only their textures change. */
    if(psx_mod_read_word(0x800ae204)==8)
        for(unsigned p=0;p<2;p++) {
            static const char *shown[2];
            const char *model=embu_model(p);
            if(model==shown[p] || !models[p].first_block) continue;
            shown[p]=model;
            char tim[32];size_t n;
            snprintf(tim,sizeof tim,"arcade-P%u.tim",models[p].costume+1);
            if((n=read_asset(p,tekken3_ttt1_asset_root(),tim,models[p].textures,sizeof models[p].textures))) {
                models[p].textures_size=n;upload_textures(p);
                fprintf(stderr,"TTT1 cinematic: P%u textures of %s\n",p+1,model?model:"its guest");
            }
        }
    if(psx_mod_read_word(0x800ae204)!=6) {
        embu_base[0]=embu_base[1]=embu_seen[0]=embu_seen[1]=0;   /* the Embu's models are gone */
        embu_activated[0]=embu_activated[1]=0;
        return;
    }
    for(unsigned p=0;p<2;p++) {
        if(!embu_activated[p])continue;
        const uint32_t actor=0x800a9228+p*0x188c;
        unsigned native=psx_mod_read_half(actor+0x14)>>2;
        int id=native<20?embu_cast[native]:-1;
        uint32_t base=psx_mod_read_word(0x800adec8+p*4);
        if(id<0 || base<0x80100000 || base>0x801f8000 || psx_mod_read_word(base)!=27 ||
           psx_mod_read_word(base+8)!=0x4b4d4433 || psx_mod_read_word(base+24)<0x80000000)continue;
        if(embu_base[p]==base) {
            uint32_t packet=psx_mod_read_word(actor+0x4f0+40+24);
            if(packet && (packet<arena[p] || packet>=arena[p]+262144))rebuild_packets(base,p);
            continue;
        }
        /* Graft once the activation has settled: same model two ticks running. */
        if(embu_seen[p]!=base){embu_seen[p]=base;continue;}
        tekken3_guest_follow(p,(unsigned)id,0);
        follow_models();
        if(!models[p].first_block)continue;
        for(unsigned i=0;i<384;i++)embu_header[p][i]=psx_mod_read_word(base+i*4);
        psx_mod_write_word(base+16,models[p].memory+models[p].payload);
        for(unsigned i=0;i<27;i++)
            for(unsigned j=0;j<56;j+=4)
                psx_mod_write_word(base+24+i*56+j,psx_mod_read_word(models[p].memory+24+i*56+j));
        embu_base[p]=base;embu_native[p]=(int)native;
        rebuild_packets(base,p);
        fprintf(stderr,"TTT1 Embu: P%u %s on %s's model at %08X\n",p+1,tekken3_guest_name_for(p),t3_keys[native],base);
    }
}
static void guest_tick(void) {
    if (!psx_mod_game_started()) return;
    if (!attempted) { attempted=1; load_assets(); }
    if (!control) return;
    /* The loading screen names each player's fighter and costume: the
     * request only stands for Jin in his punch costume. */
    if(psx_mod_read_word(0x800ae204)==11)
        for(unsigned p=0;p<2;p++)
            if(devil_jin[p] && (psx_mod_read_half(0x800add5c+p*2)!=JIN_ID ||
                                (psx_mod_read_half(0x800add98+p*2)&3)!=0))
                tekken3_devil_jin_set(p,0);
    follow_models();
    embu_tick();
    tekken3_ttt1_selector_tick();
    tekken3_ttt1_voices_tick();
    /* Before the return below: a reset leaves the fight with the flag down,
     * and the selector's icons must come back all the same. */
    icon_tick();
    moved_tick();
    attack_label_tick();      /* natives' fights too */
    if (initializing || !psx_mod_read_byte(control)) return;
    for(unsigned player=0;player<2;player++)player_tick(player);
    for(unsigned player=0;player<2;player++)movelist_tick(player);
    combo_tick();
    tekken3_ttt1_combat_tick();
}
PSX_MOD_CONSTRUCTOR(register_ttt1_characters) {
    (void)psx_mod_register_vblank_plugin("tekken3.ttt1-characters",guest_tick);
    (void)psx_mod_register_activation_plugin("tekken3.ttt1-embu",activate_embu);
}
