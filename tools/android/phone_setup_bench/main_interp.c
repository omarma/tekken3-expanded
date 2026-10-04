/* main.c with psx_interpreter.c running the same OpenBIOS routines instead of
 * the recompiled code (no cycle model: a lower bound for an interpreter). */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "cpu_state.h"
extern uint8_t *g_psx_ram; extern uint64_t psx_cycle_count;
void psx_wire(CPUState*); void psx_load_rom(const char*);
void OpenBIOS_psx_dispatch_call(CPUState*, uint32_t, uint32_t);
#define RET 0x80000100u
static CPUState cpu; static uint64_t ninsn; uint32_t interp_step(CPUState*,uint32_t); int interp_hit_breakpoint(void); int interp_break_add(uint32_t); void interp_init(CPUState*);
static uint32_t call(uint32_t fn, uint32_t a0, uint32_t a1, uint32_t a2, uint32_t a3){
  cpu.gpr[4]=a0;cpu.gpr[5]=a1;cpu.gpr[6]=a2;cpu.gpr[7]=a3;cpu.gpr[29]=0x801FFF00u;cpu.gpr[31]=RET;cpu.pc=0;
  cpu.pc=fn; while(cpu.pc!=RET){ uint32_t n=interp_step(&cpu,0x7fffffff); ninsn+=n; if(!interp_hit_breakpoint()){fprintf(stderr,"halt\n");exit(5);} } return cpu.gpr[2]; }
static double now(void){ struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec+t.tv_nsec*1e-9; }
int main(int argc,char**argv){
  psx_load_rom(argc>1?argv[1]:"openbios.bin"); psx_wire(&cpu); interp_init(&cpu); psx_wire(&cpu); interp_break_add(RET); cpu.read_absorb_which=0; cpu.read_fudge=0x20; cpu.ld_which_t=0x20;
  int reps = argc>2?atoi(argv[2]):20; enum{N=3000,REC=16};
  uint32_t base=0x80010000u, src=0x80080000u, nums=0x800C0000u;
  uint32_t seed=12345;
  for(int i=0;i<N;i++){ char s[REC]; for(int k=0;k<REC-1;k++){seed=seed*1103515245+12345; s[k]='a'+(seed>>16)%26;} s[REC-1]=0; memcpy(g_psx_ram+(src&0x1FFFFF)+i*REC,s,REC); }
  for(int i=0;i<N;i++){ char s[16]; seed=seed*1103515245+12345; snprintf(s,16,"%d",(int)(seed>>8)-(1<<22)); memcpy(g_psx_ram+(nums&0x1FFFFF)+i*16,s,16); }
  double t0=now(); uint32_t chk=0;
  for(int r=0;r<reps;r++){
    call(0xBFC085D8u, base, src, N*REC, 0);            /* memcpy */
    call(0xBFC08478u, base, N, REC, 0xBFC05A44u);      /* qsort(base,N,16,strcmp) */
    for(int i=0;i<N;i++) chk += call(0xBFC086E8u, nums+i*16, 0, 10, 0); /* strtol */
    for(int i=0;i<N;i+=4) chk += call(0xBFC059CCu, base+i*REC, 0,0,0); /* strlen */
  }
  double t=now()-t0;
  for(int i=1;i<N;i++) if(strcmp((char*)g_psx_ram+(base&0x1FFFFF)+(i-1)*REC,(char*)g_psx_ram+(base&0x1FFFFF)+i*REC)>0){fprintf(stderr,"NOT SORTED at %d\n",i);return 1;}
  printf("%.3f s  instructions=%llu  chk=%08x  (%.1f M MIPS instr/s)\n", t, (unsigned long long)ninsn, chk, ninsn/t/1e6);
  return 0; }
