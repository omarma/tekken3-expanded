#!/usr/bin/env python3
"""B167 (GH#214): a CPU Jin or Xiaoyu drawn in the school uniform by CPU COSTUME = TEKKEN TAG
TOURNAMENT (their TTT1 Start model) fights at the school, arena 7, as the uniform's costume 2
does in Tekken 3; every other draw keeps the fighter's own arena (Xiaoyu 3, Jin 8).

    python tools/test_b167_school_uniform.py --mode arcade|timeattack|survival|team
        [--setting t3|ttt|auto|random] [--seed N] [--fights 8] [--force] [--lose-at N]

A private copy of the build (test_stage_options.Game: headless, software x1, keyboard pads,
a copy of saves/), TEKKEN3_CPU_COSTUME=ttt, TEKKEN3_CPU_MOVESET_SEED=--seed, turbo. Arcade and
Time Attack: the ladder (0x800AFB18) rewritten during the first fight, Jin and Xiaoyu in turn
from stage 2. Team Battle --force: the CPU team's next members Jin and Xiaoyu (no guests).
Survival: the game's own opponents (its rotation brings each of the first ten fighters once in
about ten fights; seeds 12 and 13 draw Xiaoyu's uniform). A new fight is a new "TTT Stages:"
decision in the log; once its round runs: the CPU's fighter, costume, its last draw ("draws its
<key> model"), the model file loaded for it and the arena (0x800ADC84). FAIL if a Jin or Xiaoyu
drawn in Start is not on arena 7, or one drawn otherwise not on its own arena, or the model
file is not the draw's. --lose-at N: player 1 loses fight N once and continues: the Continue
must keep the draw and the arena. Seeds that draw uniforms: arcade / timeattack 1 (fights 5-7),
team --force 1 and 4.
"""
import argparse, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_stage_options as S

ARENA, MODE, STAGE_INDEX, OPPONENTS = 0x800adc84, 0x800afa88, 0x800afaac, 0x800afb18
FIGHTERS, COSTUMES, HUMAN = 0x800add5c, 0x800add98, 0x800ae1f8
OWN = {7: 3, 9: 8}
DRAW = re.compile(r'Native models: CPU P(\d) fighter (\d+) draws its (\w+) model')
MODEL = re.compile(r'^(Xiaoyu|Jin) \(TTT1 model\) model: costume (\d)', re.M)
KEYS = ['LP', 'LK', 'RP', 'RK', 'Start']
TEAMS, TEAM_STRIDE = 0x800afa88 + 89, 13
LADDER = [(9, 0), (7, 0), (9, 1), (7, 1), (9, 0), (7, 0), (9, 1)]      # stages 2..8


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', default='arcade', choices=['arcade', 'timeattack', 'survival', 'team'])
    ap.add_argument('--setting', default='t3', choices=['t3', 'ttt', 'auto', 'random'])
    ap.add_argument('--seed', default='1')
    ap.add_argument('--fights', type=int, default=8)
    ap.add_argument('--build', default=str(ROOT / 'build-rel-lite'))
    ap.add_argument('--mods', default='')
    ap.add_argument('--before', action='store_true')
    ap.add_argument('--lose-at', type=int, default=0, help='player 1 loses fight N once and continues: the same draw, the same arena')
    ap.add_argument('--force', action='store_true', help="Team Battle: the CPU team's next members Jin and Xiaoyu")
    ap.add_argument('--minutes', type=float, default=15)
    a = ap.parse_args()
    env = {'TEKKEN3_TEAM_GUESTS': '1,0,0'} if a.force else {}
    env.update({'TEKKEN3_CPU_COSTUME': 'ttt', 'TEKKEN3_CPU_MOVESET_SEED': a.seed, 'TEKKEN3_STAGES': a.setting,
           'TEKKEN3_STAGES_TTT': '1', 'TEKKEN3_STAGES_SEED': a.seed})
    g = S.Game(Path(a.build), a.mods or None, env, f'b167-{a.mode}-{a.setting}-{a.seed}')
    rows, fails, ladder_done, loaded, forced, target, decisions, lost = [], 0, False, False, False, 0, 0, 0
    try:
        g.modes_menu(); g.mode(S.MODES[a.mode])
        g.wait(lambda: g.screen() in (9, 10), 'no selector'); time.sleep(2)
        g.q(cmd='turbo', enabled=1)
        end = time.monotonic() + a.minutes * 60
        while len(rows) < a.fights and time.monotonic() < end:
            s = g.screen()
            n = len(S.DECISION.findall(g.log()))
            if n > decisions: decisions, loaded = n, True       # a fight set up (its STAGES decision)
            if s in (9, 10):
                forced = False
                g.press(S.CROSS)
                if a.mode == 'team': g.press(S.RIGHT)
            elif s == 8 and g.value(S.PHASE, 2) == 8:
                cpu = 1 if g.value(HUMAN + 2, 2) == 0 else 0
                fid, costume = g.value(FIGHTERS + 2 * cpu, 2), g.value(COSTUMES + 2 * cpu, 2) & 3
                if a.mode in ('arcade', 'timeattack') and not ladder_done:
                    for i, (f, c) in enumerate(LADDER):
                        g.write(OPPONENTS + 4 * (i + 1), f, 1); g.write(OPPONENTS + 4 * (i + 1) + 1, c, 1)
                    ladder_done = True
                if a.force and a.mode == 'team' and not forced:
                    # The CPU team's next members (ID * 4 + costume), Jin and Xiaoyu in turn.
                    team = TEAMS + TEAM_STRIDE * cpu
                    for i in range(1, 8):
                        if g.value(team + i, 1) != 88: g.write(team + i, (9 if i % 2 else 7) * 4, 1)
                    forced = True
                if loaded:                                   # the fight that just loaded
                    loaded = False
                    arena = g.value(ARENA, 2)
                    draws = [d for d in DRAW.findall(g.log()) if int(d[0]) == cpu + 1 and int(d[1]) == fid]
                    drawn = draws[-1][2] if draws else '-'
                    want = None
                    if fid in OWN and costume < 2: want = 7 if drawn == 'Start' else OWN[fid]
                    # The model loaded for it: the file of the draw (P1..P5).
                    models = [int(m[1]) for m in MODEL.findall(g.log()) if m[0] == ('Xiaoyu' if fid == 7 else 'Jin')]
                    if want is not None and drawn in KEYS and models and models[-1] != KEYS.index(drawn) + 1: want = 'model'
                    ok = want is None or arena == want
                    if not ok and not a.before: fails += 1
                    rows.append((fid, costume, drawn, arena, want, ok))
                    print(f'fight {len(rows)}: CPU P{cpu + 1} fighter {fid} costume {costume} drew {drawn}: arena {arena}'
                          f'{"" if want is None else f" (want {want}) " + ("OK" if ok else "FAIL")}', flush=True)
                if len(rows) == a.lose_at and lost < 1:      # player 1 loses this fight once, continues
                    if g.value(S.P1_LIFE, 2) > 0: g.write(S.P1_LIFE, 0, 2)
                elif g.value(S.P2_LIFE if cpu else S.P1_LIFE, 2) > 0: g.write(S.P2_LIFE if cpu else S.P1_LIFE, 0, 2)
            elif s == 8 and len(rows) == a.lose_at and lost < 1 and g.value(HUMAN, 2) == 0:
                g.press(S.START); lost += 1; time.sleep(.5)          # the Continue's countdown
            elif s in (12, 16, 17): g.press(S.START)
            time.sleep(.2)
    finally:
        g.stop()
        log = g.log()
        for line in log.splitlines():
            if line.startswith(('B167TRACE', 'TTT Stages:')) or 'school uniform' in line or 'Native models: CPU' in line:
                print('log:', line)
    if a.lose_at:
        again = [r for r in rows[a.lose_at:a.lose_at + 1]]
        same = again and rows[a.lose_at - 1][:4] == again[0][:4]
        print(f'Continue: fight {a.lose_at} {rows[a.lose_at - 1][:4]} then {again[0][:4] if again else None}',
              'OK' if same else 'FAIL')
        if not same: fails += 1
    uniforms = sum(1 for r in rows if r[0] in OWN and r[2] == 'Start')
    print(f'{len(rows)} fights, {uniforms} in the school uniform, {fails} FAIL')
    if not a.before and fails: sys.exit(1)


if __name__ == '__main__': main()
