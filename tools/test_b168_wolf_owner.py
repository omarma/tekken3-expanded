#!/usr/bin/env python3
"""B168 (GH#217): Unknown's wolf only behind Unknown.

    python tools/test_b168_wolf_owner.py [--build build-rel-lite] [--side 1|2|3]
                                         [--opponent-identity unknown|none] [--shots N]

Arcade from a blank card, as tools/test_unknown_wolf.py: Unknown is written
for `--side` while the fight loads, the other side keeps its fighter (player
1's under the cursor, or the CPU's draw) on its Tekken 3 moveset. A player's
guest identity outlives the guest: it stays on the last guest that player
pointed at, while a native fights on its Tekken 3 moves. --opponent-identity
unknown (the default) starts the game with TEKKEN3_GUEST / TEKKEN3_GUEST_P2 on
Unknown, so the other side's leftover identity is hers, as when that player
pointed at her before. Each side's wolf actor (its address from the log) is
placed each frame it is drawn, 800 behind its fighter: the bench samples its
root and counts the samples where it moved (an actor left from an
earlier fight stays put) and is 200..2500 from that side's
fighter. It fails when a side that is not Unknown has a wolf, or Unknown has
none. Exit status 1 on failure.
"""
import argparse, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_unknown_wolf as w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--side', type=int, choices=(1, 2, 3), default=1)
    ap.add_argument('--opponent-identity', choices=('unknown', 'none'), default='unknown')
    ap.add_argument('--cpu-moveset', default='original', help='TEKKEN3_CPU_MOVESET: original (Tekken 3) or ttt1')
    ap.add_argument('--opponent', type=int, help="the other side's native ID (0..19), written with Unknown's")
    ap.add_argument('--seconds', type=float, default=12)
    ap.add_argument('--shots', type=int, default=0)
    a = ap.parse_args()
    build = (w.ROOT / a.build).resolve()
    sides = (1, 2) if a.side == 3 else (a.side,)
    tag = f'b168-{Path(a.build).name}-side{a.side}-{a.opponent_identity}-{a.cpu_moveset}' + (f'-vs{a.opponent}' if a.opponent is not None else '')
    out = w.WORK / tag; out.mkdir(parents=True, exist_ok=True)
    env = {'TEKKEN3_WOLF_TRACE': '1', 'TEKKEN3_CPU_MOVESET': a.cpu_moveset}
    if a.opponent_identity == 'unknown': env.update(TEKKEN3_GUEST='unknown', TEKKEN3_GUEST_P2='unknown')
    g = w.Game(build, tag, False, env)
    try:
        # TEKKEN3_GUEST leaves the catalogue out: Unknown is then the one guest, ID 23.
        unknown = w.GUEST_ID if a.opponent_identity == 'unknown' else w.unknown_id(build)
        if a.opponent is not None and len(sides) == 1:
            other = 3 - sides[0]
            write = g.write
            def both(addr, data):           # the other side's choice goes in with Unknown's
                write(addr, data)
                if addr == 0x800add5c + 2 * (sides[0] - 1):
                    write(0x800add5c + 2 * (other - 1), bytes([a.opponent, 0]))
                    write(0x800add98 + 2 * (other - 1), bytes(2))
            g.write = both
        w.to_fight(g, sides, unknown)
        ids = [g.value(w.ACTOR + p * w.STRIDE + 0x18, 2) for p in (0, 1)]
        time.sleep(3)                                # past the intros
        m = re.search(r"Unknown's wolf: model \d+ B at [0-9A-F]+, packets at [0-9A-F]+, "
                      r"actors at ([0-9A-F]+) ([0-9A-F]+)", g.log())
        if not m: raise AssertionError("no wolf in the log (Unknown's wolf: model ...)")
        wolves = {p: int(m.group(p), 16) for p in (1, 2)}
        drawn, last, n = {1: 0, 2: 0}, {}, int(a.seconds * 4)
        for i in range(n):
            if i < a.shots: g.shot(out / f'shot{i:02d}.png')
            for p, actor in wolves.items():
                d, _, _, root = w.place(g, p, actor)
                drawn[p] += 200 <= d <= 2500 and p in last and root != last[p]
                last[p] = root
            time.sleep(.25)
    finally:
        g.stop()
    lines = [l for l in g.log().splitlines() if 'TTT1 characters: P' in l][-8:]
    print('\n'.join(lines))
    print(f'actors: P1 id {ids[0]}, P2 id {ids[1]} (Unknown {unknown}); wolf placed behind P1 {drawn[1]}/{n}, P2 {drawn[2]}/{n}')
    failures = [f'P{p}: {"no wolf behind Unknown" if p in sides else "a wolf behind a fighter who is not Unknown"}'
                for p in (1, 2) if (drawn[p] >= n // 2) != (p in sides)]
    for f in failures: print('FAIL:', f)
    if failures: sys.exit(1)
    print('OK')


if __name__ == '__main__': main()
