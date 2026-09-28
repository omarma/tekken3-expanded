#!/usr/bin/env python3
"""
build_instruction_coverage.py

Phase 1b artifact builder. Reads generated/instruction_inventory.json and
emits generated/instruction_coverage.json marking each inventory bucket
as one of:

  - "implemented"            : strict_translator.cpp emits real C for it
  - "missing"                : not yet implemented; Phase 1b work item
  - "deferred_phase5_or_trap": COP1/FPU instructions; PS1 has no FPU,
                               so these are either dead BIOS code or
                               trap-emulated. Decision deferred.

The "implemented" table is hand-extracted from strict_translator.cpp by
reading the dispatch in StrictTranslator::translate. It includes the
source line ranges so the coverage file is auditable.

This script is the gap-list step of Phase 1b. It does NOT modify the
strict translator. After this script runs, look at
generated/instruction_coverage.json and decide what to add next.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INVENTORY_PATH = os.path.join(ROOT, "generated", "instruction_inventory.json")
OUT_PATH = os.path.join(ROOT, "generated", "instruction_coverage.json")
TRANSLATOR_PATH = "recompiler/src/strict_translator.cpp"


# Bucket key string format from build_instruction_inventory.py:
#   "{primary_opcode}|{sub_kind}|{sub_value}"
# where primary_opcode is the int (or "NOP" for the synthetic NOP bucket).

# Each entry: bucket key string -> (mnemonic, status, source_ref_or_reason)
IMPLEMENTED = {
    # NOP (raw == 0) — strict_translator.cpp:54-59
    "NOP|none|0": ("NOP", f"{TRANSLATOR_PATH}:54-59"),
    # SPECIAL funct table
    # SLL — :72-78
    "0|funct|0": ("SLL", f"{TRANSLATOR_PATH}:72-78"),
    # Shifts batch (Phase 1b B(3))
    "0|funct|2": ("SRL",  f"{TRANSLATOR_PATH} SPECIAL funct 0x02 (logical right shift, literal shamt)"),
    "0|funct|3": ("SRA",  f"{TRANSLATOR_PATH} SPECIAL funct 0x03 (arithmetic right shift via int32_t cast, literal shamt)"),
    "0|funct|4": ("SLLV", f"{TRANSLATOR_PATH} SPECIAL funct 0x04 (variable shift, rs[4:0] via & 0x1Fu mask)"),
    "0|funct|6": ("SRLV", f"{TRANSLATOR_PATH} SPECIAL funct 0x06 (variable logical right, rs[4:0] via & 0x1Fu mask; ISA-completeness exception, zero inventory hits)"),
    "0|funct|7": ("SRAV", f"{TRANSLATOR_PATH} SPECIAL funct 0x07 (variable arithmetic right, rs[4:0] via & 0x1Fu mask)"),
    # HI/LO + multiply/divide batch (Phase 1b B(4))
    "0|funct|16": ("MFHI",  f"{TRANSLATOR_PATH} SPECIAL funct 0x10 (read cpu->hi)"),
    "0|funct|18": ("MFLO",  f"{TRANSLATOR_PATH} SPECIAL funct 0x12 (read cpu->lo)"),
    "0|funct|25": ("MULTU", f"{TRANSLATOR_PATH} SPECIAL funct 0x19 (uint64 product into HI:LO)"),
    "0|funct|26": ("DIV",   f"{TRANSLATOR_PATH} SPECIAL funct 0x1A (signed; guards div-by-zero and INT32_MIN/-1 to match R3000A)"),
    "0|funct|27": ("DIVU",  f"{TRANSLATOR_PATH} SPECIAL funct 0x1B (unsigned; guards div-by-zero to match R3000A)"),
    # Conditional branches (Phase 1b B(5))
    "4|none|0":  ("BEQ",  f"{TRANSLATOR_PATH} primary 0x04 (terminator; PC-relative target = pc+4+simm*4)"),
    "5|none|0":  ("BNE",  f"{TRANSLATOR_PATH} primary 0x05 (terminator; PC-relative target = pc+4+simm*4)"),
    "6|none|0":  ("BLEZ", f"{TRANSLATOR_PATH} primary 0x06 (terminator; signed compare against 0)"),
    "7|none|0":  ("BGTZ", f"{TRANSLATOR_PATH} primary 0x07 (terminator; signed compare against 0)"),
    "1|rt|0":    ("BLTZ", f"{TRANSLATOR_PATH} REGIMM rt 0x00 (terminator; signed compare against 0)"),
    "1|rt|1":    ("BGEZ", f"{TRANSLATOR_PATH} REGIMM rt 0x01 (terminator; signed compare against 0)"),
    # JR — case 0x08 in SPECIAL switch (Phase 1a)
    "0|funct|8": ("JR", f"{TRANSLATOR_PATH} SPECIAL funct 0x08"),
    # JALR — case 0x09 in SPECIAL switch (Phase 1a)
    "0|funct|9": ("JALR", f"{TRANSLATOR_PATH} SPECIAL funct 0x09"),
    # ALU R-type batch (Phase 1b B(1))
    "0|funct|32": ("ADD",  f"{TRANSLATOR_PATH} SPECIAL funct 0x20 (overflow-checked, calls psx_arith_overflow on trap)"),
    "0|funct|33": ("ADDU", f"{TRANSLATOR_PATH} SPECIAL funct 0x21"),
    "0|funct|35": ("SUBU", f"{TRANSLATOR_PATH} SPECIAL funct 0x23"),
    "0|funct|36": ("AND",  f"{TRANSLATOR_PATH} SPECIAL funct 0x24"),
    "0|funct|37": ("OR",   f"{TRANSLATOR_PATH} SPECIAL funct 0x25"),
    "0|funct|38": ("XOR",  f"{TRANSLATOR_PATH} SPECIAL funct 0x26"),
    "0|funct|39": ("NOR",  f"{TRANSLATOR_PATH} SPECIAL funct 0x27"),
    "0|funct|42": ("SLT",  f"{TRANSLATOR_PATH} SPECIAL funct 0x2A"),
    "0|funct|43": ("SLTU", f"{TRANSLATOR_PATH} SPECIAL funct 0x2B"),
    # Primary opcodes
    # J 0x02 — :112-123
    "2|none|0": ("J", f"{TRANSLATOR_PATH}:112-123"),
    # JAL 0x03 — :126-138
    "3|none|0": ("JAL", f"{TRANSLATOR_PATH}:126-138"),
    # ADDIU 0x09 — :141-151
    "9|none|0": ("ADDIU", f"{TRANSLATOR_PATH}:141-151"),
    # ORI 0x0D — :154-163
    "13|none|0": ("ORI", f"{TRANSLATOR_PATH}:154-163"),
    # ALU I-type batch (Phase 1b B(2))
    "8|none|0":  ("ADDI",  f"{TRANSLATOR_PATH} primary 0x08 (overflow-checked, calls psx_arith_overflow on trap)"),
    "10|none|0": ("SLTI",  f"{TRANSLATOR_PATH} primary 0x0A"),
    "11|none|0": ("SLTIU", f"{TRANSLATOR_PATH} primary 0x0B (sign-extends imm then unsigned-compares)"),
    "12|none|0": ("ANDI",  f"{TRANSLATOR_PATH} primary 0x0C (zero-extended imm)"),
    "14|none|0": ("XORI",  f"{TRANSLATOR_PATH} primary 0x0E (zero-extended imm)"),
    # LUI 0x0F — :166-174
    "15|none|0": ("LUI", f"{TRANSLATOR_PATH}:166-174"),
    # SW 0x2B — Phase 1a, updated in B(7) to include addr & 3 alignment check
    "43|none|0": ("SW", f"{TRANSLATOR_PATH} primary 0x2B (4-aligned; addr & 3 -> psx_unaligned_access)"),
    # Loads (Phase 1b B(6); LH/LHU/LW updated in B(7) to include alignment checks)
    "32|none|0": ("LB",  f"{TRANSLATOR_PATH} primary 0x20 (sign-extended byte; $zero variant uses (void) to keep the read side effect; no alignment requirement)"),
    "33|none|0": ("LH",  f"{TRANSLATOR_PATH} primary 0x21 (sign-extended halfword; 2-aligned; addr & 1 -> psx_unaligned_access)"),
    "35|none|0": ("LW",  f"{TRANSLATOR_PATH} primary 0x23 (32-bit word; 4-aligned; addr & 3 -> psx_unaligned_access)"),
    "36|none|0": ("LBU", f"{TRANSLATOR_PATH} primary 0x24 (zero-extended byte; $zero variant keeps read side effect; no alignment requirement)"),
    "37|none|0": ("LHU", f"{TRANSLATOR_PATH} primary 0x25 (zero-extended halfword; 2-aligned; addr & 1 -> psx_unaligned_access)"),
    # Unaligned word loads (Phase 1b B(9))
    "34|none|0": ("LWL", f"{TRANSLATOR_PATH} primary 0x22 (little-endian unaligned high-bytes load; merges with old rt; no alignment fault by design)"),
    "38|none|0": ("LWR", f"{TRANSLATOR_PATH} primary 0x26 (little-endian unaligned low-bytes load; merges with old rt; no alignment fault by design)"),
    # Stores (Phase 1b B(7))
    "40|none|0": ("SB",  f"{TRANSLATOR_PATH} primary 0x28 (byte store; no alignment requirement)"),
    "41|none|0": ("SH",  f"{TRANSLATOR_PATH} primary 0x29 (halfword store; 2-aligned; addr & 1 -> psx_unaligned_access)"),
    "42|none|0": ("SWL", f"{TRANSLATOR_PATH} primary 0x2A (unaligned high-bytes word store; no alignment fault by design)"),
    "46|none|0": ("SWR", f"{TRANSLATOR_PATH} primary 0x2E (unaligned low-bytes word store; no alignment fault by design)"),
    # COP0 RFE (raw 0x42000010) — :191-205
    "16|rfe|0": ("RFE", f"{TRANSLATOR_PATH}:191-205"),
    # COP0 access (Phase 1b B(8))
    "16|rs_cop0|0": ("MFC0", f"{TRANSLATOR_PATH} primary 0x10 rs 0x00 (gpr[rt] = cop0[rd]; respects $zero via emit_gpr_write; no SR-write hooks)"),
    "16|rs_cop0|4": ("MTC0", f"{TRANSLATOR_PATH} primary 0x10 rs 0x04 (cop0[rd] = gpr[rt]; cop0[0] is Index, not zero; no IRQ delivery)"),
    # Traps (Phase 1b B(10), final batch)
    "0|funct|12": ("SYSCALL", f"{TRANSLATOR_PATH} SPECIAL funct 0x0C (non-terminator; calls psx_syscall(cpu, gpr[2]) then return; no exception model)"),
    "0|funct|13": ("BREAK",   f"{TRANSLATOR_PATH} SPECIAL funct 0x0D (non-terminator; calls psx_break(cpu, code, pc) then return; no exception model)"),
}

# Buckets we explicitly defer rather than implement now.
DEFERRED = {
    # COP1 (0x11) — PS1 R3000A has no FPU. Bytes appear in BIOS atof-style
    # routines (e.g., FUN_bfc02324). Decision: defer until Phase 1c shows
    # whether any of these functions are actually reachable from the reset
    # vector. If reachable, must be implemented as a trap or as software FP.
    "17|none|0": ("COP1", "FPU; PS1 has no COP1 hardware. Decide after Phase 1c reachability proves whether the BIOS atof routines are live."),
    # LWC1 0x31 — same reasoning
    "49|none|0": ("LWC1", "FPU load; same rationale as COP1."),
    # SWC1 0x39 (not in inventory but listed for completeness if it ever appears)
}


def bucket_key_string(b):
    k = b["key"]
    p = k["primary_opcode_hex"]
    if p == "NOP":
        prim = "NOP"
    else:
        prim = str(int(p, 16))
    sub = k["sub_kind"]
    sv = str(int(k["sub_value_hex"], 16))
    return f"{prim}|{sub}|{sv}"


def main():
    if not os.path.exists(INVENTORY_PATH):
        print(f"ERROR: inventory not found at {INVENTORY_PATH}", file=sys.stderr)
        return 2

    with open(INVENTORY_PATH, "r", encoding="utf-8") as f:
        inv = json.load(f)

    rows = []
    impl_total = 0
    miss_total = 0
    def_total = 0

    for b in inv["buckets"]:
        key = bucket_key_string(b)
        row = {
            "bucket_key": key,
            "primary_opcode_hex": b["key"]["primary_opcode_hex"],
            "sub_kind": b["key"]["sub_kind"],
            "sub_value_hex": b["key"]["sub_value_hex"],
            "mnemonic": b["mnemonic"],
            "category": b["category"],
            "count": b["count"],
            "first_example": b["examples"][0]["address"] if b["examples"] else None,
        }
        if key in IMPLEMENTED:
            row["status"] = "implemented"
            row["source"] = IMPLEMENTED[key][1]
            impl_total += 1
        elif key in DEFERRED:
            row["status"] = "deferred"
            row["reason"] = DEFERRED[key][1]
            def_total += 1
        else:
            row["status"] = "missing"
            miss_total += 1
        rows.append(row)

    # Also surface implemented handlers that have no inventory bucket
    # (i.e., handlers we wrote in Phase 1a that nothing in the BIOS
    # functions hits).
    inv_keys = {bucket_key_string(b) for b in inv["buckets"]}
    implemented_unused = []
    for key, (mnem, src) in IMPLEMENTED.items():
        if key not in inv_keys:
            implemented_unused.append({
                "bucket_key": key,
                "mnemonic": mnem,
                "source": src,
                "note": "Implemented in strict_translator but not observed in any walked BIOS function. May be needed for code that lives in copy-to-RAM bytes (exception handler) — re-evaluate after Phase 1e relocation work.",
            })

    summary = {
        "schema": "psxrecomp phase1b instruction_coverage v1",
        "inventory_source": "generated/instruction_inventory.json",
        "translator_source": TRANSLATOR_PATH,
        "totals": {
            "inventory_buckets": len(rows),
            "implemented": impl_total,
            "missing": miss_total,
            "deferred": def_total,
            "implemented_but_unused_in_inventory": len(implemented_unused),
        },
        "rows": sorted(
            rows,
            key=lambda r: (r["status"], r["category"], r["mnemonic"]),
        ),
        "implemented_but_unused": implemented_unused,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"Wrote {OUT_PATH}")
    print(f"  inventory buckets : {len(rows)}")
    print(f"  implemented       : {impl_total}")
    print(f"  missing           : {miss_total}")
    print(f"  deferred          : {def_total}")
    print(f"  impl-but-unused   : {len(implemented_unused)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
