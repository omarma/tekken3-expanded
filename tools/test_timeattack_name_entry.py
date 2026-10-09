#!/usr/bin/env python3
"""Time Attack name entry: the top list scrolls to the player's row (bug B36, GH#58).

    python3 tools/test_timeattack_name_entry.py [--build build-opt-dbg] [--guests all|none]
                                                [--fighter native|guest] [--rank N] [--shots DIR]

Cold boot of a private copy of the build (tools/test_ttt1_records_screen.Game:
debug server, headless, copy of the fixture saves), modes menu, TIME ATTACK,
a fighter (native: the selector's first cell; guest: R2 then Right to a guest
cell), then every round is won by setting player 2's life to 0 (turbo). Before
the run ends the stock table (0x80097F4C, 22 rows {time, name}) is filled so
that the run's time lands at row N of the list (0 = first). On the name
entry (state 16) the ranking
structure 0x800CB878 is read once the scroll has stopped: count (+0xC), IDs (+0xE), the player's rank
(+0x88), first row shown (+0x50), cursor row (+0x86), scroll (+2).
Checks: the row 0x80097F44 points at is the player's, it is in the list at
the rank found, that row is on screen (first <= rank < first + 5) and the
scroll stopped where the overlay puts it (0xA8 - 72 * first). Exit status 0
= all checks passed.
"""
import argparse, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ttt1_records_screen import Game, ROOT, START, UP, DOWN, RIGHT, CIRCLE, IDLE, STATE

SQUARE, R2 = 0x7fff, 0xfdff
MENU_LINE, MODE, PHASE = 0x80097f40, 0x800afa88, 0x800ae224
P1_CHOICE, P1_LIFE, P2_LIFE, FIGHTER = 0x80118668, 0x800a961e, 0x800aaeaa, 0x800afb14   # life: u16 at actor + 0x3F6
TABLE, POINTER, NO_TIME = 0x80097f4c, 0x80097f44, 0x57e3f
LIST = 0x800cb878                           # the ranking overlay's structure (s2 of 0x800C2434)
SHOWN = 5                                   # rows on screen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='build-opt-dbg')
    ap.add_argument('--guests', default='all', choices=('all', 'none'))
    ap.add_argument('--fighter', default='native', choices=('native', 'guest'))
    ap.add_argument('--rank', type=int, default=4, help='row the run lands on (0 = first)')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--shots', help='directory for a capture of the name entry')
    args = ap.parse_args()
    g = Game((ROOT / args.build).resolve(), None, args.guests)
    failures = []
    def check(ok, what):
        print(('ok   ' if ok else 'FAIL ') + what, flush=True)
        if not ok: failures.append(what)
    w32 = lambda a, v: g.q(cmd='write_ram', addr=f'{a:08x}', bytes=v.to_bytes(4, 'little').hex())
    try:
        for _ in range(60):
            if g.value(STATE) == 4: break
            g.tap(START); time.sleep(2)
        check(g.value(STATE) == 4, 'reached the modes menu (state 4)')
        time.sleep(3)
        for _ in range(12):                 # down to TIME ATTACK (menu line 0x80097F40 = 4, read late)
            time.sleep(1)
            if g.value(MENU_LINE, 1) == 4: break
            g.tap(DOWN)
        g.tap(CIRCLE)
        if not g.wait_state(9, 40) or g.value(MODE) != 3:
            check(False, f'TIME ATTACK selector (state {g.value(STATE)}, mode {g.value(MODE)})'); return 1
        time.sleep(3)
        if args.fighter == 'guest':
            g.tap(R2); time.sleep(2)
            for _ in range(20):
                if g.value(P1_CHOICE) >= 23: break
                g.tap(RIGHT)
        g.tap(SQUARE)
        time.sleep(1)
        player = g.value(P1_CHOICE)
        # Stock rows: the first N faster than any run, the rest slower (the ten first fighters
        # are always listed). The player's own row is set slower so the run is a record.
        stock = [i for i in range(21) if i != player]
        for k, i in enumerate(stock):
            w32(TABLE + i * 8, 0x100 + k if k < args.rank else 0x50000 + k)
            g.q(cmd='write_ram', addr=f'{TABLE + i * 8 + 4:08x}', bytes=b'AB' .hex() + f'{0x41 + k % 26:02x}00')
        if player < 22: w32(TABLE + player * 8, NO_TIME)
        g.q(cmd='turbo', enabled=1)
        # Win every round; the run's time is read on the results screen (state 13).
        end = time.monotonic() + 900
        last = None
        while time.monotonic() < end and g.alive():
            s = g.value(STATE)
            if args.verbose and s != last:
                print(f'  state {s}: player row {g.value(TABLE + player * 8):#x}, row 12 {g.value(TABLE + 12 * 8):#x}, '
                      f'pointer {g.value(POINTER):#x}', flush=True)
                last = s
            if s in (13, 16): break
            if args.verbose and s == 8 and int(time.monotonic()) % 10 == 0:
                print(f'    phase {g.value(PHASE, 2)} life p1 {g.value(P1_LIFE, 2)} p2 {g.value(P2_LIFE, 2)} frame {g.q(cmd="frame")["frame"]}', flush=True)
            if s == 8 and g.value(PHASE, 2) >= 6 and g.value(P2_LIFE, 2):
                g.q(cmd='write_ram', addr=f'{P2_LIFE:08x}', bytes='0000')
            time.sleep(.2)
        check(g.value(STATE) in (13, 16), f'the run is over (state {g.value(STATE)})')
        g.q(cmd='turbo', enabled=0)
        # The run took no time (every round won at once): give the record a time after the
        # N rows set faster, before the name entry builds its list from the table.
        pointer = g.value(POINTER)
        if pointer: w32(pointer, 0x1000)
        while g.alive() and g.value(STATE) == 13:     # TIME ATTACK CLEAR, YOUR TIME
            g.tap(CIRCLE); time.sleep(.5)
        check(g.wait_state(16, 60), 'name entry (state 16)')
        end = time.monotonic() + 60
        seen = None                         # phase 12: the name is being entered, the scroll is over
        while time.monotonic() < end and g.alive():
            now = (g.value(STATE), g.value(PHASE, 2), g.value(LIST + 0xc, 2), g.value(LIST + 0x88, 2), g.value(POINTER))
            if args.verbose and now != seen: print(f'  state {now[0]} phase {now[1]} count {now[2]} rank {now[3]} pointer {now[4]:#x}', flush=True)
            seen = now
            if now[1] == 12: break
            time.sleep(.1)
        time.sleep(.5)
        phase = g.value(PHASE, 2)
        count, rank = g.value(LIST + 0xc, 2), g.value(LIST + 0x88, 2)
        first, cursor = g.value(LIST + 0x50), g.value(LIST + 0x86, 2)
        scroll = int.from_bytes(g.value(LIST + 2, 2).to_bytes(2, 'little'), 'little', signed=True)
        ids = [g.value(LIST + 0xe + 2 * i, 2) for i in range(min(count, 24))]
        pointer = g.value(POINTER)
        print(f'player {player}, phase {phase}, count {count}, ids {ids}, rank {rank}, first {first}, '
              f'cursor {cursor}, scroll {scroll}, pointer {pointer:#x}')
        check(rank < count, f'the player\'s rank is in the list ({rank} of {count})')
        check(rank < count and pointer == TABLE + ids[rank] * 8,
              f'the list row at the rank is the row the name goes to ({pointer:#x})')
        check(rank == args.rank, f'the run is ranked where it was put ({rank}, wanted {args.rank})')
        check(first <= rank < first + SHOWN, f'the player\'s row is on screen (rows {first}..{first + SHOWN - 1})')
        check(rank < count and rank - first == cursor, f'the cursor is on it (cursor row {cursor})')
        check(scroll == 0xa8 - 72 * first, f'scrolled to the first row shown ({scroll} == {0xa8 - 72 * first})')
        if args.shots:
            Path(args.shots).mkdir(parents=True, exist_ok=True)
            g.q(cmd='screenshot', path=str(Path(args.shots).resolve() / f'name-entry-{args.fighter}-{args.rank}.png'))
    finally:
        g.close()
    print('PASS' if not failures else f'{len(failures)} check(s) failed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
