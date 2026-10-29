#!/usr/bin/env python3
"""The CPU's opponents, counted over many draws, mode by mode (B125, GH#173).

    python3 tools/test_b125_cpu_draws.py --mode arcade|timeattack|survival|ball [--trials 200] [--build build-rel-lite]

No fight is judged; only who the CPU draws (TIPS.md section 25 for the
game's draws, src/tekken3_ttt1_roster.c for the mod's).
- arcade, timeattack: at the selector, the mode is written and a state is
  saved; each trial loads it, writes a new seed for the game's draw
  (0x8009F2A8), validates, and reads the ten opponents (0x800AFB18) once
  the mod has rewritten them on the first loading screen.
- survival: one run, the wins counter (0x800AFAAC) set to --from-wins at the
  first fight so the draws after it use the wide pools (guests from 7,
  Devil / Angel / Unknown from 17); each fight the CPU's fighter is read and
  its life taken to 0, in turbo.
- ball: Tekken Ball unlocked, the save's first match (Gon's) marked played
  (0x80097F1E); a state saved on the grid, then each trial takes the
  fighter under the cursor and the ball and reads the CPU's fighter on the
  loading screen.
Team Battle: tools/test_team_random.py --seed.
Writes workspace/b125/draws-<mode>.json.
"""
import argparse, collections, json, random, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live as L

SCREEN, PHASE, MODE, WINS, SEED = 0x800ae204, 0x800ae224, 0x800afa88, 0x800afaac, 0x8009f2a8
OPPONENTS, CPU_FIGHTER, BLOCKS = 0x800afb18, 0x800add5e, 0x800b8d70
START_SELECT, CROSS = 0xfff6, 0xbfff
BALL_LINE = 6
STOCK = ['Paul', 'Law', 'Lei', 'King', 'Yoshimitsu', 'Nina', 'Hwoarang', 'Xiaoyu', 'Eddy', 'Jin', 'Julia',
         'Kuma', 'Bryan', 'Heihachi', 'Ogre', 'Mokujin', 'Gun Jack', 'Gon', 'Anna', 'Dr. B', 'True Ogre', 'Crow']
HIDDEN = ('devil', 'angel', 'unknown')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--mode', required=True, choices=('arcade', 'timeattack', 'survival', 'ball'))
    ap.add_argument('--trials', type=int, default=200, help='lists drawn (arcade, timeattack), fights (survival), matches (ball)')
    ap.add_argument('--from-wins', type=int, default=16, help='survival: wins counter written at the first fight')
    ap.add_argument('--build', default='build-rel-lite')
    a = ap.parse_args()
    s = L.Session(build=L.ROOT / a.build, env={'TEKKEN3_NATIVE_MOVES': '0'})
    names = [line.split()[0] for line in (s.assets / 'guests.txt').read_text().splitlines() if line.split()]
    name = lambda i: STOCK[i] if i < len(STOCK) else names[i - L.GUEST_ID] if 0 <= i - L.GUEST_ID < len(names) else f'?{i}'
    out = L.ROOT / 'workspace/b125'; out.mkdir(parents=True, exist_ok=True)
    result = dict(mode=a.mode, trials=a.trials)
    try:
        s.wait(lambda: s.value(SCREEN) == 9, 'the selector', 30)
        time.sleep(1)
        if a.mode in ('arcade', 'timeattack'):
            s.write(MODE, 0 if a.mode == 'arcade' else 3)
            time.sleep(.5)
            s.q(cmd='savestate', op='save', slot=5)
            by_stage = [collections.Counter() for _ in range(10)]; players = collections.Counter()
            for trial in range(a.trials):
                s.q(cmd='savestate', op='load', slot=5); time.sleep(.4)
                s.wait(lambda: s.value(SCREEN) == 9, 'selector not restored', 20)
                s.write(SEED, random.getrandbits(32))
                s.press(CROSS)
                s.wait(lambda: s.value(SCREEN) == 11 and s.value(OPPONENTS + 36, 1) == 14, 'no opponent list', 30)
                time.sleep(.8)                  # the mod rewrites it on the loading screen's first frames
                raw = s.read(OPPONENTS, 40)
                players[name(s.value(0x800add5c, 2))] += 1
                for st in range(10): by_stage[st][name(raw[st * 4])] += 1
            stages58 = sum(by_stage[4:8], collections.Counter())
            result.update(players=dict(players),
                          stages_1_4=dict(sum(by_stage[:4], collections.Counter()).most_common()),
                          stages_5_8=dict(stages58.most_common()),
                          stages_5_8_guests=sum(n for k, n in stages58.items() if k in names),
                          stages_5_8_hidden=sum(stages58[k] for k in HIDDEN),
                          stage_9=dict(by_stage[8].most_common()), stage_10=dict(by_stage[9].most_common()),
                          stage_9_hidden=sum(by_stage[8][k] for k in HIDDEN))
        elif a.mode == 'survival':
            s.write(MODE, 4)
            s.press(CROSS)
            s.q(cmd='turbo', enabled=1)
            seen = collections.Counter(); by_wins = []
            for n in range(a.trials):
                s.wait(lambda: s.value(SCREEN) == 8 and s.value(PHASE, 2) >= 6, f'fight {n + 1} start', 120)
                wins = s.value(WINS)
                if n == 0: s.write(WINS, a.from_wins); wins = a.from_wins
                who = name(s.value(CPU_FIGHTER, 2))
                if n: seen[who] += 1                # the first fight is the game's, before the counter was written
                by_wins.append((wins, who))
                end = time.monotonic() + 100
                while s.value(WINS) <= wins and time.monotonic() < end:
                    if s.value(SCREEN) == 8 and s.value(PHASE, 2) >= 6: s.write(0x800aaeaa, 0, 2)
                    time.sleep(.2)
                assert s.value(WINS) > wins, ('fight not won', n, s.value(WINS))
            result.update(fights=dict(seen.most_common()), guests=sum(n for k, n in seen.items() if k in names),
                          hidden=sum(seen[k] for k in HIDDEN), counted=sum(seen.values()), sequence=by_wins)
        else:
            s.write(0x80097f26, 1, 1); s.write(0x80097f27, 1, 1); s.write(0x80097f1e, 1, 1)
            s.press(START_SELECT)
            s.wait(lambda: s.value(SCREEN) == 4, 'the modes menu', 15)
            time.sleep(.3)
            s.write(0x80097f40, BALL_LINE); s.press(CROSS)
            s.wait(lambda: s.value(SCREEN) == 10 and s.value(MODE) == 7 and s.value(BLOCKS) == 3, 'TEKKEN BALL SELECT', 20)
            time.sleep(1.5)
            s.q(cmd='savestate', op='save', slot=5)
            seen = collections.Counter(); players = collections.Counter()
            for trial in range(a.trials):
                s.q(cmd='savestate', op='load', slot=5); time.sleep(.4)
                s.wait(lambda: s.value(SCREEN) == 10 and s.value(BLOCKS) == 3, 'grid not restored', 20)
                s.write(SEED, random.getrandbits(32))
                s.press(CROSS)
                s.wait(lambda: s.value(BLOCKS) == 15, 'the ball choice never came', 10)
                time.sleep(.3)
                s.press(CROSS)
                try: s.wait(lambda: s.value(SCREEN) in (11, 8), 'no loading screen', 20)
                except AssertionError:
                    print('trial', trial, 'screen', s.value(SCREEN), 'phase', s.value(PHASE, 2), 'block', s.value(BLOCKS)); raise
                time.sleep(.3)
                players[name(s.value(0x800add5c, 2))] += 1
                seen[name(s.value(CPU_FIGHTER, 2))] += 1
            result.update(players=dict(players), opponents=dict(seen.most_common()),
                          guests=sum(n for k, n in seen.items() if k in names), hidden=sum(seen[k] for k in HIDDEN))
        log = s.log()
        result['log_hidden'] = len(re.findall(r'TTT1 characters: (?:Devil|Angel|Unknown)\b', log))
        print(json.dumps(result, indent=1))
        (out / f'draws-{a.mode}.json').write_text(json.dumps(result, indent=1) + '\n')
    finally:
        s.stop()


if __name__ == '__main__':
    main()
