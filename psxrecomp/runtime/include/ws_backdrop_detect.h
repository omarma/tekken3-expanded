#ifndef PSX_WS_BACKDROP_DETECT_H
#define PSX_WS_BACKDROP_DETECT_H
/* ============================================================================
 * Generic widescreen BACKDROP-PRELOAD detector ([widescreen.cull] auto_backdrop)
 *
 * Self-contained (depends only on <stdint.h>) so ONE implementation is shared
 * verbatim by the recompiler (C++) and the runtime interpreter
 * (C). Having a single source of truth matters here: a false positive corrupts
 * unrelated overlay codegen (see BACKDROP_PRELOAD.md §risk), so the gate must be
 * identical on every path.
 *
 * WHAT IT FINDS
 * -------------
 * PSX scrollers generate a far-background tile row one CAMERA-WINDOWED column
 * range per frame. The generator divides the camera world-X by ~96 to a column
 * index and emits a small window [START, END] of columns around it:
 *
 *     lui  M,0x6666 ; ori M,M,0x6667     ; M = 0x66666667 (/96 reciprocal)
 *     lh/lhu D,0x176(base)               ; D = camera world-X  (offset 0x176)
 *     [addiu/addu D, D, Koff]            ; optional per-layer parallax bias
 *     mult D, M
 *     mfhi H ; sra Q,H,5 ; subu/addu Q,Q,sign   ; Q = camX / 96  (the quotient)
 *     move  rStart, Q                    ; START finalize (offset 0)
 *     addiu rEnd,  Q, N                  ; END   delta     (offset N)
 *     <low clamp on START to a floor>  <high clamp on END to the finite extent>
 *     for (col = START; col <= END; col++) emit one tile from a finite table
 *
 * In 16:9 the window slides with the camera, so the revealed margin shows void.
 * The fix WIDENS the camera-tracked window by exactly the 16:9 reveal: pull the
 * START bound a little left and push the END bound a little right, by a margin
 * proportional to the window width (the revealed fraction of the screen). This
 * draws only the now-visible columns — NOT the whole finite row — so there is no
 * overdraw (an early "force START=0 / END=full-row" version lagged on long rows
 * and capped short on rows > the fixed cap). The generator's own low/high clamps
 * still bound the widened window at the level edges.
 *
 * THE TWO REWRITE SITES (per window)
 * ----------------------------------
 * The quotient is consumed by exactly two instructions: a `move rX, Q` (offset
 * 0) and an `addiu rY, Q, N` (offset N). Which is START and which is END is NOT
 * fixed by move-vs-addiu — it is decided by the generator's clamp tail and is
 * captured generically by OFFSET ORDERING: the smaller signed offset is the
 * START (left) bound, the larger is the END (right) bound. Verified on Tomba's
 * village (FUN_80116a28: a2=START/a3=END, +8) and flower-field (s2=START/s1=END;
 * one window has the addiu at offset -18 acting as START with the move as END).
 * The window width in columns is |N| (the addiu offset magnitude) — recorded so
 * the runtime sizes the widen margin to the reveal.
 *
 * The actual value substitution is done at runtime by psx_ws_backdrop_value()
 * (gpu.c): identity unless native-wide widescreen is engaged, so 4:3 stays
 * byte-identical. It returns orig-margin for a START site and orig+margin for an
 * END site. This detector only locates the addresses + the window width.
 *
 * VALIDATION IS PER-MULT AND LOCAL (backward), not forward-accumulated: the /96
 * magic is sometimes established in a shared branch-delay slot, so register
 * state from one branch leg would bleed into another under a forward scan. Each
 * candidate `mult` is gated by a bounded backward scan for (a) the exact magic
 * load into one operand and (b) a 0x176 camera load into the other operand.
 * ========================================================================== */
#include <stdint.h>

enum {
    WS_BD_NONE  = 0,
    WS_BD_START = 1,   /* the window's left (smaller-offset) bound  -> orig - margin */
    WS_BD_END   = 2     /* the window's right (larger-offset) bound  -> orig + margin */
};

typedef struct {
    uint32_t pc;          /* absolute guest address of the instruction to rewrite */
    int      kind;        /* WS_BD_START | WS_BD_END */
    int      window_cols; /* window width in columns (|addiu offset|), drives the widen margin */
} WsBackdropSite;

/* Scan `n` instruction words starting at guest address `base_pc` for backdrop
 * column-window generators and record the START/END rewrite sites. Returns the
 * number of sites written to `out` (capped at `max_sites`). Pure: the result
 * depends only on the instruction bytes, so the recompiler (full-function
 * words) and the runtime (a window around a PC) derive identical sites. */
static inline int psx_ws_find_backdrop_windows(const uint32_t *words, int n,
                                               uint32_t base_pc,
                                               WsBackdropSite *out, int max_sites)
{
    int count = 0;
    if (!words || n <= 0 || !out || max_sites <= 0) return 0;

    for (int i = 0; i < n; i++) {
        uint32_t w = words[i];
        /* mult rs,rt : SPECIAL(op 0) funct 0x18 (signed multiply) */
        if ((w >> 26) != 0u || (w & 0x3Fu) != 0x18u) continue;
        uint32_t op_rs = (w >> 21) & 31u;
        uint32_t op_rt = (w >> 16) & 31u;

        /* One operand is the /96 magic, the other the camera-X dividend. Try
         * both assignments; validate each by a bounded local backward scan. */
        for (int swap = 0; swap < 2; swap++) {
            uint32_t M = swap ? op_rt : op_rs;   /* magic candidate    */
            uint32_t D = swap ? op_rs : op_rt;   /* dividend candidate  */
            if (M == D) continue;

            int have_lui = 0, have_ori = 0, have_camx = 0;
            int blo = i - 32; if (blo < 0) blo = 0;
            for (int b = i - 1; b >= blo; b--) {
                uint32_t bw   = words[b];
                uint32_t bop  = bw >> 26;
                uint32_t brs  = (bw >> 21) & 31u;
                uint32_t brt  = (bw >> 16) & 31u;
                uint32_t bimm = bw & 0xFFFFu;
                if (bop == 0x0Fu && brt == M && bimm == 0x6666u) have_lui = 1;                 /* lui M,0x6666     */
                else if (bop == 0x0Du && brt == M && brs == M && bimm == 0x6667u) have_ori = 1; /* ori M,M,0x6667   */
                else if ((bop == 0x21u || bop == 0x25u) && brt == D && bimm == 0x176u) have_camx = 1; /* lh/lhu D,0x176 */
            }
            if (!have_lui || !have_ori || !have_camx) continue;

            /* Forward divide tail: mfhi H -> sra Q,H,5. Bail on a control
             * transfer before the tail (the divide is straight-line). */
            int hi_reg = -1, quot = -1, jdiv = -1;
            int fhi = i + 1 + 16; if (fhi > n) fhi = n;
            for (int f = i + 1; f < fhi; f++) {
                uint32_t fw = words[f];
                uint32_t fop = fw >> 26;
                uint32_t ffn = fw & 0x3Fu;
                uint32_t frd = (fw >> 11) & 31u;
                uint32_t frt = (fw >> 16) & 31u;
                uint32_t fsa = (fw >> 6) & 31u;
                if (fop == 0u && ffn == 0x10u) { hi_reg = (int)frd; continue; }     /* mfhi rd */
                if (hi_reg >= 0 && fop == 0u && ffn == 0x03u && (int)frt == hi_reg && fsa == 5u) {
                    quot = (int)frd; jdiv = f; break;                               /* sra quot,hi,5 */
                }
                if (fop == 0x02u || fop == 0x03u || fop == 0x04u || fop == 0x05u ||
                    fop == 0x06u || fop == 0x07u || fop == 0x01u ||
                    (fop == 0u && (ffn == 0x08u || ffn == 0x09u))) break;           /* j/jal/branch/jr/jalr */
            }
            if (quot < 0) continue;

            /* Forward: optional sign correction (addu/subu chaining the
             * quotient) + the two window consumers (a move and an addiu reading
             * the quotient, or the addiu reading the move's START register). */
            int cur = quot, move_dest = -1;
            uint32_t move_pc = 0, addiu_pc = 0;
            int have_move = 0, have_addiu = 0, addiu_n = 0;
            int fend = jdiv + 1 + 8; if (fend > n) fend = n;
            for (int f = jdiv + 1; f < fend && !(have_move && have_addiu); f++) {
                uint32_t fw = words[f];
                uint32_t fop = fw >> 26;
                uint32_t ffn = fw & 0x3Fu;
                uint32_t frd = (fw >> 11) & 31u;
                uint32_t frt = (fw >> 16) & 31u;
                uint32_t frs = (fw >> 21) & 31u;
                int      fsimm = (int)(int16_t)(uint16_t)(fw & 0xFFFFu);
                uint32_t pc = base_pc + (uint32_t)f * 4u;

                if (fop == 0u && (ffn == 0x21u || ffn == 0x25u)) {   /* addu/or */
                    int src = -1;
                    if (frt == 0u && frs != 0u) src = (int)frs;       /* move rD, rS  (rT == $0) */
                    else if (frs == 0u && frt != 0u) src = (int)frt;  /* move rD, rT  (rS == $0) */
                    if (src == cur) {
                        if (!have_move) { move_pc = pc; move_dest = (int)frd; have_move = 1; }
                        continue;
                    }
                    if (ffn == 0x21u && frs != 0u && frt != 0u &&
                        ((int)frs == cur || (int)frt == cur)) {       /* addu sign correction */
                        cur = (int)frd; continue;
                    }
                }
                if (fop == 0u && ffn == 0x23u &&
                    ((int)frs == cur || (int)frt == cur)) {           /* subu sign correction */
                    cur = (int)frd; continue;
                }
                if ((fop == 0x09u || fop == 0x08u) &&                 /* addiu/addi rD, (Q|START), N */
                    ((int)frs == cur || (have_move && (int)frs == move_dest))) {
                    if (!have_addiu) { addiu_pc = pc; addiu_n = fsimm; have_addiu = 1; }
                    continue;
                }
            }
            if (!have_move || !have_addiu || addiu_n == 0) continue;

            /* Role by offset: smaller signed offset = START (left bound), larger
             * = END (right bound). The move's offset is 0; the addiu's is
             * addiu_n. Window width = |addiu_n|. */
            int move_kind  = (addiu_n > 0) ? WS_BD_START : WS_BD_END;
            int addiu_kind = (addiu_n > 0) ? WS_BD_END   : WS_BD_START;
            int wcols      = (addiu_n < 0) ? -addiu_n : addiu_n;

            for (int s = 0; s < 2; s++) {
                uint32_t spc = s ? addiu_pc : move_pc;
                int      sk  = s ? addiu_kind : move_kind;
                int dup = 0;
                for (int q = 0; q < count; q++) if (out[q].pc == spc) { dup = 1; break; }
                if (!dup && count < max_sites) {
                    out[count].pc = spc; out[count].kind = sk;
                    out[count].window_cols = wcols; count++;
                }
            }
            break;   /* this mult handled; do not try the other operand assignment */
        }
    }
    return count;
}

/* Convenience: return the rewrite kind for a single guest PC by scanning a
 * window of words (the runtime passes a window around the PC), and output the
 * window width in columns via *out_cols. Returns WS_BD_NONE / WS_BD_START /
 * WS_BD_END. */
static inline int psx_ws_backdrop_kind_at(const uint32_t *words, int n,
                                          uint32_t base_pc, uint32_t pc,
                                          int *out_cols)
{
    WsBackdropSite sites[32];
    int ns = psx_ws_find_backdrop_windows(words, n, base_pc, sites, 32);
    for (int i = 0; i < ns; i++)
        if (sites[i].pc == pc) {
            if (out_cols) *out_cols = sites[i].window_cols;
            return sites[i].kind;
        }
    if (out_cols) *out_cols = 0;
    return WS_BD_NONE;
}

#endif /* PSX_WS_BACKDROP_DETECT_H */
