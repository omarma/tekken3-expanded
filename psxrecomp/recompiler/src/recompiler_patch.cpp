#include "recompiler_patch.h"

#include <stdexcept>

#include "fmt/format.h"
#include "ps1_exe_parser.h"

namespace PSXRecompV4 {

namespace {

uint32_t apply_one_recompiler_patch(const RecompilerPatch& patch,
                                    uint32_t address,
                                    uint32_t observed,
                                    bool overlay_mode) {
    if (observed == patch.expected) return patch.replacement;
    if (overlay_mode) return observed;
    throw std::runtime_error(fmt::format(
        "recompiler patch '{}' expected 0x{:08X} at 0x{:08X}, found "
        "0x{:08X}; wrong game revision or stale patch",
        patch.id, patch.expected, address, observed));
}

} // namespace

uint32_t apply_recompiler_patch(const std::vector<RecompilerPatch>& patches,
                                uint32_t address,
                                uint32_t observed,
                                bool overlay_mode) {
    const uint32_t address_key = recompiler_patch_address_key(address);
    for (const auto& patch : patches) {
        if (recompiler_patch_address_key(patch.address) != address_key) continue;
        return apply_one_recompiler_patch(patch, address, observed, overlay_mode);
    }
    return observed;
}

void apply_recompiler_patches_to_executable(
    PSXRecomp::PS1Executable& executable,
    const std::vector<RecompilerPatch>& patches,
    bool overlay_mode) {
    const uint32_t load_key =
        recompiler_patch_address_key(executable.load_address());
    const uint64_t image_end =
        static_cast<uint64_t>(load_key) + executable.code_data.size();

    for (const auto& patch : patches) {
        const uint32_t patch_key = recompiler_patch_address_key(patch.address);
        if (patch_key < load_key || static_cast<uint64_t>(patch_key) + 4u > image_end) {
            continue; // The patch may target a different captured overlay image.
        }

        const size_t offset = static_cast<size_t>(patch_key - load_key);
        const uint32_t observed =
            static_cast<uint32_t>(executable.code_data[offset]) |
            (static_cast<uint32_t>(executable.code_data[offset + 1]) << 8) |
            (static_cast<uint32_t>(executable.code_data[offset + 2]) << 16) |
            (static_cast<uint32_t>(executable.code_data[offset + 3]) << 24);
        const uint32_t resolved = apply_one_recompiler_patch(
            patch, patch.address, observed, overlay_mode);
        if (resolved == observed) continue;

        executable.code_data[offset] = static_cast<uint8_t>(resolved);
        executable.code_data[offset + 1] = static_cast<uint8_t>(resolved >> 8);
        executable.code_data[offset + 2] = static_cast<uint8_t>(resolved >> 16);
        executable.code_data[offset + 3] = static_cast<uint8_t>(resolved >> 24);
    }
}

void merge_recompiler_patches(std::vector<RecompilerPatch>& destination,
                              const std::vector<RecompilerPatch>& incoming) {
    for (const auto& candidate : incoming) {
        bool repeated = false;
        for (const auto& existing : destination) {
            const bool same_id = existing.id == candidate.id;
            const bool same_address =
                recompiler_patch_address_key(existing.address) ==
                recompiler_patch_address_key(candidate.address);
            if (!same_id && !same_address) continue;

            const bool identical = same_id && same_address &&
                existing.expected == candidate.expected &&
                existing.replacement == candidate.replacement &&
                existing.note == candidate.note;
            if (!identical) {
                throw std::runtime_error(fmt::format(
                    "conflicting recompiler patches '{}' at 0x{:08X} and '{}' "
                    "at 0x{:08X}",
                    existing.id, existing.address, candidate.id,
                    candidate.address));
            }
            repeated = true;
            break;
        }
        if (!repeated) destination.push_back(candidate);
    }
}

} // namespace PSXRecompV4
