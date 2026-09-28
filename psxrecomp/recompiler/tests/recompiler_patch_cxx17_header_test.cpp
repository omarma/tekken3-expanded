#include "recompiler_patch.h"

#include <vector>

int main() {
    std::vector<PSXRecompV4::RecompilerPatch> patches;
    patches.push_back({"header-smoke", 0x80010000u, 0u, 0u, {}});
    return patches.front().id == "header-smoke" &&
                   PSXRecompV4::recompiler_patch_address_key(
                       patches.front().address) == 0x00010000u
               ? 0
               : 1;
}
