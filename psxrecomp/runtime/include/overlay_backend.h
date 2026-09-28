#ifndef OVERLAY_BACKEND_H
#define OVERLAY_BACKEND_H

/* overlay_backend — compiler-NEUTRAL overlay tier-selection policy.
 *
 * This is NOT specific to any one producer. It decides which native overlay
 * tier fills a gap, in priority order:
 *
 *   static  >  gcc shard  >  tcc shard  >  interp
 *
 * - gcc:  spawn-gcc -> overlay DLL. The developer / production "holy grail"
 *         (best-optimized; the shards shipped in releases).
 * - tcc:  spawn-tcc -> overlay DLL. Bundled, toolchain-free user fallback that
 *         fills regions the shipped gcc cache misses on a machine without gcc.
 *
 * (The in-process sljit JIT tier was removed 2026-07-15 — it mis-compiled and
 * had been gated off since 2026-06-25. Uncovered gaps fall to the interpreter.)
 *
 * gcc and tcc go through the IDENTICAL pipeline (recompiler -> C -> compiler ->
 * DLL -> loader); they differ only in the compiler binary the autocompile
 * command runs. So both map to the same in-runtime "code provider" (the
 * autocompile spawn) — see code_provider.c — and which compiler runs is chosen
 * here by the resolved backend.
 */

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    OVERLAY_BACKEND_AUTO        = 0, /* gcc if a gcc toolchain is present, else tcc */
    OVERLAY_BACKEND_GCC         = 1, /* force spawn-gcc->DLL (dev / production shards) */
    /* value 2 was OVERLAY_BACKEND_SLJIT (removed 2026-07-15) */
    OVERLAY_BACKEND_TCC         = 3, /* spawn-tcc->DLL (bundled, toolchain-free fallback) */
    OVERLAY_BACKEND_AUTO_NO_GCC = 4  /* dev/test: resolve like AUTO but pretend no gcc toolchain
                                      * (gcc shards still LOAD; gaps fill via tcc) — simulate a
                                      * toolchain-less user box on a dev machine. */
} OverlayBackend;

/* Resolve the effective backend once at startup. `gcc_toolchain_available` is 1
 * when a gcc toolchain is actually reachable AND a compile command is wired (a
 * real dev/production box). Precedence: env PSX_OVERLAY_BACKEND > game.toml
 * [runtime] overlay_backend (`cfg`) > AUTO. AUTO -> gcc if the toolchain is
 * present, else tcc. AUTO_NO_GCC -> tcc regardless (the simulate-user mode).
 * The result is cached + logged. */
OverlayBackend overlay_backend_resolve(const char *cfg, int gcc_toolchain_available);

/* The cached resolution (OVERLAY_BACKEND_AUTO until resolve() runs). */
OverlayBackend overlay_backend_active(void);

/* "auto" | "gcc" | "tcc" | "auto-no-gcc". */
const char *overlay_backend_name(OverlayBackend b);

#ifdef __cplusplus
}
#endif

#endif /* OVERLAY_BACKEND_H */
