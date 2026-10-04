#!/usr/bin/env python3
"""A CPU native fighting on its drawn TTT1 moves for a whole stretch of a fight.

    python3 tools/test_cpu_moveset_fight.py [--seconds 60] [--setting ttt1]

Arcade from Practice's save (tools/test_cpu_moveset_draw.py) until the CPU has
drawn the TTT1 moves, then player 1 stands still while the CPU fights. Reports
the CPU's records (acteur +0x54), whether they come from the TTT1 pack, how
many hits player 1 took, and flags a CPU stuck in a few records (the stale
alias table of B04) or one that never attacks.
"""
import argparse, collections, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live as L
from test_cpu_moveset_draw import one_fight, DRAW

ACTOR = (0x800a9228, 0x800a9228 + 0x188c)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=int, default=60)
    ap.add_argument('--setting', default='ttt1')
    ap.add_argument('--build', default=str(L.ROOT / 'build-rel'))
    a = ap.parse_args()
    s = L.Session(build=Path(a.build), slot=8, env={'TEKKEN3_NATIVE_MOVES': '', 'TEKKEN3_CPU_MOVESET': a.setting})
    try:
        for attempt in range(10):
            one_fight(s); time.sleep(1.5)
            lines = DRAW.findall(s.log())
            if lines and lines[-1][3] != 'T3': break
        else: raise AssertionError('the CPU never drew a native with other moves')
        fid = int(lines[-1][1])
        print('CPU fighter', fid, 'on', lines[-1][3], flush=True)
        s.wait(lambda: s.value(0x800ae204) == 8 and s.value(0x800ae224, 2) >= 6, 'the fight', 90)
        s.wait(lambda: s.value(ACTOR[1] + 0x54) != 0, 'the CPU actor', 30)
        records, life0 = collections.Counter(), None
        hits, last_life, pack, total = 0, None, 0, 0
        running = s.game_until(a.seconds)
        while running():
            r2 = s.value(ACTOR[1] + 0x54)
            life1 = s.value(ACTOR[0] + 0x3f6, 2)
            if last_life is not None and life1 < last_life: hits += 1
            last_life = life1
            records[r2] += 1; total += 1
            pack += 0x9f000000 <= r2 < 0x9f400000
            time.sleep(.05)
        print(f'samples {total}, distinct CPU records {len(records)}, in the TTT1 pack {pack}, P1 life changes {hits}')
        print('most common records', [(hex(r), n) for r, n in records.most_common(5)])
        assert s.value(0x800ae204) in (8, 11, 6, 7, 12, 13), 'the game left the fight'
        assert len(records) > 6, 'the CPU is stuck in a few records'
        assert pack > total // 4, 'the CPU does not play from the TTT1 pack'
        assert hits >= 1, 'the CPU never hit'
        print('OK')
    finally:
        s.stop()

if __name__ == '__main__': main()
