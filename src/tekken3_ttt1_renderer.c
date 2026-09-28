#include "psx_runtime.h"
#include <stdio.h>
#include <string.h>
#include <math.h>
#include <stdlib.h>
#include "mod_plugins.h"
#include "gpu.h"
#include "tekken3_ttt1_assets.h"

extern void __real_func_80036CAC(CPUState *cpu);

/* Sonde TEKKEN3_NATIVE_PROBE=<fichier>, chemin NATIF uniquement.
 *
 * Pour chaque appel au transformeur de sommets natif pendant un combat, on
 * enregistre les arguments, les registres GTE a l'entree (la matrice que le
 * moteur projette reellement) et, au retour, le scratchpad entier et les deux
 * caches permanents. C'est la verite de terrain sur la numerotation des
 * emplacements de sommets, que la lecture statique n'a pas su etablir.
 *
 * On enregistre NATIVE_PROBE_CALLS appels consecutifs par combinaison de
 * modeles chargee (J1, J2), une fois le combat installe, puis on se tait. */
#define NATIVE_PROBE_CALLS 400u
static FILE *native_probe;
static void native_probe_record(CPUState *cpu, const uint32_t in[4],
                                const uint32_t gte_ctrl[32], const uint32_t gte_data[32],
                                int guest) {
    static int state=-1;
    static uint32_t key, seen, done_keys[8]; static unsigned ndone;
    if(state<0) {
        const char *path=getenv("TEKKEN3_NATIVE_PROBE");
        state=path && *path && (native_probe=fopen(path,"wb"))!=NULL;
    }
    if(!state) return;
    if(psx_mod_read_word(0x800ae204u)!=8) { seen=0; return; }
    uint32_t m1=psx_mod_read_word(0x8009bd28u), m2=psx_mod_read_word(0x8009bd2cu);
    if(!m1 || !m2) return;
    uint32_t k=psx_mod_read_word(m1+80)-m1+(psx_mod_read_word(m2+80)-m2)*65536u;
    for(unsigned i=0;i<ndone;i++) if(done_keys[i]==k) return;
    if(k!=key) { key=k; seen=0; }
    if(++seen<600) return;                       /* laisser le combat demarrer */
    /* PROB : chemin natif ; PROG : renderer arcade de l'invite (TTT1). */
    uint32_t hdr[8]={guest?0x474F5250u:0x424F5250u, seen, m1, m2, in[0], in[1], in[2], in[3]};
    fwrite(hdr,4,8,native_probe);
    fwrite(gte_ctrl,4,32,native_probe);
    fwrite(gte_data,4,32,native_probe);
    uint32_t buf[256];
    for(unsigned i=0;i<256;i++) buf[i]=psx_mod_read_word(0x1F800000u+i*4);
    fwrite(buf,4,256,native_probe);
    for(unsigned i=0;i<256;i++) buf[i]=psx_mod_read_word(0x8009BD4Cu+i*4);
    fwrite(buf,4,256,native_probe);
    for(unsigned i=0;i<256;i++) buf[i]=psx_mod_read_word(0x8009CD4Cu+i*4);
    fwrite(buf,4,256,native_probe);
    /* Zone de travail du renderer arcade (cache de sommets a 8009D550). */
    for(unsigned b=0;b<4;b++) {
        for(unsigned i=0;i<256;i++) buf[i]=psx_mod_read_word(0x8009D000u+b*1024+i*4);
        fwrite(buf,4,256,native_probe);
    }
    if(seen>=600+NATIVE_PROBE_CALLS) {
        fflush(native_probe);
        /* Instantane RAM + VRAM du meme combat, a cote du fichier de sonde :
         * les textures du costume y sont posees exactement comme le jeu les
         * utilise, ce que les TIM du disque ne donnent pas directement. */
        {
            char path[1024];
            snprintf(path,sizeof path,"%s.%u.ram",getenv("TEKKEN3_NATIVE_PROBE"),ndone);
            FILE *f=fopen(path,"wb");
            if(f) { for(uint32_t a=0;a<0x200000u;a+=4){uint32_t w=psx_mod_read_word(0x80000000u+a);fwrite(&w,4,1,f);} fclose(f); }
            snprintf(path,sizeof path,"%s.%u.vram",getenv("TEKKEN3_NATIVE_PROBE"),ndone);
            f=fopen(path,"wb");
            if(f) { for(int y=0;y<512;y++) for(int x=0;x<1024;x++){uint16_t p=gpu_vram_peek(x,y);fwrite(&p,2,1,f);} fclose(f); }
        }
        if(ndone<8) done_keys[ndone++]=k;
        fprintf(stderr,"native probe: %u appels enregistres pour J1=%08X J2=%08X\n",
                NATIVE_PROBE_CALLS,m1,m2);
    }
    (void)cpu;
}


/* Rayon laser visible (Devil / Angel). Le jeu TTT1 le dessine par son propre
 * systeme d'effets ; ici, juste apres la tete de l'invite (ligne 19), le rayon
 * calcule par le combat (tekken3_laser_beam) est ramene dans le repere de la
 * tete, projete avec l'etat GTE de la tete (meme camera que le modele), puis
 * emis en paquet GPU : mode additif, halo large puis coeur fin, en degrade,
 * chaine au premier plan de la table d'ordre (double tampon comme le jeu). */
extern int tekken3_laser_beam(unsigned p,int32_t v[6]);
static void project_beam(const uint32_t *ctrl,uint32_t actor,const int32_t w[3],double out[3]) {
    uint32_t bone=actor+0x8f4+2*68;
    double m[9],d[3],l[3],c[3];
    for(unsigned i=0;i<9;i++) m[i]=(int16_t)psx_mod_read_half(bone+i*2)/4096.0;
    for(unsigned i=0;i<3;i++) d[i]=w[i]-(double)(int32_t)psx_mod_read_word(bone+0x14+i*4);
    for(unsigned i=0;i<3;i++) l[i]=m[i]*d[0]+m[3+i]*d[1]+m[6+i]*d[2];          /* M^T (w - p) */
    int16_t r[9]={(int16_t)ctrl[0],(int16_t)(ctrl[0]>>16),(int16_t)ctrl[1],(int16_t)(ctrl[1]>>16),
                  (int16_t)ctrl[2],(int16_t)(ctrl[2]>>16),(int16_t)ctrl[3],(int16_t)(ctrl[3]>>16),(int16_t)ctrl[4]};
    for(unsigned i=0;i<3;i++) c[i]=(r[i*3]*l[0]+r[i*3+1]*l[1]+r[i*3+2]*l[2])/4096.0+(double)(int32_t)ctrl[5+i];
    double h=(double)(ctrl[26]&0xffff),z=c[2]<1?1:c[2];
    out[0]=(int32_t)ctrl[24]/65536.0+h*c[0]/z; out[1]=(int32_t)ctrl[25]/65536.0+h*c[1]/z; out[2]=c[2];
}
static void draw_laser_beam(const uint32_t *ctrl,uint32_t ot,unsigned p) {
    int32_t v[6];
    if(!tekken3_laser_beam(p,v)) return;
    /* Un paquet par joueur et par tampon : les deux rayons peuvent partir
     * dans la meme image. */
    static uint32_t bufs[2][2];
    uint32_t *buf=bufs[p];
    if(!buf[0]) { buf[0]=psx_mod_alloc_gpu_dma_memory(128,16); buf[1]=psx_mod_alloc_gpu_dma_memory(128,16); }
    if(!buf[0] || !buf[1]) return;
    uint32_t actor=0x800a9228+p*0x188c;
    double a[3],b[3];
    project_beam(ctrl,actor,v,a); project_beam(ctrl,actor,v+3,b);
    if(a[2]<=0 || b[2]<=0) return;
    double dx=b[0]-a[0],dy=b[1]-a[1],len=sqrt(dx*dx+dy*dy);
    if(len<1) return;
    double px=-dy/len,py=dx/len;
    uint32_t pkt=buf[(ot>>12)&1],o=pkt+4;
    #define XY(x,y) ((((uint32_t)(int32_t)(y))&0xffff)<<16|(((uint32_t)(int32_t)(x))&0xffff))
    psx_mod_write_word(o,0xE1000000u|(1u<<5)|(1u<<9)|(1u<<10)); o+=4;     /* additif */
    static const struct { double w0,w1; uint32_t c0,c1; } layer[2]={
        {9,14,0x103070u,0x081840u},     /* halo : orange sombre (BGR) */
        {2.5,4,0x50E0FFu,0x2090C0u},    /* coeur : jaune vif vers orange */
    };
    for(unsigned k=0;k<2;k++) {
        double w0=layer[k].w0,w1=layer[k].w1;
        psx_mod_write_word(o,0x3A000000u|layer[k].c0); psx_mod_write_word(o+4,XY(a[0]+px*w0,a[1]+py*w0));
        psx_mod_write_word(o+8,layer[k].c0);           psx_mod_write_word(o+12,XY(a[0]-px*w0,a[1]-py*w0));
        psx_mod_write_word(o+16,layer[k].c1);          psx_mod_write_word(o+20,XY(b[0]+px*w1,b[1]+py*w1));
        psx_mod_write_word(o+24,layer[k].c1);          psx_mod_write_word(o+28,XY(b[0]-px*w1,b[1]-py*w1));
        o+=32;
    }
    #undef XY
    uint32_t words=(o-pkt-4)/4, slot=ot+4;                                  /* pres de l'avant */
    psx_mod_write_word(pkt,(psx_mod_read_word(slot)&0xffffffu)|(words<<24));
    psx_mod_write_word(slot,pkt&0xffffffu);
}

/* Lame lumineuse d'Unknown sur les movesets de Yoshimitsu et de Kunimitsu.
 * TTT1 (0x80103064, corps 0x21 seulement) la dessine par son systeme de
 * trainees : quatre points dans le repere d'un noeud de main (garde x3 puis
 * pointe), projetes, puis des quads additifs de part et d'autre de la ligne
 * garde -> pointe, largeur ecran 1200 / z, couleur 0xC04040 sur une texture en
 * degrade (clair au centre, noir au bord). La pointe pousse de 0x20 par image
 * jusqu'a 0x100 (compteur 0x80243610 + 2 * joueur).
 *   Yoshimitsu (moveset 4) : noeud 5 (+0xD98, ligne TTT1 20 -> os T3 10),
 *     garde (60, -30, 70), pointe z = 20 + compteur * 950 / 256 ;
 *   Kunimitsu (moveset 26) : noeud 3 (+0xC58, ligne TTT1 16 -> os T3 6),
 *     garde (60, 30, -80), pointe z = -20 - compteur * 490 / 256.
 * Les lignes TTT1 passent aux os T3 comme le modele (convert.py : S2T, P2R,
 * PART_BONE), dont les reperes d'os sont ceux de TTT1. */
static void draw_blade(const uint32_t *ctrl,uint32_t ot,unsigned p) {
    static unsigned grow[2],last[2];
    unsigned moveset=tekken3_guest_switches_on_button(p)?tekken3_guest_moveset(p):0;
    if(moveset!=last[p]) { last[p]=moveset; grow[p]=0; }
    if(moveset!=4 && moveset!=26) return;
    if(grow[p]<0x100) grow[p]+=0x20;
    int yoshimitsu=moveset==4;
    unsigned bone=yoshimitsu?10:6;
    double hilt[3]={60,yoshimitsu?-30:30,yoshimitsu?70:-80},tip[3]={hilt[0],hilt[1],
        yoshimitsu?20+grow[p]*950/256.0:-20-grow[p]*490/256.0};
    static uint32_t bufs[2][2];
    uint32_t *buf=bufs[p];
    if(!buf[0]) { buf[0]=psx_mod_alloc_gpu_dma_memory(160,16); buf[1]=psx_mod_alloc_gpu_dma_memory(160,16); }
    if(!buf[0] || !buf[1]) return;
    uint32_t actor=0x800a9228+p*0x188c,m=actor+0x8f4+bone*68;
    double r[9];int32_t w[2][3];
    for(unsigned i=0;i<9;i++) r[i]=(int16_t)psx_mod_read_half(m+i*2)/4096.0;
    for(unsigned k=0;k<2;k++) {
        const double *l=k?tip:hilt;
        for(unsigned i=0;i<3;i++)
            w[k][i]=(int32_t)psx_mod_read_word(m+0x14+i*4)+(int32_t)(r[i*3]*l[0]+r[i*3+1]*l[1]+r[i*3+2]*l[2]);
    }
    double a[3],b[3];
    project_beam(ctrl,actor,w[0],a); project_beam(ctrl,actor,w[1],b);
    if(a[2]<=0 || b[2]<=0) return;
    double dx=b[0]-a[0],dy=b[1]-a[1],len=sqrt(dx*dx+dy*dy);
    if(len<1) return;
    dx/=len; dy/=len;
    /* Demi-largeur : 60 unites a la profondeur de la garde (TTT1 : environ
     * 7,5 pixels pour une lame de 900 unites a 105 pixels). */
    double h=(double)(ctrl[26]&0xffff),half=h*60/a[2];
    if(half<1) half=1;
    double px=-dy*half,py=dx*half;
    uint32_t pkt=buf[(ot>>12)&1],o=pkt+4;
    #define XY(x,y) ((((uint32_t)(int32_t)(y))&0xffff)<<16|(((uint32_t)(int32_t)(x))&0xffff))
    psx_mod_write_word(o,0xE1000000u|(1u<<5)|(1u<<9)|(1u<<10)); o+=4;     /* additif */
    const uint32_t core=0xFF8080u,edge=0;                                     /* BGR : 2 x 0xC04040 */
    for(int side=-1;side<=1;side+=2) {
        /* bout arrondi derriere la garde, puis la lame jusqu'a la pointe */
        double ex=px*side,ey=py*side;
        psx_mod_write_word(o,0x3A000000u|core); psx_mod_write_word(o+4,XY(a[0]-dx*half,a[1]-dy*half));
        psx_mod_write_word(o+8,edge);            psx_mod_write_word(o+12,XY(a[0]-dx*half+ex,a[1]-dy*half+ey));
        psx_mod_write_word(o+16,core);           psx_mod_write_word(o+20,XY(a[0],a[1]));
        psx_mod_write_word(o+24,edge);           psx_mod_write_word(o+28,XY(a[0]+ex,a[1]+ey));
        o+=32;
        psx_mod_write_word(o,0x3A000000u|core); psx_mod_write_word(o+4,XY(a[0],a[1]));
        psx_mod_write_word(o+8,edge);            psx_mod_write_word(o+12,XY(a[0]+ex,a[1]+ey));
        psx_mod_write_word(o+16,core);           psx_mod_write_word(o+20,XY(b[0],b[1]));
        psx_mod_write_word(o+24,edge);           psx_mod_write_word(o+28,XY(b[0]+ex,b[1]+ey));
        o+=32;
    }
    #undef XY
    uint32_t words=(o-pkt-4)/4, slot=ot+4;
    psx_mod_write_word(pkt,(psx_mod_read_word(slot)&0xffffffu)|(words<<24));
    psx_mod_write_word(slot,pkt&0xffffffu);
}

void __wrap_func_80036CAC(CPUState *cpu) {
    {
        uint32_t in[4]={cpu->gpr[4],cpu->gpr[5],cpu->gpr[6],cpu->gpr[7]}, pc0=cpu->pc, ra=cpu->gpr[31], actor=cpu->gpr[17];
        uint32_t ctrl[32], data[32];
        memcpy(ctrl,cpu->gte_ctrl,sizeof ctrl); memcpy(data,cpu->gte_data,sizeof data);
        /* TEKKEN3_GUEST_NATIVE_LOG=1 : trace chaque piece du modele natif de
         * l'invite a l'entree et a la sortie du renderer natif (premiers appels
         * seulement). Une entree sans sortie designe la piece qui bloque. */
        static int nlog=-1; static unsigned nlogged;
        if(nlog<0) nlog=getenv("TEKKEN3_GUEST_NATIVE_LOG")?1:0;
        uint32_t m1=psx_mod_read_word(0x8009bd28u), m2=psx_mod_read_word(0x8009bd2cu);
        int mine=nlog && nlogged<400 && m1 && in[0]>=m1 && in[0]<m1+27*56+24;
        if(mine) { fprintf(stderr,"native log: entree ligne %u (a0=%08X)\n",(in[0]-m1-16)/56,in[0]); fflush(stderr); }
        __real_func_80036CAC(cpu);
        /* Apres la tete (ligne 19) : rayon et lame du joueur dessine. Ses
         * deux appels (0x80037A00, 0x80037A30) lisent la ligne et les paquets
         * dans l'acteur en s1 ; en miroir, les deux joueurs partagent l'en-tete
         * de modele (m1 == m2) et seul s1 dit lequel est dessine. */
        int who=actor==0x800a9228u?0:actor==0x800aaab4u?1:-1;
        for(unsigned p=0;p<2;p++) {
            uint32_t m=p?m2:m1;
            if(!m || in[0]!=m+16+19*56 || (who>=0?(unsigned)who!=p:(p && m2==m1))) continue;
            draw_laser_beam(ctrl,in[2],p); draw_blade(ctrl,in[2],p);
        }
        if(mine) { nlogged++; fprintf(stderr,"native log: sortie ligne %u pc=%08X\n",(in[0]-m1-16)/56,cpu->pc); fflush(stderr); }
        {
            static unsigned said;
            if(said<3 && getenv("TEKKEN3_NATIVE_PROBE")) { said++;
                fprintf(stderr,"native probe: appel a0=%08X pc entree=%08X ra=%08X pc sortie=%08X\n",
                        in[0],pc0,ra,cpu->pc); }
        }
        native_probe_record(cpu,in,ctrl,data,0);
    }
}

extern void tekken3_ttt1_before_init(uint32_t model);
extern void tekken3_ttt1_after_init(void);
extern void __real_func_80035BC0(CPUState *cpu);
void __wrap_func_80035BC0(CPUState *cpu) {
    static uint32_t return_pc;
    if(cpu->pc==0 || cpu->pc==0x80035bc0) {
        return_pc=cpu->gpr[31];
        tekken3_ttt1_before_init(cpu->gpr[6]);
    }
    __real_func_80035BC0(cpu);
    if(cpu->pc==return_pc) tekken3_ttt1_after_init();
}

extern void __real_func_80035190(CPUState *cpu);
void __wrap_func_80035190(CPUState *cpu) {
    static uint32_t return_pc;
    if(cpu->pc==0 || cpu->pc==0x80035190) {
        return_pc=cpu->gpr[31];
        tekken3_ttt1_before_init(cpu->gpr[4]);
    }
    __real_func_80035190(cpu);
    if(cpu->pc==return_pc) tekken3_ttt1_after_init();
}

extern void __real_func_80035CE8(CPUState *cpu);
void __wrap_func_80035CE8(CPUState *cpu) {
    static uint32_t return_pc;
    if(cpu->pc==0 || cpu->pc==0x80035ce8) {
        return_pc=cpu->gpr[31];
        tekken3_ttt1_before_init(cpu->gpr[5]);
    }
    __real_func_80035CE8(cpu);
    if(cpu->pc==return_pc) tekken3_ttt1_after_init();
}
