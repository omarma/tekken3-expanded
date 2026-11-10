#!/usr/bin/env python3
"""F32 E5: the natives on their TTT1 models wherever the game shows them, not only in a fight.

    python tools/test_f32_e5.py --case embu [--variant 0|1|2] [--off] [--hq]
    python tools/test_f32_e5.py --case cine --cine armorking [--off] [--hq]

embu: the attract's Embu (state 6) from the modes menu without input, the
game's own variant (the guests' casting emptied: TEKKEN3_EMBU_CAST=none),
every native with a TTT1 model on it (TEKKEN3_TTT1_NATIVE_MODELS=all). Each
scene's graft is read from the game's log ("TTT1 Embu: P1 <Name> (TTT1
model) on <key>'s model"), screenshots every 2 s. --off: TEKKEN3_F32_E5=0,
the natives on their PS1 models (the before).

cine: a TTT ending or the TTT Embu played by the engine with its own scene
from the modes menu (TEKKEN3_CINE_SCENE_TEST=<key>.cine@4:30, one Start at the title:
another one in the scene's demo mode leaves it), its natives
(King beside Armor King, Hwoarang beside Baek...) grafted with their TTT1
models; shots every 2 s of the scene.

Headless, software x1, without the user's pad (test_f32_native_models.Game);
--hq: OpenGL x4, anti-aliased, for the user. The catalogue (--assets) needs
ttt-cinematics beside it (tools/ttt_cinematics.py --out) for cine.
"""
import argparse, os, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_f32_native_models as F
import test_devil_jin as T

WORK = F.WORK
VARIANT = 0x80097f20          # the Embu's variant (save), copied to 0x800DD810 as state 6 loads it
TIER = 0x80097f1f             # unlock tier (+0x2F): 2 for variant 2
EMBU_LINE = re.compile(r'TTT1 Embu: P(\d) (.+?) on (\S+)\'s model')


STEP = 120                    # frames between shots: the same game frames before / after (--off)

# F32 E6 (main's options): cpu_ttt1, the natives on their TTT1 moves (mode 4: the CPU's draw,
# TEKKEN3_CPU_MOVESET=ttt1, or every native, TEKKEN3_NATIVE_MOVES=1, where a case had them on
# Tekken 3's); default, the game without TEKKEN3_TTT1_NATIVE_MODELS (the natives' TTT1 models are
# the default with the import); no_import, a catalogue with nothing in it (no TTT1 import: the
# original game, nothing grafted); env, more variables (TEKKEN3_F32_E6=0 for the before).
E6 = {'cpu_ttt1': False, 'default': False, 'no_import': None, 'env': {}, 'tag': '', 'hq': False}


def game(build, tag, env, hq=False):
    env = dict(env)
    if E6['cpu_ttt1']:
        if 'TEKKEN3_NATIVE_MOVES' in env: env['TEKKEN3_NATIVE_MOVES'] = '1'
        if 'TEKKEN3_CPU_MOVESET' in env: env['TEKKEN3_CPU_MOVESET'] = 'ttt1'
    if E6['default'] or E6['no_import']: env.pop('TEKKEN3_TTT1_NATIVE_MODELS', None)
    if E6['no_import']: env['TEKKEN3_TTT1_ASSETS'] = str(E6['no_import'])
    env.update(E6['env'])
    return F.Game(build, tag + E6['tag'], env, hq)


def shots_by_frame(g, hq, seconds, going):
    """A shot every STEP game frames from now (the debug server's frame counter), so that two runs
    (--off and not) show the same frames of a scripted scene, whatever the host's speed."""
    f0, n = g.q(cmd='frame')['frame'], 0
    while going() and n * STEP < seconds * 60:
        if g.q(cmd='frame')['frame'] - f0 >= n * STEP:
            try: F.shot(g, f'{n:02d}', hq)
            except RuntimeError as e: print(f'  shot {n}: {e.args[0][1].get("error")}', flush=True)  # a movie's 24 bpp
            n += 1; g.halted()
        time.sleep(.005)
    return n


def embu(build, assets, variant, off, hq, seconds):
    env = {'TEKKEN3_TTT1_ASSETS': str(assets), 'TEKKEN3_TTT1_NATIVE_MODELS': 'all', 'TEKKEN3_EMBU_CAST': 'none=none'}
    if off: env['TEKKEN3_F32_E5'] = '0'
    tag = f'e5-embu-v{variant}{"-off" if off else ""}{"-hq" if hq else ""}'
    g = game(build, tag, env, hq)
    try:
        g.q(cmd='turbo', enabled=1)
        g.wait(lambda: g.value(T.STATE) == 4, 'modes menu not reached', 180, lambda: g.press(T.START))
        g.q(cmd='turbo', enabled=0)
        # The variant and its tier, held until the Embu's file is chosen (state 2 loads 0x45 + variant).
        g.write(TIER, max(g.value(TIER, 1), 2 if variant == 2 else 1), 1)
        g.wait(lambda: (g.write(VARIANT, variant, 1), g.value(T.STATE) == 6)[1], 'Embu (state 6) not reached', 400)
        print(f'  Embu: variant {g.value(0x800dd810, 1)}', flush=True)
        n = shots_by_frame(g, hq, seconds, lambda: g.value(T.STATE) == 6)
        lines = EMBU_LINE.findall(g.log())
        fatal = [l for l in g.log().splitlines() if l.startswith('FATAL')]
        return lines, fatal, n
    finally:
        g.stop()


def cine(build, assets, key, off, hq, seconds):
    cine_file = assets.parent / 'ttt-cinematics' / f'{key}.cine'
    if not cine_file.is_file(): sys.exit(f'{cine_file} missing (tools/ttt_cinematics.py --out)')
    env = {'TEKKEN3_TTT1_ASSETS': str(assets), 'TEKKEN3_TTT1_NATIVE_MODELS': 'all',
           'TEKKEN3_CINE_SCENE_TEST': f'{cine_file}@4:30'}
    if off: env['TEKKEN3_F32_E5'] = '0'
    tag = f'e5-cine-{key}{"-off" if off else ""}{"-hq" if hq else ""}'
    g = game(build, tag, env, hq)
    try:
        g.q(cmd='turbo', enabled=1)
        g.wait(lambda: g.value(T.STATE) == 3, 'title not reached', 180)
        g.q(cmd='turbo', enabled=0); time.sleep(1)
        for _ in range(10):
            g.press(T.START); time.sleep(2)
            if g.value(T.STATE) != 3: break
        g.wait(lambda: g.value(T.STATE) == 8 and g.value(T.PHASE, 2) >= 6, 'the scene did not load', 240)
        n = shots_by_frame(g, hq, seconds, lambda: True)
        log = g.log().splitlines()
        lines = [l for l in log if 'TTT1 model' in l or l.startswith('Cine: actor') or 'Native-TTT1' in l]
        fatal = [l for l in log if l.startswith('FATAL')]
        return lines, fatal, n
    finally:
        g.stop()


LINE, LIFE = 0x80097f40, {0: 0x800a961c, 1: 0x800aaea8}     # modes menu line; actor +0x3F4 (life: high half)
CPU_FIGHTER, CPU_COSTUME, STAGE_INDEX = 0x800add5e, 0x800add9a, 0x800afaac
NAMES = {0: 'Paul', 1: 'Law', 2: 'Lei', 3: 'King', 4: 'Yoshimitsu', 5: 'Nina', 6: 'Hwoarang', 7: 'Xiaoyu', 8: 'Eddy',
         9: 'Jin', 10: 'Julia', 11: 'Kuma', 12: 'Bryan', 13: 'Heihachi', 14: 'Ogre', 15: 'Mokujin', 16: 'Gunjack',
         18: 'Anna', 20: 'Trueogre'}
GRAFT = re.compile(r"^(\w+) \(TTT1 model\) model: P(\d) (?:model header replaced|shares P\d's grafted header)", re.M)


def boot_menu(g, pad2=False):
    """Cold start to the modes menu (state 4): Start only on the title (one too many in a
    menu picks its line). Tekken Ball and Theater unlocked (0x80097F26 / 27)."""
    g.write(0x80097f26, 3, 1); g.write(0x80097f27, 3, 1)
    g.q(cmd='turbo', enabled=1)
    end = time.monotonic() + 180
    while g.value(T.STATE) != 4:
        if time.monotonic() > end: raise AssertionError('modes menu not reached')
        if g.value(T.STATE) in (1, 3):
            # VS needs pad 2 plugged in at the title (tools/test_b122_gon_stages.py)
            if pad2: g.q(cmd='set_input', buttons='ffff', port=2)
            g.press(T.START)
        time.sleep(.3)
    # The menu's own clock ran in turbo: straight on, or it goes back to the attract.
    g.q(cmd='turbo', enabled=0)


def grafts(g, mark):
    """Each side's native drawn by its TTT1 model since log offset `mark`: {player: name}."""
    return {int(p) - 1: name for name, p in GRAFT.findall(g.log()[mark:])}


def ko(g, p):
    life = g.value(LIFE[p])
    if life >> 16: g.write(LIFE[p], life & 0xffff)


def fighters(g):
    return tuple(T.actor(g, p)[2] for p in (0, 1))


def check_fight(g, mark, report, label):
    """The fight that just started: each side whose actor is a native with a TTT1 model must
    have been grafted with its own files since `mark`."""
    try: g.wait(lambda: g.value(T.STATE) == 8 and g.value(T.PHASE, 2) >= 6, f'{label}: no fight', 240)
    except AssertionError:
        F.shot(g, f'{label}-stuck', False)
        print(f'  {label}: stuck in state {g.value(T.STATE)} phase {g.value(T.PHASE, 2)} mode {g.value(T.MODE, 1)}, '
              f'blocks {[g.value(GRID + p * GRID_STRIDE + o) for p in (0, 1) for o in (0, 44, 56)]}', flush=True)
        raise
    time.sleep(1.5)
    ids, got = fighters(g), grafts(g, mark)
    F.shot(g, label, E6['hq'])                      # E6: --hq for the before / after sheets
    # E6 --no-import: the original game, no side grafted.
    ok = not got if E6['no_import'] else all(NAMES.get(ids[p]) is None or got.get(p) == NAMES[ids[p]] for p in (0, 1))
    report.append((label, ids, [T.actor(g, p)[0] & 3 for p in (0, 1)], got, ok))
    print(f'  {label}: actors {ids} costumes {report[-1][2]} grafted {got} {"OK" if ok else "FAIL"}', flush=True)
    return ok


def arcade(build, assets, p1=9, opponent=(0, 1), off=False, hq=False):
    """Arcade: player 1 on a native (square, T3 moves), the CPU's first opponent a native, counted
    as stage 9 (0x800AFAAC); then Ogre, his cutscene (Heihachi in player 1's actor), True Ogre."""
    # The CPU's natives on their Tekken 3 moves: on TTT1 moves (mode 4) a native keeps its PS1 model (E6).
    env = {'TEKKEN3_TTT1_ASSETS': str(assets), 'TEKKEN3_TTT1_NATIVE_MODELS': 'all', 'TEKKEN3_CPU_MOVESET': 'original'}
    if off: env['TEKKEN3_F32_E5'] = '0'
    g = game(build, f'e5-arcade{"-off" if off else ""}{"-hq" if hq else ""}', env, hq)
    report, cut = [], []
    try:
        boot_menu(g)
        g.write(LINE, 0, 1); g.press(T.CROSS)
        g.wait(lambda: g.value(T.STATE) == 9 and g.value(0x80118648) == 21, 'Arcade selector not reached', 60)
        time.sleep(1.5)
        T.cursor_to(g, p1)
        mark = len(g.log())
        g.press(T.SQUARE, frames=5); time.sleep(1)
        # The MOVESET card's cross; without the import (E6 --no-import) square picks and the
        # loading is over within the second: the CPU's first opponent stays the game's.
        if g.value(T.STATE) == 9: g.press(T.CROSS, frames=5)
        g.wait(lambda: g.value(T.STATE) in (11, 8), 'loading not reached', 30)
        if g.value(T.STATE) == 11:
            mark = len(g.log())
            g.write(CPU_FIGHTER, opponent[0], 2); g.write(CPU_COSTUME, opponent[1], 2); g.write(STAGE_INDEX, 8, 1)
        check_fight(g, mark, report, 'arcade-stage9')
        g.q(cmd='turbo', enabled=1)
        seen, end, shot_at = fighters(g)[1], time.monotonic() + 2400, 0
        mark = len(g.log())
        while time.monotonic() < end:
            st, ph = g.value(T.STATE), g.value(T.PHASE, 2)
            if st in (18, 19): break
            if st == 8 and ph >= 16:                       # Ogre's cutscene
                if not cut and not shot_at: mark = len(g.log()); f0 = g.q(cmd='frame')['frame']
                g.q(cmd='turbo', enabled=0)
                if g.q(cmd='frame')['frame'] - f0 >= 40 * len(cut):          # the same frames before / after
                    ids = fighters(g); F.shot(g, f'ogre-cut-{len(cut):02d}', hq); cut.append(ids); shot_at = 1
                    got = grafts(g, mark)
                    print(f'  cutscene: actors {ids}, grafted {got}', flush=True)
                    if ids[0] == 13 and got.get(0) not in (None, 'Heihachi'): report.append(('ogre-cutscene', ids, None, got, False))
            elif st == 8 and 6 <= ph <= 8:
                p2 = fighters(g)[1]
                if p2 != seen:
                    g.q(cmd='turbo', enabled=0)
                    check_fight(g, mark, report, f'arcade-{NAMES.get(p2, p2)}'); seen = p2; mark = len(g.log())
                    g.q(cmd='turbo', enabled=1)
                ko(g, 1)
            g.halted(); time.sleep(.02)
        return report, cut, [l for l in g.log().splitlines() if l.startswith('FATAL')]
    finally:
        g.stop()


MENU_LINES, GRID, GRID_STRIDE, GRID_CELLS = 0x800db5d0, 0x800b8d70, 172, 0x80022768
MODE_NO = {'vs': (1, 10), 'team': (2, 10), 'timeattack': (3, 9), 'survival': (4, 9), 'ball': (7, 10), 'force': (8, 9)}
BUTTON = {'LP': T.SQ, 'LK': T.CR, 'RP': T.TR, 'RK': T.CI, 'R1': 11}
# --triangle (F32): VS with the third costumes unlocked (0x80097EF4), then two more matches whose
# files are checked: Jin square against Jin triangle (the game's clash gives player 2 the kick
# costume, its model stays RP, file P3), Xiaoyu R1 (third costume, file P5) against Eddy triangle
# (RP, P3, the punch costume). (native, button) per player, then the files each must read.
THIRD = (1, 5, 7, 8, 9, 16, 18)
TRIANGLE_MATCHES = [(((9, 'LP'), (9, 'RP')), {0: 1, 1: 3}, (0, 1)),
                    (((7, 'R1'), (8, 'RP')), {0: 5, 1: 3}, (2, 0))]
MODEL_READ = re.compile(r"^(\w+) \(TTT1 model\) model: costume (\d+),", re.M)


def to_mode(g, mode, screen):
    """The modes menu's line of that mode (its table, as tools/test_b122_gon_stages.py reads it)."""
    for _ in range(50):
        base = (g.value(MENU_LINES) & 0xffff) << 16 | g.value(MENU_LINES + 8) & 0xffff
        count = g.value(base + 4) if base >> 24 in (0x80, 0x9f) else 0
        if 0 < count < 16: break
        time.sleep(.1)
    line = next(i for i in range(count) if g.value(base + 16 + 8 * i + 4, 2) in (mode, mode | 0x100))
    # VS is greyed (0x100) without a second pad at the menu; the bench's player 2 is the debug
    # server's port 2 injection, which plugs it in at the first press: the line is let through.
    if g.value(base + 16 + 8 * line + 4, 2) & 0x100: g.write(base + 16 + 8 * line + 4, mode, 2)
    g.write(LINE, line, 4); g.press(T.CROSS)
    g.wait(lambda: g.value(T.STATE) == screen and g.value(T.MODE, 1) == mode, f'mode {mode}: no selector', 60)
    time.sleep(2)


def press(g, button, port=1):
    g.q(cmd='press', buttons=F.pad(button), frames=4, **({'port': port} if port != 1 else {})); time.sleep(.6)


def grid_pick(g, p, native, button):
    """State 10's grid (VS, Team Battle, Tekken Ball): the block's cell written (+8 column,
    +0xC row; 7 columns), the button pressed on the player's pad. Without the MOVESET card
    (TEKKEN3_NATIVE_MOVES=0) the button picks."""
    cells = {g.value(GRID_CELLS + c * 6 + 4, 1) >> 2: c for c in range(21)}
    c, blk = cells[native], GRID + p * GRID_STRIDE
    # Back on the grid after a match, early presses are lost (from the third VS match on, player
    # 1's for several seconds): the button again until it takes, never a cross in its place.
    for _ in range(12):
        g.write(blk + 8, c % 7); g.write(blk + 12, c // 7); time.sleep(.5)
        # Player 1 through the input route: on the grid after a match, its circle sent by `press`
        # is lost (its square is not; player 2's circle neither), the route's buttons all take.
        if p == 0: T.route(g, [(4, F.pad(BUTTON[button])), (20, 0xffff)]); time.sleep(.8)
        else: press(g, BUTTON[button], p + 1)
        if g.value(blk) != 3: break
        time.sleep(.5)
    else: raise AssertionError(f'player {p + 1}: {button} not taken on the grid')
    # The button takes the costume (block state 4), a cross confirms (12).
    for _ in range(6):
        if g.value(blk) >= 12: break
        press(g, T.CR, p + 1); time.sleep(.4)


def select_pick(g, native, button):
    """State 9's selector (Time Attack, Survival, Tekken Force): player 1's cursor, the button."""
    F.cursor_to(g, native); press(g, BUTTON[button])


def wait_fight(g, label, seconds=240):
    g.wait(lambda: g.value(T.STATE) == 8 and 6 <= g.value(T.PHASE, 2) <= 8, f'{label}: no round', seconds)


def modes(build, assets, mode, off=False, triangle=False):
    env = {'TEKKEN3_TTT1_ASSETS': str(assets), 'TEKKEN3_TTT1_NATIVE_MODELS': 'all', 'TEKKEN3_NATIVE_MOVES': '0'}
    if off: env['TEKKEN3_F32_E5'] = '0'
    g = game(build, f'e5-{mode}{"-off" if off else ""}{"-triangle" if triangle else ""}{"-hq" if E6["hq"] else ""}', env, E6['hq'])
    report = []
    number, screen = MODE_NO[mode]
    try:
        boot_menu(g, pad2=mode in ('vs', 'ball'))
        if triangle: g.write(0x80097ef4, g.value(0x80097ef4) | sum(1 << i for i in THIRD))
        to_mode(g, number, screen)
        if mode in ('vs', 'ball'):
            # Match 1: Law (square) against Lei (circle); match 2: Law on cross against Law on circle
            # (a mirror, two costumes), player 2 losing every round.
            matches = [(((1, 'LP'), (2, 'RK')), None, None), (((1, 'RK'), (1, 'LK')), None, None)]
            if triangle: matches += TRIANGLE_MATCHES
            for n, (picks, files, costumes) in enumerate(matches):
                g.wait(lambda: g.value(T.STATE) == 10 and g.value(GRID) == 3,
                       'no grid', 240, lambda: ko(g, 1) if g.value(T.STATE) == 8 else None)
                time.sleep(1.5)
                if g.value(GRID + GRID_STRIDE) != 3:                 # Tekken Ball: player 2 joins with Start
                    press(g, 3, 2); time.sleep(1)
                mark = len(g.log())
                for p in (0, 1): grid_pick(g, p, *picks[p])
                for _ in range(10):                              # Tekken Ball: the ball's choice, a cross
                    if g.value(T.STATE) != 10: break
                    press(g, T.CR); time.sleep(.5)
                check_fight(g, mark, report, f'{mode}-{n + 1}')
                if files:
                    # The files read since the picks, by name (both Jin: the set of both); the costumes.
                    read = {}
                    for name, c in MODEL_READ.findall(g.log()[mark:]): read.setdefault(name, set()).add(int(c))
                    got = [T.actor(g, q)[0] & 3 for q in (0, 1)]
                    want = {}
                    for q in (0, 1): want.setdefault(NAMES[picks[q][0]], set()).add(files[q])
                    good = all(want[k] <= read.get(k, set()) for k in want) and tuple(got) == costumes
                    print(f'  {mode}-{n + 1} files read {read} want {want}, costumes {got} want {list(costumes)}',
                          'OK' if good else 'FAIL', flush=True)
                    report.append((f'{mode}-{n + 1}-files', None, got, read, good))
                if mode == 'ball': time.sleep(4); F.shot(g, f'{mode}-{n + 1}-play', False)
        elif mode == 'team':
            # A team of two (Law square, Lei triangle); the CPU's team drawn by the game (Start).
            g.wait(lambda: g.value(GRID) == 1, 'team size not asked', 30)
            press(g, T.R); press(g, T.CR)
            g.wait(lambda: g.value(GRID) == 2, 'members not asked', 10)
            mark = len(g.log())
            for n, (native, button) in enumerate(((1, 'LP'), (2, 'RP'))):
                cells = {g.value(GRID_CELLS + c * 6 + 4, 1) >> 2: c for c in range(21)}
                g.write(GRID + 8, cells[native] % 7); g.write(GRID + 12, cells[native] // 7); time.sleep(.4)
                press(g, BUTTON[button])
                g.wait(lambda: g.value(GRID + 44) > n, f'member {n + 1} not picked', 10)
            time.sleep(.5)
            for _ in range(6):
                if g.value(T.STATE) != 10: break
                press(g, 3)                                      # Start (bit 3): the CPU's team drawn
                time.sleep(.8)
            # Each round: the CPU's member knocked out (its next member), then ours.
            seen = None
            for n in range(4):
                wait_fight(g, f'team-{n + 1}')
                ids = fighters(g)
                if ids != seen:
                    check_fight(g, mark, report, f'team-{n + 1}'); mark = len(g.log()); seen = ids
                ko(g, 1 if n < 2 else 0)
                g.wait(lambda: g.value(T.PHASE, 2) > 8 or g.value(T.STATE) != 8, 'round did not end', 60,
                       lambda: ko(g, 1 if n < 2 else 0))
                g.wait(lambda: g.value(T.STATE) in (8, 11, 12, 3, 4) and not (g.value(T.STATE) == 8 and g.value(T.PHASE, 2) > 8),
                       'no next round', 120)
                if g.value(T.STATE) not in (8, 11): break
        else:                                                    # Time Attack, Survival, Tekken Force
            g.wait(lambda: g.value(T.STATE) == 9 and g.value(0x8011864c) == 1, 'player 1 not choosing', 60)
            time.sleep(1)
            mark = len(g.log())
            select_pick(g, 1, 'RP')                              # Law, triangle
            opponents = [(11, 0), (13, 1), (8, 0)]               # Kuma, Heihachi cross, Eddy
            if mode == 'force':
                wait_fight(g, 'force', 300)
                time.sleep(2); F.shot(g, 'force-start', False)
                report.append(('force', fighters(g), None, grafts(g, mark), grafts(g, mark).get(0) == 'Law'))
                print(f'  force: actors {fighters(g)} grafted {grafts(g, mark)}', flush=True)
                for k in range(6):                               # walk right, a shot each 2 s
                    g.q(cmd='press', buttons=F.pad(T.R), frames=110); time.sleep(2); F.shot(g, f'force-{k}', False)
            else:
                for n in range(3):
                    # The loading choice written as soon as its screen shows (polled every 10 ms: the game
                    # reads it early, a write 100 ms late left the game's own opponent in the actor and
                    # the written one's files on it, E6).
                    end = time.monotonic() + 240
                    while not (g.value(T.STATE) == 11 or (g.value(T.STATE) == 8 and 6 <= g.value(T.PHASE, 2) <= 8)):
                        if time.monotonic() > end: raise AssertionError(f'{mode}-{n + 1}: no loading')
                        if g.value(T.STATE) == 8: ko(g, 1)
                        time.sleep(.01)
                    if g.value(T.STATE) == 11:
                        g.write(CPU_FIGHTER, opponents[n][0], 2); g.write(CPU_COSTUME, opponents[n][1], 2)
                    check_fight(g, mark, report, f'{mode}-{n + 1}'); mark = len(g.log())
                    # Time Attack: the next stage's opponent in the ladder (0x800AFB18, 4 bytes a stage:
                    # ID, costume; cpu_pick_arcade, t3-ps1 ovl0_combat/800B0794.c), read at its loading.
                    if mode == 'timeattack' and n + 1 < len(opponents):
                        at = 0x800afb18 + 4 * (g.value(STAGE_INDEX, 1) + 1)
                        g.write(at, opponents[n + 1][0], 1); g.write(at + 1, opponents[n + 1][1], 1)
                    end = time.monotonic() + 120
                    while g.value(T.STATE) == 8 and fighters(g)[1] == report[-1][1][1] and time.monotonic() < end:
                        ko(g, 1); time.sleep(.05)
        return report, [l for l in g.log().splitlines() if l.startswith('FATAL')]
    finally:
        g.stop()


def arcade_continue(build, assets):
    """Arcade, player 1 Jin on square against a native, loses the match, continues (Start on
    the countdown) and takes Law on circle: the new fighter and button read and grafted."""
    env = {'TEKKEN3_TTT1_ASSETS': str(assets), 'TEKKEN3_TTT1_NATIVE_MODELS': 'all', 'TEKKEN3_NATIVE_MOVES': '0'}
    g = game(build, 'e5-continue', env)
    report = []
    try:
        boot_menu(g)
        g.write(LINE, 0, 1); g.press(T.CROSS)
        g.wait(lambda: g.value(T.STATE) == 9 and g.value(0x80118648) == 21, 'Arcade selector not reached', 60)
        time.sleep(1.5)
        select_pick(g, 9, 'LP')
        g.wait(lambda: g.value(T.STATE) == 11, 'loading not reached', 30)
        mark = len(g.log())
        g.write(CPU_FIGHTER, 0, 2); g.write(CPU_COSTUME, 1, 2)
        check_fight(g, mark, report, 'continue-1')
        g.wait(lambda: g.value(T.STATE) == 9, 'no continue to the selector', 240,
               lambda: (ko(g, 0), g.press(T.START) if g.value(T.STATE) not in (8, 9) else None))
        time.sleep(2)
        mark = len(g.log())
        select_pick(g, 1, 'RK')
        check_fight(g, mark, report, 'continue-2')
        return report, [l for l in g.log().splitlines() if l.startswith('FATAL')]
    finally:
        g.stop()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--case', choices=('embu', 'cine', 'arcade', 'continue', 'modes'), required=True)
    ap.add_argument('--mode', choices=tuple(MODE_NO), default='vs')
    ap.add_argument('--variant', type=int, default=0)
    ap.add_argument('--cine', default='armorking')
    ap.add_argument('--off', action='store_true', help='TEKKEN3_F32_E5=0: the natives on their PS1 models there')
    ap.add_argument('--hq', action='store_true')
    ap.add_argument('--seconds', type=float, default=60)
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--assets', type=Path, default=ROOT / 'workspace/ttt1-import/roster')
    ap.add_argument('--triangle', action='store_true', help='--case modes --mode vs|ball: third costumes unlocked, '
                    'then Jin square against Jin triangle and Xiaoyu R1 against Eddy triangle, files checked (F32)')
    ap.add_argument('--cpu-ttt1', action='store_true', help='E6: the natives on their TTT1 moves (the CPU\'s, or '
                    'all where the case had them on T3 moves), drawn by their TTT1 models')
    ap.add_argument('--default', action='store_true', help='E6: without TEKKEN3_TTT1_NATIVE_MODELS (the default)')
    ap.add_argument('--no-import', action='store_true', help='E6: an empty catalogue: the original game, no graft')
    ap.add_argument('--env', action='append', default=[], metavar='NAME=VALUE', help='passed to the game')
    a = ap.parse_args()
    build, assets = ROOT / a.build, a.assets.resolve()
    E6['cpu_ttt1'], E6['default'], E6['hq'] = a.cpu_ttt1, a.default, a.hq
    E6['env'] = dict(e.split('=', 1) for e in a.env)
    if a.no_import:
        E6['no_import'] = WORK / 'e6-no-import'
        E6['no_import'].mkdir(parents=True, exist_ok=True)
    E6['tag'] = ''.join(f'-{k}' for k, on in (('cputtt1', a.cpu_ttt1), ('default', a.default), ('noimport', a.no_import)) if on) + \
        ''.join(f'-{k.lower().replace("tekken3_", "")}{v}' for k, v in E6['env'].items())
    if a.case == 'continue':
        report, fatal = arcade_continue(build, assets)
        print(f'  fatal: {fatal or "none"}')
        sys.exit(1 if fatal or len(report) < 2 or not all(r[-1] for r in report) else 0)
    if a.case == 'modes':
        report, fatal = modes(build, assets, a.mode, a.off, a.triangle)
        print(f'  fatal: {fatal or "none"}')
        sys.exit(1 if fatal or not report or not all(r[-1] for r in report) else 0)
    if a.case == 'arcade':
        report, cut, fatal = arcade(build, assets, off=a.off, hq=a.hq)
        print(f'  cutscene shots {len(cut)}, actors {sorted(set(cut))}; fatal: {fatal or "none"}')
        sys.exit(1 if fatal or not all(r[-1] for r in report) else 0)
    if a.case == 'embu': lines, fatal, n = embu(build, assets, a.variant, a.off, a.hq, a.seconds)
    else: lines, fatal, n = cine(build, assets, a.cine, a.off, a.hq, a.seconds)
    for l in lines: print('  ', l)
    print(f'  {n} shots in {WORK}; fatal: {fatal or "none"}')
    sys.exit(1 if fatal else 0)


if __name__ == '__main__':
    main()
