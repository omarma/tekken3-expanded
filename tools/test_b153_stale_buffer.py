#!/usr/bin/env python3
"""B153 (GH#201): Anna's dress panel hung from her right shoulder on her TTT1 LP / LK models.
Offline bench, no game, no data in the repository.

Anna's slots 36 (LP, red) and 37 (LK, blue) are converted from the import's ROM regions
(tools/ttt1_native_model.py), then the TTT1 model and its conversion are posed at rest and in
test_half_welds' poses and assembled with simulate.assemble (TTT1's rules, the PS1 engine's). Per
TTT1 row, the mean distance of the polygon corners to TTT1's. Fails if row 26 (the dress panel) is
further than ROW26_MAX at rest: 328 before the fix (its top corners read buffer cells that piece 24
had left, overwritten in the PS1 draw order), 0.6 after. Also fails if a conversion of every
native slot still reads a stale buffer cell (convert.stale_buffer_reads after route_stale), with
--all.

    python tools/test_b153_stale_buffer.py [--all] [--work workspace/ttt1-import]
"""
import argparse, contextlib, io, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt1'), str(ROOT / 'tools/ttt1/model')]
import convert as C, test_half_welds as H, ttt1_native_model as N    # N: the natives' table only
from fmt import load

ROW26_MAX = 5.0


def sources(out, natives, work):
    """{(native, slot): TTT1 .3dm path}, converted once into `out`. In another process: the
    import leaves texpack's plan of its last model behind, which this process's conversions
    would then use."""
    import subprocess
    found = {}
    for native in natives:
        cmd = [sys.executable, str(ROOT / 'tools/ttt1_native_model.py'), native, '--out', str(out)]
        if work: cmd += ['--work', str(work)]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for p in sorted((out / 'work').glob(f'{native}-*/ttt1.3dm')):
            found[(native, int(p.parent.name.rsplit('-', 1)[1]))] = p
    return found


def converted_stale(T):
    """The stale buffer reads left in the layout convert() chose (after route_stale)."""
    with contextlib.redirect_stdout(io.StringIO()): C.convert(T)
    src = C.fold_accessories(C.merge_extra_meshes(T))
    U = C.exact_welds(src, C.TORDER) if C.EXACT_WELDS else src
    stale = C.stale_buffer_reads(U)
    if stale:
        try: stale = C.stale_buffer_reads(C.route_stale(U, stale))
        except ValueError as e: stale = [str(e)]
    return stale


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--all', action='store_true', help='every native slot: no stale buffer read left')
    ap.add_argument('--work', type=Path, default=None, help='import work folder (ttt1/ ROM regions, captures/)')
    a = ap.parse_args(argv)
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        natives = sorted(N.natives()) if a.all else ['anna']
        found = sources(Path(tmp), natives, a.work)
        for slot in (36, 37):
            T = load(found[('anna', slot)])
            with contextlib.redirect_stdout(io.StringIO()): c = H.Conversion(T, True)
            for name in ['rest'] + list(H.POSES):
                e = c.errors({} if name == 'rest' else H.POSES[name])
                print(f'anna {slot} {name}: row 26 {e.get(26, 0):.1f}, worst row '
                      f'{max(e, key=e.get)} {max(e.values()):.1f}')
                if name == 'rest' and e.get(26, 0) > ROW26_MAX:
                    failures.append(f'anna {slot}: dress panel (row 26) {e[26]:.1f} from TTT1 at rest > {ROW26_MAX}')
        if a.all:
            for (native, slot), p in sorted(found.items()):
                stale = converted_stale(load(p))
                if stale: failures.append(f'{native} {slot}: stale buffer reads {stale[:4]}')
            print(f'{len(found)} native slots checked for stale buffer reads')
    print('FAIL:\n  ' + '\n  '.join(failures) if failures else 'OK')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
