#!/usr/bin/env python3
"""Drive the game to a TTT ending without a player (Windows or macOS, no
save state): the cinematic engine's test bench (src/tekken3_cine.c).

    python tools/cine_drive.py OUT [--p1 kazuya] [--build build-rel-lite] [--visible]
                               [--env KEY=VALUE ...] [--dump ADDR:LEN ...] [--shots N]
                               [--until credits|cutscene]

Boots a private copy of the build (software renderer, x1, headless unless
--visible) on a copy of the memory card (saves/), Start on "Namco
presents", Cross on ARCADE, R2 (the Tag page), the guest's cell, Square.
The first fight counts as stage 9 (its index written once it loads), True
Ogre next; every round is won by emptying player 2's life in turbo, True
Ogre's too (turbo off once he is on). --dump ADDR:LEN reads RAM into
OUT/ADDR.bin once the first fight runs (the Arcade overlay). --shots N: a
screenshot every N frames of the cutscene (state 8, phase 17 or the cine
engine's own, TEKKEN3_CINE_* in --env). The game's log is OUT/game.log.
Build: rel-lite (debug server lite), TTT1 catalogue and TTT Cinematics
prepared beside it. Run through ressources/slot.py (--kind game).
"""
import argparse, json, os, shutil, socket, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'psxrecomp/tools'))
import debug_client

STATE, PHASE, P2_LIFE, P2_ID, LINE = 0x800AE204, 0x800AE224, 0x800AAEA8, 0x800AAACC, 0x80097F40
START, CROSS, SQUARE, R2 = 0xfff7, 0xbfff, 0x7fff, 0xfdff
UP, DOWN, LEFT, RIGHT = 0xffef, 0xffbf, 0xff7f, 0xffdf
EXE = 'Tekken_3_Expanded.exe' if os.name == 'nt' else 'Tekken_3_Expanded'


class Game:
    def __init__(self, build, out, env, visible, video=(), mods_state=None):
        self.dir = Path(tempfile.mkdtemp(prefix='cine-drive-'))
        run, saves = self.dir / 'run', self.dir / 'saves'
        run.mkdir(); (saves / 'openbios').mkdir(parents=True)
        shutil.copy2(build / EXE, run / EXE)
        for name in ('bios', 'mods', 'assets'):
            if (build / name).is_dir(): shutil.copytree(build / name, run / name)
        # mods_state: the copy's mods/state.toml (which mods and options are on) in place of the build's
        if mods_state is not None: (run / 'mods' / 'state.toml').write_text(mods_state)
        for card in ('card1.mcd', 'card2.mcd'):
            if (ROOT / 'saves' / card).is_file(): shutil.copy2(ROOT / 'saves' / card, saves / card)
        # video: KEY=VALUE lines of [video] in place of the light defaults (a film's supersampling)
        v = dict(supersampling='1', antialiasing='false'); v.update(kv.split('=', 1) for kv in video)
        (run / 'settings.toml').write_text('[video]\n' + ''.join(f'{k}={x}\n' for k, x in v.items()) +
                                           '[controller]\np1_device="keyboard"\np2_device="none"\n')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); self.port = listener.getsockname()[1]
        self.logfile = out / 'game.log'
        environment = {k: v for k, v in os.environ.items() if not k.startswith('TEKKEN3_')}
        environment.update(env)
        if not visible: environment['SDL_AUDIO_DRIVER'] = 'dummy'
        args = [str(run / EXE), '--game', str(ROOT / 'game.toml'), '--disc', str(ROOT / 'disc/Tekken 3 (USA).cue'),
                '--no-launcher', '--renderer', 'software', '--debug-port', str(self.port), '--memcard-dir', str(saves)]
        if not visible: args.append('--headless')
        with self.logfile.open('w') as log:
            self.process = subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=log, env=environment)
        self.catalogue = [l.split()[0] for l in (build / 'mods/ttt1/guests.txt').read_text().splitlines() if l.split()]
        end = time.monotonic() + 30
        while True:
            if self.process.poll() is not None: raise RuntimeError(f'the game exited at startup; see {self.logfile}')
            try:
                with socket.create_connection(('127.0.0.1', self.port), .2): break
            except OSError:
                if time.monotonic() > end: raise RuntimeError('the debug server did not start')
                time.sleep(.1)

    def q(self, **r):
        result = debug_client.query('127.0.0.1', self.port, r)
        if result.get('ok') is False: raise RuntimeError((r, result))
        return result

    def read(self, a, n): return bytes.fromhex(self.q(cmd='read_ram', addr=f'{a:08x}', len=n)['hex'])
    def value(self, a, n=4): return int.from_bytes(self.read(a, n), 'little')

    def write(self, a, v, n=4):
        for j in range(n): self.q(cmd='write_ram', addr=f'{a + j:08x}', val=f'{v >> (j * 8) & 255:02x}')

    def press(self, buttons): self.q(cmd='press', buttons=buttons, frames=4); time.sleep(.3)
    def frame(self): return self.q(cmd='frame')['frame']

    def wait(self, predicate, description, seconds=30):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if predicate(): return
            time.sleep(.05)
        raise AssertionError(description)

    def log(self): return self.logfile.read_text(errors='replace')

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=10)
            except subprocess.TimeoutExpired: self.process.kill()
        shutil.rmtree(self.dir, ignore_errors=True)


def tag_place(k):
    """(row, column) of guest k on the Tag page (src/tekken3_ttt1_roster.c)."""
    return divmod(k, 8) if k < 16 else (k - 16, 8)


def to_arcade_guest(g, guest):
    def menu():
        if g.value(STATE) == 3: g.press(START)
        return g.value(STATE) == 4
    g.q(cmd='turbo', enabled=1)
    g.wait(menu, 'the modes menu never came', 180)
    time.sleep(.3)
    g.write(LINE, 0); g.press(CROSS)
    g.wait(lambda: g.value(STATE) == 9 and g.value(0x80118648) == 21, 'the Arcade selector never came', 60)
    g.q(cmd='turbo', enabled=0)
    time.sleep(1.5)
    g.press(R2); time.sleep(2)
    row, col = tag_place(g.catalogue.index(guest))
    for _ in range(16):
        r, c = tag_place(g.value(0x80118650))
        if (r, c) == (row, col): break
        g.press(DOWN if r < row else UP if r > row else RIGHT if c < col else LEFT)
    g.press(SQUARE)


def test(g, a, rows):
    """TEKKEN3_CINE_TEST in the first fight: screenshots while it plays
    (phase 17), then the fight must go on (a round phase, frames advancing)."""
    g.wait(lambda: g.value(STATE) == 8 and g.value(PHASE, 2) == 8, 'no fight', 180)
    # The camera's mode (0x800A0418): 0 follows the fighters, 1 plays a
    # script (the cinematic's setup starts one); the fight must get its own back.
    def camera(): return g.value(0x800A0418, 1)
    mode_before = camera()
    f0, last, shot = g.frame(), None, -10 ** 9
    while 'over after' not in g.log():
        f = g.frame() - f0
        if f > 4000: raise AssertionError('the cinematic never ended')
        st, ph = g.value(STATE), g.value(PHASE, 2)
        if (st, ph) != last: print(f, 'state', st, 'phase', ph, flush=True); rows.append([f, st, ph]); last = (st, ph)
        if a.shots and ph == 17 and f - shot >= a.shots:
            g.q(cmd='screenshot_file', path=str(a.out / f'{f:05d}.png')); shot = f
        time.sleep(.02)
    time.sleep(3)
    f1 = g.frame(); mode1 = camera(); time.sleep(2); f2 = g.frame(); mode2 = camera()
    st, ph = g.value(STATE), g.value(PHASE, 2)
    g.q(cmd='screenshot_file', path=str(a.out / 'after.png'))
    print(f'camera mode {mode_before} before, {mode1} / {mode2} after')
    ok = st == 8 and 6 <= ph <= 9 and f2 > f1 + 30 and mode1 == mode2 == mode_before
    print(f'after the cinematic: state {st}, phase {ph}, {f2 - f1} frames in 2 s:', 'OK' if ok else 'ECHEC')
    if not ok: sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=Path)
    ap.add_argument('--p1', default='kazuya')
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--visible', action='store_true')
    ap.add_argument('--env', action='append', default=[])
    ap.add_argument('--dump', action='append', default=[])
    ap.add_argument('--shots', type=int, default=0)
    ap.add_argument('--until', default='credits', choices=('credits', 'cutscene', 'fight', 'test'),
                    help='test: TEKKEN3_CINE_TEST in --env plays in the first fight; checks the fight goes on after')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    env = dict(e.split('=', 1) for e in a.env)
    g = Game(ROOT / a.build, a.out, env, a.visible)
    rows, cine, dumped, shot = [], 0, False, -10**9
    try:
        to_arcade_guest(g, a.p1)
        if a.until == 'test':
            test(g, a, rows)
            return
        g.q(cmd='turbo', enabled=1)
        end = time.monotonic() + 1500
        while True:
            if time.monotonic() > end: raise RuntimeError(f'no True Ogre: state {g.value(STATE)}')
            st, ph, p2 = g.value(STATE), g.value(PHASE, 2), g.value(P2_ID, 2)
            if st == 11 and g.value(0x800AFAAC, 1) == 0: g.write(0x800AFAAC, 8, 1)       # stage 9, Ogre next
            if st == 8 and 6 <= ph < 9:
                if not dumped:
                    for d in a.dump:
                        addr, n = (int(x, 16) for x in d.split(':'))
                        (a.out / f'{addr:08X}.bin').write_bytes(g.read(addr, n))
                    dumped = True
                    if a.until == 'fight': return
                life = g.value(P2_LIFE)
                if life >> 16: g.write(P2_LIFE, life & 0xFFFF)
            if p2 == 20: break                                                 # True Ogre
            time.sleep(.01)
        f0, last = g.frame(), None
        while (f := g.frame() - f0) < 12000:
            st, ph = g.value(STATE), g.value(PHASE, 2)
            if st == 8 and 6 <= ph < 9 and g.value(P2_ID, 2) == 20:
                life = g.value(P2_LIFE)
                if life >> 16: g.write(P2_LIFE, life & 0xFFFF)
            if (st, ph) != last:
                print(f, 'state', st, 'phase', ph, flush=True); rows.append([f, st, ph]); last = (st, ph)
                if g.value(P2_ID, 2) != 20: g.q(cmd='turbo', enabled=0)       # the ending in real time
            if st == 8 and ph >= 16 and g.value(P2_ID, 2) != 20:
                cine += 1
                if a.until == 'cutscene' and cine == 1: print('cutscene', flush=True)
                if a.shots and f - shot >= a.shots:
                    try: g.q(cmd='screenshot_file', path=str(a.out / f'{f:05d}.png'))
                    except Exception: pass
                    shot = f
            if st == 19 and ph >= 3: break                                     # the credits
            time.sleep(.01)
    finally:
        (a.out / 'states.json').write_text(json.dumps(rows))
        g.stop()
    print(f'{a.p1}: cutscene {cine} polled frames, last states {rows[-3:]}')


if __name__ == '__main__':
    main()
