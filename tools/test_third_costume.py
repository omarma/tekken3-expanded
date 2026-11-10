#!/usr/bin/env python3
"""Third costume at the selectors: triangle and Start, natives and guests (B39, GH#92, GH#90).

    python tools/test_third_costume.py [--modes arcade,vs,ball] [--build build-rel-lite]
                                       [--memcard-dir saves] [--measure] [--native-models DIR]

Boots a private copy of the build (software renderer, headless, x1) on a copy
of the memory card, the MOVESET card off (TEKKEN3_NATIVE_MOVES=0: B14 / B40),
opens the modes menu with Start on "Namco presents" (state 3) and takes
Arcade (state 9). There it saves a state; each probe reloads it, walks to a
fighter (R2 for the Tag page) and presses one button, then reads what the
game took: Arcade, the player block's costume (0x8011866C) once its state
(0x8011864C) leaves 1; VS and Tekken Ball (grid, state 10, entered by
writing the mode, phase 0 and state 10), the choice at +56 of the block
0x800B8D70 once the count (+44) is 1.

Reference: the natives on the same selector. Law (third costume unlocked,
bit 1 of 0x80097EF4) takes costume 3 on triangle and on Start; a native
whose bit is down takes the punch costume on triangle, nothing on Start. A
guest with a third TTT1 costume (Jun) must do what Law does; one without
(Wang, Unknown, Devil) what a locked native does: never costume 3, which
would be its first costume again (GH#90). Before the fix: Jun on triangle
took costume 1 (GH#92). --measure prints the table without asserting.

R1 (F32): nothing anywhere, as in the game, unless --native-models DIR (a TTT1
catalogue with the natives' models, TEKKEN3_TTT1_NATIVE_MODELS=all): a native
drawn by its TTT1 model with its third costume unlocked then takes its punch
costume on triangle (its RP model) and costume 3 on R1 and Start
(src/tekken3_native_moves.c); the others and the guests as before.
"""
import argparse, os, shutil, socket, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'psxrecomp/tools'))
import debug_client

SCREEN, PHASE, MODE, LINE, UNLOCKS = 0x800ae204, 0x800ae224, 0x800afa88, 0x80097f40, 0x80097ef4
P1_CELL, P1_STATE, P1_FIGHTER, P1_COSTUME = 0x80118650, 0x8011864c, 0x80118668, 0x8011866c
BLOCK = 0x800b8d70
START, START_SELECT, CROSS, SQUARE, TRIANGLE, R2, R1 = 0xfff7, 0xfff6, 0xbfff, 0x7fff, 0xefff, 0xfdff, 0xf7ff
UP, DOWN, LEFT, RIGHT = 0xffef, 0xffbf, 0xff7f, 0xffdf
BUTTONS = {'triangle': TRIANGLE, 'start': START, 'r1': R1}
NATIVE_MODELS = False                       # --native-models
MODES = {'vs': 1, 'ball': 7}
GUEST_ID, SAVESTATE, BALL_LINE = 23, 9, 6
EXE = 'Tekken_3_Expanded.exe' if os.name == 'nt' else 'Tekken_3_Expanded'
NATIVES = {'paul': 0, 'law': 1, 'xiaoyu': 7, 'eddy': 8}
GUESTS = ('jun', 'wang', 'unknown', 'devil')


class Game:
    def __init__(self, build, memcards, env):
        self.dir = Path(tempfile.mkdtemp(prefix='third-costume-'))
        run, saves = self.dir / 'run', self.dir / 'saves'
        run.mkdir(); (saves / 'openbios').mkdir(parents=True)
        shutil.copy2(build / EXE, run / EXE)
        for name in ('bios', 'mods', 'assets'):
            if (build / name).is_dir(): shutil.copytree(build / name, run / name)
        for card in ('card1.mcd', 'card2.mcd'):
            if (memcards / card).is_file(): shutil.copy2(memcards / card, saves / card)
        (run / 'settings.toml').write_text('[video]\nsupersampling=1\nantialiasing=false\n'
                                           '[controller]\np1_device="keyboard"\np2_device="none"\n')
        self.catalogue = [l.split()[0] for l in (build / 'mods/ttt1/guests.txt').read_text().splitlines() if l.split()]
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); self.port = listener.getsockname()[1]
        self.logfile = self.dir / 'game.log'
        environment = {k: v for k, v in os.environ.items() if not k.startswith('TEKKEN3_')}
        environment.update(env, SDL_AUDIO_DRIVER='dummy')
        with self.logfile.open('w') as out:
            self.process = subprocess.Popen(
                [str(run / EXE), '--game', str(ROOT / 'game.toml'), '--disc', str(ROOT / 'disc/Tekken 3 (USA).cue'),
                 '--no-launcher', '--renderer', 'software', '--headless', '--debug-port', str(self.port),
                 '--memcard-dir', str(saves)], cwd=ROOT, stdout=out, stderr=out, env=environment)
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

    def value(self, a, n=4):
        return int.from_bytes(bytes.fromhex(self.q(cmd='read_ram', addr=f'{a:08x}', len=n)['hex']), 'little')

    def write(self, a, v, n=4):
        for j in range(n): self.q(cmd='write_ram', addr=f'{a + j:08x}', val=f'{v >> (j * 8) & 255:02x}')

    def press(self, buttons): self.q(cmd='press', buttons=buttons, frames=4); time.sleep(.3)

    def wait(self, predicate, description, seconds=30):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if predicate(): return
            time.sleep(.05)
        raise AssertionError(description)

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=10)
            except subprocess.TimeoutExpired: self.process.kill()
        shutil.rmtree(self.dir, ignore_errors=True)


def to_arcade(g):
    # Start on "Namco presents" (state 3) opens the modes menu (state 4),
    # which gives up after two seconds: the line at once.
    def menu():
        if g.value(SCREEN) == 3: g.press(START)
        return g.value(SCREEN) == 4
    g.wait(menu, 'the modes menu never came', 180)
    time.sleep(.3)
    g.write(LINE, 0); g.press(CROSS)
    g.wait(lambda: g.value(SCREEN) == 9 and g.value(MODE) == 0 and g.value(PHASE, 2) <= 1 and g.value(P1_STATE) == 1,
           'the Arcade selector never came', 20)
    time.sleep(1.5)
    g.q(cmd='savestate', op='save', slot=SAVESTATE); time.sleep(1)


def fresh(g):
    g.q(cmd='savestate', op='load', slot=SAVESTATE); time.sleep(1)
    g.wait(lambda: g.value(SCREEN) == 9 and g.value(P1_STATE) == 1, 'the saved selector did not come back', 10)


def arcade_place(k):
    """(row, column) of guest k on the Arcade Tag page (tag_place, roster.c)."""
    return divmod(k, 8) if k < 16 else (k - 16, 8)


def arcade(g, who, button):
    fresh(g)
    if who in NATIVES:
        if g.value(P1_FIGHTER) >= GUEST_ID: g.press(R2); time.sleep(1.5)
        for _ in range(30):
            if g.value(P1_FIGHTER) == NATIVES[who]: break
            g.press(RIGHT)
        else: raise AssertionError(f'the Arcade cursor never reached {who}')
    else:
        k = g.catalogue.index(who)
        if g.value(P1_FIGHTER) < GUEST_ID: g.press(R2); time.sleep(1.5)
        for _ in range(20):
            r, c = arcade_place(g.value(P1_CELL)); row, col = arcade_place(k)
            if (r, c) == (row, col): break
            g.press(DOWN if r < row else UP if r > row else RIGHT if c < col else LEFT)
        g.wait(lambda: g.value(P1_FIGHTER) == GUEST_ID + k, f'the Arcade cursor never reached {who}', 5)
    time.sleep(.5)
    g.press(BUTTONS[button])
    got = arcade_taken(g, who)
    # Nothing taken: square must take this fighter, so the cursor was on it.
    if got is None: assert arcade_taken(g, who, SQUARE) == 1, (who, 'square did not take the punch costume')
    return got


def arcade_taken(g, who, press=None):
    if press: g.press(press)
    # Headless, the loading screen (11) and the fight (8) come within a
    # second; the costume the fight loads stays at 0x800ADD98 (player 1).
    try: g.wait(lambda: g.value(SCREEN) != 9, '', 2.5)
    except AssertionError: return None                    # nothing taken
    g.wait(lambda: g.value(SCREEN) in (8, 11), 'neither the loading screen nor the fight came', 20)
    fighter = g.value(0x800add5c, 2)
    assert fighter == (NATIVES[who] if who in NATIVES else GUEST_ID + g.catalogue.index(who)),         (who, 'another fighter was taken', fighter)
    return (g.value(0x800add98, 2) & 3) + 1


def grid(g, mode, who, button):
    fresh(g)
    if mode == 'ball':
        # Tekken Ball's grid only runs when entered from the modes menu:
        # Start + Select at the selector opens it.
        g.press(START_SELECT)
        g.wait(lambda: g.value(SCREEN) == 4, 'the modes menu never came', 15)
        time.sleep(.3)
        g.write(LINE, BALL_LINE); g.press(CROSS)
    else:
        g.write(MODE, MODES[mode]); g.write(PHASE, 0, 2); g.write(SCREEN, 10, 2)
    g.wait(lambda: g.value(SCREEN) == 10 and g.value(MODE) == MODES[mode] and g.value(BLOCK) == 3,
           f'the {mode} grid never came', 20)
    time.sleep(1.5)
    tag = who not in NATIVES
    target = g.catalogue.index(who) if tag else NATIVES[who]
    if tag: g.press(R2); time.sleep(1.5)
    for _ in range(30):
        x, y = g.value(BLOCK + 8), g.value(BLOCK + 12)
        if tag:
            # The game keeps seven columns (cell y * 7 + x = guest k), the
            # page is drawn and walked in rows of six.
            k = y * 7 + x; r, c = divmod(k, 6); row, col = divmod(target, 6)
            if k == target: break
            g.press(DOWN if r < row else UP if r > row else RIGHT if c < col else LEFT)
        else:
            cell = g.value(0x80022768 + (y * 7 + x) * 6 + 4, 1) >> 2
            if cell == target: break
            g.press(RIGHT if x < 6 else DOWN)
    else: raise AssertionError(f'the {mode} grid cursor never reached {who}')
    time.sleep(.5)
    fighter = GUEST_ID + target if tag else target
    got = grid_taken(g, who, fighter, BUTTONS[button])
    if got is None: assert grid_taken(g, who, fighter, SQUARE) == 1, (who, 'square did not take the punch costume')
    return got


def grid_taken(g, who, fighter, press):
    g.press(press)
    time.sleep(1.5)
    if g.value(BLOCK + 44) == 0: return None
    choice = g.value(BLOCK + 56)
    assert choice >> 2 == fighter, (who, 'another fighter was taken', choice >> 2)
    return (choice & 3) + 1


def expected(g, who, button, unlocks):
    """What a native does in the same place: costume 3 when it has it (its
    bit in 0x80097EF4), else punch on triangle and nothing on Start. R1:
    nothing, but for a native on its TTT1 model with its third costume, whose
    triangle is then its punch costume (F32)."""
    if who in NATIVES: third = bool(unlocks >> NATIVES[who] & 1)
    else: third = (Path(g.dir / 'run/mods/ttt1') / f'{who.capitalize()}-TTT1-arcade-P3.3dm').is_file()
    if NATIVE_MODELS and who in NATIVES and third: return 1 if button == 'triangle' else 3
    if button == 'r1': return None
    return 3 if third else (1 if button == 'triangle' else None)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--modes', default='arcade,vs,ball')
    ap.add_argument('--build', default=str(ROOT / 'build-rel-lite'))
    ap.add_argument('--memcard-dir', default=str(ROOT / 'saves'))
    ap.add_argument('--measure', action='store_true')
    ap.add_argument('--native-models', metavar='DIR', help='the natives on their TTT1 models, from this catalogue')
    a = ap.parse_args()
    # F32 E6: the natives' TTT1 models are the default with the import; without the option, off.
    env = {'TEKKEN3_NATIVE_MOVES': '0', 'TEKKEN3_TTT1_NATIVE_MODELS': '0'}
    if a.native_models:
        global NATIVE_MODELS
        NATIVE_MODELS = True
        env.update(TEKKEN3_TTT1_NATIVE_MODELS='all', TEKKEN3_TTT1_ASSETS=str(Path(a.native_models).resolve()))
    g = Game(Path(a.build), Path(a.memcard_dir), env)
    bad = []
    try:
        to_arcade(g)
        unlocks = g.value(UNLOCKS)
        print(f'0x80097EF4 = {unlocks:#x}', flush=True)
        natives = ['law'] + [n for n in NATIVES if n != 'law' and not unlocks >> NATIVES[n] & 1][:1]
        for mode in a.modes.split(','):
            for who in natives + list(GUESTS):
                for button in BUTTONS:
                    got = arcade(g, who, button) if mode == 'arcade' else grid(g, mode, who, button)
                    want = expected(g, who, button, unlocks)
                    flag = '' if got == want else '   <-- expected ' + str(want)
                    print(f'{mode:6} {who:8} {button:8} costume {got}{flag}', flush=True)
                    if got != want: bad.append((mode, who, button, got, want))
    finally:
        g.stop()
    if bad and not a.measure: raise SystemExit(f'FAIL: {bad}')
    print('OK' if not bad else f'{len(bad)} difference(s)')


if __name__ == '__main__':
    main()
