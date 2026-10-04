#!/usr/bin/env python3
"""Survival with guests: wins counters and SURVIVAL RESULTS (bug 17).

    python3 tools/test_survival_guests.py --build build-17-lite [--wins 9] [--guests 1,0]

Plays Survival as Jin from the cabinet selector, wins each fight by taking
the CPU's life to 0 (the fight, the counters and the screens are the
game's), and after every fight logs: the opponent, the wins counter
(0x800AFAAC), the sum of the stock counters (0x800AFA88 + 0x60 + 2 * ID,
IDs 0..21), the guests' counters read as a table would. At the results screen
(state 14) it logs the counters again and captures the screen.
Captures go to workspace/ttt1-live/surv17-*.png.
"""
import argparse, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live as L

MODE, WINS, COUNTS, STATE = 0x800afa88, 0x800afaac, 0x800afa88 + 0x60, 0x800ae204


def counters(s):
    raw = s.read(COUNTS, 2 * 44)
    c = [int.from_bytes(raw[i * 2:i * 2 + 2], 'little') for i in range(44)]
    return c


def report(s, label):
    c = counters(s)
    print(f'{label}: wins(+0x24)={s.value(WINS)} hud(+0x44)={s.value(WINS + 0x20)} stock_sum={sum(c[:22])} '
          f'guest_cells={[(i, c[i]) for i in range(22, 44) if c[i]]} '
          f'mode={s.value(MODE)} opp={s.value(0x800add5e, 2)} state={s.value(STATE)} sub={s.value(0x800ae224, 2)} life={s.value(0x800a961e, 2)},{s.value(0x800aaeaa, 2)}', flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='build-17-lite')
    ap.add_argument('--wins', type=int, default=10)
    ap.add_argument('--guests', default='1,0')
    ap.add_argument('--tag', default='a')
    ap.add_argument('--p1', default='', help='play as this guest (Tag page, R2) instead of Jin')
    ap.add_argument('--force', default='', help='opponents by fight, "ID:costume,..." (written while the fight loads)')
    a = ap.parse_args()
    s = L.Session(guest=a.p1 or 'jun', build=L.ROOT / a.build, env={'TEKKEN3_SURVIVAL_GUESTS': a.guests, 'TEKKEN3_NATIVE_MOVES': '0'})
    try:
        s.wait(lambda: s.value(STATE) == 9 and s.value(0x80118648) == 21, 'selector', 20)
        s.write(MODE, 4)
        if a.p1:
            s.press(L.PAD_R2)
            time.sleep(2)
            row, col = L.tag_place(s.index, s.catalogue_size)
            for _ in range(12):
                r, c = L.tag_place(s.value(0x80118650), s.catalogue_size)
                if (r, c) == (row, col): break
                s.press(0xffbf if r < row else 0xffef if r > row else 0xffdf if c < col else 0xff7f)
            s.wait(lambda: s.value(0x80118668) == s.cid, 'cursor on the guest', 10)
        else:
            for _ in range(23):
                if s.value(0x80118668) == 9: break
                s.press(0xff7f)
        s.press(0x7fff)
        forced = [tuple(map(int, f.split(':'))) for f in a.force.split(',') if f]
        for n in range(a.wins):
            if n < len(forced):
                while not (s.value(STATE) == 8 and s.value(0x800ae224, 2) >= 6):
                    if s.value(STATE) == 11: s.write(0x800add5e, forced[n][0], 2); s.write(0x800add9a, forced[n][1], 2)
                    time.sleep(0.05)
            s.wait(lambda: s.value(STATE) == 8 and s.value(0x800ae224, 2) >= 6, f'fight {n + 1} start', 120)
            time.sleep(1)
            if n in (a.wins - 1, 8):
                s.shot(f'surv17-{a.tag}-hud-{n + 1}')
            report(s, f'fight {n + 1} start')
            time.sleep(3)
            end = time.monotonic() + 100
            while s.value(WINS) <= n and time.monotonic() < end:
                if s.value(STATE) == 8 and s.value(0x800ae224, 2) >= 6: s.write(0x800aaeaa, 0, 2)                  # CPU's life (player 2 actor + 0x3F6)
                time.sleep(0.4)
            report(s, f'fight {n + 1} won  ')
        # end the run: P1's life to 0 in the next fight
        s.wait(lambda: s.value(STATE) == 8 and s.value(0x800ae224, 2) >= 6, 'last fight', 120)
        report(s, 'last fight')
        time.sleep(3)
        end = time.monotonic() + 100
        while s.value(STATE) == 8 and time.monotonic() < end:
            s.write(0x800a961e, 0, 2)
            time.sleep(0.4)
        s.wait(lambda: s.value(STATE) == 14, 'SURVIVAL RESULTS', 90)
        time.sleep(3)
        report(s, 'results')
        s.shot(f'surv17-{a.tag}-results')
        time.sleep(15)
        s.shot(f'surv17-{a.tag}-after')
        report(s, 'after')
        print('ranking', [ (s.value(0x80097ffc + r * 8, 2), s.value(0x80097ffe + r * 8, 2)) for r in range(10)])
    except BaseException:
        report(s, 'FAILED at'); s.shot(f'surv17-{a.tag}-failed'); raise
    finally:
        s.stop()


if __name__ == '__main__':
    main()
