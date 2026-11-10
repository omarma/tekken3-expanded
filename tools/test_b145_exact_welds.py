#!/usr/bin/env python3
"""Exact welds (convert.exact_welds, B145): offline bench, no game.

Each imported guest costume (workspace/ttt1-import/<key>/[costume<n>/]ttt1.3dm) is converted
twice, without and with exact welds, and posed with tools/test_half_welds.py's joint angles. Fails if:
- a row draws another number of polygons than the TTT1 model (every part drawn, none added);
- a row gets further from TTT1 with exact welds;
- Devil's shins (TTT1 rows 8 and 11, his calves) do not come at least 50 % closer to TTT1, or
  one of his leg rows (7..12) is not drawn.

    python tools/test_b145_exact_welds.py [--guest devil devil:2 ...]
"""
import argparse, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt1/model')]
from fmt import load, row
import convert as C
import test_half_welds as H

LEGS, CALVES = (7, 8, 9, 10, 11, 12), (8, 11)


class Conversion(H.Conversion):
    def __init__(self, T, exact):
        C.EXACT_WELDS = exact
        try: super().__init__(T, True)
        finally: C.EXACT_WELDS = True
        self.exact = list(C.EXACT_DONE)


def counts(m, rows):
    return {r: len(H.polys(m, r)) for r in rows}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--guest', nargs='*', default=[], help='key or key:costume (default: every imported costume)')
    args = ap.parse_args(argv)
    failures = []; devil = 0
    for key, c, src in H.costumes(args.guest):
        T = load(src)
        try: before, after = Conversion(T, False), Conversion(T, True)
        except ValueError as e: print(f'{key} c{c}: not converted ({str(e).splitlines()[-1]})'); continue
        name = f'{key} c{c}'
        drawn = {s: after.S2T[s] for s in after.DRAW if row(T, after.S2T[s])[1] > 2}
        got = {t: len(H.polys(after.P, s)) for s, t in drawn.items()}
        failures += [f'{name} row {t}: {got[t]} polygons drawn, TTT1 {n}' for t, n in counts(T, drawn.values()).items()
                     if got[t] != n]
        failures += [f'{name} PS1 row {s}: {len(H.polys(after.P, s))} polygons, {len(H.polys(before.P, s))} without exact welds'
                     for s in after.DRAW if len(H.polys(after.P, s)) != len(H.polys(before.P, s))]
        failures += [f'{name}: {e}' for e in H.engine_rules(after.P) if e not in H.engine_rules(before.P)]
        if key == 'devil':
            devil += 1
            failures += [f'{name} row {t}: leg not drawn' for t in LEGS if t not in drawn.values() or not got.get(t)]
        if before.P == after.P:
            print(f'{name}: unchanged, {sum(got.values())} polygons')
            if key == 'devil': failures.append(f'{name}: no exact weld (calves pulled into the thighs)')
            continue
        closer = worse = 0; calves = []
        for pose, anim in H.POSES.items():
            eb, ea = before.errors(anim), after.errors(anim)
            for t, e in eb.items():
                if ea.get(t, 1e9) > e + 0.5: worse += 1; failures.append(f'{name} {pose} row {t}: {e:.1f} -> {ea.get(t)}')
                elif ea[t] < e - 0.5: closer += 1
            if key == 'devil' and pose in ('guard', 'knee'): calves += [(eb[t], ea[t]) for t in CALVES]
        print(f'{name}: {len(after.exact)} exact welds, {sum(got.values())} polygons as in TTT1, '
              f'rows closer to TTT1 {closer}, further {worse}')
        if calves:
            b, a = sum(x for x, _ in calves) / len(calves), sum(y for _, y in calves) / len(calves)
            print(f'  calves (rows 8 and 11): {b:.1f} -> {a:.1f}')
            if a > 0.5 * b: failures.append(f'{name}: calves {b:.1f} -> {a:.1f}, not 50 % closer')
    if not devil and (not args.guest or any(g.split(':')[0] == 'devil' for g in args.guest)):
        failures.append('Devil not imported (workspace/ttt1-import/devil/ttt1.3dm)')
    print('FAIL:\n  ' + '\n  '.join(failures) if failures else 'OK')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
