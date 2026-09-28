#!/usr/bin/env python3
"""Kazuya: Electric (f, N, d, d/f+2), then Spinning Demon (f, N, d, d/f+4, 4)
on the falling opponent, pad only, several delays, many times in a row.

Counts the hits of each attempt from the Practice TOTAL DMG counter (read
every frame through the debug server's RAM ring). Works with any build: no
RAM write, only the pad.

  python3 tools/ttt1/juggle_case.py --build <dir> [--reps 7]
"""
import json, struct, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import moveset_check as M

DELAYS = [int(x) for x in __import__('os').environ.get('JUGGLE_DELAYS', '26,32,38').split(',')]

def main():
    a = sys.argv[1:]
    build = Path(a[a.index('--build') + 1]).resolve()
    reps = int(a[a.index('--reps') + 1]) if '--reps' in a else 7
    pack = M.guest_pack('kazuya')
    g = M.start(build, 'kazuya', 'juggle-' + build.parent.name)
    rows = []
    try:
        for slot, addr in enumerate((M.ACTOR[0], M.ACTOR[0] + 0x3f0, M.ACTOR[1], M.TOTAL)):
            g.q(dict(cmd='set_snapshot', slot=slot, addr=f'{addr:08x}'))
        for rep in range(reps):
            for delay in DELAYS:
                M.settle(g, pack, 300)
                for _ in range(60):
                    if g.u32(M.ACTOR[1] + M.RECORD) == g.dummy: break
                    g.wait_frames(10)
                M.walk_to(g, pack, 'contact')
                fwd = g.closer; back = M.LEFT if fwd == M.RIGHT else M.RIGHT
                f, d, df = M.held(fwd), M.held(M.DOWN), M.held(M.DOWN, fwd)
                ewgf = [(2, f), (2, M.NONE), (2, d), (2, M.held(M.DOWN, fwd, M.B2)), (2, M.NONE)]
                demon = [(2, f), (2, M.NONE), (2, d), (2, M.held(M.DOWN, fwd, M.B4)), (8, M.NONE), (3, M.held(M.B4)), (2, M.NONE)]
                steps = ewgf + [(delay, M.NONE)] + demon + [(90, M.NONE)]
                f0 = g.route(steps, wait=True)
                n = sum(k for k, _ in steps)
                hits, last = [], None
                for fr in range(f0, f0 + n + 5):
                    t = g.at(fr, M.TOTAL, 16)
                    r = g.at(fr, M.ACTOR[0], 0x5c)
                    if t is None: continue
                    tot = struct.unpack_from('<H', t, 0)[0]
                    if last is not None and tot != last:
                        rec = struct.unpack_from('<I', r, M.RECORD)[0] if r else 0
                        k = rec - g.records
                        o = g.at(fr, M.ACTOR[1], 0x5c)
                        hits.append(dict(frame=fr - f0, damage=tot - last, dummy=f'{struct.unpack_from("<I", o, M.RECORD)[0]:08x}' if o else None,
                                         record=k // 56 if 0 <= k < 56 * pack.count and k % 56 == 0 else f'{rec:08x}'))
                    last = tot
                path = []
                for fr in range(f0, f0 + n + 5):
                    r = g.at(fr, M.ACTOR[0], 0x5c)
                    if not r: continue
                    rec = struct.unpack_from('<I', r, M.RECORD)[0]; k = rec - g.records
                    name = k // 56 if 0 <= k < 56 * pack.count and k % 56 == 0 else f'{rec:08x}'
                    if not path or path[-1][0] != name: path.append((name, fr - f0))
                at = f0 + sum(k for k, _ in ewgf) + delay + 8
                o = g.at(at, M.ACTOR[1], 0x5c)
                state = (f'{struct.unpack_from("<I", o, M.RECORD)[0]:08x}', struct.unpack_from('<3i', o, 0)[1]) if o else None
                rows.append(dict(rep=rep, delay=delay, hits=hits, dummy_at_demon=state, path=path))
                print(rep, delay, 'dummy', state, [(h['frame'], h['damage'], h['record']) for h in hits], 'P1', path, flush=True)
    finally:
        g.close()
        (M.OUT / f'juggle-{build.parent.name}.json').write_text(json.dumps(rows, indent=1))

if __name__ == '__main__':
    main()
