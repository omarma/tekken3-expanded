#!/usr/bin/env python3
"""Exact cache welds (convert.EXACT_CACHE_WELDS, B176, GH#228): offline bench, no game.

Each TTT1 model source is converted twice, without and with exact cache welds (group 2 of the
position list, the cabinet's list B, reading a group-4 deposit with weights other than 8/8), and
posed with tools/test_half_welds.py's joint angles plus a leg drawn back and one drawn forward.
Sources: the natives' slots (<work>/native-models/work/<native>-<slot>/ttt1.3dm, written by
tools/ttt1_native_model.py) and the guests' costumes (<work>/<key>/[costume<n>/]ttt1.3dm).
Fails if:
- a row draws another number of polygons than without (every part drawn, none added);
- the engine's rules (tools/test_half_welds.engine_rules) break where they held;
- a row gets further from TTT1 (more than 0.5 unit, mean distance of its own corners that both
  conversion puts on TTT1's at rest without exact cache welds);
- Xiaoyu's punch models (84, 14): her right thigh (TTT1 row 10, welded at 12/4 and 4/12 to the
  pelvis's meshes 5 and 6) and her shins (rows 8 and 11, the knees) do not come at least 50 %
  closer to TTT1 in the poses with a leg drawn back or forward (all their corners).

    python tools/test_b176_cache_welds.py [--work workspace/ttt1-import] [--only xiaoyu-84 ...]
"""
import argparse, math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt1/model')]
from fmt import load, row, nrows, block
import convert as C, simulate as SM
import test_half_welds as H
from pose_ttt1 import mul, rot_rest

POSES = dict(H.POSES, rest={},
             rear={10: H.rot('z', -50), 11: H.rot('z', -30), 7: H.rot('z', 30)},
             front={10: H.rot('z', 70), 7: H.rot('z', -30)})
XIAOYU = ('xiaoyu-84', 'xiaoyu-14')


class Conversion(H.Conversion):
    def __init__(self, T, exact):
        C.EXACT_CACHE_WELDS = exact
        try: super().__init__(T, True)
        finally: C.EXACT_CACHE_WELDS = True
        self.exact = list(C.EXACT_DONE)

    def corners(self, anim):
        """Corner distances to TTT1 per TTT1 row, {row: {(polygon, corner): distance}}, the row's own
        vertices only (not its borrows)."""
        T = self.T; anim = {4: H.rot('z', 180), **anim}; cache = {}

        def fk(ri):
            if ri not in cache:
                w = row(T, ri)
                if w[6] < 0 or ri == 0: cache[ri] = (H.I3, [0.0, 0.0, 3000.0])
                else:
                    Rp, Tp = fk(C.ttt1_part_row(w[6]))
                    # a second mesh turns with the part it belongs to: the chest's (2, 3) and the pelvis's
                    # (5, 6), with no offset nor rest angles, and the head's (22, 23: its parent, offset, angles)
                    host = {2: 1, 3: 1, 5: 4, 6: 4, 22: 21, 23: 21}.get(ri)
                    head = host if host and w[3:10] == row(T, host)[3:10] else ri
                    R = mul(Rp, mul(rot_rest([x & 0xffff for x in w[7:10]]), anim.get(head, H.I3)))
                    cache[ri] = (R, [Tp[k] + sum(Rp[k][c] * w[3 + c] for c in range(3)) for k in range(3)])
            return cache[ri]

        def gte(ri):
            R, t = fk(ri); return [[x * 4096 for x in r_] for r_ in R], t, 0, 0, 1000
        gT = SM.assemble([(r, 1) for r in range(1, nrows(T))], T, ttt1=True,
                         xform=lambda ri: gte(ri if row(T, ri)[6] >= 0 else 1))
        gP = SM.assemble([(s, 1) for s in self.DRAW], self.P, ttt1=False, xform=lambda s: gte(self.bone_row(s)))
        out = {}
        for s in self.DRAW:
            t = self.S2T[s]; pt, pp = H.polys(T, t), H.polys(self.P, s)
            if not pt or len(pt) != len(pp): continue
            vs = SM.variants(block(T, row(T, t - 1)[12]), True) if row(T, t - 1)[12] > 2 else []
            s0 = len(vs[0]['g1']) + len(vs[0]['g2']) if vs else 0
            out[t] = {(i, k): math.dist(gT[t][a], gP[s][b]) for i, ((_, A), (_, B)) in enumerate(zip(pt, pp))
                      for k, (a, b) in enumerate(zip(A, B))
                      if s0 <= a < 128 and b < 128 and gT[t][a] is not None and gP[s][b] is not None}
        return out


def means(err, mask):
    """Mean distance per row over the corners of `mask` (those the conversion without exact cache
    welds places on TTT1's at rest)."""
    return {t: sum(d[c] for c in mask[t]) / len(mask[t]) for t, d in err.items() if mask.get(t)}


def sources(work, only):
    for p in sorted((work / 'native-models/work').glob('*/ttt1.3dm')):
        if not only or p.parent.name in only: yield p.parent.name, p
    for key, c, src in H.costumes([]):
        name = f'{key}:{c}'
        if not only or name in only or key in only: yield name, src


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--work', type=Path, default=ROOT / 'workspace/ttt1-import')
    ap.add_argument('--only', nargs='*', default=[], help='native-slot (xiaoyu-84) or guest key[:costume]')
    args = ap.parse_args(argv)
    H.WORK = args.work.resolve()
    failures, seen = [], set()
    for name, src in sources(H.WORK, args.only):
        T = load(src)
        try: before, after = Conversion(T, False), Conversion(T, True)
        except ValueError as e: print(f'{name}: not converted ({str(e).splitlines()[-1]})'); continue
        seen.add(name)
        failures += [f'{name} PS1 row {s}: {len(H.polys(after.P, s))} polygons, {len(H.polys(before.P, s))} before'
                     for s in after.DRAW if len(H.polys(after.P, s)) != len(H.polys(before.P, s))]
        failures += [f'{name}: {e}' for e in H.engine_rules(after.P) if e not in H.engine_rules(before.P)]
        if before.P == after.P:
            print(f'{name}: unchanged')
            if name in XIAOYU: failures.append(f'{name}: no exact cache weld')
            continue
        closer = worse = 0; legs = []
        rb, ra = before.corners({}), after.corners({})
        mask = {t: {c for c, x in d.items() if x <= 2} for t, d in rb.items()}
        for pose, anim in POSES.items():
            eb, ea = means(before.corners(anim), mask), means(after.corners(anim), mask)
            for t, e in eb.items():
                if ea.get(t, 1e9) > e + 0.5: worse += 1; failures.append(f'{name} {pose} row {t}: {e:.1f} -> {ea.get(t)}')
                elif ea[t] < e - 0.5: closer += 1
            if name in XIAOYU and pose in ('guard', 'knee', 'rear', 'front', 'split'):
                cb, ca = before.corners(anim), after.corners(anim)
                legs += [(sum(cb[t].values()) / len(cb[t]), sum(ca[t].values()) / len(ca[t])) for t in (8, 10, 11)]
        print(f'{name}: {len(after.exact) - len(before.exact)} more exact welds, rows closer to TTT1 {closer}, further {worse}')
        if legs:
            b, a = sum(x for x, _ in legs) / len(legs), sum(y for _, y in legs) / len(legs)
            print(f'  right thigh and shins (rows 10, 8, 11), legs drawn: {b:.1f} -> {a:.1f}')
            if a > 0.5 * b: failures.append(f'{name}: legs {b:.1f} -> {a:.1f}, not 50 % closer')
    missing = [x for x in XIAOYU if x not in seen and (not args.only or x in args.only)]
    failures += [f'{x}: not found under {H.WORK}/native-models/work (tools/ttt1_native_model.py xiaoyu)' for x in missing]
    print('FAIL:\n  ' + '\n  '.join(failures) if failures else 'OK')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
