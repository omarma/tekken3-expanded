/* Minimal runtime stand-in for benchmarking recompiled OpenBIOS code.
 * Always compiled with clang -O2 (the runtime is precompiled in the APK). */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "cpu_state.h"
#include "psx_cyc.h"
uint8_t *g_psx_ram; static uint8_t *rom;
int g_psx_load_delay = 1, g_ls_mode, g_ls_replay_active, g_event_step_conservative;
volatile int g_ds_recording;
int psx_in_device_service; uint64_t psx_cycle_count, psx_next_service_cycle = ~0ull;
uint32_t g_psx_cyc_batch, g_psx_cyc_batch_limit = 64; uint32_t *g_psx_cyc_local_acc; int g_psx_cyc_bb_defer;
int g_psx_dispatch_depth, g_psx_call_bail; uint64_t g_psx_bail_first, g_psx_bail_resolved, g_psx_bail_flattened, g_psx_bail_anomaly;
int *g_psx_call_bail_p=&g_psx_call_bail; uint64_t *g_psx_bail_first_p=&g_psx_bail_first,*g_psx_bail_resolved_p=&g_psx_bail_resolved;
uint32_t g_debug_last_store_pc, g_debug_current_func_addr; uint64_t g_dispatch_static_hits;
int (*g_psx_bios_hle_hook)(CPUState*, uint32_t);
int g_rfe_escape_pending, g_exc_escape_reason, g_psx_cps_mode, g_psx_precise_slice; uint32_t g_exception_real_epc;
volatile uint32_t g_psx_last_fn_entry;
static uint32_t icache_tag[256]; static volatile int irq_pending;
static uint32_t phys(uint32_t a){ return a & 0x1FFFFFFFu; }
static uint32_t rd32(uint32_t a){ uint32_t p=phys(a),v; if(p<0x800000){memcpy(&v,g_psx_ram+(p&0x1FFFFF),4);return v;} if(p>=0x1FC00000&&p<0x1FC80000){memcpy(&v,rom+(p-0x1FC00000),4);return v;} return 0; }
static uint16_t rd16(uint32_t a){ uint32_t p=phys(a); uint16_t v; if(p<0x800000){memcpy(&v,g_psx_ram+(p&0x1FFFFF),2);return v;} if(p>=0x1FC00000&&p<0x1FC80000){memcpy(&v,rom+(p-0x1FC00000),2);return v;} return 0; }
static uint8_t rd8(uint32_t a){ uint32_t p=phys(a); if(p<0x800000)return g_psx_ram[p&0x1FFFFF]; if(p>=0x1FC00000&&p<0x1FC80000)return rom[p-0x1FC00000]; return 0; }
static void wr32(uint32_t a,uint32_t v){ uint32_t p=phys(a); if(p<0x800000)memcpy(g_psx_ram+(p&0x1FFFFF),&v,4); }
static void wr16(uint32_t a,uint16_t v){ uint32_t p=phys(a); if(p<0x800000)memcpy(g_psx_ram+(p&0x1FFFFF),&v,2); }
static void wr8(uint32_t a,uint8_t v){ uint32_t p=phys(a); if(p<0x800000)g_psx_ram[p&0x1FFFFF]=v; }
uint32_t psx_read_word(uint32_t a){return rd32(a);} uint16_t psx_read_half(uint32_t a){return rd16(a);} uint8_t psx_read_byte(uint32_t a){return rd8(a);}
void psx_advance_cycles_slow(uint32_t c){ psx_cycle_count += c; }
void psx_devices_service_to_now(void){}
void psx_icache_fetch(CPUState*cpu,uint32_t a){ (void)cpu; uint32_t l=(a>>4)&255, t=a&~15u; if(icache_tag[l]!=t){icache_tag[l]=t; psx_advance_cycles(4);} }
void psx_check_interrupts(CPUState*cpu){ (void)cpu; psx_cyc_batch_flush(); if(irq_pending) abort(); }
void psx_check_interrupts_at(CPUState*cpu,uint32_t pc){ (void)pc; psx_check_interrupts(cpu); }
uint8_t psx_cyc_load_byte(CPUState*cpu,uint32_t a,uint32_t rt,uint32_t m){ (void)cpu;(void)rt;(void)m; psx_advance_cycles(5); return rd8(a); }
uint32_t psx_cyc_load_word_slow(CPUState*cpu,uint32_t a,uint32_t rt,uint32_t m){(void)cpu;(void)rt;(void)m;psx_advance_cycles(6);return rd32(a);}
uint16_t psx_cyc_load_half_slow(CPUState*cpu,uint32_t a,uint32_t rt,uint32_t m){(void)cpu;(void)rt;(void)m;psx_advance_cycles(6);return rd16(a);}
void psx_cyc_load_word_timing_only(CPUState*c,uint32_t a,uint32_t r,uint32_t m){(void)c;(void)a;(void)r;(void)m;}
uint32_t psx_cyc_lwc2_read(CPUState*c,uint32_t a){(void)c;return rd32(a);}
int psx_load_delay_enabled(void){ return 1; }
void psx_muldiv_set(CPUState*c,uint32_t l){ c->muldiv_ts_done = psx_cycle_count + l; }
void psx_muldiv_stall(CPUState*c){ if(c->muldiv_ts_done>psx_cycle_count) psx_cycle_count=c->muldiv_ts_done; }
uint32_t psx_mult_latency_s(uint32_t r){ (void)r; return 9; } uint32_t psx_mult_latency_u(uint32_t r){ (void)r; return 9; }
#define DIE(n) void n(void){ fprintf(stderr,"unexpected: %s\n",#n); exit(3); }
void psx_unaligned_access(CPUState*c,uint32_t a,uint32_t pc){(void)c;fprintf(stderr,"unaligned %08x at %08x\n",a,pc);exit(3);}
void psx_break(CPUState*c,uint32_t code,uint32_t pc){(void)c;fprintf(stderr,"break %x at %08x\n",code,pc);exit(3);}
int psx_syscall(CPUState*c,uint32_t code){(void)c;fprintf(stderr,"syscall %x\n",code);exit(3);}
void psx_arith_overflow(CPUState*c){(void)c;fprintf(stderr,"ovf\n");exit(3);}
void psx_unknown_dispatch(CPUState*c,uint32_t a,uint32_t p){(void)c;(void)p;fprintf(stderr,"unknown dispatch %08x\n",a);exit(3);}
DIE(psx_rfe_mark_escape) DIE(psx_restore_state_escape)
void gte_execute(CPUState*c,uint32_t x){(void)c;(void)x;exit(4);} uint32_t gte_read_data(CPUState*c,uint8_t r){(void)c;(void)r;exit(4);} void gte_write_data(CPUState*c,uint8_t r,uint32_t v){(void)c;(void)r;(void)v;exit(4);}
uint32_t gte_read_ctrl(CPUState*c,uint8_t r){(void)c;(void)r;exit(4);} void gte_write_ctrl(CPUState*c,uint8_t r,uint32_t v){(void)c;(void)r;(void)v;exit(4);} void psx_gte_stall(CPUState*c){(void)c;exit(4);} void psx_gte_read(CPUState*c,uint32_t r){(void)c;(void)r;exit(4);} void psx_gte_set(CPUState*c,uint32_t l){(void)c;(void)l;exit(4);}
int psx_game_address_in_text(uint32_t a){ (void)a; return 0; }
int psx_slice_block_impl(CPUState*c,uint32_t a,uint32_t b,int s){(void)c;(void)a;(void)b;(void)s;return 0;}
void psx_bail_record(uint32_t a, uint32_t b, uint32_t c, uint32_t d){(void)a;(void)b;(void)c;(void)d;}
void debug_server_trace_dispatch(uint32_t a){(void)a;}
void psx_wire(CPUState*c){ c->read_word=rd32;c->write_word=wr32;c->read_half=rd16;c->write_half=wr16;c->read_byte=rd8;c->write_byte=wr8; }
void psx_load_rom(const char*p){ rom=calloc(1,0x80000); FILE*f=fopen(p,"rb"); if(!f){perror(p);exit(2);} fread(rom,1,0x80000,f); fclose(f); g_psx_ram=calloc(1,0x200000); }
int dirty_ram_dispatch(CPUState*c,uint32_t a,uint32_t s){(void)c;(void)s;fprintf(stderr,"dirty_ram_dispatch %08x\n",a);exit(3);}
int psx_kernel_bless_dispatchable(uint32_t p){(void)p;return 1;}
void fntrace_record(CPUState*c,uint32_t t){(void)c;(void)t;}
void psx_rfe_escape_check(CPUState*c){(void)c;}
