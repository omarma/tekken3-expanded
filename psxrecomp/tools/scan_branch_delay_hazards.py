#!/usr/bin/env python3
"""
scan_branch_delay_hazards.py

Phase 1b B(5) safety scan + translator-fix verification.

Background
==========
Real R3000A: a conditional branch's decision uses rs/rt values from
BEFORE the delay-slot instruction executes. The slice walker
(bios_slice_walker.cpp) emits the delay-slot C code before the branch
terminator C code, so a naive translator that read cpu->gpr[rs/rt] in
the branch terminator would see POST-delay-slot state — wrong whenever
the delay slot writes to one of the branch's own operands.

This scanner does two things:

1. Counts, for the entire BIOS (every Ghidra function plus the
   reset-vector and BEV=1 GE vector synthetic seeds), how many branches
   have a delay-slot instruction that writes to that branch's rs or rt.
   This is the "would-be-hazardous-without-snapshot" set. It's an
   intrinsic property of the BIOS bytes; the translator can't shrink it.

2. Verifies that the strict translator handles ALL conditional branches
   via the pre_delay_code snapshot pattern. The check is structural:
   open recompiler/src/strict_translator.cpp and confirm every branch
   case (op 0x04, 0x05, 0x06, 0x07, REGIMM rt 0x00, REGIMM rt 0x01)
   sets `r.pre_delay_code = ...` and reads only `psx_brA_*` /
   `psx_brB_*` snapshot variables in `r.c_code` (never `cpu->gpr[`).
   If any branch case fails the check, the scanner reports it as
   `incorrect_in_current_translator` and exits non-zero.

Output
======
generated/branch_delay_hazards.json with:
  - totals.branches_scanned
  - totals.delay_slot_writes_branch_operand   (informational, intrinsic)
  - totals.incorrect_in_current_translator    (must be 0 after the fix)
  - translator_check.<branch_op>: pass/fail status
  - hazards: list of (branch, delay_slot) pairs (informational)

Exit code is non-zero if `incorrect_in_current_translator > 0`, OR if
`--fail-on-hazard` is passed and any informational hazards exist.
"""

import json
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_config

# These are populated by main() from the config. Module-level globals are
# preserved to minimize churn against the existing walker/fetch helpers.
ROOT = None
BIOS_PATH = None
STARTS_PATH = None
OUT_PATH = None
IMAGE_BASE = None
IMAGE_END = None
ROM_SIZE = None

# BIOS-specific synthetic entry seeds (reset vector + BEV=1 exception vector).
# These don't appear in ghidra_function_starts.json but must be walked to
# cover boot-time hazards. For non-BIOS configs they don't apply.
BIOS_SYNTHETIC_SEEDS = [
    (0xBFC00000, 0xBFC00420, "reset_vector"),
    (0xBFC00180, 0xBFC00420, "boot_general_exception_bev1"),
]


def fetch(rom, addr):
    off = addr - IMAGE_BASE
    if off < 0 or off + 4 > ROM_SIZE:
        return None
    return struct.unpack_from("<I", rom, off)[0]


def is_cond_branch(raw):
    """Return (mnem, rs, rt_or_None) if `raw` is one of the conditional
    branches we implemented in B(5), else None. rt is None for the
    branches that don't have a meaningful rt operand."""
    op = (raw >> 26) & 0x3F
    rs = (raw >> 21) & 0x1F
    rt = (raw >> 16) & 0x1F
    if op == 0x04:
        return ("BEQ",  rs, rt)
    if op == 0x05:
        return ("BNE",  rs, rt)
    if op == 0x06:
        return ("BLEZ", rs, None)
    if op == 0x07:
        return ("BGTZ", rs, None)
    if op == 0x01:
        if rt == 0x00:
            return ("BLTZ", rs, None)
        if rt == 0x01:
            return ("BGEZ", rs, None)
    return None


def instr_writes_to_gpr(raw):
    """Return the set of GPR indices that `raw` writes to (architectural
    destination only; HI/LO writes don't count for this scan since
    branches don't read HI/LO).

    Conservative: if we don't recognize the opcode, return empty set
    rather than guessing — the scan would then under-report hazards for
    unrecognized opcodes. To avoid that we panic on unknown opcodes; the
    instruction inventory already guarantees every BIOS opcode is in our
    classification table.
    """
    if raw == 0:
        return set()  # nop
    op = (raw >> 26) & 0x3F
    rs = (raw >> 21) & 0x1F
    rt = (raw >> 16) & 0x1F
    rd = (raw >> 11) & 0x1F

    # SPECIAL
    if op == 0x00:
        funct = raw & 0x3F
        # R-type ALU/shift writes rd
        if funct in (0x00, 0x02, 0x03, 0x04, 0x06, 0x07,
                     0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27,
                     0x2A, 0x2B):
            return {rd}
        # MFHI/MFLO write rd
        if funct in (0x10, 0x12):
            return {rd}
        # MTHI/MTLO write HI/LO only
        if funct in (0x11, 0x13):
            return set()
        # MULT/MULTU/DIV/DIVU write HI/LO only
        if funct in (0x18, 0x19, 0x1A, 0x1B):
            return set()
        # JR: no GPR write
        if funct == 0x08:
            return set()
        # JALR: writes rd ($ra default = 31 if rd==0 not encoded;
        # technically rd field is the link reg, $ra is just the
        # default name)
        if funct == 0x09:
            return {rd}
        # SYSCALL/BREAK: no architectural GPR write (handler may, but
        # for the in-line trap pattern the BIOS uses, treat as none)
        if funct in (0x0C, 0x0D):
            return set()
        return set()

    # REGIMM: BLTZ/BGEZ no write; BLTZAL/BGEZAL write $31
    if op == 0x01:
        if rt in (0x10, 0x11):
            return {31}
        return set()

    # J / JAL
    if op == 0x02:
        return set()
    if op == 0x03:
        return {31}

    # Conditional branches: no GPR write
    if op in (0x04, 0x05, 0x06, 0x07):
        return set()

    # I-type ALU writes rt
    if op in (0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F):
        return {rt}

    # COP0
    if op == 0x10:
        # MFC0 (rs=0): writes rt
        # MTC0 (rs=4): writes COP0 reg, no GPR
        # CO=1 funct (rs=0x10): RFE etc., no GPR
        rs_field = (raw >> 21) & 0x1F
        if rs_field == 0x00:
            return {rt}
        return set()

    # COP1: no GPR writes for the FPU instructions the BIOS contains
    # (mtc1/mov.d/etc. either move into FPRs or compute on FPRs).
    # bc1f/bc1t are conditional branches with no GPR write.
    if op == 0x11:
        return set()

    # COP2 (GTE): not in BIOS inventory, but be permissive
    if op == 0x12:
        return set()

    # Loads: write rt
    if op in (0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26):
        return {rt}

    # Stores: no GPR write
    if op in (0x28, 0x29, 0x2A, 0x2B, 0x2E):
        return set()

    # LWC1/SWC1 etc.: no GPR write
    if op in (0x30, 0x31, 0x32, 0x33, 0x38, 0x39, 0x3A, 0x3B):
        return set()

    # Unknown opcode: don't guess
    raise RuntimeError(
        f"unknown primary opcode 0x{op:02X} in instr_writes_to_gpr (raw=0x{raw:08X})"
    )


# Reuse the same BFS walker as build_instruction_inventory.py via a
# simplified inline copy. Kept independent so this scan stays self-
# contained.
def branch_target(addr, raw):
    op = (raw >> 26) & 0x3F
    if op in (0x04, 0x05, 0x06, 0x07):
        simm = raw & 0xFFFF
        if simm & 0x8000:
            simm -= 0x10000
        return ("cond_branch", addr + 4 + (simm << 2))
    if op == 0x01:
        simm = raw & 0xFFFF
        if simm & 0x8000:
            simm -= 0x10000
        return ("cond_branch", addr + 4 + (simm << 2))
    if op == 0x02:
        return ("jump", ((addr + 4) & 0xF0000000) | ((raw & 0x03FFFFFF) << 2))
    if op == 0x03:
        return ("call", ((addr + 4) & 0xF0000000) | ((raw & 0x03FFFFFF) << 2))
    if op == 0x00:
        funct = raw & 0x3F
        if funct == 0x08:
            return ("jr", None)
        if funct == 0x09:
            return ("call", None)
        if funct == 0x0C:
            return ("syscall", None)
        if funct == 0x0D:
            return ("break", None)
    if op in (0x11, 0x12):
        rs = (raw >> 21) & 0x1F
        if rs == 0x08:
            simm = raw & 0xFFFF
            if simm & 0x8000:
                simm -= 0x10000
            return ("cond_branch", addr + 4 + (simm << 2))
    return ("normal", None)


def walk(rom, entry, hard_cap):
    visited = {}
    work = [entry]

    def visit_delay_slot(addr):
        if addr in visited:
            return
        if addr < entry or addr >= hard_cap or addr > IMAGE_END:
            return
        raw = fetch(rom, addr)
        if raw is None:
            return
        visited[addr] = raw

    while work:
        addr = work.pop()
        if addr in visited:
            continue
        if addr < entry or addr >= hard_cap or addr > IMAGE_END:
            continue
        raw = fetch(rom, addr)
        if raw is None:
            continue
        visited[addr] = raw

        kind, target = branch_target(addr, raw)
        delay = addr + 4

        if kind == "jr":
            visit_delay_slot(delay)
            continue
        if kind == "jump":
            visit_delay_slot(delay)
            if target is not None and entry <= target < hard_cap:
                work.append(target)
            continue
        if kind == "cond_branch":
            visit_delay_slot(delay)
            work.append(addr + 8)
            if target is not None and entry <= target < hard_cap:
                work.append(target)
            continue
        if kind == "call":
            visit_delay_slot(delay)
            work.append(addr + 8)
            continue
        if kind in ("syscall", "break"):
            work.append(addr + 4)
            continue
        work.append(addr + 4)
    return visited


def main():
    global ROOT, BIOS_PATH, STARTS_PATH, OUT_PATH, IMAGE_BASE, IMAGE_END, ROM_SIZE
    cfg = audit_config.from_argv(sys.argv)
    ROOT = str(cfg.project_root)
    BIOS_PATH = str(cfg.rom)
    OUT_PATH = str(cfg.out_dir / "branch_delay_hazards.json")
    IMAGE_BASE = cfg.load_address
    IMAGE_END = cfg.load_address + cfg.text_size - 1
    ROM_SIZE = cfg.text_size

    print(f"# branch_delay_hazards: {cfg.name}")
    print(f"  rom          = {BIOS_PATH}")
    print(f"  image base   = 0x{IMAGE_BASE:08X}")
    print(f"  image end    = 0x{IMAGE_END:08X}")
    print(f"  out          = {OUT_PATH}")

    if not cfg.function_starts:
        print(f"  function_starts: <not configured for this program>")
        print()
        print("Branch-hazard walker requires a function_starts JSON to seed "
              "the reachable-code walk. This config has none (typical for "
              "games using dynamic discovery). The walker-based hazard "
              "scan is skipped. The translator-source check still runs.")
        translator_check = verify_translator_uses_snapshots()
        incorrect = sum(1 for v in translator_check.values() if not v["pass"])
        print(f"\n  translator-source check: "
              f"{'PASS' if incorrect == 0 else 'FAIL'}")
        if incorrect:
            for op_name, info in translator_check.items():
                if not info["pass"]:
                    print(f"    FAIL {op_name}: {info['reason']}", file=sys.stderr)
            return 8
        # Returning OK because the walker check simply doesn't apply to
        # this config; the translator-source invariant is still upheld.
        return 0

    STARTS_PATH = str(cfg.function_starts)
    with open(BIOS_PATH, "rb") as f:
        rom = f.read()
    with open(STARTS_PATH, "r", encoding="utf-8") as f:
        starts_doc = json.load(f)
    starts = [int(s, 16) for s in starts_doc["function_starts"]]

    # Union all walked addresses across all seeds.
    all_instrs = {}

    # Synthetic seeds: BIOS-specific reset/exception vectors. Only apply
    # to the BIOS image — recognized by load_address.
    if cfg.load_address == 0xBFC00000:
        for (entry, cap, _label) in BIOS_SYNTHETIC_SEEDS:
            for addr, raw in walk(rom, entry, cap).items():
                all_instrs[addr] = raw

    for i, entry in enumerate(starts):
        cap = starts[i + 1] if i + 1 < len(starts) else (IMAGE_END + 1)
        for addr, raw in walk(rom, entry, cap).items():
            all_instrs[addr] = raw

    # Now scan every conditional branch.
    hazards = []
    safe_count = 0
    branch_count = 0
    no_delay_in_walk = 0

    for addr in sorted(all_instrs.keys()):
        raw = all_instrs[addr]
        cb = is_cond_branch(raw)
        if cb is None:
            continue
        branch_count += 1
        mnem, br_rs, br_rt = cb

        delay_addr = addr + 4
        delay_raw = all_instrs.get(delay_addr)
        if delay_raw is None:
            # The walker may not have visited the delay slot if the
            # branch sits at the very end of the walked region. Fetch
            # directly from ROM as a fallback so the scan is complete.
            delay_raw = fetch(rom, delay_addr)
            if delay_raw is None:
                no_delay_in_walk += 1
                continue

        try:
            written = instr_writes_to_gpr(delay_raw)
        except RuntimeError as e:
            return _bail(f"unknown delay-slot opcode at 0x{delay_addr:08x}: {e}")

        flagged = []
        if br_rs in written and br_rs != 0:
            flagged.append("rs")
        if br_rt is not None and br_rt in written and br_rt != 0:
            flagged.append("rt")

        if flagged:
            hazards.append({
                "branch_addr":  f"0x{addr:08x}",
                "branch_raw":   f"0x{raw:08x}",
                "branch_mnem":  mnem,
                "branch_rs":    f"0x{br_rs:02x}",
                "branch_rt":    f"0x{br_rt:02x}" if br_rt is not None else None,
                "delay_addr":   f"0x{delay_addr:08x}",
                "delay_raw":    f"0x{delay_raw:08x}",
                "delay_writes": flagged,
                "hazard":       True,
            })
        else:
            safe_count += 1

    # Translator-fix verification: confirm strict_translator.cpp handles
    # every branch via the pre_delay_code snapshot pattern.
    translator_check = verify_translator_uses_snapshots()

    incorrect_in_translator = sum(
        1 for v in translator_check.values() if not v["pass"]
    )

    out = {
        "schema": "psxrecomp phase1b branch_delay_hazards v2",
        "program": cfg.name,
        "totals": {
            "branches_scanned":                  branch_count,
            "delay_slot_writes_branch_operand":  len(hazards),
            "incorrect_in_current_translator":   incorrect_in_translator,
            "delay_slot_unreachable_in_walk":    no_delay_in_walk,
        },
        "translator_check": translator_check,
        "rationale": (
            "Phase 1b B(5) implements conditional branches as slice-walker "
            "terminators. The walker (with the corrected emit contract) "
            "emits TranslateResult.pre_delay_code BEFORE the delay slot "
            "and the terminator c_code AFTER it. The strict translator's "
            "branch handlers populate pre_delay_code with `uint32_t "
            "psx_brA_<addr> = cpu->gpr[rs];` (and psx_brB_ for "
            "BEQ/BNE), and the c_code reads ONLY those snapshot locals. "
            "This makes the architectural rs/rt-before-delay rule "
            "correct for every branch regardless of what the delay slot "
            "writes. The `delay_slot_writes_branch_operand` count is an "
            "intrinsic property of the BIOS bytes (it cannot be reduced "
            "by translator work); `incorrect_in_current_translator` is "
            "the count that matters for correctness and must be 0."
        ),
        "hazards": hazards,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print(f"Wrote {OUT_PATH}")
    print(f"  branches scanned                 : {branch_count}")
    print(f"  delay slot writes branch operand : {len(hazards)} (informational)")
    print(f"  incorrect in current translator  : {incorrect_in_translator}")
    print(f"  delay-slot unreachable in walk   : {no_delay_in_walk}")
    if incorrect_in_translator > 0:
        print("ERROR: strict translator does not snapshot all branch operands",
              file=sys.stderr)
        for op_name, info in translator_check.items():
            if not info["pass"]:
                print(f"  FAIL {op_name}: {info['reason']}", file=sys.stderr)
        return 8
    if "--fail-on-hazard" in sys.argv and hazards:
        return 6
    return 0


def verify_translator_uses_snapshots():
    """Open recompiler/src/strict_translator.cpp and confirm that every
    conditional-branch handler:
      1. Sets r.pre_delay_code (non-empty assignment).
      2. Uses only snapshot variables (psx_brA_/psx_brB_) in r.c_code,
         and never reads cpu->gpr[ in the c_code body.
    Returns a dict { branch_name -> {pass: bool, reason: str} }.
    """
    # strict_translator.cpp lives in psxrecomp regardless of which
    # program config is being audited. Resolve relative to this script.
    psxrecomp_root = Path(__file__).parent.parent
    src_path = psxrecomp_root / "recompiler" / "src" / "strict_translator.cpp"
    with open(src_path, "r", encoding="utf-8") as f:
        text = f.read()

    # Find the comment marker that starts the branch section, and only
    # check from there to the end of the REGIMM block. This avoids false
    # positives from earlier instruction handlers.
    section_start = text.find("Conditional branches (Phase 1b B(5)")
    if section_start < 0:
        return {"_section": {"pass": False,
                             "reason": "branch section marker not found in strict_translator.cpp"}}
    # End of section: the J handler comment that follows.
    section_end = text.find("// J (0x02)", section_start)
    if section_end < 0:
        section_end = len(text)
    section = text[section_start:section_end]

    results = {}
    branch_specs = [
        ("BEQ_op04",  "if (opcode == 0x04)",  True),   # has rt
        ("BNE_op05",  "if (opcode == 0x05)",  True),
        ("BLEZ_op06", "if (opcode == 0x06)",  False),
        ("BGTZ_op07", "if (opcode == 0x07)",  False),
        # REGIMM (op 0x01) handles BLTZ + BGEZ in one block
        ("REGIMM_op01", "if (opcode == 0x01)", False),
    ]

    for name, marker, has_rt in branch_specs:
        marker_pos = section.find(marker)
        if marker_pos < 0:
            results[name] = {"pass": False, "reason": f"handler marker `{marker}` not found"}
            continue
        # Capture the handler block. Use a simple brace counter from the
        # opening `{` after marker_pos to the matching `}`.
        body_start = section.find("{", marker_pos)
        if body_start < 0:
            results[name] = {"pass": False, "reason": "no `{` after marker"}
            continue
        depth = 0
        i = body_start
        body_end = -1
        while i < len(section):
            ch = section[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    body_end = i + 1
                    break
            i += 1
        if body_end < 0:
            results[name] = {"pass": False, "reason": "unbalanced braces in handler"}
            continue
        body = section[body_start:body_end]

        # Rule 1: pre_delay_code must be assigned with snapshot pattern
        if "r.pre_delay_code" not in body:
            results[name] = {"pass": False, "reason": "no r.pre_delay_code assignment"}
            continue
        if "psx_brA_" not in body:
            results[name] = {"pass": False, "reason": "snapshot variable psx_brA_* not used"}
            continue
        if has_rt and "psx_brB_" not in body:
            results[name] = {"pass": False, "reason": "snapshot variable psx_brB_* not used (BEQ/BNE need rt snapshot)"}
            continue

        # Rule 2: r.c_code must NOT read cpu->gpr[
        # Find the r.c_code = fmt::format(...) string and check that
        # the format string contains no `cpu->gpr[` substring.
        c_code_pos = body.find("r.c_code = fmt::format(")
        if c_code_pos < 0:
            results[name] = {"pass": False, "reason": "no r.c_code = fmt::format(...) assignment"}
            continue
        # Walk forward to the matching `);` of fmt::format. Track parens.
        paren_start = body.find("(", c_code_pos)
        depth = 0
        j = paren_start
        c_code_end = -1
        while j < len(body):
            if body[j] == "(":
                depth += 1
            elif body[j] == ")":
                depth -= 1
                if depth == 0:
                    c_code_end = j + 1
                    break
            j += 1
        if c_code_end < 0:
            results[name] = {"pass": False, "reason": "unbalanced parens in r.c_code = fmt::format(...)"}
            continue
        c_code_call = body[c_code_pos:c_code_end]
        if "cpu->gpr[" in c_code_call:
            results[name] = {"pass": False,
                             "reason": "r.c_code reads cpu->gpr[...] directly — must use psx_brA_/psx_brB_ snapshot variables only"}
            continue

        results[name] = {"pass": True, "reason": "snapshot pattern verified"}

    return results


def _bail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    return 7


if __name__ == "__main__":
    sys.exit(main())
