// bios_slice_walker.cpp — see header.

#include "bios_slice_walker.h"

#include <cstdint>
#include <stdexcept>
#include <string>

#include "fmt/format.h"
#include "mips_decoder.h"

namespace PSXRecompV4 {

namespace {

uint32_t read_u32_le(const std::vector<uint8_t>& rom, uint32_t offset) {
    if (offset + 3 >= rom.size()) {
        throw std::runtime_error(fmt::format(
            "BiosSliceWalker: read_u32_le out of range (offset=0x{:X}, rom_size=0x{:X})",
            offset, rom.size()));
    }
    return  static_cast<uint32_t>(rom[offset + 0])
         | (static_cast<uint32_t>(rom[offset + 1]) << 8)
         | (static_cast<uint32_t>(rom[offset + 2]) << 16)
         | (static_cast<uint32_t>(rom[offset + 3]) << 24);
}

const char* format_name(PSXRecomp::InstrFormat f) {
    switch (f) {
        case PSXRecomp::InstrFormat::R:       return "R";
        case PSXRecomp::InstrFormat::I:       return "I";
        case PSXRecomp::InstrFormat::J:       return "J";
        case PSXRecomp::InstrFormat::SPECIAL: return "SPECIAL";
        case PSXRecomp::InstrFormat::REGIMM:  return "REGIMM";
        case PSXRecomp::InstrFormat::COP0:    return "COP0";
        case PSXRecomp::InstrFormat::COP2:    return "COP2";
        case PSXRecomp::InstrFormat::UNKNOWN: return "UNKNOWN";
    }
    return "UNKNOWN";
}

void record_unsupported(WalkResult& result, const PSXRecomp::DecodedInstruction& d, const std::string& reason) {
    UnsupportedEntry e;
    e.address        = d.address;
    e.raw            = d.raw;
    e.opcode_top6    = static_cast<uint8_t>(d.opcode);
    e.decoded_format = format_name(d.format);
    e.reason         = reason;
    result.unsupported.push_back(std::move(e));
    result.ok = false;
}

} // namespace

WalkResult BiosSliceWalker::walk(const std::vector<uint8_t>& rom,
                                 uint32_t                    base_addr,
                                 uint32_t                    start_addr,
                                 uint32_t                    max_bytes) {
    WalkResult result;
    result.ok = true;
    result.start_addr = start_addr;

    if (start_addr < base_addr || start_addr >= base_addr + rom.size()) {
        throw std::runtime_error(fmt::format(
            "BiosSliceWalker: start_addr 0x{:08X} outside ROM [0x{:08X}, 0x{:08X})",
            start_addr, base_addr, base_addr + static_cast<uint32_t>(rom.size())));
    }

    const uint32_t walk_end = start_addr + max_bytes;  // exclusive

    uint32_t pc = start_addr;
    while (pc < walk_end) {
        // Bounds check both the current instruction and a possible delay slot fetch.
        if (pc + 4 > base_addr + rom.size()) {
            throw std::runtime_error(fmt::format(
                "BiosSliceWalker: walk fell off end of ROM at pc=0x{:08X}", pc));
        }

        const uint32_t offset = pc - base_addr;
        const uint32_t raw = read_u32_le(rom, offset);
        const PSXRecomp::DecodedInstruction d = PSXRecomp::MipsDecoder::decode(raw, pc);

        const TranslateResult tr = StrictTranslator::translate(d);

        if (!tr.supported) {
            record_unsupported(result, d, tr.fail_reason);
            // Continue walking so the unsupported list is COMPLETE in one pass.
            // Do NOT push to emitted (it would be incomplete/wrong).
            pc += 4;
            // Do not honor terminator semantics on a failed translation; the
            // unsupported entry already proves the slice is broken.
            continue;
        }

        if (tr.is_terminator) {
            // 1) Translate the delay-slot instruction.
            const uint32_t delay_pc = pc + 4;
            if (delay_pc + 4 > base_addr + rom.size()) {
                throw std::runtime_error(fmt::format(
                    "BiosSliceWalker: terminator at 0x{:08X} has no delay slot in ROM", pc));
            }
            const uint32_t delay_offset = delay_pc - base_addr;
            const uint32_t delay_raw = read_u32_le(rom, delay_offset);
            const PSXRecomp::DecodedInstruction delay_d =
                PSXRecomp::MipsDecoder::decode(delay_raw, delay_pc);
            const TranslateResult delay_tr = StrictTranslator::translate(delay_d);

            if (!delay_tr.supported) {
                record_unsupported(result, delay_d,
                    fmt::format("delay slot of terminator at 0x{:08X}: {}",
                                pc, delay_tr.fail_reason));
                pc += 8;
                continue;
            }
            if (delay_tr.is_terminator) {
                // Branch in delay slot of branch is illegal on R3000A. Fail loud.
                record_unsupported(result, delay_d,
                    fmt::format("delay slot of terminator at 0x{:08X} is itself a terminator (illegal on R3000A)", pc));
                pc += 8;
                continue;
            }

            // 1.5) If the terminator declared a pre-delay snapshot, emit it
            //      BEFORE the delay slot. This is used by conditional
            //      branches to capture rs/rt values into function-scope C
            //      locals so the branch condition (in tr.c_code, emitted
            //      after the delay slot) reads pre-delay state. The walker
            //      stays structurally the same — just one more EmittedInstr
            //      pushed when this string is non-empty. No control flow.
            if (!tr.pre_delay_code.empty()) {
                EmittedInstr ep;
                ep.address = pc;        // logically belongs to the branch
                ep.raw     = raw;
                ep.c_code  = tr.pre_delay_code;
                ep.comment = fmt::format("[pre-delay snapshot for 0x{:08X}] {}", pc, tr.comment);
                result.emitted.push_back(std::move(ep));
            }

            // 2) Emit delay slot (program order in C output: delay slot
            //    executes BEFORE control transfer in MIPS semantics — well, in
            //    parallel, but the C representation puts the side-effects of
            //    the delay slot before the PC update + return).
            EmittedInstr ed;
            ed.address = delay_pc;
            ed.raw = delay_raw;
            ed.c_code = delay_tr.c_code;
            ed.comment = fmt::format("[delay slot of 0x{:08X}] {}", pc, delay_tr.comment);
            result.emitted.push_back(std::move(ed));

            // 3) Emit terminator.
            EmittedInstr et;
            et.address = pc;
            et.raw = raw;
            et.c_code = tr.c_code;
            et.comment = tr.comment;
            result.emitted.push_back(std::move(et));

            result.end_addr = delay_pc;  // delay slot is the last addr in the slice
            result.instruction_count = static_cast<uint32_t>(result.emitted.size());
            result.termination_reason = tr.terminator_kind;
            result.terminator_target = tr.terminator_target;
            if (std::string(tr.terminator_kind) == "rfe") {
                result.termination_note =
                    "RFE; FIRST_MILESTONE.md listed ERET, substituted per session approval 2026-04-06 "
                    "(R3000A has no ERET)";
            }
            return result;
        }

        // Non-terminator: emit and advance.
        EmittedInstr ei;
        ei.address = pc;
        ei.raw = raw;
        ei.c_code = tr.c_code;
        ei.comment = tr.comment;
        result.emitted.push_back(std::move(ei));
        pc += 4;
    }

    // Walk hit max_bytes without seeing a terminator.
    if (result.emitted.empty()) {
        // Could happen only if every instruction was unsupported. ok is already false.
        result.end_addr = pc - 4;
        result.instruction_count = 0;
    } else {
        result.end_addr = result.emitted.back().address;
        result.instruction_count = static_cast<uint32_t>(result.emitted.size());
    }
    result.termination_reason = "size_limit";
    return result;
}

} // namespace PSXRecompV4
