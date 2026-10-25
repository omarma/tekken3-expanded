#!/usr/bin/env python3
"""A CPU native answering a TTT1 string from the guest's own records (B64, GH#121, GH#125).

    python tools/test_b64_low_guard_lag.py [--build build-rel-lite] [--cpu 13] [--tries 12]
                                          [--mode arcade|survival|timeattack] [--cpu-moves original|ttt1]
                                          [--exe <before>] [--visible]

Cold start (a blank memory card), Options difficulty HARD, the mode's line
of the modes menu (its selector is Arcade's);
player 1 takes Jin with his MOVESET card on TEKKEN TAG TOURNAMENT, the CPU
(TEKKEN3_CPU_MOVESET=original: its Tekken 3 moves) is written while the fight
loads (0x800ADD5E, TIPS.md section 25). Player 1 walks into range with the
CPU held idle (+0xC5 = 0), savestate 1; each try reloads it, wakes the CPU
and plays u/f+4, 4, 4, 4 (Jin's pack: 156, 295, 299, 301; mid, low, low,
mid) as a frame route. Heihachi parries the first low now and then: Jin
goes to 0x2254 and the CPU to 0x220F, a record of Jin's pack whose end of
clip names another (0x2011). The CPU's candidate scan (0x80056764) looked
that move up in its native alias table, far past its end, and walked
whatever it found: one game frame in about a hundred vblanks.

The debug server's frame is the emulated vblank, which goes on while the
game loops: a stall is a stretch of vblanks in which neither fighter's move
or move frame (+0xA0, +0x58) changes. Exit status 1 when a try has one
longer than 30 vblanks, 2 when the CPU never stood on a record of Jin's pack
past its 16th frame (nothing measured).
"""
import argparse, os, shutil, socket, struct, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'psxrecomp/tools'))
import debug_client

WORK = ROOT / 'out/b64'
STATE, PHASE, CURSOR_CHAR, GRID = 0x800ae204, 0x800ae224, 0x80118668, 0x80118648
ACTOR, STRIDE, CLOCK = 0x800a9228, 0x188c, 0x800adbcc
START, CROSS, SQUARE, CIRCLE, RIGHT, DOWN, UP = 0xfff7, 0xbfff, 0x7fff, 0xdfff, 0xffdf, 0xffbf, 0xffef
JIN, HARD, PACK = 9, 2, 0x2000
MODES = {'arcade': 0, 'timeattack': 3, 'survival': 4}     # 0x800AFA88
STALL = 30                      # vblanks without a game frame


class Game:
    def __init__(self, build, tag, visible=False, exe=None, env=None):
        run = WORK / f'run-{os.getpid()}-{tag}'
        shutil.rmtree(run, ignore_errors=True); run.mkdir(parents=True)
        built = next(p for p in (build / 'Tekken_3_Expanded.exe', build / 'Tekken_3_Expanded') if p.exists())
        shutil.copy2(exe or built, run / built.name)
        for name in ('bios', 'mods'):       # links, not copies: the catalogue is large
            if os.name == 'nt':
                subprocess.run(['cmd', '/c', 'mklink', '/J', str(run / name), str(build / name)], check=True, capture_output=True)
            else: (run / name).symlink_to(build / name)
        (run / 'settings.toml').write_text('[video]\nsupersampling=1\nantialiasing=false\n'
                                           '[controller]\np1_device="keyboard"\np2_device="none"\n')
        cards = run / 'cards'; cards.mkdir()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); self.port = listener.getsockname()[1]
        self.log_path = WORK / f'{tag}.log'
        environ = {k: v for k, v in os.environ.items() if not k.startswith('TEKKEN3_')}
        environ['SDL_AUDIO_DRIVER'] = 'dummy'
        environ.update(env or {})
        args = [str(run / built.name), '--game', str(ROOT / 'game.toml'), '--disc', str(ROOT / 'disc/Tekken 3 (USA).cue'),
                '--no-launcher', '--renderer', 'opengl' if visible else 'software', '--debug-port', str(self.port),
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
    """The modes menu's line of a mode: 8-byte rows (label, then the mode
    in byte + 4) at the menu state + 16, their count at + 4 (TIPS.md section
    26); the state's address is the lui / ori pair at 0x800DB5D0 / 0x800DB5D8
    (QUIT GAME moves it)."""
    state = (g.value(0x800db5d0) & 0xffff) << 16 | g.value(0x800db5d8) & 0xffff
    count = g.value(state + 4)
    for line in range(min(count, 16)):
        if g.value(state + 16 + 8 * line + 4, 1) == mode: return line
    raise AssertionError(f'mode {mode} is not on the modes menu')


def to_fight(g, cpu, mode):
    g.q(cmd='turbo', enabled=1)
    g.wait(lambda: g.value(STATE) == 4, 'mode menu not reached', 240, lambda: g.press(START))
    g.q(cmd='turbo', enabled=0)
    time.sleep(1)
    g.write(0x80097f06, bytes([HARD]))              # Options difficulty, copied when the mode starts
    g.write(0x80097f40, bytes([menu_line(g, MODES[mode])]))
    g.wait(lambda: g.value(STATE) == 9 and g.value(GRID) == 21, 'selector not reached', 90,
           lambda: (g.press(CROSS), time.sleep(.4)))
    time.sleep(1.5)
    for k in range(48):                              # right along a row, then down a row
        if g.value(CURSOR_CHAR) == JIN: break
        before = g.value(CURSOR_CHAR)
        g.press(RIGHT)
        if k % 12 == 11 or g.value(CURSOR_CHAR) == before: g.press(DOWN)
    else: raise AssertionError('the grid cursor never reached Jin')
    g.press(SQUARE)
    g.wait(lambda: 'P1 opens the MOVESET card' in g.log(), 'no MOVESET card', 5)
    g.press(RIGHT)
    g.wait(lambda: 'P1 highlights TTT1 moves' in g.log(), 'right did not switch to TTT1 moves', 5)
    g.press(CROSS)
    g.wait(lambda: 'P1 takes TTT1 moves' in g.log(), 'X did not take the card', 5)
    g.wait(lambda: g.value(STATE) == 11, 'loading screen not reached', 30)
    assert g.value(0x800afa88) == MODES[mode], ('not the mode asked for', g.value(0x800afa88))
    g.write(0x800add5e, struct.pack('<H', cpu)); g.write(0x800add9a, b'\0\0')
    g.wait(lambda: g.value(STATE) == 8 and g.value(PHASE, 2) >= 6, 'round did not start', 120)
    g.wait(lambda: g.value(ACTOR + STRIDE + 0x16, 1) == cpu, 'player 2 is not the CPU fighter', 10)
    g.wait(lambda: 0x9f000000 <= g.value(0x800adc20) < 0x9f400000, 'player 1 is not on its TTT1 moves', 30)
    time.sleep(2.5)                                  # past the intros


def approach(g):
    """The CPU held idle (+0xC5 = 0) in its stance, player 1 holds forward
    once (taps would dash) into range; savestate 1. Returns the CPU's +0xC5."""
    awake = g.read(ACTOR + STRIDE + 0xc5, 1)
    g.write(ACTOR + STRIDE + 0xc5, b'\0')
    g.wait(lambda: g.value(ACTOR + STRIDE + 0xa0, 2) == 3, 'the idle CPU never stood in its stance', 20)
    def distance():
        x = [struct.unpack('<i', g.read(ACTOR + p * STRIDE + 0x908, 4))[0] for p in (0, 1)]
        z = [struct.unpack('<i', g.read(ACTOR + p * STRIDE + 0x910, 4))[0] for p in (0, 1)]
        return ((x[0] - x[1]) ** 2 + (z[0] - z[1]) ** 2) ** .5
    g.q(cmd='set_input', buttons=f'{RIGHT:04x}')
    end = time.monotonic() + 6
    while time.monotonic() < end and distance() > 1300: time.sleep(.01)
    g.q(cmd='clear_input')
    g.frames(10)
    g.q(cmd='savestate', op='save', slot=1); time.sleep(.5)
    return awake


def series(g, awake):
    """One try: the moves of both fighters with the vblank they started on,
    the longest stretch of vblanks without a game frame, whether the CPU stood
    on a record of Jin's pack past frame 16, and the wall time."""
    g.q(cmd='savestate', op='load', slot=1); time.sleep(.3)
    g.write(CLOCK, struct.pack('<H', 3600))
    g.write(ACTOR + STRIDE + 0xc5, awake)
    # u/f+4 = 156, its 4 within frames 1..25 -> 295, 4 within 1..46 -> 299,
    # 4 within 1..23 -> 301: a press of 4 every 10 frames falls in each window.
    route = [(3, UP & RIGHT), (3, UP & RIGHT & CIRCLE)]
    for _ in range(10): route += [(7, 0xffff), (3, CIRCLE)]
    g.q(cmd='input_route_clear')
    for n, b in route: g.q(cmd='input_route_append', frames=n, buttons=b)
    g.q(cmd='input_route_start')
    start, wall = g.frame(), time.monotonic()
    moves, last, changed, longest, foreign = [], None, start, 0, False
    while True:
        f = g.frame()
        v = g.read(ACTOR + 0x58, STRIDE + 0x4a)
        frame1, move1 = struct.unpack_from('<H', v, 0)[0], struct.unpack_from('<H', v, 0x48)[0]
        frame2, move2 = struct.unpack_from('<H', v, STRIDE)[0], struct.unpack_from('<H', v, STRIDE + 0x48)[0]
        now = (move1, frame1, move2, frame2)
        if now != last: changed, last = f, now
        longest = max(longest, f - changed)
        if not moves or moves[-1][1:] != (move1, move2): moves.append((f - start, move1, move2))
        foreign |= PACK <= move2 < PACK + 0x1000 and frame2 > 16
        if f - start > 240: break
        time.sleep(.001)
    return moves, longest, foreign, time.monotonic() - wall


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--cpu', type=int, default=13, help='stock ID of the CPU fighter (Heihachi = 13)')
    ap.add_argument('--tries', type=int, default=12)
    ap.add_argument('--mode', choices=tuple(MODES), default='arcade')
    ap.add_argument('--cpu-moves', default='original', help='TEKKEN3_CPU_MOVESET: original (T3) or ttt1')
    ap.add_argument('--exe', help="another executable for the build's data (the build before a change)")
    ap.add_argument('--visible', action='store_true')
    a = ap.parse_args()
    build = (ROOT / a.build).resolve()
    WORK.mkdir(parents=True, exist_ok=True)
    g = Game(build, 'b64', a.visible, a.exe, {'TEKKEN3_CPU_MOVESET': a.cpu_moves})
    stalls = measured = 0
    try:
        to_fight(g, a.cpu, a.mode)
        awake = approach(g)
        for t in range(a.tries):
            moves, longest, foreign, wall = series(g, awake)
            measured += foreign
            stalls += longest > STALL
            print(f'try {t + 1}: longest stretch without a game frame {longest} vblanks, {wall:.1f} s'
                  f'{", CPU on a record of the pack" if foreign else ""}', flush=True)
            print('   moves', ' '.join(f'{f}:{m1:x}/{m2:x}' for f, m1, m2 in moves), flush=True)
            if longest > STALL:
                print('   stalled at', g.q(cmd='get_registers').get('pc'), flush=True)
    finally:
        g.stop()
    print(f'{stalls} stalled tries, {measured} with the CPU on a record of the pack')
    if stalls: print('FAIL'); sys.exit(1)
    if not measured: print('nothing measured'); sys.exit(2)
    print('OK')


if __name__ == '__main__': main()
