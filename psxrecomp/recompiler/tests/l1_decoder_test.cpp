/*
 * L1 Decoder Conformance Test
 *
 * Compares MipsDecoder::decode() mnemonic output against Rabbitizer
 * (trusted MIPS disassembler) for every instruction word in the BIOS
 * ROM's known code regions.
 *
 * Usage:
 *   l1_decoder_test [--rom PATH] [-v|--verbose] [--log-dir DIR]
 *
 * Exit codes:
 *   0  all instructions match
 *   1  at least one mismatch
 *   2  usage / I/O error
 */

#include <cstdio>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include <map>
#include <algorithm>
#include <fstream>

#include "mips_decoder.h"
#include "rabbitizer.hpp"
#include "instructions/InstructionR3000GTE.hpp"
#include "common/RabbitizerConfig.h"
#include "fmt/format.h"

// ── BIOS code regions (from Ghidra analysis of SCPH1001.BIN) ────────────

struct CodeRegion {
    uint32_t rom_start;   // byte offset in ROM file
    uint32_t rom_end;     // exclusive
    uint32_t vaddr_base;  // virtual address of first byte
    const char* name;
};

static const CodeRegion kRegions[] = {
    { 0x00000, 0x0DC60, 0xBFC00000, "Boot"   },
    { 0x10000, 0x16760, 0xBFC10000, "Kernel" },
    { 0x18000, 0x42800, 0xBFC18000, "Shell"  },
};

// ── Bucket for failure aggregation ──────────────────────────────────────

struct Bucket {
    std::string key;         // "oracle_mnem -> our_mnem"
    unsigned    count = 0;
    uint32_t    first_addr = 0;
    uint32_t    first_word = 0;
};

// ── Helpers ─────────────────────────────────────────────────────────────

static std::string to_lower(const std::string& s) {
    std::string out;
    out.reserve(s.size());
    for (char c : s)
        out += (c >= 'A' && c <= 'Z') ? static_cast<char>(c - 'A' + 'a') : c;
    return out;
}

// Is this a COP2 GTE command? (opcode=0x12, CO bit=bit25 set)
static bool is_gte_command(uint32_t word) {
    return ((word >> 26) & 0x3F) == 0x12 && ((word >> 25) & 1);
}

// Get oracle mnemonic via the right Rabbitizer class
static std::string oracle_mnemonic(uint32_t word, uint32_t addr) {
    if (is_gte_command(word)) {
        rabbitizer::InstructionR3000GTE insn(word, addr);
        return to_lower(insn.getOpcodeName());
    }
    rabbitizer::InstructionCpu insn(word, addr);
    return to_lower(insn.getOpcodeName());
}

// ── main ────────────────────────────────────────────────────────────────

int main(int argc, char** argv) {
    const char* rom_path = "bios/SCPH1001.BIN";
    bool verbose = false;
    const char* log_dir = nullptr;

    for (int i = 1; i < argc; i++) {
        if ((std::strcmp(argv[i], "--rom") == 0) && i + 1 < argc)
            rom_path = argv[++i];
        else if (std::strcmp(argv[i], "-v") == 0 || std::strcmp(argv[i], "--verbose") == 0)
            verbose = true;
        else if ((std::strcmp(argv[i], "--log-dir") == 0) && i + 1 < argc)
            log_dir = argv[++i];
        else if (argv[i][0] != '-')
            rom_path = argv[i];
    }

    // ── Configure Rabbitizer ────────────────────────────────────────────
    // Disable pseudo-instructions so Rabbitizer reports the actual opcode
    // (e.g. "or" not "move", "beq" not "beqz").
    RabbitizerConfig_Cfg.pseudos.enablePseudos = false;

    // ── Load ROM ────────────────────────────────────────────────────────
    std::ifstream f(rom_path, std::ios::binary | std::ios::ate);
    if (!f) {
        fmt::print(stderr, "l1: cannot open {}\n", rom_path);
        return 2;
    }
    auto rom_size = static_cast<size_t>(f.tellg());
    f.seekg(0);
    std::vector<uint8_t> rom(rom_size);
    f.read(reinterpret_cast<char*>(rom.data()), static_cast<std::streamsize>(rom_size));
    f.close();

    if (rom_size != 524288) {
        fmt::print(stderr, "l1: expected 524288 bytes, got {}\n", rom_size);
        return 2;
    }

    // ── Walk code regions ───────────────────────────────────────────────
    unsigned total = 0, pass = 0, fail = 0;
    std::map<std::string, Bucket> buckets;

    for (const auto& region : kRegions) {
        unsigned region_total = 0, region_pass = 0;

        for (uint32_t off = region.rom_start; off < region.rom_end; off += 4) {
            uint32_t word = static_cast<uint32_t>(rom[off])
                          | (static_cast<uint32_t>(rom[off + 1]) << 8)
                          | (static_cast<uint32_t>(rom[off + 2]) << 16)
                          | (static_cast<uint32_t>(rom[off + 3]) << 24);
            uint32_t addr = region.vaddr_base + (off - region.rom_start);

            // Our decoder
            auto ours = PSXRecomp::MipsDecoder::decode(word, addr);
            std::string our_mnem = to_lower(ours.mnemonic ? ours.mnemonic : "???");

            // Rabbitizer oracle
            std::string orc_mnem = oracle_mnemonic(word, addr);

            total++;
            region_total++;

            if (our_mnem == orc_mnem) {
                pass++;
                region_pass++;
            } else {
                fail++;
                std::string key = orc_mnem + " -> " + our_mnem;
                auto& b = buckets[key];
                if (b.count == 0) {
                    b.key = key;
                    b.first_addr = addr;
                    b.first_word = word;
                }
                b.count++;

                if (verbose) {
                    fmt::print("  FAIL 0x{:08X}: 0x{:08X}  oracle={:<12s} ours={}\n",
                               addr, word, orc_mnem, our_mnem);
                }
            }
        }

        fmt::print("{:<8s}: {}/{} ok\n", region.name, region_pass, region_total);
    }

    // ── Summary ─────────────────────────────────────────────────────────
    fmt::print("\nL1 decoder: {}/{} ok", pass, total);
    if (fail > 0)
        fmt::print(" ({} failures)", fail);
    fmt::print("\n");

    // ── Bucket report ───────────────────────────────────────────────────
    if (!buckets.empty()) {
        std::vector<Bucket> sorted;
        sorted.reserve(buckets.size());
        for (auto& [k, b] : buckets)
            sorted.push_back(b);
        std::sort(sorted.begin(), sorted.end(),
                  [](const Bucket& a, const Bucket& b) { return a.count > b.count; });

        fmt::print("\nFailure buckets (oracle -> ours):\n");
        for (size_t i = 0; i < sorted.size() && i < 40; i++) {
            fmt::print("  {:>6}  {:<40s}  first: 0x{:08X} [0x{:08X}]\n",
                       sorted[i].count, sorted[i].key,
                       sorted[i].first_addr, sorted[i].first_word);
        }

        // Optional log output
        if (log_dir) {
            std::string summary_path  = std::string(log_dir) + "/l1_summary.txt";
            std::string failures_path = std::string(log_dir) + "/l1_failures.log";

            if (FILE* sf = std::fopen(summary_path.c_str(), "w")) {
                std::fprintf(sf, "L1 decoder: %u/%u ok (%u failures)\n", pass, total, fail);
                std::fclose(sf);
            }
            if (FILE* ff = std::fopen(failures_path.c_str(), "w")) {
                for (const auto& b : sorted)
                    std::fprintf(ff, "%6u  %-40s  first: 0x%08X [0x%08X]\n",
                                 b.count, b.key.c_str(), b.first_addr, b.first_word);
                std::fclose(ff);
            }
        }
    }

    return fail > 0 ? 1 : 0;
}
