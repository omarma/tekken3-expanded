#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace PSXRecomp {
class PS1Executable;
}

namespace PSXRecompV4 {

// One game-owned, opcode-verified instruction replacement. Addresses use PSX
// virtual-address spelling in TOML but compare by their 29-bit physical key, so
// KUSEG/KSEG0/KSEG1 aliases refer to the same instruction site.
struct RecompilerPatch {
    std::string id;
    uint32_t address = 0;
    uint32_t expected = 0;
    uint32_t replacement = 0;
    std::string note;
};

inline uint32_t recompiler_patch_address_key(uint32_t address) {
    return address & 0x1FFFFFFFu;
}

// Apply the patch targeting address, if any. A main-EXE guard mismatch throws;
// an overlay mismatch is an expected different variant and leaves the observed
// instruction unchanged.
uint32_t apply_recompiler_patch(const std::vector<RecompilerPatch>& patches,
                                uint32_t address,
                                uint32_t observed,
                                bool overlay_mode);

// Apply every in-range patch directly to the parsed image before discovery and
// CFG analysis. This keeps control-flow replacements and emitted code in sync.
void apply_recompiler_patches_to_executable(
    PSXRecomp::PS1Executable& executable,
    const std::vector<RecompilerPatch>& patches,
    bool overlay_mode);

// Merge patches received through --config and --ws-config. Byte-identical
// repeats are deduplicated; conflicting IDs or aliased addresses throw.
void merge_recompiler_patches(std::vector<RecompilerPatch>& destination,
                              const std::vector<RecompilerPatch>& incoming);

} // namespace PSXRecompV4
