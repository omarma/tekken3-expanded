#!/usr/bin/env python3
"""
build_instruction_inventory.py

Phase 1b artifact builder. Reads bios/SCPH1001.BIN plus
generated/ghidra_function_starts.json, walks every Ghidra-known function
body, and emits generated/instruction_inventory.json.

The walk is deterministic: starting at each function entry, decode 32-bit
words as MIPS R3000A. Stop on the first `jr $ra` (raw 0x03E00008),
INCLUDING its delay slot, OR on hitting the next function's start
address. This is the canonical MIPS function-epilogue terminator and
matches how PS1 BIOS code is laid out.

Verification: a sample of 5 function bodies retrieved from Ghidra MCP
(see ghidra_function_starts.json -> verified_function_bodies) is
compared against this walker. If any verified end disagrees with the
walker's detected end, the script aborts with a non-zero exit and an
error message identifying the function. NO FALLBACK.

Output: generated/instruction_inventory.json with one entry per
classification bucket. A bucket is keyed by:
  (top6_opcode, sub_field_value, sub_field_kind)

where sub_field_kind is one of:
  - "none"        : top-level opcode is unique enough on its own
  - "funct"       : top opcode == 0x00 (SPECIAL),  funct = raw & 0x3F
  - "rt"          : top opcode == 0x01 (REGIMM),   rt    = (raw>>16)&0x1F
  - "rs_cop0"     : top opcode == 0x10 (COP0),     rs    = (raw>>21)&0x1F
  - "rs_cop2"     : top opcode == 0x12 (COP2),     rs    = (raw>>21)&0x1F
  - "rfe"         : raw == 0x42000010 special-cased
  - "cop2_cofun"  : top opcode == 0x12, rs >= 0x10 (CFC2/CTC2/MFC2/MTC2 vs GTE op)

Each bucket records: mnemonic_guess, count, first_address, three example
addresses, and a `category` ("CPU", "COP0", "COP2_GTE", "PRIVILEGED",
"UNKNOWN").

This script does not fall back to "unknown opcode = OK". Every word it
decodes lands in a bucket; if a bucket cannot be classified by the table
below it goes into the "UNKNOWN" category and the script exits non-zero
unless --allow-unknown is passed.
"""

import json
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIOS_PATH = os.path.join(ROOT, "bios", "SCPH1001.BIN")
STARTS_PATH = os.path.join(ROOT, "generated", "ghidra_function_starts.json")
OUT_PATH = os.path.join(ROOT, "generated", "instruction_inventory.json")

IMAGE_BASE = 0xBFC00000
IMAGE_END = 0xBFC7FFFF  # inclusive
ROM_SIZE = 0x80000      # 524288

# Synthetic seeds for the pre-Ghidra-function region (0xBFC00000..0xBFC0041F).
# Ghidra's first analysed function is at 0xBFC00420; the reset vector and the
# two ROM-side boot exception vectors live below it and are NOT covered by the
# function list. Each entry: (entry_addr, hard_cap, label).
SYNTHETIC_SEEDS = [
    (0xBFC00000, 0xBFC00420, "reset_vector"),
    # 0xBFC00100 is the R3000 UTLB-miss vector when BEV=1. PS1's R3000A has
    # no TLB, so this address is never executed. Empirically Ghidra has the
    # bytes at 0xBFC00108 classified as the "Sony Computer Entertainment Inc."
    # copyright string, and walking from 0xBFC00100 produces opcodes that
    # decode to that string text. NOT a valid seed; deliberately omitted.
    (0xBFC00180, 0xBFC00420, "boot_general_exception_bev1"),
]


# --- MIPS R3000A opcode tables --------------------------------------------
#
# Sources cross-referenced:
#   - IDT R3000 Family Software Reference Manual
#   - Sony PSX MIPS-1 instruction listing (nocash psx-spx)
#   - rabbitizer (which the salvaged recompiler also uses)

OP_PRIMARY = {
    0x00: ("SPECIAL", "funct"),
    0x01: ("REGIMM",  "rt"),
    0x02: ("J",       "none"),
    0x03: ("JAL",     "none"),
    0x04: ("BEQ",     "none"),
    0x05: ("BNE",     "none"),
    0x06: ("BLEZ",    "none"),
    0x07: ("BGTZ",    "none"),
    0x08: ("ADDI",    "none"),
    0x09: ("ADDIU",   "none"),
    0x0A: ("SLTI",    "none"),
    0x0B: ("SLTIU",   "none"),
    0x0C: ("ANDI",    "none"),
    0x0D: ("ORI",     "none"),
    0x0E: ("XORI",    "none"),
    0x0F: ("LUI",     "none"),
    0x10: ("COP0",    "rs_cop0"),
    0x11: ("COP1",    "rs_cop0"),     # PS1 has no FPU; appearing means data
    0x12: ("COP2",    "rs_cop2"),     # GTE
    0x13: ("COP3",    "rs_cop0"),     # PS1 has no COP3; appearing means data
    0x20: ("LB",      "none"),
    0x21: ("LH",      "none"),
    0x22: ("LWL",     "none"),
    0x23: ("LW",      "none"),
    0x24: ("LBU",     "none"),
    0x25: ("LHU",     "none"),
    0x26: ("LWR",     "none"),
    0x28: ("SB",      "none"),
    0x29: ("SH",      "none"),
    0x2A: ("SWL",     "none"),
    0x2B: ("SW",      "none"),
    0x2E: ("SWR",     "none"),
    0x30: ("LWC0",    "none"),
    0x31: ("LWC1",    "none"),
    0x32: ("LWC2",    "none"),         # GTE
    0x33: ("LWC3",    "none"),
    0x38: ("SWC0",    "none"),
    0x39: ("SWC1",    "none"),
    0x3A: ("SWC2",    "none"),         # GTE
    0x3B: ("SWC3",    "none"),
}

SPECIAL_FUNCT = {
    0x00: "SLL",
    0x02: "SRL",
    0x03: "SRA",
    0x04: "SLLV",
    0x06: "SRLV",
    0x07: "SRAV",
    0x08: "JR",
    0x09: "JALR",
    0x0C: "SYSCALL",
    0x0D: "BREAK",
    0x10: "MFHI",
    0x11: "MTHI",
    0x12: "MFLO",
    0x13: "MTLO",
    0x18: "MULT",
    0x19: "MULTU",
    0x1A: "DIV",
    0x1B: "DIVU",
    0x20: "ADD",
    0x21: "ADDU",
    0x22: "SUB",
    0x23: "SUBU",
    0x24: "AND",
    0x25: "OR",
    0x26: "XOR",
    0x27: "NOR",
    0x2A: "SLT",
    0x2B: "SLTU",
}

REGIMM_RT = {
    0x00: "BLTZ",
    0x01: "BGEZ",
    0x10: "BLTZAL",
    0x11: "BGEZAL",
}

COP0_RS = {
    0x00: "MFC0",
    0x04: "MTC0",
    0x10: "COP0_FUNC",   # CO=1; funct disambiguates (RFE=0x10)
}

COP2_RS = {
    0x00: "MFC2",
    0x02: "CFC2",
    0x04: "MTC2",
    0x06: "CTC2",
    # rs >= 0x10 -> GTE function (CO=1); funct field selects GTE op
}

# Categories for opcodes the BIOS uses.
def categorize_primary(op):
    if op in (0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,
              0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F):
        return "CPU"
    if 0x20 <= op <= 0x2E:
        return "CPU"
    if op == 0x10:
        return "COP0"
    if op == 0x11:
        return "PRIVILEGED_OR_DATA"   # COP1: PS1 has no FPU
    if op == 0x12 or op == 0x32 or op == 0x3A:
        return "COP2_GTE"
    if op == 0x13 or op == 0x33 or op == 0x3B:
        return "PRIVILEGED_OR_DATA"   # COP3: PS1 has no COP3
    if op in (0x30, 0x31, 0x38, 0x39):
        return "PRIVILEGED_OR_DATA"   # LWCx/SWCx for cop0/cop1: not used in BIOS
    return "UNKNOWN"


def classify(raw, addr):
    """Return (bucket_key, mnemonic, category)."""
    if raw == 0:
        return (("NOP", "none", 0), "NOP", "CPU")

    op = (raw >> 26) & 0x3F

    if op == 0x00:
        funct = raw & 0x3F
        mnem = SPECIAL_FUNCT.get(funct, f"SPECIAL_funct_0x{funct:02X}")
        cat = "CPU" if funct in SPECIAL_FUNCT else "UNKNOWN"
        return ((op, "funct", funct), mnem, cat)

    if op == 0x01:
        rt = (raw >> 16) & 0x1F
        mnem = REGIMM_RT.get(rt, f"REGIMM_rt_0x{rt:02X}")
        cat = "CPU" if rt in REGIMM_RT else "UNKNOWN"
        return ((op, "rt", rt), mnem, cat)

    if op == 0x10:
        # COP0
        if raw == 0x42000010:
            return ((op, "rfe", 0), "RFE", "COP0")
        rs = (raw >> 21) & 0x1F
        if rs == 0x10:  # CO=1 -> coprocessor function (only RFE we expect)
            return ((op, "rs_cop0", rs), "COP0_FUNC_NONRFE", "COP0")
        mnem = COP0_RS.get(rs, f"COP0_rs_0x{rs:02X}")
        cat = "COP0" if rs in COP0_RS else "UNKNOWN"
        return ((op, "rs_cop0", rs), mnem, cat)

    if op == 0x12:
        rs = (raw >> 21) & 0x1F
        if rs >= 0x10:  # GTE function (CO=1)
            return ((op, "cop2_cofun", 0x10), "COP2_GTE_FUNC", "COP2_GTE")
        mnem = COP2_RS.get(rs, f"COP2_rs_0x{rs:02X}")
        return ((op, "rs_cop2", rs), mnem, "COP2_GTE")

    if op in OP_PRIMARY:
        mnem, _ = OP_PRIMARY[op]
        return ((op, "none", 0), mnem, categorize_primary(op))

    return ((op, "none", 0), f"PRIMARY_0x{op:02X}", "UNKNOWN")


def addr_to_offset(addr):
    return addr - IMAGE_BASE


def offset_to_addr(off):
    return IMAGE_BASE + off


def fetch(rom, addr):
    off = addr_to_offset(addr)
    if off < 0 or off + 4 > ROM_SIZE:
        return None
    return struct.unpack_from("<I", rom, off)[0]


def branch_target(addr, raw):
    """
    Compute branch/jump target if `raw` is a control-flow instruction.
    Returns (kind, target_or_None) where kind is one of:
      'cond_branch' : conditional branch, fall-through possible
      'jump'        : unconditional J/B (no fall-through)
      'jr'          : indirect jump (terminator, no in-function target)
      'call'        : JAL/JALR (returns, falls through to addr+8)
      'syscall'     : syscall (treated as fall-through; BIOS uses it as
                      a regular call out via exception handler that
                      returns)
      'break'       : break (treated as fall-through; same reasoning —
                      BREAK 0x401 is the BIOS-internal divide-by-zero
                      and similar checks where the handler returns)
      'normal'      : ordinary instruction, falls through
    target is computed for cond_branch and jump only.
    """
    op = (raw >> 26) & 0x3F
    # Conditional branches: BEQ/BNE/BLEZ/BGTZ + REGIMM BLTZ/BGEZ/BLTZAL/BGEZAL
    if op in (0x04, 0x05, 0x06, 0x07):
        simm = raw & 0xFFFF
        if simm & 0x8000:
            simm -= 0x10000
        target = addr + 4 + (simm << 2)
        return ("cond_branch", target)
    if op == 0x01:
        # REGIMM. rt selects sub-op. 0x10/0x11 are BLTZAL/BGEZAL (also calls).
        simm = raw & 0xFFFF
        if simm & 0x8000:
            simm -= 0x10000
        target = addr + 4 + (simm << 2)
        return ("cond_branch", target)
    if op == 0x02:  # J
        target = ((addr + 4) & 0xF0000000) | ((raw & 0x03FFFFFF) << 2)
        return ("jump", target)
    if op == 0x03:  # JAL
        target = ((addr + 4) & 0xF0000000) | ((raw & 0x03FFFFFF) << 2)
        return ("call", target)
    if op == 0x00:
        funct = raw & 0x3F
        if funct == 0x08:  # JR
            return ("jr", None)
        if funct == 0x09:  # JALR
            return ("call", None)
        if funct == 0x0C:  # SYSCALL
            return ("syscall", None)
        if funct == 0x0D:  # BREAK
            return ("break", None)
    # COP1/COP2 conditional branches (BC1F/BC1T/BC2F/BC2T):
    # primary opcode 0x11 or 0x12, rs field == 0x08.
    if op in (0x11, 0x12):
        rs = (raw >> 21) & 0x1F
        if rs == 0x08:
            simm = raw & 0xFFFF
            if simm & 0x8000:
                simm -= 0x10000
            target = addr + 4 + (simm << 2)
            return ("cond_branch", target)
    return ("normal", None)


def walk_function(rom, entry, hard_cap):
    """
    BFS reachability walker. Starts at `entry`, follows fall-through and
    in-function branch targets, stops at JR/J terminators (after their
    delay slot). Returns:
      - list of (addr, raw) for every reachable instruction (sorted by
        addr)
      - end_address as the LAST BYTE of the highest-addr reachable
        instruction (matches Ghidra's body end convention)

    Constraints:
      - hard_cap: never visit addr >= hard_cap (prevents bleed into the
        next function or into inter-function data)
      - delay slot: every control transfer's addr+4 is always visited
      - JR/J have no fall-through; conditional branches and calls do
      - cross-function targets (target < entry or target >= hard_cap)
        are NOT followed; they're recorded as out-of-function calls or
        tail-jumps for the indirect-jump phase later
    """
    visited = {}  # addr -> raw
    work = [entry]

    def visit_delay_slot(addr):
        """Mark a delay-slot instruction visited without enqueuing its
        fall-through. Delay slots are reached only via the control
        transfer above them, so they must NOT independently extend the
        walk."""
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
            # JAL/JALR: delay slot is reached, then control returns to
            # addr+8. Cross-function call target is NOT followed.
            visit_delay_slot(delay)
            work.append(addr + 8)
            continue
        if kind in ("syscall", "break"):
            # BIOS uses these as in-line traps that return; fall through.
            work.append(addr + 4)
            continue
        # normal
        work.append(addr + 4)

    if not visited:
        return [], entry + 3
    pairs = sorted(visited.items())
    last_addr = pairs[-1][0]
    return pairs, last_addr + 3


def main():
    if not os.path.exists(BIOS_PATH):
        print(f"ERROR: BIOS not found at {BIOS_PATH}", file=sys.stderr)
        return 2
    if not os.path.exists(STARTS_PATH):
        print(f"ERROR: function starts not found at {STARTS_PATH}", file=sys.stderr)
        return 2

    with open(BIOS_PATH, "rb") as f:
        rom = f.read()
    if len(rom) != ROM_SIZE:
        print(f"ERROR: BIOS size {len(rom)} != expected {ROM_SIZE}", file=sys.stderr)
        return 2

    with open(STARTS_PATH, "r", encoding="utf-8") as f:
        starts_doc = json.load(f)

    starts = [int(s, 16) for s in starts_doc["function_starts"]]
    if sorted(starts) != starts:
        print("ERROR: function_starts not sorted ascending", file=sys.stderr)
        return 2
    if len(starts) != starts_doc["function_count"]:
        print("ERROR: function_starts length != function_count", file=sys.stderr)
        return 2

    verified = starts_doc.get("verified_function_bodies", [])

    # Walk synthetic seeds first (reset vector + ROM-side exception vectors).
    walks = []
    for (entry, cap, label) in SYNTHETIC_SEEDS:
        instrs, end_addr = walk_function(rom, entry, cap)
        walks.append({
            "entry": entry,
            "end": end_addr,
            "instr_count": len(instrs),
            "instrs": instrs,
            "kind": "synthetic_seed",
            "label": label,
            "hard_cap": cap,
        })

    # Walk every Ghidra-known function.
    for i, entry in enumerate(starts):
        cap = starts[i + 1] if i + 1 < len(starts) else (IMAGE_END + 1)
        instrs, end_addr = walk_function(rom, entry, cap)
        walks.append({
            "entry": entry,
            "end": end_addr,
            "instr_count": len(instrs),
            "instrs": instrs,
            "kind": "ghidra_function",
        })

    # Verify against Ghidra-sampled bodies (Ghidra functions only).
    by_entry = {w["entry"]: w for w in walks if w.get("kind") == "ghidra_function"}
    verification = []
    verification_failed = False
    for v in verified:
        ent = int(v["entry"], 16)
        ghidra_end = int(v["end"], 16)
        w = by_entry.get(ent)
        if w is None:
            verification.append({
                "entry": v["entry"],
                "ghidra_end": v["end"],
                "walker_end": None,
                "match": False,
                "reason": "function not in walker output",
            })
            verification_failed = True
            continue
        match = (w["end"] == ghidra_end)
        verification.append({
            "entry": v["entry"],
            "ghidra_end": v["end"],
            "walker_end": f"0x{w['end']:08x}",
            "match": match,
        })
        if not match:
            verification_failed = True

    if verification_failed:
        print("ERROR: walker disagreed with Ghidra on at least one verified function:",
              file=sys.stderr)
        for v in verification:
            if not v.get("match"):
                print(f"  {v['entry']}: ghidra={v['ghidra_end']} walker={v['walker_end']}",
                      file=sys.stderr)
        # Still write a partial artifact for inspection, but exit non-zero.
        with open(OUT_PATH + ".verification_failure.json", "w", encoding="utf-8") as f:
            json.dump({"verification": verification}, f, indent=2)
        return 3

    # Union all walked instructions into a single (addr -> raw) map so that
    # overlapping walks (e.g. synthetic reset-vector seed and Ghidra function
    # walks that share addresses) do not double-count. Each unique address
    # is counted exactly once. If two walks disagree about the bytes at an
    # address, that's a real corruption finding and we abort.
    all_instrs = {}
    for w in walks:
        for (addr, raw) in w["instrs"]:
            existing = all_instrs.get(addr)
            if existing is not None and existing != raw:
                print(
                    f"ERROR: walks disagree at 0x{addr:08x}: 0x{existing:08x} vs 0x{raw:08x}",
                    file=sys.stderr,
                )
                return 5
            all_instrs[addr] = raw

    # Build the inventory buckets from the deduped union.
    buckets = {}
    total_instrs = 0
    for addr in sorted(all_instrs.keys()):
        raw = all_instrs[addr]
        if True:
            total_instrs += 1
            key, mnem, cat = classify(raw, addr)
            key_s = f"{key[0]}|{key[1]}|{key[2]}"
            b = buckets.get(key_s)
            if b is None:
                b = {
                    "key": {
                        "primary_opcode_hex": f"0x{key[0]:02X}" if isinstance(key[0], int) else key[0],
                        "sub_kind": key[1],
                        "sub_value_hex": f"0x{key[2]:02X}",
                    },
                    "mnemonic": mnem,
                    "category": cat,
                    "count": 0,
                    "examples": [],
                }
                buckets[key_s] = b
            b["count"] += 1
            if len(b["examples"]) < 3:
                b["examples"].append({
                    "address": f"0x{addr:08x}",
                    "raw": f"0x{raw:08x}",
                })

    # Stable ordering by mnemonic then count desc.
    bucket_list = sorted(
        buckets.values(),
        key=lambda b: (b["category"], b["mnemonic"], -b["count"]),
    )

    unknown_count = sum(b["count"] for b in bucket_list if b["category"] == "UNKNOWN")
    has_unknown = unknown_count > 0

    synth_walks = [w for w in walks if w.get("kind") == "synthetic_seed"]
    out_doc = {
        "schema": "psxrecomp phase1b instruction_inventory v2",
        "program": "SCPH1001.BIN",
        "image_base": "0xbfc00000",
        "image_end": "0xbfc7ffff",
        "source_function_count": len(starts),
        "walker": {
            "strategy": "BFS reachability from each seed: visit linear fall-through, in-function direct/conditional branch targets, and JAL/JALR delay-slot+return; terminate paths on JR/J after their delay slot. Conditional branches enqueue both taken target and post-delay fall-through. Delay slots are visited inline (never re-enqueued) so they cannot extend the walk on their own.",
            "verification": verification,
            "synthetic_seeds": [
                {
                    "label": w["label"],
                    "entry": f"0x{w['entry']:08x}",
                    "hard_cap": f"0x{w['hard_cap']:08x}",
                    "end": f"0x{w['end']:08x}",
                    "instr_count": w["instr_count"],
                }
                for w in synth_walks
            ],
        },
        "totals": {
            "instructions_walked": total_instrs,
            "distinct_buckets": len(bucket_list),
            "unknown_bucket_instructions": unknown_count,
        },
        "buckets": bucket_list,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out_doc, f, indent=2)

    print(f"Wrote {OUT_PATH}")
    print(f"  functions walked   : {len(starts)}")
    print(f"  instructions walked: {total_instrs}")
    print(f"  distinct buckets   : {len(bucket_list)}")
    print(f"  unknown instr count: {unknown_count}")
    if has_unknown and "--allow-unknown" not in sys.argv:
        print("ERROR: unknown opcode buckets present and --allow-unknown not given",
              file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
