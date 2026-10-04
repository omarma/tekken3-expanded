#!/usr/bin/env python3
"""Keep dirty-text continuation handoff behavior from regressing."""

from pathlib import Path
import sys


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    memory = (root / "runtime/src/memory.c").read_text(encoding="utf-8")
    interp = (root / "runtime/src/dirty_ram_interp.c").read_text(encoding="utf-8")

    start = memory.index("static int text_native_ok_ranges_uncached(")
    end = memory.index("\n/* Preserve the generated-code ABI", start)
    range_guard = memory[start:end]
    revisit = memory[memory.index("static int text_continuation_may_revisit("):start]
    # A backward branch only blocks the compiled continuation when the code it
    # can reach (followed to a fixed point) includes a changed word.
    for fragment in ("uint32_t last_changed", "if (lowest <= last_changed) return 1;",
                     "if (lowest == reach) return 0;", "return 1; /* jr register"):
        if fragment not in revisit:
            raise AssertionError(f"missing continuation reach guard: {fragment}")

    required_range_fragments = (
        "uint32_t exec_pc",
        "text_continuation_may_revisit(lo_len_pairs, count, at, last_changed)",
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
