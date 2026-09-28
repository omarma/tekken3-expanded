// function_discovery.h
// ----------------------------------------------------------------------------
// Phase 1c: deterministic function discovery pipeline.
//
// Given a set of seed addresses and a flat ROM image, discovers functions
// transitively via direct JAL targets. Each function is walked exactly
// once using BFS over basic blocks. Emits structured artifacts:
//   - function_manifest.json   (per-function metadata)
//   - function_edges.json      (caller->callee edges)
//   - discovery_run.log.json   (structured run statistics)
//
// Design constraints (from PLAN.md Phase 1c):
//   - Every seed must come from an explicit seed file.
//   - Functions are identified by normalized address (addr & 0x1FFFFFFF).
//   - No function may be emitted twice under the same normalized address.
//   - Indirect jumps (jr non-$ra, jalr) terminate the walk for that path
//     and are recorded for Phase 1d. They are NOT resolved.
//   - Every instruction is validated through StrictTranslator. An
//     unsupported opcode is a hard failure.
//   - Direct JAL targets outside the ROM range are recorded as edges
//     but NOT walked (they may be RAM-side copies; Phase 1e handles that).

#pragma once

#include <cstdint>
#include <map>
#include <set>
#include <string>
#include <vector>

#include "strict_translator.h"

namespace PSXRecompV4 {

struct Seed {
    uint32_t    address;
    std::string label;
    std::string rationale;
};

struct BasicBlockInfo {
    uint32_t start_addr;
    uint32_t end_addr;          // address of last instruction (inclusive)
    uint32_t instruction_count;
    std::string termination;    // "fall_through", "jr_ra", "jr_indirect", "jalr",
                                // "j_intra", "j_out", "branch", "jal", "rfe",
                                // "syscall", "break"
    uint32_t branch_target;     // target address for branches/jumps, 0 if N/A
};

struct DiscoveredFunction {
    uint32_t    entry_addr;
    uint32_t    normalized_addr;    // entry_addr & 0x1FFFFFFF
    uint32_t    end_addr;           // highest instruction address (inclusive)
    uint32_t    instruction_count;
    std::string termination_reason; // primary termination: "jr_ra", "rfe",
                                    // "j_out_of_function",
                                    // "indirect_jump_recorded_for_1d",
                                    // "mixed" (multiple exit types)
    std::string discovered_by;      // seed lineage description
    std::vector<uint32_t> block_leaders;  // sorted basic block start addresses
};

struct CallEdge {
    uint32_t caller_func;   // entry address of calling function
    uint32_t caller_pc;     // PC of the JAL instruction
    uint32_t callee_addr;   // target of the JAL
    bool     in_rom;        // true if callee_addr is within ROM range
};

struct PrecedingInstr {
    uint32_t    address;
    uint32_t    raw;
    std::string mnemonic;
};

struct IndirectJumpSite {
    uint32_t    func_addr;      // entry address of containing function
    uint32_t    pc;             // PC of the indirect jump
    uint8_t     reg;            // register used (e.g. $t0 for jr $t0)
    std::string kind;           // "jr_non_ra", "jalr"
    std::string classification; // "a0_b0_c0_dispatch", "computed_tail_call",
                                // "computed_call", "jump_table", "unknown"
    std::vector<PrecedingInstr> context_window; // ~16 instructions before the jump
};

struct UnsupportedInstr {
    uint32_t    address;
    uint32_t    raw;
    std::string reason;
};

struct DiscoveryResult {
    bool ok = false;

    std::vector<DiscoveredFunction> functions;
    std::vector<CallEdge>           edges;
    std::vector<IndirectJumpSite>   indirect_jumps;
    std::vector<UnsupportedInstr>   unsupported;

    // Statistics
    uint32_t total_instructions = 0;
    uint32_t total_functions = 0;
    uint32_t total_edges = 0;
    uint32_t total_indirect_jumps = 0;

    // Opcode histogram: mnemonic -> count
    std::map<std::string, uint32_t> opcode_histogram;
};

class BiosAddressModel;

class FunctionDiscovery {
public:
    // Set the active BIOS address model BEFORE any discover/walk call. The
    // profile-derived model (bios_address_model.h) is the single source of
    // truth for the relocation windows discovery follows J/JAL targets
    // through; there is no built-in default. Must outlive the run.
    static void set_address_model(const BiosAddressModel* m);

    // Discover functions starting from the given seeds.
    // rom: flat BIOS image bytes
    // base_addr: virtual address of rom[0] (e.g. 0xBFC00000)
    // rom_end: last valid address inclusive (e.g. 0xBFC7FFFF)
    // seeds: explicit seed addresses with labels
    static DiscoveryResult discover(
        const std::vector<uint8_t>& rom,
        uint32_t                    base_addr,
        uint32_t                    rom_end,
        const std::vector<Seed>&    seeds);

    // Walk a single function via BFS. Returns the set of visited
    // (addr, raw) pairs, basic block info, edges, and indirect jump sites.
    // Made public for Phase 2 full function emitter.
    struct SingleFunctionResult {
        std::vector<std::pair<uint32_t, uint32_t>> instructions; // (addr, raw) sorted
        std::vector<BasicBlockInfo>                blocks;
        std::vector<CallEdge>                      edges;
        std::vector<IndirectJumpSite>              indirect_jumps;
        std::vector<UnsupportedInstr>              unsupported;
        std::set<std::string>                      exit_types;   // "jr_ra", "rfe", etc.
        uint32_t                                   end_addr = 0;
        // Direct branch/J targets that escape [entry, hard_cap) but land in
        // ROM. Input to discover()'s dispatchability closure: every published
        // target must resolve to a dispatch key, so an escaping target covered
        // by no function's instruction set becomes a new entry.
        std::set<uint32_t>                         escaping_targets;
    };

    static SingleFunctionResult walk_function(
        const std::vector<uint8_t>& rom,
        uint32_t                    base_addr,
        uint32_t                    rom_end,
        uint32_t                    entry,
        uint32_t                    hard_cap,
        const std::string&          lineage);

private:
    static uint32_t read_u32_le(const std::vector<uint8_t>& rom, uint32_t offset);

    // Control flow classification for a raw instruction at a given address.
    enum class CFKind {
        Normal,         // falls through
        CondBranch,     // conditional branch (BEQ/BNE/BLEZ/BGTZ/BLTZ/BGEZ/BLTZAL/BGEZAL)
        Jump,           // unconditional J
        Call,           // JAL
        JR_RA,          // jr $ra (function return)
        JR_Indirect,    // jr $reg (not $ra)
        JALR,           // jalr (indirect call)
        Syscall,        // SYSCALL
        Break,          // BREAK
        RFE,            // return from exception
    };

    struct CFInfo {
        CFKind   kind;
        uint32_t target;    // computed target for CondBranch/Jump/Call, 0 otherwise
        uint8_t  reg;       // register for JR_Indirect/JALR
    };

    static CFInfo classify_control_flow(uint32_t raw, uint32_t addr);
};

} // namespace PSXRecompV4
