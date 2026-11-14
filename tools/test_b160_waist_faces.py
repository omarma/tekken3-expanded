#!/usr/bin/env python3
"""B160 (GH#210): the inside of Hwoarang's jacket showed over his belly on his TTT1 LP / RP models.
Offline bench, no game, no data in the repository.

The converter draws on both sides (convert.double_sided, TIPS 53) the polygons of the pelvis and
legs (PS1 rows 3..10) that touch an approximated weld: a bent knee turned them away and the engine
dropped them (Lee's knee). The pelvis's waist welds (to the chest rows, or between the pelvis's two
meshes) also did: Hwoarang 82 (LP) had 48 of its 58 pelvis polygons double-sided, 12 (RP) 42 of
its second pelvis mesh's 56; the jacket's inner faces, back-facing on the cabinet, were drawn at
their depth rank in front of his belly. Now only welds that touch a leg (convert.leg_welds).

Fails if a pelvis row (PS1 3, 4) of Hwoarang 82 / 12 keeps a double-sided polygon (48 and 43
before the fix), or if Lee's legs lose theirs (the knee fix, rows 5..10).

    python tools/test_b160_waist_faces.py [--work workspace/ttt1-import]
"""
import argparse, contextlib, io, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt1'), str(ROOT / 'tools/ttt1/model')]
import convert as C
from fmt import load, row, nrows, block

PELVIS = (3, 4)


def double_sided(m):
    """{PS1 row: polygons carrying convert.DOUBLE_SIDED}."""
    out = {}
    for s in range(nrows(m)):
        w = row(m, s)
        if w[1] <= 2: continue
        b, q, n_ds = block(m, w[1]), 0, 0
        for k in range(4):
            n = struct.unpack_from('<I', b, q)[0]; q += 4; st = 12 if k == 3 else 8
            for i in range(n):
                at = q + i * st + (4 if k in (1, 3) else 0)
                n_ds += bool(struct.unpack_from('<I', b, at)[0] & C.DOUBLE_SIDED)
            q += n * st
        if n_ds: out[s] = n_ds
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--work', type=Path, default=ROOT / 'workspace/ttt1-import',
                    help='import work folder (ttt1/ ROM regions, captures/, lee/ttt1.3dm)')
    a = ap.parse_args(argv)
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        # In another process: the import leaves texpack's plan of its last model behind (TIPS 240).
        subprocess.run([sys.executable, str(ROOT / 'tools/ttt1_native_model.py'), 'hwoarang', '--out', tmp,
                        '--work', str(a.work)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for slot, p in (('82 LP', 'P1'), ('12 RP', 'P3')):
            ds = double_sided(load(Path(tmp) / f'Hwoarang-Native-TTT1-arcade-{p}.3dm'))
            pelvis = sum(ds.get(s, 0) for s in PELVIS)
            print(f'hwoarang {slot}: double-sided by row {ds}')
            if pelvis: failures.append(f'hwoarang {slot}: {pelvis} double-sided pelvis polygons')
    lee = a.work / 'lee/ttt1.3dm'
    if lee.is_file():
        with contextlib.redirect_stdout(io.StringIO()): P, _ = C.convert(load(lee))
        ds = double_sided(P); legs = sum(n for s, n in ds.items() if s in C.LEG_ONLY)
        print(f'lee: double-sided by row {ds}')
        if not legs: failures.append("lee: no double-sided leg polygon left (TIPS 53's knee)")
    else: failures.append(f'{lee}: missing')
    print('FAIL:\n  ' + '\n  '.join(failures) if failures else 'OK')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
