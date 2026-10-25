#!/usr/bin/env python3
"""Retrofit the mist's hit limb in imported TTT1 move packs (<Name>-TTT1-combat*.jmv),
without a new import (B65, import version 7).

TTT1 spits the mist through a virtual limb 25: Nina's Evil Mist and Yoshimitsu's
Poison Breath, and a shared record of Nina's and Anna's. Before version 7 the
converter found no bone for it and wrote limb 0: no cloud, no hit. It now writes
the marker 0x3C (tools/ttt1/moves.py MIST_LIMB), which the runtime gives the
engine as T3's own effect limb 25. The records are known by their TTT1 address
(the pack's provenance), the same on every verified ROM: Unknown's donors and the
natives' TTT1 moves, which are copies of them.

    python3 tools/ttt1_retrofit_mist.py workspace/ttt1-import/roster
"""
import struct, sys
from pathlib import Path

MIST_LIMB = 0x3c
# TTT1 records with limb 25 (all of them, checked against every selector capture).
MIST_RECORDS = {0x80050428: 'Nina Evil Mist', 0x8007b424: 'Nina', 0x80054730: 'Yoshimitsu Poison Breath',
                0x8007b458: 'Anna'}


def retrofit(data):
    """Rewrites `data` (a v4 combat pack) in place; number of records changed."""
    done = 0
    for i in range(struct.unpack_from('<I', data, 12)[0]):
        _, provenance, rp, _ = struct.unpack_from('<4I', data, 32 + i * 16)
        if provenance in MIST_RECORDS and data[rp + 40:rp + 44] == b'\0\0\0\0':
            data[rp + 40] = MIST_LIMB; done += 1
    return done


def main(folders):
    for folder in folders:
        for path in sorted(Path(folder).rglob('*-TTT1-combat*.jmv')):
            data = bytearray(path.read_bytes())
            if retrofit(data):
                path.write_bytes(data)
                print(f'  {path.name}: mist hit limb', flush=True)


if __name__ == '__main__':
    main(sys.argv[1:] or ['workspace/ttt1-import/roster'])
