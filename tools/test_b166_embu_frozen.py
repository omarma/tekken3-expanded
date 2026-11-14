#!/usr/bin/env python3
"""B166: the attract's TTT Embu after a fight left during its K.O. replay, its actors frozen.

    python tools/test_b166_embu_frozen.py OUT [--build DIR] [--plan quit:9:replay,embu]
                                          [--force-replay N] [--env KEY=VALUE] [--visible]

Each actor's animation step (0x8003A818) first replays a recorded frame of the
last fight (replay_move_restore, replay_state 0x8009BCA8 = 1, 3, 4, 6); the
round's setup (0x8002A914) turns it off, which the engine's scene skips: a
fight left by Start + Select during its K.O. replay kept it on, and the TTT
Embu after it held its actors in a frame of that fight.

Boots a private copy of the build (tools/cine_drive.py) and runs the plan:
  quit:<fighter>:<fight|replay>  Arcade (a native's ID[/t3|ttt1|dr] or a guest key),
                                 left by Start + Select in the fight or during the K.O. replay
  arcade:<fighter>               Arcade, player 1 idle until the game over
  l2                             the modes menu, L2 held: the TTT Embu next (TIPS 135)
  embu                           the attract's next Embu, whichever (turbo up to it)
At frames 300, 900, 1500 of each Embu: replay_state, the actors' records,
their bones' world rotations against 12 frames later, a screenshot. The TTT
Embu fails if an actor never moves; the game's own Embus are told, not judged
(they step one actor at a time). --force-replay N writes replay_state as the
TTT Embu loads (N = 1: frozen before the fix, from a cold start). Exit 1 on a
failure; OUT/result.json. Run through ressources/slot.py (--kind game).
"""
import argparse, json, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cine_drive as cd

ACTOR0, ACTOR_SIZE, JOINTS = 0x800a9228, 0x188c, 0x8f4
CHECK = (300, 900, 1500)
REPLAY_STATE = 0x8009bca8     # replay_state: 1, 3, 4, 6 replay a recorded frame (replay_move_restore)
FORCE = None
WRITES = []
PAUSE_REQUEST, FIGHT_FREEZE = 0x8009548c, 0x80095468


def bones(g, p):
    """The world rotations (3 x 3 int16, the first 18 bytes of each joint) of bones 1..11:
    a pose held with its root sliding or the camera moving keeps them."""
    raw = g.read(ACTOR0 + p * ACTOR_SIZE + JOINTS, 0x44 * 12)
    return b''.join(raw[0x44 * i:0x44 * i + 18] for i in range(1, 12))


def scene_frame(g, start): return g.frame() - start


def embu(g, out, n, results):
    """The attract's next Embu, whichever the rotation plays (T3 v0 / v1 / v2, the guests', the TTT one)."""
    end = time.monotonic() + 1800
    seen = g.log().count('Cine scene: loading')
    g.q(cmd='turbo', enabled=1)
    while g.value(cd.STATE, 2) == 6:                    # out of the one playing
        if time.monotonic() > end: raise AssertionError('state 6 never left')
        time.sleep(.05)
    # The game's Embus stay in state 6; the TTT one leaves it at once for its scene's loading.
    while g.value(cd.STATE, 2) != 6 and g.log().count('Cine scene: loading') <= seen:
        if time.monotonic() > end: raise AssertionError('no Embu came')
        time.sleep(.02)
    time.sleep(.5)
    log = g.log()
    kinds = re.findall(r'Cine trigger: Embu rotation, ([^\n]*)', log)
    kind = kinds[-1] if kinds else 'game'
    ttt = log.count('Cine scene: loading') > seen
    if ttt and FORCE is not None:
        g.write(REPLAY_STATE, FORCE)
        print(f'  replay_state forced to {FORCE} as the scene loads', flush=True)
    if ttt:
        for kv in WRITES:
            addr, value = (int(x, 0) for x in kv.split('='))
            g.write(addr, value)
            print(f'  {addr:08x} forced to {value} as the scene loads', flush=True)
    if ttt:
        while g.log().count('pace held, the scene') <= seen:
            if time.monotonic() > end: raise AssertionError('the TTT Embu never played')
            time.sleep(.05)
    g.q(cmd='turbo', enabled=0)
    start = g.frame()
    row = {'embu': n, 'kind': kind, 'ttt': ttt, 'checks': []}
    print(f'Embu {n}: {kind}{" (the engine)" if ttt else ""}', flush=True)
    for at in CHECK:
        while g.frame() - start < at: time.sleep(.02)
        if not ttt and g.value(cd.STATE, 2) != 6: break
        a = [bones(g, p) for p in (0, 1)]
        t = g.frame()
        while g.frame() < t + 12: time.sleep(.01)
        b = [bones(g, p) for p in (0, 1)]
        moved = [a[p] != b[p] for p in (0, 1)]
        rec = [g.value(ACTOR0 + p * ACTOR_SIZE + 0x54) for p in (0, 1)]
        row.setdefault('replay_state', []).append(g.value(REPLAY_STATE))
        ids = [g.value(ACTOR0 + p * ACTOR_SIZE + 0x18, 2) for p in (0, 1)]
        g.q(cmd='screenshot_file', path=str((out / f'embu{n}_{at:05d}.png').resolve()))
        row['checks'].append({'frame': at, 'moved': moved, 'record': [f'{r:08x}' for r in rec], 'ids': ids})
        print(f'  frame {at}: replay_state {g.value(REPLAY_STATE)}, ids {ids}, records {[hex(r) for r in rec]}, moved {moved}', flush=True)
    # A hidden actor is not stepped (frame 300: the opening shot): each must move in one check at least.
    # The game's own Embus (T3 v0 / v1 / v2, the guests') step one actor at a time: told, not judged.
    row['ok'] = not ttt or all(any(c['moved'][p] for c in row['checks']) for p in (0, 1))
    results.append(row)


CURSOR_CHAR, CARD_RIGHT = 0x80118668, cd.RIGHT


def to_arcade_native(g, nid, rights):
    """The Arcade selector, player 1 on native `nid` with Square; the MOVESET card
    that opens takes the TTT1 moves (Right) or Tekken 3's, then Square again."""
    def menu():
        if g.value(cd.STATE) == 3: g.press(cd.START)
        return g.value(cd.STATE) == 4
    g.q(cmd='turbo', enabled=1)
    g.wait(menu, 'the modes menu never came', 180)
    time.sleep(.3)
    g.write(cd.LINE, 0); g.press(cd.CROSS)
    g.wait(lambda: g.value(cd.STATE) == 9 and g.value(0x80118648) == 21, 'the Arcade selector never came', 60)
    g.q(cmd='turbo', enabled=0)
    time.sleep(1.5)
    for vertical in (cd.DOWN, cd.DOWN, cd.UP, cd.UP, cd.UP, cd.DOWN):
        for _ in range(12):
            if g.value(CURSOR_CHAR) == nid: break
            g.press(cd.RIGHT)
        if g.value(CURSOR_CHAR) == nid: break
        g.press(vertical)
    if g.value(CURSOR_CHAR) != nid: raise AssertionError(f'the cursor never reached {nid}')
    mark = len(g.log())
    g.press(cd.SQUARE); time.sleep(1)
    if 'opens the MOVESET card' in g.log()[mark:]:
        want = ('t3', 'ttt1', 'dr')[rights]
        for _ in range(8):
            lit = re.findall(r'highlights (\w+) moves', g.log()[mark:])
            if (lit[-1] if lit else 't3') == want: break
            g.q(cmd='press', buttons=CARD_RIGHT, frames=8); time.sleep(.8)
        for _ in range(5):
            if 'takes' in g.log()[mark:] or g.value(cd.STATE) != 9: break
            g.q(cmd='press', buttons=cd.SQUARE, frames=8); time.sleep(1)
        print('  card:', [l for l in g.log()[mark:].splitlines() if 'Native moves' in l], flush=True)


def arcade(g, key):
    if key.isdigit() or key.split('/')[0].isdigit():
        nid, _, moves = key.partition('/')
        to_arcade_native(g, int(nid), {'t3': 0, 'ttt1': 1, 'dr': 2}[moves or 'ttt1'])
    else: cd.to_arcade_guest(g, key)
    g.q(cmd='turbo', enabled=1)
    g.wait(lambda: g.value(cd.STATE) == 8, 'no fight', 300)
    # Player 1 idle: the CPU wins; the game over goes back to the title.
    g.wait(lambda: g.value(cd.STATE) in (2, 3), 'never back to the title', 1200)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=Path)
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--plan', default='quit:9:replay,embu')
    ap.add_argument('--visible', action='store_true')
    ap.add_argument('--env', action='append', default=[], help='KEY=VALUE for the game')
    ap.add_argument('--write', action='append', default=[], help='ADDR=VALUE (word) written as the TTT Embu loads')
    ap.add_argument('--force-replay', type=int, help='replay_state written as the TTT Embu loads')
    a = ap.parse_args()
    global FORCE
    FORCE = a.force_replay
    WRITES.extend(a.write)
    a.out.mkdir(parents=True, exist_ok=True)
    g = cd.Game(ROOT / a.build, a.out, dict(kv.split('=', 1) for kv in a.env), a.visible, mods_state='format_version = 2\n')
    results, n = [], 0
    try:
        for step in a.plan.split(','):
            print('step', step, flush=True)
            if step == 'embu': n += 1; embu(g, a.out, n, results)
            elif step.startswith('arcade:'): arcade(g, step.split(':', 1)[1])
            elif step.startswith('quit:'):
                # quit:<fighter>:<fight|replay>: an Arcade left by Start + Select (the modes menu),
                # in the fight or while its K.O. replays (replay_state 1, 3 or 6), player 1 idle.
                _, key, when = step.split(':')
                if key.split('/')[0].isdigit():
                    nid, _, moves = key.partition('/')
                    to_arcade_native(g, int(nid), {'t3': 0, 'ttt1': 1, 'dr': 2}[moves or 't3'])
                else: cd.to_arcade_guest(g, key)
                g.q(cmd='turbo', enabled=1)
                g.wait(lambda: g.value(cd.STATE) == 8 and g.value(cd.PHASE, 2) == 8, 'no fight', 300)
                if when.startswith('win1'):
                    # The first fight won (player 2's life emptied each round), the second left.
                    while g.value(cd.STATE) != 11:
                        if g.value(cd.STATE) == 8 and 6 <= g.value(cd.PHASE, 2) < 9:
                            life = g.value(cd.P2_LIFE)
                            if life >> 16: g.write(cd.P2_LIFE, life & 0xFFFF)
                        time.sleep(.01)
                    g.wait(lambda: g.value(cd.STATE) == 8 and g.value(cd.PHASE, 2) == 8, 'no second fight', 300)
                    g.q(cmd='turbo', enabled=0); time.sleep(2)
                elif when == 'replay':
                    g.wait(lambda: g.value(REPLAY_STATE) in (1, 3, 6), 'no K.O. replay', 900)
                    g.q(cmd='turbo', enabled=0); time.sleep(1)
                else:
                    g.q(cmd='turbo', enabled=0); time.sleep(3)
                if when.endswith('pause'):
                    # Start: the pause menu (pause_request 0x8009548C), then Start + Select from it.
                    g.q(cmd='press', buttons=cd.START, frames=4); time.sleep(1.5)
                    print(f'  paused: pause_request {g.value(PAUSE_REQUEST)}', flush=True)
                at = g.value(REPLAY_STATE)
                g.q(cmd='press', buttons=0xfff6, frames=30)
                g.wait(lambda: g.value(cd.STATE) != 8, 'Start + Select did not leave the fight', 30)
                print(f'  left the fight with replay_state {at}, then {g.value(REPLAY_STATE)}; pause_request '
                      f'{g.value(PAUSE_REQUEST)}, fight_freeze {g.value(FIGHT_FREEZE)}', flush=True)
            elif step == 'l2':
                # The modes menu, L2 held until it goes back to the title: the TTT Embu next (TIPS 135).
                g.q(cmd='turbo', enabled=1)
                g.wait(lambda: g.value(cd.STATE, 2) == 4 or (g.value(cd.STATE, 2) == 3 and g.press(cd.START)),
                       'the modes menu never came', 600)
                g.q(cmd='turbo', enabled=0)
                g.q(cmd='press', buttons=0xfffe, frames=700)
                g.wait(lambda: g.value(cd.STATE, 2) != 4, 'the menu never left', 60)
            else: raise SystemExit(f'unknown step {step}')
    finally:
        g.stop()
    (a.out / 'result.json').write_text(json.dumps(results, indent=1))
    bad = [r['embu'] for r in results if not r['ok']]
    print('frozen Embu:', bad if bad else 'none', '->', 'ECHEC' if bad else 'OK')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
