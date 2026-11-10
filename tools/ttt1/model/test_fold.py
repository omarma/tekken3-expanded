#!/usr/bin/env python3
"""Pieces repliees (convert.fold_accessories, F32 E3) : banc hors jeu, sans donnees dans le depot.

Les quatre modeles TTT1 de natifs que le convertisseur refusait : Hwoarang Poing (emplacement 82)
et Julia Pied (91), recursion sans fin dans rewired() ; les anciens costumes de Hwoarang (12) et
de Julia (21), sept pieces pour six places PS1. Lus dans les regions ROM de l'import
(workspace/ttt1-import/ttt1, sinon --ttt1 tektagt.zip). Pour chacun : conversion, regles du
moteur (test_half_welds.engine_rules), repli attendu, et ecart du repli : les coins des polygones
de la piece repliee, modele TTT1 d'origine contre modele replie, assembles avec les regles TTT1
dans les poses de test_half_welds (au plus REPLI_MAX unites, l'arrondi des matrices 12 bits).

    python tools/ttt1/model/test_fold.py [--ttt1 tektagt.zip]
"""
import argparse, io, contextlib, json, math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt1'), str(ROOT / 'tools/ttt1/model')]
from fmt import row, nrows
import simulate as SM, convert as C
import test_half_welds as H

# emplacement -> (fichier du modele dans l'archive 24, pieces repliees attendues {B: A})
CASES = {82: (82, {}), 91: (91, {}), 12: (12, {29: 28}), 21: (21, {29: 27})}
REPLI_MAX = 3.0


def models(zip_path):
    import extract as E
    regions = ROOT / 'workspace/ttt1-import/ttt1'
    if zip_path is None and (regions / 'bankedroms.bin').is_file():
        bank, main = (regions / 'bankedroms.bin').read_bytes(), (regions / 'maincpu_rom.bin').read_bytes()
    else:
        if zip_path is None: raise SystemExit('regions TTT1 absentes : --ttt1 tektagt.zip')
        import arcade_model_probe as P
        sets = json.loads(P.MANIFEST.read_text(encoding='utf-8'))['sets']
        wanted = [r for r in sets[P.ttt_set(zip_path)]['regions'] if r['name'] in ('maincpu:rom', 'bankedroms')]
        regs, _ = P.reconstruct(zip_path, {'regions': wanted})
        bank, main = regs['bankedroms'], regs['maincpu:rom']
    rom, game = E.Rom(bank, main), E.unpack_game(main)
    files = {n: (a, s) for i, n, a, s in E.archives(game, rom) if i == 24}
    return {slot: bytes(rom(*files[n])) for slot, (n, _) in CASES.items()}


def pose(T, anim):
    """Assemblage TTT1 de T dans la pose `anim` (memes os que test_half_welds)."""
    anim = {4: H.rot('z', 180), **anim}; cache = {}
    def fk(ri):
        if ri not in cache:
            w = row(T, ri)
            if w[6] < 0 or ri == 0: cache[ri] = (H.I3, [0.0, 0.0, 3000.0])
            else:
                Rp, Tp = fk(C.ttt1_part_row(w[6]))
                R = H.mul(Rp, H.mul(H.rot_rest([x & 0xffff for x in w[7:10]]), anim.get(ri, H.I3)))
                cache[ri] = (R, [Tp[k] + sum(Rp[k][c] * w[3 + c] for c in range(3)) for k in range(3)])
        return cache[ri]
    def gte(ri):
        R, t = fk(ri if row(T, ri)[6] >= 0 else 1); return [[x * 4096 for x in r_] for r_ in R], t, 0, 0, 1000
    return SM.assemble([(r, 1) for r in range(1, nrows(T))], T, ttt1=True, xform=gte)


def fold_error(T0, T, folded):
    """Plus grand ecart des coins des pieces repliees (A puis B dans chaque famille de A)."""
    worst = 0.0
    for anim in [{}] + list(H.POSES.values()):
        g0, g1 = pose(T0, anim), pose(T, anim)
        for B, A in folded.items():
            pa, pb, pm = H.polys(T0, A), H.polys(T0, B), H.polys(T, A)
            start, at = {}, 0
            for f in range(4):
                at += sum(1 for k, _ in pa if k == f); start[f] = at; at += sum(1 for k, _ in pb if k == f)
            seen = [0] * 4
            for k, p in pb:
                q = pm[start[k] + seen[k]][1]; seen[k] += 1
                worst = max([worst] + [math.dist(g0[B][a], g1[A][b]) for a, b in zip(p, q)
                                       if g0[B][a] is not None and g1[A][b] is not None])
    return worst


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--ttt1', type=Path, help='tektagt.zip, si workspace/ttt1-import/ttt1 manque')
    args = ap.parse_args(argv)
    failures = []
    for slot, T0 in models(args.ttt1).items():
        want = CASES[slot][1]
        try:
            with contextlib.redirect_stdout(io.StringIO()): P, _ = C.convert(T0)
        except ValueError as e:
            failures.append(f'{slot}: not converted ({str(e).splitlines()[-1]})'); continue
        folded = dict(C.FOLDED)
        rules = H.engine_rules(P)
        err = fold_error(T0, C.fold_accessories(T0), folded) if folded else 0.0
        print(f'slot {slot}: {len(P)} bytes, folded {folded or "nothing"}, fold error {err:.1f}, '
              f'unplaced {C.unplaced(T0)}, engine rules {rules or "ok"}')
        if folded != want: failures.append(f'{slot}: folded {folded}, expected {want}')
        if err > REPLI_MAX: failures.append(f'{slot}: fold error {err:.1f} > {REPLI_MAX}')
        failures += [f'{slot}: {r}' for r in rules]
    print('FAIL:\n  ' + '\n  '.join(failures) if failures else 'OK')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
