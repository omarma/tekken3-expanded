#!/usr/bin/env python3
"""P. Jack's Megaton Punishment and its victim's inputs (B42, GH#85; B68), without a player.

    python3 tools/test_b42_megaton.py [--build build-opt-dbg] [--victim 9|kazuya] [--ttt1] [--tries 4] [--visible]

Cold start (no save), Arcade selector, player 2 joins (Start on pad 2) and takes
the victim on its T3 moves (Jin by default, as in TTT1 under MAME), player 1
takes P. Jack on the Tag page. Player 1 walks into contact once (savestate 1),
then each try reloads it and plays 2+4, then d/b, d, d/f+2; in turn the
victim does nothing, mashes 1+2 at the end of the lift (one frame down, one
up, timed on the game's frame counter), holds back or holds forward from the
grab on (B68). TTT1 (MAME tektagt, same inputs): at
the last hit the victim leaves the lift (80083380) for its dash for one
frame, its own list then sends it on running or, 1+2 mashed, into its own
1+2 (looked ahead at the end of the clip), so the hit launches it from the
front (8007a960, 49 damage) or as a counter (8007aa30, 58); it falls and lies
on the ground (mashing: it gets up, then attacks). Holding any direction it
leaves the lift for 0x3D (800376d8, no guard) instead, and the hit launches
it from the front all the same (49 damage): back, down/back, down, up,
forward and down/forward measured.
Checks: after the last hit (P. Jack on 800833b4) the victim plays P. Jack's
front launch with no input or a direction held, his counter launch with 1+2 mashed (records of
his pack): the bugs where it ran on, on its feet (its own dash and run,
engine aliases 0x1B / 0x1D, where mashed 1+2 started its running moves),
was launched from behind (8007a9fc), and was never countered. One frame of
its own run or 1+2 before the launch is TTT1's (80038064, its alias 0x43).
Back held, it guarded the hit (P. Jack's guard reaction 0x80070cf8, then
its own steps: left standing, turning); forward held, it was launched from
behind (B68).
Build: pad 2 needs the debug server's port 2 (PSX_DEBUG_TOOLS=ON).
"""
import argparse, os, shutil, socket, struct, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'psxrecomp/tools'))
import debug_client

WORK = ROOT / 'workspace/b42-live'
STATE, PHASE, CURSOR_CHAR, CELL, GRID = 0x800ae204, 0x800ae224, 0x80118668, 0x80118650, 0x80118648
ACTOR, STRIDE = 0x800a9228, 0x188c
START, CROSS, SQUARE, R2, RIGHT, LEFT, DOWN, UP = 0xfff7, 0xbfff, 0x7fff, 0xfdff, 0xffdf, 0xff7f, 0xffbf, 0xffef
GUEST_ID, PACK = 23, 8192
GRAB, LIFT, HIT = 0x80083318, 0x80083380, 0x800833b4           # TTT1 records of the throw
LAUNCHES = (0x8007a960, 0x8007a994, 0x8007a9c8, 0x8007a9fc, 0x8007aa30)
FRONT, COUNTER = 0x8007a960, 0x8007aa30              # TTT1 with no input / 1+2 mashed


def pad(*bits):
    m = 0xffff
    for b in bits: m &= ~(1 << b)
    return m
B_R, B_D, B_L, B_TR, B_CI, B_SQ = 5, 6, 7, 12, 13, 15
MODES = ('none', 'mash', 'back', 'forward')
HOLD = {'back': B_R, 'forward': B_L}                 # the victim, player 2, faces left


class Game:
    def __init__(self, build, tag, visible=False):
        run = WORK / f'run-{os.getpid()}-{tag}'
        shutil.rmtree(run, ignore_errors=True); run.mkdir(parents=True)
        exe = next(p for p in (build / 'Tekken_3_Expanded.exe', build / 'Tekken_3_Expanded') if p.exists())
        shutil.copy2(exe, run / exe.name)
        for name in ('bios', 'mods'):       # links, not copies: the disk is shared
            if os.name == 'nt':
                subprocess.run(['cmd', '/c', 'mklink', '/J', str(run / name), str(build / name)], check=True, capture_output=True)
            else: (run / name).symlink_to(build / name)
        (run / 'settings.toml').write_text('[video]\nsupersampling=1\nantialiasing=false\n'
                                           '[controller]\np1_device="keyboard"\np2_device="none"\n')
        cards = run / 'cards'; cards.mkdir()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); self.port = listener.getsockname()[1]
        self.log_path = WORK / f'{tag}.log'
        env = {k: v for k, v in os.environ.items() if not k.startswith('TEKKEN3_')}
        env['SDL_AUDIO_DRIVER'] = 'dummy'
        args = [str(run / exe.name), '--game', str(ROOT / 'game.toml'), '--disc', str(ROOT / 'disc/Tekken 3 (USA).cue'),
                '--no-launcher', '--renderer', 'opengl' if visible else 'software', '--debug-port', str(self.port),
                '--memcard-dir', str(cards)] + ([] if visible else ['--headless'])
        self.out = self.log_path.open('w')
        self.process = subprocess.Popen(args, cwd=ROOT, stdout=self.out, stderr=self.out, env=env)
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
        for _ in range(100):
            result = debug_client.query('127.0.0.1', self.port, r)
            if result.get('err') != 'emu busy or frozen': break
            time.sleep(.2)
        if result.get('ok') is False: raise RuntimeError((r, result))
        return result

    def read(self, a, n=4): return bytes.fromhex(self.q(cmd='read_ram', addr=f'{a:08x}', len=n)['hex'])
    def value(self, a, n=4): return int.from_bytes(self.read(a, n), 'little')
    def press(self, b, port=1): self.q(cmd='press', buttons=b, frames=4, port=port); time.sleep(.25)
    def p2(self, b): self.q(cmd='set_input', buttons=f'{b:04x}', port=2)
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


def route(g, steps):
    g.q(cmd='input_route_clear')
    for n, b in steps: g.q(cmd='input_route_append', frames=n, buttons=b)
    g.q(cmd='input_route_start')


def tag_place(k): return divmod(k, 8) if k < 16 else (k - 16, 8)


def to_fight(g, guest_index, victim, ttt1=False, victim_guest=None):
    """Arcade selector: player 2 joins and takes the victim (a native on its
    T3 or TTT1 moves, or a guest on its own Tag page), player 1 takes
    P. Jack on the Tag page."""
    g.q(cmd='turbo', enabled=1)
    g.wait(lambda: g.value(STATE) == 4, 'mode menu not reached', 240, lambda: g.press(START))
    g.q(cmd='turbo', enabled=0)
    time.sleep(1)
    g.wait(lambda: g.value(STATE) == 9 and g.value(GRID) == 21, 'selector not reached', 90,
           lambda: (g.press(CROSS), time.sleep(.4)))
    time.sleep(1.5)
    g.press(START, port=2); time.sleep(2)
    if victim_guest is not None:
        g.press(R2, port=2); time.sleep(2.5)
        victim = GUEST_ID + victim_guest
    for k in range(48):
        c = g.value(CURSOR_CHAR + 0x7c)
        if c == victim: break
        g.press(RIGHT, port=2)
        if k % 12 == 11 or g.value(CURSOR_CHAR + 0x7c) == c: g.press(DOWN, port=2)
    else: raise AssertionError('player 2 did not reach the victim')
    g.press(SQUARE, port=2); time.sleep(1)
    if 'P2 opens the MOVESET card' in g.log():          # the card opens on TEKKEN 3
        if ttt1:
            g.press(RIGHT, port=2)
            g.wait(lambda: 'P2 highlights TTT1 moves' in g.log(), 'player 2 did not reach TTT1 moves', 5)
        g.press(CROSS, port=2)
        moves = 'TTT1' if ttt1 else 'T3'
        g.wait(lambda: f'P2 takes {moves} moves' in g.log(), f'player 2 did not take {moves} moves', 5)
    time.sleep(1)
    if g.value(CURSOR_CHAR) < GUEST_ID:                 # the Tag page is both players' (a guest victim)
        g.press(R2); time.sleep(2.5)
    row, col = tag_place(guest_index)
    for _ in range(14):
        r, c = tag_place(g.value(CELL))
        if (r, c) == (row, col): break
        g.press(DOWN if r < row else UP if r > row else RIGHT if c < col else LEFT)
    g.wait(lambda: g.value(CURSOR_CHAR) == GUEST_ID + guest_index, 'player 1 did not reach P. Jack', 10)
    g.press(SQUARE)
    g.wait(lambda: g.value(STATE) == 8 and g.value(PHASE, 2) >= 6, 'round did not start', 120)
    time.sleep(1)


def pack_ids(build):
    """Move numbers (+0xA0) of player 1's P. Jack records, by TTT1 address."""
    pack = (build / 'mods/ttt1/Pjack-TTT1-combat.jmv').read_bytes()
    n = struct.unpack_from('<8I', pack)[3]
    return {struct.unpack_from('<4I', pack, 32 + i * 16)[1]: PACK + i for i in range(n)}


def attempt(g, mode, ids):
    """One try from savestate 1: P. Jack's (player 1, a route) and the
    victim's move numbers, in order, and the damage. With mash, the victim
    presses 1+2 on the lift's even frames from 22: the engine takes it if a
    fresh press falls in the lift's last five frames, so the presses follow
    the victim's own frame (+0x58), read each time, not a predicted count."""
    g.q(cmd='savestate', op='load', slot=1); time.sleep(1.5)
    g.p2(0xffff)
    life = lambda: struct.unpack('<h', g.read(ACTOR + STRIDE + 0x3f6, 2))[0]
    before = life()
    route(g, [(2, pad(B_TR, B_CI)), (40, 0xffff), (2, pad(B_D, B_L)), (2, pad(B_D)), (2, pad(B_D, B_R, B_TR)), (200, 0xffff)])
    p1, p2, mashed, held = [], [], mode != 'mash', mode not in HOLD
    end = g.q(cmd='frame')['frame'] + 260
    while g.q(cmd='frame')['frame'] < end:
        both = g.read(ACTOR + 0x58, STRIDE + 0x4a)
        a, b = struct.unpack_from('<H', both, 0x48)[0], struct.unpack_from('<H', both, STRIDE + 0x48)[0]
        if b == ids[GRAB] and not held:                  # from the grab on
            held = True; g.p2(pad(HOLD[mode]))
        if b == ids[LIFT] and not mashed:
            mashed, down = True, False
            while True:                                  # the victim's own frame, read each time
                rec, vf = struct.unpack('<IH', g.read(ACTOR + STRIDE + 0x54, 6))
                if struct.unpack('<H', g.read(ACTOR + STRIDE + 0xa0, 2))[0] != ids[LIFT] or vf > 31: break
                want = vf >= 22 and vf % 2 == 0          # down on even frames, up on odd ones
                if want != down:
                    down = want; g.p2(pad(B_SQ, B_TR) if down else 0xffff)
            g.p2(0xffff)
        if not p1 or p1[-1] != a: p1.append(a)
        if not p2 or p2[-1] != b: p2.append(b)
    g.p2(0xffff)
    return p1, p2, before - life()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='build-opt-dbg')
    ap.add_argument('--victim', default='9', help='victim: a native (stock grid number) or a guest (its key, e.g. kazuya)')
    ap.add_argument('--ttt1', action='store_true', help='the native victim on its TTT1 moves')
    ap.add_argument('--tries', type=int, default=4, help='in turn: no input, 1+2 mashed (up to 3 goes), back held, forward held')
    ap.add_argument('--visible', action='store_true')
    a = ap.parse_args()
    build = (ROOT / a.build).resolve()
    catalogue = [l.split()[0] for l in (build / 'mods/ttt1/guests.txt').read_text().splitlines() if l.split()]
    ids = pack_ids(build)
    launches = {ids[x] for x in LAUNCHES}
    WORK.mkdir(parents=True, exist_ok=True)
    g = Game(build, 'megaton', a.visible)
    ok = True
    try:
        guest = None if a.victim.isdigit() else catalogue.index(a.victim)
        to_fight(g, catalogue.index('pjack'), int(a.victim) if guest is None else None, a.ttt1, guest)
        x = lambda p: struct.unpack('<i', g.read(ACTOR + p * STRIDE, 4))[0]
        for _ in range(6):              # one held forward press, into contact
            route(g, [(70, pad(B_R)), (30, 0xffff)])
            while g.q(cmd='input_route_status').get('active'): time.sleep(.03)
            if x(1) - x(0) < 1300: break
        g.q(cmd='savestate', op='save', slot=1); time.sleep(1.5)
        for t in range(a.tries):
            mode = MODES[t % len(MODES)]
            mash = mode == 'mash'
            # A press through the socket misses the window now and then (the
            # engine's own counter needs it there): up to three goes mashed.
            for go in range(3 if mash else 1):
                p1, p2, damage = attempt(g, mode, ids)
                name = f'try {t} ({"1+2 mashed, go " + str(go + 1) if mash else mode + " held" if mode in HOLD else "no input"})'
                if ids[HIT] not in p1 or ids[LIFT] not in p2:
                    print(f'{name}: the throw did not reach its last hit, P. Jack {[hex(m) for m in p1]}, victim {[hex(m) for m in p2]}')
                    good = False; continue
                after = p2[p2.index(ids[LIFT]) + 1:]
                launch = [m for m in after if m in launches]
                want = ids[COUNTER if mash else FRONT]
                good = bool(launch) and launch[0] == want
                print(f'{name}:', 'OK' if good else 'FAIL', f'{damage} damage, victim after the lift', [hex(m) for m in after[:8]],
                      f'(expected {want:#x} first)')
                if good: break
            ok &= good
    finally:
        g.stop()
    print('B42:', 'OK' if ok else 'FAIL')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
