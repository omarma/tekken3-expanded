#!/usr/bin/env python3
"""Arcade selector on a locked roster (B58, GH#7).

    python3 tools/test_locked_select.py [--build build-rel-lite]

Cold boot of a private copy of the build (debug server, full or lite,
headless, software renderer) on a NEW memory card (an empty folder) with
"Unlock All Characters" off: ten fighters, as on a first boot of the game.
Real pad input from the modes menu, in 16:9 then in 4:3. Checks:

  - Player 1's cursor arrives on a fighter (cell < count, character < 22)
    and its portrait loads (0x80118660). It used to start on cell 10, a
    hidden cell of ID 22 (no fighter): no frame, no portrait, no name. The
    overlay looks for the cell of the player's last fighter (22 on a new
    card) only below its "ID < 22" bound (0x8010D9B4, 0x8010DA30); widened
    for the guests, the bound let 22 through and the search found the first
    hidden cell. The stock bound sends 22 to the default cell.
  - The cursor moves: Right takes it to the next fighter.
  - Square on a native with TTT1 moves opens the MOVESET card (game log),
    Circle closes it.
  - R2 opens the Tag page: the grid holds the guests (cell 0 = ID 23) and
    the cursor is on one; L2 gives back the stock page with its own count
    (10). The stock page was saved only when it had 21 cells, so R2 did
    nothing on a locked roster.
  - The Tag page is drawn on two rows (cells at y 336 and 398), the stock
    page on one (y 369): the overlay lays its strip out for the stock grid
    (0x8011862C, layout 0x80118744); the guests' second row fell off the
    screen under a one-row strip.
  - The same with every fighter unlocked: cursor on cell 0, 21 cells (the
    roster the release is tested with).
  - QUICK SELECT (GAME OPTION, 0x80097F10) on: Arcade chooses on the VS
    grid (screen 10, mode 0). Square opens the MOVESET card there instead
    of starting the fight, Cross on the card takes the moves and the fight
    comes. The card knew only VS and Tekken Ball on that grid.

Exit status 0 = all checks passed. The menu has QUIT GAME on line 1:
the script never presses X there.
"""
import argparse, os, re, shutil, socket, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'psxrecomp/tools'))
import debug_client

START, CROSS, SQUARE, CIRCLE, DOWN, UP, RIGHT = 0xfff7, 0xbfff, 0x7fff, 0xdfff, 0xffbf, 0xffef, 0xffdf
R2, L2 = 0xfdff, 0xfeff
STATE, PHASE, MENU_LINE, ARCADE_LINE = 0x800ae204, 0x800ae224, 0x80097f40, 0
GRID, GRID_COUNT, COUNTDOWN = 0x801296c8, 0x80118648, 0x8011863c
CELL, CHARACTER, SHOWN = 0x80118650, 0x80118668, 0x80118660
ABSENT, GUEST_ID = 22, 23
# The strip's layouts (0x801102DC): two rows of cells, or one set lower.
TWO_ROWS, ONE_ROW = [336, 398], [369]
CELL_SIZES = (58 << 16 | 32, 68 << 16 | 32)
# GAME OPTION's QUICK SELECT; player 1's block on the VS grid (3 = choosing);
# player 1's fighter once chosen.
QUICK_SELECT, VS_BLOCK, VS_CHOOSING, FIGHTERS = 0x80097f10, 0x800b8d70, 3, 0x800add5c
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
enabled = {unlock}
'''


class Game:
    def __init__(self, build, wide, unlock):
        self.tmp = Path(tempfile.mkdtemp(prefix='locked-select-'))
        run = self.tmp / 'run'
        run.mkdir()
        shutil.copy2(build / EXE, run / EXE)
        shutil.copytree(build / 'bios', run / 'bios')
        (run / 'mods').mkdir()
        for entry in (build / 'mods').iterdir():
            if entry.name != 'state.toml': link(entry, run / 'mods' / entry.name)
        (run / 'mods/state.toml').write_text(STATE_TOML.format(wide=str(wide).lower(), unlock=str(unlock).lower()))
        (run / 'settings.toml').write_text('[video]\nsupersampling=1\nantialiasing=false\n'
                                           '[controller]\np1_device="keyboard"\np2_device="keyboard"\n')
        (self.tmp / 'saves').mkdir()                     # a new memory card
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0)); self.port = s.getsockname()[1]
        env = {k: v for k, v in os.environ.items() if not k.startswith('TEKKEN3_')}
        env['SDL_AUDIO_DRIVER'] = 'dummy'
        self.log = self.tmp / 'game.log'
        self.proc = subprocess.Popen(
            [str(run / EXE), '--game', str(ROOT / 'game.toml'), '--disc', str(ROOT / 'disc/Tekken 3 (USA).cue'),
             '--no-launcher', '--renderer', 'software', '--debug-port', str(self.port),
             '--memcard-dir', str(self.tmp / 'saves'), '--headless'],
            cwd=run, stdout=self.log.open('w'), stderr=subprocess.STDOUT, env=env)
        for _ in range(300):
            try: socket.create_connection(('127.0.0.1', self.port), .2).close(); break
            except OSError: time.sleep(.1)

    def q(self, **r): return debug_client.query('127.0.0.1', self.port, r)
    def value(self, a, n=4): return int.from_bytes(bytes.fromhex(self.q(cmd='read_ram', addr=f'{a:08x}', len=n)['hex']), 'little')
    def write(self, a, v, n=4): self.q(cmd='write_ram', addr=f'{a:08x}', bytes=v.to_bytes(n, 'little').hex())
    def press(self, b): self.q(cmd='press', buttons=b, frames=4, port=1); time.sleep(.5)
    def text(self): return self.log.read_text(errors='replace')

    def wait(self, predicate, what, seconds=60):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if predicate(): return
            time.sleep(.1)
        raise AssertionError(what)

    def to_mode(self, line):
        """Start until the modes menu answers Down, then the line, then X."""
        for _ in range(120):
            if self.value(STATE) == 4 and self.value(MENU_LINE) == 0:
                self.press(DOWN)
                if self.value(MENU_LINE) == 1:
                    while self.value(MENU_LINE) < line: self.press(DOWN)
                    while self.value(MENU_LINE) > line: self.press(UP)
                    self.press(CROSS)
                    return
            elif self.value(STATE) != 4:
                self.press(START)
            time.sleep(.5)
        raise AssertionError('the modes menu never came')

    def frame(self): return self.q(cmd='frame')['frame']

    def rows(self, since):
        """y of the cells' rows drawn since a frame (32 x 58 sprites, 32 x 68
        on one row). In 4:3
        the row is drawn only for two frames after a cursor move."""
        ys = set()
        for f in range(since, self.frame()):
            for e in self.q(cmd='gpu_frame_dump', frame=f, count=8192).get('entries', []):
                w = [int(x, 16) for x in e['w']]
                if int(e['op'], 16) == 0x65 and w[3] in CELL_SIZES and w[1] >> 16 >= 300: ys.add(w[1] >> 16)
        return sorted(ys)

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


def run(build, wide, unlock, check):
    name = ('16:9' if wide else '4:3') + (', all unlocked' if unlock else ', locked')
    g = Game(build, wide, unlock)
    try:
        g.to_mode(ARCADE_LINE)
        g.wait(lambda: g.value(STATE) == 9 and g.value(PHASE, 2) == 1, 'the Arcade selector', 30)
        time.sleep(1.5)
        g.write(COUNTDOWN, 50000)
        count, cell, who = g.value(GRID_COUNT), g.value(CELL), g.value(CHARACTER)
        check(count == (21 if unlock else 10), f'{name}: {count} cells')
        check(cell < count and who < ABSENT and g.value(SHOWN) == who,
              f'{name}: player 1 arrives on cell {cell}, fighter {who}, portrait {g.value(SHOWN)}')
        if unlock:
            check(cell == 0, f'{name}: on the first cell ({cell})')
            return
        g.press(RIGHT); time.sleep(.3)
        moved = g.value(CELL), g.value(CHARACTER)
        check(moved[0] == cell + 1 and moved[1] < ABSENT, f'{name}: Right moves to cell {moved[0]}, fighter {moved[1]}')
        g.press(SQUARE); time.sleep(.3)
        check('P1 opens the MOVESET card' in g.text(), f'{name}: Square opens the MOVESET card')
        g.press(CIRCLE); time.sleep(.3)
        g.press(R2); time.sleep(.5)
        tag = g.value(GRID_COUNT), g.value(GRID + 6, 2), g.value(CHARACTER)
        check(tag[1] == GUEST_ID and tag[2] >= GUEST_ID and 'Tag page' in g.text(),
              f'{name}: R2 opens the Tag page ({tag[0]} cells, cell 0 = ID {tag[1]}, cursor on {tag[2]})')
        f0 = g.frame(); g.press(DOWN); time.sleep(.3)
        rows = g.rows(f0)
        check(rows == TWO_ROWS and g.value(CHARACTER) >= GUEST_ID,
              f'{name}: the Tag page\'s two rows at y {rows} ({TWO_ROWS}), Down on guest {g.value(CHARACTER)}')
        g.press(L2); time.sleep(.5)
        back = g.value(GRID_COUNT), g.value(CHARACTER)
        check(back[0] == count and back[1] < ABSENT, f'{name}: L2 gives back {back[0]} cells, cursor on fighter {back[1]}')
        f0 = g.frame(); g.press(RIGHT); time.sleep(.3)
        rows = g.rows(f0)
        check(rows == ONE_ROW, f'{name}: the stock page\'s one row at y {rows} ({ONE_ROW})')
    finally:
        g.close()


def quick(build, check):
    """QUICK SELECT on: Arcade chooses on the VS grid (screen 10, mode 0)."""
    name = '16:9, locked, QUICK SELECT'
    g = Game(build, True, False)
    try:
        end = time.monotonic() + 60
        while g.value(STATE) != 4 and time.monotonic() < end: g.press(START)
        g.write(QUICK_SELECT, 1, 1)                    # on the modes menu, as from GAME OPTION
        g.to_mode(ARCADE_LINE)
        g.wait(lambda: g.value(STATE) == 10 and g.value(VS_BLOCK) == VS_CHOOSING, 'the quick grid', 30)
        time.sleep(1.5)
        g.press(SQUARE); time.sleep(.5)
        check('P1 opens the MOVESET card' in g.text() and g.value(STATE) == 10 and g.value(VS_BLOCK) == VS_CHOOSING,
              f'{name}: Square opens the MOVESET card (screen {g.value(STATE)}, block {g.value(VS_BLOCK)})')
        g.press(CROSS)
        g.wait(lambda: g.value(STATE) in (8, 11), 'the fight', 20)
        check('P1 takes' in g.text() and g.value(FIGHTERS, 2) < ABSENT,
              f'{name}: Cross on the card takes the moves, fighter {g.value(FIGHTERS, 2)}')
    finally:
        g.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='build-rel-lite')
    args = ap.parse_args()
    build = (ROOT / args.build).resolve()
    failures = []
    def check(ok, what):
        print(('ok   ' if ok else 'FAIL ') + what, flush=True)
        if not ok: failures.append(what)
    for wide, unlock in ((True, False), (False, False), (True, True)):
        run(build, wide, unlock, check)
    quick(build, check)
    print('OK' if not failures else f'{len(failures)} check(s) failed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
