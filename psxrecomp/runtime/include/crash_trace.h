#ifndef PSXRECOMP_CRASH_TRACE_H
#define PSXRECOMP_CRASH_TRACE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Install signal/SEH/atexit handlers. Call once early in main(). */
void psx_crash_trace_install_handlers(void);

/* Manually trigger a crash dump. `reason` is a short string identifying
 * the trigger (e.g. "fail_fast_unknown_dispatch", "trap_crash"). On
 * Windows, `seh_info` is the EXCEPTION_POINTERS* from the SEH filter or
 * NULL. Writes to psx_last_run_report.json (overwrite). */
void psx_crash_trace_dump(const char *reason, void *seh_info);

/* Tag a deliberate exit() so the atexit report can attribute it
 * (e.g. "tcp_quit", "sdl_window_close"). An "atexit" report whose
 * exit_origin is still "unknown" means an untagged exit fired. */
void psx_crash_trace_set_exit_origin(const char *origin);

/* Terminal stop for deliberate fatal sites (unhandled MMIO access,
 * trap_crash, fail-fast unknown dispatch). Writes the structured crash
 * report AND a full freeze-style ring dump, then:
 *   - debug-tools builds: halts emulation but keeps pumping the TCP
 *     debug server forever so every ring buffer stays queryable
 *     post-mortem (ring-buffer-first: the crash state is interrogated,
 *     not just snapshotted).
 *   - PSX_NO_DEBUG_TOOLS builds: exit(1) as before.
 * Never returns. */
void psx_fatal_halt(const char *reason);

/* Set when psx_fatal_halt fires; the freeze heartbeat includes it so an
 * external reader can tell a fatal halt from a wedge. NULL = healthy. */
extern const char *g_psx_fatal_reason;

#ifdef __cplusplus
}
#endif

#endif /* PSXRECOMP_CRASH_TRACE_H */
