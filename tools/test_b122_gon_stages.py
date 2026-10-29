#!/usr/bin/env python3
"""B122 (GH#171): Gon, Dr. B, Roger and Alex on TTT's stages, without a player.

    python ressources/slot.py --kind game --who b122 --prio 2 -- \\
        python tools/test_b122_gon_stages.py arcade|practice|vs|team --setting auto|ttt|t3|random
            [--bgm arcade|remixed] [--build build-rel-lite] [--out DIR] [--seed N]

(a PSX_DEBUG_SERVER_LITE build; vs needs player 2 on port 2: a
PSX_DEBUG_TOOLS=ON build, build-dbg. --data: the mods folder of an
install, its stage packs, TTT1 catalogue and music read in place)

A cold start each (stage_check.Game: software renderer x1, headless),
STAGES forced by TEKKEN3_STAGES, the STAGE line of F18 left on DEFAULT. Each
fight prints its "TTT Stages:" decision, the arena the game fights on, the
stage the engine loaded ("arcade stages:") and the music (round music
0x800ADD08, the TTT piece), and checks them against the table of
src/tekken3_stage_source.c (B122: Gon's arena Eddy-A 13 on Eddy's arena 10,
Dr. B's Nina's 9 on her arena 9; a native in AUTO and T3 the PS1 stage;
RANDOM either of the two):

    arcade    the CPU's opponents of stages 2 to 5 written as Gon, Dr. B,
              Roger, Alex (TIPS.md section 17): the arena is the CPU's
    practice  player 1 and the dummy are the fighter of --who (gon, drb, or a
              guest of the Tag page: roger, alex), picked on the grid
    vs        both players the fighter of --who, then a rematch
    team      both teams of one, the fighter of --who
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/arcade_stages'))
import stage_check as sc  # noqa: E402

DATA = Path('C:/TekkenProject/release-1.4.0-test/pc-banc/tekken3-expanded-1.4.0/build-release/mods')
SCREEN, PHASE, MODE, LINE = 0x800ae204, 0x800ae224, 0x800afa88, 0x80097f40
MENU_LINES = 0x800db5d0
ARENA, MUSIC, P2_LIFE, OPPONENTS, STAGE_INDEX = 0x800adc84, 0x800add08, 0x800aaeaa, 0x800afb18, 0x800afaac
FIGHTERS, MUSIC_OPTION = 0x800add5c, 0x80097f05
GRID_FIGHTER, GRID_CELL, TAG_CELLS = 0x80118668, 0x80118650, 0x80118648   # player 1's block of the grid
START, CROSS, CIRCLE, RIGHT, LEFT, UP, DOWN, R2 = 0xfff7, 0xbfff, 0xdfff, 0xffdf, 0xff7f, 0xffef, 0xffbf, 0xfdff
NONE = 0xffff
ARCADE, VS, TEAM, PRACTICE = 0, 1, 2, 5
GUEST_ID = 23
NATIVE = {'gon': 17, 'drb': 19}
# The expectation (B122): the TTT stage and the arena the game loads for it.
HOME = {13: (13, 10), 14: (9, 9)}            # Gon's arena: Eddy-A on Eddy's; Dr. B's: Nina's on hers
DECISION = re.compile(r'TTT Stages: (\w[\w ]*?) fight in arena (\d+), P(\d)\'s (native|guest \w+|-).*?'
                      r'STAGES (\w+) -> (TTT|T3) stage (\d+)')


class Game(sc.Game):
    def __init__(self, build: Path, run: Path, data: Path, setting: str, seed: str, env=None):
        super().__init__(build, run, 'mod', 'software', data / 'arcade-stages',
                         env_extra={'TEKKEN3_TTT_STAGES_DIR': str(data / 'ttt-stages'),
                                    'TEKKEN3_TTT1_ASSETS': str(data / 'ttt1'),
                                    'TEKKEN3_TTT_MUSIC_DIR': str(data / 'ttt-music'),
                                    'TEKKEN3_TTT_PS2_MUSIC_DIR': str(data / 'ttt-ps2-music'),
                                    'TEKKEN3_STAGES': setting, 'TEKKEN3_STAGES_SEED': seed,
                                    'TEKKEN3_STAGE_SELECT': 'vs=default,practice=default',
                                    'TEKKEN3_CPU_GUESTS': '0,0,0', 'TEKKEN3_TEAM_GUESTS': '1,0',
                                    **(env or {})})
        self.catalogue = [l.split()[0] for l in (data / 'ttt1/guests.txt').read_text().splitlines() if l.split()]

    def press(self, buttons, port=1):
        self.q(cmd='press', buttons=buttons, frames=4, **({'port': port} if port != 1 else {}))
        time.sleep(.15)
        self.q(cmd='press', buttons=NONE, frames=2, **({'port': port} if port != 1 else {}))
        time.sleep(.2)

    def logtext(self):
        return self.log.read_text(errors='replace')

    def fighter_id(self, who):
        return NATIVE[who] if who in NATIVE else GUEST_ID + self.catalogue.index(who)


def to_menu(g: Game, bgm: int, pad2=False):
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
    g.write(MUSIC_OPTION, bgm)                         # BGM SELECT: 0 REMIXED, 1 ARCADE
    time.sleep(.5)


def to_mode(g: Game, mode: int, screen: int):
    for _ in range(50):
        base = (g.value(MENU_LINES) & 0xffff) << 16 | g.value(MENU_LINES + 8) & 0xffff
        count = g.value(base + 4) if base >> 24 in (0x80, 0x9f) else 0
        if 0 < count < 16: break
        time.sleep(.1)
    line = next(i for i in range(count) if g.value(base + 16 + 8 * i + 4, 2) in (mode, mode | 0x100))
    g.write(LINE, line, 4)
    g.press(CROSS)
    g.wait(lambda: g.value(SCREEN) == screen and g.value(MODE) == mode, f'the selector of mode {mode} never came', 30)
    if screen == 9: g.write(0x8011863c, 0x10ff, 2)     # the grid's timer up (Arcade's overlay)
    time.sleep(2)


def pick(g: Game, who: str):
    """Player 1's cursor of the grid to `who`: a native along the stock page
    (Right), a guest on the Tag page (R2); not confirmed."""
    want = g.fighter_id(who)
    if who in NATIVE:
        for i in range(40):                            # two rows of 11 (Right wraps in its row)
            if g.value(GRID_FIGHTER, 2) == want: return
            g.press(DOWN if i == 11 else RIGHT)
    else:
        if g.value(TAG_CELLS) != len(g.catalogue):
            g.press(R2)
            g.wait(lambda: g.value(TAG_CELLS) == len(g.catalogue), 'R2 did not open the Tag page', 10)
            time.sleep(1.5)
        cell = g.catalogue.index(who)
        place = lambda c: divmod(c, 8) if c < 16 else (c - 16, 8)
        for _ in range(40):
            if g.value(GRID_FIGHTER, 2) == want: return
            here = g.value(GRID_CELL)
            if here >= len(g.catalogue): time.sleep(.2); continue
            (r, c), (R, C) = place(here), place(cell)
            g.press(DOWN if r < R else UP if r > R else RIGHT if c < C else LEFT)
    raise AssertionError(f'the cursor never reached {who} ({g.value(GRID_FIGHTER, 2)})')


def expected(setting: str, arena: int, guest: bool, true_ogre: bool):
    """The stage sources allowed for the fight decided in arena 13 or 14;
    True Ogre fighting: Unknown's TTT 14 (on Ogre's arena 6) in TTT, either
    in RANDOM, the PS1 stage in AUTO and T3."""
    stage, load = (14, 6) if true_ogre else HOME[arena]
    ttt, t3 = ('TTT', stage, load), ('T3', arena, arena)
    return {'ttt': [ttt], 't3': [t3], 'random': [ttt, t3],
            'auto': [ttt] if guest and not true_ogre else [t3]}[setting]


def fight(g: Game, seen: int, label: str, setting: str, out: Path, results: list):
    """The next decision of the log and the fight it loads; checked."""
    g.wait(lambda: len(DECISION.findall(g.logtext())) > seen, f'{label}: no decision', 180)
    g.wait(lambda: g.value(SCREEN) == 8 and g.value(PHASE, 2) >= 6, f'{label}: the round never started', 180)
    time.sleep(2.5)
    log = g.logtext()
    decisions = DECISION.findall(log)
    line = [l for l in log.splitlines() if l.startswith('TTT Stages:') and 'fight in arena' in l][-1]
    mode, arena, player, who, s, source, number = decisions[-1]
    arena, number = int(arena), int(number)
    fought, music = g.value(ARENA, 2), g.value(MUSIC, 2)
    after = log[log.rindex(line):]                     # what this fight loaded and played
    loads = re.findall(r'arcade stages: (TTT )?stage (\d+) loaded', after)
    loaded = f'{"TTT" if loads[-1][0] else "T3"} {loads[-1][1]}' if loads else 'PS1 (no pack)'
    # The engine keeps a pack loaded for the next fight on the same stage.
    if not loads and getattr(g, 'last', None) == (source, number) and g.last_loaded != 'PS1 (no pack)':
        loaded = g.last_loaded + ' (kept)'
    g.last, g.last_loaded = (source, number), loaded.replace(' (kept)', '')
    pieces = re.findall(r'TTT music: TTT stage (\d+),', after)
    if not pieces and source == 'TTT' and getattr(g, 'piece', None) == str(number): pieces = [g.piece]   # still playing
    g.piece = pieces[-1] if pieces else None
    g.q(cmd='screenshot', path=str(out / f'{label}.png'))
    ok = True
    if arena in HOME:
        guest = who.startswith('guest')
        allowed = expected(setting, arena, guest, 'True Ogre fights' in line)
        got = (source, number, fought)
        ok = got in allowed
        if source == 'T3': ok = ok and loaded.startswith('PS1')
        else: ok = ok and loaded.startswith(f'TTT {number}') and bool(pieces) and int(pieces[-1]) == number
    elif source == 'TTT':                              # any other arena: the stage decided is the one drawn (B118)
        ok = fought == arena and loaded.startswith(f'TTT {number}')
    results.append((label, ok))
    print(f'{label}: {line.strip()}', flush=True)
    print(f'    fought on arena {fought}, engine {loaded}, round music {music:#04x}, '
          f'TTT piece of stage {pieces[-1] if pieces else "-"}  => {"OK" if ok else "WRONG"}', flush=True)
    return len(decisions)


def win(g: Game):
    """Player 2 loses every round of the fight on screen."""
    if g.value(SCREEN) == 8 and g.value(PHASE, 2) >= 6 and g.value(P2_LIFE, 2): g.write(P2_LIFE, 0, 2)


def arcade(a, g: Game, out: Path, results: list):
    to_menu(g, a.bgm)
    to_mode(g, ARCADE, 9)
    g.press(CROSS)
    seen = fight(g, 0, 'arcade-1-xiaoyu', a.setting, out, results)
    cast = ['gon', 'drb', 'roger', 'alex']
    for i, who in enumerate(cast):                     # stages 2..5 (TIPS.md section 17)
        g.write(OPPONENTS + 4 * (i + 1), g.fighter_id(who)); g.write(OPPONENTS + 4 * (i + 1) + 1, 0)
    for i, who in enumerate(cast):
        def next_fight(stage=i + 1):
            win(g)
            if g.value(SCREEN) in (12, 16, 17): g.press(START)
            return g.value(STAGE_INDEX) == stage and g.value(SCREEN) in (11, 8)
        g.wait(next_fight, f'stage {i + 2} never came', 240)
        assert g.value(FIGHTERS + 2, 2) == g.fighter_id(who) or g.value(SCREEN) == 11, 'another opponent'
        seen = fight(g, seen, f'arcade-{i + 2}-{who}', a.setting, out, results)
        assert g.value(FIGHTERS + 2, 2) == g.fighter_id(who), f'the CPU is {g.value(FIGHTERS + 2, 2)}, not {who}'


def practice(a, g: Game, out: Path, results: list):
    to_menu(g, a.bgm)
    to_mode(g, PRACTICE, 9)
    pick(g, a.who); g.press(CROSS); time.sleep(1.5)
    pick(g, a.who); g.press(CROSS); time.sleep(1)
    if 'waits on the STAGE band' in g.logtext(): g.press(CROSS)     # F18's band: GAME AUTO, DEFAULT
    fight(g, 0, f'practice-{a.who}', a.setting, out, results)
    ids = g.value(FIGHTERS, 2), g.value(FIGHTERS + 2, 2)
    assert ids == (g.fighter_id(a.who),) * 2, f'fighters {ids}'


RECORDS = 0x80097d40                              # fighter records: ID * 4 + costume -> record, byte 10 the arena


def team(a, g: Game, out: Path, results: list):
    """Team Battle, player 1 against the CPU, both teams drawn by Start
    (random fill), player 1 wins every fight. --who gon / drb: every
    fighter record given Gon's arena 13 / Dr. B's 14, so that whoever
    decides (natives, and guests through their model fighter's record:
    Roger, Alex) decides in that arena; --who b118: the records untouched,
    the CPU's first member made a guest by the mod (TEKKEN3_TEAM_GUESTS
    1,1): the stage decided must be the one drawn."""
    to_menu(g, a.bgm)
    to_mode(g, TEAM, 10)
    g.press(CROSS); time.sleep(.8)
    if a.who in NATIVE:
        records = g.read(RECORDS, 4 * 92)
        for i in range(92):
            ptr = int.from_bytes(records[4 * i:4 * i + 4], 'little')
            if 0x80010000 <= ptr < 0x80200000: g.write(ptr + 10, {'gon': 13, 'drb': 14}[a.who])
    for _ in range(6):
        if g.value(SCREEN) != 10: break
        g.press(START); time.sleep(.8)                 # the teams are drawn
    seen = 0
    for i in range(a.fights):
        seen = fight(g, seen, f'team-{i + 1}', a.setting, out, results)
        g.wait(lambda: (win(g), g.value(SCREEN) == 11 or g.value(SCREEN) not in (8, 11))[1], 'no next fight', 240)
        if g.value(SCREEN) != 11: break
    print('\n'.join(l for l in g.logtext().splitlines() if 'joins' in l))


VS_BLOCKS, VS_STRIDE = 0x800b8d70, 172           # +0 state (3 choosing, 12 done), +8 column, +0xC row
VS_CELLS = {'gon': [(2, 3)], 'drb': [(2, 1)],                         # VS BATTLE SELECT's grid
            'roger': [(1, 4)], 'alex': [(1, 5)]}                          # the Tag page: catalogue 12, 13


def vs(a, g: Game, out: Path, results: list):
    """VS: both players the same fighter, match after match, those of --who
    (gon,drb); player 2 loses every round. When both players change
    fighters, Tekken 3 keeps the previous match's arena (0x8004F3B0, mode 1):
    check a fighter on its first match. Roger and Alex (R2, the Tag page,
    its cells not mapped here) are covered by practice."""
    to_menu(g, a.bgm, pad2=True)
    to_mode(g, VS, 10)
    seen, tag = 0, False
    for who in a.who.split(','):
        want = g.fighter_id(who)
        for r, c in VS_CELLS[who]:
            g.wait(lambda: g.value(VS_BLOCKS) == 3 and g.value(VS_BLOCKS + VS_STRIDE) == 3, 'no selector', 240)
            time.sleep(1.5)
            if who not in NATIVE and not tag:
                g.press(R2); time.sleep(1.5); tag = True
            for p in (0, 1):
                blk = VS_BLOCKS + p * VS_STRIDE
                for _ in range(12):
                    if g.value(blk + 0xc, 2) == r: break
                    g.press(DOWN if g.value(blk + 0xc, 2) < r else UP, port=p + 1)
                for _ in range(12):
                    if g.value(blk + 8, 2) == c: break
                    g.press(RIGHT, port=p + 1)
            for _ in range(8):
                if g.value(VS_BLOCKS) == 12 and g.value(VS_BLOCKS + VS_STRIDE) == 12: break
                if g.value(VS_BLOCKS) != 12: g.press(CROSS)
                if g.value(VS_BLOCKS + VS_STRIDE) != 12: g.press(CROSS, port=2)
                time.sleep(.3)
            g.wait(lambda: g.value(SCREEN) in (11, 8), f'{who}: no loading', 60)
            time.sleep(.5)
            if g.value(FIGHTERS, 2) == want: break
            print(f'    cell {(r, c)} is fighter {g.value(FIGHTERS, 2)}, not {who}', flush=True)
            g.wait(lambda: (win(g), g.value(SCREEN) == 10 and g.value(VS_BLOCKS) == 3)[1], 'no rematch', 240)
            seen = len(DECISION.findall(g.logtext()))
        seen = fight(g, seen, f'vs-{who}', a.setting, out, results)
        ids = g.value(FIGHTERS, 2), g.value(FIGHTERS + 2, 2)
        assert ids == (want, want), f'fighters {ids}, not {who}'
        g.wait(lambda: (win(g), g.value(SCREEN) == 10 and g.value(VS_BLOCKS) == 3)[1], 'no rematch', 240)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('case', choices=['arcade', 'practice', 'vs', 'team'])
    ap.add_argument('--setting', default='ttt', choices=['auto', 'ttt', 't3', 'random'])
    ap.add_argument('--who', default='gon', help='practice, vs, team: gon, drb, roger, alex')
    ap.add_argument('--bgm', default='arcade', choices=['arcade', 'remixed'])
    ap.add_argument('--build', default=str(ROOT / 'build-rel-lite'))
    ap.add_argument('--data', default=str(DATA))
    ap.add_argument('--seed', default='1')
    ap.add_argument('--fights', type=int, default=4, help='team: fights checked')
    ap.add_argument('--out', default=str(ROOT / 'workspace/b122'))
    a = ap.parse_args()
    a.bgm = {'remixed': 0, 'arcade': 1}[a.bgm]
    tag = f'{a.case}-{a.setting}' + ('' if a.case == 'arcade' else f'-{a.who.replace(",", "-")}')
    out = Path(a.out).resolve() / tag
    out.mkdir(parents=True, exist_ok=True)
    env = {'TEKKEN3_TEAM_GUESTS': '1,1'} if a.who == 'b118' else {'TEKKEN3_TEAM_GUESTS': '2,4'} if a.case == 'team' else {}
    g = Game(Path(a.build).resolve(), out / 'run', Path(a.data), a.setting, a.seed, env)
    results: list = []
    try:
        {'arcade': arcade, 'practice': practice, 'vs': vs, 'team': team}[a.case](a, g, out, results)
    finally:
        g.stop()
    bad = [l for l, ok in results if not ok]
    print(f'{tag}: {len(results) - len(bad)}/{len(results)} OK' + (f', wrong: {" ".join(bad)}' if bad else ''))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
