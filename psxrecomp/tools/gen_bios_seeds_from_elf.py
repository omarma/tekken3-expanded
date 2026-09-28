#!/usr/bin/env python3
"""gen_bios_seeds_from_elf.py — BIOS discovery seeds from ELF symbol tables.

For an open-source BIOS built from source (OpenBIOS), the linker knows every
function start exactly — no Ghidra pass over a proprietary blob needed. This
tool reads STT_FUNC symbols out of one or more ELFs (the main BIOS ELF plus
any separately-linked embedded payloads, e.g. OpenBIOS's shell.elf) and emits
the seeds JSON that psxrecomp-bios --emit-full consumes.

Symbols whose virtual address lies in RAM (relocated code: OpenBIOS's
.ramtext blob at 0x500, the shell at 0x80030000) are folded BACK to their ROM
source through the BIOS profile's [recompiler.address_model] copy table — the
tool takes the profile as input precisely so it cannot invent an address
model of its own. Symbols that fold nowhere are dropped and reported.

Output-format contract (the consumer is the hand-rolled brace scanner in
recompiler/src/main_bios.cpp load_seeds(), NOT a JSON library):
  1. no '[' or ']' inside any emitted string (depth counting ignores quotes);
  2. per-object field order is address, label, rationale (later fields are
     only found if they appear after "address" within the object);
  3. ASCII only, no '"' or backslash in strings (no escape handling).

Usage:
  gen_bios_seeds_from_elf.py --profile bios/OpenBIOS.toml \
      --elf path/to/openbios.elf [--elf path/to/shell.elf ...] \
      --out recompiler/seeds/openbios_elf_seeds.json
"""

import argparse
import json
import os
import re
import struct
import sys

KSEG_MASK = 0x1FFFFFFF


def parse_profile(path):
    """Crude single-purpose parse of the profile: load_address, text_size and
    the [[recompiler.address_model.copy]] entries. The tracked profiles are
    authored as simple `key = "value"` lines, which is all this reads."""
    text = open(path, encoding="utf-8").read()

    def top_value(key, default=None):
        m = re.search(r'^\s*%s\s*=\s*"([^"]+)"' % key, text, re.M)
        return m.group(1) if m else default

    load_address = int(top_value("load_address", "0xBFC00000"), 16)
    text_size = int(top_value("text_size", "0x80000"), 16)

    copies = []
    for block in re.findall(
            r'\[\[recompiler\.address_model\.copy\]\](.*?)(?=\n\[|\Z)',
            text, re.S):
        def v(key, blk=block):
            m = re.search(r'^\s*%s\s*=\s*"([^"]+)"' % key, blk, re.M)
            return m.group(1) if m else None
        copies.append({
            "name": v("name") or "?",
            "rom_lo": int(v("rom_lo"), 16),
            "rom_hi": int(v("rom_hi"), 16),
            "ram_lo": int(v("ram_lo"), 16),
        })
    return load_address & KSEG_MASK, text_size, copies


def read_elf(path):
    """Parse an ELF32-LE (EM_MIPS): returns (data, sections) with each
    section's name/type/flags/addr/offset/size/link/entsize."""
    data = open(path, "rb").read()
    if data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 1:
        raise SystemExit(f"{path}: not a little-endian ELF32")
    (e_machine,) = struct.unpack_from("<H", data, 18)
    if e_machine != 8:
        raise SystemExit(f"{path}: e_machine={e_machine}, expected EM_MIPS(8)")
    e_shoff, = struct.unpack_from("<I", data, 32)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", data, 46)

    sections = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        name, stype, flags, addr, offset, size, link, info, align, entsize = \
            struct.unpack_from("<10I", data, off)
        sections.append(dict(name=name, type=stype, flags=flags, addr=addr,
                             offset=offset, size=size, link=link,
                             entsize=entsize))
    return data, sections


def read_elf_funcs(path):
    """Yield (vaddr, size, name) for defined STT_FUNC symbols."""
    data, sections = read_elf(path)
    for sec in sections:
        if sec["type"] != 2:          # SHT_SYMTAB
            continue
        strtab = sections[sec["link"]]
        count = sec["size"] // (sec["entsize"] or 16)
        for i in range(count):
            off = sec["offset"] + i * (sec["entsize"] or 16)
            st_name, st_value, st_size, st_info, st_other, st_shndx = \
                struct.unpack_from("<IIIBBH", data, off)
            if st_info & 0xF != 2:    # STT_FUNC
                continue
            if st_shndx == 0 or st_value == 0:   # undefined
                continue
            end = data.index(b"\0", strtab["offset"] + st_name)
            name = data[strtab["offset"] + st_name:end].decode(
                "ascii", errors="replace")
            yield st_value, st_size, name


SHF_ALLOC, SHF_EXECINSTR = 0x2, 0x4


def read_elf_code_pointers(path):
    """Yield vaddrs of words in allocated NON-code sections that point into
    a code section. Catches computed-goto label tables and function-pointer
    tables (e.g. GCC's vxprintf format dispatch), which have no symbols and
    which the Sony-era jump-table pattern matcher does not recognize. A data
    word that merely looks like a code address seeds a bogus walk; discovery
    and the strict translator skip what does not decode, so the cost is a
    dead stub, not a miscompile."""
    data, sections = read_elf(path)
    code_ranges = [(s["addr"], s["addr"] + s["size"]) for s in sections
                   if s["flags"] & SHF_EXECINSTR and s["size"]]
    for sec in sections:
        if sec["type"] != 1:                    # SHT_PROGBITS
            continue
        if not (sec["flags"] & SHF_ALLOC) or (sec["flags"] & SHF_EXECINSTR):
            continue
        for off in range(sec["offset"], sec["offset"] + (sec["size"] & ~3), 4):
            (w,) = struct.unpack_from("<I", data, off)
            if w & 3:
                continue
            if any(lo <= w < hi for lo, hi in code_ranges):
                yield w


def sanitize(s):
    """Enforce the brace-scanner string contract."""
    s = s.encode("ascii", errors="replace").decode("ascii")
    return re.sub(r'[\[\]"\\]', "_", s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--elf", action="append", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--extra", help="empirical dispatch-miss seeds JSON to merge "
                    "(same shape; the SCPH1001 dispatch_miss_seeds.json loop)")
    args = ap.parse_args()

    rom_base, rom_size, copies = parse_profile(args.profile)

    def fold(vaddr):
        phys = vaddr & KSEG_MASK
        if phys & 3:
            return None
        if rom_base <= phys < rom_base + rom_size:
            return phys
        for c in copies:
            ram_hi = c["ram_lo"] + (c["rom_hi"] - c["rom_lo"])
            if c["ram_lo"] <= phys < ram_hi:
                return c["rom_lo"] + (phys - c["ram_lo"])
        return None

    seeds = {}
    dropped = []
    # Each ELF's e_entry is an authoritative code entry point even when the
    # symbol at it is untyped assembly (shell.elf's _start): discovery walks
    # the whole crt0 call chain from it, reaching helpers that carry no
    # symbols at all.
    for elf in args.elf:
        data, _secs = read_elf(elf)
        (e_entry,) = struct.unpack_from("<I", data, 24)
        rom_phys = fold(e_entry)
        if rom_phys is not None:
            addr = 0xA0000000 | rom_phys
            base = sanitize(elf.replace(chr(92), "/").split("/")[-1]).replace(".", "_")
            seeds.setdefault(addr, (f"elf_entry_{base}", elf, "entry"))
    for elf in args.elf:
        for vaddr, size, name in read_elf_funcs(elf):
            rom_phys = fold(vaddr)
            if rom_phys is None:
                dropped.append((elf, vaddr, name, "outside ROM and every copy window"))
                continue
            addr = 0xA0000000 | rom_phys          # KSEG1, matches 0xBFCxxxxx
            if addr in seeds:
                continue                           # first name wins
            seeds[addr] = (sanitize(name), elf, "sym")

    # Second pass: code pointers found in data sections — computed-goto label
    # tables and function-pointer tables without symbols. Dedup against the
    # symbol seeds so a real function keeps its name.
    ptr_seeds = 0
    for elf in args.elf:
        for vaddr in read_elf_code_pointers(elf):
            rom_phys = fold(vaddr)
            if rom_phys is None:
                continue
            addr = 0xA0000000 | rom_phys
            if addr in seeds:
                continue
            seeds[addr] = (f"code_ptr_{addr:08X}", elf, "ptr")
            ptr_seeds += 1

    merge_note = ""
    if args.extra:
        if os.path.exists(args.extra):
            doc = json.load(open(args.extra, encoding="utf-8"))
            merged = 0
            for e in doc.get("seeds", []):
                addr = int(e["address"], 16)
                if addr not in seeds:
                    seeds[addr] = (sanitize(e.get("label", f"miss_{addr:08X}")),
                                   args.extra, "extra")
                    merged += 1
            print(f"  merged {merged} empirical seeds from {args.extra}")
            if merged:
                extra_base = sanitize(
                    args.extra.replace(chr(92), "/").split("/")[-1])
                merge_note = f" + {merged} empirical seeds from {extra_base}"

    RATIONALE = {
        "entry": "ELF entry point (e_entry) of ",
        "sym":   "ELF STT_FUNC symbol from ",
        "ptr":   "code pointer in a data section of ",
        "extra": "empirical dispatch-miss seed merged from ",
    }
    entries = []
    for addr in sorted(seeds):
        name, src, kind = seeds[addr]
        entries.append({
            "address": f"0x{addr:08X}",
            "label": name,
            "rationale": RATIONALE[kind]
                         + sanitize(src.replace(chr(92), "/").split("/")[-1]),
        })

    doc = {
        "schema": "psxrecomp phase2 seeds",
        "source": f"gen_bios_seeds_from_elf.py over {', '.join(sanitize(e.replace(chr(92), '/').split('/')[-1]) for e in args.elf)}{merge_note}",
        "seed_count": len(entries),
        "seeds": entries,
    }
    with open(args.out, "w", encoding="ascii", newline="\n") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")

    print(f"gen_bios_seeds_from_elf: {len(entries)} seeds "
          f"({ptr_seeds} from data-section code pointers) -> {args.out}")
    if dropped:
        print(f"  dropped {len(dropped)}:")
        for elf, vaddr, name, why in dropped[:20]:
            print(f"    0x{vaddr:08X} {name}: {why}")
        if len(dropped) > 20:
            print(f"    ... and {len(dropped) - 20} more")


if __name__ == "__main__":
    main()
