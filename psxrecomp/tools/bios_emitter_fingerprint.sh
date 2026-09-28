#!/usr/bin/env bash
# bios_emitter_fingerprint.sh — print a single content hash of every input that
# affects the BIOS generated C: the psxrecomp-bios emitter sources, the cycle
# model they bake in, and — per BIOS profile — the profile TOML itself, its
# seeds file, and the ROM image. regen_bios.sh writes this into
# generated/<stem>.emitter.sha after a regen; runtime/runtime.cmake recomputes
# it at configure time and warns if it differs — i.e. "you changed an emitter
# input but didn't regenerate the BIOS". Hashing the ROM and profile means
# swapping the BIOS image or editing its profile trips the staleness warning
# too, not just emitter-source edits.
#
# Usage: bios_emitter_fingerprint.sh [profile.toml]
#   default profile: bios/SCPH1001.toml
#
# The rom/seeds extraction expects simple `key = "value"` lines, which is how
# the tracked profiles are written. Keep the FILES list in sync with what
# actually feeds psxrecomp-bios --emit-full.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROFILE="${1:-bios/SCPH1001.toml}"

FILES=(
    recompiler/src/full_function_emitter.cpp
    recompiler/src/full_function_emitter.h
    recompiler/src/strict_translator.cpp
    recompiler/src/main_bios.cpp
    recompiler/src/function_discovery.cpp
    recompiler/src/bios_address_model.cpp
    recompiler/src/bios_address_model.h
    recompiler/src/config_loader.cpp
    recompiler/src/control_flow.cpp
    recompiler/src/function_analysis.cpp
    recompiler/src/mips_decoder.cpp
    recompiler/src/bios_slice_walker.cpp
    recompiler/src/basic_block.cpp
    runtime/include/psx_cyc.h
    runtime/include/psx_instr_cost.h
)

# Per-profile inputs: the profile itself, its seeds file, its ROM.
if [ -f "$PROFILE" ]; then
    FILES+=("$PROFILE")
    toml_value() {
        sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*\"\([^\"]*\)\".*/\1/p" "$PROFILE" | head -1
    }
    SEEDS="$(toml_value seeds)"
    ROM="$(toml_value rom)"
    [ -n "$SEEDS" ] && FILES+=("$SEEDS")
    [ -n "$ROM" ]   && FILES+=("$ROM")
else
    # Legacy fallback (pre-profile invocations): the historical seeds path.
    FILES+=(recompiler/seeds/phase2_ghidra_seeds.json)
fi

# Hash only files that exist (list may evolve). sha256sum is in Git Bash/coreutils.
present=()
for f in "${FILES[@]}"; do [ -f "$f" ] && present+=("$f"); done
# Single combined digest over file CONTENTS in the FILES-array order above.
# Content-only (stdin mode) on purpose: `sha256sum "$f"` emits "<hash>  <path>"
# lines, so the digest depended on the profile's PATH SPELLING — regen_bios.sh
# records with a relative path while runtime.cmake recomputes with an absolute
# one, and every configure read as STALE with a byte-identical tree. The array
# order is defined by this script alone, so it is stable across spellings.
for f in "${present[@]}"; do
    sha256sum < "$f"
done | sha256sum | awk '{print $1}'
