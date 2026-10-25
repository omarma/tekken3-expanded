#!/usr/bin/env python3
"""The selector's last frames keep Bryan's and Heihachi's icons (B84, GH#141).

    python3 tools/test_select_exit_icons.py [--build build-rel-lite] [--pick heihachi]

Cold boot of a private copy of the build (debug server, full or lite,
headless, software renderer, all fighters unlocked), in 16:9 then in 4:3.
Player 1 takes a guest on the Tag page and fights; once the COMMAND LIST's
icons sit in their fight spot, VRAM (960..994, 224..255), the round is lost
until the title, and Arcade's selector comes back. Player 1 then takes a
stock fighter on the stock page. Checks:

  - The icon sheet went up in the guest's fight (the case is armed).
  - From the pick to the loading screen, VRAM (960..994, 224..255) keeps
    the selector's icon sheet: that spot is the bottom of Bryan's (u 128)
    and Heihachi's (u 160) icons, v 198..255 of page (896, 0), 8bpp. The
    game passes through state 8, phase 1, between the selector and the
    loading screen while the selector still draws; the mod took it for the
    fight and put the command icons there (tekken3_ttt1_mod.c, icon_tick).
  - The selector did draw those two icons after the pick (the frames the
    check covers are the ones a player sees).

Natives are picked without the MOVESET card (TEKKEN3_NATIVE_MOVES=0).

Exit status 0 = all checks passed. --film DIR (with a build carrying the
local present patch, PSX_FILM_DIR) keeps every frame from the pick to the
loading screen, in a window; --pick guest takes a guest again instead.
"""
import argparse, os, shutil, socket, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'psxrecomp/tools'))
import debug_client

START, CROSS, RIGHT, DOWN, R2, L2 = 0xfff7, 0xbfff, 0xffdf, 0xffbf, 0xfdff, 0xfeff
STATE, PHASE, MENU_LINE = 0x800ae204, 0x800ae224, 0x80097f40
GRID_COUNT, COUNTDOWN, CHARACTER = 0x80118648, 0x8011863c, 0x80118668
P1_LIFE = 0x800a961c
FIGHT, LOADING, SELECTOR, MODES = 8, 11, 9, 4
STOCK_CELLS, GUEST_ID = 21, 23
PICKS = {'paul': 0, 'xiaoyu': 7, 'bryan': 12, 'heihachi': 13, 'guest': None}
SPOT = dict(x=960, y=224, w=35, h=32)            # the icons' fight spot (ICON_NX, ICON_NY)
EXE = 'Tekken_3_Expanded' + ('.exe' if os.name == 'nt' else '')

STATE_TOML = '''format_version = 2

[[package]]
id = "tekken3.enhancement.true-widescreen"

[[package]]
id = "tekken3.gameplay.all-characters"

[[feature]]
package_id = "tekken3.enhancement.true-widescreen"
id = "true-widescreen"
enabled = {wide}

[[feature]]
package_id = "tekken3.gameplay.all-characters"
id = "all-characters"
enabled = true
'''


class Game:
    def __init__(self, build, wide, film=None):
        self.tmp = Path(tempfile.mkdtemp(prefix='select-exit-'))
        run = self.tmp / 'run'
        run.mkdir()
        shutil.copy2(build / EXE, run / EXE)
        shutil.copytree(build / 'bios', run / 'bios')
        (run / 'mods').mkdir()
        for entry in (build / 'mods').iterdir():
            if entry.name != 'state.toml': link(entry, run / 'mods' / entry.name)
        (run / 'mods/state.toml').write_text(STATE_TOML.format(wide=str(wide).lower()))
        (run / 'settings.toml').write_text('[video]\nsupersampling=1\nantialiasing=false\n'
                                           '[controller]\np1_device="keyboard"\np2_device="none"\n')
        (self.tmp / 'saves').mkdir()                     # a new memory card
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0)); self.port = s.getsockname()[1]
        env = {k: v for k, v in os.environ.items() if not k.startswith('TEKKEN3_')}
        env['SDL_AUDIO_DRIVER'] = 'dummy'
        env['TEKKEN3_NATIVE_MOVES'] = '0'               # natives picked without the MOVESET card
        self.film = film
        if film: env['PSX_FILM_DIR'] = str(film)
        self.log = self.tmp / 'game.log'
        args = [str(run / EXE), '--game', str(ROOT / 'game.toml'), '--disc', str(ROOT / 'disc/Tekken 3 (USA).cue'),
                '--no-launcher', '--renderer', 'software', '--debug-port', str(self.port),
                '--memcard-dir', str(self.tmp / 'saves')]
        if not film: args.append('--headless')
        self.proc = subprocess.Popen(args, cwd=run, stdout=self.log.open('w'), stderr=subprocess.STDOUT, env=env)
        for _ in range(300):
            try: socket.create_connection(('127.0.0.1', self.port), .2).close(); break
            except OSError: time.sleep(.1)

    def q(self, **r): return debug_client.query('127.0.0.1', self.port, r)
    def read(self, a, n):
        """A loaded machine sometimes answers "emu busy" instead: ask again."""
        for _ in range(50):
            r = self.q(cmd='read_ram', addr=f'{a:08x}', len=n)
            if 'hex' in r: return bytes.fromhex(r['hex'])
            time.sleep(.1)
        raise RuntimeError(r)

    def value(self, a, n=4): return int.from_bytes(self.read(a, n), 'little')
    def write(self, a, v, n=4): self.q(cmd='write_ram', addr=f'{a:08x}', bytes=v.to_bytes(n, 'little').hex())
    def tap(self, b): self.q(cmd='press', buttons=b, frames=4, port=1)
    def press(self, b): self.tap(b); time.sleep(.5)
    def frame(self): return self.q(cmd='frame')['frame']
    def spot(self):
        for _ in range(50):
            r = self.q(cmd='vram_peek', **SPOT)
            if 'hex' in r: return r['hex']
            time.sleep(.1)
        raise RuntimeError(r)
    def text(self): return self.log.read_text(errors='replace')

    def wait(self, predicate, what, seconds=60):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if predicate(): return
            time.sleep(.1)
        raise AssertionError(what)

    def to_arcade(self):
        """Start until the modes menu, Arcade (line 0), then the selector."""
        self.q(cmd='turbo', enabled=1)
        end = time.monotonic() + 300
        while time.monotonic() < end:
            if self.value(STATE) == MODES and self.value(MENU_LINE) == 0:
                time.sleep(.5); self.press(CROSS)
                if self.value(STATE) != MODES: break
            elif self.value(STATE) != MODES:
                self.press(START)
            time.sleep(.3)
        else: raise AssertionError('the modes menu never came')
        self.wait(lambda: self.value(STATE) == SELECTOR and self.value(PHASE, 2) == 1, 'the Arcade selector', 60)
        self.q(cmd='turbo', enabled=0)
        time.sleep(1.5)
        self.write(COUNTDOWN, 50000)

    def thumbs_drawn(self, f0, f1):
        """Frames in which a sprite of page (896, 0), 8bpp, reads v 224..255
        at u 128..187 (Bryan's and Heihachi's icons)."""
        frames = []
        for f in range(f0, f1 + 1):
            page = None
            for e in self.q(cmd='gpu_frame_dump', frame=f, count=16384).get('entries', []):
                op, w = int(e['op'], 16), [int(x, 16) for x in e['w']]
                if op == 0xe1: page = w[0]
                if op in (0x64, 0x65) and page is not None and len(w) > 3 and (page & 15) == 14 and (page >> 7) & 3 == 1:
                    u, v, width, height = w[2] & 255, w[2] >> 8 & 255, w[3] & 0xffff, w[3] >> 16
                    if v + height > 224 and u < 188 and u + width > 128: frames.append(f); break
        return frames

    def close(self):
        if self.proc.poll() is None: self.proc.kill()
        self.proc.wait()
        # Links first, without following them: they point into the build.
        for entry in (self.tmp / 'run/mods').iterdir():
            if entry.is_symlink() or getattr(os.path, 'isjunction', lambda p: False)(entry): os.rmdir(entry) if entry.is_dir() else entry.unlink()
        shutil.rmtree(self.tmp, ignore_errors=True)


def link(source, target):
    if os.name == 'nt':
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(target), str(source)], capture_output=True, check=True)
    else:
        os.symlink(source, target)


def run(build, wide, pick, check, film=None):
    name = ('16:9' if wide else '4:3') + ', ' + pick
    g = Game(build, wide, film)
    try:
        g.to_arcade()
        sheet = g.spot()
        g.press(R2); time.sleep(1.5)
        check(g.value(CHARACTER) >= GUEST_ID, f'{name}: R2 puts player 1 on a guest ({g.value(CHARACTER)})')
        g.press(CROSS)
        g.wait(lambda: g.value(STATE) == FIGHT and g.value(PHASE, 2) >= 6, 'the guest\'s fight', 120)
        try: g.wait(lambda: g.spot() != sheet, '', 20); armed = True
        except AssertionError: armed = False
        check(armed, f'{name}: the command icons went up in the guest\'s fight')
        g.q(cmd='turbo', enabled=1)
        end = time.monotonic() + 300
        while g.value(STATE) == FIGHT and time.monotonic() < end:
            g.write(P1_LIFE, 0, 2); time.sleep(.3)
        g.to_arcade()
        if g.value(GRID_COUNT) != STOCK_CELLS: g.press(L2); time.sleep(1.5)
        target = PICKS[pick]
        if target is None:
            g.press(R2); time.sleep(1.5)
        else:
            for _ in range(2):                        # the stock page's two rows
                for _ in range(12):
                    if g.value(CHARACTER) == target: break
                    g.press(RIGHT); time.sleep(.2)
                if g.value(CHARACTER) == target: break
                g.press(DOWN); time.sleep(.2)
        who = g.value(CHARACTER)
        check(who == target if target is not None else who >= GUEST_ID, f'{name}: player 1 on {who}')
        sheet = g.spot()
        if film: (film / 'on').touch()
        f0 = g.frame()
        g.tap(CROSS)
        # Two requests a sample: the spot holds the command icons for about
        # ten frames, from state 8 phase 1 to player 1's upload.
        samples, wrong = 0, []
        end = time.monotonic() + 60
        while time.monotonic() < end:
            now = g.spot()
            screen = g.read(STATE, PHASE + 2 - STATE)
            state, phase = int.from_bytes(screen[:4], 'little'), int.from_bytes(screen[-2:], 'little')
            samples += 1
            if now != sheet: wrong.append((state, phase))
            if state == LOADING and phase >= 2: break
        f1 = g.frame()
        if film:
            time.sleep(1); (film / 'on').unlink()
        drawn = g.thumbs_drawn(f0, f1)
        if target is not None:
            check(drawn, f'{name}: the selector drew Bryan\'s and Heihachi\'s icons after the pick '
                         f'(frames {drawn[:1]}..{drawn[-1:]})')
        check(not wrong, f'{name}: the icons\' spot kept the selector\'s sheet over {samples} samples, '
                         f'frames {f0}..{f1}' + (f'; command icons in {len(wrong)} (state, phase) {wrong[:4]}' if wrong else ''))
    finally:
        g.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--pick', choices=sorted(PICKS), action='append')
    ap.add_argument('--aspect', choices=('16:9', '4:3'), action='append')
    ap.add_argument('--film', type=Path)
    args = ap.parse_args()
    build = (ROOT / args.build).resolve()
    failures = []
    def check(ok, what):
        print(('ok   ' if ok else 'FAIL ') + what, flush=True)
        if not ok: failures.append(what)
    for aspect in args.aspect or ('16:9', '4:3'):
        for pick in args.pick or (['heihachi'] if aspect == '16:9' else ['bryan']):
            film = None
            if args.film:
                film = args.film.resolve() / f"{aspect.replace(':', 'x')}-{pick}"
                film.mkdir(parents=True, exist_ok=True)
            run(build, aspect == '16:9', pick, check, film)
    print('OK' if not failures else f'{len(failures)} check(s) failed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
