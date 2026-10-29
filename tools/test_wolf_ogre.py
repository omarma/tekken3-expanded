#!/usr/bin/env python3
"""Unknown's wolf on the final stages (B111): does it trail her against Ogre
and True Ogre as in an ordinary fight?

    python tools/test_wolf_ogre.py [--build build-rel-lite] [--frames 240] [--off]
                                   [--stages auto|t3|ttt] [--ps1]

Cold start (tools/test_unknown_wolf.py's Game), Arcade, Unknown written for
player 1 at each loading screen; the first fight counts as stage 9 (0x800AFAAC
= 8, as tools/test_ogre_lift.py), so Ogre comes next, then True Ogre in the
dark arena (0x800AFAA0). Player 2's life is emptied in turbo. In the first
fight, against Ogre and against True Ogre, turbo off, player 1 walks forward
then back for --frames frames each way while the bench samples her root
(actor +0xF54 + 0x14), the wolf's (its actor from the log) and the game's
counters: the stage tiles' frame counter 0x800A08F0 and the dark arena flag.

The check, in each fight: the wolf's root travels with hers (its travel on
the floor at least half of hers, hers over 300) and stays within 2500 of her.
--stages: TEKKEN3_STAGES (the STAGES row; True Ogre's dark arena keeps its
Tekken 3 stage in AUTO and T3, the TTT stage 14 in TTT); --ps1: the PS1
stages (no Arcade Stages packs). Exit status 1 when a check fails. One game:
run it through slot.py.
"""
import argparse, re, struct, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_unknown_wolf as W

STAGE, DARK, COUNTER = 0x800AFAAC, 0x800AFAA0, 0x800A08F0
P2_LIFE, OGRE, TRUE_OGRE = 0x800AAEA8, 14, 20
RIGHT, LEFT = 0xffdf, 0xff7f


def s32(b, o): return struct.unpack_from('<i', b, o)[0]


def root(g, actor):
    b = g.read(actor + W.ROOT_M + 0x14, 12)
    return [s32(b, 4 * k) for k in range(3)]


def sample(g, wolf, frames, name):
    """Turbo off; player 1 walks forward then back; her root, the wolf's, the counters."""
    g.q(cmd='turbo', enabled=0)
    rows = []
    for buttons in (RIGHT, LEFT):
        g.q(cmd='press', buttons=buttons, frames=frames)
        end = time.monotonic() + frames / 60 + .5
        while time.monotonic() < end:
            if g.value(W.STATE) != 8 or g.value(W.PHASE, 2) < 6: break
            her = root(g, W.ACTOR)
            w = root(g, wolf) if wolf else [0, 0, 0]
            rows.append((g.value(COUNTER), g.value(DARK, 1), her, w))
            time.sleep(.05)
    if not rows: return None
    span = lambda pts: max(max(p[k] for p in pts) - min(p[k] for p in pts) for k in (0, 2))
    hers, wolfs = [r[2] for r in rows], [r[3] for r in rows]
    far = max(((a[0] - b[0]) ** 2 + (a[2] - b[2]) ** 2) ** .5 for a, b in zip(hers, wolfs))
    counter = rows[-1][0] - rows[0][0]
    print(f'{name}: {len(rows)} samples, dark {sorted({r[1] for r in rows})}, counter +{counter}, '
          f'her travel {span(hers)}, wolf travel {span(wolfs)}, farthest {far:.0f}', flush=True)
    for r in rows[::max(1, len(rows) // 6)]: print(f'  counter {r[0]} dark {r[1]} her {r[2]} wolf {r[3]}', flush=True)
    return span(hers), span(wolfs), far


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--frames', type=int, default=240)
    ap.add_argument('--off', action='store_true', help='TEKKEN3_UNKNOWN_WOLF=0')
    ap.add_argument('--stages', default='auto', choices=['auto', 't3', 'ttt'])
    ap.add_argument('--ps1', action='store_true', help='no Arcade Stages packs: the PS1 stages')
    ap.add_argument('--visible', action='store_true')
    a = ap.parse_args()
    build = (W.ROOT / a.build).resolve()
    env = {'TEKKEN3_WOLF_TRACE': '1', 'TEKKEN3_STAGES': a.stages}
    if a.off: env['TEKKEN3_UNKNOWN_WOLF'] = '0'
    if a.ps1:
        empty = W.WORK / 'no-arcade-stages'; empty.mkdir(parents=True, exist_ok=True)
        env['TEKKEN3_ARCADE_STAGES_DIR'] = str(empty)
    g = W.Game(build, f'ogre-{a.stages}' + ('-ps1' if a.ps1 else '') + ('-off' if a.off else ''), a.visible, env)
    unknown = W.unknown_id(build)
    failures, results = [], {}
    try:
        W.to_fight(g, (1,), unknown)
        g.write(STAGE, bytes([8]))                  # the next fight is Ogre's
        time.sleep(2)
        m = re.search(r"Unknown's wolf: model \d+ B at [0-9A-F]+, packets at [0-9A-F]+, actors at ([0-9A-F]+)", g.log())
        wolf = int(m.group(1), 16) if m and not a.off else 0
        if not a.off and not wolf: raise AssertionError("no wolf in the log (Unknown's wolf: model ...)")
        results['first fight'] = sample(g, wolf, a.frames, 'first fight')
        g.q(cmd='turbo', enabled=1)
        end, loading = time.monotonic() + 1500, False
        while time.monotonic() < end and len(results) < 3:
            st, ph = g.value(W.STATE), g.value(W.PHASE, 2)
            if st == 11 and not loading:
                g.write(0x800add5c, struct.pack('<H', unknown)); g.write(0x800add98, b'\0\0')
                loading = True
            if st != 11: loading = False
            if st == 8 and 6 <= ph < 9:
                opponent = g.value(W.ACTOR + W.STRIDE + 0x18, 2)
                name = {OGRE: 'Ogre', TRUE_OGRE: 'True Ogre'}.get(opponent)
                if name and name not in results and g.value(W.ACTOR + 0x18, 2) == unknown:
                    time.sleep(.5)
                    results[name] = sample(g, wolf, a.frames, name)
                    g.q(cmd='turbo', enabled=1)
                    continue
                life = g.value(P2_LIFE)
                if life >> 16: g.write(P2_LIFE, struct.pack('<I', life & 0xFFFF))
            time.sleep(.01)
    finally:
        g.stop()
    for name in ('first fight', 'Ogre', 'True Ogre'):
        r = results.get(name)
        if r is None: failures.append(f'{name}: not reached'); continue
        hers, wolfs, far = r
        if a.off: continue
        if hers < 300: failures.append(f'{name}: she moved {hers} only')
        elif wolfs < hers / 2: failures.append(f'{name}: the wolf moved {wolfs} for her {hers}')
        if far > 2500: failures.append(f'{name}: the wolf {far:.0f} from her')
    for f in failures: print('FAIL:', f)
    if failures: sys.exit(1)
    print('OK')


if __name__ == '__main__': main()
