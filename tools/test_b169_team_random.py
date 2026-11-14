#!/usr/bin/env python3
"""B169 (GH#215): the player's Team Battle Random fill draws its natives' TTT1 models.

    python tools/test_b169_team_random.py --case team|pose [--seeds 1-4] [--costume ttt|tekken3]
                                          [--size 8] [--build build-rel-lite]

Team Battle, Start on the grid: the game fills both teams (Tekken 3's only
random pick of a player, TIPS section 44).
  team  teams of --size, player 1's all drawn by the Random fill. Under CPU
        COSTUME = TEKKEN TAG TOURNAMENT each of its natives with TTT1 models
        has a line "P1 fighter N placed by the Random fill draws its <key>
        model among n"; under TEKKEN 3, none (the team's costume, F37's 1 in
        6 for Xiaoyu). Then player 1 loses each fight (its life emptied), so
        that each member fights once: the model grafted on P1 for it must be
        the drawn one (the "model: costume k" line read before "model: P1
        model header replaced").
  pose  a team of one, Xiaoyu placed by the Random fill
        (TEKKEN3_TEAM_FILL_NATIVE=7); the CPU loses: Xiaoyu's win pose is
        read (actor +0xA0, moves 0xD67..0xD6A) with her drawn variant and
        her game model (+0x1C). Tekken 3 never plays 0xD67 for model 0x26
        (fighter_win_pose_start, 0x8002D45C), TTT1 never for charno 0x27
        (her school uniform, the Start model).
One session per seed (TEKKEN3_CPU_MOVESET_SEED). Headless, software renderer,
keyboard only (never the player's pad). Exit status 1 on a failure.
"""
import argparse, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live as L

STATE, PHASE, MODE = 0x800AE204, 0x800AE224, 0x800AFA88
TEAMS, TEAM_STRIDE, EMPTY = 0x800AFA88 + 89, 13, 88
ACTOR, ACTOR_STRIDE = 0x800A9228, 0x188C
LIFE = (0x800A961C, 0x800AAEA8)                   # actor +0x3F4, life in the high half
XIAOYU = 7
NAMES = {0: 'Paul', 1: 'Law', 2: 'Lei', 3: 'King', 4: 'Yoshimitsu', 5: 'Nina', 6: 'Hwoarang', 7: 'Xiaoyu', 8: 'Eddy',
         9: 'Jin', 10: 'Julia', 11: 'Kuma', 12: 'Bryan', 13: 'Heihachi', 14: 'Ogre', 15: 'Mokujin', 16: 'Gunjack',
         18: 'Anna', 20: 'Trueogre'}
KEYS = {'LP': 0, 'LK': 1, 'RP': 2, 'RK': 3, 'Start': 4, "random cell's": 7}
POSES = {0xD67: 'pose 1', 0xD68: 'pose 2', 0xD69: 'pose 3', 0xD6A: 'pose 4'}


def ko(s, p):
    life = s.value(LIFE[p])
    if life >> 16: s.write(LIFE[p], life & 0xffff)


def start_teams(s, size):
    if not s.boot: s.write(MODE, 2); s.write(PHASE, 0, 2); s.write(STATE, 10, 2)
    time.sleep(3)
    for _ in range(size - 1): s.press(0xffdf)                      # Right: one more member
    s.press(0xbfff); time.sleep(.8)                                # Cross: the size
    for _ in range(6):
        s.press(0xfff7)                                            # Start: the teams are drawn
        if s.value(STATE) != 10: break
        time.sleep(.8)
    s.wait(lambda: s.value(STATE) in (8, 11), 'no loading screen', 30)
    time.sleep(1)
    return [list(s.read(TEAMS + p * TEAM_STRIDE, 13)) for p in (0, 1)]


def draws(log):
    return {int(i): (KEYS[k], int(n)) for i, k, n in
            re.findall(r'P1 fighter (\d+) placed by the Random fill draws its (.+?) model among (\d)', log)}


def p1_grafts(log):
    """[(name, costume)] of each P1 graft, in order: the costume read just before it."""
    out, last = [], {}
    for line in log.splitlines():
        m = re.match(r'^(\w+) \(TTT1 model\) model: costume (\d+)', line)
        if m: last[m[1]] = int(m[2]); continue
        m = re.match(r'^(\w+) \(TTT1 model\) model: P1 model header replaced', line)
        if m: out.append((m[1], last.get(m[1])))
    return out


def team_case(a, seed, failures):
    s = L.Session(guest='jun', build=L.ROOT / a.build, line=2,
                  env={'TEKKEN3_NATIVE_MOVES': '0', 'TEKKEN3_CPU_COSTUME': a.costume,
                       'TEKKEN3_CPU_MOVESET_SEED': str(seed)})
    try:
        teams = start_teams(s, a.size)
        members = [m >> 2 for m in teams[0][:a.size] if m != EMPTY]
        drawn = draws(s.log())
        natives = [i for i in members if i in NAMES]
        print(f'seed {seed}: P1 team {[NAMES.get(i, i) for i in members]} (by hand {teams[0][10]}), '
              f'draws {[(NAMES[i], v) for i, (v, n) in drawn.items()]}', flush=True)
        if a.costume == 'ttt':
            for i in natives:
                if i not in drawn and i != 17 and i != 19: failures.append(f'seed {seed}: no draw for P1 {NAMES[i]}')
        elif drawn: failures.append(f'seed {seed}: draws under TEKKEN 3: {drawn}')
        # Each member fights once: P1 loses each fight.
        s.q(cmd='turbo', enabled=1)
        seen, t0 = [], time.monotonic()
        while time.monotonic() - t0 < 600 and len(seen) < len(members):
            if s.process.poll() is not None: raise RuntimeError('the game exited')
            state, phase = s.value(STATE), s.value(PHASE, 2)
            if state == 8 and phase >= 6:
                me = s.read(ACTOR + 0x18, 2); me = int.from_bytes(me, 'little')
                if not seen or seen[-1] != me: seen.append(me)
                ko(s, 0)
            elif state not in (8, 9, 10, 11): s.press(0xfff7)
            time.sleep(.1)
        s.q(cmd='turbo', enabled=0)
        grafts = p1_grafts(s.log())
        print(f'  fought {[NAMES.get(i, i) for i in seen]}, P1 grafts {grafts}', flush=True)
        if seen != members: failures.append(f'seed {seed}: fought {seen}, team {members}')
        # Each native's graft (the first one under its name) carries its drawn variant.
        for i in natives:
            if i not in drawn: continue
            got = [c for n, c in grafts if n == NAMES[i]]
            want = drawn[i][0] + 1
            if not got: failures.append(f'seed {seed}: {NAMES[i]} never grafted on P1')
            elif got[0] != want: failures.append(f'seed {seed}: {NAMES[i]} grafted costume {got[0]}, drawn {want}')
        return {NAMES[i]: drawn[i][0] for i in natives if i in drawn}
    finally:
        s.stop()


def pose_case(a, seed, failures):
    s = L.Session(guest='jun', build=L.ROOT / a.build, line=2,
                  env={'TEKKEN3_NATIVE_MOVES': '0', 'TEKKEN3_CPU_COSTUME': a.costume,
                       'TEKKEN3_CPU_MOVESET_SEED': str(seed), 'TEKKEN3_TEAM_FILL_NATIVE': str(XIAOYU)})
    try:
        start_teams(s, 1)
        log = s.log()
        d = draws(log).get(XIAOYU)
        f37 = re.search(rf'P1 fighter {XIAOYU} placed by the Random fill: (its random cell\'s|its costume\'s) model', log)
        variant = d[0] if d else (7 if f37 and 'cell' in f37[1] else None)
        s.wait(lambda: s.value(STATE) == 8 and s.value(PHASE, 2) >= 6 and
               int.from_bytes(s.read(ACTOR + 0x18, 2), 'little') == XIAOYU, "Xiaoyu's fight was not reached", 120)
        model = int.from_bytes(s.read(ACTOR + 0x1C, 2), 'little')
        poses, t0 = set(), time.monotonic()
        while time.monotonic() - t0 < 25:
            if s.value(STATE) == 8: ko(s, 1)
            n = int.from_bytes(s.read(ACTOR + 0xA0, 2), 'little')
            if n in POSES: poses.add(n)
            elif poses: break
            time.sleep(.05)
        if not poses: failures.append(f'seed {seed}: no win pose read')
        bad = 0xD67 in poses and variant == 4
        if bad: failures.append(f'seed {seed}: Xiaoyu in her school uniform (Start model) plays pose 1')
        print(f'pose seed {seed}: variant {variant} (file P{variant + 1 if variant is not None else "?"}), game model '
              f'0x{model:x}, win pose {[POSES[p] + f" 0x{p:X}" for p in sorted(poses)]}{" FAIL" if bad else ""}', flush=True)
        return variant, sorted(poses)
    finally:
        s.stop()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--case', choices=('team', 'pose'), default='team')
    ap.add_argument('--seeds', default='1-4')
    ap.add_argument('--costume', choices=('ttt', 'tekken3'), default='ttt')
    ap.add_argument('--size', type=int, default=8)
    ap.add_argument('--build', default='build-rel-lite')
    a = ap.parse_args()
    lo, _, hi = a.seeds.partition('-')
    failures, results = [], []
    for seed in range(int(lo), int(hi or lo) + 1):
        try:
            results.append((team_case if a.case == 'team' else pose_case)(a, seed, failures))
        except (AssertionError, RuntimeError) as e:
            failures.append(f'seed {seed}: {e}')
    if a.case == 'team' and a.costume == 'ttt':
        tally = {}
        for r in results:
            for v in r.values(): tally[v] = tally.get(v, 0) + 1
        print('variants drawn (variant: count)', dict(sorted(tally.items())))
        if len(tally) < 2: failures.append('one variant only: not a draw')
    for f in failures: print('ECHEC', f)
    print('OK' if not failures else 'ECHEC')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
