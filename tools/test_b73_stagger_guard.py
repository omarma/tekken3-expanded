#!/usr/bin/env python3
"""A native hit by a TTT1 string guards its next hit as in TTT1 (B73).

    python tools/test_b73_stagger_guard.py [--build build-opt-dbg] [--string uf4|d3_2|all]
                                           [--victim xiaoyu] [--exe <other exe>]

Practice, player 1 on Jin's / Nina's TEKKEN TAG TOURNAMENT moves, player 2 a
T3 native (Xiaoyu by default) in the dummy's CONTROLLER mode (0x800B8BDD = 8),
its pad driven by the debug server (set_input port=2). Player 1 walks into
range once (savestate 1); each plan reloads it and plays the string as a
frame route while player 2 plays its plan. The hits that deal damage
(Practice TOTAL DMG, 0x800B8B94) are counted against TTT1's (MAME tektagt,
tools/ttt1_guard_probe.lua, 2026-10-22, same plans):

  uf4   Jin u/f+4, 4, 4, 4 (pack 156 high, 295, 299 low, 301).
        stand: the high is guarded, the low 295 and the rest land (2 or more).
        stand_down_back: down-back from frame 30, nothing lands (0).
        forward_down_back: player 2 walks into the first hit (no counter),
        which leaves it on the stagger 707 (0x22C3); down-back held from frame
        30 leaves 707 at its 40th frame on the guard 783 (the native's own
        0xD59) and nothing else lands (1). The bug: 2, the native stayed on
        707 to its end and the mid 301 hit it crouched.
  d3_2  Nina d+3, 2: none, both land (2); back held from frame 8, 14 or 20
        guards the mid (1).

Build: pad 2 needs the debug server's port 2 (PSX_DEBUG_TOOLS=ON); a rel-lite
build compiles it out (apply_p2_override_to_sio) and player 2 then never
moves: every plan reads as no guard. A full build drops a copied mods/ttt1.
A plan whose first hit misses (a pad written by TCP lands a frame or two
apart) is played again, up to four times.

The check, on the fixed build:  --build <debug build>  (exit 0).
Exit status 1 when a guarding plan's hit count is not TTT1's (the bug:
__wrap_func_8002CC28 refused the victim's back entries of the guest's
reaction record, B73); 2 when a plan without guard did not land two hits
(the bench lost the string: nothing measured).
"""
import argparse, os, shutil, socket, struct, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'psxrecomp/tools'))
import debug_client

WORK = ROOT / 'out/b73'
STATE, CURSOR_CHAR, GRID, LINE = 0x800ae204, 0x80118668, 0x80118648, 0x80097f40
ACTOR, STRIDE = 0x800a9228, 0x188c
DUMMY, TOTAL, VICTIM = 0x800b8bdd, 0x800b8b94, 0x800add5e
START, CROSS, SQUARE, RIGHT, LEFT, DOWN, UP = 0xfff7, 0xbfff, 0x7fff, 0xffdf, 0xff7f, 0xffbf, 0xffef
TRIANGLE, CIRCLE, NONE = 0xefff, 0xdfff, 0xffff
PRACTICE = 5                     # 0x800AFA88 mode of the modes menu's Practice line
IDS = {'paul': 0, 'law': 1, 'nina': 5, 'xiaoyu': 7, 'jin': 9, 'heihachi': 13}
BACK, FORWARD, DOWN_BACK = RIGHT, LEFT, DOWN & RIGHT     # player 2 starts on the right

# (fighter, player 1's route [(frames, pad)], plans {name: (hits, [(frame, pad)])}): hits, the
# hits that deal damage in TTT1 (MAME); None: no guard, at least two must.
STRINGS = {
    'uf4': ('jin', [(3, UP & RIGHT), (3, UP & RIGHT & CIRCLE)] + [(7, NONE), (3, CIRCLE)] * 10, {
        'stand': (None, []),
        'stand_down_back': (0, [(30, DOWN_BACK)]),
        'forward_down_back': (1, [(0, FORWARD), (26, NONE), (30, DOWN_BACK)]),
    }),
    'd3_2': ('nina', [(3, DOWN), (3, DOWN & CROSS), (6, NONE), (3, TRIANGLE), (40, NONE)], {
        'none': (None, []),
        'back8': (1, [(8, BACK)]),
        'back14': (1, [(14, BACK)]),
        'back20': (1, [(20, BACK)]),
    }),
}


class Game:
    def __init__(self, build, tag, exe=None, visible=False):
        run = WORK / f'run-{os.getpid()}-{tag}'
        shutil.rmtree(run, ignore_errors=True); run.mkdir(parents=True)
        built = next(p for p in (build / 'Tekken_3_Expanded.exe', build / 'Tekken_3_Expanded') if p.exists())
        shutil.copy2(exe or built, run / built.name)
        for name in ('bios', 'mods'):       # links, not copies: the catalogue is large
            if os.name == 'nt':
                subprocess.run(['cmd', '/c', 'mklink', '/J', str(run / name), str(build / name)], check=True, capture_output=True)
            else: (run / name).symlink_to(build / name)
        (run / 'settings.toml').write_text('[video]\nsupersampling=1\nantialiasing=false\n'
                                           '[controller]\np1_device="keyboard"\np2_device="keyboard"\n')
        cards = run / 'cards'; cards.mkdir()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); self.port = listener.getsockname()[1]
        self.log_path = WORK / f'{tag}.log'
        environ = {k: v for k, v in os.environ.items() if not k.startswith('TEKKEN3_')}
        environ['SDL_AUDIO_DRIVER'] = 'dummy'
        args = [str(run / built.name), '--game', str(ROOT / 'game.toml'), '--disc', str(ROOT / 'disc/Tekken 3 (USA).cue'),
                '--no-launcher', '--renderer', 'software', '--debug-port', str(self.port),
                '--memcard-dir', str(cards)] + ([] if visible else ['--headless'])
        self.out = self.log_path.open('w')
        self.process = subprocess.Popen(args, cwd=ROOT, stdout=self.out, stderr=self.out, env=environ)
        self.run = run
        deadline = time.monotonic() + 60
        while True:
            if self.process.poll() is not None: raise RuntimeError(f'game exited; see {self.log_path}')
            try:
                with socket.create_connection(('127.0.0.1', self.port), .2): break
            except OSError:
                if time.monotonic() > deadline: raise RuntimeError('debug endpoint did not start')
                time.sleep(.2)

    def q(self, **r):
        for _ in range(600):
            result = debug_client.query('127.0.0.1', self.port, r)
            if result.get('err') != 'emu busy or frozen': break
            time.sleep(.1)
        if result.get('ok') is False: raise RuntimeError((r, result))
        return result

    def read(self, a, n=4): return bytes.fromhex(self.q(cmd='read_ram', addr=f'{a:08x}', len=n)['hex'])
    def value(self, a, n=4): return int.from_bytes(self.read(a, n), 'little')
    def write(self, a, data): self.q(cmd='write_ram', addr=f'{a:08x}', bytes=data.hex())
    def press(self, b, frames=4): self.q(cmd='press', buttons=b, frames=frames); time.sleep(.25)
    def frame(self): return self.q(cmd='frame')['frame']
    def frames(self, n):
        end = self.frame() + n
        while self.frame() < end: time.sleep(.001)
    def log(self): return self.log_path.read_text(errors='replace')

    def wait(self, predicate, what, seconds=120, step=None):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if predicate(): return
            if step: step()
            time.sleep(.1)
        raise AssertionError(what)

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=10)
            except subprocess.TimeoutExpired: self.process.kill()
        self.out.close()
        for name in ('bios', 'mods'):
            if os.name == 'nt': subprocess.run(['cmd', '/c', 'rmdir', str(self.run / name)], capture_output=True)
            else: (self.run / name).unlink(missing_ok=True)
        shutil.rmtree(self.run, ignore_errors=True)


def menu_line(g, mode):
    """The modes menu's line of a mode: 8-byte rows (label, then the mode in
    byte + 4) at the menu state + 16, their count at + 4 (TIPS.md section 26)."""
    state = (g.value(0x800db5d0) & 0xffff) << 16 | g.value(0x800db5d8) & 0xffff
    for line in range(min(g.value(state + 4), 16)):
        if g.value(state + 16 + 8 * line + 4, 1) == mode: return line
    raise AssertionError(f'mode {mode} is not on the modes menu')


def x(g, p): return struct.unpack('<i', g.read(ACTOR + p * STRIDE + 0x908, 4))[0]


def to_practice(g, fighter, victim):
    """Practice, player 1 on the fighter's TTT1 MOVESET card, the dummy
    written while the fight loads, then CONTROLLER."""
    g.q(cmd='turbo', enabled=1)
    g.wait(lambda: g.value(STATE) == 4, 'mode menu', 240, lambda: g.press(START))
    g.q(cmd='turbo', enabled=0); time.sleep(1)
    g.write(LINE, bytes([menu_line(g, PRACTICE)]))
    g.wait(lambda: g.value(STATE) == 9 and g.value(GRID) == 21, 'selector', 90,
           lambda: (g.press(CROSS), time.sleep(.4)))
    time.sleep(1.5)
    for k in range(48):
        if g.value(CURSOR_CHAR) == IDS[fighter]: break
        before = g.value(CURSOR_CHAR)
        g.press(RIGHT)
        if k % 12 == 11 or g.value(CURSOR_CHAR) == before: g.press(DOWN)
    assert g.value(CURSOR_CHAR) == IDS[fighter], ('cursor', g.value(CURSOR_CHAR))
    g.wait(lambda: 'P1 opens the MOVESET card' in g.log(), 'no MOVESET card', 10, lambda: (g.press(SQUARE), time.sleep(1)))
    g.press(RIGHT)
    g.wait(lambda: 'P1 highlights TTT1 moves' in g.log(), 'no TTT1 line', 5)
    g.press(CROSS)
    g.wait(lambda: 'P1 takes' in g.log(), 'card not taken', 5)
    time.sleep(1.5)
    # Player 1's pad picks the dummy (its card on T3); once taken, the dummy's
    # character is written on every pass until the fight (the loading
    # screen, state 11, is too brief to catch between two presses).
    end, last, written = time.monotonic() + 60, 0, False
    while time.monotonic() < end:
        st = g.value(STATE)
        if st == 8: break
        taken = 'P2 takes' in g.log()
        if taken or st in (10, 11):
            g.write(VICTIM, struct.pack('<H', IDS[victim])); g.write(0x800add9a, b'\0\0'); written = True
        elif st == 9 and time.monotonic() - last > 1:
            g.press(CROSS if 'P2 opens the MOVESET card' in g.log() else SQUARE)
            last = time.monotonic()
        time.sleep(.01)
    assert written, 'the dummy was never written'
    # MODE SELECT, then 1P FREESTYLE: Cross until player 1 walks towards the
    # dummy. Only a step that brings them closer counts: a spare Cross that
    # lands on RESET also moves player 1 (back to the start, farther).
    g.wait(lambda: g.value(STATE) == 8 and g.value(0x800ae224, 2) >= 6, 'fight', 120)
    for _ in range(10):
        time.sleep(1.5); g.press(CROSS); time.sleep(1.5)
        before = distance(g)
        g.q(cmd='set_input', buttons=f'{RIGHT if x(g, 0) < x(g, 1) else LEFT:04x}'); g.frames(20)
        walking = g.value(ACTOR + 0xa0, 2) != 3
        g.q(cmd='clear_input')
        if walking and distance(g) < before - 30: break
    else: raise AssertionError('player 1 never walked')
    time.sleep(1)
    g.write(DUMMY, bytes([8]))


def mirror(pad):
    r, l = pad >> 5 & 1, pad >> 7 & 1
    return pad & ~0xa0 | l << 5 | r << 7


def distance(g):
    z = [struct.unpack('<i', g.read(ACTOR + p * STRIDE + 0x910, 4))[0] for p in (0, 1)]
    return ((x(g, 0) - x(g, 1)) ** 2 + (z[0] - z[1]) ** 2) ** .5


def approach(g, reach):
    on_right = x(g, 0) > x(g, 1)
    g.q(cmd='set_input', buttons=f'{mirror(RIGHT) if on_right else RIGHT:04x}')
    end = time.monotonic() + 6
    while time.monotonic() < end and distance(g) > reach: time.sleep(.01)
    g.q(cmd='clear_input'); g.frames(40)
    print(f'distance {distance(g):.0f}', flush=True)
    g.q(cmd='savestate', op='save', slot=1); time.sleep(.5)
    return on_right


def attempt(g, route, plan, length=130):
    """Returns the timeline [(frame, p1 move, p2 move, p2 frame, damage)] and
    the damage of the first hit."""
    g.q(cmd='savestate', op='load', slot=1); time.sleep(.3)
    g.q(cmd='set_input', buttons='ffff', port=2)
    total0 = g.value(TOTAL, 2)
    g.q(cmd='input_route_clear')
    for n, b in route: g.q(cmd='input_route_append', frames=n, buttons=b)
    g.q(cmd='input_route_start')
    start, k, seen = g.frame(), 0, []
    while g.frame() - start < length:
        f = g.frame() - start
        while k < len(plan) and f >= plan[k][0]:
            g.q(cmd='set_input', buttons=f'{plan[k][1]:04x}', port=2); k += 1
        v = g.read(ACTOR + 0x58, STRIDE + 0x4a)
        row = (struct.unpack_from('<H', v, 0x48)[0], struct.unpack_from('<H', v, STRIDE + 0x48)[0],
               g.value(TOTAL, 2) - total0)
        if not seen or seen[-1][1:4] != row:
            seen.append((f,) + row + (struct.unpack_from('<H', v, STRIDE)[0],))
        time.sleep(.002)
    g.q(cmd='set_input', buttons='ffff', port=2)
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='build-opt-dbg')
    ap.add_argument('--exe')
    ap.add_argument('--string', default='all', choices=['all'] + list(STRINGS))
    ap.add_argument('--victim', default='xiaoyu', choices=list(IDS))
    ap.add_argument('--range', type=int, default=1050)
    a = ap.parse_args()
    failed = unmeasured = False
    for name in STRINGS if a.string == 'all' else [a.string]:
        fighter, route, plans = STRINGS[name]
        g = Game((ROOT / a.build).resolve(), f'b73-{name}', exe=a.exe)
        try:
            to_practice(g, fighter, a.victim)
            if approach(g, a.range):
                route = [(n, mirror(b)) for n, b in route]
                plans = {k: (hits, [(f, mirror(b)) for f, b in v]) for k, (hits, v) in plans.items()}
            for plan, (expected, steps) in plans.items():
                # A pad written by TCP lands a frame or two apart: the first
                # hit can miss a fighter still walking in. Then again.
                for _ in range(4):
                    seen = attempt(g, route, steps)
                    damage = [d for _, _, _, d, _ in seen]
                    hits = sum(1 for before, now in zip([0] + damage, damage) if now > before)
                    if hits or expected == 0: break
                ok = hits >= 2 if expected is None else hits == expected
                print(f'{name} {plan}: {hits} hit(s), damage {damage[-1]}, TTT1 '
                      f'{"at least 2" if expected is None else expected} -> {"ok" if ok else "FAIL"}', flush=True)
                print('   ', ' '.join(f'{f}:{m1:x}/{m2:x}@{f2}[{d}]' for f, m1, m2, d, f2 in seen), flush=True)
                if expected is None and not ok: unmeasured = True
                elif not ok: failed = True
        finally:
            g.stop()
    sys.exit(1 if failed else 2 if unmeasured else 0)


if __name__ == '__main__': main()
