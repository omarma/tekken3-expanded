#!/usr/bin/env python3
"""Retrofit the hand-pose table of imported guest models (<Name>-TTT1-arcade-P<n>.3dm),
without a new import. Same remapping as convert.hand_steps: indices 0..3 of each hand's
pose table run from open hand to fist (the last pose), the others fall back to pose 0.
Already remapped or short tables (fewer than 8 poses) are left alone.

    python3 tools/ttt1_retrofit_hands.py workspace/ttt1-import/roster
"""
import struct, sys
from pathlib import Path


def retrofit(data):
    """Rewrites `data` (a PS1 3DMK model) in place; number of tables remapped."""
    rows = struct.unpack_from('<I', data, 0)[0]
    done = 0
    for r in range(rows):
        w = struct.unpack_from('<14I', data, 24 + 56 * r)
        if w[13] <= 2 or r not in (13, 17): continue      # the hands only (Devil's wings keep their poses)
        n = 0
        while w[13] + 4 * (n + 1) <= len(data) and struct.unpack_from('<I', data, w[13] + 4 * n)[0] > 0x100: n += 1
        e = list(struct.unpack_from(f'<{n}I', data, w[13]))
        poses = list(dict.fromkeys(e))
        if len(poses) < 8 or e != poses + [e[0]] * (n - len(poses)): continue
        steps = [round(i * (len(poses) - 1) / 3) for i in range(4)]
        struct.pack_into(f'<{n}I', data, w[13], *([poses[s] for s in steps] + [poses[0]] * (n - 4)))
        done += 1
    return done


def main(paths):
    for root in paths:
        for f in sorted(Path(root).rglob('*-TTT1-arcade-P*.3dm')):
            data = bytearray(f.read_bytes()); n = retrofit(data)
            if n: f.write_bytes(data)
            print(f'{f.name}: {n} table(s) remapped' if n else f'{f.name}: unchanged')


if __name__ == '__main__':
    main(sys.argv[1:] or ['workspace/ttt1-import/roster'])
