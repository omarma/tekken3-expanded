#!/usr/bin/env python3
"""Practice > VS CPU offers the arcade CPU levels of GAME OPTION (B135, GH#182).

    python ressources/slot.py --kind game --who b135 --prio 2 -- \\
        python tools/test_b135_practice_cpu_difficulty.py OUT [--build build-rel-lite] [--option 1]

Build: PSX_DEBUG_SERVER_LITE=ON, with mods/difficulty/levels.bin (tools/difficulty/import.py). --option: GAME
OPTION's DIFFICULTY LEVEL (0x80097F06) set before Practice: 0..2 the game's, 3.. the levels added by
src/tekken3_difficulty_mod.c (6 = EX SUPER HARD).

A cold start each (stage_check.Game: software x1, headless, a blank card), the Practice grid, both picks, the
fight; RETURN TO MODE SELECT, VS CPU. Then right on CPU DIFFICULTY (practice block 0x800B8B60 + 0x7E) through every
value and back to the start, and left once from EASY: at each value the row as the menu draws it (the name and
the label list read back from the lui / addiu at 0x800B5A20 and 0x800B5A38), then OK: the menu closes, the CPU is
reset (practice_menu_close, ai_fighter_reset), and its block (P2's AI structure 0x8009F648 + 568, 110 bytes) is
compared with the one of levels.bin it should be, at CPU LEVEL's stage (+0x7F).

Expected (the game's own rule: EASY is passed as 0, which 0x80061488 reads as the game's copy of GAME OPTION's
level): EASY = GAME OPTION's level, MEDIUM / HARD = the game's, each added level = its own blocks under its short
name with the row named DIFFICULTY; the cycle wraps over all of them. Before the fix: three values only, and with
an added level in GAME OPTION every one of them played it (MEDIUM measured as EX SUPER HARD, 2026-10-31).
Screenshots of each value in OUT; exit 1 on a mismatch.
"""
from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import test_f18_stage_select as f18  # noqa: E402

sc = f18.sc
OPTION = 0x80097F06
BLOCK = 0x800B8B60                        # practice block: +0x77 mode, +0x79 VS CPU cursor, +0x7E / +0x7F CPU
PAUSE, CONTROL = BLOCK + 0x8A, BLOCK + 0x80
CHOICE, STAGE, CURSOR, PAGE = BLOCK + 0x7E, BLOCK + 0x7F, BLOCK + 0x79, BLOCK + 0x77
MODE_SELECT = BLOCK + 0x75
NAME_HI, LIST_HI = 0x800B5A20, 0x800B5A38
AI_P2 = 0x8009F648 + 568
NATIVE = ('ps1-easy', 'ps1-medium', 'ps1-hard')


def levels(path: Path):
    """key -> (label, ten 110-byte blocks), in the order of the file."""
    data = path.read_bytes()
    out = {}
    for i in range(struct.unpack_from('<I', data, 8)[0]):
        e = data[16 + i * 1188:16 + (i + 1) * 1188]
        out[e[:24].split(b'\0')[0].decode()] = (e[24:88].split(b'\0')[0].decode(),
                                               [e[88 + s * 110:88 + (s + 1) * 110] for s in range(10)])
    return out


class Game(f18.Game):
    def __init__(self, build: Path, run: Path):
        sc.Game.__init__(self, build, run, 'off', 'software', Path('.'), widescreen=False)

    def address(self, hi):
        """The address a lui / addiu pair (hi, hi + 4 or hi + 8) builds."""
        lo = hi + 8 if hi == LIST_HI else hi + 4
        return ((self.value(hi) & 0xffff) << 16) + struct.unpack('<h', struct.pack('<H', self.value(lo) & 0xffff))[0]

    def row(self):
        """(name, label) of CPU DIFFICULTY as drawn."""
        choice = self.value(CHOICE, 1)
        return self.string(self.address(NAME_HI)), self.string(self.value(self.address(LIST_HI) + 4 * choice))


def to_vs_cpu(g: Game):
    f18.to_practice_grid(g)
    g.press(f18.CROSS); time.sleep(1.5); g.press(f18.CROSS)
    g.wait(lambda: g.value(f18.SCREEN) == 8, 'the fight never came', 120)
    g.wait(lambda: g.value(f18.PHASE, 2) >= 6, 'the round never started', 60)
    time.sleep(2)
    open_menu(g)
    g.press(f18.UP); time.sleep(.3); g.press(f18.CROSS)                     # RETURN TO MODE SELECT
    g.wait(lambda: g.value(MODE_SELECT, 1), 'MODE SELECT never came', 5)
    time.sleep(.5)
    g.press(f18.DOWN); time.sleep(.3); g.press(f18.CROSS)                   # VS CPU
    g.wait(lambda: g.value(PAGE, 1) == 1 and not g.value(MODE_SELECT, 1), 'the VS CPU page never came', 5)
    time.sleep(.5)


def open_menu(g: Game):
    """Start until the pause menu shows (a press on a busy frame can be lost)."""
    for _ in range(5):
        g.press(f18.START)
        try:
            g.wait(lambda: g.value(PAUSE, 1), '', 1.5)
            time.sleep(.5)
            return
        except AssertionError:
            pass
    raise AssertionError('the pause menu never opened')


def to_line(g: Game, line: int):
    for _ in range(12):
        c = g.value(CURSOR, 1)
        if c == line: return
        g.press(f18.DOWN if c < line else f18.UP); time.sleep(.2)
    raise AssertionError(f'the cursor never reached line {line}')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('out')
    p.add_argument('--build', default='build-rel-lite')
    p.add_argument('--option', type=int, default=1, help="GAME OPTION's DIFFICULTY LEVEL value")
    args = p.parse_args()
    build, out = (ROOT / args.build).resolve(), Path(args.out).resolve()
    table = levels(build / 'mods/difficulty/levels.bin')
    added = [k for k in table if k not in NATIVE]
    count = 3 + len(added)
    keys = list(NATIVE) + added
    game_level = keys[min(args.option, count - 1)]
    g = Game(build, out / 'run')
    failures = []
    try:
        f18.to_menu(g)
        g.write(OPTION, args.option)
        to_vs_cpu(g)
        stage = g.value(STAGE, 1)
        start = g.value(CHOICE, 1)
        print(f'GAME OPTION {args.option} ({game_level}), CPU LEVEL stage {stage + 1}, '
              f'CPU DIFFICULTY starts on {start}, {count} values expected')
        seen = []
        for step in range(count + 1):
            to_line(g, 2)
            g.press(f18.RIGHT if step < count else f18.LEFT); time.sleep(.4)
            choice = g.value(CHOICE, 1)
            seen.append(choice)
            name, label = g.row()
            g.shot(out / f'{step:02d}-value-{choice}.png')
            to_line(g, 0)
            g.press(f18.CROSS); time.sleep(1.2)
            if g.value(PAUSE, 1) or g.value(CONTROL, 1) != 2:
                failures.append(f'value {choice}: the menu did not close on the CPU')
            block = g.read(AI_P2, 110)
            want = game_level if choice == 0 else keys[choice]
            hit = [k for k in keys if table[k][1][stage] == block]
            ok = table[want][1][stage] == block
            short = label if choice < 3 else table[want][0].split(' (')[0]
            row_ok = label == short and name == ('DIFFICULTY' if choice >= 3 else 'CPU DIFFICULTY')
            print(f'value {choice}: row "{name}  {label}", CPU block {"/".join(hit) or "unknown"} '
                  f'(expected {want}) {"OK" if ok and row_ok else "FAILED"}')
            if not ok: failures.append(f'value {choice}: block {hit} instead of {want}')
            if not row_ok: failures.append(f'value {choice}: row "{name}  {label}"')
            open_menu(g)
        cycle = [(start + 1 + i) % count for i in range(count)] + [(start + count - 1) % count]
        if seen != cycle:
            failures.append(f'cycle {seen} instead of {cycle}')
        print('cycle', seen)
    finally:
        g.stop()
    if failures:
        print('FAILED:\n  ' + '\n  '.join(failures))
        sys.exit(1)
    print('B135: OK')


if __name__ == '__main__':
    main()
