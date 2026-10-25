#!/usr/bin/env python3
"""The guests' records follow memory card 1 (B63, GH#113).

    python tools/test_guest_records_card.py [--build build-rel-lite] [--mods <dir>] [--only ...]

Boots private copies of a debug-server build (rel-lite: headless, software
renderer, x1) on a memory card folder of its own, and plays real Arcade
matches lost by player 1 on a TTT1 guest (the CPU KOs it twice), which adds
to the guest's counters (src/tekken3_ttt1_records.c). The stock fighters'
counters live in the save data, in RAM, and reach card 1 only when the card
is written (CARD SAVE, or the AUTO SAVE option over an existing save); the
guests' must do the same, in <card>-ttt1-guest-records.txt beside the card.
Scenarios, each on the folder the previous one left:

  new-card: a new card (empty folder). After the match, no records file at
      all (the file used to be written after every game, and read back by
      the next boot whatever the card said). OPTION MODE > MEMORY CARD >
      CARD SAVE: the card and card1-ttt1-guest-records.txt are written, the
      guest with its games.
  no-autosave: reboot on that card (the guest's games read back, the log
      says so), AUTO SAVE off, a second match: the file does not change.
  autosave: reboot (the guest still has the card's games, not the second
      match's), AUTO SAVE on, a third match: the auto save writes the card
      and the file, the guest one game up.
  shared: card1-ttt1-guest-records.txt removed, the older shared file
      ttt1-guest-records.txt (and a newer ttt1-guest-records.txt.new, what a
      refused rename left on Windows) written by hand: the boot reads the
      newer one, CARD SAVE writes it into the card's own file.

Exit status 0 = all checks passed. The menus are driven by pad input; the
menu line of the modes menu (0x80097F40) is written, as the other benches do.
"""
import argparse, os, re, shutil, socket, struct, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'psxrecomp/tools'))
import debug_client

EXE = 'Tekken_3_Expanded.exe' if os.name == 'nt' else 'Tekken_3_Expanded'
SCREEN, PHASE, MODE, LINE = 0x800ae204, 0x800ae224, 0x800afa88, 0x80097f40
ACTOR, STRIDE, LIFE = 0x800a9228, 0x188c, 0x3f6
IDS, AUTO_SAVE = 0x800add5c, 0x80097f11
START, CROSS, SQUARE, CIRCLE = 0xfff7, 0xbfff, 0x7fff, 0xdfff
UP, DOWN, LEFT, RIGHT = 0xffef, 0xffbf, 0xff7f, 0xffdf
GUEST, HWOARANG = 23, 6          # the catalogue's first guest; the CPU
CARD_FILE, SHARED = 'card1-ttt1-guest-records.txt', 'ttt1-guest-records.txt'


class Game:
    def __init__(self, build, mods, saves, visible=False, env=None):
        self.dir = Path(tempfile.mkdtemp(prefix='guest-records-'))
        run = self.dir / 'run'
        (run / 'mods').mkdir(parents=True)
        shutil.copy2(build / EXE, run / EXE)
        for name in ('bios', 'assets'):
            if (build / name).is_dir(): shutil.copytree(build / name, run / name)
        # The build's mods, then --mods over them; folders linked, never written.
        for source in (build / 'mods', mods):
            if not source or not source.is_dir(): continue
            for entry in source.iterdir():
                target = run / 'mods' / entry.name
                if target.exists() or os.path.lexists(target): self.unlink(target)
                if entry.is_dir(): self.link(entry.resolve(), target)
                else: shutil.copy2(entry, target)
        (run / 'settings.toml').write_text('[video]\nsupersampling=1\nantialiasing=false\n'
                                           '[controller]\np1_device="keyboard"\n')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); self.port = listener.getsockname()[1]
        self.logfile = self.dir / 'game.log'
        environment = {k: v for k, v in os.environ.items() if not k.startswith('TEKKEN3_')}
        environment.update(SDL_AUDIO_DRIVER='dummy', TEKKEN3_NATIVE_MOVES='0', TEKKEN3_CPU_MOVESET='original')
        environment.update(env or {})
        # visible: a window (60 frames a second, frames presented: what a film needs), headless otherwise.
        with self.logfile.open('w') as out:
            self.process = subprocess.Popen(
                [str(run / EXE), '--game', str(ROOT / 'game.toml'), '--disc', str(ROOT / 'disc/Tekken 3 (USA).cue'),
                 '--no-launcher', '--renderer', 'software', *([] if visible else ['--headless']),
                 '--debug-port', str(self.port), '--memcard-dir', str(saves)], cwd=ROOT, stdout=out, stderr=out,
                env=environment)
        end = time.monotonic() + 30
        while True:
            if self.process.poll() is not None: raise RuntimeError(f'the game exited at startup; see {self.logfile}')
            try:
                with socket.create_connection(('127.0.0.1', self.port), .2): break
            except OSError:
                if time.monotonic() > end: raise RuntimeError('the debug server did not start')
                time.sleep(.1)

    @staticmethod
    def link(source, target):
        if os.name == 'nt': subprocess.run(['cmd', '/c', 'mklink', '/J', str(target), str(source)], check=True, capture_output=True)
        else: target.symlink_to(source)

    @staticmethod
    def unlink(target):
        # A junction or a link goes, never what it points to.
        if os.path.islink(target) or (hasattr(os.path, 'isjunction') and os.path.isjunction(target)):
            os.unlink(target) if os.path.islink(target) else os.rmdir(target)
        elif target.is_dir(): shutil.rmtree(target)
        else: target.unlink()

    def q(self, **r):
        for _ in range(400):
            try: result = debug_client.query('127.0.0.1', self.port, r)
            except (OSError, ValueError):
                if self.process.poll() is not None: raise RuntimeError(f'the game exited; see {self.logfile}')
                time.sleep(.1); continue
            if result.get('err') != 'emu busy or frozen': break
            time.sleep(.05)
        if result.get('ok') is False: raise RuntimeError((r, result))
        return result

    def read(self, a, n): return bytes.fromhex(self.q(cmd='read_ram', addr=f'{a:08x}', len=n)['hex'])
    def value(self, a, n=4): return int.from_bytes(self.read(a, n), 'little')

    def write(self, a, v, n=4):
        for j in range(n): self.q(cmd='write_ram', addr=f'{a + j:08x}', val=f'{v >> (j * 8) & 255:02x}')

    def press(self, buttons, port=1, settle=.4):
        self.q(cmd='press', buttons=buttons, frames=4, port=port); time.sleep(settle)
    def log(self): return self.logfile.read_text(errors='replace')
    def shot(self, path): self.q(cmd='screenshot_file', path=str(path))

    def wait(self, predicate, description, seconds=30, step=None):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if predicate(): return
            if step: step()
            time.sleep(.05)
        raise AssertionError(description)

    def stop(self, keep=None):
        if keep: keep.mkdir(parents=True, exist_ok=True); shutil.copy2(self.logfile, keep / f'{self.dir.name}.log')
        if self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=10)
            except subprocess.TimeoutExpired: self.process.kill()
        for entry in (self.dir / 'run/mods').iterdir():
            if os.path.islink(entry) or (hasattr(os.path, 'isjunction') and os.path.isjunction(entry)): self.unlink(entry)
        shutil.rmtree(self.dir, ignore_errors=True)


def booted(g):
    """The boot has read the card (or found none): the modes menu can come."""
    g.wait(lambda: g.value(SCREEN) >= 2, 'the game did not boot', 90)


def to_menu(g):
    # The modes menu (state 4) gives up after two seconds: Start on "Namco
    # presents" (state 3) until it comes.
    def menu():
        if g.value(SCREEN) == 3: g.press(START)
        return g.value(SCREEN) == 4
    g.wait(menu, 'the modes menu never came', 240)
    time.sleep(.3)


def load_fight(g, ids, seconds=60):
    """Through the loading screen (11) to the fight, writing the fighters
    (0x800ADD5C) from the moment the selector is left until the screen has
    read them."""
    end, seen = time.monotonic() + seconds, False
    while time.monotonic() < end:
        screen = g.value(SCREEN)
        if screen == 11: seen = True
        if seen and (screen == 8 or (screen == 11 and g.value(PHASE, 2) >= 6)): return
        if screen not in (8, 9):
            for p, cid in enumerate(ids): g.write(IDS + 2 * p, cid, 2)
        elif screen == 9: g.press(SQUARE, settle=0)
    raise AssertionError(f'no fight (screen {g.value(SCREEN)}, phase {g.value(PHASE, 2)})')


def round_ready(g): return g.value(SCREEN) == 8 and g.value(PHASE, 2) == 8


def lose_round(g, first):
    """Player 1's life at 1, the CPU's kept full, until the KO."""
    if not first: g.wait(lambda: not round_ready(g), 'the previous round did not end', 150)
    g.wait(lambda: round_ready(g) and 1 < g.value(ACTOR + LIFE, 2) < 1000, 'the round did not start', 150)
    time.sleep(.3)
    full = g.value(ACTOR + STRIDE + 0x3fa, 2) or 140
    g.write(ACTOR + LIFE, 1, 2)
    def over():
        life = g.value(ACTOR + LIFE, 2)
        if life == 0 or life > 1000: return True
        g.write(ACTOR + STRIDE + LIFE, full, 2)
        return False
    g.wait(over, 'the CPU never KOed player 1', 120)


def arcade_loss(g):
    """ARCADE, the guest against Hwoarang, two rounds lost; back to the
    modes menu without continuing (the continue screen runs out)."""
    to_menu(g)
    g.write(LINE, 0); g.press(CROSS)
    g.wait(lambda: g.value(SCREEN) == 9 and g.value(MODE) == 0, 'the Arcade selector never came', 30)
    time.sleep(1.5)
    load_fight(g, (GUEST, HWOARANG))
    lose_round(g, True)
    lose_round(g, False)
    g.wait(lambda: g.value(SCREEN) in (2, 3, 4), 'the match never ended', 240)


def card_save(g, shots=None):
    """OPTION MODE > MEMORY CARD (sixth line) > CARD SAVE (the first): Start
    asks "SAVE : PUSH START", Start again writes."""
    to_menu(g)
    g.write(LINE, 0); g.press(UP); g.press(CIRCLE)
    g.wait(lambda: g.value(SCREEN) == 5, 'OPTION MODE never came', 30)
    time.sleep(1)
    for _ in range(5): g.press(DOWN)
    if shots: g.shot(shots / 'option-mode.png')
    g.press(CIRCLE); time.sleep(1.5)
    if shots: g.shot(shots / 'memory-card.png')
    g.press(START); time.sleep(1)
    if shots: g.shot(shots / 'card-save.png')
    g.press(START); time.sleep(3)
    if shots: g.shot(shots / 'card-saved.png')


def records(saves, name=CARD_FILE):
    """{key: games} from a records file, None if there is none."""
    path = saves / name
    if not path.is_file(): return None
    out = {}
    for line in path.read_text().splitlines():
        f = line.split()
        if len(f) == 5 and not f[0].startswith('@'): out[f[0]] = int(f[1]) + int(f[3]) + int(f[4])
    return out


def main():
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', default=str(ROOT / 'build-rel-lite'))
    ap.add_argument('--mods', help='a mods folder over the build\'s (one with the TTT1 catalogue)')
    ap.add_argument('--only', default='new-card,no-autosave,autosave,shared')
    ap.add_argument('--logs', help='keep each game\'s log in that folder')
    a = ap.parse_args()
    build = Path(a.build).resolve()
    mods = Path(a.mods).resolve() if a.mods else None
    catalogue = (mods if mods and (mods / 'ttt1').is_dir() else build / 'mods') / 'ttt1/guests.txt'
    key = next(l for l in catalogue.read_text().splitlines() if l.split()).split()[0]
    only = a.only.split(',')
    saves = Path(tempfile.mkdtemp(prefix='guest-records-saves-'))
    failures = []

    def check(ok, what):
        print(('ok    ' if ok else 'FAIL  ') + what, flush=True)
        if not ok: failures.append(what)

    def run(body):
        g = Game(build, mods, saves)
        try:
            booted(g)
            body(g)
        except (AssertionError, RuntimeError) as error: check(False, f'{error}')
        finally: g.stop(Path(a.logs) if a.logs else None)

    def read_back(g):
        g.wait(lambda: re.search(r'TTT1 records: \d+ guest\(s\) read from', g.log()), 'the boot did not read the records', 60)
        return g.log()

    state = {}
    if 'new-card' in only:
        def new_card(g):
            arcade_loss(g)
            leftovers = sorted(p.name for p in saves.iterdir() if 'guest-records' in p.name)
            check(not leftovers, f'no records file before the card is saved ({leftovers or "none"})')
            card_save(g)
            g.wait(lambda: (saves / CARD_FILE).is_file(), f'CARD SAVE wrote no {CARD_FILE}', 30)
            check((saves / 'card1.mcd').is_file(), 'CARD SAVE wrote card1.mcd')
            games = (records(saves) or {}).get(key, 0)
            check(games >= 1, f'{CARD_FILE} holds {key} with its games ({games})')
            state['games'] = games
        run(new_card)
    if 'no-autosave' in only:
        def no_autosave(g):
            log = read_back(g)
            check(f'TTT1 records: 1 guest(s) read from' in log, 'the boot read the guest back from the card\'s file')
            before = (saves / CARD_FILE).read_bytes()
            to_menu(g); g.write(AUTO_SAVE, 0, 1)
            arcade_loss(g)
            time.sleep(3)
            check((saves / CARD_FILE).read_bytes() == before, 'AUTO SAVE off: the file did not change after a match')
        run(no_autosave)
    if 'autosave' in only:
        def autosave(g):
            read_back(g)
            games = (records(saves) or {}).get(key, 0)
            check(games == state.get('games', games), f'the file still holds the saved games ({games})')
            to_menu(g); g.write(AUTO_SAVE, 1, 1)
            arcade_loss(g)
            g.wait(lambda: (records(saves) or {}).get(key, 0) > games, 'AUTO SAVE on: the file never took the match', 60)
            after = records(saves)[key]
            check(after == games + 1, f'AUTO SAVE on: {key} one game up in the file ({games} -> {after})')
        run(autosave)
    if 'shared' in only:
        (saves / CARD_FILE).unlink(missing_ok=True)
        (saves / SHARED).write_text(f'{key} 3 0 3 0\n')
        os.utime(saves / SHARED, (time.time() - 60, time.time() - 60))
        (saves / (SHARED + '.new')).write_text(f'{key} 9 0 9 0\n')
        def shared(g):
            log = read_back(g)
            check(f'{SHARED}.new (shared file)' in log, 'the boot read the newer shared file (.new)')
            card_save(g)
            g.wait(lambda: (saves / CARD_FILE).is_file(), f'CARD SAVE wrote no {CARD_FILE}', 30)
            games = (records(saves) or {}).get(key)
            check(games == 18, f'the shared file\'s games went into {CARD_FILE} ({games})')
        run(shared)
    shutil.rmtree(saves, ignore_errors=True)
    print('PASS' if not failures else f'{len(failures)} check(s) failed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
