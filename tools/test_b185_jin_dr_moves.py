#!/usr/bin/env python3
"""B185: Jin DR's u/f+4 hits, and a new DR move's recovery is timed on the guard reaction it really has.

    python tools/test_b185_jin_dr_moves.py <catalogue> [--name Jin]

<catalogue> is a TTT1 catalogue the DR import wrote into (mods/ttt1 of an install, or dr_setup.py's
--roster), with dr_pack's report.json. Three checks on <Name>-DR-combat.jmv:
  limbs   no attack record the DR import made has a hitting pair without its first bone (byte 0 or 2 at 0
          with the other byte of the pair set; Tekken 3 reads byte 0 when byte 2 is 0,
          fighter_move_advance): u/f+4 (Jz_jprk00F, DR's off-skeleton point 112) had (0, 0, 13, 0), no
          capsule on the foot, and never hit.
  air     u/f+4 jumps forward as in DR: push -9848 a frame from 9 to 23, frame 22 held (the copy of u+1 stood
          still, 0 from 9 to 34, and kicked short).
  guard   each new move with a block advantage aimed at (report 'bounds' block) gets it with the guard
          reaction its row names: first active frame + that record's end window - the move's free frame
          (its end window). b+1, 3 (Leaping Side Kick) was +20 on block with DR's sGrd_YA37 (38), its
          recovery 27..56 played in 13 frames, from the jab's guard (19) that new() had used.
Exit 1 with the faults listed.
"""
import argparse, json, struct, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'ttt1'))
from pack_edit import Pack  # noqa: E402

BASE_ID, GUARD = 8192, 10


def end_window(p, k):
    return next((e[5] for e in p.cancels(k) if e[0] == 0xc000), None)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('catalogue', type=Path)
    ap.add_argument('--name', default='Jin')
    a = ap.parse_args()
    p = Pack((a.catalogue / f'{a.name}-DR-combat.jmv').read_bytes())
    t = (a.catalogue / f'{a.name}-DR-tables.jst').read_bytes()
    first_new = Pack((a.catalogue / f'{a.name}-TTT1-combat.jmv').read_bytes()).records.__len__()
    report = json.loads((a.catalogue / 'report.json').read_text(encoding='utf-8'))
    moves = report['moves']
    faults = []
    for k in range(first_new, len(p.records)):
        r = p.records[k]
        if not r[45] or r[40] >= 0x18: continue                    # no hit, or a laser / effect limb
        l = list(r[40:44])
        if (not l[0] and l[1]) or (not l[0] and l[2]) or (not l[2] and l[3]):
            faults.append(f'limbs: record {k} hits with {l}')
    uf4 = moves.get('u/f+4')
    if uf4:
        r = p.records[uf4['record']]
        air = (struct.unpack_from('<h', r, 22)[0], r[25], r[26], r[27])
        if air != (-9848, 9, 23, 22): faults.append(f'air: u/f+4 record {uf4["record"]} push/air/held {air}, DR (-9848, 9, 23, 22)')
    for cmd, v in moves.items():
        b = v.get('bounds') or {}
        if 'like' not in v or b.get('block') is None: continue
        k = v['record']
        g = struct.unpack_from('<14H', t, 32 + (p.word(k, 12) >> 16) * 42)[GUARD] - BASE_ID
        if not 0 <= g < len(p.records): continue
        adv = p.records[k][45] + end_window(p, g) - end_window(p, k)
        # new() keeps DR's own recovery when the aim is out of reach (a sheet advantage read through
        # crouched states, -190: the attacker held 220 frames).
        dr, tg = v['dr'], v['target']
        if adv != b['block'] and tg[3] - tg[2] != dr[3] - dr[2]:
            faults.append(f'guard: {cmd} (record {k}) {adv:+d} on block with guard record {g} '
                          f'(window {end_window(p, g)}), {b["block"]:+d} aimed at; DR {v["dr"]} -> {v["target"]}')
    for f in faults: print('FAULT', f)
    print(f'{len(faults)} fault(s)')
    sys.exit(1 if faults else 0)


if __name__ == '__main__':
    main()
