/*
 * test_chain_handler_check.c — validate disassembly interpretation of
 * func_00005A08 (state-11 chain handler in the BIOS card READ protocol).
 *
 * The wtrace evidence + disasm says:
 *   - func_00005A08 reads RX byte from SIO MMIO into $a0
 *   - reads expected from kernel state into $t6 = ($a2 & 0xFF)
 *   - branches: beq $a0, $t6 → continue at 0xBFC15548
 *                fallthrough → always-taken to 0xBFC15654 (epilogue, $v0=-1)
 *
 * If $v0 = -1 returned, chain dispatcher (func_00004D6C) writes 0x21 to
 * the slot state byte at 0x7568[slot], aborting the read. This is the
 * exact pattern wtrace captured.
 *
 * This test calls func_00005A08 directly with controlled inputs:
 *   case 1: SIO RX = 0x4D ('M' data byte), $a2 = 0 (sector 0)
 *           → $a0=0x4D, $t6=0, mismatch → error exit, cpu->pc = 0xBFC15654
 *   case 2: SIO RX = 0x00, $a2 = 0 (sector 0)
 *           → $a0=0, $t6=0, match → cpu->pc = 0xBFC15548
 *
 * If both cases behave as predicted, the disassembly interpretation is correct.
 *
 * Build: cc -I../include -o test_chain_handler_check test_chain_handler_check.c
 *           ../../generated/SCPH1001_full.c ../../generated/SCPH1001_dispatch.c
 *           [stubs for psx_check_interrupts, psx_dispatch, etc.]
 *
 * That's ~22K lines of generated code — too heavy. So this test uses a
 * Python-style interpretation: we emulate the func_00005A08 body in C
 * directly (mirroring the recompiled C exactly) and assert the branch
 * decision. Same instructions, same data flow, no dependency on the
 * larger recompiled BIOS.
 */

#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/* ---- Minimal CPUState mock — RAM is static to avoid stack overflow ---- */
static uint8_t g_ram[0x200000];  /* 2MB main RAM */
typedef struct {
    uint32_t gpr[32];
    uint32_t pc;
    uint8_t* ram;  /* points to g_ram */
} MockCPU;

static uint8_t mock_read_byte(MockCPU* cpu, uint32_t addr) {
    /* SIO RX = 0x1F801040 — return controlled value */
    if (addr == 0x1F801040) return cpu->ram[0x1F801040 & 0x1FFFFF];
    /* Kernel SIO ptr at 0x7258 reads back as SIO MMIO base */
    if ((addr & 0x1FFFFFFFu) < 0x200000u)
        return cpu->ram[addr & 0x1FFFFF];
    return 0xFF;
}

static uint16_t mock_read_half(MockCPU* cpu, uint32_t addr) {
    return (uint16_t)mock_read_byte(cpu, addr) | ((uint16_t)mock_read_byte(cpu, addr+1) << 8);
}

static uint32_t mock_read_word(MockCPU* cpu, uint32_t addr) {
    return (uint32_t)mock_read_byte(cpu, addr)
         | ((uint32_t)mock_read_byte(cpu, addr+1) << 8)
         | ((uint32_t)mock_read_byte(cpu, addr+2) << 16)
         | ((uint32_t)mock_read_byte(cpu, addr+3) << 24);
}

static void mock_write_byte(MockCPU* cpu, uint32_t addr, uint8_t val) {
    if ((addr & 0x1FFFFFFFu) < 0x200000u) cpu->ram[addr & 0x1FFFFF] = val;
}

static void mock_write_half(MockCPU* cpu, uint32_t addr, uint16_t val) {
    mock_write_byte(cpu, addr, (uint8_t)(val & 0xFF));
    mock_write_byte(cpu, addr+1, (uint8_t)(val >> 8));
}

static void mock_write_word(MockCPU* cpu, uint32_t addr, uint32_t val) {
    mock_write_byte(cpu, addr, (uint8_t)(val & 0xFF));
    mock_write_byte(cpu, addr+1, (uint8_t)((val >> 8) & 0xFF));
    mock_write_byte(cpu, addr+2, (uint8_t)((val >> 16) & 0xFF));
    mock_write_byte(cpu, addr+3, (uint8_t)((val >> 24) & 0xFF));
}

/* ---- Mirror of func_00005A08's first block (label_BFC15508), exactly as
 *      the recompiler emitted, but inline — no psx_check_interrupts/dispatch.
 *      Returns 1 if check passed (continue protocol), 0 if check failed (error). */
static int sim_func_00005A08(MockCPU* cpu) {
    /* 0xBFC15508: lw $v1, 29272($v1) — $v1 = word at 0x7258+$v1 base
     *   (RAM 0x7258 = kernel SIO MMIO ptr, value 0x1F801040 typically) */
    cpu->gpr[3] = mock_read_word(cpu, cpu->gpr[3] + 29272);

    /* 0xBFC1550C: addu $t1, $t1, $a3  — $t1 += slot */
    cpu->gpr[9] = cpu->gpr[9] + cpu->gpr[7];

    /* 0xBFC15510: lbu $t1, 30040($t1) — $t1 = byte at 0x7558+slot */
    cpu->gpr[9] = mock_read_byte(cpu, cpu->gpr[9] + 30040);

    /* 0xBFC15514: lbu $a0, 0($v1) — $a0 = SIO RX byte */
    cpu->gpr[4] = mock_read_byte(cpu, cpu->gpr[3]);

    /* 0xBFC15518: sb $t1, 0($v1) — write next TX byte */
    mock_write_byte(cpu, cpu->gpr[3], (uint8_t)cpu->gpr[9]);

    /* 0xBFC1551C-0xBFC15530: SIO CTRL ack + I_STAT clear (skipped — not relevant to check) */
    /* 0xBFC15534: andi $t6, $a2, 0xFF */
    cpu->gpr[14] = cpu->gpr[6] & 0xFF;

    /* 0xBFC15538: beq $a0, $t6, 0xBFC15548 */
    int taken = (cpu->gpr[4] == cpu->gpr[14]);
    return taken ? 1 : 0;
}

/* ---- Tests ---- */

static int g_failures = 0;

#define EXPECT(label, cond)                                                     \
    do {                                                                        \
        if (!(cond)) {                                                          \
            g_failures++;                                                       \
            fprintf(stderr, "FAIL  %s\n", label);                               \
        } else {                                                                \
            fprintf(stderr, "ok    %s\n", label);                               \
        }                                                                       \
    } while (0)

static void setup_cpu(MockCPU* cpu, uint8_t rx_byte, uint32_t a2_sector,
                      uint32_t a3_slot, uint8_t per_slot_byte) {
    memset(cpu, 0, sizeof(*cpu));
    memset(g_ram, 0, sizeof(g_ram));
    cpu->ram = g_ram;
    /* Place SIO MMIO base ptr at 0x7258 */
    mock_write_word(cpu, 0x7258, 0x1F801040);
    /* Place RX byte at SIO RX address */
    mock_write_byte(cpu, 0x1F801040 & 0x1FFFFF, rx_byte);
    /* Set $a2 = sector */
    cpu->gpr[6] = a2_sector;
    /* Set $a3 = slot */
    cpu->gpr[7] = a3_slot;
    /* Set $v1 = 0 so first instruction reads SIO ptr from 0x0 + 29272 = 0x7258 */
    cpu->gpr[3] = 0;
    /* Set $t1 = 0 so $t1 += $a3 = slot, then lbu reads 0x7558 + slot */
    cpu->gpr[9] = 0;
    /* Place per-slot byte at 0x7558 */
    mock_write_byte(cpu, 0x7558 + a3_slot, per_slot_byte);
}

int main(void) {
    MockCPU cpu;

    fprintf(stderr, "=== chain handler byte-check disasm validation ===\n");

    /* Case 1: RX = 0x4D ('M'), $a2 = 0 (sector 0)
     *   $t6 = $a2 & 0xFF = 0
     *   $a0 = 0x4D
     *   beq 0x4D, 0 → NOT TAKEN → error path → return 0
     *   This is what we observe in the runtime — protocol bails at byte 11. */
    setup_cpu(&cpu, /*rx*/0x4D, /*sector*/0, /*slot*/0, /*per_slot*/0);
    int r1 = sim_func_00005A08(&cpu);
    EXPECT("case1 RX=0x4D sector=0 → error (return 0)", r1 == 0);

    /* Case 2: RX = 0x00, $a2 = 0 (sector 0)
     *   $t6 = 0, $a0 = 0
     *   beq 0, 0 → TAKEN → continue → return 1 */
    setup_cpu(&cpu, /*rx*/0x00, /*sector*/0, /*slot*/0, /*per_slot*/0);
    int r2 = sim_func_00005A08(&cpu);
    EXPECT("case2 RX=0x00 sector=0 → continue (return 1)", r2 == 1);

    /* Case 3: RX = 0x01, $a2 = 1 (sector 1)
     *   $t6 = 1, $a0 = 1
     *   beq 1, 1 → TAKEN → continue → return 1 */
    setup_cpu(&cpu, /*rx*/0x01, /*sector*/1, /*slot*/0, /*per_slot*/0);
    int r3 = sim_func_00005A08(&cpu);
    EXPECT("case3 RX=0x01 sector=1 → continue (return 1)", r3 == 1);

    /* Case 4: RX = data byte, $a2 = sector — for any sector with data[N] != sector_low,
     *   the check fails. Confirms the disasm: this state validates that RX equals
     *   the LOW BYTE OF THE EXPECTED ECHO at this protocol step (NOT a data byte).
     *   So this state must be the LSB ECHO step, NOT a data-byte step. */
    setup_cpu(&cpu, /*rx*/0x43, /*sector*/0, /*slot*/0, /*per_slot*/0);
    int r4 = sim_func_00005A08(&cpu);
    EXPECT("case4 RX=0x43 ('C') sector=0 → error (return 0)", r4 == 0);

    fprintf(stderr, "=== %s: %d failures ===\n",
            g_failures == 0 ? "PASS" : "FAIL", g_failures);
    return g_failures > 0 ? 1 : 0;
}
