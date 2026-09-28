/* psx_netplay_sched.c — rollback admission scheduler (policy only).
 *
 * Moved out of psx_netplay.c in §44 (see docs/ROLLBACK_MOTK_HOOKUP.md).
 * Everything here is host-side pacing/decision policy: it never touches the
 * input history, tip-hold state machine or snapshot rings, so guest
 * determinism is unaffected by any change in this file.
 *
 * History note: the §21–§43 policy layers (invent grace, gap1 case split,
 * timesync pacing, pcap freeze, adaptive delay) were grown while consumption
 * ran at wire = sim + D (zero real delay, permanent pred_depth 1). Under §44
 * real delay they are the RECOVERY path — in steady state the cushion keeps
 * remote rows a full D ahead of consumption and none of them fire. */

#include "psx_netplay_sched.h"

#if !defined(PSX_HAS_RECOMP_NET)
/* Single-player / PSX_NETPLAY=OFF: no recomp-net. Match psx_netplay_rb.c. */
void np_sched_bind(const PsxNpSchedBridge *bridge) { (void)bridge; }
void np_sched_reset_session(void) {}
uint32_t np_sched_wire_for_sim(uint32_t sim_tick) { return sim_tick; }
int np_sched_real_delay_enabled(void) { return 0; }
void np_sched_sync_delay_from_session(void) {}
int np_sched_pre_admit(uint32_t sim, uint32_t wire, const RNetSessionStats *st)
{
    (void)sim;
    (void)wire;
    (void)st;
    return 0;
}
int np_sched_on_remote_miss(int slot, uint32_t sim, uint32_t wire,
                            const RNetSessionStats *st, int pred,
                            const char **reason_out)
{
    (void)slot;
    (void)sim;
    (void)wire;
    (void)st;
    (void)pred;
    if (reason_out)
        *reason_out = "off";
    return 0;
}
void np_sched_note_remote_hit(void) {}
void np_sched_post_admit(int any_invent) { (void)any_invent; }
void np_sched_set_admit_stall(const char *tag) { (void)tag; }
void np_sched_clear_admit_stall(void) {}
const char *np_sched_admit_stall_tag(void) { return ""; }
void np_sched_note_mispredict(uint32_t age) { (void)age; }
void np_sched_note_episode_boundary(void) {}
void np_sched_arm_absurd_invent_catchup(void) {}
#else /* PSX_HAS_RECOMP_NET */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "host_time.h"
#include "psx_netplay.h"
#include "psx_netplay_rb.h"
#include "recomp_net/recomp_net.h"

/* §104/§105: auto-delay / lobby seed floors (shared with sync_delay). */
#define RB_FORCE_TURN_DELAY_FLOOR 6
#define RB_AUTO_DELAY_LOWER_FLOOR 5

/* ------------------------------------------------------------------ */
/* Bridge into psx_netplay.c state                                     */
/* ------------------------------------------------------------------ */

static PsxNpSchedBridge g_sb;

/* Timesync throttle wire tracking — file-scope so rematch can clear it. */
static uint32_t g_ts_last_wire;
static uint32_t g_ts_last_wire_ms;
static uint32_t g_ts_stall_until;
static uint8_t  g_ts_stall_logged;

void np_sched_bind(const PsxNpSchedBridge *bridge)
{
    /* Always drop prior-match policy — bind happens at every psx_netplay_start
     * and (with NULL) on shutdown after soft-return. */
    np_sched_reset_session();
    if (bridge)
        g_sb = *bridge;
    else
        memset(&g_sb, 0, sizeof(g_sb));
}

static RNetSession *sched_session(void)
{
    return g_sb.session ? *g_sb.session : NULL;
}

static int sched_delay(void)
{
    return g_sb.input_delay ? *g_sb.input_delay : 0;
}

static int sched_local_slot(void)
{
    return g_sb.local_slot ? *g_sb.local_slot : -1;
}

static uint32_t sched_mono_ms(void)
{
    /* QPC / CLOCK_MONOTONIC — not GetTickCount64 (coarse on Win32). */
    return (uint32_t)psx_host_mono_ms();
}

/* ------------------------------------------------------------------ */
/* §44: sim→wire consumption mapping (real delay)                      */
/* ------------------------------------------------------------------ */

int np_sched_real_delay_enabled(void)
{
    static int s_mode = -1;
    if (s_mode < 0) {
        const char *e = getenv("PSX_RB_ZERO_DELAY");
        s_mode = (e && e[0] && atoi(e) != 0) ? 0 : 1;
        fprintf(stderr,
                s_mode
                    ? "psxrecomp: rb consumption REAL-DELAY (§44: guest tick T "
                      "plays wire T; local sample stored at T+D — D is a real "
                      "cushion; PSX_RB_ZERO_DELAY=1 restores legacy)\n"
                    : "psxrecomp: rb consumption ZERO-DELAY (legacy: guest tick "
                      "T plays wire T+D sampled the same admit — no cushion, "
                      "permanent pred_depth 1)\n");
        fflush(stderr);
    }
    return s_mode;
}

uint32_t np_sched_wire_for_sim(uint32_t sim_tick)
{
    int d;
    if (np_sched_real_delay_enabled())
        return sim_tick;
    d = sched_delay();
    if (d < 0)
        d = 0;
    if (d > 255)
        d = 255;
    return rnet_wire_tick_from_sim(sim_tick, (rnet_u8)d);
}

void np_sched_sync_delay_from_session(void)
{
    rnet_u8 d;
    RNetSession *s = sched_session();
    if (!s || !g_sb.input_delay)
        return;
    d = rnet_session_committed_delay(s);
    /* §105: rollback never runs undersized D from lobby seed (session-149
     * started D=4 → invent storm → auto-delay ratchet to 7). Floor matches
     * auto-delay lower bound; Force-TURN keeps its higher floor via adapt. */
    if (d >= 2u && d < (rnet_u8)RB_AUTO_DELAY_LOWER_FLOOR &&
        np_sched_real_delay_enabled()) {
        static int s_floor_log;
        if (!s_floor_log) {
            fprintf(stderr,
                    "psxrecomp: rb delay floor %u → %u (rollback min D; "
                    "lobby seed was undersized)\n",
                    (unsigned)d, (unsigned)RB_AUTO_DELAY_LOWER_FLOOR);
            fflush(stderr);
            s_floor_log = 1;
        }
        d = (rnet_u8)RB_AUTO_DELAY_LOWER_FLOOR;
    }
    if (d >= 2u && (int)d != *g_sb.input_delay) {
        fprintf(stderr, "psxrecomp: rb delay committed %d → %u (session)\n",
                *g_sb.input_delay, (unsigned)d);
        fflush(stderr);
        *g_sb.input_delay = (int)d;
    } else if (d >= 2u) {
        *g_sb.input_delay = (int)d;
    }
}

/* ------------------------------------------------------------------ */
/* Invent-grace RTT estimate                                           */
/* ------------------------------------------------------------------ */

/* Rematch boot gates — cleared in np_sched_reset_session (not function-static). */
static int g_boot_tip_logged;
static int g_boot_dig0_logged;

/* After episode commit: refuse invent until remote tip rebuilds most of D. */
static int g_cushion_rebuild;
/* §56: when the current rebuild window opened (episode boundary). A full
 * cushion (lead >= D) clears immediately; a near-cushion lead (D-1) only
 * clears after a hold-off so the rebuild actually reaches equilibrium
 * instead of declaring victory one tick short and inventing into the gap. */
static uint32_t g_cushion_rebuild_since_ms;
/* §83 C: invent through cushion_rebuild while remote_lead is absurd after a
 * baseline-abort Live realign (soak: lead=500 refuse invent → crawl). 0 = off. */
static uint32_t g_absurd_catchup_until_ms;
#define RB_ABSURD_INVENT_CATCHUP_MS 2500u

/* ------------------------------------------------------------------ */
/* §57: arrival-driven delay controller state                          */
/*                                                                      */
/* The §56 soak proved the scheduler converges to the equilibrium the   */
/* delay budget permits: lead ≈ D − 1 − transit_ticks (measured 0.24 /  */
/* 0.91 with D=4 and ~2.1–2.8 ticks of transit), with ~25% of ticks     */
/* missing their row at need. D must therefore be provisioned from the  */
/* ARRIVAL stream (what the scheduler actually consumes), not from the  */
/* POST RTT EMA — the two peers' RTT estimates disagreed 80 vs 12 ms on */
/* the same link. Accumulators reset each controller eval window.       */
/* ------------------------------------------------------------------ */

static uint32_t g_ad_ticks;       /* live lead samples this window */
static int64_t  g_ad_lead_sum;
static uint32_t g_ad_miss;        /* rows absent at need (once per wire) */
static uint32_t g_ad_late_n;      /* misses that later arrived (waited out) */
static uint32_t g_ad_late_sum_ms; /* how late those rows were vs need */
static uint32_t g_ad_late_max_ms;
static int      g_ad_miss_pending; /* waiting to time the current miss */
static uint32_t g_ad_miss_t0_ms;
/* Transit estimate EMA in 1/16-tick units: transit ≈ D − 1 − lead_avg.
 * Also feeds the cushion-rebuild achievable-lead target (§57). */
static uint32_t g_transit_x16;
static int      g_transit_have;

/* Invent-grace RTT: POST-handshake EMA is asymmetric (often 0 on the peer
 * that receives POST first / light-tip skips). Always keep a D-scaled synth
 * floor so both peers share a comparable patience baseline; trusted raw can
 * only raise the estimate, never drop below the floor. */
static uint32_t np_invent_rtt_ms(uint32_t *raw_out)
{
    uint32_t raw = psx_netplay_rb_rtt_estimate_ms();
    uint32_t tick_ms = 17u;
    uint32_t delay_ticks;
    uint32_t synth;
    int d = sched_delay();
    if (raw_out)
        *raw_out = raw;
    delay_ticks = (uint32_t)(d > 0 ? d : 4);
    synth = (delay_ticks * tick_ms) / 4u; /* ~1/4 of the delay runway in ms */
    if (synth < 8u)
        synth = 8u;
    if (synth > 24u)
        synth = 24u;
    if (raw >= 4u && raw > synth)
        return raw;
    return synth;
}

/* ------------------------------------------------------------------ */
/* Stall-before-invent grace (§21/§23/§26)                             */
/* ------------------------------------------------------------------ */

/* Stall-before-invent grace. Soaks showed every menu episode was a real
 * press/release edge whose wire row landed only 1–2 ticks after the seal
 * point (LAN, admit skew — not link latency): invent-on-first-miss then
 * mispredicted the edge and opened a paired episode every few ticks
 * (resim storm, 0.44–0.8x). Before inventing a missing remote row, stall
 * the admit up to PSX_RB_INVENT_GRACE_MS (default 30) measured from the
 * first miss of that wire tick. This is a rate governor, not just packet
 * wait: while the ahead peer stalls here, the behind peer keeps simulating
 * and catches up, so in steady state the sims stay aligned and inputs
 * arrive before the seal with no stall at all.
 * Adaptive off: if the grace keeps expiring (peer genuinely lagging beyond
 * the budget — real WAN latency), disable it for a while so we don't add a
 * per-tick stall on top of real lag. Host-side pacing only — the invented
 * value is unchanged (hold-last), so guest determinism is unaffected.
 * budget_cap: hard ceiling on this stall (0 = disabled / invent now;
 * UINT32_MAX = full §21 budget for gap>=2). count_expire: only gap>=2
 * expiries feed the adaptive-off streak. */
static int np_invent_grace_stall_ex(int slot, rnet_u32 wire, uint32_t budget_cap,
                                    int count_expire)
{
    static int      s_grace_ms = -1;
    static rnet_u32 s_wire[PSX_MAX_PLAYERS];
    static uint32_t s_t0[PSX_MAX_PLAYERS];
    static uint8_t  s_expired[PSX_MAX_PLAYERS];
    static uint8_t  s_budget_logged[PSX_MAX_PLAYERS];
    static uint32_t s_expire_streak;
    static uint32_t s_off_until;
    static uint32_t s_tick_ema_ms; /* fallback-only EMA of inter-tick period, ms */
    uint32_t now;
    uint32_t budget;
    uint32_t rtt;
    uint32_t rtt_raw;
    uint32_t delay_ms = 0;

    if (s_grace_ms < 0) {
        const char *e = getenv("PSX_RB_INVENT_GRACE_MS");
        s_grace_ms = (e && e[0]) ? atoi(e) : 8;
        if (s_grace_ms < 0) s_grace_ms = 0;
        if (s_grace_ms > 200) s_grace_ms = 200;
        fprintf(stderr,
                "psxrecomp: rb invent grace floor=%d ms (minimum stall before "
                "hold-last invent; PSX_RB_INVENT_GRACE_MS — actual per-stall "
                "budget scales up from measured/synth RTT, see 'rb invent "
                "grace budget' lines; gap=1 uses a short cap, see §23)\n",
                s_grace_ms);
        fflush(stderr);
    }
    if (s_grace_ms == 0 || budget_cap == 0u || slot < 0 || slot >= PSX_MAX_PLAYERS)
        return 0;
    now = sched_mono_ms();
    if (s_off_until != 0u && (int32_t)(now - s_off_until) < 0)
        return 0;
    s_off_until = 0u;
    if (s_wire[slot] != wire) {
        /* Previous tracked tick arrived before its grace expired (we moved
         * on without hitting the expiry path) — the link is keeping up. */
        if (s_wire[slot] != 0u && !s_expired[slot])
            s_expire_streak = 0;
        /* Consecutive tracked ticks give the live tick period — diagnostics
         * only; invent budget prefers np_invent_rtt_ms(). */
        if (s_wire[slot] != 0u && wire == s_wire[slot] + 1u) {
            uint32_t dt = now - s_t0[slot];
            if (dt >= 1u && dt <= 250u)
                s_tick_ema_ms = s_tick_ema_ms
                                    ? (3u * s_tick_ema_ms + dt) / 4u
                                    : dt;
        }
        s_wire[slot] = wire;
        s_t0[slot] = now;
        s_expired[slot] = 0;
        s_budget_logged[slot] = 0;
        return 1;
    }
    budget = (uint32_t)s_grace_ms;
    rtt = np_invent_rtt_ms(&rtt_raw);
    /* Ceiling scales with the configured input_delay (§21): half the nominal
     * delay window (floored so D<=4 keeps usable patience, capped so a very
     * large D can't hang admit indefinitely). */
    {
        uint32_t tick_ms = s_tick_ema_ms ? s_tick_ema_ms : 17u; /* ~59.94Hz nominal */
        int d = sched_delay();
        uint32_t delay_ticks = (uint32_t)(d > 0 ? d : 0);
        uint32_t rtt_ceiling;
        delay_ms = delay_ticks * tick_ms;
        rtt_ceiling = delay_ms / 2u;
        /* §26: floor was 60ms — with D=4 synth RTT that forced a 25ms+
         * invent tax every RUNWAY_EMPTY miss and capped WAN at ~30fps even
         * after gap1 invent. Cap patience closer to one frame. */
        if (rtt_ceiling < 20u) rtt_ceiling = 20u;
        if (rtt_ceiling > 80u) rtt_ceiling = 80u;

        /* 1.5x invent RTT (trusted POST sample or D-scaled synth). */
        {
            uint32_t scaled = rtt + rtt / 2u;
            if (scaled > budget)
                budget = scaled;
            if (budget > rtt_ceiling)
                budget = rtt_ceiling;
        }
    }
    if (budget_cap != 0xffffffffu && budget > budget_cap)
        budget = budget_cap;
    if (!s_budget_logged[slot]) {
        s_budget_logged[slot] = 1;
        fprintf(stderr,
                "psxrecomp: rb invent grace budget=%u ms (floor=%d rtt=%u "
                "rtt_raw=%u tick_ema=%u delay_ms=%u cap=%u) slot=%d wire=%u\n",
                (unsigned)budget, s_grace_ms, (unsigned)rtt, (unsigned)rtt_raw,
                (unsigned)s_tick_ema_ms, (unsigned)delay_ms,
                (unsigned)budget_cap, slot, (unsigned)wire);
        fflush(stderr);
    }
    if ((uint32_t)(now - s_t0[slot]) < budget)
        return 1;
    if (!s_expired[slot]) {
        s_expired[slot] = 1;
        if (count_expire && ++s_expire_streak >= 15u) {
            s_expire_streak = 0;
            /* §26: WAN soaks needed invent-free sooner than 45×25ms (~2s of
             * admit tax before OFF). Hold OFF longer so FMV/menu cutovers
             * don't immediately re-arm a 25ms per-tick stall. */
            s_off_until = now + 5000u;
            fprintf(stderr,
                    "psxrecomp: rb invent grace OFF 5s (remote input "
                    "consistently later than %u ms)\n",
                    (unsigned)budget);
            fflush(stderr);
        }
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/* Gap=1 policy (§27–§29, §43)                                         */
/* ------------------------------------------------------------------ */

static uint32_t g_gap1_shrink_until_ms;
static uint32_t g_gap1_expire_invent_streak;
#define RB_GAP1_SHRINK_CAP_MS 6u
#define RB_GAP1_SHRINK_HOLD_MS 1000u
/* §27: deep invent (pred_depth≥2) only after tip looks stale. */
#define RB_INVENT_DEPTH_STALE_FLOOR_MS 40u
/* §29: A/B classification — tip considered "advancing" if its last advance
 * was within this multiple of its own arrival-period EMA (x2 fixed point). */
#define RB_TIP_FRESH_MULT_X2 3u

/* §43/§104/§105/§107: micro-grace before a gap=1 invent. Session-149 invents
 * were 100% remote_lead=-1. §105 waited only when RTT≤48 or tip-due (cap 12).
 * Post-§105 soak: 1277/1305 host invents had rtt>48 (SFU ~75ms) → lan gate
 * off → gap1_cap=0 → invent every tip tick. §107: always grace on gap=1
 * (non-FMV), scale ½RTT+base, LAN cap 12 / relay cap 20. */
#define RB_GAP1_LAN_RTT_MAX_MS 48u
#define RB_GAP1_LAN_GRACE_BASE_MS 4u
#define RB_GAP1_LAN_GRACE_CAP_MS 12u
#define RB_GAP1_RELAY_GRACE_CAP_MS 20u
/* §104: runway (gap≥2) grace — was 8; guest RUNWAY_EMPTY invent was high. */
#define RB_INVENT_RUNWAY_GRACE_CAP_MS 12u

/* §28: tip arrival cadence — tracks how often the confirmed remote tip
 * (highest_remote_wire) actually advances, independent of whether admit
 * hit a miss. Lets a gap=1 miss be judged against "is a new row about due"
 * instead of a flat timeout. */
static uint32_t g_tip_last_highest;
static uint32_t g_tip_last_advance_ms;
static uint32_t g_tip_arrival_ema_ms;
static uint8_t  g_tip_have_advance;

static void np_tip_track_advance(rnet_u32 highest_remote_wire)
{
    uint32_t now = sched_mono_ms();

    if (!g_tip_have_advance) {
        g_tip_last_highest = highest_remote_wire;
        g_tip_last_advance_ms = now;
        g_tip_have_advance = 1;
        return;
    }
    if (highest_remote_wire == g_tip_last_highest)
        return;
    {
        uint32_t dt = now - g_tip_last_advance_ms;
        if (dt >= 1u && dt <= 250u)
            g_tip_arrival_ema_ms = g_tip_arrival_ema_ms
                                        ? (3u * g_tip_arrival_ema_ms + dt) / 4u
                                        : dt;
    }
    g_tip_last_highest = highest_remote_wire;
    g_tip_last_advance_ms = now;
}

/* ms since the remote tip last advanced; UINT32_MAX if never observed yet
 * (treated as stale — no evidence the pipeline is healthy). */
static uint32_t np_tip_age_ms(void)
{
    if (!g_tip_have_advance)
        return 0xffffffffu;
    return sched_mono_ms() - g_tip_last_advance_ms;
}

/* has_override: set to 1 if PSX_RB_GAP1_GRACE_MS forces a flat cap (the
 * return value is that cap, already SHRINK-adjusted). Set to 0 when
 * unset — caller should run the §28 adaptive Case A/B split instead. */
static uint32_t np_gap1_grace_cap_ms(int *has_override)
{
    static int s_cap = -2; /* -2 unset */
    uint32_t rtt_raw;
    uint32_t cap;
    uint32_t now;

    if (s_cap == -2) {
        const char *e = getenv("PSX_RB_GAP1_GRACE_MS");
        if (e && e[0]) {
            s_cap = atoi(e);
            if (s_cap < 0) s_cap = 0;
            if (s_cap > 40) s_cap = 40;
            fprintf(stderr,
                    "psxrecomp: rb gap1 invent grace cap=%d ms "
                    "(PSX_RB_GAP1_GRACE_MS override; §28 adaptive split "
                    "disabled)\n",
                    s_cap);
            fflush(stderr);
        } else {
            s_cap = -1; /* §28: no flat override, adaptive split decides */
            fprintf(stderr,
                    "psxrecomp: rb gap1 invent grace: adaptive §28 split "
                    "(healthy/advancing tip waits a few ms; stale tip "
                    "invents now; PSX_RB_GAP1_GRACE_MS forces a flat cap)\n");
            fflush(stderr);
        }
    }
    if (has_override)
        *has_override = (s_cap >= 0);
    if (s_cap < 0)
        return 0u;
    now = sched_mono_ms();
    if (s_cap == 0)
        return 0u;
    cap = (uint32_t)s_cap;
    /* Only shrink when we have a trusted link sample — otherwise shrink
     * recreates the guest invent/host wait split. */
    rtt_raw = psx_netplay_rb_rtt_estimate_ms();
    if (rtt_raw < 4u) {
        g_gap1_shrink_until_ms = 0u;
    } else if (g_gap1_shrink_until_ms != 0u &&
               (int32_t)(now - g_gap1_shrink_until_ms) < 0) {
        if (cap > RB_GAP1_SHRINK_CAP_MS)
            cap = RB_GAP1_SHRINK_CAP_MS;
    } else {
        g_gap1_shrink_until_ms = 0u;
    }
    return cap;
}

/* Call after inventing at gap=1 when grace already expired for this wire. */
static void np_gap1_note_expire_invent(void)
{
    uint32_t now = sched_mono_ms();
    /* No SHRINK while POST-RTT is untrusted — both peers must keep the same
     * invent patience (see rb-diag1/2 guest rtt=0–1 vs host 15–48). */
    if (psx_netplay_rb_rtt_estimate_ms() < 4u) {
        g_gap1_expire_invent_streak = 0u;
        return;
    }
    if (++g_gap1_expire_invent_streak < 10u)
        return;
    g_gap1_expire_invent_streak = 0u;
    g_gap1_shrink_until_ms = now + RB_GAP1_SHRINK_HOLD_MS;
    fprintf(stderr,
            "psxrecomp: rb gap1 invent grace SHRINK %ums for %ums "
            "(stall expired into invent repeatedly; trusted RTT only)\n",
            (unsigned)RB_GAP1_SHRINK_CAP_MS, (unsigned)RB_GAP1_SHRINK_HOLD_MS);
    fflush(stderr);
}

void np_sched_note_remote_hit(void)
{
    g_gap1_expire_invent_streak = 0u;
    /* §57: a miss we chose to wait out just paid off — the row's lateness
     * (first-miss → hit) is exactly the extra runway D was short by. */
    if (g_ad_miss_pending) {
        uint32_t late = (uint32_t)(sched_mono_ms() - g_ad_miss_t0_ms);
        g_ad_miss_pending = 0;
        if (late < 2000u) { /* discard episode/pause artifacts */
            g_ad_late_sum_ms += late;
            if (late > g_ad_late_max_ms)
                g_ad_late_max_ms = late;
            g_ad_late_n++;
        }
    }
}

/* ------------------------------------------------------------------ */
/* Mispredict-driven timesync pacing (§29–§32)                         */
/* ------------------------------------------------------------------ */

/* The ground truth for "I am the ahead peer" is the mispredict itself: only
 * the ahead side promotes real rows that arrived AFTER it already invented
 * them WRONG — note_late() is gated on pads_differ in the reconcile caller.
 * Each genuine mispredict adds ~1.25 ticks of pacing debt (capped at 3
 * ticks); the admit path shaves the debt off at <=6 ms per tick. Zero cost
 * in steady state. Host pacing only — guest determinism unaffected.
 * PSX_RB_TIMESYNC=0 disables. */
static int      g_ts_enabled = -1;
static uint32_t g_ts_tick_ema_ms;
static uint32_t g_ts_debt_ms;
static uint32_t g_ts_pegged_streak; /* consecutive mispredicts landing at/above cap */
static uint32_t g_ts_off_until_ms;
/* §30 soak counters: mispredicts = remote pads_differ resolves;
 * note_late_applied = debt actually added; note_late_suppressed_rb =
 * note_late early-out while rb_active/tip_holding. */
static uint32_t g_ts_mispredict_count;
/* §32: cumulative/max prediction "age" (ticks ridden before a wrong guess
 * was caught) across mispredicts. */
static uint64_t g_ts_mispredict_age_sum;
static uint32_t g_ts_mispredict_age_max;
static uint32_t g_ts_note_late_applied;
static uint32_t g_ts_note_late_suppressed_rb;
static uint32_t g_ts_note_late_suppressed_off;
static uint32_t g_ts_debt_added_ms; /* cumulative debt added (pre-cap clamp) */
/* remote_lead samples taken every live admit (window reset on phase-ctrl log). */
static int64_t  g_ts_lead_sum;
static uint32_t g_ts_lead_n;
static int      g_ts_lead_min;
static int      g_ts_lead_max;
static int      g_ts_lead_have;

static void np_timesync_check_enabled(void)
{
    if (g_ts_enabled < 0) {
        const char *e = getenv("PSX_RB_TIMESYNC");
        g_ts_enabled = (e && e[0]) ? (atoi(e) != 0) : 1;
    }
}

void np_sched_note_episode_boundary(void)
{
    /* Resim/tip-hold can leave debt elevated; clear only the pegged-streak
     * off-guard so the next live mispredicts can re-arm pacing. Keep debt —
     * the ahead peer may still need a few ms/tick shaves after TipHold. */
    g_ts_pegged_streak = 0u;
    if (!g_cushion_rebuild) {
        uint32_t now = sched_mono_ms();
        g_cushion_rebuild_since_ms = now ? now : 1u;
    }
    g_cushion_rebuild = 1;
}

void np_sched_arm_absurd_invent_catchup(void)
{
    uint32_t now = sched_mono_ms();
    g_absurd_catchup_until_ms = now + RB_ABSURD_INVENT_CATCHUP_MS;
    if (g_absurd_catchup_until_ms == 0u)
        g_absurd_catchup_until_ms = 1u;
    fprintf(stderr,
            "psxrecomp: rb absurd invent catchup armed %u ms "
            "(baseline-abort realign — invent allowed despite absurd lead)\n",
            (unsigned)RB_ABSURD_INVENT_CATCHUP_MS);
    fflush(stderr);
}

static int absurd_invent_catchup_active(uint32_t now)
{
    if (g_absurd_catchup_until_ms == 0u)
        return 0;
    if ((int32_t)(now - g_absurd_catchup_until_ms) >= 0) {
        g_absurd_catchup_until_ms = 0u;
        return 0;
    }
    return 1;
}

void psx_netplay_timesync_on_episode_boundary(void)
{
    np_sched_note_episode_boundary();
}

/* Reconcile saw a real remote row that contradicted what we invented for
 * this tick — i.e. we are (locally) the mispredicting/ahead peer for this
 * edge. Add pacing debt. Adaptive off: the "this is transit latency, not
 * phase skew" signal is debt landing AT THE CAP repeatedly with no room to
 * have drained in between (§30 rationale in docs). */
static void np_timesync_note_late(uint32_t age)
{
    uint32_t now;
    uint32_t add;
    uint32_t cap;
    uint32_t expected_age;
    uint32_t extra_age;
    int d = sched_delay();

    np_timesync_check_enabled();
    if (!g_ts_enabled)
        return;
    /* Replay/tip-hold cost is not phase skew — do not feed pegged-streak
     * adaptive-off (fight/resim load used to look like "WAN transit"). */
    if (psx_netplay_rb_active() || psx_netplay_rb_tip_holding()) {
        g_ts_note_late_suppressed_rb++;
        return;
    }
    /* §98: FMV media invent/mispredict noise must not pile timesync debt —
     * each 6 ms/tick shave showed up as admit=5–11 ms/f in FMV soaks. */
    if (psx_netplay_rb_fmv_media_active()) {
        g_ts_note_late_suppressed_rb++;
        return;
    }
    now = sched_mono_ms();
    if (g_ts_off_until_ms != 0u && (int32_t)(now - g_ts_off_until_ms) < 0) {
        g_ts_note_late_suppressed_off++;
        return;
    }
    g_ts_off_until_ms = 0u;
    /* ~1.25 ticks per mispredict, cap 3 ticks (§29: mispredicts are sparse —
     * hold-last suppresses most gap1 misses from ever becoming one — so the
     * per-edge closure must be strong enough to walk a persistent phase
     * offset back inside one exchange). */
    add = g_ts_tick_ema_ms ? (g_ts_tick_ema_ms * 5u) / 4u : 20u;
    cap = g_ts_tick_ema_ms ? g_ts_tick_ema_ms * 3u : 50u;
    /* §32 lead regulation: a mispredict resolved right at the normal
     * input-delay boundary (age ≈ D) is expected steady-state noise. One
     * that rode notably longer means we were running unusually far ahead of
     * the confirmed remote tip when we guessed it; scale extra debt by how
     * far past D it went (+25% of the base add per extra tick of age). */
    expected_age = d > 0 ? (uint32_t)d : 2u;
    extra_age = (age > expected_age) ? (age - expected_age) : 0u;
    if (extra_age)
        add += (add * extra_age) / 4u;
    /* 18 consecutive cap-hits: fight scenes can peg briefly while pacing is
     * still working; require a longer streak before declaring transit. */
    if (g_ts_debt_ms >= cap) {
        if (++g_ts_pegged_streak >= 18u) {
            g_ts_pegged_streak = 0u;
            g_ts_debt_ms = 0u;
            g_ts_off_until_ms = now + 10000u;
            fprintf(stderr,
                    "psxrecomp: rb timesync OFF 10s (mispredicts keep landing "
                    "at the pacing cap — transit latency, not phase skew)\n");
            fflush(stderr);
            return;
        }
    } else {
        g_ts_pegged_streak = 0u;
    }
    g_ts_debt_ms += add;
    if (g_ts_debt_ms > cap)
        g_ts_debt_ms = cap;
    g_ts_note_late_applied++;
    g_ts_debt_added_ms += add;
}

void np_sched_note_mispredict(uint32_t age)
{
    g_ts_mispredict_count++;
    /* Raw signal (age-at-catch), independent of whether debt was actually
     * applied below — a suppressed edge (resim/tip-hold/off-guard) still
     * tells us how far ahead this peer was running when it guessed wrong. */
    g_ts_mispredict_age_sum += age;
    if (age > g_ts_mispredict_age_max)
        g_ts_mispredict_age_max = age;
    np_timesync_note_late(age);
}

static void np_timesync_sample_lead(int remote_lead)
{
    if (!g_ts_lead_have) {
        g_ts_lead_min = remote_lead;
        g_ts_lead_max = remote_lead;
        g_ts_lead_have = 1;
    } else {
        if (remote_lead < g_ts_lead_min)
            g_ts_lead_min = remote_lead;
        if (remote_lead > g_ts_lead_max)
            g_ts_lead_max = remote_lead;
    }
    g_ts_lead_sum += remote_lead;
    g_ts_lead_n++;
}

/* §30: ~1 Hz phase-control soak line. Compare host vs guest:
 * higher lead + higher mispredicts + higher suppressed_rb on one peer
 * ⇒ control-loop instability; balanced/rare suppress ⇒ gameplay/transport. */
static void np_phase_ctrl_maybe_log(uint32_t now, rnet_u32 sim, int remote_lead)
{
    static uint32_t s_last;
    int lead_avg;

    if (s_last != 0u && (uint32_t)(now - s_last) < 1000u)
        return;
    s_last = now ? now : 1u;
    lead_avg = g_ts_lead_n ? (int)(g_ts_lead_sum / (int64_t)g_ts_lead_n)
                           : remote_lead;
    fprintf(stderr,
            "psxrecomp: rb phase ctrl slot=%d sim=%u lead=%d lead_avg=%d "
            "lead_min=%d lead_max=%d debt_ms=%u debt_added=%u "
            "mispredict=%u mispredict_age_avg=%u mispredict_age_max=%u "
            "note_late=%u suppressed_rb=%u suppressed_off=%u "
            "D=%d\n",
            sched_local_slot(), (unsigned)sim, remote_lead, lead_avg,
            g_ts_lead_have ? g_ts_lead_min : remote_lead,
            g_ts_lead_have ? g_ts_lead_max : remote_lead,
            (unsigned)g_ts_debt_ms, (unsigned)g_ts_debt_added_ms,
            (unsigned)g_ts_mispredict_count,
            (unsigned)(g_ts_mispredict_count
                           ? (g_ts_mispredict_age_sum / g_ts_mispredict_count)
                           : 0u),
            (unsigned)g_ts_mispredict_age_max,
            (unsigned)g_ts_note_late_applied,
            (unsigned)g_ts_note_late_suppressed_rb,
            (unsigned)g_ts_note_late_suppressed_off,
            sched_delay());
    fflush(stderr);
    /* Windowed lead stats reset each second; cumulative counters keep rising. */
    g_ts_lead_sum = 0;
    g_ts_lead_n = 0;
    g_ts_lead_have = 0;
}

/* Admit-side: shave pacing debt off at <=6 ms per tick (§29: was 4; §23:
 * was 3). */
static int np_timesync_throttle(uint32_t wire)
{
    uint32_t now;

    np_timesync_check_enabled();
    if (!g_ts_enabled)
        return 0;
    /* §98: drain media-era debt without stalling admit (FMV guest is already
     * the ceiling; do not stack timesync shaves on top). */
    if (psx_netplay_rb_fmv_media_active()) {
        g_ts_debt_ms = 0u;
        g_ts_stall_until = 0u;
        g_ts_stall_logged = 0;
        return 0;
    }
    now = sched_mono_ms();
    if (wire != g_ts_last_wire) {
        if (g_ts_last_wire != 0u && wire == g_ts_last_wire + 1u) {
            uint32_t dt = now - g_ts_last_wire_ms;
            if (dt >= 1u && dt <= 250u)
                g_ts_tick_ema_ms = g_ts_tick_ema_ms
                                       ? (7u * g_ts_tick_ema_ms + dt) / 8u
                                       : dt;
        }
        g_ts_last_wire = wire;
        g_ts_last_wire_ms = now;
        if (g_ts_debt_ms > 0u) {
            uint32_t slice = g_ts_debt_ms > 6u ? 6u : g_ts_debt_ms;
            g_ts_debt_ms -= slice;
            if (g_ts_debt_ms == 0u)
                g_ts_stall_logged = 0;
            g_ts_stall_until = now + slice;
            if (!g_ts_stall_logged) {
                fprintf(stderr,
                        "psxrecomp: rb timesync pacing (debt=%u ms tick=%u ms — "
                        "shaving <=6 ms/tick)\n",
                        (unsigned)(g_ts_debt_ms + slice),
                        (unsigned)g_ts_tick_ema_ms);
                fflush(stderr);
                g_ts_stall_logged = 1;
            }
        }
    }
    if (g_ts_stall_until != 0u && (int32_t)(now - g_ts_stall_until) < 0)
        return 1;
    g_ts_stall_until = 0u;
    return 0;
}

/* ------------------------------------------------------------------ */
/* Admit telemetry + pcap freeze + adaptive delay (§22/§23)            */
/* ------------------------------------------------------------------ */

static uint32_t g_admit_invent_gap1;
static uint32_t g_admit_invent_gap2;
static uint32_t g_admit_invent_gap3p;
static uint32_t g_admit_gap1_grace; /* times gap=1 short grace returned stall */
static uint32_t g_admit_pcap_stalls;
static uint32_t g_admit_pcap_enters;
static int      g_pcap_frozen;
static uint32_t g_pcap_freeze_enters_window;
static uint32_t g_pcap_window_t0_ms;
static uint32_t g_pcap_last_enter_ms;
static uint32_t g_adapt_last_bump_ms;
static uint32_t g_admit_stats_last_log_ms;
/* Soak-only: PSX_RB_ADAPT_DELAY=0 disables mid-match D bumps. */
static int      g_adapt_delay_enabled = -1;

#define RB_ADAPT_FREEZE_ENTERS_THRESH 3u
#define RB_ADAPT_WINDOW_MS            5000u
#define RB_ADAPT_COOLDOWN_MS          10000u
#define RB_ADAPT_DELAY_MAX            16

static void np_admit_note_invent_gap(rnet_u32 wire, rnet_u32 highest_remote)
{
    rnet_u32 gap;
    if (wire <= highest_remote)
        gap = 0u;
    else
        gap = wire - highest_remote;
    if (gap <= 1u)
        g_admit_invent_gap1++;
    else if (gap == 2u)
        g_admit_invent_gap2++;
    else
        g_admit_invent_gap3p++;
}

/* Why we spent prediction budget (one line per invent; throttle bursts). */
static uint32_t g_admit_invent_runway_empty;
static uint32_t g_admit_invent_tip_stale;
static uint32_t g_admit_invent_gap1_legacy;
static uint32_t g_admit_cushion_wait; /* lead>0 stalls that refused invent */
/* §28: gap1 Case A/B split telemetry. */
static uint32_t g_admit_gap1_case_a;
static uint32_t g_admit_gap1_case_b;

static void np_admit_log_invent(rnet_u32 sim, rnet_u32 wire,
                                rnet_u32 highest_remote, int remote_lead,
                                const char *reason)
{
    static uint32_t s_last_ms;
    static uint32_t s_burst;
    uint32_t now = sched_mono_ms();
    uint32_t pred_depth =
        (wire > highest_remote) ? (wire - highest_remote) : 0u;
    int D = sched_delay() > 0 ? sched_delay() : 0;

    if (s_last_ms != 0u && (uint32_t)(now - s_last_ms) < 50u) {
        s_burst++;
        if ((s_burst & 15u) != 0u)
            return;
    } else {
        s_burst = 0u;
    }
    s_last_ms = now ? now : 1u;
    fprintf(stderr,
            "psxrecomp: rb invent sim=%u wire=%u remote_tip=%u D=%d "
            "pred_depth=%u remote_lead=%d reason=%s%s\n",
            (unsigned)sim, (unsigned)wire, (unsigned)highest_remote, D,
            (unsigned)pred_depth, remote_lead, reason,
            s_burst ? " (burst)" : "");
    fflush(stderr);
}

static void np_admit_log_runway(uint32_t now, rnet_u32 sim, rnet_u32 wire,
                                rnet_u32 highest_remote, int remote_lead)
{
    static uint32_t s_last;
    uint32_t pred_depth;
    int runway_rem;
    uint32_t rtt_raw = 0;
    uint32_t rtt = np_invent_rtt_ms(&rtt_raw);
    int D = sched_delay() > 0 ? sched_delay() : 0;

    if (s_last != 0u && (uint32_t)(now - s_last) < 1000u)
        return;
    s_last = now ? now : 1u;
    pred_depth = (wire > highest_remote) ? (wire - highest_remote) : 0u;
    /* How many delay frames of remote tip remain vs live sim. */
    runway_rem = remote_lead; /* highest_remote - sim; §44 healthy ≈ D */
    fprintf(stderr,
            "psxrecomp: rb runway sim=%u wire=%u remote_tip=%u D=%d P=%d "
            "pred_depth=%u remote_lead=%d runway_rem=%d cushion=%d "
            "rtt=%u rtt_raw=%u\n",
            (unsigned)sim, (unsigned)wire, (unsigned)highest_remote, D,
            g_sb.input_prediction ? *g_sb.input_prediction : 0,
            (unsigned)pred_depth, remote_lead,
            runway_rem, g_cushion_rebuild, (unsigned)rtt, (unsigned)rtt_raw);
    fflush(stderr);
    (void)D;
}

static void np_admit_maybe_log_stats(uint32_t now)
{
    if (g_admit_stats_last_log_ms != 0u &&
        (uint32_t)(now - g_admit_stats_last_log_ms) < 5000u)
        return;
    g_admit_stats_last_log_ms = now ? now : 1u;
    fprintf(stderr,
            "psxrecomp: rb admit stats invent_gap1=%u gap2=%u gap3+=%u "
            "gap1_grace=%u gap1_case_a=%u gap1_case_b=%u tip_ema=%u "
            "invent_runway_empty=%u invent_tip_stale=%u "
            "invent_gap1_legacy=%u cushion_wait=%u "
            "pcap_stalls=%u pcap_enters=%u freeze=%d D=%d P=%d cushion=%d "
            "mispredict=%u note_late=%u suppressed_rb=%u suppressed_off=%u "
            "debt_ms=%u debt_added=%u\n",
            (unsigned)g_admit_invent_gap1, (unsigned)g_admit_invent_gap2,
            (unsigned)g_admit_invent_gap3p, (unsigned)g_admit_gap1_grace,
            (unsigned)g_admit_gap1_case_a, (unsigned)g_admit_gap1_case_b,
            (unsigned)g_tip_arrival_ema_ms,
            (unsigned)g_admit_invent_runway_empty,
            (unsigned)g_admit_invent_tip_stale,
            (unsigned)g_admit_invent_gap1_legacy,
            (unsigned)g_admit_cushion_wait,
            (unsigned)g_admit_pcap_stalls, (unsigned)g_admit_pcap_enters,
            g_pcap_frozen, sched_delay(),
            g_sb.input_prediction ? *g_sb.input_prediction : 0,
            g_cushion_rebuild,
            (unsigned)g_ts_mispredict_count,
            (unsigned)g_ts_note_late_applied,
            (unsigned)g_ts_note_late_suppressed_rb,
            (unsigned)g_ts_note_late_suppressed_off,
            (unsigned)g_ts_debt_ms,
            (unsigned)g_ts_debt_added_ms);
    fflush(stderr);
}

/* BattleShip-style Win↔Linux cadence triage. PSX_NETPLAY_CROSS_OS_PACING_DIAG=1 */
static int np_cross_os_diag_enabled(void)
{
    static int s = -1;
    if (s < 0) {
        const char *e = getenv("PSX_NETPLAY_CROSS_OS_PACING_DIAG");
        s = (e && e[0] == '1' && e[1] == '\0') ? 1 : 0;
    }
    return s;
}

static const char *np_cross_os_platform(void)
{
#if defined(_WIN32)
    return "windows";
#elif defined(__APPLE__)
    return "darwin";
#elif defined(__linux__)
    return "linux";
#else
    return "other";
#endif
}

static void np_cross_os_maybe_log(uint32_t now, uint32_t sim,
                                  const RNetSessionStats *st)
{
    static uint32_t s_last_ms;
    static uint32_t s_gap1_0;
    static uint32_t s_gap2_0;
    static uint32_t s_gap3_0;
    static uint32_t s_grace_0;
    static uint32_t s_tip_stale_0;
    static uint32_t s_runway_0;
    static uint32_t s_cushion_wait_0;
    static uint32_t s_debt_added_0;
    const char *stall;
    uint32_t tip_age;

    if (!np_cross_os_diag_enabled() || !st)
        return;
    if (s_last_ms != 0u && (uint32_t)(now - s_last_ms) < 1000u)
        return;
    s_last_ms = now ? now : 1u;
    stall = np_sched_admit_stall_tag();
    tip_age = np_tip_age_ms();
    fprintf(stderr,
            "psxrecomp: cross_os_pacing platform=%s slot=%d sim=%u "
            "hr=%u remote_lead=%d D=%d P=%d tip_ema=%u tip_age=%u "
            "debt_ms=%u d_debt_added=%u "
            "d_invent_gap1=%u gap2=%u gap3+=%u grace=%u tip_stale=%u "
            "runway=%u cushion_wait=%u stall=%s freeze=%d cushion=%d\n",
            np_cross_os_platform(), sched_local_slot(), (unsigned)sim,
            (unsigned)st->highest_remote_wire, st->remote_lead, sched_delay(),
            g_sb.input_prediction ? *g_sb.input_prediction : 0,
            (unsigned)g_tip_arrival_ema_ms,
            tip_age == 0xffffffffu ? 0u : (unsigned)tip_age,
            (unsigned)g_ts_debt_ms,
            (unsigned)(g_ts_debt_added_ms - s_debt_added_0),
            (unsigned)(g_admit_invent_gap1 - s_gap1_0),
            (unsigned)(g_admit_invent_gap2 - s_gap2_0),
            (unsigned)(g_admit_invent_gap3p - s_gap3_0),
            (unsigned)(g_admit_gap1_grace - s_grace_0),
            (unsigned)(g_admit_invent_tip_stale - s_tip_stale_0),
            (unsigned)(g_admit_invent_runway_empty - s_runway_0),
            (unsigned)(g_admit_cushion_wait - s_cushion_wait_0),
            (stall && stall[0]) ? stall : "-", g_pcap_frozen,
            g_cushion_rebuild);
    fflush(stderr);
    s_gap1_0 = g_admit_invent_gap1;
    s_gap2_0 = g_admit_invent_gap2;
    s_gap3_0 = g_admit_invent_gap3p;
    s_grace_0 = g_admit_gap1_grace;
    s_tip_stale_0 = g_admit_invent_tip_stale;
    s_runway_0 = g_admit_invent_runway_empty;
    s_cushion_wait_0 = g_admit_cushion_wait;
    s_debt_added_0 = g_ts_debt_added_ms;
}

/* ------------------------------------------------------------------ */
/* §56 equilibrium scorecard (per-window deltas, ~30 s)                 */
/*                                                                      */
/* One line answers "is the scheduler converging?": episode rate and    */
/* replay depth move with scheduler changes; slack (ms between a remote */
/* row ARRIVING and being NEEDED at admit) exposes the produce→consume  */
/* pipeline phase that the tick-domain lead quantizes away. Healthy     */
/* real-delay steady state: lead ≈ D, slack ≈ D·16ms − transit,         */
/* miss_need ≈ 0. slack ≈ 0 with "healthy" lead means rows arrive just  */
/* in time — the cushion exists on paper only.                          */
/* ------------------------------------------------------------------ */

static uint32_t g_sc_window_t0_ms;
static uint32_t g_sc_ep0;
static uint64_t g_sc_rt0;
static uint32_t g_sc_gap1_0;
static uint32_t g_sc_tip_stale0;
static int64_t  g_sc_lead_sum;
static uint32_t g_sc_lead_n;
static int      g_sc_lead_min;
static int      g_sc_lead_max;
static uint64_t g_sc_slack_sum;
static uint32_t g_sc_slack_n;
static uint32_t g_sc_slack_min;
static uint32_t g_sc_slack_max;
static uint32_t g_sc_miss_at_need;

static void np_scorecard_window_reset(uint32_t now)
{
    g_sc_window_t0_ms = now ? now : 1u;
    g_sc_ep0 = psx_netplay_rb_episode_count();
    g_sc_rt0 = psx_netplay_rb_replay_ticks_total();
    g_sc_gap1_0 = g_admit_invent_gap1;
    g_sc_tip_stale0 = g_admit_invent_tip_stale;
    g_sc_lead_sum = 0;
    g_sc_lead_n = 0;
    g_sc_lead_min = 0;
    g_sc_lead_max = 0;
    g_sc_slack_sum = 0;
    g_sc_slack_n = 0;
    g_sc_slack_min = 0;
    g_sc_slack_max = 0;
    g_sc_miss_at_need = 0;
}

/* on_remote_miss: the row for `wire` was not there when needed. */
static void np_scorecard_note_miss(rnet_u32 wire)
{
    static rnet_u32 s_counted_wire = 0xffffffffu;
    if (s_counted_wire != wire) {
        s_counted_wire = wire;
        g_sc_miss_at_need++;
        /* §57/§105: feed the delay controller and arm the lateness timer —
         * if we wait this miss out, note_remote_hit measures how late the
         * row was. If we invent instead, np_auto_delay_undo_invent_miss
         * drops the controller sample (session-149: invent→miss 993‰
         * ratcheted D 4→7 without real arrival lateness). */
        g_ad_miss++;
        g_ad_miss_pending = 1;
        g_ad_miss_t0_ms = sched_mono_ms();
    }
}

/* §105: invent is not an arrival miss — undo the controller sample so tip
 * invent storms cannot raise D (mushy input with no cushion gain). */
static void np_auto_delay_undo_invent_miss(void)
{
    if (g_ad_miss_pending) {
        if (g_ad_miss > 0u)
            g_ad_miss--;
        g_ad_miss_pending = 0;
    }
}

static void np_scorecard_sample(uint32_t now, rnet_u32 sim, rnet_u32 wire,
                                const RNetSessionStats *st)
{
    static rnet_u32 s_last_sim = 0xffffffffu;
    RNetSession *s = sched_session();

    if (g_sc_window_t0_ms == 0u)
        np_scorecard_window_reset(now);

    if (s_last_sim != sim) {
        int slot;
        s_last_sim = sim;
        /* §57: controller lead samples — live steady state only. Episode /
         * tip-hold leads (parked sim, lead 10+) and ring-age absurdities
         * would poison the transit estimate. */
        if (!psx_netplay_rb_active() && !psx_netplay_rb_tip_holding() &&
            st->remote_lead > -32 && st->remote_lead < 32) {
            g_ad_ticks++;
            g_ad_lead_sum += st->remote_lead;
        }
        if (!g_sc_lead_n) {
            g_sc_lead_min = st->remote_lead;
            g_sc_lead_max = st->remote_lead;
        } else {
            if (st->remote_lead < g_sc_lead_min)
                g_sc_lead_min = st->remote_lead;
            if (st->remote_lead > g_sc_lead_max)
                g_sc_lead_max = st->remote_lead;
        }
        g_sc_lead_sum += st->remote_lead;
        g_sc_lead_n++;
        if (s) {
            for (slot = 0; slot < RNET_MAX_SLOTS; ++slot) {
                uint32_t age =
                    rnet_session_remote_arrival_age_ms(s, slot, wire);
                if (age == 0xffffffffu)
                    continue;
                if (!g_sc_slack_n) {
                    g_sc_slack_min = age;
                    g_sc_slack_max = age;
                } else {
                    if (age < g_sc_slack_min)
                        g_sc_slack_min = age;
                    if (age > g_sc_slack_max)
                        g_sc_slack_max = age;
                }
                g_sc_slack_sum += age;
                g_sc_slack_n++;
            }
        }
    }

    if ((uint32_t)(now - g_sc_window_t0_ms) >= 30000u) {
        uint32_t ep = psx_netplay_rb_episode_count();
        uint64_t rt = psx_netplay_rb_replay_ticks_total();
        uint32_t d_ep = (ep >= g_sc_ep0) ? (ep - g_sc_ep0) : ep;
        uint64_t d_rt = (rt >= g_sc_rt0) ? (rt - g_sc_rt0) : rt;
        uint32_t d_gap1 = (g_admit_invent_gap1 >= g_sc_gap1_0)
                              ? (g_admit_invent_gap1 - g_sc_gap1_0)
                              : g_admit_invent_gap1;
        uint32_t d_ts = (g_admit_invent_tip_stale >= g_sc_tip_stale0)
                            ? (g_admit_invent_tip_stale - g_sc_tip_stale0)
                            : g_admit_invent_tip_stale;
        double dt_s = (double)(uint32_t)(now - g_sc_window_t0_ms) / 1000.0;
        double lead_avg =
            g_sc_lead_n ? (double)g_sc_lead_sum / (double)g_sc_lead_n : 0.0;
        double depth_avg = d_ep ? (double)d_rt / (double)d_ep : 0.0;
        double slack_avg =
            g_sc_slack_n ? (double)g_sc_slack_sum / (double)g_sc_slack_n : 0.0;
        fprintf(stderr,
                "psxrecomp: rb scorecard dt=%.1fs ep=+%u depth_avg=%.1f "
                "gap1=+%u tip_stale=+%u miss_need=%u "
                "lead avg=%.2f min=%d max=%d "
                "slack avg=%.0fms min=%u max=%u n=%u "
                "transit_est=%.2f D=%d cushion=%d\n",
                dt_s, (unsigned)d_ep, depth_avg, (unsigned)d_gap1,
                (unsigned)d_ts, (unsigned)g_sc_miss_at_need, lead_avg,
                g_sc_lead_min, g_sc_lead_max, slack_avg,
                (unsigned)g_sc_slack_min, (unsigned)g_sc_slack_max,
                (unsigned)g_sc_slack_n,
                g_transit_have ? (double)g_transit_x16 / 16.0 : -1.0,
                sched_delay(), g_cushion_rebuild);
        fflush(stderr);
        np_scorecard_window_reset(now);
    }
}

static void np_adapt_delay_on_pcap_enter(uint32_t now)
{
    const char *e;
    RNetSession *s = sched_session();

    if (g_adapt_delay_enabled < 0) {
        e = getenv("PSX_RB_ADAPT_DELAY");
        g_adapt_delay_enabled = (e && e[0]) ? (atoi(e) != 0) : 1;
    }
    if (!g_adapt_delay_enabled || !s)
        return;
    /* Host / sim-authority only — guests receive DELAY_SYNC. */
    if (sched_local_slot() != 0)
        return;
    /* §98: FMV media invent storms must not ratchet D (soak: D=6→7 while
     * admit climbed to 5–11 ms/f). Keep D stable through the movie. */
    if (psx_netplay_rb_fmv_media_active())
        return;

    if (g_pcap_window_t0_ms == 0u ||
        (uint32_t)(now - g_pcap_window_t0_ms) > RB_ADAPT_WINDOW_MS) {
        g_pcap_window_t0_ms = now ? now : 1u;
        g_pcap_freeze_enters_window = 0u;
    }
    g_pcap_freeze_enters_window++;

    if (g_pcap_freeze_enters_window < RB_ADAPT_FREEZE_ENTERS_THRESH)
        return;
    if (g_adapt_last_bump_ms != 0u &&
        (uint32_t)(now - g_adapt_last_bump_ms) < RB_ADAPT_COOLDOWN_MS)
        return;
    if (sched_delay() >= RB_ADAPT_DELAY_MAX)
        return;

    {
        int old_d = sched_delay();
        int new_d = old_d + 1;
        if (new_d > RB_ADAPT_DELAY_MAX)
            new_d = RB_ADAPT_DELAY_MAX;
        if (rnet_session_request_delay_change(s, (rnet_u8)new_d)) {
            g_adapt_last_bump_ms = now ? now : 1u;
            g_pcap_freeze_enters_window = 0u;
            g_pcap_window_t0_ms = now ? now : 1u;
            fprintf(stderr,
                    "psxrecomp: rb adaptive delay bump %d → %d "
                    "(pcap freezes in window; P stays %d)\n",
                    old_d, new_d,
                    g_sb.input_prediction ? *g_sb.input_prediction : 0);
            fflush(stderr);
        }
    }
}

static void np_pcap_freeze_enter(rnet_u32 wire, rnet_u32 highest_remote, int pred)
{
    uint32_t now = sched_mono_ms();
    g_admit_pcap_stalls++;
    g_pcap_last_enter_ms = now ? now : 1u;
    if (!g_pcap_frozen) {
        g_pcap_frozen = 1;
        g_admit_pcap_enters++;
        fprintf(stderr,
                "psxrecomp: rb pcap FREEZE enter wire=%u remote=%u P=%d "
                "gap=%u D=%d\n",
                (unsigned)wire, (unsigned)highest_remote, pred,
                (unsigned)(wire > highest_remote ? wire - highest_remote : 0u),
                sched_delay());
        fflush(stderr);
        np_adapt_delay_on_pcap_enter(now);
    }
    np_admit_maybe_log_stats(now);
}

static void np_pcap_freeze_exit(void)
{
    if (!g_pcap_frozen)
        return;
    g_pcap_frozen = 0;
    fprintf(stderr,
            "psxrecomp: rb pcap FREEZE exit (remote caught up / invent ok) "
            "D=%d enters=%u\n",
            sched_delay(), (unsigned)g_admit_pcap_enters);
    fflush(stderr);
}

/* ------------------------------------------------------------------ */
/* §44: RTT-based D resolution (host proposes via DELAY_SYNC)          */
/* ------------------------------------------------------------------ */

/* Under real delay, D IS the cushion: a press costs D ticks of local
 * latency and buys D ticks of transit budget.
 *
 * §57 rewrite: D is resolved from the ARRIVAL stream — how the remote rows
 * actually reach the consumption point — instead of the POST RTT EMA, which
 * measured 80 ms on one peer and 12 ms on the other for the same link. Per
 * 5 s eval window (live samples only, both peers accumulate, host decides):
 *   miss_rate  = rows absent at need / live ticks;
 *   lateness   = first-miss → arrival for misses we waited out;
 *   transit    ≈ D − 1 − lead_avg (EMA'd; also drives the cushion-rebuild
 *                achievable-lead target).
 * Raise: miss_rate > 2% → D += ceil(late_avg/tick) (1..2 per step).
 * Lower: miss_rate < 0.2% AND ≥2 ticks of spare lead, must repeat on 3
 * consecutive evals + 30 s cooldown + no pcap freeze in the last 30 s.
 * The reactive §22 bump (np_adapt_delay_on_pcap_enter) still catches freeze
 * storms between eval windows. PSX_RB_AUTO_DELAY=0 disables. */
#define RB_AUTO_DELAY_EVAL_MS     5000u
#define RB_AUTO_DELAY_AGREE       3u
#define RB_AUTO_DELAY_COOLDOWN_MS 30000u
/* Delay floors: RB_FORCE_TURN_DELAY_FLOOR / RB_AUTO_DELAY_LOWER_FLOOR
 * defined near top of file (§104/§105). */

static void np_auto_delay_tick(uint32_t now)
{
    static int      s_enabled = -1;
    static uint32_t s_last_eval_ms;
    static uint32_t s_last_change_ms;
    static uint32_t s_agree_streak;
    static int      s_last_target = -1;
    RNetSession *s = sched_session();
    uint32_t tick_ms = g_ts_tick_ema_ms ? g_ts_tick_ema_ms : 17u;
    uint32_t ticks, miss, late_n, late_sum, late_max;
    int64_t  lead_sum;
    int32_t  lead_avg_x16;
    int32_t  transit_x16;
    uint32_t miss_per_mille;
    int target;
    int d;

    if (s_enabled < 0) {
        const char *e = getenv("PSX_RB_AUTO_DELAY");
        s_enabled = (e && e[0]) ? (atoi(e) != 0) : 1;
        if (s_enabled)
            fprintf(stderr,
                    "psxrecomp: rb auto delay ON (§57: D provisioned from "
                    "arrival misses/lateness, host-proposed; "
                    "PSX_RB_AUTO_DELAY=0 off)\n");
        fflush(stderr);
    }
    if (!s_enabled || !s)
        return;
    if (!np_sched_real_delay_enabled())
        return; /* D is not a latency budget in legacy zero-delay mode */
    if (s_last_eval_ms != 0u && (uint32_t)(now - s_last_eval_ms) < RB_AUTO_DELAY_EVAL_MS)
        return;
    s_last_eval_ms = now ? now : 1u;

    /* Harvest + reset the window (both peers, so guest transit stays live). */
    ticks = g_ad_ticks;
    lead_sum = g_ad_lead_sum;
    miss = g_ad_miss;
    late_n = g_ad_late_n;
    late_sum = g_ad_late_sum_ms;
    late_max = g_ad_late_max_ms;
    g_ad_ticks = 0;
    g_ad_lead_sum = 0;
    g_ad_miss = 0;
    g_ad_late_n = 0;
    g_ad_late_sum_ms = 0;
    g_ad_late_max_ms = 0;

    /* §98: freeze D through FMV media — discard invent-storm samples so the
     * first post-media eval does not ratchet from movie miss_rate. */
    if (psx_netplay_rb_fmv_media_active())
        return;

    d = sched_delay();
    if (ticks < 120u) {
        s_agree_streak = 0u; /* <~2 s of live samples — episode/FMV window */
        return;
    }

    lead_avg_x16 = (int32_t)((lead_sum * 16) / (int64_t)ticks);
    transit_x16 = (int32_t)(d - 1) * 16 - lead_avg_x16;
    if (transit_x16 < 0)
        transit_x16 = 0;
    if (transit_x16 > 12 * 16)
        transit_x16 = 12 * 16;
    if (g_transit_have)
        g_transit_x16 = (g_transit_x16 * 7u + (uint32_t)transit_x16) / 8u;
    else
        g_transit_x16 = (uint32_t)transit_x16;
    g_transit_have = 1;

    if (sched_local_slot() != 0)
        return; /* host proposes; guests follow DELAY_SYNC */

    miss_per_mille = (uint32_t)(((uint64_t)miss * 1000u) / ticks);
    /* §105: raise only on waited-out arrival pressure (late_n>0). Invent-only
     * miss storms (session-149 lead_avg≈-2, late_n=1, miss=993‰) must not
     * ratchet D — raising delay does not stop tip invent. */
    if (miss_per_mille > 20u && late_n > 0u) {
        uint32_t late_avg = late_n ? (late_sum / late_n) : 0u;
        int bump = (int)((late_avg + tick_ms - 1u) / tick_ms);
        if (bump < 1)
            bump = 1;
        if (bump > 2)
            bump = 2;
        target = d + bump;
    } else if (miss_per_mille < 1u && lead_avg_x16 >= 3 * 16) {
        /* §104: tighter lower bar (was miss<2‰ + lead≥2) — session-144
         * shrank D 5→4 under healthy fight cushion and fueled invent. */
        target = d - 1;
    } else {
        target = d;
    }
    {
        int floor_d = RB_AUTO_DELAY_LOWER_FLOOR;
        if (g_sb.force_turn)
            floor_d = RB_FORCE_TURN_DELAY_FLOOR;
        if (target < floor_d)
            target = floor_d;
    }
    if (target > RB_ADAPT_DELAY_MAX)
        target = RB_ADAPT_DELAY_MAX;

    if (target == d) {
        s_agree_streak = 0u;
        s_last_target = target;
        return;
    }
    /* §59: first raise of the session (never changed yet) confirms on 1 eval
     * (~5 s) so a badly under-provisioned lobby D does not invent-storm for
     * a full 10 s. Later raises keep 2-eval confirm; lowers stay at 3. */
    {
        uint32_t need_agree;
        if (target < d)
            need_agree = RB_AUTO_DELAY_AGREE;
        else if (s_last_change_ms == 0u)
            need_agree = 1u;
        else
            need_agree = 2u;
        if (target != s_last_target) {
            s_last_target = target;
            s_agree_streak = 1u;
            if (s_agree_streak < need_agree)
                return;
        } else if (++s_agree_streak < need_agree) {
            return;
        }
    }
    if (s_last_change_ms != 0u &&
        (uint32_t)(now - s_last_change_ms) < RB_AUTO_DELAY_COOLDOWN_MS)
        return;
    if (target < d && g_pcap_last_enter_ms != 0u &&
        (uint32_t)(now - g_pcap_last_enter_ms) < RB_AUTO_DELAY_COOLDOWN_MS)
        return; /* prediction was needed at current D — don't shrink cushion */

    if (rnet_session_request_delay_change(s, (rnet_u8)target)) {
        s_last_change_ms = now ? now : 1u;
        s_agree_streak = 0u;
        fprintf(stderr,
                "psxrecomp: rb auto delay %d → %d (arrival: miss=%u/%u "
                "(%u‰) late avg=%ums max=%ums n=%u lead_avg=%.2f "
                "transit_est=%.2f ticks)\n",
                d, target, (unsigned)miss, (unsigned)ticks,
                (unsigned)miss_per_mille,
                (unsigned)(late_n ? late_sum / late_n : 0u),
                (unsigned)late_max, (unsigned)late_n,
                (double)lead_avg_x16 / 16.0,
                (double)g_transit_x16 / 16.0);
        fflush(stderr);
    }
}

/* ------------------------------------------------------------------ */
/* MotK admit stall tag (barrier logs; rnet last_stall stays "ok")      */
/* ------------------------------------------------------------------ */

static char g_admit_stall_tag[80];

void np_sched_set_admit_stall(const char *tag)
{
    if (!tag || !tag[0]) {
        g_admit_stall_tag[0] = '\0';
        return;
    }
    snprintf(g_admit_stall_tag, sizeof(g_admit_stall_tag), "%s", tag);
}

void np_sched_clear_admit_stall(void)
{
    g_admit_stall_tag[0] = '\0';
}

const char *np_sched_admit_stall_tag(void)
{
    return g_admit_stall_tag;
}

/* Tip ahead of need but consumption wire missing: sliding retransmit window
 * no longer covers the hole (WAN/TURN loss). Rate-limited + stall tag. */
static void np_diag_wire_hole(int slot, uint32_t sim, uint32_t wire,
                              const RNetSessionStats *st, const char *stall_why)
{
    RNetSession *s = sched_session();
    RNetInputSample sample;
    rnet_u32 tip;
    rnet_u32 t;
    rnet_u32 hole_end;
    rnet_u32 first_present = 0;
    int have_present = 0;
    int red;
    int d;
    static rnet_u32 s_last_need;
    static rnet_u32 s_last_tip;
    static uint32_t s_last_log_ms;

    if (!st || !s)
        return;
    tip = st->highest_remote_wire;
    if (tip <= wire)
        return; /* behind tip — ordinary wait, not a hole-under-tip */

    hole_end = wire;
    for (t = wire + 1u; t <= tip; ++t) {
        if (rnet_session_peek_remote_input(s, slot, t, &sample)) {
            first_present = t;
            have_present = 1;
            break;
        }
        hole_end = t;
        if (t == 0xffffffffu)
            break;
    }

    d = sched_delay();
    red = d + 1;
    if (red < (int)RNET_DEFAULT_BUNDLE_REDUNDANCY)
        red = (int)RNET_DEFAULT_BUNDLE_REDUNDANCY;
    {
        rnet_u32 red_lo =
            (tip + 1u > (rnet_u32)red) ? (tip + 1u - (rnet_u32)red) : 0u;
        uint32_t now = sched_mono_ms();
        int same = (s_last_need == wire && s_last_tip == tip);
        if (!same || s_last_log_ms == 0u ||
            (uint32_t)(now - s_last_log_ms) >= 1000u) {
            s_last_need = wire;
            s_last_tip = tip;
            s_last_log_ms = now ? now : 1u;
            fprintf(stderr,
                    "psxrecomp: rb WIRE_HOLE slot=%d sim=%u need=%u tip=%u "
                    "hole_end=%u hole_span=%u first_present=%d lead=%d "
                    "red_win_lo≈%u need_in_red_win=%d stall=%s "
                    "(tip-window retransmit may no longer cover need)\n",
                    slot, (unsigned)sim, (unsigned)wire, (unsigned)tip,
                    (unsigned)hole_end,
                    (unsigned)(hole_end >= wire ? (hole_end - wire + 1u) : 1u),
                    have_present ? (int)first_present : -1, st->remote_lead,
                    (unsigned)red_lo, (wire >= red_lo) ? 1 : 0,
                    stall_why ? stall_why : "?");
            fflush(stderr);
        }
    }
    np_sched_set_admit_stall("wire_hole");
}

/* ------------------------------------------------------------------ */
/* Admit entry points                                                  */
/* ------------------------------------------------------------------ */

int np_sched_pre_admit(uint32_t sim, uint32_t wire, const RNetSessionStats *st)
{
    uint32_t now;

    if (!st)
        return 0;
    /* §28: feed tip-arrival cadence every admit tick (not just on miss) so
     * the gap1 Case A/B split has a real cadence to judge freshness by. */
    np_tip_track_advance(st->highest_remote_wire);

    /* Rematch dig0 sync: hold only the first step past dig0 (sim==1) until
     * both peers published tick-0 digests. Gate latches open; do not re-arm
     * for sim<48 after HC drops dig0 (soak: hung at sim=25 post-replay). */
    if (sim == 1u && !psx_netplay_rb_active() &&
        psx_netplay_rb_boot_dig0_gate()) {
        if (!g_boot_dig0_logged) {
            g_boot_dig0_logged = 1;
            fprintf(stderr,
                    "psxrecomp: rb boot dig0 wait sim=%u wire=%u "
                    "remote_tip=%u (hold until peer dig0)\n",
                    (unsigned)sim, (unsigned)wire,
                    (unsigned)st->highest_remote_wire);
            fflush(stderr);
        }
        np_sched_set_admit_stall("boot_dig0_wait");
        np_cross_os_maybe_log(sched_mono_ms(), sim, st);
        return 1;
    }

    /* Phase alignment: the ahead peer paces down a few ms/tick so remote
     * rows arrive before the seal (kills invent-mispredict episodes at the
     * source). Never engages during episodes/lockstep — only live admits. */
    if (!psx_netplay_rb_active() && np_timesync_throttle(wire)) {
        np_sched_set_admit_stall("timesync_pace");
        np_cross_os_maybe_log(sched_mono_ms(), sim, st);
        return 1;
    }

    now = sched_mono_ms();
    np_timesync_sample_lead(st->remote_lead);
    np_admit_log_runway(now, sim, wire, st->highest_remote_wire,
                        st->remote_lead);
    np_phase_ctrl_maybe_log(now, sim, st->remote_lead);
    np_cross_os_maybe_log(now, sim, st);
    np_auto_delay_tick(now);
    np_scorecard_sample(now, sim, wire, st);

    /* Rebuild D cushion after episode: do not invent until the remote tip
     * is nearly back at a full cushion (remote_lead >= D-1; §44: lead is
     * measured against sim, healthy steady state ≈ D). Both peers wait for
     * real inputs instead of racing the frontier with hold-last.
     * §45: do NOT clear on an absurd lead (tip-hold park / ring-age cliff).
     * Soak cleared at lead=280 then invented RUNWAY_EMPTY across a gap the
     * 128-entry wire ring had already dropped. Only a near-cushion lead
     * counts as rebuilt. */
    if (g_cushion_rebuild && !psx_netplay_rb_active()) {
        int d = sched_delay();
        int pred = g_sb.input_prediction ? *g_sb.input_prediction : 0;
        int full = d > 0 ? d : 0;
        int achievable;
        int max_ok = d + (pred > 0 ? pred : 4);
        if (max_ok < full + 2)
            max_ok = full + 2;
        /* §56: FULL cushion (lead >= D) clears immediately.
         * §57: the physical steady-state ceiling is lead ≈ D−1−transit, so
         * demanding D−1 on a WAN link just parked the rebuild against the
         * timeout (soak: held=12665ms). Clear at the ACHIEVABLE lead for the
         * measured transit, after a short hold so the rebuild really settles
         * there rather than clipping through it. */
        achievable = d - 1;
        if (g_transit_have) {
            achievable = d - 1 - (int)((g_transit_x16 + 8u) / 16u);
            if (achievable < 1)
                achievable = 1;
            if (achievable > d - 1)
                achievable = d - 1;
        }
        if (st->remote_lead >= full && st->remote_lead <= max_ok) {
            g_cushion_rebuild = 0;
            g_absurd_catchup_until_ms = 0u;
            fprintf(stderr,
                    "psxrecomp: rb cushion rebuilt FULL remote_lead=%d D=%d\n",
                    st->remote_lead, d);
            fflush(stderr);
        } else if (st->remote_lead >= achievable && st->remote_lead <= max_ok) {
            uint32_t held = g_cushion_rebuild_since_ms
                                ? (uint32_t)(now - g_cushion_rebuild_since_ms)
                                : 0u;
            if (held >= 400u) {
                g_cushion_rebuild = 0;
                g_absurd_catchup_until_ms = 0u;
                fprintf(stderr,
                        "psxrecomp: rb cushion rebuilt ACH remote_lead=%d "
                        "achievable=%d D=%d transit_est=%.2f held=%ums\n",
                        st->remote_lead, achievable, d,
                        g_transit_have ? (double)g_transit_x16 / 16.0 : 0.0,
                        (unsigned)held);
                fflush(stderr);
            }
        } else if (st->remote_lead > max_ok) {
            static uint32_t s_last_absurd_ms;
            uint32_t now_a = sched_mono_ms();
            if (absurd_invent_catchup_active(now_a)) {
                if (s_last_absurd_ms == 0u ||
                    (uint32_t)(now_a - s_last_absurd_ms) >= 1000u) {
                    s_last_absurd_ms = now_a ? now_a : 1u;
                    fprintf(stderr,
                            "psxrecomp: rb cushion CATCHUP (absurd lead=%d > %d "
                            "— invent allowed until catchup expires)\n",
                            st->remote_lead, max_ok);
                    fflush(stderr);
                }
            } else if (s_last_absurd_ms == 0u ||
                       (uint32_t)(now_a - s_last_absurd_ms) >= 1000u) {
                s_last_absurd_ms = now_a ? now_a : 1u;
                fprintf(stderr,
                        "psxrecomp: rb cushion KEEP (absurd lead=%d > %d — "
                        "not a rebuilt cushion; refuse invent)\n",
                        st->remote_lead, max_ok);
                fflush(stderr);
            }
        }
    }
    return 0;
}

int np_sched_on_remote_miss(int slot, uint32_t sim, uint32_t wire,
                            const RNetSessionStats *st, int pred,
                            const char **reason_out)
{
    const char *invent_reason = NULL;
    static int s_gap1_legacy = -1; /* PSX_RB_GAP1_INVENT=1 → old path */
    static rnet_u32 s_miss_wire;
    static uint32_t s_miss_t0;
    uint32_t now_miss;
    uint32_t tip_stale_ms;
    rnet_u32 gap;

    if (reason_out)
        *reason_out = NULL;
    if (!st)
        return 1;

    np_scorecard_note_miss(wire);

    /* FMV media + post-FMV settle: wait for remote wire (skip / title
     * Start). Invent idle opened tip episodes that hung. Tip-ahead with a
     * missing consumption wire is a ring hole — log before stalling. */
    if (psx_netplay_rb_lockstep_no_invent()) {
        /* §94: DESYNC invent-hold is not settle — mis-tag hid the real gate. */
        const char *why = psx_netplay_rb_fmv_media_active() ? "fmv_media"
                          : (psx_netplay_rb_fmv_desync_hold() ? "fmv_desync_hold"
                                                             : "fmv_settle");
        if (st->highest_remote_wire > wire)
            np_diag_wire_hole(slot, sim, wire, st, why);
        else
            np_sched_set_admit_stall(why);
        if (reason_out)
            *reason_out = why;
        return 1;
    }
    /* Rematch / asymmetric dig0: faster peer finishes tick-0 CRC and reaches
     * the first missing wire while the slower peer is still in present dig
     * (no tip publishes). Inventing here races into pcap_freeze then 1.5s
     * silence-disconnect. Wait until peer tip advances past the delay-prefix
     * production tip (sim0 tip == D) before inventing. */
    {
        int d = sched_delay();
        if (d < 2)
            d = 2;
        if (st->highest_remote_wire <= (rnet_u32)d) {
            if (!g_boot_tip_logged) {
                g_boot_tip_logged = 1;
                fprintf(stderr,
                        "psxrecomp: rb boot tip wait sim=%u wire=%u "
                        "remote_tip=%u D=%d (no invent until peer past "
                        "delay-prefix — rematch dig asymmetry)\n",
                        (unsigned)sim, (unsigned)wire,
                        (unsigned)st->highest_remote_wire, d);
                fflush(stderr);
            }
            np_sched_set_admit_stall("boot_tip_wait");
            if (reason_out)
                *reason_out = "boot_tip_wait";
            return 1;
        }
    }
    /* Stall when invent would run more than P ahead of remote tip (freeze +
     * refill; adaptive delay may bump D on sustained freeze enters — §22). */
    if (wire > st->highest_remote_wire + (rnet_u32)pred) {
        np_pcap_freeze_enter(wire, st->highest_remote_wire, pred);
        np_sched_set_admit_stall("pcap_freeze");
        if (reason_out)
            *reason_out = "pcap_freeze";
        return 1;
    }
    /* Cushion rebuild: wait for real remote rows (no invent) — unless §83 C
     * absurd catchup is armed after a baseline-abort Live realign. */
    if (g_cushion_rebuild && !psx_netplay_rb_active()) {
        int d = sched_delay();
        int pred = g_sb.input_prediction ? *g_sb.input_prediction : 0;
        int max_ok = d + (pred > 0 ? pred : 4);
        uint32_t now_c = sched_mono_ms();
        if (max_ok < d + 2)
            max_ok = d + 2;
        if (absurd_invent_catchup_active(now_c) && st->remote_lead > max_ok) {
            /* Fall through to invent path — catch up the realign cliff. */
            np_sched_set_admit_stall("absurd_catchup");
        } else {
            if (st->highest_remote_wire > wire)
                np_diag_wire_hole(slot, sim, wire, st, "cushion_rebuild");
            else
                np_sched_set_admit_stall("cushion_rebuild");
            if (reason_out)
                *reason_out = "cushion_rebuild";
            return 1;
        }
    }

    if (s_gap1_legacy < 0) {
        const char *e = getenv("PSX_RB_GAP1_INVENT");
        /* §26: default ON — short gap1 grace then invent (rollback).
         * Cushion-wait-until-TIP_STALE while remote_lead>0 was the WAN
         * 30fps delay-sync path; ENV=0 restores that. */
        if (e && e[0])
            s_gap1_legacy = (atoi(e) != 0) ? 1 : 0;
        else
            s_gap1_legacy = 1;
        fprintf(stderr,
                "psxrecomp: rb gap1 invent %s "
                "(short grace then invent while remote_lead healthy%s)\n",
                s_gap1_legacy ? "ON" : "OFF",
                s_gap1_legacy ? "" : "; PSX_RB_GAP1_INVENT=0");
        fflush(stderr);
    }

    gap = (wire > st->highest_remote_wire)
              ? (wire - st->highest_remote_wire)
              : 0u;
    now_miss = sched_mono_ms();
    if (s_miss_wire != wire) {
        s_miss_wire = wire;
        s_miss_t0 = now_miss;
    }

    /* Default: invent is last resort. While remote_lead > 0 the confirmed
     * tip is still ahead of sim — keep consuming wait, not prediction.
     * Ideal LAN: lead≈D, pred_depth=0, never invent. Safety: if the tip
     * stalls too long, invent as TIP_STALE. */
    if (!s_gap1_legacy && st->remote_lead > 0) {
        tip_stale_ms = np_invent_rtt_ms(NULL) * 4u;
        if (tip_stale_ms < 150u)
            tip_stale_ms = 150u;
        if (tip_stale_ms > 400u)
            tip_stale_ms = 400u;
        if ((uint32_t)(now_miss - s_miss_t0) < tip_stale_ms) {
            static rnet_u32 s_cw_wire;
            if (s_cw_wire != wire) {
                s_cw_wire = wire;
                g_admit_cushion_wait++;
            }
            /* gap=1: still count as grace-wait for telemetry. */
            if (gap == 1u) {
                static rnet_u32 s_gap1_counted_wire;
                if (s_gap1_counted_wire != wire) {
                    s_gap1_counted_wire = wire;
                    g_admit_gap1_grace++;
                    np_admit_maybe_log_stats(now_miss);
                }
            }
            if (st->highest_remote_wire > wire)
                np_diag_wire_hole(slot, sim, wire, st, "tip_stale_wait");
            else
                np_sched_set_admit_stall("tip_stale_wait");
            if (reason_out)
                *reason_out = "tip_stale_wait";
            return 1;
        }
        invent_reason = "TIP_STALE";
        g_admit_invent_tip_stale++;
    } else if (s_gap1_legacy && gap == 1u) {
        /* §29: §28's per-miss Case A wait was reverted — soak data showed
         * remote_lead sitting at a rock-stable D-1 the whole match under
         * ZERO-DELAY consumption, the signature of the missing cushion
         * (§44), not a wait-it-out jitter blip. gap=1 invents immediately
         * (classified GAP1_PHASE/GAP1_LEGACY for diagnostics) except for
         * the §43 LAN micro-grace below. PSX_RB_GAP1_GRACE_MS still forces
         * the old flat-cap wait for A/B testing. */
        int has_override = 0;
        uint32_t gap1_cap = np_gap1_grace_cap_ms(&has_override);
        int case_a = 0;

        if (!has_override) {
            uint32_t tip_age = np_tip_age_ms();
            uint32_t period =
                g_tip_arrival_ema_ms ? g_tip_arrival_ema_ms : 17u;

            case_a = (st->remote_lead >= 1) &&
                     (tip_age != 0xffffffffu) &&
                     (tip_age * 2u < period * RB_TIP_FRESH_MULT_X2);
            if (case_a)
                g_admit_gap1_case_a++;
            else
                g_admit_gap1_case_b++;
            gap1_cap = 0u; /* §29 default: no wait — classify only */
            /* §43/§105/§107: micro-grace for gap=1 tip invent (lead typically
             * -1). Session-149: invents were 100% remote_lead=-1 / case_b —
             * the §104 "healthy lead ≥ D-1" arm never fired. §105 waited
             * only when RTT≤LAN gate or tip-due — SFU soaks (rtt~75) skipped
             * grace and invented every tick. §107: always wait
             * min(½RTT+base, lan_cap|relay_cap) outside FMV; tip_due still
             * uses the short LAN cap so a due tip does not stall a full
             * relay budget. Expiry still invents. */
            if (!psx_netplay_rb_fmv_media_active()) {
                uint32_t rtt_raw = 0u;
                int lan;
                int tip_due;
                uint32_t cap;
                (void)np_invent_rtt_ms(&rtt_raw);
                lan = (rtt_raw <= RB_GAP1_LAN_RTT_MAX_MS);
                tip_due = (tip_age != 0xffffffffu &&
                           tip_age + RB_GAP1_LAN_GRACE_CAP_MS >= period);
                /* Prefer trusted POST sample; synth/zero still get base. */
                gap1_cap = rtt_raw / 2u + RB_GAP1_LAN_GRACE_BASE_MS;
                if (lan || tip_due)
                    cap = RB_GAP1_LAN_GRACE_CAP_MS;
                else
                    cap = RB_GAP1_RELAY_GRACE_CAP_MS;
                if (gap1_cap > cap)
                    gap1_cap = cap;
                if (gap1_cap < RB_GAP1_LAN_GRACE_BASE_MS)
                    gap1_cap = RB_GAP1_LAN_GRACE_BASE_MS;
            }
            /* §98: during FMV media invent immediately (no micro-grace). */
        }
        if (gap1_cap != 0u) {
            if (np_invent_grace_stall_ex(slot, wire, gap1_cap, 0)) {
                static rnet_u32 s_gap1_counted_wire;
                if (s_gap1_counted_wire != wire) {
                    s_gap1_counted_wire = wire;
                    g_admit_gap1_grace++;
                    np_admit_maybe_log_stats(sched_mono_ms());
                }
                np_sched_set_admit_stall("gap1_grace");
                if (reason_out)
                    *reason_out = "gap1_grace";
                return 1;
            }
            np_gap1_note_expire_invent();
        }
        invent_reason = case_a ? "GAP1_PHASE" : "GAP1_LEGACY";
        g_admit_invent_gap1_legacy++;
    } else {
        /* §27 shallow invent: pred_depth≥2 only after tip looks stale
         * (1× invent RTT, floor 40ms). Avoids burning deep into P every
         * tick (constant deep resim). Then short grace. */
        uint32_t pred_depth = gap;
        tip_stale_ms = np_invent_rtt_ms(NULL);
        if (tip_stale_ms < RB_INVENT_DEPTH_STALE_FLOOR_MS)
            tip_stale_ms = RB_INVENT_DEPTH_STALE_FLOOR_MS;
        if (pred_depth >= 2u &&
            (uint32_t)(now_miss - s_miss_t0) < tip_stale_ms) {
            np_sched_set_admit_stall("depth_stale_wait");
            if (reason_out)
                *reason_out = "depth_stale_wait";
            return 1;
        }
        if (np_invent_grace_stall_ex(slot, wire,
                                     RB_INVENT_RUNWAY_GRACE_CAP_MS, 1)) {
            if (st->highest_remote_wire > wire)
                np_diag_wire_hole(slot, sim, wire, st, "runway_grace");
            else
                np_sched_set_admit_stall("runway_grace");
            if (reason_out)
                *reason_out = "runway_grace";
            return 1;
        }
        invent_reason = "RUNWAY_EMPTY";
        g_admit_invent_runway_empty++;
    }

    np_admit_note_invent_gap(wire, st->highest_remote_wire);
    np_admit_log_invent(sim, wire, st->highest_remote_wire,
                        st->remote_lead, invent_reason);
    /* §105: invent is not arrival lateness — drop controller miss sample. */
    np_auto_delay_undo_invent_miss();
    if (reason_out)
        *reason_out = invent_reason;
    np_sched_clear_admit_stall(); /* inventing — not a barrier stall */
    return 0;
}

void np_sched_post_admit(int any_invent)
{
    RNetSession *s;
    RNetSessionStats st;
    uint32_t now;

    np_sched_clear_admit_stall();
    /* Remote caught up or we invented inside P — leave freeze if armed. */
    np_pcap_freeze_exit();
    now = sched_mono_ms();
    if (any_invent)
        np_admit_maybe_log_stats(now);
    s = sched_session();
    if (s) {
        memset(&st, 0, sizeof(st));
        rnet_session_get_stats(s, &st);
        np_cross_os_maybe_log(now, st.sim_tick, &st);
    }
}

void np_sched_reset_session(void)
{
    /* Invent / cushion / tip cadence from the prior match must not gate the
     * next soft-return rematch (lockstep armed → no frames). */
    g_boot_tip_logged = 0;
    g_boot_dig0_logged = 0;
    g_cushion_rebuild = 0;
    g_cushion_rebuild_since_ms = 0u;
    g_absurd_catchup_until_ms = 0u;

    g_ad_ticks = 0u;
    g_ad_lead_sum = 0;
    g_ad_miss = 0u;
    g_ad_late_n = 0u;
    g_ad_late_sum_ms = 0u;
    g_ad_late_max_ms = 0u;
    g_ad_miss_pending = 0;
    g_ad_miss_t0_ms = 0u;
    g_transit_x16 = 0u;
    g_transit_have = 0;

    g_gap1_shrink_until_ms = 0u;
    g_gap1_expire_invent_streak = 0u;

    g_tip_last_highest = 0u;
    g_tip_last_advance_ms = 0u;
    g_tip_arrival_ema_ms = 0u;
    g_tip_have_advance = 0;

    /* Keep g_ts_enabled / g_adapt_delay_enabled latched (−1 = unread). */
    g_ts_tick_ema_ms = 0u;
    g_ts_debt_ms = 0u;
    g_ts_pegged_streak = 0u;
    g_ts_off_until_ms = 0u;
    g_ts_mispredict_count = 0u;
    g_ts_mispredict_age_sum = 0ull;
    g_ts_mispredict_age_max = 0u;
    g_ts_note_late_applied = 0u;
    g_ts_note_late_suppressed_rb = 0u;
    g_ts_note_late_suppressed_off = 0u;
    g_ts_debt_added_ms = 0u;
    g_ts_lead_sum = 0;
    g_ts_lead_n = 0u;
    g_ts_lead_min = 0;
    g_ts_lead_max = 0;
    g_ts_lead_have = 0;
    g_ts_last_wire = 0u;
    g_ts_last_wire_ms = 0u;
    g_ts_stall_until = 0u;
    g_ts_stall_logged = 0;

    g_admit_invent_gap1 = 0u;
    g_admit_invent_gap2 = 0u;
    g_admit_invent_gap3p = 0u;
    g_admit_gap1_grace = 0u;
    g_admit_pcap_stalls = 0u;
    g_admit_pcap_enters = 0u;
    g_pcap_frozen = 0;
    g_pcap_freeze_enters_window = 0u;
    g_pcap_window_t0_ms = 0u;
    g_pcap_last_enter_ms = 0u;
    g_adapt_last_bump_ms = 0u;
    g_admit_stats_last_log_ms = 0u;
    g_admit_invent_runway_empty = 0u;
    g_admit_invent_tip_stale = 0u;
    g_admit_invent_gap1_legacy = 0u;
    g_admit_cushion_wait = 0u;
    g_admit_gap1_case_a = 0u;
    g_admit_gap1_case_b = 0u;

    g_sc_window_t0_ms = 0u;
    g_sc_ep0 = 0u;
    g_sc_rt0 = 0ull;
    g_sc_gap1_0 = 0u;
    g_sc_tip_stale0 = 0u;
    g_sc_lead_sum = 0;
    g_sc_lead_n = 0u;
    g_sc_lead_min = 0;
    g_sc_lead_max = 0;
    g_sc_slack_sum = 0ull;
    g_sc_slack_n = 0u;
    g_sc_slack_min = 0u;
    g_sc_slack_max = 0u;
    g_sc_miss_at_need = 0u;

    g_admit_stall_tag[0] = '\0';
}

#endif /* PSX_HAS_RECOMP_NET */
