#!/usr/bin/env python3
"""Retrofit the window kinds of imported TTT1 move packs (<Name>-TTT1-combat*.jmv),
without a new import (B179, GH#221).

The converter copied a record's attributes as they are. Their bits 11..15 are
its window kind, numbered one higher in TTT1 from 12 on: TTT1's 13, the low
crush (a hit of id 0x10F does not touch a fighter in the airborne frames of
such a record: Yoshimitsu's Flea, u+1+2), is Tekken 3's 12, and TTT1's 12
has no T3 number (tools/ttt1/combat_semantics.py WINDOW_KINDS). Every 13
becomes 12; the four TTT1 records of kind 12 (Armor King's and Kunimitsu's,
known by their TTT1 address, the pack's provenance) become 14. A pack
already converted holds no 13, and those four no 12: running it again
changes nothing.

    python3 tools/ttt1_retrofit_window_kinds.py workspace/ttt1-import/roster
"""
import struct, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'ttt1'))
from combat_semantics import WINDOW_KINDS

# TTT1 records of window kind 12 (all of them, in every pack of the import).
KIND_12_RECORDS = (0x80067508, 0x8006753c, 0x8006aa0c, 0x8006abac)


def retrofit(data):
    """Rewrites `data` (a v4 combat pack) in place; number of records changed."""
    done = 0
    for i in range(struct.unpack_from('<I', data, 12)[0]):
        _, provenance, rp, _ = struct.unpack_from('<4I', data, 32 + i * 16)
        attributes = struct.unpack_from('<I', data, rp + 4)[0]
        kind = attributes >> 11 & 31
        if kind == 13 or (kind == 12 and provenance in KIND_12_RECORDS):
            struct.pack_into('<I', data, rp + 4, attributes & ~(31 << 11) | WINDOW_KINDS[kind] << 11)
            done += 1
    return done


def main(folders):
    for folder in folders:
        for path in sorted(Path(folder).rglob('*-TTT1-combat*.jmv')):
            data = bytearray(path.read_bytes())
            done = retrofit(data)
            if done:
                path.write_bytes(data)
                print(f'  {path.name}: {done} window kind(s)', flush=True)


if __name__ == '__main__':
    main(sys.argv[1:] or ['workspace/ttt1-import/roster'])
