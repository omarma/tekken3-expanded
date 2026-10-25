#ifndef PSXRECOMP_GTE_PRECISION_INTERP_H
#define PSXRECOMP_GTE_PRECISION_INTERP_H
/* Value propagation in interpreted code (ENHANCEMENTS.md G1.15).
 *
 * [recompiler] precision_funcs (G1.12) makes the recompiler emit the
 * LW / SW / ADDU / SRA / AND / OR hooks of gte.cpp inside listed functions.
 * Code that runs in the interpreters instead (overlays without a native
 * cache) gets the same hooks from them, while provenance tracking is on, for
 * instructions whose PC lies inside a listed RANGE ("0xSTART-0xEND"; a
 * single-address entry names an emitted function, whose extent the
 * interpreters do not know). Every shadow is validated by value where it is
 * read (G1.2), so a range that holds other code at another time can only
 * lose a shadow, never give a wrong one. Kept out of cpu_state.h, which
 * feeds the codegen hash. */
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Startup: the ranges of [recompiler] precision_funcs (guest addresses). */
void gte_precision_interp_ranges_set(const uint32_t *lo, const uint32_t *hi, int count);
/* 1 when `pc` lies in a range. Call only behind g_gte_precision_tracking and
 * GTE_PRECISION_INTERP_PAGE: overlays run interpreted in every fight, and a
 * call per instruction cost 0.13 ms a frame there. */
int  gte_precision_interp_pc(uint32_t pc);
extern int g_gte_precision_tracking;
/* One byte per 4 KiB page of the 2 MiB RAM: nonzero when a range touches it. */
extern uint8_t g_gte_precision_interp_pages[512];
#define GTE_PRECISION_INTERP_PAGE(pc) (g_gte_precision_interp_pages[((pc) & 0x1FFFFFu) >> 12])
/* The test the interpreters run per instruction. */
#define GTE_PRECISION_INTERP(pc) \
    (g_gte_precision_tracking && GTE_PRECISION_INTERP_PAGE(pc) && gte_precision_interp_pc(pc))
/* Before an interpreted instruction at a listed PC, with the values of its
 * rs and rt operands: LW, ADDU / ADD, SRA, AND, ANDI, OR, as the recompiler
 * emits them before the instruction. SW goes through gte_precision_cpu_sw
 * after the store, as emitted. */
void gte_precision_interp_before(uint32_t insn, uint32_t rs_val, uint32_t rt_val);
/* One coordinate at a time (half-word vertex building): LH / LHU before the
 * load, SH after the store, SRL and SLL before (SRA, ADDU, OR take
 * coordinates too). Called from the interpreters only: no emitted function
 * listed by a title needs them yet. */
void gte_precision_cpu_lh(uint8_t rt, uint32_t addr, int sign);
void gte_precision_cpu_sh(uint32_t addr, uint8_t rt, uint32_t value);
void gte_precision_cpu_srl(uint8_t rd, uint8_t rt, uint8_t sa, uint32_t vt);
void gte_precision_cpu_sll(uint8_t rd, uint8_t rt, uint8_t sa, uint32_t vt);

#ifdef __cplusplus
}
#endif
#endif
