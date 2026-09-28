/* Original 57-channel arcade poses -> PS1 local joint matrices. Mode 1 is
 * the neutral-only reference; mode 2 uses the experimental combat adapter. */
#include "psx_runtime.h"
#include "mod_plugins.h"
#include "psx_sha256.h"
#include "tekken3_ttt1_assets.h"
#include "tekken3_ttt1_basis.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern unsigned tekken3_ttt1_motion_mode(void);
extern unsigned tekken3_ttt1_player_motion_mode(unsigned player);
extern uint32_t tekken3_ttt1_guest_skeleton(unsigned player);
extern const uint16_t *tekken3_ttt1_decoded_pose(uint32_t input);
extern void __real_func_8003AD10(CPUState *cpu);
static uint16_t idle[100][57];
static int loaded;
static unsigned stance_frame, previous_frame;
static int was_neutral;

static uint32_t pose_actor(CPUState *cpu) {
    for(unsigned p=0;p<2;p++) {
        uint32_t actor=0x800a9228+p*0x188c;
        if(cpu->gpr[5]==actor+0xf74)return actor;
        /* The transition blender decodes the previous pose into its stack
         * before subtracting it from this actor's saved local matrices, and
         * the two poses it mixes (8003C728, 8003C738) into its stack too:
         * the actor is in s2 for all three. Missed, a native on its TTT1
         * moves took those poses in the arcade basis - upside down for the
         * frames of a transition. */
        if((cpu->gpr[31]==0x8003c5e0 || cpu->gpr[31]==0x8003c72c || cpu->gpr[31]==0x8003c73c) &&
           cpu->gpr[18]==actor)return actor;
    }
    return 0;
}
/* A guest's model has the arcade bases; a native fighter on its TTT1 moves
 * (mode 4) keeps its own, so the TTT1 poses change basis for it as for a
 * native thrown by a guest. */
static int arcade_skeleton(uint32_t actor) {
    return actor && tekken3_ttt1_guest_skeleton(actor==0x800aaab4)!=0;
}
static void change_basis(uint32_t output) {
    for(unsigned bone=0;bone<18;bone++) {
        int32_t m[9];
        for(unsigned n=0;n<9;n++)m[n]=(int16_t)psx_mod_read_half(output+bone*32+n*2);
        tekken3_ttt1_change_basis(m,bone,1);
        for(unsigned n=0;n<9;n++)psx_mod_write_half(output+bone*32+n*2,(uint16_t)m[n]);
    }
}

/* The neutral-only reference mode (1) poses player 1's guest in its arcade
 * stance; the file follows that guest's identity. */
static int load_motion(void) {
    static unsigned generation;
    if(generation!=tekken3_guest_moves_generation(0)){generation=tekken3_guest_moves_generation(0);loaded=0;}
    if(loaded) return loaded>0;
    loaded=-1;
    const char *root=tekken3_ttt1_asset_root();
    if(!root) return 0;
    char path[4096];
    if(snprintf(path,sizeof(path),"%s/%s-idle.poses",root,tekken3_guest_moves_prefix_for(0))>=(int)sizeof(path)) return 0;
    FILE *f=fopen(path,"rb");
    if(!f) return 0;
    int ok=fread(idle,1,sizeof(idle),f)==sizeof(idle) && fgetc(f)==EOF;
    fclose(f);
    if(ok) {
        unsigned char hash[32];char actual[65];
        psx_sha256_compute((const uint8_t*)idle,sizeof(idle),hash);
        for(unsigned i=0;i<32;i++) snprintf(actual+i*2,3,"%02x",hash[i]);
        /* Identity check only; the pose geometry checks still run. */
        ok=!tekken3_guest_digests_frozen() ||
           !strcmp(actual,"02a32dc9b370ed52e9aee028063ca918ff96bedfdf4afaf655368aacf56e0cd2");
    }
    if(ok) { loaded=1; fprintf(stderr,"%s motion: loaded original 100-frame arcade stance\n",tekken3_guest_name_for(0)); }
    return ok;
}
static int32_t mul12(int32_t a,int32_t b) { return (a*b)>>12; }
static void rotation(const uint16_t *angle,int32_t *matrix) {
    int32_t s[3],c[3];
    for(unsigned i=0;i<3;i++) {
        uint16_t a=i==2?angle[i]:(uint16_t)-angle[i];
        uint32_t table=0x8001e8c4+((a>>3)&0x1ffe);
        s[i]=(int16_t)psx_mod_read_half(table);
        c[i]=(int16_t)psx_mod_read_half(table+0x800);
    }
    int32_t a=mul12(c[0],c[2]),b=mul12(c[0],s[2]);
    int32_t d=mul12(s[0],c[2]),e=mul12(s[0],s[2]);
    int32_t m[9]={mul12(c[1],c[2]),mul12(d,s[1])-b,e+mul12(a,s[1]),
        mul12(c[1],s[2]),a+mul12(e,s[1]),mul12(b,s[1])-d,
        -s[1],mul12(s[0],c[1]),mul12(c[0],c[1])};
    for(unsigned i=0;i<9;i++) matrix[i]=m[i];
}
void __wrap_func_8003AD10(CPUState *cpu) {
    static uint32_t native_output,native_return;
    static int native_needs_basis;
    if(cpu->pc==0 || cpu->pc==0x8003ad10) {
        uint32_t actor=pose_actor(cpu);
        int donor=arcade_skeleton(actor);
        const uint16_t *p=tekken3_ttt1_decoded_pose(cpu->gpr[4]);
        if(p) {
            static int reported;
            if(!reported){reported=1;fprintf(stderr,"TTT1 characters: donor pose reached native skeleton bridge\n");}
            static uint32_t unknown_caller;
            if(!actor && unknown_caller!=cpu->gpr[31]) {
                unknown_caller=cpu->gpr[31];
                fprintf(stderr,"TTT1 characters: TTT1 pose decoded for no fighter (return %08X)\n",unknown_caller);
            }
            for(unsigned bone=0;bone<18;bone++) {
                int32_t m[9];rotation(p+3+bone*3,m);
                if(bone==0)for(unsigned n=3;n<9;n++)m[n]=-m[n];
                if(actor && !donor)tekken3_ttt1_change_basis(m,bone,0);
                for(unsigned n=0;n<9;n++)psx_mod_write_half(cpu->gpr[5]+bone*32+n*2,(uint16_t)m[n]);
            }
            cpu->pc=cpu->gpr[31];return;
        }
        native_output=cpu->gpr[5];native_return=cpu->gpr[31];
        native_needs_basis=donor;
    }
    unsigned mode=tekken3_ttt1_motion_mode();
    const uint32_t actor=0x800a9228;
    int entry=cpu->pc==0 || cpu->pc==0x8003ad10;
    int player_one=entry && cpu->gpr[5]==actor+0xf74;
    uint32_t record=psx_mod_read_word(actor+0x54);
    uint32_t clip=record>=0x80010000 && record<0x80200000 ? psx_mod_read_word(record):0;
    int neutral=clip>=0x80010000 && clip<0x80200000 &&
        psx_mod_read_word(clip)==0x38553880 && psx_mod_read_word(clip+4)==0x25242c28;
    if(player_one && mode==1 && neutral && load_motion()) {
        unsigned native_frame=(psx_mod_read_half(actor+0x58)-1u)%128;
        if(!was_neutral) stance_frame=0;
        else if(native_frame!=previous_frame) stance_frame=(stance_frame+1)%100;
        previous_frame=native_frame;was_neutral=1;
        unsigned frame=stance_frame;
        for(unsigned bone=0;bone<18;bone++) {
            int32_t m[9];rotation(idle[frame]+3+bone*3,m);
            /* Convert the donor's root basis once; all child rotations remain
             * in their original local bases, matching the imported geometry. */
            if(bone==0) for(unsigned n=3;n<9;n++) m[n]=-m[n];
            for(unsigned n=0;n<9;n++) psx_mod_write_half(cpu->gpr[5]+bone*32+n*2,(uint16_t)m[n]);
        }
        cpu->pc=cpu->gpr[31];
        return;
    }
    if(player_one) was_neutral=0;
    __real_func_8003AD10(cpu);
    if(native_needs_basis && cpu->pc==native_return) {
        change_basis(native_output);native_needs_basis=0;
    }
}
