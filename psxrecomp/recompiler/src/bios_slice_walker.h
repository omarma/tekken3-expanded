// bios_slice_walker.h
// ----------------------------------------------------------------------------
// Phase 1a bounded linear walk of the BIOS reset vector.
//
// Walks instructions in strict 4-byte stride starting at `start_addr`.
// Stops when ANY of the following becomes true:
//   1. Current instruction is a terminator: JR / JALR / J / JAL / RFE.
//      (J/JAL added per Option A, 2026-04-06.)
//   2. Bytes consumed reach `max_bytes` (typically 4096).
// On terminator hit, the single delay-slot instruction following it is also
// translated and emitted (MIPS branch-delay semantics). The slice ends after
// the delay slot.
//
// The walker does NOT follow branches or jumps. Phase 1a is purely linear.
// Function discovery is Phase 1c work.

#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "strict_translator.h"

namespace PSXRecompV4 {

struct EmittedInstr {
    uint32_t    address;
    uint32_t    raw;
    std::string c_code;
    std::string comment;
};

struct UnsupportedEntry {
    uint32_t    address;
    uint32_t    raw;
    uint8_t     opcode_top6;
    std::string decoded_format;
    std::string reason;
};

struct WalkResult {
    bool                          ok = false;             // false if any unsupported
    std::vector<EmittedInstr>     emitted;                // in walker order (delay slot before terminator!)
    std::vector<UnsupportedEntry> unsupported;
    uint32_t                      start_addr = 0;
    uint32_t                      end_addr = 0;           // address of last instruction in slice (inclusive)
    uint32_t                      instruction_count = 0;
    std::string                   termination_reason;     // "j", "jal", "jr", "jalr", "rfe", "size_limit"
    uint32_t                      terminator_target = 0;  // for j/jal; 0 otherwise
    std::string                   termination_note;       // free-form, e.g. ERET->RFE substitution
};

class BiosSliceWalker {
public:
    // ROM is treated as a flat byte vector. base_addr is the virtual address of rom[0].
    static WalkResult walk(const std::vector<uint8_t>& rom,
                           uint32_t                    base_addr,
                           uint32_t                    start_addr,
                           uint32_t                    max_bytes);
};

} // namespace PSXRecompV4
