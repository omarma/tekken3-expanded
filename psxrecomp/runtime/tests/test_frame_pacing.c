/*
 * test_frame_pacing.c — validate the race-free pacing decision function.
 *
 * Bug B regression test. The old open-coded pacing loop in
 * sdl_vblank_present read the performance counter twice: once in the
 * while-condition, once to compute remaining time. If the deadline was
 * crossed between the two reads, the unsigned subtraction underflowed
 * and SDL_Delay received (2^64 - delta_ticks)*1000/freq truncated to
 * Uint32 — ~24.7 days at the standard 10 MHz QPC. The replacement,
 * frame_pacing_sleep_ms(), takes a SINGLE counter sample and compares
 * before subtracting, so the underflow is impossible by construction.
 * This test pins that property, including the exact post-deadline
 * sample that froze the app.
 *
 * Build: gcc -I../include -o test_frame_pacing test_frame_pacing.c
 * (includes ../src/frame_pacing.c directly with FRAME_PACING_PURE_ONLY,
 *  which compiles only the SDL-free decision function.)
 */
#include <stdio.h>
#include <stdint.h>

/* Pull in just the pure function — frame_pacing.c guards its SDL parts. */
#define FRAME_PACING_PURE_ONLY 1
#include "../src/frame_pacing.c"

static int failures = 0;
#define CHECK(cond, msg) do { \
    if (!(cond)) { printf("FAIL: %s\n", msg); failures++; } \
    else         { printf("ok:   %s\n", msg); } \
} while (0)

int main(void) {
    const uint64_t FREQ   = 10000000ull;            /* standard Win10 QPC: 10 MHz */
    const uint64_t PERIOD = (uint64_t)((double)FREQ * (1000.0 / 59.94) / 1000.0);

    /* 1. The Bug B scenario: counter sampled just AFTER the deadline
     *    (old code underflowed here -> ~24.7-day sleep). Must be 0. */
    uint64_t deadline = 1000000000ull;
    CHECK(frame_pacing_sleep_ms(deadline + 1, deadline, FREQ, PERIOD) == 0,
          "now just past deadline sleeps 0 (Bug B underflow case)");
    CHECK(frame_pacing_sleep_ms(deadline + 123456789ull, deadline, FREQ, PERIOD) == 0,
          "now far past deadline sleeps 0");
    CHECK(frame_pacing_sleep_ms(deadline, deadline, FREQ, PERIOD) == 0,
          "now exactly at deadline sleeps 0");

    /* 2. Normal case: ~10ms remaining -> sleep 9ms (1ms undershoot for spin). */
    CHECK(frame_pacing_sleep_ms(deadline - FREQ / 100, deadline, FREQ, PERIOD) == 9,
          "10ms remaining sleeps 9ms");

    /* 3. Sub-2ms remaining -> 0 (caller spins). */
    CHECK(frame_pacing_sleep_ms(deadline - FREQ / 1000, deadline, FREQ, PERIOD) == 0,
          "1ms remaining spins (0)");

    /* 4. Deadline absurdly far ahead (corrupt/poisoned state) -> clamped to
     *    one period, never a multi-day sleep. */
    uint32_t ms = frame_pacing_sleep_ms(0, UINT64_MAX, FREQ, PERIOD);
    CHECK(ms <= (PERIOD * 1000 / FREQ),
          "runaway deadline clamped to <= one period");

    /* 5. freq == 0 (degenerate platform answer) -> 0, no divide-by-zero. */
    CHECK(frame_pacing_sleep_ms(deadline - FREQ / 100, deadline, 0, PERIOD) == 0,
          "freq 0 returns 0");

    /* 6. Sweep the deadline-crossing window tick by tick: result must be
     *    monotonically sane and never exceed one period's ms. This is the
     *    exact window the old TOCTOU race made lethal. */
    int sweep_ok = 1;
    for (int64_t d = -20; d <= 20; d++) {
        uint64_t now = deadline + (uint64_t)d;   /* wraps safely for d<0 */
        uint32_t v = frame_pacing_sleep_ms(now, deadline, FREQ, PERIOD);
        if (v > (PERIOD * 1000 / FREQ) + 1) { sweep_ok = 0; break; }
    }
    CHECK(sweep_ok, "tick-by-tick sweep across deadline never exceeds one period");

    printf(failures ? "FAILED (%d)\n" : "ALL PASS\n", failures);
    return failures ? 1 : 0;
}
