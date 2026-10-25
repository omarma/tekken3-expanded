#include "cpu_state.h"
#include "gte.h"
#include "gte_precision_interp.h"

#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>

using PSXRecomp::GTE::GTEState;
using PSXRecomp::GTE::gte_cfc2;
using PSXRecomp::GTE::gte_ctc2;
using PSXRecomp::GTE::gte_mfc2;
using PSXRecomp::GTE::gte_mtc2;

extern "C" void gte_canonicalize_cpu_state(CPUState *cpu);
extern "C" void gte_test_set_precise_valid_mask(uint32_t mask);
extern "C" uint32_t gte_test_get_precise_valid_mask(void);
extern "C" void gte_test_set_timeline_generations(uint32_t precision,
                                                   uint32_t geometry);
extern "C" uint32_t gte_test_get_precision_generation(void);
extern "C" uint32_t gte_test_get_geometry_generation(void);
extern "C" void gte_precision_tracking_set(int enabled);
extern "C" void gte_precision_invalidate_word(uint32_t addr);
extern "C" void gte_precision_invalidate_store(uint32_t addr, uint32_t size);
extern "C" void gte_precision_store_word(uint32_t addr, uint8_t reg);
extern "C" void gte_precision_lwc2_word(uint32_t addr, uint8_t reg,
                                        uint32_t value, uint32_t pc);
extern "C" void gte_precision_timeline_invalidate(void);
extern "C" void gte_precision_speculative_begin(void);
extern "C" void gte_precision_speculative_end(void);
extern "C" int gte_precision_load_word(uint32_t addr, uint32_t packed,
                                        int32_t *x16, int32_t *y16,
                                        uint16_t *z, uint8_t *derived);
extern "C" void gte_precision_cpu_lw(uint8_t rt, uint32_t addr);
extern "C" void gte_precision_cpu_sw(uint32_t addr, uint8_t rt, uint32_t value);
extern "C" void gte_precision_cpu_add(uint8_t rd, uint8_t rs, uint8_t rt,
                                      uint32_t vs, uint32_t vt);
extern "C" void gte_precision_cpu_sra(uint8_t rd, uint8_t rt, uint8_t sa,
                                      uint32_t vt);
extern "C" void gte_precision_cpu_and(uint8_t rd, uint8_t rs, uint8_t rt,
                                      uint32_t vs, uint32_t vt);
extern "C" void gte_precision_cpu_or(uint8_t rd, uint8_t rs, uint8_t rt,
                                     uint32_t vs, uint32_t vt);
extern "C" void gte_precision_cpu_drop(uint8_t rd);
extern "C" uint8_t gte_test_get_precise_derived(uint32_t index);
extern "C" int gte_precision_native_active(void);
extern "C" void gte_precision_native_word(uint32_t addr, uint32_t packed,
                                          int32_t x16, int32_t y16, uint16_t z);
extern "C" void gte_geometry_correction_set(int enabled);
extern "C" void gte_geometry_position_fallback_set(int enabled);
extern "C" int gte_geometry_correction_lookup(uint32_t packed,
                                                int32_t *x16, int32_t *y16);
extern "C" void gte_test_seed_precise_projection(uint32_t index,
                                                   uint32_t packed,
                                                   int32_t x16,
                                                   int32_t y16,
                                                   uint16_t z);
extern "C" void gte_test_get_precise_projection(uint32_t index,
                                                  uint32_t *packed,
                                                  int32_t *x16,
                                                  int32_t *y16,
                                                  uint16_t *z,
                                                  uint8_t *valid);
extern "C" void gte_test_seed_geometry(uint32_t packed, int32_t x16,
                                        int32_t y16);
extern "C" void gte_test_execute_reference(CPUState *cpu, uint32_t cmd);
extern "C" void gte_ws_set_nclip_gpu_coords(int on);

/* gte.cpp runtime dependencies that are irrelevant to register-transfer tests. */
extern "C" int gpu_ws_present_native_43(void) { return 0; }
static int g_test_native_wide = 0;
extern "C" int ws_native_wide_active(void) { return g_test_native_wide; }
extern "C" void psx_ws_note_gte_project(int) {}
extern "C" {
uint64_t s_frame_count = 0;
uint32_t g_debug_last_store_pc = 0;   /* census attribution (debug_server.c) */
}

uint64_t g_test_cycle = 0;
uint32_t g_test_gte_set_calls = 0;
uint32_t g_test_gte_last_latency = 0;

extern "C" uint32_t psx_gte_cmd_latency(uint32_t cmd) {
    return 7u + (cmd & 0x3Fu);
}

extern "C" void psx_gte_set(CPUState *cpu, uint32_t latency) {
    ++g_test_gte_set_calls;
    g_test_gte_last_latency = latency;
    if (cpu->gte_ts_done > g_test_cycle) g_test_cycle = cpu->gte_ts_done;
    cpu->gte_ts_done = g_test_cycle + latency;
}

namespace {

struct PreciseState {
    uint32_t packed;
    int32_t x16;
    int32_t y16;
    uint16_t z;
    uint8_t valid;
};

std::array<PreciseState, 4> precise_snapshot() {
    std::array<PreciseState, 4> result{};
    for (uint32_t i = 0; i < result.size(); ++i) {
        auto &p = result[i];
        gte_test_get_precise_projection(i, &p.packed, &p.x16, &p.y16,
                                        &p.z, &p.valid);
    }
    return result;
}

void seed_precise_snapshot() {
    for (uint32_t i = 0; i < 4; ++i)
        gte_test_seed_precise_projection(i, 0x01010001u * (i + 1u),
                                         0x10000 + static_cast<int32_t>(i * 31),
                                         -0x20000 - static_cast<int32_t>(i * 47),
                                         static_cast<uint16_t>(0x100u + i));
}

bool same_precise(const std::array<PreciseState, 4> &lhs,
                  const std::array<PreciseState, 4> &rhs) {
    for (uint32_t i = 0; i < lhs.size(); ++i) {
        if (lhs[i].packed != rhs[i].packed || lhs[i].x16 != rhs[i].x16 ||
            lhs[i].y16 != rhs[i].y16 || lhs[i].z != rhs[i].z ||
            lhs[i].valid != rhs[i].valid)
            return false;
    }
    return true;
}

constexpr std::array<uint32_t, 10> kEdgeValues = {
    0x00000000u, 0x00000001u, 0x00007FFFu, 0x00008000u, 0x0000FFFFu,
    0x00010000u, 0x7FFFFFFFu, 0x80000000u, 0xFFFFFFFEu, 0xFFFFFFFFu,
};

constexpr std::array<uint8_t, 6> kInvalidRegs = {32u, 33u, 63u, 64u, 127u, 255u};

uint64_t g_rng = 0xD1B54A32D192ED03ull;

uint32_t random_u32() {
    g_rng ^= g_rng >> 12;
    g_rng ^= g_rng << 25;
    g_rng ^= g_rng >> 27;
    return static_cast<uint32_t>((g_rng * 0x2545F4914F6CDD1Dull) >> 16);
}

void randomize_gte(CPUState &cpu) {
    std::memset(&cpu, 0, sizeof(cpu));
    for (uint32_t &value : cpu.gte_data) value = random_u32();
    for (uint32_t &value : cpu.gte_ctrl) value = random_u32();
}

void oracle_load(GTEState &gte, const CPUState &cpu) {
    for (uint8_t reg = 0; reg < 32; ++reg) {
        if (reg == 15 || reg == 28) continue;
        gte_mtc2(&gte, reg, cpu.gte_data[reg]);
    }
    for (uint8_t reg = 0; reg < 32; ++reg)
        gte_ctc2(&gte, reg, cpu.gte_ctrl[reg]);
    /* Importing emulator state is not a guest CTC2 write. Preserve a computed
     * FLAG error bit and any existing backing bits exactly like gte_load_data. */
    gte.FLAG = cpu.gte_ctrl[31];
}

void oracle_export(CPUState &cpu, GTEState &gte) {
    for (uint8_t reg = 0; reg < 32; ++reg)
        cpu.gte_data[reg] = gte_mfc2(&gte, reg);
    for (uint8_t reg = 0; reg < 32; ++reg)
        cpu.gte_ctrl[reg] = gte_cfc2(&gte, reg);
}

void oracle_canonicalize(CPUState &cpu) {
    GTEState gte;
    oracle_load(gte, cpu);
    oracle_export(cpu, gte);
}

uint32_t oracle_read_data(const CPUState &cpu, uint8_t reg) {
    GTEState gte;
    oracle_load(gte, cpu);
    return gte_mfc2(&gte, reg);
}

uint32_t oracle_read_ctrl(const CPUState &cpu, uint8_t reg) {
    GTEState gte;
    oracle_load(gte, cpu);
    return gte_cfc2(&gte, reg);
}

void oracle_write_data(CPUState &cpu, uint8_t reg, uint32_t value) {
    GTEState gte;
    oracle_load(gte, cpu);
    gte_mtc2(&gte, reg, value);
    oracle_export(cpu, gte);
}

void oracle_write_ctrl(CPUState &cpu, uint8_t reg, uint32_t value) {
    GTEState gte;
    oracle_load(gte, cpu);
    gte_ctc2(&gte, reg, value);
    oracle_export(cpu, gte);
}

bool same_gte(const CPUState &lhs, const CPUState &rhs) {
    return std::memcmp(lhs.gte_data, rhs.gte_data, sizeof(lhs.gte_data)) == 0 &&
           std::memcmp(lhs.gte_ctrl, rhs.gte_ctrl, sizeof(lhs.gte_ctrl)) == 0;
}

int fail_value(const char *phase, unsigned iteration, unsigned reg,
               uint32_t value, uint32_t expected, uint32_t actual) {
    std::fprintf(stderr,
                 "FAIL: %s iter=%u reg=%u value=%08X expected=%08X actual=%08X\n",
                 phase, iteration, reg, value, expected, actual);
    return 1;
}

int fail_state(const char *phase, unsigned iteration, unsigned reg, uint32_t value,
               const CPUState &expected, const CPUState &actual) {
    for (unsigned i = 0; i < 32; ++i) {
        if (expected.gte_data[i] != actual.gte_data[i]) {
            std::fprintf(stderr,
                         "FAIL: %s iter=%u source_reg=%u value=%08X data=%u "
                         "expected=%08X actual=%08X\n",
                         phase, iteration, reg, value, i, expected.gte_data[i],
                         actual.gte_data[i]);
            return 1;
        }
    }
    for (unsigned i = 0; i < 32; ++i) {
        if (expected.gte_ctrl[i] != actual.gte_ctrl[i]) {
            std::fprintf(stderr,
                         "FAIL: %s iter=%u source_reg=%u value=%08X ctrl=%u "
                         "expected=%08X actual=%08X\n",
                         phase, iteration, reg, value, i, expected.gte_ctrl[i],
                         actual.gte_ctrl[i]);
            return 1;
        }
    }
    std::fprintf(stderr, "FAIL: %s reported unequal states without a differing word\n",
                 phase);
    return 1;
}

int check_all_reads(const CPUState &expected, CPUState &actual,
                    const char *phase, unsigned iteration) {
    for (uint8_t reg = 0; reg < 32; ++reg) {
        const uint32_t expected_data = oracle_read_data(expected, reg);
        const uint32_t actual_data = gte_read_data(&actual, reg);
        if (actual_data != expected_data)
            return fail_value(phase, iteration, reg, 0, expected_data, actual_data);

        const uint32_t expected_ctrl = oracle_read_ctrl(expected, reg);
        const uint32_t actual_ctrl = gte_read_ctrl(&actual, reg);
        if (actual_ctrl != expected_ctrl)
            return fail_value(phase, iteration, reg, 1, expected_ctrl, actual_ctrl);
    }
    return 0;
}

int test_canonicalizer() {
    for (unsigned iteration = 0; iteration < 512; ++iteration) {
        CPUState expected;
        randomize_gte(expected);
        CPUState actual = expected;
        oracle_canonicalize(expected);
        gte_canonicalize_cpu_state(&actual);
        if (!same_gte(expected, actual))
            return fail_state("canonicalize", iteration, 0, 0, expected, actual);
    }
    return 0;
}

int test_reads() {
    for (unsigned iteration = 0; iteration < 256; ++iteration) {
        CPUState state;
        randomize_gte(state);
        /* Deliberately use raw randomized backing here. Read helpers must match
         * the architectural value reconstructed by the old bridge even before
         * an explicit canonicalization boundary. */
        CPUState before = state;
        if (int rc = check_all_reads(state, state, "raw read", iteration)) return rc;
        if (!same_gte(before, state))
            return fail_state("read mutated state", iteration, 0, 0, before, state);

        for (uint8_t reg : kInvalidRegs) {
            const uint32_t actual_data = gte_read_data(&state, reg);
            const uint32_t actual_ctrl = gte_read_ctrl(&state, reg);
            if (actual_data != 0u)
                return fail_value("invalid data read", iteration, reg, 0, 0, actual_data);
            if (actual_ctrl != 0u)
                return fail_value("invalid ctrl read", iteration, reg, 0, 0, actual_ctrl);
        }
    }
    return 0;
}

int test_writes() {
    for (unsigned iteration = 0; iteration < 64; ++iteration) {
        CPUState seed;
        randomize_gte(seed);

        /* Valid helper writes must also normalize unrelated backing words.
         * This preserves the old bridge's behavior when falling back from
         * committed AOT C that predates helper routing for masked registers. */
        for (uint8_t reg = 0; reg < 32; ++reg) {
            for (uint32_t edge : kEdgeValues) {
                const uint32_t value = edge ^ (iteration ? random_u32() : 0u);

                CPUState expected = seed;
                CPUState actual = seed;
                oracle_write_data(expected, reg, value);
                gte_write_data(&actual, reg, value);
                if (!same_gte(expected, actual))
                    return fail_state("data write", iteration, reg, value,
                                      expected, actual);

                expected = seed;
                actual = seed;
                oracle_write_ctrl(expected, reg, value);
                gte_write_ctrl(&actual, reg, value);
                if (!same_gte(expected, actual))
                    return fail_state("ctrl write", iteration, reg, value,
                                      expected, actual);
            }
        }

        CPUState canonical_seed = seed;
        oracle_canonicalize(canonical_seed);
        for (uint8_t reg : kInvalidRegs) {
            CPUState expected = canonical_seed;
            CPUState actual = canonical_seed;
            const uint32_t value = random_u32();
            oracle_write_data(expected, reg, value);
            gte_write_data(&actual, reg, value);
            if (!same_gte(expected, actual))
                return fail_state("invalid data write", iteration, reg, value,
                                  expected, actual);

            expected = canonical_seed;
            actual = canonical_seed;
            oracle_write_ctrl(expected, reg, value);
            gte_write_ctrl(&actual, reg, value);
            if (!same_gte(expected, actual))
                return fail_state("invalid ctrl write", iteration, reg, value,
                                  expected, actual);
        }
    }

    return 0;
}

int test_sequence_fuzz() {
    for (unsigned iteration = 0; iteration < 128; ++iteration) {
        CPUState expected;
        randomize_gte(expected);
        oracle_canonicalize(expected);
        CPUState actual = expected;

        for (unsigned step = 0; step < 512; ++step) {
            const uint32_t selector = random_u32();
            const uint8_t reg = (selector & 7u) == 0u
                                    ? kInvalidRegs[selector % kInvalidRegs.size()]
                                    : static_cast<uint8_t>((selector >> 8) & 31u);
            const uint32_t value = random_u32();
            switch ((selector >> 16) & 3u) {
            case 0: {
                const uint32_t want = oracle_read_data(expected, reg);
                const uint32_t got = gte_read_data(&actual, reg);
                if (want != got)
                    return fail_value("sequence data read", iteration, reg, value,
                                      want, got);
                break;
            }
            case 1: {
                const uint32_t want = oracle_read_ctrl(expected, reg);
                const uint32_t got = gte_read_ctrl(&actual, reg);
                if (want != got)
                    return fail_value("sequence ctrl read", iteration, reg, value,
                                      want, got);
                break;
            }
            case 2:
                oracle_write_data(expected, reg, value);
                gte_write_data(&actual, reg, value);
                break;
            case 3:
                oracle_write_ctrl(expected, reg, value);
                gte_write_ctrl(&actual, reg, value);
                break;
            }
            if (!same_gte(expected, actual))
                return fail_state("sequence state", iteration, reg, value,
                                  expected, actual);
        }
    }
    return 0;
}

int test_command_marshaling() {
    constexpr std::array<uint8_t, 22> kFunctions = {
        0x01, 0x06, 0x0C, 0x10, 0x11, 0x12, 0x13, 0x14,
        0x16, 0x1B, 0x1C, 0x1E, 0x20, 0x28, 0x29, 0x2A,
        0x2D, 0x2E, 0x30, 0x3D, 0x3E, 0x3F,
    };

    for (uint8_t function : kFunctions) {
        for (unsigned iteration = 0; iteration < 96; ++iteration) {
            CPUState seed;
            randomize_gte(seed);  // deliberately raw/noncanonical legacy state
            CPUState expected = seed;
            CPUState actual = seed;
            const uint32_t cmd = (random_u32() & ~0x3Fu) | function;
            gte_test_execute_reference(&expected, cmd);
            gte_execute(&actual, cmd);
            if (!same_gte(expected, actual))
                return fail_state("command marshal", iteration, function, cmd,
                                  expected, actual);
            if (actual.gte_data[15] != actual.gte_data[14] ||
                actual.gte_data[23] != 0u ||
                actual.gte_data[28] != actual.gte_data[29] ||
                actual.gte_data[31] != gte_read_data(&actual, 31))
                return fail_value("command canonical aliases", iteration,
                                  function, cmd, actual.gte_data[14],
                                  actual.gte_data[15]);
        }
    }

    /* MVMVA's matrix/vector/translation dependencies are all selected by the
     * command word. Exhaust every selector plus sf/lm combination explicitly. */
    for (uint32_t mx = 0; mx < 4; ++mx) {
        for (uint32_t vv = 0; vv < 4; ++vv) {
            for (uint32_t tv = 0; tv < 4; ++tv) {
                for (uint32_t sf = 0; sf < 2; ++sf) {
                    for (uint32_t lm = 0; lm < 2; ++lm) {
                        CPUState seed;
                        randomize_gte(seed);
                        CPUState expected = seed;
                        CPUState actual = seed;
                        const uint32_t cmd = 0x12u | (mx << 17) | (vv << 15) |
                                             (tv << 13) | (sf << 19) | (lm << 10);
                        gte_test_execute_reference(&expected, cmd);
                        gte_execute(&actual, cmd);
                        if (!same_gte(expected, actual))
                            return fail_state("MVMVA selectors", mx * 16u + vv * 4u + tv,
                                              static_cast<unsigned>(sf * 2u + lm),
                                              cmd, expected, actual);
                    }
                }
            }
        }
    }

    /* Stateful command streams catch FIFO/alias state that single-command
     * comparisons can accidentally reinitialize away. */
    for (unsigned iteration = 0; iteration < 64; ++iteration) {
        CPUState expected;
        randomize_gte(expected);
        CPUState actual = expected;
        for (unsigned step = 0; step < 128; ++step) {
            const uint8_t function = kFunctions[random_u32() % kFunctions.size()];
            const uint32_t cmd = (random_u32() & ~0x3Fu) | function;
            gte_test_execute_reference(&expected, cmd);
            gte_execute(&actual, cmd);
            if (!same_gte(expected, actual))
                return fail_state("command stream", iteration, function, cmd,
                                  expected, actual);
        }
    }

    /* Projection commands update a host-only precise-SXY FIFO. Reset that
     * global state around each path so the old and direct marshalers can be
     * compared independently instead of executing twice on one timeline. */
    for (uint8_t function : kFunctions) {
        CPUState seed;
        randomize_gte(seed);
        CPUState expected = seed;
        CPUState actual = seed;
        const uint32_t cmd = (random_u32() & ~0x3Fu) | function;
        seed_precise_snapshot();
        gte_test_execute_reference(&expected, cmd);
        const auto expected_precise = precise_snapshot();
        seed_precise_snapshot();
        gte_execute(&actual, cmd);
        const auto actual_precise = precise_snapshot();
        if (!same_precise(expected_precise, actual_precise))
            return fail_value("command precise provenance", 0, function,
                              cmd, 1u, 0u);
    }
    return 0;
}

int test_command_timing_hook() {
    CPUState cpu{};
    g_test_cycle = 100u;
    cpu.gte_ts_done = 175u;
    g_test_gte_set_calls = 0;
    g_test_gte_last_latency = 0;
    gte_execute(&cpu, 0x06u);
    if (g_test_gte_set_calls != 1u || g_test_gte_last_latency != 13u ||
        cpu.gte_ts_done != 188u)
        return fail_value("command timing serialization", 0, 0x06u, 0,
                          188u, static_cast<uint32_t>(cpu.gte_ts_done));
    gte_execute(&cpu, 0x30u);
    if (g_test_gte_set_calls != 2u || g_test_gte_last_latency != 55u ||
        cpu.gte_ts_done != 243u)
        return fail_value("back-to-back command timing", 0, 0x30u, 0,
                          243u, static_cast<uint32_t>(cpu.gte_ts_done));
    return 0;
}

int test_precise_sxy_invalidation() {
    CPUState cpu{};
    /* An SXY write drops the written register's projection only; SXYP pushes
     * the FIFO, so SXY0/SXY1 take SXY1/SXY2's (G1.11). */
    for (uint8_t reg = 0; reg < 32; ++reg) {
        gte_test_set_precise_valid_mask(0xFu);
        gte_write_data(&cpu, reg, 0x12345678u);
        const uint32_t expected = reg == 12 ? 0xEu : reg == 13 ? 0xDu :
                                  (reg == 14 || reg == 15) ? 0x3u : 0xFu;
        const uint32_t actual = gte_test_get_precise_valid_mask();
        if (actual != expected)
            return fail_value("precise SXY invalidation", 0, reg,
                              0x12345678u, expected, actual);
    }

    for (uint16_t wide_reg = 32; wide_reg <= 255; ++wide_reg) {
        const uint8_t reg = static_cast<uint8_t>(wide_reg);
        gte_test_set_precise_valid_mask(0xFu);
        gte_write_data(&cpu, reg, 0x87654321u);
        if (gte_test_get_precise_valid_mask() != 0xFu)
            return fail_value("invalid data preserves precise SXY", 0, reg,
                              0x87654321u, 0xFu,
                              gte_test_get_precise_valid_mask());
    }

    for (uint16_t wide_reg = 0; wide_reg <= 255; ++wide_reg) {
        const uint8_t reg = static_cast<uint8_t>(wide_reg);
        gte_test_set_precise_valid_mask(0xFu);
        gte_write_ctrl(&cpu, reg, 0xCAFEBABEu);
        if (gte_test_get_precise_valid_mask() != 0xFu)
            return fail_value("ctrl preserves precise SXY", 0, reg,
                              0xCAFEBABEu, 0xFu,
                              gte_test_get_precise_valid_mask());
    }

    gte_test_set_precise_valid_mask(0xFu);
    gte_test_set_timeline_generations(41u, 73u);
    gte_canonicalize_cpu_state(&cpu);
    if (gte_test_get_precise_valid_mask() != 0u)
        return fail_value("canonicalize invalidates precise SXY", 0, 0,
                          0, 0, gte_test_get_precise_valid_mask());
    if (gte_test_get_precision_generation() != 42u)
        return fail_value("canonicalize advances precision generation", 0, 0,
                          0, 42u, gte_test_get_precision_generation());
    if (gte_test_get_geometry_generation() != 74u)
        return fail_value("canonicalize advances geometry generation", 0, 0,
                          0, 74u, gte_test_get_geometry_generation());

    /* Generation zero is reserved. Wrapping must clear stale generations and
     * restart at one rather than resurrecting ancient generation-one entries. */
    gte_test_set_precise_valid_mask(0xFu);
    gte_test_set_timeline_generations(0xFFFFFFFFu, 0xFFFFFFFFu);
    gte_precision_timeline_invalidate();
    if (gte_test_get_precise_valid_mask() != 0u ||
        gte_test_get_precision_generation() != 1u ||
        gte_test_get_geometry_generation() != 1u)
        return fail_value("timeline generation wrap", 0, 0, 0, 1u,
                          gte_test_get_precision_generation());
    return 0;
}

int test_precision_speculative_transaction() {
    constexpr uint32_t address = 0x00123450u;
    constexpr uint32_t packed = 0x00420021u;
    constexpr int32_t x16 = 0x00123456;
    constexpr int32_t y16 = -0x00034567;
    constexpr uint16_t z = 0x4567u;

    gte_precision_tracking_set(1);
    gte_geometry_correction_set(1);
    gte_geometry_position_fallback_set(1);   /* the position cache (G1.11) */
    gte_test_set_timeline_generations(41u, 73u);
    gte_test_seed_precise_projection(2, packed, x16, y16, z);
    gte_precision_store_word(address, 14);
    gte_test_seed_geometry(packed, x16, y16);

    int32_t got_x = 0, got_y = 0;
    uint16_t got_z = 0;
    if (!gte_precision_load_word(address, packed, &got_x, &got_y, &got_z, nullptr) ||
        got_x != x16 || got_y != y16 || got_z != z)
        return fail_value("precision seed lookup", 0, 14, packed, z, got_z);
    if (!gte_geometry_correction_lookup(packed, &got_x, &got_y) ||
        got_x != x16 || got_y != y16)
        return fail_value("geometry seed lookup", 0, 0, packed,
                          static_cast<uint32_t>(x16), static_cast<uint32_t>(got_x));

    gte_precision_speculative_begin();
    gte_precision_speculative_begin();
    if (gte_precision_load_word(address, packed, &got_x, &got_y, &got_z, nullptr) != 0)
        return fail_value("speculative precision read", 0, 0, packed, 0, 1);
    if (gte_geometry_correction_lookup(packed, &got_x, &got_y) != 0)
        return fail_value("speculative geometry read", 0, 0, packed, 0, 1);
    gte_precision_invalidate_word(address);  // suppressed: must not age live entry
    CPUState cpu{};
    gte_write_data(&cpu, 14, 0xDEADBEEFu);  // mutates speculative SXY only
    gte_precision_speculative_end();
    if (gte_precision_load_word(address, packed, &got_x, &got_y, &got_z, nullptr) != 0)
        return fail_value("nested speculation remains isolated", 0, 0,
                          packed, 0, 1);
    gte_precision_speculative_end();

    if (gte_test_get_precise_valid_mask() != 0x4u)
        return fail_value("speculative SXY restore", 0, 0, 0, 0x4u,
                          gte_test_get_precise_valid_mask());
    if (!gte_precision_load_word(address, packed, &got_x, &got_y, &got_z, nullptr) ||
        got_x != x16 || got_y != y16 || got_z != z)
        return fail_value("authoritative precision survives", 0, 0, packed,
                          z, got_z);
    if (!gte_geometry_correction_lookup(packed, &got_x, &got_y) ||
        got_x != x16 || got_y != y16)
        return fail_value("authoritative geometry survives", 0, 0, packed,
                          static_cast<uint32_t>(x16), static_cast<uint32_t>(got_x));

    /* A raw savestate/import restore is authoritative even when host polling
     * reaches it during speculation. Defer its timeline invalidation until the
     * outer transaction closes, but never restore pre-load provenance. */
    gte_precision_speculative_begin();
    gte_precision_speculative_begin();
    gte_precision_timeline_invalidate();
    if (gte_test_get_precision_generation() != 41u ||
        gte_test_get_geometry_generation() != 73u)
        return fail_value("deferred timeline invalidation", 0, 0, 0, 41u,
                          gte_test_get_precision_generation());
    gte_precision_speculative_end();
    if (gte_test_get_precision_generation() != 41u)
        return fail_value("nested timeline remains deferred", 0, 0, 0, 41u,
                          gte_test_get_precision_generation());
    gte_precision_speculative_end();
    if (gte_test_get_precise_valid_mask() != 0u ||
        gte_test_get_precision_generation() != 42u ||
        gte_test_get_geometry_generation() != 74u ||
        gte_precision_load_word(address, packed, nullptr, nullptr, nullptr, nullptr) != 0 ||
        gte_geometry_correction_lookup(packed, nullptr, nullptr) != 0)
        return fail_value("authoritative restore invalidation", 0, 0, 0, 42u,
                          gte_test_get_precision_generation());

    /* Exercise each cache's wrap independently and prove stale entries miss,
     * rather than checking generation counters alone. */
    gte_test_set_timeline_generations(0xFFFFFFFFu, 90u);
    gte_test_seed_precise_projection(2, packed, x16, y16, z);
    gte_precision_store_word(address, 14);
    gte_test_seed_geometry(packed, x16, y16);
    gte_precision_timeline_invalidate();
    if (gte_test_get_precision_generation() != 1u ||
        gte_test_get_geometry_generation() != 91u ||
        gte_precision_load_word(address, packed, nullptr, nullptr, nullptr, nullptr) != 0 ||
        gte_geometry_correction_lookup(packed, nullptr, nullptr) != 0)
        return fail_value("independent precision wrap", 0, 0, 0, 1u,
                          gte_test_get_precision_generation());

    gte_test_set_timeline_generations(120u, 0xFFFFFFFFu);
    gte_test_seed_precise_projection(2, packed, x16, y16, z);
    gte_precision_store_word(address, 14);
    gte_test_seed_geometry(packed, x16, y16);
    gte_precision_timeline_invalidate();
    if (gte_test_get_precision_generation() != 121u ||
        gte_test_get_geometry_generation() != 1u ||
        gte_precision_load_word(address, packed, nullptr, nullptr, nullptr, nullptr) != 0 ||
        gte_geometry_correction_lookup(packed, nullptr, nullptr) != 0)
        return fail_value("independent geometry wrap", 0, 0, 0, 1u,
                          gte_test_get_geometry_generation());
    gte_geometry_position_fallback_set(0);
    if (gte_geometry_correction_lookup(packed, nullptr, nullptr) != 0)
        return fail_value("position fallback off", 0, 0, packed, 0, 1);
    return 0;
}

/* LWC2 provenance chain (ENHANCEMENTS.md G1.11): RTPT result parked in the
 * scratchpad by SWC2, reloaded by LWC2, stored to a packet word by SWC2. */
constexpr uint32_t kScratch = 0x1F800040u;
constexpr uint32_t kPacket = 0x00123460u;
constexpr uint32_t kPacked = 0x00420021u;
constexpr int32_t kX16 = 0x00218000;            /* 33.5 */
constexpr int32_t kY16 = 0x00424000;            /* 66.25 */
constexpr uint16_t kZ = 0x0345u;

static int precise_is(uint32_t index, uint32_t packed, int32_t x16, int32_t y16,
                      const char *phase) {
    uint32_t p = 0; int32_t x = 0, y = 0; uint16_t z = 0; uint8_t valid = 0;
    gte_test_get_precise_projection(index, &p, &x, &y, &z, &valid);
    if (!valid || p != packed || x != x16 || y != y16)
        return fail_value(phase, 0, index, packed, static_cast<uint32_t>(x16),
                          valid ? static_cast<uint32_t>(x) : 0xFFFFFFFFu);
    return 0;
}

static void lwc2(CPUState *cpu, uint32_t addr, uint8_t reg, uint32_t value) {
    gte_write_data(cpu, reg, value);           /* what generated code emits */
    gte_precision_lwc2_word(addr, reg, cpu->gte_data[reg], 0x80001000u);
}

int test_precision_lwc2_chain() {
    CPUState cpu{};
    gte_geometry_correction_set(0);
    gte_precision_tracking_set(1);
    gte_precision_timeline_invalidate();

    /* store (scratchpad), load, store (packet): exact at the packet word. */
    gte_test_seed_precise_projection(2, kPacked, kX16, kY16, kZ);
    gte_precision_store_word(kScratch, 14);
    gte_test_set_precise_valid_mask(0u);
    lwc2(&cpu, kScratch, 13, kPacked);
    if (int rc = precise_is(1, kPacked, kX16, kY16, "lwc2 restores SXY1")) return rc;
    gte_precision_store_word(kPacket, 13);
    int32_t x = 0, y = 0; uint16_t z = 0;
    if (!gte_precision_load_word(kPacket, kPacked, &x, &y, &z, nullptr) ||
        x != kX16 || y != kY16 || z != kZ)
        return fail_value("packet word exact after the chain", 0, 13, kPacked,
                          static_cast<uint32_t>(kX16), static_cast<uint32_t>(x));

    /* The word changed between store and load (value check, G1.2's
     * Validate): the reload carries nothing. */
    gte_test_set_precise_valid_mask(0xFu);
    lwc2(&cpu, kScratch, 12, kPacked + 1u);
    if (gte_test_get_precise_valid_mask() != 0xEu)
        return fail_value("changed word drops SXY0", 0, 12, kPacked + 1u, 0xEu,
                          gte_test_get_precise_valid_mask());

    /* A CPU store to the word (even of the same value) drops it. */
    gte_precision_invalidate_word(kScratch + 2u);  /* SH into the word */
    gte_test_set_precise_valid_mask(0xFu);
    lwc2(&cpu, kScratch, 12, kPacked);
    if (gte_test_get_precise_valid_mask() != 0xEu)
        return fail_value("CPU store drops the scratch word", 0, 12, kPacked, 0xEu,
                          gte_test_get_precise_valid_mask());

    /* MTC2 drops only its register. */
    gte_test_seed_precise_projection(0, 1u, 0x10000, 0x20000, 9u);
    gte_test_seed_precise_projection(1, 2u, 0x30000, 0x40000, 9u);
    gte_test_seed_precise_projection(2, 3u, 0x50000, 0x60000, 9u);
    gte_test_seed_precise_projection(3, 3u, 0x50000, 0x60000, 9u);
    gte_write_data(&cpu, 13, 7u);              /* mtc2 SXY1 */
    if (gte_test_get_precise_valid_mask() != 0xDu)
        return fail_value("mtc2 drops SXY1 only", 0, 13, 7u, 0xDu,
                          gte_test_get_precise_valid_mask());

    /* LWC2 into SXYP pushes the shadow FIFO with the guest one and lands the
     * restored projection in SXY2 (and the SXYP mirror). */
    gte_test_seed_precise_projection(1, 2u, 0x30000, 0x40000, 9u);
    gte_test_seed_precise_projection(2, kPacked, kX16, kY16, kZ);
    gte_precision_store_word(kScratch + 4u, 14);
    gte_test_seed_precise_projection(2, 3u, 0x50000, 0x60000, 9u);
    cpu.gte_data[13] = 2u; cpu.gte_data[14] = 3u; cpu.gte_data[15] = 3u;
    lwc2(&cpu, kScratch + 4u, 15, kPacked);
    if (cpu.gte_data[12] != 2u || cpu.gte_data[13] != 3u || cpu.gte_data[14] != kPacked)
        return fail_value("SXYP pushes the guest FIFO", 0, 15, kPacked, kPacked,
                          cpu.gte_data[14]);
    if (int rc = precise_is(0, 2u, 0x30000, 0x40000, "SXYP: SXY1 -> SXY0")) return rc;
    if (int rc = precise_is(1, 3u, 0x50000, 0x60000, "SXYP: SXY2 -> SXY1")) return rc;
    if (int rc = precise_is(2, kPacked, kX16, kY16, "SXYP: restored SXY2")) return rc;
    if (int rc = precise_is(3, kPacked, kX16, kY16, "SXYP: mirror")) return rc;

    /* LWC2 into a non-SXY register does nothing to the shadow. */
    gte_test_set_precise_valid_mask(0xFu);
    lwc2(&cpu, kScratch, 0, kPacked);
    if (gte_test_get_precise_valid_mask() != 0xFu)
        return fail_value("lwc2 V0 leaves SXY", 0, 0, kPacked, 0xFu,
                          gte_test_get_precise_valid_mask());

    /* A speculative pass neither restores nor records, and is undone. */
    gte_test_seed_precise_projection(2, kPacked, kX16, kY16, kZ);
    gte_precision_store_word(kScratch + 8u, 14);
    gte_test_set_precise_valid_mask(0x1u);
    gte_precision_speculative_begin();
    lwc2(&cpu, kScratch + 8u, 13, kPacked);
    if (gte_test_get_precise_valid_mask() != 0x1u)
        return fail_value("speculative lwc2 restores nothing", 0, 13, kPacked, 0x1u,
                          gte_test_get_precise_valid_mask());
    gte_precision_speculative_end();
    lwc2(&cpu, kScratch + 8u, 13, kPacked);
    if (int rc = precise_is(1, kPacked, kX16, kY16, "authoritative lwc2 after speculation"))
        return rc;

    /* A state load (timeline invalidation) forgets the scratchpad table. */
    gte_precision_timeline_invalidate();
    lwc2(&cpu, kScratch + 8u, 13, kPacked);
    if (gte_test_get_precise_valid_mask() & 0x2u)
        return fail_value("state load forgets scratch provenance", 0, 13, kPacked, 0u,
                          gte_test_get_precise_valid_mask());

    /* Tracking off: one flag test, nothing restored. */
    gte_precision_tracking_set(0);
    gte_test_seed_precise_projection(2, kPacked, kX16, kY16, kZ);
    gte_precision_store_word(kScratch + 12u, 14);
    gte_test_set_precise_valid_mask(0u);
    lwc2(&cpu, kScratch + 12u, 13, kPacked);
    if (gte_test_get_precise_valid_mask() != 0u)
        return fail_value("tracking off restores nothing", 0, 13, kPacked, 0u,
                          gte_test_get_precise_valid_mask());

    /* Geometry correction alone turns tracking on (its exact path needs it). */
    gte_geometry_correction_set(1);
    gte_test_seed_precise_projection(2, kPacked, kX16, kY16, kZ);
    gte_precision_store_word(kScratch + 12u, 14);
    lwc2(&cpu, kScratch + 12u, 13, kPacked);
    if (int rc = precise_is(1, kPacked, kX16, kY16, "geometry alone tracks")) return rc;
    gte_geometry_correction_set(0);
    return 0;
}

/* [widescreen] nclip_gpu_coords (B71): Tekken 3's packed weld of two
 * vertices on both sides of X = 0 leaves 0x7FFF in SX2 (the GPU draws -1).
 * Words taken from scene c of the PGXP bench (2026-10-18). The console's
 * 16-bit NCLIP gives a negative MAC0 and culls this front face. */
int test_nclip_gpu_coords() {
    using PSXRecomp::GTE::gte_nclip;
    struct Case {
        const char *phase;
        int option, wide;
        uint32_t sxy[3];
        int32_t expected;
    };
    const Case cases[] = {
        {"nclip console 16-bit", 0, 1, {0x0184FFFAu, 0x018D0001u, 0x01927FFFu}, -294859},
        {"nclip option in 4:3", 1, 0, {0x0184FFFAu, 0x018D0001u, 0x01927FFFu}, -294859},
        {"nclip option native-wide", 1, 1, {0x0184FFFAu, 0x018D0001u, 0x01927FFFu}, 53},
        {"nclip 0x8000 half", 1, 1, {0x0184FFFAu, 0x018D0001u, 0x01938003u}, 24},
        /* Projected words are saturated to 11 bits: never changed. */
        {"nclip projected words", 1, 1, {0x0100FFC0u, 0x012003FFu, 0x0110FC00u}, 48112},
    };
    for (const Case &c : cases) {
        GTEState gte{};
        for (int i = 0; i < 3; ++i) gte.SXY[i] = static_cast<int32_t>(c.sxy[i]);
        gte_ws_set_nclip_gpu_coords(c.option);
        g_test_native_wide = c.wide;
        gte_nclip(&gte, 0x1400006u);
        if (gte.MAC0 != c.expected)
            return fail_value(c.phase, 0, 24, c.sxy[2],
                              static_cast<uint32_t>(c.expected),
                              static_cast<uint32_t>(gte.MAC0));
    }
    gte_ws_set_nclip_gpu_coords(0);
    g_test_native_wide = 0;
    return 0;
}

} // namespace

/* Value propagation through the CPU (ENHANCEMENTS.md G1.12): a vertex welded
 * from two projections parked in the scratchpad, the way a body renderer
 * does it (halve two packed SXY words, mask the bit Y shifted into X, add,
 * store), then reloaded by LWC2 and stored to a packet. */
static uint32_t half_word(uint32_t w) { return ((uint32_t)((int32_t)w >> 1)) & 0xFFFF7FFFu; }

int test_precision_cpu_weld() {
    CPUState cpu{};
    gte_geometry_correction_set(0);
    gte_precision_tracking_set(1);
    gte_precision_timeline_invalidate();
    const uint32_t kA = 0x00640032u, kB = 0x003C001Fu;          /* (50,100) (31,60) */
    const int32_t ax = 0x00328000, ay = 0x00640000;             /* 50.5, 100.0 */
    const int32_t bx = 0x001FC000, by = 0x003C8000;             /* 31.75, 60.5 */
    const uint32_t sA = kScratch + 0x20u, sB = kScratch + 0x24u;
    const uint32_t sHalf = kScratch + 0x28u, sWeld = kScratch + 0x2Cu;
    gte_test_seed_precise_projection(2, kA, ax, ay, 1000u);
    gte_precision_store_word(sA, 14);
    gte_test_seed_precise_projection(2, kB, bx, by, 2000u);
    gte_precision_store_word(sB, 14);

    /* Half of B parked by SW. */
    gte_precision_cpu_lw(11, sB);
    gte_precision_cpu_sra(11, 11, 1, kB);
    gte_precision_cpu_and(11, 11, 12, (uint32_t)((int32_t)kB >> 1), 0xFFFF7FFFu);
    const uint32_t hB = half_word(kB);
    gte_precision_invalidate_word(sHalf);                    /* the store itself */
    gte_precision_cpu_sw(sHalf, 11, hB);

    /* Weld = half of B (reloaded) + half of A. */
    gte_precision_cpu_lw(9, sHalf);
    gte_precision_cpu_lw(11, sA);
    gte_precision_cpu_sra(11, 11, 1, kA);
    gte_precision_cpu_and(11, 11, 12, (uint32_t)((int32_t)kA >> 1), 0xFFFF7FFFu);
    const uint32_t hA = half_word(kA);
    gte_precision_cpu_add(9, 9, 11, hB, hA);
    const uint32_t weld = hB + hA;
    gte_precision_invalidate_word(sWeld);
    gte_precision_cpu_sw(sWeld, 9, weld);

    gte_test_set_precise_valid_mask(0u);
    lwc2(&cpu, sWeld, 13, weld);
    /* Halved as the game halves: (x - (X mod 2)) / 2, so the weld's integer is
     * the game's own word and only the fraction is added. */
    auto half16 = [](int32_t v) { return (v - (((v >> 16) & 1) << 16)) >> 1; };
    const int32_t wx = half16(ax) + half16(bx), wy = half16(ay) + half16(by);
    if (int rc = precise_is(1, weld, wx, wy, "welded vertex restored by lwc2")) return rc;
    if (!gte_test_get_precise_derived(1))
        return fail_value("welded vertex is derived", 0, 13, weld, 1u, 0u);
    gte_precision_store_word(kPacket + 0x10u, 13);
    int32_t x = 0, y = 0; uint16_t z = 0; uint8_t derived = 0;
    if (!gte_precision_load_word(kPacket + 0x10u, weld, &x, &y, &z, &derived) ||
        x != wx || y != wy || z != 1500u || !derived)
        return fail_value("packet word carries the weld", 0, 13, weld,
                          static_cast<uint32_t>(wx), static_cast<uint32_t>(x));
    /* The weld's integer part is the game's word exactly. */
    const int32_t gx = (int32_t)(int16_t)(weld & 0xFFFFu), gy = (int32_t)(int16_t)(weld >> 16);
    if ((x >> 16) != gx || (y >> 16) != gy)
        return fail_value("weld integer is the game's", 0, 13, weld, (uint32_t)gx, (uint32_t)(x >> 16));

    /* A straight copy (LW then SW) keeps an exact, non-derived projection. */
    gte_precision_cpu_lw(9, sA);
    gte_precision_invalidate_word(sWeld);
    gte_precision_cpu_sw(sWeld, 9, kA);
    lwc2(&cpu, sWeld, 12, kA);
    if (int rc = precise_is(0, kA, ax, ay, "copied vertex restored")) return rc;
    if (gte_test_get_precise_derived(0))
        return fail_value("copied vertex is exact", 0, 12, kA, 0u, 1u);

    /* Validate(): a register whose value changed since its shadow was made
     * stores nothing; neither does a mask that cuts a half-word, nor ANDI. */
    gte_precision_cpu_lw(9, sA);
    gte_precision_invalidate_word(sWeld);
    gte_precision_cpu_sw(sWeld, 9, kA + 1u);
    gte_test_set_precise_valid_mask(0u);
    lwc2(&cpu, sWeld, 12, kA + 1u);
    if (gte_test_get_precise_valid_mask() != 0u)
        return fail_value("changed register stores no shadow", 0, 12, kA + 1u, 0u,
                          gte_test_get_precise_valid_mask());
    gte_precision_cpu_lw(9, sA);
    gte_precision_cpu_and(9, 9, 12, kA, 0x0000FFFFu);
    gte_precision_invalidate_word(sWeld);
    gte_precision_cpu_sw(sWeld, 9, kA & 0xFFFFu);
    lwc2(&cpu, sWeld, 12, kA & 0xFFFFu);
    if (gte_test_get_precise_valid_mask() != 0u)
        return fail_value("cutting mask drops the shadow", 0, 12, kA, 0u,
                          gte_test_get_precise_valid_mask());
    gte_precision_cpu_lw(9, sA);
    gte_precision_cpu_drop(9);                                /* andi */
    gte_precision_invalidate_word(sWeld);
    gte_precision_cpu_sw(sWeld, 9, kA);
    lwc2(&cpu, sWeld, 12, kA);
    if (gte_test_get_precise_valid_mask() != 0u)
        return fail_value("andi drops the shadow", 0, 12, kA, 0u,
                          gte_test_get_precise_valid_mask());

    /* OR with zero is a move; $zero never carries a shadow. */
    gte_precision_cpu_lw(9, sA);
    gte_precision_cpu_or(10, 9, 0, kA, 0u);
    gte_precision_cpu_lw(0, sA);
    gte_precision_invalidate_word(sWeld);
    gte_precision_cpu_sw(sWeld, 10, kA);
    lwc2(&cpu, sWeld, 12, kA);
    if (int rc = precise_is(0, kA, ax, ay, "or with zero moves the shadow")) return rc;

    /* RAM words carry shadows too (vertex tables shared between calls). */
    const uint32_t kTable = 0x0009BD60u;
    gte_precision_cpu_lw(9, sA);
    gte_precision_invalidate_word(kTable);
    gte_precision_cpu_sw(kTable, 9, kA);
    gte_precision_cpu_lw(13, kTable);
    gte_precision_invalidate_word(sWeld);
    gte_precision_cpu_sw(sWeld, 13, kA);
    gte_test_set_precise_valid_mask(0u);
    lwc2(&cpu, sWeld, 12, kA);
    if (int rc = precise_is(0, kA, ax, ay, "shadow through a RAM table")) return rc;

    /* Speculation and tracking off: the hooks do nothing. */
    gte_precision_cpu_lw(9, sA);
    gte_precision_speculative_begin();
    gte_precision_invalidate_word(sWeld);
    gte_precision_cpu_sw(sWeld, 9, kA);
    gte_precision_speculative_end();
    gte_precision_invalidate_word(sWeld);
    gte_test_set_precise_valid_mask(0u);
    lwc2(&cpu, sWeld, 12, kA);
    if (gte_test_get_precise_valid_mask() != 0u)
        return fail_value("speculative sw stores no shadow", 0, 12, kA, 0u,
                          gte_test_get_precise_valid_mask());
    gte_precision_tracking_set(0);
    gte_precision_cpu_lw(9, sA);
    gte_precision_cpu_sw(sWeld, 9, kA);
    gte_precision_tracking_set(1);
    lwc2(&cpu, sWeld, 12, kA);
    if (gte_test_get_precise_valid_mask() != 0u)
        return fail_value("tracking off: no shadow", 0, 12, kA, 0u,
                          gte_test_get_precise_valid_mask());
    gte_precision_tracking_set(0);
    return 0;
}

/* G1.13: packet words in the mods' GPU-DMA aperture are tracked under keys
 * of their own (never RAM's, though both fold to the same low 21 bits), and
 * a native mod's projection is read back only while its word holds it. */
int test_precision_aperture_native() {
    gte_geometry_correction_set(0);
    gte_precision_tracking_set(1);
    gte_precision_timeline_invalidate();
    const uint32_t kAp = 0x80E01000u, kRam = 0x80001000u;      /* same 21 low bits */
    const uint32_t pA = 0x00640032u, pR = 0x003C001Fu;
    gte_test_seed_precise_projection(2, pA, 0x00328000, 0x00640000, 1000u);
    gte_precision_store_word(kAp, 14);
    gte_test_seed_precise_projection(2, pR, 0x001FC000, 0x003C8000, 2000u);
    gte_precision_store_word(kRam, 14);
    int32_t x = 0, y = 0; uint16_t z = 0;
    if (!gte_precision_load_word(0x00E01000u, pA, &x, &y, &z, nullptr) || x != 0x00328000 || z != 1000u)
        return fail_value("aperture SWC2 tracked", 0, 14, pA, 0x00328000u, static_cast<uint32_t>(x));
    if (!gte_precision_load_word(kRam, pR, &x, &y, &z, nullptr) || x != 0x001FC000 || z != 2000u)
        return fail_value("RAM word kept beside the aperture word", 0, 14, pR, 0x001FC000u,
                          static_cast<uint32_t>(x));
    if (gte_precision_load_word(kRam, pA, &x, &y, &z, nullptr))
        return fail_value("aperture word not read at its RAM alias", 0, 14, pA, 0u, 1u);

    /* Native projection: after the store, value checked, dropped by a store. */
    const uint32_t kNat = 0x80E02000u, pN = 0x00500028u;
    if (!gte_precision_native_active())
        return fail_value("native precision active while tracking", 0, 0, 0, 1u, 0u);
    gte_precision_native_word(kNat, pN, 0x0028C000, 0x00504000, 300u);
    if (!gte_precision_load_word(kNat, pN, &x, &y, &z, nullptr) ||
        x != 0x0028C000 || y != 0x00504000 || z != 300u)
        return fail_value("native word read back", 0, 0, pN, 0x0028C000u, static_cast<uint32_t>(x));
    if (gte_precision_load_word(kNat, pN + 1u, &x, &y, &z, nullptr))
        return fail_value("native word refused for another value", 0, 0, pN + 1u, 0u, 1u);
    gte_precision_invalidate_word(kNat);
    if (gte_precision_load_word(kNat, pN, &x, &y, &z, nullptr))
        return fail_value("native word dropped by a store", 0, 0, pN, 0u, 1u);
    gte_precision_native_word(kRam + 0x10u, pN, 0x0028C000, 0x00504000, 0u);   /* RAM, depth 0 */
    if (!gte_precision_load_word(kRam + 0x10u, pN, &x, &y, &z, nullptr) || z != 1u)
        return fail_value("native RAM word, depth floor 1", 0, 0, pN, 1u, z);

    /* Speculative passes and tracking off record nothing. */
    gte_precision_speculative_begin();
    if (gte_precision_native_active())
        return fail_value("native precision inactive while speculative", 0, 0, 0, 0u, 1u);
    gte_precision_native_word(kNat, pN, 0x0028C000, 0x00504000, 300u);
    gte_precision_speculative_end();
    if (gte_precision_load_word(kNat, pN, &x, &y, &z, nullptr))
        return fail_value("native word not stored while speculative", 0, 0, pN, 0u, 1u);
    gte_precision_tracking_set(0);
    if (gte_precision_native_active())
        return fail_value("native precision inactive with tracking off", 0, 0, 0, 0u, 1u);
    gte_precision_native_word(kNat, pN, 0x0028C000, 0x00504000, 300u);
    gte_precision_tracking_set(1);
    if (gte_precision_load_word(kNat, pN, &x, &y, &z, nullptr))
        return fail_value("native word not stored with tracking off", 0, 0, pN, 0u, 1u);
    gte_precision_tracking_set(0);
    return 0;
}

/* G1.15: the hooks run by the interpreters over precision_funcs ranges, and
 * a vertex word built one coordinate at a time, the way Tekken 3's showcase
 * floor splits a near tile: LH of X and Y of two corners, (a + b + sign) >> 1
 * (SRL 31, ADDU, SRL 1; Y sign-extended by SLL 16 / SRA 16), SH of each half. */
static uint32_t enc_i(uint32_t op, uint32_t rs, uint32_t rt, uint32_t imm) {
    return op << 26 | rs << 21 | rt << 16 | (imm & 0xFFFFu);
}
static uint32_t enc_r(uint32_t fn, uint32_t rs, uint32_t rt, uint32_t rd, uint32_t sa) {
    return rs << 21 | rt << 16 | rd << 11 | sa << 6 | fn;
}

int test_precision_interp_halfwords() {
    gte_geometry_correction_set(0);
    gte_precision_tracking_set(1);
    gte_precision_timeline_invalidate();
    const uint32_t lo[2] = { 0x800D4000u, 0x80037B28u }, hi[2] = { 0x800D5000u, 0x80037B28u };
    gte_precision_interp_ranges_set(lo, hi, 2);
    if (!gte_precision_interp_pc(0x800D4100u) || !gte_precision_interp_pc(0x000D4100u) ||
        gte_precision_interp_pc(0x800D5004u) || gte_precision_interp_pc(0x80037B28u))
        return fail_value("interp ranges: ranges only, any segment", 0, 0, 0, 1u, 0u);

    const uint32_t kA = 0x00640032u, kB = 0x003C001Fu;          /* (50,100) (31,60) */
    const int32_t ax = 0x00328000, ay = 0x00640000;             /* 50.5, 100.0 */
    const int32_t bx = 0x001FC000, by = 0x003C8000;             /* 31.75, 60.5 */
    const uint32_t sA = kScratch + 0x40u, sB = kScratch + 0x44u, pkt = kPacket + 0x40u;
    gte_test_seed_precise_projection(2, kA, ax, ay, 1000u);
    gte_precision_store_word(sA, 14);
    gte_test_seed_precise_projection(2, kB, bx, by, 2000u);
    gte_precision_store_word(sB, 14);

    /* lh $4,0(sA) ; lh $8,0(sB) ; lh $6,2(sA) ; lh $9,2(sB), as the interpreter decodes them. */
    gte_precision_interp_before(enc_i(0x21, 1, 4, 0), sA, 0);
    gte_precision_interp_before(enc_i(0x21, 1, 8, 0), sB, 0);
    gte_precision_interp_before(enc_i(0x25, 1, 6, 2), sA, 0);   /* lhu: same coordinate */
    gte_precision_interp_before(enc_i(0x21, 1, 9, 2), sB, 0);
    /* X: v1 = a0 + t0 ; v0 = v1 >> 31 (srl) ; v1 += v0 ; v1 = v1 >> 1 (srl) */
    gte_precision_interp_before(enc_r(0x21, 4, 8, 3, 0), 50u, 31u);
    gte_precision_interp_before(enc_r(0x02, 0, 3, 2, 31), 0, 81u);
    gte_precision_interp_before(enc_r(0x21, 3, 2, 3, 0), 81u, 0u);
    gte_precision_interp_before(enc_r(0x02, 0, 3, 3, 1), 0, 81u);
    /* Y: a3 = a2 + t1 ; v0 = a3 >> 31 ; a3 += v0 ; a3 = a3 >> 1 (sra) ; sll 16 ; sra 16 */
    gte_precision_interp_before(enc_r(0x21, 6, 9, 7, 0), 100u, 60u);
    gte_precision_interp_before(enc_r(0x02, 0, 7, 2, 31), 0, 160u);
    gte_precision_interp_before(enc_r(0x21, 7, 2, 7, 0), 160u, 0u);
    gte_precision_interp_before(enc_r(0x03, 0, 7, 7, 1), 0, 160u);
    gte_precision_interp_before(enc_r(0x00, 0, 7, 7, 16), 0, 80u);
    gte_precision_interp_before(enc_r(0x03, 0, 7, 7, 16), 0, 80u << 16);

    const uint32_t word = 80u << 16 | 40u;
    int32_t x = 0, y = 0; uint16_t z = 0; uint8_t derived = 0;
    gte_precision_invalidate_store(pkt, 2);
    gte_precision_cpu_sh(pkt, 3, 40u);
    if (gte_precision_load_word(pkt, word, &x, &y, &z, &derived))
        return fail_value("one half alone is no vertex", 0, 3, word, 0u, 1u);
    gte_precision_invalidate_store(pkt + 2u, 2);                 /* keeps the X half */
    gte_precision_cpu_sh(pkt + 2u, 7, 80u);
    /* Halved as the game halves (its integer bit dropped): (sum - (S mod 2)) / 2. */
    const int32_t wx = (ax + bx - (1 << 16)) >> 1, wy = (ay + by) >> 1;
    if (!gte_precision_load_word(pkt, word, &x, &y, &z, &derived) || x != wx || y != wy ||
        z != 1500u || !derived)
        return fail_value("vertex word built from two halves", 0, 7, word,
                          static_cast<uint32_t>(wx), static_cast<uint32_t>(x));
    if ((x >> 16) != 40 || (y >> 16) != 80)
        return fail_value("built vertex integer is the game's", 0, 7, word, 40u,
                          static_cast<uint32_t>(x >> 16));

    /* A byte store into the word drops it; a half stored without a shadow
     * leaves no vertex either. */
    gte_precision_invalidate_store(pkt + 1u, 1);
    if (gte_precision_load_word(pkt, word, &x, &y, &z, &derived))
        return fail_value("byte store drops the built word", 0, 0, word, 0u, 1u);
    gte_precision_invalidate_store(pkt, 2);
    gte_precision_cpu_sh(pkt, 3, 41u);                            /* register changed */
    if (gte_precision_load_word(pkt, (80u << 16) | 41u, &x, &y, &z, &derived))
        return fail_value("changed register builds nothing", 0, 3, word, 0u, 1u);

    /* A copied coordinate (lhu, sh) stays exact; a word copied by lw / sw too. */
    const uint32_t pkt2 = kPacket + 0x48u;
    gte_precision_interp_before(enc_i(0x25, 1, 10, 0), sA, 0);
    gte_precision_interp_before(enc_i(0x25, 1, 11, 2), sA, 0);
    gte_precision_invalidate_store(pkt2, 2);
    gte_precision_cpu_sh(pkt2, 10, 50u);
    gte_precision_invalidate_store(pkt2 + 2u, 2);
    gte_precision_cpu_sh(pkt2 + 2u, 11, 100u);
    if (!gte_precision_load_word(pkt2, kA, &x, &y, &z, &derived) || x != ax || y != ay || derived)
        return fail_value("copied halves rebuild the exact vertex", 0, 10, kA,
                          static_cast<uint32_t>(ax), static_cast<uint32_t>(x));
    gte_precision_interp_before(enc_i(0x23, 1, 12, 0), sB, 0);
    gte_precision_invalidate_word(pkt2);
    gte_precision_cpu_sw(pkt2, 12, kB);
    if (!gte_precision_load_word(pkt2, kB, &x, &y, &z, &derived) || x != bx || y != by)
        return fail_value("interpreted lw / sw copy", 0, 12, kB, static_cast<uint32_t>(bx),
                          static_cast<uint32_t>(x));
    gte_precision_interp_ranges_set(lo, hi, 0);
    gte_precision_tracking_set(0);
    return 0;
}

int main() {
    if (int rc = test_canonicalizer()) return rc;
    if (int rc = test_reads()) return rc;
    if (int rc = test_writes()) return rc;
    if (int rc = test_sequence_fuzz()) return rc;
    if (int rc = test_command_marshaling()) return rc;
    if (int rc = test_command_timing_hook()) return rc;
    if (int rc = test_precise_sxy_invalidation()) return rc;
    if (int rc = test_precision_speculative_transaction()) return rc;
    if (int rc = test_nclip_gpu_coords()) return rc;
    if (int rc = test_precision_lwc2_chain()) return rc;
    if (int rc = test_precision_cpu_weld()) return rc;
    if (int rc = test_precision_aperture_native()) return rc;
    if (int rc = test_precision_interp_halfwords()) return rc;
    std::puts("PASS: canonical GTE register helpers match GTEState transfer oracle");
    return 0;
}
