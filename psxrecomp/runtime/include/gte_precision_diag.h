#ifndef PSXRECOMP_GTE_PRECISION_DIAG_H
#define PSXRECOMP_GTE_PRECISION_DIAG_H
/* Projection-provenance census (diagnostic only; see ENHANCEMENTS.md G1.10).
 * Nothing on the render path reads these. Kept out of cpu_state.h and
 * overlay_api.h on purpose: both feed the codegen hash, and a counter must
 * not invalidate every overlay cache and save state. */
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum {
    GTE_DIAG_SWC2 = 0,                  /* SWC2 of SXY0-2/SXYP, tracking on  */
    GTE_DIAG_SWC2_INVALID,              /* ... no valid projection in reg    */
    GTE_DIAG_SWC2_TRACKED,              /* ... stored in the RAM table       */
    GTE_DIAG_SWC2_SCRATCH,              /* ... stored in the scratchpad table
                                           (refused before G1.11)            */
    GTE_DIAG_SWC2_OTHER,                /* ... refused: other non-RAM        */
    GTE_DIAG_LWC2,                      /* LWC2 reads, any register          */
    GTE_DIAG_LWC2_SCRATCH,              /* ... from the scratchpad           */
    GTE_DIAG_LWC2_SCRATCH_WOULD_TRACK,  /* ... of a word a SWC2 projection
                                           wrote, value unchanged            */
    GTE_DIAG_LWC2_RAM_TRACKED,          /* ... of a RAM word the store table
                                           tracks, value unchanged           */
    GTE_DIAG_SITES_DROPPED,             /* SWC2 sites beyond the site table  */
    GTE_DIAG_PROJECTED_VERTICES,        /* RTPS/RTPT vertices, always counted */
    /* G1.11: LWC2 into SXY0-2/SXYP (gte_precision_lwc2_word). */
    GTE_DIAG_LWC2_SXY,                  /* LWC2 into an SXY register         */
    GTE_DIAG_LWC2_SXY_RESTORED,         /* ... projection restored           */
    GTE_DIAG_LWC2_SXY_MISS_UNWRITTEN,   /* ... none: scratch word not written
                                           since tracking (re)started        */
    GTE_DIAG_LWC2_SXY_MISS_CPU_STORE,   /* ... none: a CPU store wrote it    */
    GTE_DIAG_LWC2_SXY_MISS_UNPROJECTED, /* ... none: SWC2 of an SXY register
                                           holding no projection             */
    GTE_DIAG_LWC2_SXY_MISS_VALUE,       /* ... none: word differs from the
                                           tracked projection                */
    GTE_DIAG_LWC2_SXY_MISS_RAM,         /* ... none: RAM word not tracked    */
    GTE_DIAG_MISSES_DROPPED,            /* miss keys beyond the miss table   */
    /* G1.12: value propagation in [recompiler] precision_funcs. */
    GTE_DIAG_LWC2_SXY_RESTORED_DERIVED, /* restored, computed by the CPU     */
    GTE_DIAG_CPU_LW,                    /* LW hooks run                      */
    GTE_DIAG_CPU_LW_SHADOW,             /* ... that gave the register a shadow */
    GTE_DIAG_CPU_SW_SHADOW,             /* SW that left a shadow on the word */
    GTE_DIAG_CPU_ALU_SHADOW,            /* ALU results carrying a shadow     */
    GTE_DIAG_STORE_EVICTED,             /* RAM store table: live entry of
                                           another address overwritten       */
    /* G1.13 */
    GTE_DIAG_NATIVE_WORDS,              /* projections left by native mods
                                           (gte_precision_native_word)        */
    /* G1.15 */
    GTE_DIAG_CPU_INTERP,                /* interpreted instructions at a listed
                                           PC that ran a propagation hook    */
    GTE_PRECISION_DIAG_COUNT
};

/* Causes of an LWC2-into-SXY miss, in GTE_DIAG_LWC2_SXY_MISS_* order. */
enum {
    GTE_LWC2_MISS_UNWRITTEN = 0,
    GTE_LWC2_MISS_CPU_STORE,
    GTE_LWC2_MISS_UNPROJECTED,
    GTE_LWC2_MISS_VALUE,
    GTE_LWC2_MISS_RAM,
};

void gte_precision_diag_stats(uint32_t out[GTE_PRECISION_DIAG_COUNT]);
/* SWC2 sites that stored a valid projection: PC, count, 1 = scratchpad. */
int  gte_precision_diag_sites(uint32_t *pc, uint32_t *count, uint8_t *scratch,
                              int max);
void gte_precision_diag_lwc2(uint32_t addr, uint32_t value);
/* LWC2-into-SXY misses: LWC2 PC, PC of the store that wrote the word last
 * (0 if unknown), count, cause (GTE_LWC2_MISS_*). */
int  gte_precision_diag_misses(uint32_t *pc, uint32_t *writer_pc,
                               uint32_t *count, uint8_t *cause, int max);
/* Mirror of the provenance-tracking switch, for a cheap inline test. */
extern int g_gte_precision_tracking;

/* gpu.c: GP0 triangles reaching the enhancement seam. */
enum {
    GPU_DIAG_PRECISE_TRIANGLES = 0,     /* prepare_precise_triangle calls    */
    GPU_DIAG_TEXTURE_TRIANGLES,         /* textured, perspective path checked */
    GPU_DIAG_TEXTURE_WORDS_EXACT,       /* position words with exact SWC2
                                           provenance at their packet address */
    GPU_DIAG_TEXTURE_TRIANGLES_EXACT,   /* all three words exact (perspective
                                           UVs handed to the renderer)        */
    /* G1.11, geometry_correction on: */
    GPU_DIAG_PRECISE_WORDS_EXACT,       /* position words given their exact
                                           16.16 projection                   */
    GPU_DIAG_PRECISE_TRIANGLES_EXACT,   /* triangles with all three exact     */
    GPU_DIAG_PRECISE_TRIANGLES_PARTIAL, /* ... with one or two exact          */
    GPU_DIAG_PRECISE_TRIANGLES_POSITION,/* corrected by the position fallback */
    /* G1.12: */
    GPU_DIAG_PRECISE_WORDS_DERIVED,     /* exact words computed by the CPU,
                                           accepted within one pixel          */
    GPU_DIAG_PRECISE_WORDS_REFUSED,     /* tracked words whose integer part
                                           disagrees with the packet word     */
    GPU_DIAG_PRECISE_VERTICES_MERGED,   /* corrected vertices moved to the
                                           sub-pixel position of an earlier
                                           vertex on the same integer pixel */
    GPU_DIAG_SEAM_EDGES,                /* edges sharing both integer
                                           endpoints with an earlier triangle
                                           of the frame, sub-pixel ends apart */
    /* G1.14: */
    GPU_DIAG_PRECISE_RECT_QUADS,        /* axis-aligned quads with an exact
                                           word drawn as two corrected
                                           triangles instead of one rect     */
    GPU_PRECISION_DIAG_COUNT
};
/* One seam (G1.12): the shared integer edge, then the sub-pixel endpoints,
 * store PCs and derived flags of the first and the second triangle. */
typedef struct {
    uint32_t frame;
    int16_t x[2], y[2];
    int32_t first_fx[2], first_fy[2], second_fx[2], second_fy[2];
    uint32_t first_pc[2], second_pc[2];
    uint8_t first_derived[2], second_derived[2];
} GpuSeamSample;
/* Pixel-cell merge of corrected vertices (on by default with geometry). */
void gpu_geometry_cell_merge_set(int enabled);
int  gpu_geometry_cell_merge_enabled(void);
/* Axis-aligned quads with an exact word drawn as triangles, not as a rect
 * (on by default with geometry, G1.14). */
void gpu_geometry_rect_quads_set(int enabled);
int  gpu_geometry_rect_quads_enabled(void);
/* Seam census (GPU_DIAG_SEAM_EDGES, seams): off by default, a bench turns it
 * on (video_enhancements geometry_seam_census). */
void gpu_geometry_seam_census_set(int enabled);
int  gpu_geometry_seam_census_enabled(void);
/* The first seams of the last frame that had any. */
int  gpu_precision_diag_seams(GpuSeamSample *out, int max);
void gpu_precision_diag_stats(uint32_t out[GPU_PRECISION_DIAG_COUNT]);
/* Exact and partial geometry triangles by the store PC of their first exact
 * word (the packet builder), G1.12. Returns the number of sites. */
int  gpu_precision_diag_triangle_sites(uint32_t *pc, uint32_t *exact,
                                       uint32_t *partial, int max);
/* gte.cpp, census only: PC of the store that left the tracked word at addr. */
uint32_t gte_precision_word_writer_pc(uint32_t addr);

#ifdef __cplusplus
}
#endif
#endif
