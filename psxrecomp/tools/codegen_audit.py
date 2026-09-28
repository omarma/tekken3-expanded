"""codegen_audit — scan a generated `_full.c` + `_dispatch.c` for codegen bugs.

Generic across any PSX program (BIOS or game). Consumes an audit-config
TOML via `--config PATH`; see `bios/SCPH1001.toml` and game `audit.toml`
for the schema. The original BIOS-only version was at `_codegen_audit.py`
and is superseded by this file.

Five passes:
  1. Predicate-init declaration audit (verifies 2026-05-04 fix landed).
  2. Direct psx_dispatch(cpu, 0xXXXX) targets vs dispatch table.
  3. Indirect psx_dispatch(cpu, cpu->gpr[N]) site distribution.
  4. Tail-call (`cpu->pc = 0xXXXX; return;`) targets vs dispatch table.
  5. Chained-branch + delay-slot-as-label site population (protected by
     the predicate-init fix; informational).

Usage:
  python tools/codegen_audit.py --config bios/SCPH1001.toml
  python tools/codegen_audit.py --config /path/to/game.toml

Exit code:
  0  no real bugs (excluding expected install-at-runtime stubs)
  1  buggy predicate decls present, or unexpected dispatch misses
"""
import re
import sys
from collections import Counter
from pathlib import Path

# Allow `python tools/codegen_audit.py` from project root
sys.path.insert(0, str(Path(__file__).parent))
import audit_config


# Tail-call targets we expect to miss (install-at-runtime stubs handled
# by the dirty-RAM interpreter). Documented per program — BIOS-only for
# now; games may add their own.
EXPECTED_TAIL_CALL_MISSES = {
    "SCPH1001 BIOS": {0x00000CF0},   # SIO data-byte install stub
}


def main():
    cfg = audit_config.from_argv(sys.argv)
    print(f"# codegen audit: {cfg.name}")
    print(f"  full_c     = {cfg.full_c}")
    print(f"  dispatch_c = {cfg.dispatch_c}")
    print()

    if not cfg.full_c.exists():
        print(f"ERROR: full_c not found: {cfg.full_c}", file=sys.stderr)
        return 2
    if not cfg.dispatch_c.exists():
        print(f"ERROR: dispatch_c not found: {cfg.dispatch_c}", file=sys.stderr)
        return 2

    full_c = cfg.full_c.read_text(encoding="utf-8", errors="replace")
    dispatch_c = cfg.dispatch_c.read_text(encoding="utf-8", errors="replace")

    expected_misses = EXPECTED_TAIL_CALL_MISSES.get(cfg.name, set())

    # ---- 1. predicate-init declaration audit ----
    buggy_decls = re.findall(r'int psx_taken_[0-9A-F]+ = \([^)]*\);', full_c)
    zero_decls  = re.findall(r'int psx_taken_[0-9A-F]+ = 0;',         full_c)
    assignments = re.findall(r'^\s+psx_taken_[0-9A-F]+ = \(',        full_c, re.M)
    print(f"[1] predicate decl audit: buggy={len(buggy_decls)} "
          f"zero_init={len(zero_decls)} assigns={len(assignments)}")
    if buggy_decls:
        print("  ⚠ FIX REGRESSION — found buggy declarations:")
        for b in buggy_decls[:5]:
            print(f"    {b}")

    # ---- 2. direct psx_dispatch(cpu, 0xXXXX) targets ----
    direct_targets = re.findall(r'psx_dispatch\(cpu,\s*0x([0-9A-Fa-f]+)u?\);', full_c)
    direct_set = set(cfg.normalize_addr(int(t, 16)) for t in direct_targets)
    print(f"\n[2] direct psx_dispatch targets (literal, normalized): "
          f"{len(direct_set)} unique")

    table_entries = re.findall(r'\{\s*0x([0-9A-Fa-f]+)u?\s*,\s*func_[0-9A-Fa-f]+', dispatch_c)
    table_set = set(cfg.normalize_addr(int(e, 16)) for e in table_entries)
    print(f"    dispatch table size: {len(table_set)} entries")

    missing = sorted(direct_set - table_set)
    print(f"    direct targets MISSING from table after normalization: "
          f"{len(missing)}")
    for m in missing[:25]:
        cnt = sum(1 for t in direct_targets
                  if cfg.normalize_addr(int(t, 16)) == m)
        print(f"      0x{m:08X}  ({cnt} call site{'s' if cnt!=1 else ''})")

    # ---- 3. indirect dispatch sites (jalr/jr through gpr[N]) ----
    indirect_sites = re.findall(r'psx_dispatch\(cpu,\s*cpu->gpr\[(\d+)\]\);', full_c)
    print(f"\n[3] indirect psx_dispatch sites: {len(indirect_sites)} total")
    gpr_use = Counter(indirect_sites)
    print(f"    by register: {dict(gpr_use.most_common(8))}")

    # ---- 4. tail-call targets ----
    tail_calls = re.findall(r'cpu->pc = 0x([0-9A-Fa-f]+)u;\s*return;', full_c)
    tail_set = set(cfg.normalize_addr(int(t, 16)) for t in tail_calls)
    print(f"\n[4] tail-call (cpu->pc=...; return;) targets (normalized): "
          f"{len(tail_set)} unique")
    tail_missing = sorted(tail_set - table_set)
    unexpected_missing = sorted(set(tail_missing) - expected_misses)
    print(f"    tail-call targets MISSING from dispatch: {len(tail_missing)} "
          f"(of which {len(unexpected_missing)} unexpected)")
    for m in tail_missing[:25]:
        cnt = sum(1 for t in tail_calls
                  if cfg.normalize_addr(int(t, 16)) == m)
        tag = "" if m not in expected_misses else "  [expected install-at-runtime stub]"
        print(f"      0x{m:08X}  ({cnt} site{'s' if cnt!=1 else ''}){tag}")

    # ---- 5. chained-branch + delay-slot-as-label population ----
    labels = set(re.findall(r'^label_([0-9A-F]+):', full_c, re.M))
    beq_sites = re.findall(
        r'/\* 0x([0-9A-F]+):\s+[0-9A-F]+\s+(beq|bne|bgez|bgtz|blez|bltz|bnel|beql)\b',
        full_c)
    beq_addrs = [int(a, 16) for a, _ in beq_sites]
    delay_is_label = sum(1 for a in beq_addrs if f"{a+4:08X}" in labels)
    print(f"\n[5] chained-branch-with-delay-slot-label population:")
    print(f"    total conditional branches: {len(beq_addrs)}")
    print(f"    delay slot also a basic-block label: {delay_is_label} "
          f"(protected by zero-init fix)")

    # ---- summary ----
    real_bugs = (
        len(buggy_decls)         # predicate-init regression
        + len(missing)           # direct dispatch miss
        + len(unexpected_missing)  # unexpected tail-call miss
    )

    print(f"\n[summary] {cfg.name}")
    print(f"  buggy predicate decls           : {len(buggy_decls)}")
    print(f"  direct dispatch miss            : {len(missing)}")
    print(f"  unexpected tail-call miss       : {len(unexpected_missing)}")
    print(f"  total real-bug findings         : {real_bugs}")
    if real_bugs == 0:
        print(f"  STATUS                          : CLEAN")
    else:
        print(f"  STATUS                          : ISSUES FOUND")

    return 0 if real_bugs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
