/*
 * psx_fiber.h — cross-platform cooperative fibers for the BIOS thread
 * scheduler (traps.c) and exception-deferral (interrupts.c).
 *
 * The PS1 BIOS manages its own threads (TCBs) and switches between them
 * cooperatively; the runtime mirrors each BIOS thread with a host fiber so
 * the recompiled C for a suspended thread keeps its own native call stack
 * across a ChangeThread. The CD-boot handoff in particular depends on this:
 * a thread issues a CD command, WaitEvent-blocks, and the scheduler must be
 * able to resume a *different* thread's previously-suspended stack — which
 * requires real separate stacks, not nested dispatch.
 *
 * Backends:
 *   - Windows: the Win32 Fiber API (ConvertThreadToFiber / CreateFiber /
 *     SwitchToFiber / DeleteFiber). Behavior is identical to the original.
 *   - POSIX (macOS/Linux): ucontext (makecontext / swapcontext).
 *
 * Cooperative, single-threaded: exactly one fiber runs at a time and all
 * switches are explicit. psx_fiber_current() is the GetCurrentFiber analog.
 */
#ifndef PSX_FIBER_H
#define PSX_FIBER_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef void* psx_fiber_t;
typedef void (*psx_fiber_entry)(void* arg);

/* Make the current thread a fiber so it can switch to others. Idempotent;
 * returns the handle for the current thread's fiber. Call before the first
 * psx_fiber_switch on this thread. */
psx_fiber_t psx_fiber_convert_thread(void);

/* The currently-executing fiber (GetCurrentFiber analog). */
psx_fiber_t psx_fiber_current(void);

/* Create a fiber with its own stack. It does not run until switched to. */
psx_fiber_t psx_fiber_create(size_t stack_size, psx_fiber_entry entry, void* arg);

/* Switch execution to target; the caller is suspended until switched back. */
void psx_fiber_switch(psx_fiber_t target);

/* Destroy a fiber created by psx_fiber_create and free its stack. Must not
 * be the currently-running fiber. */
void psx_fiber_destroy(psx_fiber_t fiber);

#ifdef __cplusplus
}
#endif

#endif /* PSX_FIBER_H */
