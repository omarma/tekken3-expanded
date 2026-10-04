/*
 * psx_fiber.c — Win32-Fiber / POSIX-ucontext backends for psx_fiber.h.
 */
#include "psx_fiber.h"

#if defined(_WIN32)

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

psx_fiber_t psx_fiber_convert_thread(void)
{
    /* Attempt the conversion unconditionally and check the error code on
     * failure. The 0x1E00000000000000 TEB sentinel for "not yet a fiber"
     * is MSVC-internal and not guaranteed by MinGW's GetCurrentFiber()
     * implementation — reading it before ConvertThreadToFiber is called
     * can return an unspecified TEB value that isn't the sentinel, causing
     * the sentinel check to silently skip ConvertThreadToFiber, leaving
     * the thread as a non-fiber, and crashing the first SwitchToFiber. */
    void* fib = ConvertThreadToFiber(NULL);
    if (!fib && GetLastError() == ERROR_ALREADY_FIBER)
        fib = GetCurrentFiber();
    return (psx_fiber_t)fib;
}

psx_fiber_t psx_fiber_current(void)      { return (psx_fiber_t)GetCurrentFiber(); }

psx_fiber_t psx_fiber_create(size_t stack_size, psx_fiber_entry entry, void* arg)
{
    return (psx_fiber_t)CreateFiber((SIZE_T)stack_size,
                                    (LPFIBER_START_ROUTINE)entry, arg);
}

void psx_fiber_switch(psx_fiber_t target) { SwitchToFiber((LPVOID)target); }
void psx_fiber_destroy(psx_fiber_t fiber) { if (fiber) DeleteFiber((LPVOID)fiber); }

#elif defined(__ANDROID__) && defined(__aarch64__)

/* Android's libc (bionic) has no getcontext/makecontext/swapcontext, so the
 * switch is a few lines of AArch64 assembly: save the callee-saved registers
 * the AAPCS64 requires to survive a call (x19-x30, sp, d8-d15), load the
 * target's, and return into it. x18 is Android's platform register and is
 * never touched. Same cooperative, single-threaded contract as the others. */

#include <stdint.h>
#include <stdlib.h>

typedef struct psx_fiber_impl {
    uint64_t        regs[21]; /* x19-x28, x29, x30, sp, d8-d15 */
    void*           stack;    /* NULL for the thread-fiber */
    psx_fiber_entry entry;
    void*           arg;
} psx_fiber_impl;

void psx_fiber_a64_swap(uint64_t* save, const uint64_t* load);
void psx_fiber_a64_start(void);

__asm__(
    ".text\n"
    ".p2align 2\n"
    ".globl psx_fiber_a64_swap\n"
    ".hidden psx_fiber_a64_swap\n"
    ".type psx_fiber_a64_swap, %function\n"
    "psx_fiber_a64_swap:\n"
    "    stp x19, x20, [x0, #0]\n"
    "    stp x21, x22, [x0, #16]\n"
    "    stp x23, x24, [x0, #32]\n"
    "    stp x25, x26, [x0, #48]\n"
    "    stp x27, x28, [x0, #64]\n"
    "    stp x29, x30, [x0, #80]\n"
    "    mov x2, sp\n"
    "    str x2, [x0, #96]\n"
    "    stp d8,  d9,  [x0, #104]\n"
    "    stp d10, d11, [x0, #120]\n"
    "    stp d12, d13, [x0, #136]\n"
    "    stp d14, d15, [x0, #152]\n"
    "    ldp x19, x20, [x1, #0]\n"
    "    ldp x21, x22, [x1, #16]\n"
    "    ldp x23, x24, [x1, #32]\n"
    "    ldp x25, x26, [x1, #48]\n"
    "    ldp x27, x28, [x1, #64]\n"
    "    ldp x29, x30, [x1, #80]\n"
    "    ldr x2, [x1, #96]\n"
    "    mov sp, x2\n"
    "    ldp d8,  d9,  [x1, #104]\n"
    "    ldp d10, d11, [x1, #120]\n"
    "    ldp d12, d13, [x1, #136]\n"
    "    ldp d14, d15, [x1, #152]\n"
    "    ret\n"
    ".size psx_fiber_a64_swap, .-psx_fiber_a64_swap\n"
    /* A new fiber's first switch "returns" here with its impl in x19. */
    ".globl psx_fiber_a64_start\n"
    ".hidden psx_fiber_a64_start\n"
    ".type psx_fiber_a64_start, %function\n"
    "psx_fiber_a64_start:\n"
    "    mov x0, x19\n"
    "    bl psx_fiber_a64_run\n"
    "    brk #0\n"
    ".size psx_fiber_a64_start, .-psx_fiber_a64_start\n");

static psx_fiber_impl* s_current = NULL;

__attribute__((visibility("hidden"), used, noreturn))
void psx_fiber_a64_run(psx_fiber_impl* f)
{
    f->entry(f->arg);
    /* The BIOS thread entry never returns normally. Reaching here is a bug. */
    abort();
}

psx_fiber_t psx_fiber_convert_thread(void)
{
    if (!s_current) {
        psx_fiber_impl* f = (psx_fiber_impl*)calloc(1, sizeof(*f));
        f->stack = NULL;       /* runs on the real thread stack */
        s_current = f;
    }
    return (psx_fiber_t)s_current;
}

psx_fiber_t psx_fiber_current(void) { return (psx_fiber_t)s_current; }

psx_fiber_t psx_fiber_create(size_t stack_size, psx_fiber_entry entry, void* arg)
{
    if (stack_size < 65536) stack_size = 65536;
    stack_size = (stack_size + 15) & ~(size_t)15;
    psx_fiber_impl* f = (psx_fiber_impl*)calloc(1, sizeof(*f));
    if (!f) return NULL;
    f->stack = malloc(stack_size);
    if (!f->stack) { free(f); return NULL; }
    f->entry = entry;
    f->arg   = arg;
    uintptr_t top = ((uintptr_t)f->stack + stack_size) & ~(uintptr_t)15;
    f->regs[0]  = (uint64_t)(uintptr_t)f;                    /* x19 */
    f->regs[10] = 0;                                         /* x29: end of frame chain */
    f->regs[11] = (uint64_t)(uintptr_t)psx_fiber_a64_start;  /* x30 */
    f->regs[12] = (uint64_t)top;                             /* sp */
    return (psx_fiber_t)f;
}

void psx_fiber_switch(psx_fiber_t target)
{
    psx_fiber_impl* to   = (psx_fiber_impl*)target;
    psx_fiber_impl* from = s_current;
    if (!to || to == from) return;
    s_current = to;
    psx_fiber_a64_swap(from->regs, to->regs);
}

void psx_fiber_destroy(psx_fiber_t fiber)
{
    psx_fiber_impl* f = (psx_fiber_impl*)fiber;
    if (!f) return;
    free(f->stack);
    free(f);
}

#else /* POSIX: ucontext */

#ifndef _XOPEN_SOURCE
#  define _XOPEN_SOURCE 700
#endif
#ifdef __APPLE__
#  define _DARWIN_C_SOURCE 1
#endif

#include <ucontext.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>
#include <signal.h>    /* SIGSTKSZ — minimum fiber stack floor */

/* glibc >= 2.34 no longer exposes SIGSTKSZ as a compile-time constant under
 * _XOPEN_SOURCE; provide a portable fallback (used only as a stack floor). */
#ifndef SIGSTKSZ
#  define SIGSTKSZ 16384
#endif

#if defined(__clang__) || defined(__GNUC__)
#  pragma GCC diagnostic ignored "-Wdeprecated-declarations"
#endif

typedef struct psx_fiber_impl {
    ucontext_t      ctx;
    void*           stack;    /* NULL for the thread-fiber */
    psx_fiber_entry entry;
    void*           arg;
} psx_fiber_impl;

/* Cooperative + single-threaded, so a plain static tracks who's running. */
static psx_fiber_impl* s_current = NULL;

/* makecontext only passes ints; split the fiber pointer across two. */
static void psx_fiber_trampoline(unsigned int hi, unsigned int lo)
{
    uintptr_t p = ((uintptr_t)hi << 32) | (uintptr_t)lo;
    psx_fiber_impl* f = (psx_fiber_impl*)p;
    f->entry(f->arg);
    /* The BIOS thread entry never returns normally (it switches back to its
     * scheduler target, or trap_crashes). Reaching here is a bug. */
    abort();
}

psx_fiber_t psx_fiber_convert_thread(void)
{
    if (!s_current) {
        psx_fiber_impl* f = (psx_fiber_impl*)calloc(1, sizeof(*f));
        f->stack = NULL;       /* runs on the real thread stack */
        s_current = f;
    }
    return (psx_fiber_t)s_current;
}

psx_fiber_t psx_fiber_current(void) { return (psx_fiber_t)s_current; }

psx_fiber_t psx_fiber_create(size_t stack_size, psx_fiber_entry entry, void* arg)
{
    if (stack_size < SIGSTKSZ) stack_size = SIGSTKSZ;
    psx_fiber_impl* f = (psx_fiber_impl*)calloc(1, sizeof(*f));
    if (!f) return NULL;
    f->stack = malloc(stack_size);
    if (!f->stack) { free(f); return NULL; }
    f->entry = entry;
    f->arg   = arg;
    if (getcontext(&f->ctx) != 0) { free(f->stack); free(f); return NULL; }
    f->ctx.uc_stack.ss_sp   = f->stack;
    f->ctx.uc_stack.ss_size = stack_size;
    f->ctx.uc_link          = NULL;   /* entry never returns; see trampoline */
    uintptr_t p = (uintptr_t)f;
    makecontext(&f->ctx, (void (*)(void))psx_fiber_trampoline, 2,
                (unsigned int)(p >> 32), (unsigned int)(p & 0xFFFFFFFFu));
    return (psx_fiber_t)f;
}

void psx_fiber_switch(psx_fiber_t target)
{
    psx_fiber_impl* to   = (psx_fiber_impl*)target;
    psx_fiber_impl* from = s_current;
    if (!to || to == from) return;
    s_current = to;
    swapcontext(&from->ctx, &to->ctx);
    /* Resumed: s_current was set back to `from` by whoever switched here. */
}

void psx_fiber_destroy(psx_fiber_t fiber)
{
    psx_fiber_impl* f = (psx_fiber_impl*)fiber;
    if (!f) return;
    free(f->stack);
    free(f);
}

#endif /* _WIN32 */
