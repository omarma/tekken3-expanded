#!/usr/bin/env python3
"""OPTION MODE > RECORDS with and without the TTT1 guests (bug B01).

    python3 tools/test_ttt1_records_screen.py [--build build-opt-dbg] [--ttt1 DIR] [--guests all|one|none]

Cold boot of a private copy of the build (debug server, headless), then real
pad input: Start through the intro to the modes menu (state 4), Up = OPTION
MODE (state 5), Down x3 = RECORDS, Circle. Checks, in this order:
  - the game is still running and state 5 holds for 120 frames after the
    screen opens (before the fix the game ended with PC=0 a few frames in);
  - no guest availability bit (23..31) is set in 0x80097EF0 while the screen
    is up, and the stock bits are untouched;
  - the three pages (Right, Right, Right) can be visited;
  - leaving (Circle, Down x3, Circle on EXIT) reaches the modes menu again and the guests'
    bits are back in 0x80097EF0 when guests are present.
guests: all = the catalogue as staged; one = only its first guest; none =
TEKKEN3_TTT1_ROSTER=0 (the stock game). Exit status 0 = all checks passed.
The build's own mods are linked, not copied. The first launch of a run
takes about 30 s at game speed.
"""
import argparse, json, os, shutil, socket, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'psxrecomp/tools'))
import debug_client

START, UP, DOWN, LEFT, RIGHT, CIRCLE = 0xfff7, 0xffef, 0xffbf, 0xff7f, 0xffdf, 0xdfff
IDLE = 0xffff
STATE, UNLOCK = 0x800ae204, 0x80097ef0
GUEST_BITS_MASK = 0xff800000          # IDs 23..31: the only guests the word can carry
GUEST_FIELDS, GUEST_TIME = (7, 5, 3, 0), 120000   # injected into ttt1-guest-records.txt for the first guest
GUEST_GAMES = GUEST_FIELDS[0] + GUEST_FIELDS[2] + GUEST_FIELDS[3]   # what USAGE counts
SURVIVAL = 0x80097ffc
X, PAGE, TA_ROWS = 0x801e0000, 0x40, 0x801e0100      # the patched overlay's structures (records.c)
STOCK_TA, COUNTERS = 0x80097f4c, 0x8009804c
WL = X + 0x250                            # the wins / losses rows


class Game:
    def __init__(self, build, ttt1, guests):
        self.tmp = Path(tempfile.mkdtemp(prefix='records-screen-'))
        run = self.tmp / 'run'
        run.mkdir()
        shutil.copy2(build / 'Tekken_3_Expanded', run / 'Tekken_3_Expanded')
        shutil.copytree(build / 'bios', run / 'bios') if (build / 'bios').is_dir() else None
        (run / 'mods').mkdir()
        for entry in (build / 'mods').iterdir():
            if entry.name != 'ttt1': os.symlink(entry, run / 'mods' / entry.name)
        source = ttt1 or build / 'mods' / 'ttt1'
        if guests == 'one':
            (run / 'mods' / 'ttt1').mkdir()
            for entry in source.iterdir():
                if entry.name != 'guests.txt': os.symlink(entry, run / 'mods' / 'ttt1' / entry.name)
            first = next(l for l in (source / 'guests.txt').read_text().splitlines() if l.split())
            (run / 'mods' / 'ttt1' / 'guests.txt').write_text(first + '\n')
        else:
            os.symlink(source, run / 'mods' / 'ttt1')
        (run / 'settings.toml').write_text('[video]\nsupersampling=1\n[controller]\np1_device="keyboard"\np2_device="none"\n')
        saves = self.tmp / 'saves'
        shutil.copytree(ROOT / 'workspace/fixtures/ps1-saves', saves)
        # The first guest has played 7 games and holds a TIME ATTACK record.
        self.first_key = next(l for l in (source / 'guests.txt').read_text().splitlines() if l.split()).split()[0]
        if guests != 'none':
            (saves / 'ttt1-guest-records.txt').write_text(
                f'{self.first_key} {" ".join(map(str, GUEST_FIELDS))}\n@time {self.first_key} {GUEST_TIME} 84 83 84\n')
        self.guest_count = {'none': 0, 'one': 1}.get(guests) if guests != 'all' else sum(
            1 for l in (source / 'guests.txt').read_text().splitlines() if l.split())
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0)); self.port = s.getsockname()[1]
        env = {k: v for k, v in os.environ.items() if not k.startswith('TEKKEN3_')}
        env['SDL_AUDIO_DRIVER'] = 'dummy'
        if guests == 'none': env['TEKKEN3_TTT1_ROSTER'] = '0'
        self.log = self.tmp / 'game.log'
        self.proc = subprocess.Popen(
            [str(run / 'Tekken_3_Expanded'), '--game', str(ROOT / 'game.toml'),
             '--disc', str(ROOT / 'disc/Tekken 3 (USA).cue'), '--no-launcher', '--renderer', 'software',
             '--debug-port', str(self.port), '--memcard-dir', str(saves), '--headless'],
            cwd=ROOT, stdout=self.log.open('w'), stderr=subprocess.STDOUT, env=env)
        for _ in range(300):
            try: socket.create_connection(('127.0.0.1', self.port), .2).close(); break
            except OSError: time.sleep(.1)

    def q(self, **r): return debug_client.query('127.0.0.1', self.port, r)
    def value(self, a, n=4): return int.from_bytes(bytes.fromhex(self.q(cmd='read_ram', addr=f'{a:08x}', len=n)['hex']), 'little')
    def alive(self): return self.proc.poll() is None

    def route(self, steps):
        self.q(cmd='input_route_clear')
        for frames, buttons in steps: self.q(cmd='input_route_append', frames=frames, buttons=buttons)
        self.q(cmd='input_route_start')
        while self.q(cmd='input_route_status').get('active'): time.sleep(.05)

    def tap(self, b): self.route([(4, b), (14, IDLE)])

    def wait_state(self, want, seconds=90):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.value(STATE) == want: return True
            time.sleep(.1)
        return False

    def close(self):
        if self.alive(): self.proc.terminate()
        try: self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired: self.proc.kill()
        shutil.rmtree(self.tmp, ignore_errors=True)


def check_pages(g, args, check, stock_ta, stock_bits):
    """The page structures the patched overlay reads (step 1: TIME ATTACK and USAGE)."""
    def page(p):
        base = X + p * PAGE
        count = g.value(base + 4)
        ids = list(bytes.fromhex(g.q(cmd='read_ram', addr=f'{base + 8:08x}', len=min(count, PAGE - 8))['hex']))
        return count, ids
    guest_ids = list(range(23, 23 + g.guest_count))
    first = 23
    # TIME ATTACK (page 0): the ten first fighters always, then records; the first guest has one.
    count, ids = page(0)
    check(count == len(ids) and count == 10 + 1, f'TIME ATTACK lists the ten stock fighters and the guest with a record ({count})')
    check(ids[:1] == [first], f'the guest (120000) is ranked first on TIME ATTACK ({ids[:3]})')
    row = g.value(TA_ROWS + first * 8)
    check(row == GUEST_TIME, f'the guest row carries its own time at X+0x100+23*8 ({row})')
    name = bytes.fromhex(g.q(cmd='read_ram', addr=f'{TA_ROWS + first * 8 + 4:08x}', len=3)['hex'])
    check(name == b'TST', f'and its own name ({name!r})')
    # USAGE (page 2): every unlocked stock fighter but id 21, plus every guest, most games first.
    count, ids = page(2)
    expected = sorted([i for i in range(21) if stock_bits >> i & 1] + guest_ids)
    check(sorted(ids) == expected and count == len(expected), f'USAGE lists the unlocked stock fighters but id 21 and {len(guest_ids)} guests ({count})')
    def games(i):
        if i >= 23: return GUEST_GAMES if i == first else 0
        a = COUNTERS + i * 8
        return g.value(a, 2) + g.value(a + 4, 2) + g.value(a + 6, 2)
    order = [games(i) for i in ids]
    check(order == sorted(order, reverse=True), f'USAGE sorted by games, most first ({order[:6]}...)')
    check(g.value(0x800ec450) >= GUEST_GAMES, 'USAGE total includes the guests\' games')
    # wins / losses (page 3): the stock fighters of the mask and every guest, best ratio first
    count, ids = page(3)
    check(sorted(ids) == sorted([i for i in range(22) if stock_bits >> i & 1] + guest_ids),
          f'wins/losses lists the unlocked stock fighters and {len(guest_ids)} guests ({count})')
    row = [g.value(WL + first * 8 + 2 * k, 2) for k in range(4)]
    check(row == list(GUEST_FIELDS), f'the guest wins/losses row at X+0x250+23*8 is its own ({row})')
    def key(i):
        a, b = g.value(WL + i * 8 + 2, 2), g.value(WL + i * 8 + 4, 2)
        return ((a * 1000 // (a + b) if a + b else 0) << 20) + a + b
    keys = [key(i) for i in ids]
    check(keys == sorted(keys, reverse=True), f'wins/losses sorted by ratio then total, best first ({[hex(k) for k in keys[:3]]}...)')
    check(g.value(WL + 5 * 8 + 2, 2) == g.value(COUNTERS + 5 * 8 + 2, 2), 'a stock row is the game\'s own row')
    # GREATEST SURVIVORS (page 1): the fixed ten rows, the first one is a guest
    count, ids = page(1)
    check(count == 10 and ids == list(range(10)), f'GREATEST SURVIVORS keeps its ten rows 0..9 ({ids})')
    check(g.value(SURVIVAL, 2) == 23, 'and the guest is still in the first Survival row')
    # the real tables are never written
    check(g.q(cmd='read_ram', addr=f'{STOCK_TA:08x}', len=0x1b0)['hex'] == stock_ta, 'stock TIME ATTACK table and Survival rows untouched')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='build-opt-dbg')
    ap.add_argument('--ttt1', help='staged ttt1 assets (default: BUILD/mods/ttt1)')
    ap.add_argument('--guests', default='all', choices=('all', 'one', 'none'))
    ap.add_argument('--native', help='json file: with --guests none the native (vanilla) pages are written there, otherwise the stock part of ours is compared with it')
    ap.add_argument('--shots', help='directory for one capture per RECORDS page (to be judged by eye)')
    args = ap.parse_args()
    build = (ROOT / args.build).resolve()
    g = Game(build, Path(args.ttt1).resolve() if args.ttt1 else None, args.guests)
    failures = []
    def check(ok, what):
        print(('ok   ' if ok else 'FAIL ') + what, flush=True)
        if not ok: failures.append(what)
    try:
        # Start through the intro until the modes menu (state 4).
        for _ in range(60):
            if g.value(STATE) == 4: break
            g.tap(START); time.sleep(2)
        check(g.value(STATE) == 4, 'reached the modes menu (state 4)')
        time.sleep(3)
        stock_before = g.value(UNLOCK) & ~GUEST_BITS_MASK
        g.route([(4, UP), (30, IDLE)]); g.tap(CIRCLE)
        check(g.wait_state(5, 30), 'OPTION MODE is state 5')
        time.sleep(2)
        if args.guests != 'none':       # the first Survival row holds the first guest (id 23), 5 wins, name TST
            g.q(cmd='write_ram', addr=f'{SURVIVAL:08x}', bytes='17000500545354' + '00')
        stock_ta = g.q(cmd='read_ram', addr=f'{STOCK_TA:08x}', len=0x1b0)['hex']   # table and Survival rows
        for _ in range(3): g.tap(DOWN)
        crashed = False
        try:
            g.tap(CIRCLE)
            start = g.q(cmd='frame')['frame']
            while g.q(cmd='frame')['frame'] < start + 120 and g.alive(): time.sleep(.1)
        except Exception:
            crashed = True
        crashed = crashed or not g.alive()
        check(not crashed, 'RECORDS stays up for 120 frames (game still running)')
        if not crashed:
            check(g.value(STATE) == 5, 'still in state 5 on the RECORDS screen')
            word = g.value(UNLOCK)
            check(word & GUEST_BITS_MASK == 0, f'no guest bit in 0x80097EF0 on RECORDS ({word:#010x})')
            check(word & ~GUEST_BITS_MASK == stock_before, 'stock availability bits untouched')
            if args.guests != 'none': check_pages(g, args, check, stock_ta, stock_before)
            elif args.native:
                native = {}
                for p in (0, 1, 2, 3):
                    base = 0x800ec458 + p * 0x20
                    n = g.value(base + 4)
                    native[p] = list(bytes.fromhex(g.q(cmd='read_ram', addr=f'{base + 8:08x}', len=min(n, 24))['hex']))
                Path(args.native).write_text(json.dumps(native)); print('native pages:', native)
            if args.guests != 'none' and args.native and Path(args.native).exists():
                native = json.loads(Path(args.native).read_text())
                for p in (0, 1, 2, 3):
                    base = X + p * PAGE
                    n = g.value(base + 4)
                    ours = [i for i in bytes.fromhex(g.q(cmd='read_ram', addr=f'{base + 8:08x}', len=min(n, PAGE - 8))['hex']) if i < 23]
                    check(ours == native[str(p)], f'page {p}: stock ids and their order equal the vanilla ones ({ours} vs {native[str(p)]})')
            def shot(name):
                if args.shots:
                    Path(args.shots).mkdir(parents=True, exist_ok=True)
                    g.q(cmd='screenshot', path=str(Path(args.shots).resolve() / f'records-{args.guests}-{name}.png'))
            shot('page0')
            def scroll_check(p):    # the native Down scroll reaches the last row, Up goes back
                base = X + p * PAGE; count = g.value(base + 4)
                for _ in range(count + 2): g.tap(DOWN)
                off = g.value(base)
                check(count > 10 and off == count - 10, f'page {p} scrolled down to its last ten rows (offset {off}, {count} rows)'); shot(f'page{p}-end')
                for _ in range(count + 2): g.tap(UP)
                check(g.value(base) == 0, f'page {p} back to the top with Up')
            if args.guests != 'none': scroll_check(0)
            for page in range(3):
                g.tap(RIGHT); time.sleep(1)
                check(g.alive() and g.value(STATE) == 5, f'page step {page + 1} alive'); shot(f'page{(page + 1) % 4}')
                if page in (1, 2) and args.guests != 'none': scroll_check(page + 1)
            g.tap(CIRCLE); time.sleep(1)                 # leave RECORDS, cursor on it in the option list
            for _ in range(3): g.tap(DOWN)             # DISPLAY ADJUST, MEMORY CARD, EXIT
            g.tap(CIRCLE)
            check(g.wait_state(4, 30), 'back at the modes menu after leaving')
            time.sleep(2)
            if args.guests != 'none':
                check(g.value(UNLOCK) & GUEST_BITS_MASK != 0, 'guest bits back in 0x80097EF0 outside OPTION MODE')
                # and a guest can really be chosen: ARCADE selector, Tag page (R2), cursor onto a guest cell
                g.tap(DOWN); g.tap(CIRCLE)          # the cursor is on OPTION MODE: one Down wraps to ARCADE
                check(g.wait_state(9, 40), 'ARCADE character selector (state 9) after RECORDS')
                time.sleep(3)
                check(g.value(0x80118648) == 21, f'stock grid of 21 cells ({g.value(0x80118648)})')
                g.tap(0xfdff); time.sleep(2)
                check(g.value(0x80118648) == g.guest_count, f'R2 opens the Tag page with {g.guest_count} guest cells ({g.value(0x80118648)})')
                for _ in range(20):
                    if g.value(0x80118668) >= 23: break
                    g.tap(RIGHT)
                check(g.value(0x80118668) >= 23, f'the cursor reaches a guest (character {g.value(0x80118668)})')
                shot('tag-page')
        else:
            tail = g.log.read_text(errors='replace').splitlines()[-2:]
            print('game output tail:', *tail, sep='\n  ')
    finally:
        g.close()
    print('PASS' if not failures else f'{len(failures)} check(s) failed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
