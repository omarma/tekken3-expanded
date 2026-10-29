#!/usr/bin/env python3
"""F18 (GH#148): the STAGE line of VS BATTLE SELECT and of the Practice grid, without a player.

    python ressources/slot.py --kind game --who f18 --prio 2 -- \\
        python tools/test_f18_stage_select.py vs|practice out/f18 [--build build-dbg]

(a PSX_DEBUG_SERVER_LITE build; a Python with Pillow; the stage packs of an
install: --data, its mods folder)

A cold start each (stage_check.Game: software renderer x1, headless, the
stage packs of --data), screenshots at each step in --out. vs needs player 2
injected on port 2: a PSX_DEBUG_TOOLS=ON build (build-dbg).

    vs        no band while player 2 still chooses (B127); player 2 done
              last opens it for both: TEKKEN TAG TOURNAMENT, LAW, back to
              PAUL, the fight on TTT PAUL; the rematch: player 2 done first,
              no band, player 1 last: TEKKEN 3, DR B, back to the handicap
              and again, player 2 takes (arena 14, Dr. B's music 0x19)
    practice  the dummy's pick opens the band on GAME: TEKKEN 3, its STAGE,
              BRYAN, back to GAME, again, PAUL: arena 0, Paul's music 0x07
    random    RANDOM of both games: the stage drawn and its music together
    option    GAME OPTION's STAGE SELECT row: ON to OFF, kept beside the card;
              OFF: no band in Practice, the game's arena (3)
    off       the feature off: no band, the game's arena (3)
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/arcade_stages'))
import stage_check as sc  # noqa: E402

DATA = Path('C:/TekkenProject/release-1.4.0-test/pc-banc/tekken3-expanded-1.4.0/build-release/mods')
SCREEN, PHASE, MODE, LINE = 0x800ae204, 0x800ae224, 0x800afa88, 0x80097f40
ENTRY, LEVEL = 0x800ead58, 0x800ec020         # GAME OPTION's menu level (src/tekken3_game_options.c)
MENU_LINES = 0x800db5d0                    # the modes menu's lines: base, count at +4, mode at +16 + 8i + 4
VS_BLOCKS, VS_STRIDE = 0x800b8d70, 172     # +0 state: 3 choosing, 4 handicap, 12 done
ARENA, MUSIC, HUMAN, P2_LIFE = 0x800adc84, 0x800add08, 0x800ae1f8, 0x800aaeaa
START, CROSS, CIRCLE, RIGHT, LEFT, UP, DOWN = 0xfff7, 0xbfff, 0xdfff, 0xffdf, 0xff7f, 0xffef, 0xffbf
NONE = 0xffff
VS, PRACTICE = 1, 5
FEATURE = ('tekken3.gameplay.stage-select', 'stage-select')


class Game(sc.Game):
    def __init__(self, build: Path, run: Path, data: Path, widescreen=True, env=None, feature=True):
        super().__init__(build, run, 'mod', 'software', data / 'arcade-stages', widescreen=widescreen,
                         env_extra={'TEKKEN3_TTT_STAGES_DIR': str(data / 'ttt-stages'), **(env or {})},
                         features=[(*FEATURE, feature)])

    # Without a pad the selector's input hook runs only while a press is
    # injected: an explicit release, or two presses of one button are one.
    def press(self, buttons):
        self.q(cmd='press', buttons=buttons, frames=4)
        time.sleep(.15)
        self.q(cmd='press', buttons=NONE, frames=2)
        time.sleep(.2)

    def p2(self, buttons, frames=4):
        self.q(cmd='press', buttons=buttons, frames=frames, port=2)
        time.sleep(.15)
        self.q(cmd='press', buttons=NONE, frames=2, port=2)
        time.sleep(.2)

    def shot(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.q(cmd='screenshot', path=str(path))
        time.sleep(.3)

    def logtext(self):
        return self.log.read_text(errors='replace')

    def vs_state(self, p):
        return self.value(VS_BLOCKS + p * VS_STRIDE)

    def tap(self, buttons):
        """One frame: the options' cursor moves once a frame a direction is held."""
        self.q(cmd='press', buttons=buttons, frames=1)
        time.sleep(.15)
        self.q(cmd='press', buttons=NONE, frames=2)
        time.sleep(.25)

    def string(self, a):
        out = b''
        while len(out) < 40 and (c := self.value(a + len(out), 1)): out += bytes([c])
        return out.decode('latin-1')

    def option_row(self):
        """(the row under GAME OPTION's cursor, its value label)."""
        rows, c = self.value(ENTRY + 0x20), self.value(ENTRY)
        row = rows + 20 * c
        labels = self.value(row + 8)
        value = self.string(self.value(labels + 4 * self.value(self.value(row), 1))) if labels else ''
        return self.string(self.value(row + 4)), value


def to_menu(g: Game, pad2=False):
    """The modes menu; pad2: player 2's pad plugged from the title on (the
    menu has VS MODE then, after QUIT GAME)."""
    g.q(cmd='turbo', enabled=1)

    def menu():
        if g.value(SCREEN) == 3:
            g.write(0x80097ef0, 0x1fffff, 4)            # every fighter, Gon's first Ball match past
            g.write(0x80097f1e, 1); g.write(0x80097f26, 1); g.write(0x80097f27, 1)
            if pad2: g.q(cmd='set_input', buttons='ffff', port=2)
            g.press(START)
        return g.value(SCREEN) == 4
    g.wait(menu, 'the modes menu never came', 240)
    g.q(cmd='turbo', enabled=0)
    time.sleep(.5)


def menu_line(g: Game, mode: int) -> int:
    # lui / ori at 0x800DB5D0 / 0x800DB5D8 build the lines' base (TIPS.md section 22)
    for _ in range(50):
        base = (g.value(MENU_LINES) & 0xffff) << 16 | g.value(MENU_LINES + 8) & 0xffff
        count = g.value(base + 4) if base >> 24 in (0x80, 0x9f) else 0
        if 0 < count < 16: break
        time.sleep(.1)
    for i in range(count):
        if g.value(base + 16 + 8 * i + 4, 2) in (mode, mode | 0x100):   # VS MODE 0x101, QUIT GAME 0xff
            return i
    modes = [hex(g.value(base + 16 + 8 * i + 4, 2)) for i in range(count)]
    raise AssertionError(f'no line of mode {mode} in the modes menu: {modes}')


def to_vs(g: Game):
    """VS MODE from the modes menu, player 2 on port 2."""
    to_menu(g, pad2=True)
    g.write(LINE, menu_line(g, VS), 4)
    g.press(CROSS)
    g.wait(lambda: g.value(SCREEN) == 10 and g.value(MODE) == VS and g.vs_state(0) == 3,
           'VS BATTLE SELECT never came', 30)
    time.sleep(2)


def to_practice_grid(g: Game):
    to_menu(g)
    g.write(LINE, menu_line(g, PRACTICE), 4)
    g.press(CROSS)
    g.wait(lambda: g.value(SCREEN) == 9 and g.value(MODE) == PRACTICE, 'the Practice grid never came', 30)
    time.sleep(2)


def fight_on(g: Game, out: Path, name: str):
    g.wait(lambda: g.value(SCREEN) == 8, 'the fight never came', 120)
    g.wait(lambda: g.value(PHASE, 2) >= 6, 'the round never started', 60)
    time.sleep(2)
    g.shot(out / f'{name}.png')
    return g.value(ARENA, 2)


def vs(args):
    """VS: no line while both choose, nor while one is done and the other
    still chooses (B127, the user's, 2026-10-29). Player 1 picks and takes
    the handicap: no band, right is the game's. Player 2 picks, the handicap's
    take is held: the band shows on GAME for both. Player 1: right three
    times, DEFAULT, RANDOM, TEKKEN 3, TEKKEN TAG TOURNAMENT (TTT PAUL);
    player 2: down to STAGE, right (LAW); player 1: left (PAUL), cross: player
    2's take goes to the game, the fight on TTT's stage 0 (arena 0). The match
    is ended (player 2's life at 0 in each round), both choose again: player
    2 done first, no band, left is the game's. Player 1 last: the band on GAME
    TEKKEN TAG TOURNAMENT; player 2: left (TEKKEN 3, T3 PAUL), down, left
    twice (RANDOM, DR B); player 1: circle back to GAME, circle back to the
    handicap (still 4), cross again: the band, on DR B; player 2 takes it, and
    the fight loads Dr. B's arena 14 and music 0x19 for Xiaoyu and Jin (hers
    0x0E, his 0x10). Port 1 is polled only while injected: player 2's take is
    handed to player 1 over an all-up press of port 1."""
    out = Path(args.out).resolve()
    g = Game(Path(args.build).resolve(), out / 'run-vs', Path(args.data), args.aspect == '16:9',
             env={'TEKKEN3_STAGE_SELECT': 'vs=default,practice=default'})

    def sets():
        return [l for l in g.logtext().splitlines() if ' sets the VS ' in l]
    try:
        to_vs(g)
        g.shot(out / 'vs-0-grid.png')
        g.press(CROSS); g.press(CROSS)
        g.wait(lambda: g.vs_state(0) == 12, 'player 1 never got done', 10)
        g.press(RIGHT); time.sleep(.5)
        g.shot(out / 'vs-1-p1-done.png')
        assert 'waits on the STAGE band' not in g.logtext() and not sets(), 'the band opened before player 2 chose'
        g.p2(CROSS); time.sleep(.5); g.shot(out / 'vs-2-p2-handicap.png')
        assert g.vs_state(1) == 4 and 'waits on the STAGE band' not in g.logtext(), 'the band opened on the pick'
        g.p2(CROSS); time.sleep(.5)
        g.shot(out / 'vs-3-band.png')
        assert 'P2 done last, the handicap waits on the STAGE band' in g.logtext(), 'player 2 done last: no band'
        assert g.vs_state(1) == 4 and g.value(SCREEN) == 10, "player 2's take went to the game"
        g.press(RIGHT); g.press(RIGHT); g.press(RIGHT); time.sleep(.5)
        assert 'P1 sets the VS game to TEKKEN TAG TOURNAMENT (TTT PAUL)' in g.logtext(), 'player 1 did not set TTT'
        g.p2(DOWN); g.p2(RIGHT); time.sleep(.5)
        g.shot(out / 'vs-4-p2-stage.png')
        assert 'P2 sets the VS stage to TTT LAW' in g.logtext(), 'player 2 did not step to TTT LAW'
        g.press(LEFT); time.sleep(.3)
        assert 'P1 sets the VS stage to TTT PAUL' in g.logtext(), 'player 1 did not step back to TTT PAUL'
        g.press(CROSS)
        arena = fight_on(g, out, 'vs-5-fight')
        assert "P1 takes TTT PAUL for VS, P2's handicap goes to the game" in g.logtext(), 'no take'
        assert arena == 0 and "STAGE line's TTT stage 0 in arena 0" in g.logtext(), f'not TTT PAUL (arena {arena})'

        def back():                         # player 2 loses every round
            if g.value(SCREEN) == 8 and g.value(PHASE, 2) >= 6: g.write(P2_LIFE, 0, 2)
            return g.value(SCREEN) == 10 and g.vs_state(0) == 3 and g.vs_state(1) == 3
        g.wait(back, 'VS BATTLE SELECT never came back', 240)
        time.sleep(2)
        g.shot(out / 'vs-6-rematch.png')
        before = len(sets())
        g.p2(CROSS); g.p2(CROSS)
        g.wait(lambda: g.vs_state(1) == 12, 'player 2 never got done', 10)
        g.p2(LEFT); time.sleep(.5)
        g.shot(out / 'vs-7-p2-done.png')
        assert g.logtext().count('waits on the STAGE band') == 1 and len(sets()) == before, \
            'the band opened before player 1 chose'
        g.press(CROSS); g.press(CROSS); time.sleep(.5)
        assert 'P1 done last, the handicap waits on the STAGE band' in g.logtext(), 'player 1 done last: no band'
        assert g.vs_state(0) == 4, "player 1's take went to the game"
        g.p2(LEFT); time.sleep(.5)
        assert 'P2 sets the VS game to TEKKEN 3 (T3 PAUL)' in g.logtext(), 'player 2 did not set TEKKEN 3'
        g.p2(DOWN); g.p2(LEFT); g.p2(LEFT); time.sleep(.5)
        g.shot(out / 'vs-8-p2-stage.png')
        assert 'P2 sets the VS stage to T3 DR B' in g.logtext(), 'player 2 did not set T3 DR B'
        g.press(CIRCLE); g.press(CIRCLE); time.sleep(.5)
        g.shot(out / 'vs-9-p1-handicap.png')
        assert "VS, back to P1's handicap" in g.logtext() and g.vs_state(0) == 4, 'player 1 not back to the handicap'
        g.press(CROSS); time.sleep(.5)
        assert g.logtext().count('P1 done last') == 2 and g.vs_state(0) == 4, 'the band did not open again'
        g.p2(CROSS)
        g.q(cmd='press', buttons=NONE, frames=8); time.sleep(.5)
        arena = fight_on(g, out, 'vs-10-fight')
        assert "P2 takes T3 DR B for VS, P1's handicap goes to the game" in g.logtext(), 'no take'
        assert arena == 14, f'not the arena of Dr. B ({arena})'
        assert g.value(MUSIC, 2) == 0x19, f'not the music of Dr. B ({g.value(MUSIC, 2):#x})'
        print('\n'.join(l for l in g.logtext().splitlines() if 'Stage select' in l or 'TTT Stages' in l))
        print('VS: OK')
    finally:
        g.stop()


def practice(args):
    """Practice from a blank card (AUTO): player 1 picks, the dummy's pick
    opens the band on GAME, right twice (TEKKEN 3), cross to its STAGE, right
    (BRYAN), circle back to GAME, cross, left (PAUL), cross: the fight loads
    on arena 0 with Paul's music 0x07 (Xiaoyu's 0x0E without the line), and
    stage-select.txt, beside the card, keeps practice t3-paul."""
    out = Path(args.out).resolve()
    g = Game(Path(args.build).resolve(), out / 'run-practice', Path(args.data), args.aspect == '16:9')
    try:
        to_practice_grid(g)
        g.press(CROSS); time.sleep(1.5); g.shot(out / 'pr-1-band.png')
        g.press(CROSS); time.sleep(.8); g.shot(out / 'pr-2-open.png')
        assert 'waits on the STAGE band' in g.logtext(), 'the dummy pick did not open the band'
        assert g.value(SCREEN) == 9, 'the pick went to the game'
        g.press(RIGHT); g.press(RIGHT); time.sleep(.5); g.shot(out / 'pr-3-game.png')
        g.press(CROSS); g.press(RIGHT); time.sleep(.5); g.shot(out / 'pr-4-bryan.png')
        assert 'P1 sets the Practice stage to T3 BRYAN' in g.logtext(), 'no STAGE step after TEKKEN 3'
        g.press(CIRCLE); time.sleep(.5); g.shot(out / 'pr-5-back.png')
        assert g.value(SCREEN) == 9 and 'back to the grid' not in g.logtext(), 'circle left the band'
        g.press(CROSS); g.press(LEFT); time.sleep(.5); g.shot(out / 'pr-6-paul.png')
        g.press(CROSS)
        g.wait(lambda: g.value(SCREEN) == 8, 'the fight never came', 120)
        g.wait(lambda: g.value(PHASE, 2) >= 6, 'the round never started', 60)
        time.sleep(2); g.shot(out / 'pr-7-fight.png')
        assert g.value(ARENA, 2) == 0, f'not arena 0 ({g.value(ARENA, 2)})'
        assert g.value(MUSIC, 2) == 0x07, f"not Paul's music ({g.value(MUSIC, 2):#x})"
        kept = [f.read_text() for f in g.run.rglob('stage-select.txt')]
        assert kept and 'practice t3-paul' in kept[0], f'the choice was not kept beside the card: {kept}'
        print('\n'.join(l for l in g.logtext().splitlines() if 'Stage select' in l or 'TTT Stages' in l))
        print('practice: OK, kept:', kept[0].replace('\n', ' / '))
    finally:
        g.stop()


def random(args):
    """RANDOM of both games kept for Practice (the user's run, 2026-10-27:
    TTT's school to the deciding Paul's music): the band opens on GAME
    RANDOM, which has no list: cross takes it. The drawn stage's arena and
    its music (the TTT stage's owner's under the TTT piece) both in the
    fight. --seed: the draw."""
    out = Path(args.out).resolve()
    g = Game(Path(args.build).resolve(), out / 'run-random', Path(args.data), args.aspect == '16:9',
             env={'TEKKEN3_STAGE_SELECT': 'vs=default,practice=random', 'TEKKEN3_STAGE_SELECT_SEED': str(args.seed)})
    try:
        to_practice_grid(g)
        g.press(CROSS); time.sleep(1.5)
        g.press(CROSS); time.sleep(.8); g.shot(out / 'rnd-1-game.png')
        g.press(CROSS)
        arena = fight_on(g, out, 'rnd-2-fight')
        fights = [l for l in g.logtext().splitlines() if 'Practice fight on' in l]
        m = re.search(r'arena (\d+), music 0x([0-9A-F]{2}), RANDOM', fights[-1] if fights else '')
        assert m, f'no stage drawn with its music: {fights}'
        music = g.value(MUSIC, 2)
        assert arena == int(m.group(1)) and music == int(m.group(2), 16), \
            f'{fights[-1]}: the fight has arena {arena}, music {music:#x}'
        print(fights[-1], f'/ arena {arena}, music {music:#04x}')
        print('random: OK')
    finally:
        g.stop()


def option(args):
    """GAME OPTION's STAGE SELECT row: Options, GAME OPTION, down to the row
    (ON), right: OFF, kept beside the card (select off). Then a Practice with
    select=off: the dummy's pick goes to the game, no band, Xiaoyu's arena 3
    though practice holds T3 PAUL."""
    out = Path(args.out).resolve()
    g = Game(Path(args.build).resolve(), out / 'run-option', Path(args.data), args.aspect == '16:9')
    try:
        to_menu(g)
        menu_line(g, 0)                                # the menu's lines are built
        base = (g.value(MENU_LINES) & 0xffff) << 16 | g.value(MENU_LINES + 8) & 0xffff
        labels = [g.string(g.value(base + 16 + 8 * i)) for i in range(g.value(base + 4))]
        g.write(LINE, labels.index('OPTION MODE'), 4)
        g.press(CROSS)
        g.wait(lambda: g.value(SCREEN) == 5, 'no Options screen', 30)
        time.sleep(1.5)
        g.press(CROSS); time.sleep(1.5)
        assert g.value(LEVEL, 1) == 1, 'GAME OPTION did not open'
        for _ in range(20):
            if g.option_row()[0] == 'STAGE SELECT': break
            g.tap(DOWN)
        name, value = g.option_row()
        g.shot(out / 'opt-1-row.png')
        assert name == 'STAGE SELECT' and value == 'ON', f'row {name!r} {value!r}'
        g.tap(RIGHT)
        name, value = g.option_row()
        g.shot(out / 'opt-2-off.png')
        kept = [f.read_text() for f in g.run.rglob('stage-select.txt')]
        assert value == 'OFF' and 'STAGE SELECT set to OFF' in g.logtext(), f'row {value!r}'
        assert kept and 'select off' in kept[0], f'not kept beside the card: {kept}'
        print('option row: OK, kept:', kept[0].replace('\n', ' / '))
    finally:
        g.stop()
    g = Game(Path(args.build).resolve(), out / 'run-option-off', Path(args.data), args.aspect == '16:9',
             env={'TEKKEN3_STAGE_SELECT': 'vs=t3-paul,practice=t3-paul,select=off'})
    try:
        to_practice_grid(g)
        g.press(CROSS); time.sleep(1.5)
        g.press(CROSS)
        arena = fight_on(g, out, 'opt-3-fight')
        assert arena == 3, f'not arena 3 ({arena})'
        assert 'STAGE band' not in g.logtext() and 'Practice fight on' not in g.logtext(), 'the line ran'
        print('option off: OK')
    finally:
        g.stop()


def off(args):
    """The feature off (Mods page): no band, the dummy's pick goes to the
    game, Xiaoyu against Xiaoyu on her arena 3, nothing logged."""
    out = Path(args.out).resolve()
    g = Game(Path(args.build).resolve(), out / 'run-off', Path(args.data), args.aspect == '16:9', feature=False,
             env={'TEKKEN3_STAGE_SELECT': 'vs=t3-paul,practice=t3-paul'})
    try:
        to_practice_grid(g)
        g.press(CROSS); time.sleep(1.5); g.shot(out / 'off-1-grid.png')
        g.press(CROSS)
        arena = fight_on(g, out, 'off-2-fight')
        assert arena == 3, f'not arena 3 ({arena})'
        assert 'Stage select' not in g.logtext(), 'the feature ran'
        print('off: OK')
    finally:
        g.stop()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('what', choices=['vs', 'practice', 'random', 'option', 'off'])
    ap.add_argument('out')
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--data', default=str(DATA))
    ap.add_argument('--aspect', default='16:9', choices=['16:9', '4:3'])
    ap.add_argument('--seed', default=7, type=int, help='random: the draw (7: TTT PAUL)')
    args = ap.parse_args()
    {'vs': vs, 'practice': practice, 'random': random, 'option': option, 'off': off}[args.what](args)


if __name__ == '__main__':
    main()
