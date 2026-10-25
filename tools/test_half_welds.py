#!/usr/bin/env python3
"""Half welds on whole vertices (convert.half_welds, B70, GH#117): offline bench, no game.

Each imported guest costume (workspace/ttt1-import/<key>/[costume<n>/]ttt1.3dm) is converted
twice, without and with half welds. The TTT1 model and both conversions are posed with the same
joint angles (legs, torso, arms) and assembled with simulate.assemble: TTT1's own rules for the
model, the PS1 engine's for the conversions. Per row and pose, the mean distance of every polygon
corner to TTT1's. Fails if a row gets further from TTT1 with half welds, or if Michelle's third
costume (the shorts' hem on her thighs, rows 7 and 10) does not come at least 40 % closer.

    python tools/test_half_welds.py [--guest michelle:3 bruce ...]
"""
import argparse, math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools/ttt1/model')]
from fmt import load, row, nrows, block, parse_b, prim_verts
import simulate as SM, convert as C
from pose_ttt1 import mul, rot_rest

WORK = ROOT / 'workspace/ttt1-import'
I3 = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]


def rot(axis, deg):
    a = math.radians(deg); c, s = math.cos(a), math.sin(a)
    return {'x': [[1, 0, 0], [0, c, -s], [0, s, c]], 'y': [[c, 0, s], [0, 1, 0], [-s, 0, c]],
            'z': [[c, -s, 0], [s, c, 0], [0, 0, 1]]}[axis]


# Local rotations by TTT1 row (7 / 10 thighs, 8 / 11 shins, 1 chest, 13..19 arms, 21 head).
POSES = {
    'guard': {7: rot('z', 35), 8: rot('z', -45), 10: rot('z', -20), 11: rot('z', -25)},
    'knee': {7: rot('z', 80), 8: rot('z', -90), 10: rot('z', -5), 11: rot('z', -10)},
    'split': {7: mul(rot('y', 35), rot('z', 20)), 10: mul(rot('y', -35), rot('z', 20))},
    'torso': {1: mul(rot('y', 30), rot('x', 25)), 21: rot('z', 30)},
    'arms': {13: rot('z', 50), 14: rot('z', 70), 15: rot('y', 40), 17: rot('y', -45), 18: rot('z', -60),
             19: rot('x', 40)},
}


class Conversion:
    def __init__(self, T, half):
        C.HALF_WELDS = half
        try: self.P, _ = C.convert(T)
        finally: C.HALF_WELDS = True
        self.T, self.S2T, self.SECOND, self.DRAW = T, dict(C.S2T), dict(C.SECOND), list(C.DRAW)
        self.heads, self.done = C.head_extra_rows(T), list(C.HALF_DONE)

    def bone_row(self, s):
        """TTT1 row whose bone carries PS1 row s (host part of a second mesh, head for extra heads)."""
        q = next((q for q, r in self.SECOND.items() if r == s), None)
        if q is not None: return self.S2T[C.P2R[q]]
        return 21 if self.S2T[s] in self.heads else self.S2T[s]

    def errors(self, anim):
        """Mean corner distance to TTT1 per TTT1 row."""
        T = self.T; anim = {4: rot('z', 180), **anim}; cache = {}     # the pelvis faces down

        def fk(ri):
            if ri not in cache:
                w = row(T, ri)
                if w[6] < 0 or ri == 0: cache[ri] = (I3, [0.0, 0.0, 3000.0])
                else:
                    Rp, Tp = fk(C.ttt1_part_row(w[6]))
                    R = mul(Rp, mul(rot_rest([x & 0xffff for x in w[7:10]]), anim.get(ri, I3)))
                    cache[ri] = (R, [Tp[k] + sum(Rp[k][c] * w[3 + c] for c in range(3)) for k in range(3)])
            return cache[ri]

        def gte(ri):
            R, t = fk(ri); return [[x * 4096 for x in r_] for r_ in R], t, 0, 0, 1000
        gT = SM.assemble([(r, 1) for r in range(1, nrows(T))], T, ttt1=True,
                         xform=lambda ri: gte(ri if row(T, ri)[6] >= 0 else 1))
        gP = SM.assemble([(s, 1) for s in self.DRAW], self.P, ttt1=False, xform=lambda s: gte(self.bone_row(s)))
        out = {}
        for s in self.DRAW:
            t = self.S2T[s]; pt, pp = polys(T, t), polys(self.P, s)
            if not pt or len(pt) != len(pp): continue
            d = [math.dist(gT[t][a], gP[s][b]) for (_, A), (_, B) in zip(pt, pp) for a, b in zip(A, B)
                 if a < 128 and b < 128 and gT[t][a] is not None and gP[s][b] is not None]
            if d: out[t] = sum(d) / len(d)
        return out


def engine_rules(P):
    """What 0x80036CAC does that simulate.assemble does not model: a buffer of 110 slots (SZ follows
    SXY at 0x1F8001B8), and the whole list stored before the welds, so a group-3 read inside the
    row's own list reads one of its vertices. Both gave spikes in game (B70)."""
    bad = []
    for r in range(1, nrows(P)):
        if row(P, r - 1)[12] <= 2: continue
        for a in SM.variants(block(P, row(P, r - 1)[12]), False):
            n = len(a['g1']) + len(a['g2']) + len(a['verts'])
            slots = [b // 2 - 1 for b in a['g1']] + [(f & 0xff) // 2 - 1 for gi in (2, 4) for f in a['tails'][gi]]
            if n > C.BUFFER_TOP + 1 or any(s > C.BUFFER_TOP for s in slots): bad.append(f'row {r}: slot past {C.BUFFER_TOP}')
            if any((f & 0xff) // 2 - 1 < n for f in a['tails'][2]): bad.append(f'row {r}: group-3 read inside its own list')
    return bad


def polys(m, r):
    w = row(m, r)
    if w[1] <= 2: return []
    return [(k, prim_verts(k, rec)) for k, fl in enumerate(parse_b(block(m, w[1]))) for rec in fl]


def costumes(wanted):
    for key in sorted(p.name for p in WORK.iterdir() if (p / 'ttt1.3dm').is_file()):
        for c in (1, 2, 3):
            src = WORK / key / ('ttt1.3dm' if c == 1 else f'costume{c}/ttt1.3dm')
            if src.is_file() and (not wanted or key in wanted or f'{key}:{c}' in wanted): yield key, c, src


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--guest', nargs='*', default=[], help='key or key:costume (default: every imported costume)')
    args = ap.parse_args(argv)
    failures = []
    for key, c, src in costumes(args.guest):
        T = load(src)
        try: before, after = Conversion(T, False), Conversion(T, True)
        except ValueError as e: print(f'{key} c{c}: not converted ({str(e).splitlines()[-1]})'); continue
        failures += [f'{key} c{c}: {e}' for e in engine_rules(after.P) if e not in engine_rules(before.P)]
        if before.P == after.P:
            print(f'{key} c{c}: unchanged')
            if (key, c) == ('michelle', 3): failures.append('michelle c3: no half weld (the shorts stay on her hips)')
            continue
        closer = worse = 0; hem = []
        for name, anim in POSES.items():
            eb, ea = before.errors(anim), after.errors(anim)
            for t, e in eb.items():
                if ea.get(t, 1e9) > e + 0.5: worse += 1; failures.append(f'{key} c{c} {name} row {t}: {e:.1f} -> {ea.get(t)}')
                elif ea[t] < e - 0.5: closer += 1
            if (key, c) == ('michelle', 3) and name in ('guard', 'split'): hem += [(eb[t], ea[t]) for t in (7, 10)]
        print(f'{key} c{c}: {len(after.done)} half welds, {len(after.P) - len(before.P):+d} bytes, '
              f'rows closer to TTT1 {closer}, further {worse}')
        if hem:
            b, a = sum(x for x, _ in hem), sum(y for _, y in hem)
            print(f'  shorts hem (rows 7 and 10): {b / len(hem):.1f} -> {a / len(hem):.1f}')
            if a > 0.6 * b: failures.append(f'michelle c3: hem {b / len(hem):.1f} -> {a / len(hem):.1f}, not 40 % closer')
    print('FAIL:\n  ' + '\n  '.join(failures) if failures else 'OK')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
