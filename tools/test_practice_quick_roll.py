#!/usr/bin/env python3
"""The Practice menu's QUICK ROLL triangles with a guest as player 1 (B89).

    python tools/test_practice_quick_roll.py [--build build-rel-lite]
        [--guests kazuya,devil] [--attract] [--renderer opengl]
        [--video "supersampling=4;antialiasing=true"] [--shots DIR]

Build: rel-lite or debug (the debug server's screenshot and gpu_frame_dump).
Cold start (a blank memory card, every line of the modes menu open),
Practice, software renderer x1 without a window by default. Player 1 takes
Paul (the reference: Tekken 3's own textures) or a guest on the Tag page,
the dummy is Jin, 1P FREESTYLE, Start: the pause menu. With the cursor on
CANCEL, then on TRAINING DUMMY (0x800B8BD8), the dummy is set to each of its
nine actions (0x800B8BDD, 0 STAND .. 8 CONTROLLER) and the menu's panel is
captured (screen (64..304, 40..355) in 4:3 x1, opaque: nothing of the fight
shows through it). --attract: each guest's Practice comes after an attract
demo fight with a guest as player 1 (the title left alone).

QUICK ROLL (6 and 7) ends with a down or up triangle, a sprite of the sheet
the game keeps in player 1's texture band (page (384, 0), u 120..139,
v 224..239, CLUT (432, 504), or (416, 504) on the highlighted line), just
right of the COMMAND LIST icons. The mod moved only u 0..119 of that sheet
away from the guest's costume, for CLUTs from x 768 (tekken3_ttt1_mod.c,
icon_tick), and kept the first sheet it saw: in the attract, before the
modes menu fills the triangles' part. The triangles showed the costume.

Checks, for each guest: every panel is the reference's, pixel for pixel,
and the triangles were drawn from that sheet (the sprite is found in the
frame's GPU commands). Exit status 0 = all checks passed. --shots keeps the
screenshots (reference and guests) in DIR.
"""
import argparse, json, os, shutil, socket, struct, subprocess, sys, tempfile, time, zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'psxrecomp/tools'))
import debug_client

STATE, PHASE, CURSOR_CHAR, CELL = 0x800ae204, 0x800ae224, 0x80118668, 0x80118650
MODE, LINE, PRACTICE, PRACTICE_LINE = 0x800afa88, 0x80097f40, 5, 8
DUMMY, ACTIONS, QUICK_ROLLS = 0x800b8bdd, 9, (6, 7)
START, CROSS, R2, RIGHT, LEFT, DOWN, UP = 0xfff7, 0xbfff, 0xfdff, 0xffdf, 0xff7f, 0xffbf, 0xffef
GUEST_ID, PAUL, JIN, FIGHTER = 23, 0, 9, 0x800a9240     # FIGHTER: player 1's fighter ID
PANEL = (64, 40, 305, 356)                       # the pause menu's panel, screen x0, y0, x1, y1
SHEET_PAGE, TRIANGLES_U, TRIANGLES_V = 6, (120, 139), (224, 239)
TRIANGLES_CLUTS = ((432, 504), (416, 504))      # the line's colour, then highlighted (the cursor on it)
CURSOR, CURSOR_LINES = 0x800b8bd8, {0: 'CANCEL', 2: 'TRAINING DUMMY'}      # the pause menu's cursor
EXE = 'Tekken_3_Expanded' + ('.exe' if os.name == 'nt' else '')


def png_rgb(path):
    """(width, height, rows of RGB bytes) of the debug server's 8-bit PNG."""
    data = Path(path).read_bytes()
    o, idat, width = 8, b'', 0
    while o < len(data):
        n, kind = struct.unpack('>I4s', data[o:o + 8])
        chunk = data[o + 8:o + 8 + n]
        if kind == b'IHDR':
            width, height, depth, colour = struct.unpack('>IIBB', chunk[:10])
            assert depth == 8 and colour == 2, 'not an 8-bit RGB PNG'
        elif kind == b'IDAT': idat += chunk
        o += 12 + n
    raw, stride, rows, prev = zlib.decompress(idat), 3 * width, [], bytearray(3 * width)
    for y in range(height):
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - 3] if i >= 3 else 0
            b, c = prev[i], prev[i - 3] if i >= 3 else 0
            if f == 1: line[i] = (line[i] + a) & 255
            elif f == 2: line[i] = (line[i] + b) & 255
            elif f == 3: line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c; pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(bytes(line)); prev = line
    return width, height, rows


def crop(path, box):
    x0, y0, x1, y1 = box
    return [row[3 * x0:3 * x1] for row in png_rgb(path)[2][y0:y1]]


class Game:
    def __init__(self, build, tag, renderer='software', video=''):
        self.tmp = Path(tempfile.mkdtemp(prefix=f'quick-roll-{tag}-'))
        run = self.tmp / 'run'
        run.mkdir()
        shutil.copy2(build / EXE, run / EXE)
        for name in ('bios', 'mods'): link(build / name, run / name)
        video = video.replace(';', '\n') if video else 'supersampling=1\nantialiasing=false'
        (run / 'settings.toml').write_text('[video]\n' + video + '\n'
                                           '[controller]\np1_device="keyboard"\np2_device="none"\n')
        (self.tmp / 'saves').mkdir()                     # a new memory card
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0)); self.port = s.getsockname()[1]
        env = {k: v for k, v in os.environ.items() if not k.startswith('TEKKEN3_')}
        env['SDL_AUDIO_DRIVER'] = 'dummy'
        env['TEKKEN3_NATIVE_MOVES'] = '0'               # Paul picked without the MOVESET card
        self.log = self.tmp / 'game.log'
        self.out = self.log.open('w')
        self.proc = subprocess.Popen(
            [str(run / EXE), '--game', str(ROOT / 'game.toml'), '--disc', str(ROOT / 'disc/Tekken 3 (USA).cue'),
             '--no-launcher', '--renderer', renderer, '--debug-port', str(self.port),
             '--memcard-dir', str(self.tmp / 'saves')] + (['--headless'] if renderer == 'software' else []),
            cwd=run, stdout=self.out, stderr=subprocess.STDOUT, env=env)
        self.run = run
        end = time.monotonic() + 60
        while True:
            if self.proc.poll() is not None: raise RuntimeError(f'the game exited, see {self.log}')
            try: socket.create_connection(('127.0.0.1', self.port), .2).close(); break
            except OSError:
                if time.monotonic() > end: raise RuntimeError('the debug server never answered')
                time.sleep(.2)

    def q(self, **r):
        for _ in range(100):
            res = debug_client.query('127.0.0.1', self.port, r)
            if res.get('err') != 'emu busy or frozen': return res
            time.sleep(.2)
        return res
    def read(self, a, n): return bytes.fromhex(self.q(cmd='read_ram', addr=f'{a:08x}', len=n)['hex'])
    def value(self, a, n=4): return int.from_bytes(self.read(a, n), 'little')
    def write(self, a, data): self.q(cmd='write_ram', addr=f'{a:08x}', bytes=data.hex())
    def press(self, b): self.q(cmd='press', buttons=b, frames=4, port=1); time.sleep(.3)
    def frame(self): return self.q(cmd='frame')['frame']
    def frames(self, n):
        end = self.frame() + n
        while self.frame() < end: time.sleep(.005)
    def wait(self, predicate, what, seconds=120):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if predicate(): return
            time.sleep(.1)
        raise AssertionError(what)
    def shot(self, path):
        self.q(cmd='screenshot', path=str(path))
        self.wait(lambda: Path(path).is_file(), f'no screenshot {path}', 10)

    def close(self):
        if self.proc.poll() is None: self.proc.kill()
        self.proc.wait(); self.out.close()
        for name in ('bios', 'mods'): unlink(self.run / name)     # links first: they point into the build
        shutil.rmtree(self.tmp, ignore_errors=True)


def link(source, target):
    if os.name == 'nt': subprocess.run(['cmd', '/c', 'mklink', '/J', str(target), str(source)], capture_output=True, check=True)
    else: os.symlink(source, target)


def unlink(path):
    if os.name == 'nt': subprocess.run(['cmd', '/c', 'rmdir', str(path)], capture_output=True)
    else: path.unlink(missing_ok=True)


def tag_place(k): return divmod(k, 8) if k < 16 else (k - 16, 8)


def seek(g, target, cursors=(CURSOR_CHAR, CURSOR_CHAR + 0x7c)):
    """The grid cursor that moves (player 1's, or the dummy's once player 1
    has picked) onto a Tekken 3 fighter: right along a row, down to the next
    one (test_b67_machine_gun_cannon)."""
    for k in range(48):
        before = [g.value(c) for c in cursors]
        if target in before: return
        g.press(RIGHT)
        after = [g.value(c) for c in cursors]
        if target in after: return
        if k % 12 == 11 or after == before:
            g.press(DOWN)
            if [g.value(c) for c in cursors] == after: g.press(UP)
    raise AssertionError(f'the grid cursor never reached fighter {target}')


def to_pause_menu(g, guest, catalogue, attract=False):
    def unlock():                                 # every fighter and every line of the modes menu (TIPS section 6)
        g.write(0x80097ef0, struct.pack('<I', 0x1fffff)); g.write(0x80097f1e, b'\1'); g.write(0x80097f26, b'\1\1')
    def menu():
        if g.value(STATE) == 3:
            unlock(); g.press(START)
        return g.value(STATE) == 4
    g.q(cmd='turbo', enabled=1)
    if attract:
        # An attract demo fight with a guest as player 1 first (the title's
        # loop draws its fighters), Start only once it is over: player 1's
        # first costume then lands while the triangles' part of the sheet is
        # still empty (the modes menu fills it).
        seen = []
        def demo_over():
            s = g.value(STATE)
            if s == 3: unlock()
            if s == 8 and not seen and g.value(PHASE, 2) >= 6 and g.value(FIGHTER, 2) >= GUEST_ID:
                seen.append(g.value(FIGHTER, 2))
            return bool(seen) and s != 8
        g.wait(demo_over, 'no attract demo fight with a guest as player 1', 1200)
        print(f'       attract demo fight with guest {seen[0]} as player 1', flush=True)
    g.wait(menu, 'the modes menu never came', 240)
    g.q(cmd='turbo', enabled=0)
    time.sleep(.5)
    g.write(LINE, struct.pack('<I', PRACTICE_LINE)); g.press(CROSS)
    g.wait(lambda: g.value(STATE) == 9 and g.value(MODE) == PRACTICE, 'the Practice selector never came', 30)
    time.sleep(1.5)
    if guest:
        g.press(R2); time.sleep(2.5)
        row, col = tag_place(catalogue.index(guest))
        for _ in range(14):
            r, c = tag_place(g.value(CELL))
            if (r, c) == (row, col): break
            g.press(DOWN if r < row else UP if r > row else RIGHT if c < col else LEFT)
        g.wait(lambda: g.value(CURSOR_CHAR) >= GUEST_ID, f'player 1 did not reach {guest}', 10)
        g.press(CROSS); time.sleep(1.5)
        if g.value(CURSOR_CHAR) >= GUEST_ID: g.press(R2); time.sleep(2.5)    # the dummy, on the Tekken 3 page
    else:
        seek(g, PAUL, (CURSOR_CHAR,))
        g.press(CROSS); time.sleep(1.5)
    seek(g, JIN)
    for _ in range(10):
        if g.value(STATE) == 8: break
        g.press(CROSS); time.sleep(.7)
    g.wait(lambda: g.value(STATE) == 8 and g.value(PHASE, 2) >= 8, 'the fight never started', 120)
    time.sleep(3)
    for _ in range(3): g.press(CROSS); g.frames(60)   # MODE SELECT -> 1P FREESTYLE
    g.press(START); g.frames(30)


def triangle_sprites(g, frame):
    """The frame's sprites read from the triangles' spot of the sheet."""
    found, page = [], None
    for e in g.q(cmd='gpu_frame_dump', frame=frame, count=16384).get('entries', []):
        op, w = int(e['op'], 16), [int(x, 16) for x in e['w']]
        if op == 0xe1: page = w[0]
        if 0x64 <= op <= 0x67 and page is not None and len(w) > 3 and (page & 31) == SHEET_PAGE and not (page >> 7) & 3:
            u, v, clut = w[2] & 255, w[2] >> 8 & 255, w[2] >> 16
            if TRIANGLES_U[0] <= u <= TRIANGLES_U[1] and TRIANGLES_V[0] <= v <= TRIANGLES_V[1] and \
               ((clut & 63) * 16, clut >> 6 & 511) in TRIANGLES_CLUTS: found.append((u, v, (clut & 63) * 16))
    return found


def panels(g, guest, catalogue, keep, attract=False):
    """The panel of each dummy action, the pause cursor on CANCEL then on
    TRAINING DUMMY (its line highlighted), and the triangles' sprites."""
    to_pause_menu(g, guest, catalogue, attract)
    shots, sprites = {}, {}
    for line in CURSOR_LINES:
        g.write(CURSOR, bytes([line]))
        for action in range(ACTIONS):
            g.write(DUMMY, bytes([action])); g.frames(10)
            path = keep / f'{guest or "reference"}-line{line}-action{action}.png'
            g.shot(path)
            shots[line, action] = crop(path, PANEL)
            if action in QUICK_ROLLS: sprites[line, action] = triangle_sprites(g, g.frame() - 1)
    return shots, sprites


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--guests', default='kazuya,devil')
    ap.add_argument('--shots', type=Path)
    ap.add_argument('--attract', action='store_true', help='let an attract demo fight play before each guest Practice')
    ap.add_argument('--renderer', choices=('software', 'opengl'), default='software')
    ap.add_argument('--video', default='', help='[video] settings instead of x1 without AA: "supersampling=4;antialiasing=true"')
    a = ap.parse_args()
    build = (ROOT / a.build).resolve()
    catalogue = [l.split()[0] for l in (build / 'mods/ttt1/guests.txt').read_text().splitlines() if l.split()]
    keep = a.shots.resolve() if a.shots else Path(tempfile.mkdtemp(prefix='quick-roll-shots-'))
    keep.mkdir(parents=True, exist_ok=True)
    failures = []
    def check(ok, what):
        print(('ok   ' if ok else 'FAIL ') + what, flush=True)
        if not ok: failures.append(what)
    try:
        g = Game(build, 'reference', a.renderer, a.video)
        try: reference, sprites = panels(g, None, catalogue, keep)
        finally: g.close()
        check(all(sprites.values()), f'reference (Paul): the triangles drawn from the sheet {sprites}')
        for guest in a.guests.split(','):
            g = Game(build, guest, a.renderer, a.video)
            try: shots, sprites = panels(g, guest, catalogue, keep, a.attract)
            finally: g.close()
            check(all(sprites.values()), f'{guest}: the triangles drawn from the sheet {sprites}')
            for line, action in sorted(reference):
                bad = sum(x != y for r0, r1 in zip(reference[line, action], shots[line, action])
                          for x, y in zip(zip(*[iter(r0)] * 3), zip(*[iter(r1)] * 3)))
                check(not bad, f'{guest}: cursor on {CURSOR_LINES[line]}, TRAINING DUMMY {action}, the panel is '
                               'the reference\'s' + (f' ({bad} pixels differ)' if bad else ''))
    finally:
        if not a.shots: shutil.rmtree(keep, ignore_errors=True)
    print('OK' if not failures else f'{len(failures)} check(s) failed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
