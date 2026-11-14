#!/usr/bin/env python3
"""Save states with Unknown: saving and loading never stops the game (B181).

    python tools/test_b181_unknown_savestate.py [--build build-rel-lite] [--exe <other exe>]
                                                [--case all|<name>] [--cycles 60]

Practice, player 1 Unknown in Yoshimitsu's style (L1), the dummy Jin. Each
cycle saves slot 1 at a random frame, plays on, loads it, and checks the
game still runs (frames advance, no FATAL in the log).

The bug: Unknown's wolf (src/tekken3_ttt1_wolf.c) runs two routines of the
game from C every frame, with 0x80010000 as their return address. A save
taken inside them stored that return address; once loaded, the routine
returned to 0x80010000 with no C frame behind it any more:
'FAIL-FAST unknown dispatch: addr=0x80010054 ... ra=0x80010000'.

  yoshi     her Yoshimitsu style, save and load.
  switch    the same, with an L1 style switch between the save and the load.
  wolf_off  TEKKEN3_UNKNOWN_WOLF=0 (no wolf, no nested call): the control.

Exit status 1 when the game stopped after a load.
"""
import argparse, random, struct, sys, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_b73_stagger_guard as b73
import test_b90_cjm_throw_reversal as b90

b73.WORK = ROOT / 'out/b181'
L1, NONE = b90.L1, b73.NONE
b90.IDS.update({'yoshimitsu': 4, 'jin': 9})

# name: (switch between save and load, environment)
CASES = {
    'yoshi': (False, {}),
    'switch': (True, {}),
    'wolf_off': (False, {'TEKKEN3_UNKNOWN_WOLF': '0'}),
}


class Game(b90.Game):
    def __init__(self, build, tag, exe, extra):
        popen = b73.subprocess.Popen
        def started(*args, **kw):
            if 'env' in kw: kw['env'] = dict(kw['env'], **extra)
            return popen(*args, **kw)
        b73.subprocess.Popen = started
        try: super().__init__(build, tag, exe, 't3')
        finally: b73.subprocess.Popen = popen

    def count(self, text): return self.log().count(text)

    def until(self, text, before, seconds=10):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.count(text) > before: return True
            if 'FATAL' in self.log(): return False
            time.sleep(.02)
        return False


def keep_choices(g, stop):
    """Player 1 Unknown, the dummy Jin, written without pause from the
    selector to the fight: the selector writes its own choices at the dummy's
    confirmation and the loading reads them within a frame or two, a window
    b90.to_practice's 10 ms loop misses on a fast headless build."""
    keys = [l.split()[0] for l in (g.run / 'mods/ttt1/guests.txt').read_text().splitlines() if l.split()]
    p1 = struct.pack('<H', b90.GUEST_ID + keys.index('unknown'))
    while not stop.is_set():
        try:
            if g.value(b73.STATE) in (9, 10, 11):
                g.write(0x800add5c, p1); g.write(0x800add98, b'\0\0')
                g.write(b73.VICTIM, struct.pack('<H', b90.IDS['jin'])); g.write(0x800add9a, b'\0\0')
            else: time.sleep(.005)
        except Exception: time.sleep(.01)


def running(g, frames=40):
    """Frames still advance and nothing fatal in the log."""
    start = g.frame(); end = time.monotonic() + 10
    while time.monotonic() < end:
        if 'FATAL' in g.log(): return False
        if g.frame() - start >= frames: return 'FATAL' not in g.log()
        time.sleep(.02)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--exe')
    ap.add_argument('--case', default='all', choices=['all'] + list(CASES))
    ap.add_argument('--cycles', type=int, default=60)
    ap.add_argument('--seed', type=int, default=181)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    failed = False
    for name in (list(CASES) if a.case == 'all' else [a.case]):
        switch, extra = CASES[name]
        b90.IDS['anna'] = 4                 # b90.to_practice's cursor: Yoshimitsu
        # b90.to_practice writes Unknown and the dummy while the fight loads,
        # a window it sometimes misses: then player 1 is not Unknown, start over.
        for tries in range(4):
            g = Game((ROOT / a.build).resolve(), f'b181-{name}', a.exe, extra)
            stop = threading.Event()
            keeper = threading.Thread(target=keep_choices, args=(g, stop), daemon=True)
            keeper.start()
            try:
                b90.to_practice(g, 't3', 'jin', True)
                stop.set(); keeper.join()
                b90.unknown_style(g, 'Yoshimitsu'); time.sleep(1)
                break
            except AssertionError as e:
                stop.set(); keeper.join()
                print(f'{name}: set-up missed ({e}), again', flush=True)
                g.stop()
        else: raise AssertionError('player 1 never got Unknown')
        loads = 0
        try:
            for k in range(a.cycles):
                g.frames(rng.randrange(3, 40))
                saved = g.count('savestate: SAVED')
                g.q(cmd='savestate', op='save', slot=1)
                if not g.until('savestate: SAVED', saved):
                    print(f'{name} cycle {k}: no save', flush=True); failed = True; break
                pc = g.log().rsplit('savestate: SAVED', 1)[1].split('pc=', 1)[1][:10]
                if switch:
                    g.q(cmd='input_route_clear')
                    g.q(cmd='input_route_append', frames=2, buttons=L1)
                    g.q(cmd='input_route_append', frames=30, buttons=NONE)
                    g.q(cmd='input_route_start')
                g.frames(rng.randrange(10, 60))
                before = g.count('savestate: LOADED')
                g.q(cmd='savestate', op='load', slot=1)
                ok = g.until('savestate: LOADED', before) and running(g)
                loads += ok
                if not ok:
                    fatal = [l for l in g.log().splitlines() if 'FATAL' in l]
                    print(f'{name} cycle {k}: saved at pc={pc}, the game stopped after the load:',
                          fatal[-1] if fatal else 'frames no longer advance', flush=True)
                    failed = True; break
            print(f'{name}: {loads} load(s) of {a.cycles} -> {"ok" if loads == a.cycles else "FAIL"}', flush=True)
        finally:
            g.stop()
    sys.exit(1 if failed else 0)


if __name__ == '__main__': main()
