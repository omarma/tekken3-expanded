#!/usr/bin/env python3
"""Keep dirty-text continuation handoff behavior from regressing."""

from pathlib import Path
import sys


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    memory = (root / "runtime/src/memory.c").read_text(encoding="utf-8")
    interp = (root / "runtime/src/dirty_ram_interp.c").read_text(encoding="utf-8")

    start = memory.index("int dirty_ram_text_native_ok_ranges_from(")
    end = memory.index("\n/* Preserve the generated-code ABI", start)
    range_guard = memory[start:end]

    required_range_fragments = (
        "uint32_t exec_pc",
        "changed_prefix && text_continuation_may_revisit(lo_len_pairs, count, at)",
        "if (phys + len <= at) continue;",
        "len -= at - phys;",
        "if (!any)",
    )
    for fragment in required_range_fragments:
        if fragment not in range_guard:
            raise AssertionError(f"missing continuation range guard: {fragment}")
    if "text_diverged_bitmap" in range_guard:
        raise AssertionError("exact-range mismatch still sticky-poisons a whole page")
    if "dirty_ram_text_native_ok_ranges_from(lo_len_pairs, count, 0u)" not in memory:
        raise AssertionError("legacy generated-code ABI is not preserved")

    handoff = "clean_game_text_miss && interp_enter_compiled(cpu, "
    if interp.count(handoff) != 2:
        raise AssertionError("expected transfer and call-return continuation handoffs")
    if "interp_enter_compiled(cpu, target)" not in interp:
        raise AssertionError("missing transfer-boundary continuation handoff")
    if "interp_enter_compiled(cpu, pc)" not in interp:
        raise AssertionError("missing call-return continuation handoff")

    print("dirty-text continuation guards: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
