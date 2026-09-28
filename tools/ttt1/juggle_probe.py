#!/usr/bin/env python3
"""Kazuya: Electric, then f, N, d, d/f+4 (203, first spin of the Spinning
Demon) at a delay; per active frame of 203: its capsules, how far they pass
from the opponent's 14 spheres, the opponent's record and height.

  JUGGLE_DELAYS=45,55 python3 tools/ttt1/juggle_probe.py --build <dir>
"""
import json, os, struct, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import moveset_check as M

def main():
    a = sys.argv[1:]
    build = Path(a[a.index('--build') + 1]).resolve()
    delays = [int(x) for x in os.environ.get('JUGGLE_DELAYS', '45,55').split(',')]
    pack = M.guest_pack('kazuya')
    g = M.start(build, 'kazuya', 'jprobe')
    rows = []
    try:
        for delay in delays:
            M.settle(g, pack, 300)
            for _ in range(60):
                if g.u32(M.ACTOR[1] + M.RECORD) == g.dummy: break
                g.wait_frames(10)
            M.walk_to(g, pack, 'contact')
            fwd = g.closer
            f, d = M.held(fwd), M.held(M.DOWN)
            ewgf = [(2, f), (2, M.NONE), (2, d), (2, M.held(M.DOWN, fwd, M.B2)), (2, M.NONE)]
            demon = [(2, f), (2, M.NONE), (2, d), (3, M.held(M.DOWN, fwd)), (3, M.held(M.DOWN, fwd, M.B4)), (2, M.NONE)]
            steps = ewgf + [(delay, M.NONE)] + demon + [(90, M.NONE)]
            for slot, addr in enumerate((M.ACTOR[0], M.ACTOR[0] + M.CAPSULES, M.ACTOR[1] + M.SPHERES, M.ACTOR[1] + M.SPHERES + 128)):
                g.q(dict(cmd='set_snapshot', slot=slot, addr=f'{addr:08x}'))
            total = g.u16(M.TOTAL)
            f0 = g.route(steps, wait=True)
            n = sum(k for k, _ in steps)
            goal = g.records + int(os.environ.get("JUGGLE_GOAL", "276")) * 56
            rec = g.rd(goal, 56); first, last = rec[45], rec[46]
            frames = []
            for fr in range(f0, f0 + n):
                r = g.at(fr, M.ACTOR[0], 0x5c)
                if not r or struct.unpack_from('<I', r, M.RECORD)[0] != goal: continue
                k = struct.unpack_from('<H', r, M.FRAME)[0]
                if not first <= k <= last: continue
                cap = g.at(fr, M.ACTOR[0] + M.CAPSULES, 48)
                sph = (g.at(fr, M.ACTOR[1] + M.SPHERES, 128) or b'') + (g.at(fr, M.ACTOR[1] + M.SPHERES + 128, 128) or b'')
                seg = struct.unpack_from('<6i', cap, 0)
                gaps = []
                for j in range(len(sph) // 20):
                    c = struct.unpack_from('<3i', sph, j * 20); rad = struct.unpack_from('<h', sph, j * 20 + 12)[0]
                    gaps.append((round(M.segment_distance(seg[:3], seg[3:], c) - rad), j, c[1]))
                frames.append(dict(frame=k, capsule=seg, closest=min(gaps), sphere_heights=sorted(x[2] for x in gaps)[:3]))
            path = []
            for fr in range(f0, f0 + n):
                r = g.at(fr, M.ACTOR[0], 0x5c)
                if not r: continue
                rec2 = struct.unpack_from('<I', r, M.RECORD)[0]; kk = rec2 - g.records
                nm = kk // 56 if 0 <= kk < 56 * pack.count and kk % 56 == 0 else f'{rec2:08x}'
                if not path or path[-1][0] != nm: path.append((nm, fr - f0))
            dealt = g.u16(M.TOTAL) - total
            inside = [x for x in frames if x['closest'][0] <= 0]
            row = dict(delay=delay, window=[first, last], dealt=dealt, frames=frames, path=path, traverse=bool(inside and dealt <= 25),
                       dummy=f'{g.u32(M.ACTOR[1] + M.RECORD):08x}')
            rows.append(row)
            print(delay, 'TRAVERSE' if inside and dealt <= 25 else '', 'path', path[-4:], 'dealt', dealt, 'window', first, last, [(x['frame'], x['closest'], x['sphere_heights']) for x in frames], flush=True)
            for slot, addr in enumerate((M.ACTOR[0], M.ACTOR[0] + 0x3f0, M.ACTOR[1], M.TOTAL)):
                g.q(dict(cmd='set_snapshot', slot=slot, addr=f'{addr:08x}'))
    finally:
        g.close()
        (M.OUT / 'juggle-probe.json').write_text(json.dumps(rows, indent=1))

if __name__ == '__main__':
    main()
