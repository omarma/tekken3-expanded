#!/usr/bin/env python3
"""Team Battle's Random fill and the CPU's team, many draws, no fight played.

    python3 tools/test_team_random.py [--trials 60] [--size 8] [--picks 0] [--seed] [--build build-11-lite]

From the private Arcade selector save (slot 7) it opens the Team Battle grid,
sets the team size, picks --picks members by hand for player 1, and saves a
state. Each trial loads that state and presses Start: the game builds both
teams (0x800B0808) and the mod redraws the places nobody picked
(src/tekken3_ttt1_roster.c, team_fill). The teams are read from RAM at the
first frame of the loading screen, before any fight, and the draws' log lines
are counted. Nothing here judges how a fighter looks or plays. The game's
own draw follows its seed (0x8009F2A8), saved with the state: --seed writes
a new one before each Start, so the natives vary too.

Reports, over all trials: how often each fighter fills a Random place of
player 1 and a place of the CPU's team, how many hand picks survived, how
many natives took their TTT1 moves, any fighter found twice in a team, and
how many CPU teams had Devil, Angel or Unknown (B125).
Build: needs the debug server (build-opt-dbg, or a PSX_DEBUG_SERVER_LITE build).
"""
import argparse, collections, json, random, re, struct, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live as L

PAD_START, PAD_CROSS, PAD_RIGHT = 0xfff7, 0xbfff, 0xffdf
TEAMS = (0x800afae1, 0x800afaee)
EMPTY = 88
STOCK = ['Paul', 'Law', 'Lei', 'King', 'Yoshimitsu', 'Nina', 'Hwoarang', 'Xiaoyu', 'Eddy', 'Jin', 'Julia',
         'Kuma', 'Bryan', 'Heihachi', 'Ogre', 'Mokujin', 'Gun Jack', 'Gon', 'Anna', 'Dr. B', 'True Ogre', 'Crow']


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--trials', type=int, default=60)
    ap.add_argument('--size', type=int, default=8, help='team size, 1..8')
    ap.add_argument('--picks', type=int, default=0, help='members player 1 picks by hand before Start')
    ap.add_argument('--fight', action='store_true', help='also wait for the first round and check each first fighter is member 1 of its team')
    ap.add_argument('--first-cell', type=int, default=0, help='grid cell (y * 7 + x) the hand picks start from')
    ap.add_argument('--seed', action='store_true', help="a new seed for the game's own draw before each Start")
    ap.add_argument('--build', default='build-opt-dbg')
    a = ap.parse_args()
    s = L.Session(build=L.ROOT / a.build)
    names = [line.split()[0] for line in (s.assets / 'guests.txt').read_text().splitlines() if line.split()]

    def name(member):
        i = member >> 2
        return STOCK[i] if i < len(STOCK) else names[i - L.GUEST_ID]

    def team(p):
        raw = s.read(TEAMS[p], 13)
        return list(raw[:8]), raw[10], raw[12]

    result = {}
    try:
        s.write(0x800afa88, 2); s.write(0x800ae224, 0, 2); s.write(0x800ae204, 10, 2)
        time.sleep(3)
        for _ in range(a.size - 1): s.press(PAD_RIGHT)
        s.press(PAD_CROSS); time.sleep(.8)
        by_hand = []
        # The cursor (block +8 x, +12 y) written cell after cell: the pad's
        # Right lost presses (Windows, no private save), and a cell taken or
        # locked refuses the pick.
        cells = iter(([(x, y) for y in range(3) for x in range(7)] * 2)[a.first_cell:])
        for _ in range(a.picks):
            for x, y in cells:
                s.write(0x800b8d70 + 8, x); s.write(0x800b8d70 + 12, y); time.sleep(.2)
                s.press(PAD_CROSS); time.sleep(.6)
                if s.value(0x800b8d70 + 44) > len(by_hand): break
            by_hand.append(s.value(0x800b8d70 + 56 + 4 * (len(by_hand))) >> 2)
        assert s.value(0x800b8d70 + 44) == a.picks, ('picks by hand', s.value(0x800b8d70 + 44))
        print('picked by hand:', [name(4 * i) for i in by_hand], flush=True)
        s.q(cmd='savestate', op='save', slot=5)
        random_places = collections.Counter(); cpu_places = collections.Counter()
        toss = collections.Counter(); duplicates = []; wrong_first = []; kept = 0; log_at = len(s.log())
        hidden = ('devil', 'angel', 'unknown'); cpu_boss_teams = collections.Counter(); cpu_boss_place = collections.Counter()
        for trial in range(a.trials):
            s.q(cmd='savestate', op='load', slot=5); time.sleep(.5)
            s.wait(lambda: s.value(0x800ae204) == 10 and s.value(0x800b8d70) == 2, 'grid not restored', 20)
            time.sleep(1.0)
            if a.seed: s.write(0x8009f2a8, random.getrandbits(32))
            for _ in range(4):
                s.press(PAD_START)
                if s.value(0x800ae204) != 10 or team(1)[2]: break
                time.sleep(.8)
            try:
                s.wait(lambda: s.value(0x800ae204) in (11, 8) and team(1)[2] == a.size and team(1)[0][0] != EMPTY, 'teams not built', 20)
            except AssertionError:
                print('trial', trial, 'state', s.value(0x800ae204), 'phase', s.value(0x800ae224, 2), 'block', s.value(0x800b8d70),
                      s.value(0x800b8d70 + 44), 'teams', team(0), team(1)); raise
            time.sleep(.5)                      # the mod redraws on the loading screen's first frames
            for p in range(2):
                members, chosen, size = team(p)
                assert size == a.size, (p, members, size)
                live = [m for m in members[:size] if m != EMPTY]
                if len(set(m >> 2 for m in live)) != len(live): duplicates.append((trial, p, members))
                if p == 0:
                    assert chosen == a.picks, (trial, chosen)
                    kept += sum(1 for i in range(a.picks) if members[i] >> 2 == by_hand[i])
                    for m in members[a.picks:size]: random_places[name(m)] += 1
                else:
                    for m in members[:size]: cpu_places[name(m)] += 1
                    bosses = [i for i, m in enumerate(members[:size]) if name(m) in hidden]
                    cpu_boss_teams[len(bosses)] += 1
                    for i in bosses: cpu_boss_place[i + 1] += 1
            if a.fight:
                s.wait(lambda: s.value(0x800ae204) == 8 and s.value(0x800ae224, 2) >= 6, 'round did not start', 120)
                for p in range(2):
                    want, got = team(p)[0][0] >> 2, s.actor(p)[2]
                    if want != got: wrong_first.append((trial, p, want, got))
            time.sleep(.2)
        text = s.log()[log_at:]
        for who, mover in re.findall(r'Native moves: P(\d)\'s (.*?) fights on TTT1 moves', text): toss[f'P{who}'] += 1
        random_total = sum(random_places.values()); cpu_total = sum(cpu_places.values())
        extras = lambda c: sum(n for k, n in c.items() if k in names or k == 'Mokujin')
        result = dict(trials=a.trials, size=a.size, picks=a.picks, by_hand=[name(4 * i) for i in by_hand], hand_picks_kept=kept,
                      hand_picks_expected=a.picks * a.trials, first_fighter_mismatch=wrong_first, duplicates=duplicates,
                      random_places=random_total, random_places_guest_or_mokujin=extras(random_places),
                      random_fill=dict(random_places.most_common()),
                      cpu_places=cpu_total, cpu_places_guest_or_mokujin=extras(cpu_places),
                      cpu_team=dict(cpu_places.most_common()),
                      hidden_in_random=sum(random_places[n] for n in ('devil', 'angel', 'unknown') if n in random_places),
                      hidden_in_cpu=sum(cpu_places[n] for n in hidden if n in cpu_places),
                      cpu_teams_by_boss_count=dict(sorted(cpu_boss_teams.items())),
                      cpu_boss_by_member=dict(sorted(cpu_boss_place.items())),
                      ttt1_moves_tossed=dict(toss))
        print(json.dumps(result, indent=1))
        (L.WORK / 'team-random.json').write_text(json.dumps(result, indent=1) + '\n')
    finally:
        s.stop()


if __name__ == '__main__':
    main()
