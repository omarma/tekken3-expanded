// function_discovery.cpp — Phase 1c function discovery pipeline.
// See function_discovery.h for the design contract.

#include "function_discovery.h"

#include <algorithm>
#include <cstdint>
#include <map>
#include <queue>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

#include "fmt/format.h"
#include "bios_address_model.h"
#include "mips_decoder.h"

namespace PSXRecompV4 {

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

uint32_t FunctionDiscovery::read_u32_le(const std::vector<uint8_t>& rom, uint32_t offset) {
    if (offset + 3 >= static_cast<uint32_t>(rom.size())) {
        throw std::runtime_error(fmt::format(
            "FunctionDiscovery: read_u32_le out of range (offset=0x{:X}, rom_size=0x{:X})",
            offset, rom.size()));
    }
    return  static_cast<uint32_t>(rom[offset + 0])
         | (static_cast<uint32_t>(rom[offset + 1]) << 8)
         | (static_cast<uint32_t>(rom[offset + 2]) << 16)
         | (static_cast<uint32_t>(rom[offset + 3]) << 24);
}

/* The active BIOS address model (profile-derived; bios_address_model.h) —
 * shared single source of truth with full_function_emitter.cpp for every
 * relocation window. No built-in default: discovery without a model is a
 * caller bug and aborts loudly. */
static const BiosAddressModel* g_addr_model = nullptr;

void FunctionDiscovery::set_address_model(const BiosAddressModel* m) {
    g_addr_model = m;
}

static const BiosAddressModel& addr_model() {
    if (!g_addr_model) {
        throw std::runtime_error(
            "FunctionDiscovery: no BIOS address model set "
            "(FunctionDiscovery::set_address_model must run before discover)");
    }
    return *g_addr_model;
}

// Phase 1e normalization: KSEG strip + per-copy key fold.
// See generated/normalization_rule.md for the full derivation.
static uint32_t normalize_address(uint32_t addr) {
    return addr_model().normalize(addr);
}

static uint32_t ram_alias_to_rom(uint32_t addr) {
    return addr_model().ram_alias_to_rom(addr);
}

// Relocated code (Shell, Kernel Part 2) runs at RAM addresses, not ROM
// addresses. J/JAL targets use (PC & 0xF0000000) as the region base, so
// when the instruction is analyzed at its ROM address the target lands in
// the wrong region. This mirrors full_function_emitter.cpp
// relocate_j_target, but converts the resulting RAM address back to a ROM
// address so that function discovery can follow it.
static uint32_t remap_relocated_j_target(uint32_t target, uint32_t source_rom_addr) {
    return addr_model().remap_relocated_j_target(target, source_rom_addr);
}

FunctionDiscovery::CFInfo FunctionDiscovery::classify_control_flow(uint32_t raw, uint32_t addr) {
    CFInfo info{};
    info.kind = CFKind::Normal;
    info.target = 0;
    info.reg = 0;

    uint8_t op = (raw >> 26) & 0x3F;

    // Conditional branches: BEQ/BNE/BLEZ/BGTZ
    if (op >= 0x04 && op <= 0x07) {
        int16_t simm = static_cast<int16_t>(raw & 0xFFFF);
        info.kind = CFKind::CondBranch;
        info.target = static_cast<uint32_t>(
            static_cast<int64_t>(addr) + 4 + (static_cast<int64_t>(simm) * 4));
        return info;
    }

    // REGIMM: BLTZ/BGEZ/BLTZAL/BGEZAL
    if (op == 0x01) {
        int16_t simm = static_cast<int16_t>(raw & 0xFFFF);
        info.kind = CFKind::CondBranch;
        info.target = static_cast<uint32_t>(
            static_cast<int64_t>(addr) + 4 + (static_cast<int64_t>(simm) * 4));
        return info;
    }

    // J (unconditional jump)
    if (op == 0x02) {
        uint32_t target26 = raw & 0x03FFFFFF;
        info.kind = CFKind::Jump;
        info.target = ((addr + 4) & 0xF0000000u) | (target26 << 2);
        info.target = remap_relocated_j_target(info.target, addr);
        return info;
    }

    // JAL (call)
    if (op == 0x03) {
        uint32_t target26 = raw & 0x03FFFFFF;
        info.kind = CFKind::Call;
        info.target = ((addr + 4) & 0xF0000000u) | (target26 << 2);
        info.target = remap_relocated_j_target(info.target, addr);
        return info;
    }

    // SPECIAL: JR / JALR / SYSCALL / BREAK
    if (op == 0x00) {
        uint8_t funct = raw & 0x3F;
        if (funct == 0x08) { // JR
            uint8_t rs = (raw >> 21) & 0x1F;
            if (rs == 31) { // $ra
                info.kind = CFKind::JR_RA;
            } else {
                info.kind = CFKind::JR_Indirect;
                info.reg = rs;
            }
            return info;
        }
        if (funct == 0x09) { // JALR
            uint8_t rs = (raw >> 21) & 0x1F;
            info.kind = CFKind::JALR;
            info.reg = rs;
            return info;
        }
        if (funct == 0x0C) { // SYSCALL
            info.kind = CFKind::Syscall;
            return info;
        }
        if (funct == 0x0D) { // BREAK
            info.kind = CFKind::Break;
            return info;
        }
    }

    // COP0: RFE (raw == 0x42000010)
    if (raw == 0x42000010u) {
        info.kind = CFKind::RFE;
        return info;
    }

    return info;
}

// ---------------------------------------------------------------------------
// Single function walk (BFS within function boundaries)
// ---------------------------------------------------------------------------

FunctionDiscovery::SingleFunctionResult FunctionDiscovery::walk_function(
    const std::vector<uint8_t>& rom,
    uint32_t                    base_addr,
    uint32_t                    rom_end,
    uint32_t                    entry,
    uint32_t                    hard_cap,
    const std::string&          lineage)
{
    SingleFunctionResult result;

    std::set<uint32_t> visited;
    std::queue<uint32_t> work;
    work.push(entry);

    // Block leaders: every address that is a branch target or follows a
    // control transfer is a basic block leader.
    std::set<uint32_t> block_leader_set;
    block_leader_set.insert(entry);

    auto in_bounds = [&](uint32_t addr) -> bool {
        return addr >= base_addr && addr <= rom_end &&
               addr >= entry && addr < hard_cap;
    };

    auto fetch = [&](uint32_t addr) -> uint32_t {
        uint32_t offset = addr - base_addr;
        return read_u32_le(rom, offset);
    };

    // BFS: visit instructions, follow in-function control flow.
    while (!work.empty()) {
        uint32_t addr = work.front();
        work.pop();

        if (visited.count(addr)) continue;
        if (!in_bounds(addr)) continue;

        uint32_t raw = fetch(addr);
        visited.insert(addr);

        // Validate through strict translator.
        PSXRecomp::DecodedInstruction d = PSXRecomp::MipsDecoder::decode(raw, addr);
        TranslateResult tr = StrictTranslator::translate(d);
        if (!tr.supported) {
            UnsupportedInstr u;
            u.address = addr;
            u.raw = raw;
            u.reason = tr.fail_reason;
            result.unsupported.push_back(std::move(u));
            // Hard failure: do not continue walking from this instruction.
            continue;
        }

        CFInfo cf = classify_control_flow(raw, addr);
        uint32_t delay_addr = addr + 4;

        switch (cf.kind) {
            case CFKind::Normal:
                // Fall through to next instruction.
                if (in_bounds(addr + 4)) {
                    work.push(addr + 4);
                }
                break;

            case CFKind::CondBranch:
                // Visit delay slot, then fall-through (addr+8) and branch target.
                if (in_bounds(delay_addr) && !visited.count(delay_addr)) {
                    visited.insert(delay_addr);
                    // Validate delay slot.
                    uint32_t delay_raw = fetch(delay_addr);
                    PSXRecomp::DecodedInstruction dd = PSXRecomp::MipsDecoder::decode(delay_raw, delay_addr);
                    TranslateResult dtr = StrictTranslator::translate(dd);
                    if (!dtr.supported) {
                        UnsupportedInstr u;
                        u.address = delay_addr;
                        u.raw = delay_raw;
                        u.reason = fmt::format("delay slot of branch at 0x{:08X}: {}", addr, dtr.fail_reason);
                        result.unsupported.push_back(std::move(u));
                    }
                }
                // Fall-through after delay slot.
                if (in_bounds(addr + 8)) {
                    work.push(addr + 8);
                    block_leader_set.insert(addr + 8);
                }
                // Branch target (if in-function).
                if (cf.target != 0 && in_bounds(cf.target)) {
                    work.push(cf.target);
                    block_leader_set.insert(cf.target);
                } else if (cf.target != 0 &&
                           cf.target >= base_addr && cf.target <= rom_end) {
                    // Escapes the walk range (seed-truncated fragment). The
                    // emitter publishes this target; record it for the
                    // dispatchability closure in discover().
                    result.escaping_targets.insert(cf.target);
                }
                break;

            case CFKind::Jump: {
                // Unconditional jump. Visit delay slot.
                if (in_bounds(delay_addr) && !visited.count(delay_addr)) {
                    visited.insert(delay_addr);
                    uint32_t delay_raw = fetch(delay_addr);
                    PSXRecomp::DecodedInstruction dd = PSXRecomp::MipsDecoder::decode(delay_raw, delay_addr);
                    TranslateResult dtr = StrictTranslator::translate(dd);
                    if (!dtr.supported) {
                        UnsupportedInstr u;
                        u.address = delay_addr;
                        u.raw = delay_raw;
                        u.reason = fmt::format("delay slot of J at 0x{:08X}: {}", addr, dtr.fail_reason);
                        result.unsupported.push_back(std::move(u));
                    }
                }
                // Follow target if in-function (intra-function jump).
                if (cf.target != 0 && in_bounds(cf.target)) {
                    work.push(cf.target);
                    block_leader_set.insert(cf.target);
                } else {
                    // J to out-of-function: tail call or exit. Record the
                    // target for the dispatchability closure — usually it is
                    // another function's entry (covered), but a seed-truncated
                    // fragment can jump into bytes no function walks.
                    if (cf.target != 0 &&
                        cf.target >= base_addr && cf.target <= rom_end) {
                        result.escaping_targets.insert(cf.target);
                    }
                    result.exit_types.insert("j_out_of_function");
                }
                break;
            }

            case CFKind::Call: {
                // JAL: visit delay slot, fall through to addr+8.
                // Target is a new function (recorded as edge, NOT followed in this function).
                if (in_bounds(delay_addr) && !visited.count(delay_addr)) {
                    visited.insert(delay_addr);
                    uint32_t delay_raw = fetch(delay_addr);
                    PSXRecomp::DecodedInstruction dd = PSXRecomp::MipsDecoder::decode(delay_raw, delay_addr);
                    TranslateResult dtr = StrictTranslator::translate(dd);
                    if (!dtr.supported) {
                        UnsupportedInstr u;
                        u.address = delay_addr;
                        u.raw = delay_raw;
                        u.reason = fmt::format("delay slot of JAL at 0x{:08X}: {}", addr, dtr.fail_reason);
                        result.unsupported.push_back(std::move(u));
                    }
                }
                // Fall through after JAL (returns to addr+8).
                if (in_bounds(addr + 8)) {
                    work.push(addr + 8);
                    block_leader_set.insert(addr + 8);
                }
                // Record call edge.
                bool target_in_rom = (cf.target >= base_addr && cf.target <= rom_end);
                CallEdge edge;
                edge.caller_func = entry;
                edge.caller_pc = addr;
                edge.callee_addr = cf.target;
                edge.in_rom = target_in_rom;
                result.edges.push_back(std::move(edge));
                break;
            }

            case CFKind::JR_RA: {
                // Function return. Visit delay slot. No fall-through.
                if (in_bounds(delay_addr) && !visited.count(delay_addr)) {
                    visited.insert(delay_addr);
                    uint32_t delay_raw = fetch(delay_addr);
                    PSXRecomp::DecodedInstruction dd = PSXRecomp::MipsDecoder::decode(delay_raw, delay_addr);
                    TranslateResult dtr = StrictTranslator::translate(dd);
                    if (!dtr.supported) {
                        UnsupportedInstr u;
                        u.address = delay_addr;
                        u.raw = delay_raw;
                        u.reason = fmt::format("delay slot of jr $ra at 0x{:08X}: {}", addr, dtr.fail_reason);
                        result.unsupported.push_back(std::move(u));
                    }
                }
                result.exit_types.insert("jr_ra");
                break;
            }

            case CFKind::JR_Indirect: {
                // Indirect jump (not $ra). Visit delay slot. Record for Phase 1d.
                if (in_bounds(delay_addr) && !visited.count(delay_addr)) {
                    visited.insert(delay_addr);
                    uint32_t delay_raw = fetch(delay_addr);
                    PSXRecomp::DecodedInstruction dd = PSXRecomp::MipsDecoder::decode(delay_raw, delay_addr);
                    TranslateResult dtr = StrictTranslator::translate(dd);
                    if (!dtr.supported) {
                        UnsupportedInstr u;
                        u.address = delay_addr;
                        u.raw = delay_raw;
                        u.reason = fmt::format("delay slot of jr at 0x{:08X}: {}", addr, dtr.fail_reason);
                        result.unsupported.push_back(std::move(u));
                    }
                }
                IndirectJumpSite site;
                site.func_addr = entry;
                site.pc = addr;
                site.reg = cf.reg;
                site.kind = "jr_non_ra";
                result.indirect_jumps.push_back(std::move(site));
                result.exit_types.insert("indirect_jump_recorded_for_1d");

                // --- Jump table resolution ---
                // Scan backward from jr to detect the pattern:
                //   SLTIU (count), SLL, LUI, ADDU, LW, jr
                // If found, read the table entries from ROM and push each
                // case target onto the work queue so the case body code
                // is included in this function's instruction set.
                {
                    uint32_t jr_rs = cf.reg;
                    uint32_t lw_base = 0xFF; int32_t lw_off = 0;
                    uint32_t ac[2] = {0xFF, 0xFF}; uint32_t lui_v = 0;
                    int16_t  av[2] = {0, 0}; bool fa[2] = {false, false};
                    bool fl = false; uint32_t tc = 0;

                    for (int b = 1; b <= 40; b++) {
                        uint32_t sa = addr - (uint32_t)(b * 4);
                        if (sa < entry) break;
                        if (!in_bounds(sa)) break;
                        uint32_t si = fetch(sa);
                        uint32_t s_op = (si >> 26) & 0x3F;
                        uint32_t s_rs = (si >> 21) & 0x1F;
                        uint32_t s_rt = (si >> 16) & 0x1F;
                        uint32_t s_rd = (si >> 11) & 0x1F;
                        uint32_t s_fn = si & 0x3F;

                        if (s_op == 0x23 && s_rt == jr_rs && lw_base == 0xFF) {
                            lw_base = s_rs; lw_off = (int32_t)(int16_t)(si & 0xFFFF); continue;
                        }
                        if (s_op == 0x00 && s_fn == 0x21 && s_rd == lw_base &&
                            lw_base != 0xFF && ac[0] == 0xFF) {
                            ac[0] = s_rs; ac[1] = s_rt; continue;
                        }
                        if (s_op == 0x09 && ac[0] != 0xFF) {
                            for (int c = 0; c < 2; c++) {
                                if (!fa[c] && ac[c] != 0xFF && s_rs == ac[c] && s_rt == ac[c]) {
                                    av[c] = (int16_t)(si & 0xFFFF); fa[c] = true; break;
                                }
                            }
                            continue;
                        }
                        if (s_op == 0x0F && ac[0] != 0xFF && !fl) {
                            for (int c = 0; c < 2; c++) {
                                if (ac[c] != 0xFF && s_rt == ac[c]) {
                                    lui_v = ((uint32_t)(si & 0xFFFF)) << 16;
                                    if (!fa[c]) av[c] = 0;
                                    av[0] = av[c]; fa[0] = fa[c]; fl = true; break;
                                }
                            }
                            continue;
                        }
                        if (s_op == 0x0B && tc == 0) { tc = si & 0xFFFF; continue; }
                        if (fl && tc != 0) break;
                    }

                    if (fl && tc > 0 && tc < 512) {
                        uint32_t tb = (lui_v + (fa[0] ? (uint32_t)(int32_t)av[0] : 0u))
                                    + (uint32_t)lw_off;
                        // tb is a RAM address; map to ROM for reading.
                        uint32_t rom_tb = ram_alias_to_rom(tb);

                        for (uint32_t i = 0; i < tc; i++) {
                            uint32_t taddr = rom_tb + i * 4;
                            if (!in_bounds(taddr)) continue;
                            uint32_t tval = fetch(taddr);
                            // tval is a RAM address; map to ROM.
                            uint32_t rom_target = ram_alias_to_rom(tval);

                            if (in_bounds(rom_target)) {
                                work.push(rom_target);
                                block_leader_set.insert(rom_target);
                            }
                        }
                        // Also push fall-through after delay slot (code between
                        // jr and the first case target may be dead, but including
                        // it ensures no gaps in the generated function).
                        // EXCEPT when the table itself sits right after the delay
                        // slot (hand-written asm idiom: OpenBIOS fastMemset puts
                        // jumptable1 at jr+8). Walking the table words as code
                        // poisons the whole function with a bogus unsupported
                        // instruction and the emitter skips it entirely.
                        uint32_t after_delay = addr + 8;
                        if (in_bounds(after_delay) && after_delay != rom_tb) {
                            work.push(after_delay);
                            block_leader_set.insert(after_delay);
                        }
                    }
                }
                break;
            }

            case CFKind::JALR: {
                // Indirect call. Visit delay slot, fall through to addr+8.
                // Record as indirect jump AND as edge (target unknown).
                if (in_bounds(delay_addr) && !visited.count(delay_addr)) {
                    visited.insert(delay_addr);
                    uint32_t delay_raw = fetch(delay_addr);
                    PSXRecomp::DecodedInstruction dd = PSXRecomp::MipsDecoder::decode(delay_raw, delay_addr);
                    TranslateResult dtr = StrictTranslator::translate(dd);
                    if (!dtr.supported) {
                        UnsupportedInstr u;
                        u.address = delay_addr;
                        u.raw = delay_raw;
                        u.reason = fmt::format("delay slot of jalr at 0x{:08X}: {}", addr, dtr.fail_reason);
                        result.unsupported.push_back(std::move(u));
                    }
                }
                // Fall through (jalr returns).
                if (in_bounds(addr + 8)) {
                    work.push(addr + 8);
                    block_leader_set.insert(addr + 8);
                }
                IndirectJumpSite site;
                site.func_addr = entry;
                site.pc = addr;
                site.reg = cf.reg;
                site.kind = "jalr";
                result.indirect_jumps.push_back(std::move(site));
                break;
            }

            case CFKind::Syscall:
            case CFKind::Break:
                // Fall through (BIOS uses these as in-line traps that return).
                if (in_bounds(addr + 4)) {
                    work.push(addr + 4);
                }
                break;

            case CFKind::RFE:
                // Return from exception. No fall-through.
                result.exit_types.insert("rfe");
                break;
        }
    }

    // Sort visited instructions by address.
    for (uint32_t addr : visited) {
        uint32_t raw = fetch(addr);
        result.instructions.emplace_back(addr, raw);
    }
    std::sort(result.instructions.begin(), result.instructions.end());

    // Phase 1d enrichment: capture context window and classify each
    // indirect jump site. We read the ~16 linear instructions preceding
    // the jump PC directly from ROM (not from the visited set), since the
    // value tracker needs the linear predecessor chain regardless of BFS
    // reachability.
    for (auto& site : result.indirect_jumps) {
        // Context window: up to 16 instructions before the jump PC.
        constexpr int kContextSize = 16;
        for (int i = kContextSize; i >= 1; --i) {
            uint32_t ctx_addr = site.pc - (i * 4);
            if (ctx_addr >= base_addr && ctx_addr <= rom_end) {
                uint32_t ctx_raw = fetch(ctx_addr);
                PSXRecomp::DecodedInstruction ctx_d =
                    PSXRecomp::MipsDecoder::decode(ctx_raw, ctx_addr);
                PrecedingInstr pi;
                pi.address = ctx_addr;
                pi.raw = ctx_raw;
                pi.mnemonic = ctx_d.mnemonic ? ctx_d.mnemonic : "UNKNOWN";
                site.context_window.push_back(std::move(pi));
            }
        }

        // Classification based on pattern analysis.
        // Pattern 1: A0/B0/C0 dispatch stub.
        //   3 instructions: li reg, {0xA0|0xB0|0xC0}; jr reg; li t1, <index>
        //   The jr is the indirect jump. Check if func is 3 instructions
        //   and the preceding instruction loads 0xA0, 0xB0, or 0xC0.
        bool is_dispatch_stub = false;
        if (site.kind == "jr_non_ra" && !site.context_window.empty()) {
            // Look at the instruction immediately before the jr.
            // For a 3-instr stub, the function entry is at pc-4 (li reg, addr).
            uint32_t prev_addr = site.pc - 4;
            if (prev_addr >= base_addr && prev_addr <= rom_end) {
                uint32_t prev_raw = fetch(prev_addr);
                // Check for "li reg, 0xA0/0xB0/0xC0" patterns.
                // LUI + ORI or ADDIU $zero patterns. The simplest: ADDIU $reg, $zero, imm
                // where imm is 0xA0, 0xB0, or 0xC0.
                uint8_t prev_op = (prev_raw >> 26) & 0x3F;
                uint8_t prev_rs = (prev_raw >> 21) & 0x1F;
                int16_t prev_simm = static_cast<int16_t>(prev_raw & 0xFFFF);
                if (prev_op == 0x09 && prev_rs == 0) { // ADDIU rd, $zero, imm
                    uint16_t val = static_cast<uint16_t>(prev_simm);
                    if (val == 0xA0 || val == 0xB0 || val == 0xC0) {
                        is_dispatch_stub = true;
                    }
                }
                // Also check ORI $reg, $zero, imm
                if (prev_op == 0x0D && prev_rs == 0) { // ORI rd, $zero, imm
                    uint16_t val = prev_raw & 0xFFFF;
                    if (val == 0xA0 || val == 0xB0 || val == 0xC0) {
                        is_dispatch_stub = true;
                    }
                }
            }
        }

        if (is_dispatch_stub) {
            site.classification = "a0_b0_c0_dispatch";
        } else if (site.kind == "jalr") {
            site.classification = "computed_call";
        } else if (site.kind == "jr_non_ra") {
            // jr to a non-$ra register that isn't a dispatch stub.
            // Could be a jump table or a computed tail call.
            // Check if the register was loaded from a table (lw from base+index).
            bool has_lw_to_reg = false;
            for (const auto& pi : site.context_window) {
                uint8_t pi_op = (pi.raw >> 26) & 0x3F;
                uint8_t pi_rt = (pi.raw >> 16) & 0x1F;
                if (pi_op == 0x23 && pi_rt == site.reg) { // LW into the jr register
                    has_lw_to_reg = true;
                    break;
                }
            }
            if (has_lw_to_reg) {
                site.classification = "jump_table";
            } else {
                site.classification = "computed_tail_call";
            }
        } else {
            site.classification = "unknown";
        }
    }

    // Compute end address.
    if (!result.instructions.empty()) {
        result.end_addr = result.instructions.back().first;
    } else {
        result.end_addr = entry;
    }

    // Build basic block info from the sorted instruction list and leader set.
    // A block starts at a leader and runs until the next leader or end.
    std::vector<uint32_t> leaders(block_leader_set.begin(), block_leader_set.end());
    std::sort(leaders.begin(), leaders.end());

    // Build a set of visited addresses for fast lookup.
    std::set<uint32_t> visited_set(visited.begin(), visited.end());

    for (size_t i = 0; i < leaders.size(); ++i) {
        uint32_t block_start = leaders[i];
        if (!visited_set.count(block_start)) continue; // unreachable leader

        uint32_t next_leader = (i + 1 < leaders.size()) ? leaders[i + 1] : (result.end_addr + 4);

        BasicBlockInfo bb;
        bb.start_addr = block_start;
        bb.instruction_count = 0;
        bb.end_addr = block_start;
        bb.branch_target = 0;
        bb.termination = "fall_through";

        // Count instructions in this block.
        for (const auto& [iaddr, iraw] : result.instructions) {
            if (iaddr >= block_start && iaddr < next_leader) {
                bb.instruction_count++;
                bb.end_addr = iaddr;

                // Check if this is the last instruction in the block.
                CFInfo cf = classify_control_flow(iraw, iaddr);
                // Only record termination for the block's last visited instruction
                // before the next leader.
                bool is_last_before_next = true;
                for (const auto& [jaddr, jraw] : result.instructions) {
                    if (jaddr > iaddr && jaddr < next_leader) {
                        is_last_before_next = false;
                        break;
                    }
                }
                if (is_last_before_next) {
                    switch (cf.kind) {
                        case CFKind::CondBranch:
                            bb.termination = "branch";
                            bb.branch_target = cf.target;
                            break;
                        case CFKind::Jump:
                            if (cf.target != 0 && in_bounds(cf.target)) {
                                bb.termination = "j_intra";
                            } else {
                                bb.termination = "j_out";
                            }
                            bb.branch_target = cf.target;
                            break;
                        case CFKind::Call:
                            bb.termination = "jal";
                            bb.branch_target = cf.target;
                            break;
                        case CFKind::JR_RA:
                            bb.termination = "jr_ra";
                            break;
                        case CFKind::JR_Indirect:
                            bb.termination = "jr_indirect";
                            break;
                        case CFKind::JALR:
                            bb.termination = "jalr";
                            break;
                        case CFKind::Syscall:
                            bb.termination = "syscall";
                            break;
                        case CFKind::Break:
                            bb.termination = "break";
                            break;
                        case CFKind::RFE:
                            bb.termination = "rfe";
                            break;
                        case CFKind::Normal:
                            bb.termination = "fall_through";
                            break;
                    }
                }
            }
        }

        if (bb.instruction_count > 0) {
            result.blocks.push_back(std::move(bb));
        }
    }

    return result;
}

// ---------------------------------------------------------------------------
// Main discovery pipeline
// ---------------------------------------------------------------------------

DiscoveryResult FunctionDiscovery::discover(
    const std::vector<uint8_t>& rom,
    uint32_t                    base_addr,
    uint32_t                    rom_end,
    const std::vector<Seed>&    seeds)
{
    // Sorted set of all known function entries (by address). Persists across
    // closure rounds (grows monotonically; the loop below re-discovers with
    // the enlarged entry set each round).
    std::set<uint32_t> known_entries;
    // Map from entry address to lineage string.
    std::map<uint32_t, std::string> lineage_map;

    // Seed the entry set.
    for (const auto& seed : seeds) {
        if (seed.address < base_addr || seed.address > rom_end) {
            throw std::runtime_error(fmt::format(
                "FunctionDiscovery: seed address 0x{:08X} ({}) is outside ROM range "
                "[0x{:08X}, 0x{:08X}]",
                seed.address, seed.label, base_addr, rom_end));
        }
        if (!known_entries.count(seed.address)) {
            known_entries.insert(seed.address);
            lineage_map[seed.address] = seed.label;
        }
    }

    // Branch-target dispatchability closure. A conditional branch or direct J
    // can escape its function's walk range when seeds truncate the function
    // into fragments (OpenBIOS cdromRead is split by jump-table code_ptr
    // seeds; its `beq ,,0xBFC1F3F8` lands past the fragment's cap in bytes no
    // function walks). The emitter publishes every such target
    // (`cpu->pc = target; return`), so each one MUST resolve to a dispatch
    // key: either an address inside some walked function (the emitter's
    // cross-target continuation injection covers that) or a function entry.
    // An escaping target covered by NO function's instruction set would be a
    // guaranteed runtime unknown-dispatch — promote it to a new entry and
    // re-discover, to fixpoint so promoted fragments' own escapes close too.
    // (The loop body below is deliberately NOT re-indented, to keep the
    // pre-existing discovery pass reviewable as an unchanged block.)
    for (int closure_round = 0; ; closure_round++) {
    if (closure_round > 64) {
        throw std::runtime_error(
            "FunctionDiscovery: branch-target closure did not converge in 64 "
            "rounds — runaway promotion (data walked as code?)");
    }

    DiscoveryResult result;
    result.ok = true;
    // Set of normalized addresses to detect duplicates.
    std::set<uint32_t> normalized_set;
    // Every instruction address walked this round (second pass), and every
    // escaping direct branch/J target seen — the closure inputs.
    std::set<uint32_t> closure_covered;
    std::set<uint32_t> closure_escapes;

    // Worklist of entries to process.
    std::queue<uint32_t> worklist;
    for (uint32_t e : known_entries) {
        worklist.push(e);
    }

    // Phase 1: collect all function entries transitively before doing full walks.
    // This ensures hard_caps are correct when we do the final walk.
    //
    // We do a lightweight scan: for each function, BFS to find all JAL targets
    // and add them to known_entries. Then we walk again with proper boundaries.
    //
    // Actually, we do a single iterative pass. When we discover a new JAL
    // target, we add it to known_entries and the worklist. Functions already
    // processed may have used a too-large hard_cap, but we re-walk them in a
    // second pass with correct caps.

    // First pass: discover all function entries.
    std::set<uint32_t> first_pass_done;
    while (!worklist.empty()) {
        uint32_t entry = worklist.front();
        worklist.pop();

        if (first_pass_done.count(entry)) continue;
        first_pass_done.insert(entry);

        // Compute hard_cap: next known entry after this one.
        auto it = known_entries.upper_bound(entry);
        uint32_t hard_cap = (it != known_entries.end()) ? *it : (rom_end + 1);

        // Quick scan: just walk instructions and find JAL targets.
        // We use the full BFS walk since we need it anyway for validation.
        SingleFunctionResult sfr = walk_function(rom, base_addr, rom_end, entry, hard_cap, lineage_map[entry]);

        // If unsupported instructions found, record and mark failure.
        for (auto& u : sfr.unsupported) {
            result.unsupported.push_back(std::move(u));
            result.ok = false;
        }

        // Discover new function entries from JAL targets.
        for (const auto& edge : sfr.edges) {
            uint32_t callee = edge.callee_addr;
            if (edge.in_rom && !known_entries.count(callee)) {
                known_entries.insert(callee);
                lineage_map[callee] = fmt::format("{} -> jal at 0x{:08X}",
                    lineage_map[entry], edge.caller_pc);
                worklist.push(callee);
            }
        }
    }

    // Second pass: walk every discovered function with correct hard_caps.
    // The first pass may have walked some functions with incorrect caps
    // (because later-discovered entries weren't known yet). Re-walk all.
    std::vector<uint32_t> all_entries(known_entries.begin(), known_entries.end());
    std::sort(all_entries.begin(), all_entries.end());

    for (size_t i = 0; i < all_entries.size(); ++i) {
        uint32_t entry = all_entries[i];
        uint32_t hard_cap = (i + 1 < all_entries.size()) ? all_entries[i + 1] : (rom_end + 1);
        std::string lineage = lineage_map[entry];

        SingleFunctionResult sfr = walk_function(rom, base_addr, rom_end, entry, hard_cap, lineage);

        // Check for unsupported (should be same as first pass, but verify).
        for (auto& u : sfr.unsupported) {
            result.unsupported.push_back(std::move(u));
            result.ok = false;
        }

        // Check normalized address uniqueness.
        uint32_t normalized = normalize_address(entry);
        if (normalized_set.count(normalized)) {
            throw std::runtime_error(fmt::format(
                "FunctionDiscovery: duplicate normalized address 0x{:08X} "
                "(entry 0x{:08X}). This violates Phase 1c constraints.",
                normalized, entry));
        }
        normalized_set.insert(normalized);

        // Build DiscoveredFunction.
        DiscoveredFunction func;
        func.entry_addr = entry;
        func.normalized_addr = normalized;
        func.end_addr = sfr.end_addr;
        func.instruction_count = static_cast<uint32_t>(sfr.instructions.size());
        func.discovered_by = lineage;

        // Determine termination reason.
        if (sfr.exit_types.empty()) {
            func.termination_reason = "no_exit_found";
        } else if (sfr.exit_types.size() == 1) {
            func.termination_reason = *sfr.exit_types.begin();
        } else {
            // Multiple exit types. Compose a summary.
            func.termination_reason = "mixed";
        }

        // Block leaders.
        for (const auto& bb : sfr.blocks) {
            func.block_leaders.push_back(bb.start_addr);
        }
        std::sort(func.block_leaders.begin(), func.block_leaders.end());

        result.functions.push_back(std::move(func));

        // Collect edges.
        for (auto& edge : sfr.edges) {
            result.edges.push_back(std::move(edge));
        }

        // Collect indirect jumps.
        for (auto& ij : sfr.indirect_jumps) {
            result.indirect_jumps.push_back(std::move(ij));
        }

        // Update opcode histogram.
        for (const auto& [iaddr, iraw] : sfr.instructions) {
            PSXRecomp::DecodedInstruction d = PSXRecomp::MipsDecoder::decode(iraw, iaddr);
            const char* mnem = d.mnemonic ? d.mnemonic : "UNKNOWN";
            result.opcode_histogram[mnem]++;
        }

        result.total_instructions += static_cast<uint32_t>(sfr.instructions.size());

        // Closure inputs: what this round walked, and what escaped it.
        for (const auto& [iaddr, iraw] : sfr.instructions) {
            closure_covered.insert(iaddr);
        }
        for (uint32_t t : sfr.escaping_targets) {
            closure_escapes.insert(t);
        }
    }

    result.total_functions = static_cast<uint32_t>(result.functions.size());
    result.total_edges = static_cast<uint32_t>(result.edges.size());
    result.total_indirect_jumps = static_cast<uint32_t>(result.indirect_jumps.size());

    // Dispatchability closure check: any escaping direct target that no
    // function's instruction set covers becomes a new entry; re-discover.
    // (Targets covered by another function are fine — the emitter's
    // cross-function continuation injection gives them dispatch keys.)
    std::vector<uint32_t> closure_promote;
    for (uint32_t t : closure_escapes) {
        if (!closure_covered.count(t) && !known_entries.count(t)) {
            closure_promote.push_back(t);
        }
    }
    std::fprintf(stdout,
        "FunctionDiscovery: closure round %d: escapes=%zu covered=%zu "
        "entries=%zu promote=%zu\n",
        closure_round, closure_escapes.size(), closure_covered.size(),
        known_entries.size(), closure_promote.size());
    for (uint32_t t : closure_promote) {
        std::fprintf(stdout,
            "FunctionDiscovery:   promoting uncovered escaping target 0x%08X\n", t);
    }
    // NOTE: iterate even when result.ok is false — unsupported instructions in
    // unrelated walks (data-as-code seeds) are tolerated by the emitter (it
    // skips those functions) and must not disable the closure.
    if (closure_promote.empty()) {
        return result;
    }
    for (uint32_t t : closure_promote) {
        known_entries.insert(t);
        lineage_map[t] = fmt::format(
            "branch_closure: uncovered escaping branch/J target (round {})",
            closure_round);
    }
    } // closure_round
}

} // namespace PSXRecompV4
