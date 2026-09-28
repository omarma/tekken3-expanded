"""B0 schema verification: parse both audit configs and check shape.

Confirms tools/* can rely on a stable layout. If this passes, B1 can
proceed to consume the configs.
"""
import sys
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib

ROOT = Path(__file__).parent.parent

def hex_int(s, field):
    if not isinstance(s, str): raise ValueError(f"{field}: expected hex string, got {type(s).__name__}")
    return int(s, 16)

def validate(path, expect_remaps):
    print(f"\n=== {path} ===")
    with open(path, "rb") as f:
        cfg = tomllib.load(f)

    # Program info: accept [program] (BIOS / non-game) or [game] (game convention).
    p = cfg.get("program") or cfg.get("game")
    if p is None:
        raise KeyError("config has neither [program] nor [game] block")
    rom_field = p.get("rom") or p.get("exe")   # [program].rom or [game].exe
    if rom_field is None:
        raise KeyError("program/game block missing rom/exe path")
    print(f"  program.name        = {p['name']!r}")
    print(f"  program.rom         = {rom_field!r}")
    print(f"  program.load_address = {p['load_address']} = 0x{hex_int(p['load_address'], 'load_address'):08X}")
    print(f"  program.text_size   = {p['text_size']} = 0x{hex_int(p['text_size'], 'text_size'):08X}")

    # [audit] block
    a = cfg["audit"]

    fs = a.get("function_starts")
    print(f"  audit.function_starts = {fs!r}")

    regions = a["regions"]
    print(f"  audit.regions      = {len(regions)} region(s)")
    for r in regions:
        lo = hex_int(r["rom_start"], "rom_start")
        hi = hex_int(r["rom_end"], "rom_end")
        va = hex_int(r["vaddr_base"], "vaddr_base")
        print(f"    - {r['name']:8s}  rom 0x{lo:05X}..0x{hi:05X}  vaddr base 0x{va:08X}  ({hi-lo} bytes)")

    norm = a["normalize"]
    mask = hex_int(norm["kseg_mask"], "kseg_mask")
    print(f"  audit.normalize.kseg_mask = 0x{mask:08X}")

    remaps = norm.get("remap", [])
    print(f"  audit.normalize.remap     = {len(remaps)} remap(s)")
    assert len(remaps) == expect_remaps, f"expected {expect_remaps} remaps, got {len(remaps)}"
    for rm in remaps:
        flo = hex_int(rm["from_lo"], "from_lo")
        fhi = hex_int(rm["from_hi"], "from_hi")
        tlo = hex_int(rm["to_lo"], "to_lo")
        print(f"    - 0x{flo:08X}..0x{fhi:08X} -> +0x{tlo:X}  ({rm.get('description','')})")

    return cfg

bios = validate(ROOT / "bios" / "SCPH1001.toml", expect_remaps=2)
tomba = validate(Path("../TombaRecomp/game.toml"), expect_remaps=0)
print("\nOK: both configs parse and validate.")
