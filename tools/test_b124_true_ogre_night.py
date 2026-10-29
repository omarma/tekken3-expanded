#!/usr/bin/env python3
"""B124 (GH#172): True Ogre's fights on TTT's stages at night, without a player.

    python ressources/slot.py --kind game --who b124 --prio 2 -- \\
        python tools/test_b124_true_ogre_night.py arcade|arcade-p1|practice|vs|team --setting auto|ttt|t3|random
            [--build build-rel-lite] [--out DIR] [--seed N] [--line ttt-6]

(a PSX_DEBUG_SERVER_LITE build; vs needs player 2 on port 2: a
PSX_DEBUG_TOOLS=ON build, build-dbg. --data: the mods folder of an
install, its stage packs, TTT1 catalogue and music read in place)

True Ogre (ID 20) on either side makes the fight Tekken 3's dark arena
(0x800AFAA0, 0x80050F5C). Each fight prints its "TTT Stages:" decision, the
dark arena byte, the stage the engine loaded, whether it drew it at night
("arcade stages: TTT stage n at night") and the TTT piece, and checks them
against src/tekken3_stage_source.c (B124: the usual rules, a TTT stage at
night, Tekken 3's the PS1 dark arena; but True Ogre as Arcade's CPU, the
boss, 1.4.0's rule: TTT's stage 14, Unknown's, as it is, in TTT, T3 or 14 in
RANDOM, T3 in AUTO and T3; before, that rule for every True Ogre):

    arcade    the CPU's opponents of stages 2 and 3 written as True Ogre (the
              boss's rule), stage 4 as Kazuya (a guest in AUTO: his TTT stage,
              by day); the first fight (Xiaoyu's CPU) is lit
    arcade-p1 player 1 True Ogre (at night), the CPU's opponent of stage 2
              written as Kazuya, of stage 3 as True Ogre (the boss's rule)
    practice  player 1 and the dummy True Ogre, picked on the grid; --line
              sets F18's STAGE line (vs=, practice= of TEKKEN3_STAGE_SELECT)
    vs        both players True Ogre, then a rematch
    team      teams of one drawn by Start, the CPU's second member written as
              True Ogre (0x800AFAEE + 1, ID * 4)
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import test_b122_gon_stages as b122  # noqa: E402

TRUE_OGRE, DARK_ARENA, CPU_TEAM, HUMAN = 20, 0x800afaa0, 0x800afaee, 0x800ae1f8
OGRE_ARENA = 6
DECISION = b122.DECISION
FIGHTS = re.compile(r"TTT Stages: \w[\w ]*? fight[ ,]")    # every decision, the STAGE line's too
NIGHT = re.compile(r'arcade stages: TTT stage (\d+) at night')


def expected(setting: str, true_ogre: bool, guest: bool, arena: int, line: str | None, boss: bool):
    """The sources allowed: (source, stage, night); the arena the fight's."""
    t3 = [('T3', arena, False)]
    if boss:                                            # True Ogre as Arcade's CPU: 1.4.0's rule
        return {'ttt': [('TTT', 14, False)], 'random': [('TTT', 14, False)] + t3, 'auto': t3, 't3': t3}[setting]
    if line:                                            # F18's line: its stage, at night with True Ogre
        return [('TTT', int(line.split('-')[1]), true_ogre)]
    stages = (10, 13) if arena == 10 else (b122.HOME[arena][0],) if arena in b122.HOME else (arena,)   # B122: 13, 14
    ttt = [('TTT', s, true_ogre) for s in stages]
    return {'ttt': ttt, 't3': t3, 'random': ttt + t3, 'auto': ttt if guest else t3}[setting]


def fight(g: b122.Game, seen: int, label: str, a, out: Path, results: list):
    g.wait(lambda: len(FIGHTS.findall(g.logtext())) > seen, f'{label}: no decision', 180)
    g.wait(lambda: g.value(b122.SCREEN) == 8 and g.value(b122.PHASE, 2) >= 6, f'{label}: the round never started', 180)
    time.sleep(2.5)
    log = g.logtext()
    count = len(FIGHTS.findall(log))
    line = [l for l in log.splitlines() if l.startswith('TTT Stages:') and ' fight' in l][-1]
    after = log[log.rindex(line):]
    dark = g.value(DARK_ARENA, 1)
    ids = g.value(b122.FIGHTERS, 2), g.value(b122.FIGHTERS + 2, 2)
    true_ogre = TRUE_OGRE in ids
    boss = g.value(b122.MODE) == b122.ARCADE and any(ids[p] == TRUE_OGRE and not g.value(HUMAN + 2 * p, 2) for p in (0, 1))
    chosen = re.search(r"the STAGE line's (TTT|T3) stage (\d+) in arena (\d+)", line)
    if chosen:
        source, number, arena, who = chosen.group(1), int(chosen.group(2)), int(chosen.group(3)), 'line'
    else:
        mode, arena, player, who, s, source, number = DECISION.search(line).groups()
        arena, number = int(arena), int(number)
    loads = re.findall(r'arcade stages: (TTT )?stage (\d+) loaded', after)
    loaded = f'{"TTT" if loads[-1][0] else "T3"} {loads[-1][1]}' if loads else None
    if loaded is None and getattr(g, 'last', None) == (source, number): loaded = g.last_loaded
    loaded = loaded or 'PS1 (no pack)'
    g.last, g.last_loaded = (source, number), loaded
    night = NIGHT.findall(after)
    pieces = re.findall(r'TTT music: TTT stage (\d+),', after)
    if not pieces and source == 'TTT' and getattr(g, 'piece', None) == str(number): pieces = [g.piece]
    g.piece = pieces[-1] if pieces else None
    g.q(cmd='screenshot', path=str(out / f'{label}.png'))
    allowed = expected(a.setting, true_ogre, who.startswith('guest'), arena, a.line, boss)
    got = (source, number, bool(night))
    ok = got in allowed and bool(dark) == true_ogre
    if source == 'T3': ok = ok and (loaded.startswith('PS1') if dark else True)
    else: ok = ok and loaded.startswith(f'TTT {number}') and bool(pieces) and int(pieces[-1]) == number
    results.append((label, ok))
    print(f'{label}: {line.strip()}', flush=True)
    print(f'    fighters {ids}{" (boss)" if boss else ""}, dark arena {dark}, engine {loaded}, at night {night[-1] if night else "-"}, '
          f'TTT piece {pieces[-1] if pieces else "-"}  => {"OK" if ok else "WRONG"} (allowed {allowed})', flush=True)
    return count


def arcade(a, g, out, results):
    b122.to_menu(g, 1)
    b122.to_mode(g, b122.ARCADE, 9)
    g.press(b122.CROSS)
    seen = fight(g, 0, 'arcade-1-lit', a, out, results)
    kazuya = g.fighter_id('kazuya')
    cast = [TRUE_OGRE, TRUE_OGRE, kazuya]
    for i, who in enumerate(cast):                     # stages 2..4 (TIPS.md section 17)
        g.write(b122.OPPONENTS + 4 * (i + 1), who); g.write(b122.OPPONENTS + 4 * (i + 1) + 1, 0)
    for i, who in enumerate(cast):
        def next_fight(stage=i + 1):
            b122.win(g)
            if g.value(b122.SCREEN) in (12, 16, 17): g.press(b122.START)
            return g.value(b122.STAGE_INDEX) == stage and g.value(b122.SCREEN) in (11, 8)
        g.wait(next_fight, f'stage {i + 2} never came', 240)
        seen = fight(g, seen, f'arcade-{i + 2}-{"true-ogre" if who == TRUE_OGRE else "kazuya"}', a, out, results)


def arcade_p1(a, g, out, results):
    b122.NATIVE['trueogre'] = TRUE_OGRE
    b122.to_menu(g, 1)
    b122.to_mode(g, b122.ARCADE, 9)
    b122.pick(g, 'trueogre'); g.press(b122.CROSS)
    seen = fight(g, 0, 'arcade-p1-1', a, out, results)
    cast = [g.fighter_id('kazuya'), TRUE_OGRE]
    for i, who in enumerate(cast):                     # stages 2, 3
        g.write(b122.OPPONENTS + 4 * (i + 1), who); g.write(b122.OPPONENTS + 4 * (i + 1) + 1, 0)
    for i, who in enumerate(cast):
        def next_fight(stage=i + 1):
            b122.win(g)
            if g.value(b122.SCREEN) in (12, 16, 17): g.press(b122.START)
            return g.value(b122.STAGE_INDEX) == stage and g.value(b122.SCREEN) in (11, 8)
        g.wait(next_fight, f'stage {i + 2} never came', 240)
        seen = fight(g, seen, f'arcade-p1-{i + 2}-{"true-ogre" if who == TRUE_OGRE else "kazuya"}', a, out, results)


def practice(a, g, out, results):
    b122.NATIVE['trueogre'] = TRUE_OGRE
    b122.to_menu(g, 1)
    b122.to_mode(g, b122.PRACTICE, 9)
    b122.pick(g, 'trueogre'); g.press(b122.CROSS); time.sleep(1.5)
    b122.pick(g, 'trueogre'); g.press(b122.CROSS); time.sleep(1)
    if 'waits on the STAGE band' in g.logtext(): g.press(b122.CROSS)
    fight(g, 0, 'practice-true-ogre', a, out, results)


def vs(a, g, out, results):
    b122.NATIVE['trueogre'] = TRUE_OGRE
    a.who = 'trueogre'
    b122.VS_CELLS['trueogre'] = [(0, 5)]               # grid_cells (t3-ps1 rodata_80022768.c): 0x50 = 20 * 4
    b122.vs(a, g, out, results)


def team(a, g, out, results):
    b122.to_menu(g, 1)
    b122.to_mode(g, b122.TEAM, 10)
    g.press(b122.CROSS); time.sleep(.8)
    for _ in range(6):
        if g.value(b122.SCREEN) != 10: break
        g.press(b122.START); time.sleep(.8)
    g.wait(lambda: g.value(b122.SCREEN) in (11, 8), 'no first fight', 60)
    g.write(CPU_TEAM + 1, TRUE_OGRE * 4)              # the CPU's second member
    seen = 0
    for i in range(3):
        seen = fight(g, seen, f'team-{i + 1}', a, out, results)
        g.wait(lambda: (b122.win(g), g.value(b122.SCREEN) == 11 or g.value(b122.SCREEN) not in (8, 11))[1],
               'no next fight', 240)
        if g.value(b122.SCREEN) != 11: break


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('case', choices=['arcade', 'arcade-p1', 'practice', 'vs', 'team'])
    ap.add_argument('--setting', default='ttt', choices=['auto', 'ttt', 't3', 'random'])
    ap.add_argument('--line', help="practice, vs: F18's STAGE line, ttt-N (default DEFAULT)")
    ap.add_argument('--build', default=str(ROOT / 'build-rel-lite'))
    ap.add_argument('--data', default=str(b122.DATA))
    ap.add_argument('--seed', default='1')
    ap.add_argument('--out', default=str(ROOT / 'workspace/b124'))
    a = ap.parse_args()
    a.bgm = 1
    tag = f'{a.case}-{a.setting}' + (f'-line-{a.line}' if a.line else '')
    out = Path(a.out).resolve() / tag
    out.mkdir(parents=True, exist_ok=True)
    env = {'TEKKEN3_TEAM_GUESTS': '0,0'} if a.case == 'team' else {}
    if a.line: env['TEKKEN3_STAGE_SELECT'] = f'vs={a.line},practice={a.line}'
    g = b122.Game(Path(a.build).resolve(), out / 'run', Path(a.data), a.setting, a.seed, env)
    b122.DECISION = FIGHTS
    b122.fight = lambda g_, seen, label, setting, out_, res: fight(g_, seen, label, a, out_, res)   # vs()
    results: list = []
    try:
        {'arcade': arcade, 'arcade-p1': arcade_p1, 'practice': practice, 'vs': vs, 'team': team}[a.case](a, g, out, results)
    finally:
        g.stop()
    bad = [l for l, ok in results if not ok]
    print(f'{tag}: {len(results) - len(bad)}/{len(results)} OK' + (f', wrong: {" ".join(bad)}' if bad else ''))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
