#!/usr/bin/env python3
"""TTT Stages: a TTT stage fought twice in a row is drawn both times, a
savestate loaded between the two included (B149, TIPS.md section 235).

    python ressources/slot.py --kind game --who ttt-stage-reload --prio 2 -- \\
        python tools/test_ttt_stage_reload.py OUT CASE [CASE ...] [--build build-rel-lite] [--data MODS]
            [--arena 0] [--other 5] [--stages ttt|t3] [--renderer software|opengl]

(a PSX_DEBUG_SERVER_LITE build; --data: the mods folder of an install, its
stage packs and TTT1 catalogue read in place; Python with Pillow, the one
of venv-import)

Seen on the 1.5.0 trailer shoot (10/11): Practice reloaded from a state
saved on the grid before any fight, arena 0 fought, the state loaded again,
arena 0 again: the second fight's TTT stage black, its floor alone drawn.
A savestate puts the upper VRAM half back as it was saved, while the stage
engine keeps its pack (src/tekken3_arcade_stages.c, active(): the same
stage next is not loaded again), so its textures were gone.

A cold start each (stage_check.Game: software renderer x1, headless, no
pad; --renderer opengl: a window at x1), STAGES = TTT (TEKKEN3_STAGES; --stages t3: the arcade stages of
Arcade Stages, the same engine), the STAGE band of F18 off, the arena
written in every fighter record before each Cross of the grid. Each fight
is shot 3 s into the round. A stage is "drawn" when more than 25 % of the
band y 20..55 % of the picture is not black and, for an arena already
fought in the run, its top right (the stage above the fighters, clear of
Practice's MODE SELECT) is within 30 (mean of 0..255) of that arena's first
shot: same fighters, same camera. With the software renderer the stale
upper half shows as the grid's art on the stage's polygons, with OpenGL
as black.

    reload         grid saved (slot 7), fight on --arena, slot 7 loaded,
                   the same fight again (the shoot's path; wrong before
                   the fix)
    between        the same with --other fought between the two
    fight          grid saved, fight on --arena saved (the stage in the
                   upper half) and loaded again
    again          no savestate: fight on --arena, Practice's MODE SELECT,
                   PLAYER SELECT, the grid, the same arena (a player's path)
    again-between  the same with --other fought between the two
    continue       Arcade, --arena written in the records, player 1 loses
                   the first fight and continues (Start on the countdown):
                   the fight replayed on the same stage (its camera may
                   look the other way: judged lit, and by eye)
    vs             VS (a PSX_DEBUG_TOOLS=ON build: player 2 on port 2),
                   fight on --arena, player 2 loses the match, VS BATTLE
                   SELECT again, the same arena (judged lit, and by eye)

Exit 1 when a fight's stage is not drawn. Screenshots in OUT/CASE.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import test_f18_stage_select as f18  # noqa: E402

sc = f18.sc
SCREEN, PHASE, MODE, ARENA = 0x800ae204, 0x800ae224, 0x800afa88, 0x800adc84
RECORDS = 0x80097d40                     # 92 fighter records, byte 10 the arena
P1_LIFE = 0x800a961e
BLOCK = 0x800b8b60                       # Practice block: +0x75 MODE SELECT up
MODE_SELECT = BLOCK + 0x75
CROSS, START, DOWN = 0xbfff, 0xfff7, 0xffbf
ARCADE, PRACTICE = 0, 5
SLOT = 7
NO_PAD = dict(SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS='0', SDL_JOYSTICK_HIDAPI='0', SDL_JOYSTICK_RAWINPUT='0',
              SDL_XINPUT_ENABLED='0', SDL_JOYSTICK_DIRECTINPUT='0', SDL_JOYSTICK_WGI='0', SDL_JOYSTICK_GAMEINPUT='0')
DATA = ROOT / 'build-rel-lite/mods'


class Game(f18.Game):
    def __init__(self, build: Path, run: Path, data: Path, stages='ttt', renderer='software'):
        sc.Game.__init__(self, build, run, 'mod', renderer, data / 'arcade-stages',
                         env_extra={'TEKKEN3_TTT_STAGES_DIR': str(data / 'ttt-stages'),
                                    'TEKKEN3_TTT1_ASSETS': str(data / 'ttt1'),
                                    'TEKKEN3_TTT_MUSIC_DIR': str(data / 'ttt-music'),
                                    'TEKKEN3_STAGES': stages, 'TEKKEN3_CPU_GUESTS': '0,0,0', **NO_PAD},
                         features=[(*f18.FEATURE, False)])

    def slot_file(self):
        return self.run / 'cards/openbios' / f'state_80079C70_slot{SLOT:02d}.pst'

    def save(self):
        f = self.slot_file()
        t0 = f.stat().st_mtime if f.exists() else 0
        self.q(cmd='savestate', op='save', slot=SLOT)
        self.wait(lambda: f.exists() and f.stat().st_mtime > t0, 'the state was not saved', 20)
        time.sleep(.5)

    def load(self, screen):
        self.q(cmd='savestate', op='load', slot=SLOT)
        time.sleep(.5)
        for _ in range(200):
            try:
                if self.value(SCREEN) == screen: break
            except RuntimeError:            # "emu busy or frozen" while it loads
                pass
            time.sleep(.05)
        time.sleep(1)


def force_arena(g: Game, arena: int):
    raw = g.read(RECORDS, 4 * 92)
    for i in range(92):
        p = int.from_bytes(raw[4 * i:4 * i + 4], 'little')
        if 0x80010000 <= p < 0x80200000 and g.value(p + 10, 1) != arena:
            g.write(p + 10, arena)


def lit(png: Path):
    """The part of the band y 20..55 % that is not black."""
    from PIL import Image
    im = Image.open(png).convert('L')
    w, h = im.size
    px = im.crop((0, int(h * .20), w, int(h * .55))).tobytes()
    return sum(1 for v in px if v > 12) / len(px)


def apart(png: Path, ref: Path):
    """Mean difference (0..255) with the first fight's shot over the top right
    of the picture (the stage above the fighters, clear of Practice's MODE
    SELECT on the left)."""
    from PIL import Image, ImageChops
    a, b = (Image.open(f).convert('RGB') for f in (png, ref))
    w, h = a.size
    box = (int(w * .55), int(h * .04), w, int(h * .35))
    d = ImageChops.difference(a.crop(box), b.crop(box)).convert('L').tobytes()
    return sum(d) / len(d)


def judge(g: Game, png: Path, name: str, arena: int, refs: dict, results: list, same_camera=True):
    """Drawn: lit, and (the same arena seen before in this run) close to the
    first shot of that arena: same fighters, same camera 3 s into a round
    (same_camera: not a Continue's replay, which may look the other way)."""
    got, l = g.value(ARENA, 2), lit(png)
    ok, note = l > .25 and got == arena, ''
    if arena in refs:
        d = apart(png, refs[arena])
        ok = ok and (d < 30 or not same_camera)
        note = f', {d:.0f} from {refs[arena].stem}' + ('' if same_camera else ' (another camera: look at it)')
    else:
        refs[arena] = png
    results.append((name, ok))
    print(f'{name}: arena {got} (wanted {arena}), {l:.0%} lit{note}: {"drawn" if ok else "NOT DRAWN"}', flush=True)


def fight(g: Game, arena: int, out: Path, name: str, results: list, refs: dict):
    """From the grid: picks (MOVESET cards taken with Cross), the arena
    written before each Cross; shot 3 s into the round."""
    end = time.monotonic() + 90
    while g.value(SCREEN) == 9:
        if time.monotonic() > end: raise AssertionError(f'{name}: the grid never closed')
        force_arena(g, arena)
        g.press(CROSS)
        time.sleep(.5)
    g.wait(lambda: g.value(SCREEN) == 8, f'{name}: the fight never came', 120)
    g.wait(lambda: g.value(PHASE, 2) >= 6, f'{name}: the round never started', 60)
    time.sleep(3)
    png = out / f'{name}.png'
    g.shot(png)
    judge(g, png, name, arena, refs, results)


def to_grid(g: Game, mode: int):
    g.write(f18.LINE, f18.menu_line(g, mode), 4)
    g.press(CROSS)
    g.wait(lambda: g.value(SCREEN) == 9 and g.value(MODE) == mode, f'the grid of mode {mode} never came', 30)
    if mode == ARCADE: g.write(0x8011863c, 0x10ff, 2)       # the grid's timer up
    time.sleep(2)


def case_reload(a, g, out, results, between=None):
    refs = {}
    f18.to_menu(g)
    to_grid(g, PRACTICE)
    g.save()
    fight(g, a.arena, out, '1-first', results, refs)
    if between is not None:
        g.load(9)
        fight(g, between, out, '2-between', results, refs)
    g.load(9)
    fight(g, a.arena, out, '3-again' if between is not None else '2-again', results, refs)


def case_fight(a, g, out, results):
    refs = {}
    f18.to_menu(g)
    to_grid(g, PRACTICE)
    g.save()                                   # the grid's upper half in slot 7 first
    fight(g, a.arena, out, '1-first', results, refs)
    g.save()                                   # then the fight's, the stage in it
    time.sleep(2)
    g.load(8)
    time.sleep(1)
    png = out / '2-loaded.png'
    g.shot(png)
    judge(g, png, '2-loaded', a.arena, refs, results)


def player_select(g: Game, out: Path, name: str):
    """Practice's MODE SELECT (up at the round's start): Down to PLAYER
    SELECT, Cross: the grid."""
    g.wait(lambda: g.value(MODE_SELECT, 1), 'MODE SELECT is not up', 10)
    for _ in range(3):
        g.press(DOWN); time.sleep(.2)
    g.shot(out / f'{name}.png')
    for _ in range(5):
        g.press(CROSS)
        try:
            g.wait(lambda: g.value(SCREEN) == 9, '', 8); break
        except AssertionError:
            pass
    else:
        raise AssertionError('PLAYER SELECT did not lead to the grid')
    time.sleep(2)


def case_again(a, g, out, results, between=None):
    refs = {}
    f18.to_menu(g)
    to_grid(g, PRACTICE)
    fight(g, a.arena, out, '1-first', results, refs)
    if between is not None:
        player_select(g, out, '1b-player-select')
        fight(g, between, out, '2-between', results, refs)
    player_select(g, out, '2b-player-select' if between is not None else '1b-player-select')
    fight(g, a.arena, out, '3-again' if between is not None else '2-again', results, refs)


def case_continue(a, g, out, results):
    """tools/test_stage_options.py --lose 1, by memory only (the game's log
    reaches its file late): player 1's life 0 in the first fight, Start
    while 0x800AE1F8 is 0 (the round decided, the countdown), Cross on a
    grid; the replay is on when 0x800AE1F8 is back to 1. Shot 3 s later;
    the log, read once the game is closed, must have the Continue and no
    attract demo (main)."""
    refs = {}
    f18.to_menu(g)
    to_grid(g, ARCADE)
    fight(g, a.arena, out, '1-first', results, refs)
    end, lost, seen = time.monotonic() + 180, False, []
    while time.monotonic() < end:
        here = (g.value(SCREEN), g.value(PHASE, 2), g.value(0x800ae1f8, 2), g.value(P1_LIFE, 2))
        s, phase, deciding, life = here
        if not seen or seen[-1][:3] != here[:3]: seen.append(here)
        if lost and s == 8 and phase >= 6 and deciding: break    # the replay is on
        if s == 9:
            force_arena(g, a.arena); g.press(CROSS)
        elif s == 8 and phase >= 8:
            if not deciding: lost = True; g.press(START)
            elif not lost and phase == 8 and life > 0: g.write(P1_LIFE, 0, 2)
        elif s in (12, 16, 17): g.press(START)
        time.sleep(.2)
    else:
        raise AssertionError(f'the Continue never came back to a fight: {seen}')
    print('  screen, phase, 0x800AE1F8, P1 life:', ' '.join(map(str, seen)), flush=True)
    time.sleep(3)
    png = out / '2-continue.png'
    g.shot(png)
    judge(g, png, '2-continue', a.arena, refs, results, same_camera=False)


def vs_fight(g: Game, arena: int, out: Path, name: str, results: list, refs: dict):
    """VS BATTLE SELECT: both pick (Cross on each pad, MOVESET cards
    included; port 1 polled only while injected, an all-up press after
    player 2's), the arena written before each round of presses."""
    end = time.monotonic() + 90
    while g.value(SCREEN) == 10:
        if time.monotonic() > end: raise AssertionError(f'{name}: VS BATTLE SELECT never closed')
        force_arena(g, arena)
        g.press(CROSS)
        g.p2(CROSS)
        g.q(cmd='press', buttons=f18.NONE, frames=8); time.sleep(.4)
    g.wait(lambda: g.value(SCREEN) == 8, f'{name}: the fight never came', 120)
    g.wait(lambda: g.value(PHASE, 2) >= 6, f'{name}: the round never started', 60)
    time.sleep(3)
    png = out / f'{name}.png'
    g.shot(png)
    judge(g, png, name, arena, refs, results, same_camera=False)     # the rematch's camera may differ


def case_vs(a, g, out, results):
    """VS (player 2 on port 2: a PSX_DEBUG_TOOLS=ON build), fight on --arena,
    player 2 loses every round, VS BATTLE SELECT again, the same arena (the
    test_f18_stage_select.py vs path)."""
    refs = {}
    f18.to_vs(g)
    vs_fight(g, a.arena, out, '1-first', results, refs)

    def back():
        if g.value(SCREEN) == 8 and g.value(PHASE, 2) >= 6: g.write(f18.P2_LIFE, 0, 2)
        return g.value(SCREEN) == 10 and g.vs_state(0) == 3 and g.vs_state(1) == 3
    g.wait(back, 'VS BATTLE SELECT never came back', 240)
    time.sleep(2)
    vs_fight(g, a.arena, out, '2-again', results, refs)


CASES = {'reload': case_reload, 'between': lambda a, g, o, r: case_reload(a, g, o, r, between=a.other),
         'fight': case_fight, 'again': case_again,
         'again-between': lambda a, g, o, r: case_again(a, g, o, r, between=a.other), 'continue': case_continue,
         'vs': case_vs}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('out')
    p.add_argument('cases', nargs='+', choices=sorted(CASES))
    p.add_argument('--build', default='build-rel-lite')
    p.add_argument('--data', default=str(DATA))
    p.add_argument('--arena', type=int, default=0)
    p.add_argument('--other', type=int, default=5)
    p.add_argument('--renderer', default='software', help='opengl: a window at x1 (the shoot saw the stage black there)')
    p.add_argument('--stages', default='ttt', help='STAGES: ttt, or t3 (the arcade stages of Arcade Stages)')
    a = p.parse_args()
    out = Path(a.out).resolve()
    build = (ROOT / a.build).resolve()
    failed = []
    for name in a.cases:
        results = []
        g = Game(build, out / name / 'r', Path(a.data), a.stages, a.renderer)
        try:
            CASES[name](a, g, out / name, results)
        except Exception as e:                               # the next case still runs
            results.append((f'error: {e}', False))
            print(f'{name}: ERROR {e}', flush=True)
        finally:
            g.stop()
        log = g.logtext()
        if name == 'continue':                               # the replay was the Continue's, not a demo
            results.append(('the Continue in the log', 'Continue, the same fight' in log
                            and 'Attract demo' not in log))
        lines = [l for l in log.splitlines() if 'loaded from' in l or 'savestate' in l or 'put back' in l
                 or 'TTT Stages:' in l]
        print('\n'.join(f'  | {l}' for l in lines[-12:]), flush=True)
        failed += [f'{name}: {n}' for n, ok in results if not ok]
        print(f'{name}: {"OK" if all(ok for _, ok in results) else "FAILED"}', flush=True)
    if failed:
        print('FAILED:\n  ' + '\n  '.join(failed))
        sys.exit(1)
    print('all drawn')


if __name__ == '__main__':
    main()
