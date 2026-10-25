#!/usr/bin/env python3
"""B79 (GH#133): the sky of the arcade stages under Gun Jack's flying win pose.

    python tools/arcade_stages/sky_check.py --build build-b79-dbg --out workspace/b79/runs/x --arena N
        [--button triangle|square|cross|circle] [--mode mod|off] [--aspect 16:9|4:3]
        [--renderer software|opengl] [--source t3|ttt] [--moves t3|ttt1] [--pose 3432] [--tries 3] [--limit 0.006] [--margin-limit 0.02]

Cold start, Arcade: player 1 is Gun Jack (Paul under the cursor, then 16
written in +28 of the player's block and at 0x800ADD5C, TIPS section 87),
every fight forced on --arena (byte 10 of the fighter records). Once a round
runs, player 2's life goes to 0 and --button is held without a break through
the K.O.: the pose reads it once (Triangle: move 3432, the flying pose, the
camera up to pitch -0x1F0; Square 3431, Cross 3433, Circle 3434; broken
presses gave a pose at random). Not the pose wanted: again on the next
round, --tries times.

The camera's pitch (0x800A85C0, negative: looking up) is read live; from
the first frame looking up past --pitch-from, every frame's GP0 commands
are taken from the debug server's ring (gpu_frame_dump, ~4 s deep) and
rasterized afterwards on the wide canvas (stage_check.coverage): T3 never
clears the screen, so a place no primitive covers shows older frames (the
"noise" of the report: trails of the flying Jack). Frames without any stage
primitive of ours (a cut) end the count: the transition after the pose
draws a few partial frames, not a stage.

Fails when the uncovered share of the 4:3 picture (and, in OpenGL, of a
16:9 margin: the software renderer without a window draws the native 368
picture only) passes --limit (--margin-limit) on a frame of the pose. The sky rows (the top
SKY_ROWS of the picture) are also given apart.
Writes NN-frames.txt (frame, pitch, uncovered left / 4:3 / right, stage
primitives, sky of the picture, sky of the margins), NN-live.txt (frame,
pitch, player 1's move) and the masks of the worst frames.
"""
import argparse
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stage_check as S  # noqa: E402

CURSOR_CHAR, LOADING_CHAR, GUN_JACK = 0x80118668, 0x800add5c, 16
TTT_ARENA = {13: 10, 14: 6}     # TTT stages without an arena of their own (as tools/test_ttt_stage_holes.py)
SKY_ROWS = 288          # the top 60 % of the picture: the sky
ACTOR, STRIDE, LIFE, MOVE, CAMERA = 0x800a9228, 0x188c, 0x3f6, 0xa0, 0x800a85c0
RIGHT = 0xffdf
BUTTONS = dict(triangle=0xefff, circle=0xdfff, cross=0xbfff, square=0x7fff)


def s12(a):
    a &= 0xFFF
    return a - 0x1000 if a >= 0x800 else a


def to_fight(g, arena):
    g.q(cmd='turbo', enabled=1)

    def menu():
        if g.value(S.SCREEN) == 3:
            g.write(0x80097f26, 1); g.write(0x80097f27, 1)
            g.write(0x80097f1e, 1)
            g.press(S.START)
        return g.value(S.SCREEN) == 4
    g.wait(menu, 'the modes menu never came', 180)
    g.q(cmd='turbo', enabled=0)
    time.sleep(.3)
    g.write(S.LINE, 0, 4)
    g.press(S.CROSS)
    g.wait(lambda: g.value(S.SCREEN) == 9, 'the Arcade selector never came', 30)
    time.sleep(1.5)
    S.force_arena(g, arena)
    seen = []
    for _ in range(120):
        seen.append(g.value(CURSOR_CHAR, 2))
        if seen[-1] == 0:
            break
        g.q(cmd='press', buttons=RIGHT, frames=6, port=1); time.sleep(.5)
    else:
        raise AssertionError(f'cursor did not reach Paul: {seen[-24:]}')
    g.q(cmd='write_ram', addr=f'{CURSOR_CHAR:08x}', bytes=GUN_JACK.to_bytes(2, 'little').hex())
    g.q(cmd='press', buttons=S.SQUARE, frames=12)

    def chosen():
        s = g.value(S.SCREEN)
        if s == 9:      # the pick missed: Gun Jack again under the cursor
            g.q(cmd='write_ram', addr=f'{CURSOR_CHAR:08x}', bytes=GUN_JACK.to_bytes(2, 'little').hex())
            g.q(cmd='press', buttons=S.SQUARE, frames=12); time.sleep(.3)
        if s == 11:
            g.q(cmd='write_ram', addr=f'{LOADING_CHAR:08x}', bytes=GUN_JACK.to_bytes(2, 'little').hex())
        return s == 8 and g.value(S.PHASE, 2) >= 8
    g.wait(chosen, 'the round never started', 150)
    who = g.value(ACTOR + 0x18, 2)
    assert who == GUN_JACK, f'P1 is {who}, not Gun Jack'


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--arena', type=int, default=5)
    ap.add_argument('--button', choices=BUTTONS, default='triangle')
    ap.add_argument('--mode', choices=('mod', 'off'), default='mod', help='off: the PS1 stage (Arcade Stages off)')
    ap.add_argument('--source', choices=('t3', 'ttt'), default='t3',
                    help='ttt: TTT stage --arena (STAGES = TTT; 13 and 14 forced in arenas 10 and 6)')
    ap.add_argument('--ttt-packs', default=str(S.TTT_PACKS))
    ap.add_argument('--ttt1', default=str(S.ROOT / 'workspace/ttt1-catalogue'), help='the TTT1 catalogue (TTT stages need it)')
    ap.add_argument('--aspect', choices=('16:9', '4:3'), default='16:9')
    ap.add_argument('--renderer', default='software')
    ap.add_argument('--moves', choices=('t3', 'ttt1'), default='t3')
    ap.add_argument('--packs', default=str(S.PACKS))
    ap.add_argument('--seconds', type=float, default=16)
    ap.add_argument('--pitch-from', type=int, default=-0x40, help='frames counted below this pitch (looking up)')
    ap.add_argument('--tries', type=int, default=3, help='rounds won until the flying pose comes')
    ap.add_argument('--pose', type=int, default=3432, help="the flying pose's move (T3's Gun Jack); 0: any look up")
    ap.add_argument('--shots', type=int, default=0, help='live screenshots while looking up (every 3rd read)')
    ap.add_argument('--masks', type=int, default=6, help='hole masks written (the worst frames)')
    ap.add_argument('--limit', type=float, default=.006,
                    help="uncovered share of the 4:3 picture (a fight's own seams: up to 0.55 %%, arena 7, TIPS section 93)")
    ap.add_argument('--margin-limit', type=float, default=.02,
                    help='of a 16:9 margin (OpenGL): level cameras leave seams there (arena 7: 1 %%, as in fights, TIPS section 93)')
    a = ap.parse_args(argv)
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    env = {'TEKKEN3_NATIVE_MOVES': '0' if a.moves == 't3' else '1'}
    arena = a.arena
    if a.source == 'ttt' and a.arena in TTT_ARENA:
        arena = TTT_ARENA[a.arena]
        env['TEKKEN3_TTT_STAGES_FORCE'] = f'{a.arena}@8'
    g = S.Game(Path(a.build).resolve(), out / 'run', a.mode, a.renderer, Path(a.packs).resolve(),
               widescreen=a.aspect == '16:9', env_extra=env,
               ttt=Path(a.ttt_packs).resolve() if a.source == 'ttt' else None, ttt1=a.ttt1)
    dumps = {}          # GPU frame -> GP0 entries, the frames around the camera looking up
    shot = 0
    pitches, moves = [], []      # moves: (frame, pitch, player 1's move) read live
    try:
        to_fight(g, arena)
        print(f'arena {g.value(S.ARENA, 2)}, {a.source} stage {a.arena}, Gun Jack ({a.moves} moves), {a.mode}, {a.aspect}',
              flush=True)
        for attempt in range(a.tries):
            # a round running (both lives given), then player 2's K.O.
            g.wait(lambda: g.value(S.SCREEN) == 8 and g.value(S.PHASE, 2) >= 8
                   and g.value(ACTOR + STRIDE + LIFE, 2) > 0, 'no round to win', 120)
            time.sleep(1.5)
            first = len(moves)
            g.q(cmd='write_ram', addr=f'{ACTOR + STRIDE + LIFE:08x}', bytes='0000')
            end = time.monotonic() + a.seconds
            # the button held without a break through the K.O. and the replay
            # (the pose reads it once: short presses gave poses at random)
            g.q(cmd='press', buttons=BUTTONS[a.button], frames=int(a.seconds * 60))
            next_dump, until = None, -1
            # past --seconds, the dump goes on until the pose's frames are all
            # taken (it runs behind the game)
            while time.monotonic() < end or (next_dump is not None and time.monotonic() < end + 30):
                now = time.monotonic()
                pitch = s12(g.value(CAMERA))
                stats = g.q(cmd='gpu_ring_stats')
                newest = stats['newest_frame'] - 1          # the last complete frame
                pitches.append((newest, pitch))
                move = g.value(ACTOR + MOVE, 2)
                moves.append((newest, pitch, move))
                # the frames of the pose, or of a camera looking up (B79's fix
                # holds the camera level through the pose: no look up then)
                wanted = pitch < a.pitch_from or (a.pose and move == a.pose)
                if a.shots and wanted and len(pitches) % 3 == 0 and shot < a.shots:
                    g.q(cmd='screenshot', path=str(out / f'{a.arena:02d}-shot-{newest}-{pitch}.png'))
                    shot += 1
                if wanted:
                    until = newest + 30
                    if next_dump is None:
                        next_dump = max(newest - 30, stats['oldest_frame'] + 1)
                if next_dump is not None:
                    # every frame from the first one wanted (less a margin), as
                    # the GP0 ring still holds them (~4 s)
                    next_dump = max(next_dump, g.q(cmd='gpu_ring_stats')['oldest_frame'] + 1)
                    while next_dump <= min(newest, until) and time.monotonic() < now + .25:
                        dumps[next_dump] = g.q(cmd='gpu_frame_dump', frame=next_dump, count=40000)['entries']
                        next_dump += 1
                    if next_dump > until:
                        next_dump = None
            # the pose is drawn at random (move 3432 flies, 3433 does not): again
            # on the next round until the camera has looked up
            print(f'attempt {attempt}: {len(dumps)} frames dumped so far', flush=True)
            if dumps and (not a.pose or any(m[2] == a.pose for m in moves[first:])):
                break
            dumps.clear()
    finally:
        g.stop()
    (out / f'{a.arena:02d}-live.txt').write_text(''.join('%d %d %d' % m + chr(10) for m in moves))
    rows = []
    for n in sorted(dumps):
        # the stage's own primitives (the engine's GPU-DMA memory, 0x00E.....):
        # none on a frame the game does not draw the stage on (a cut)
        mine = sum(1 for e in dumps[n] if e['src'].startswith('0x00E'))
        if a.mode == 'off':        # no stage of ours: every drawing command
            mine = sum(1 for e in dumps[n] if 0x20 <= int(e['op'], 16) < 0x80)
        c = fast_coverage(dumps[n])
        rows.append((n, nearest_pitch(pitches, n)) + c[:3] + (mine,) + c[3:])
    (out / f'{a.arena:02d}-frames.txt').write_text(''.join('%d %d %.5f %.5f %.5f %d %.5f %.5f' % r + chr(10) for r in rows))
    # the pose up to its cut: the first frame drawing nothing (no stage of
    # ours, or nothing at all mod off); the transition after it draws a few
    # partial frames, not a stage. The last frame before the cut is left out
    # too: the game leaves it unfinished (a third to a half of the stage).
    up, cut = [], False
    for r in rows:
        drawn = r[5] and r[3] < .99
        if not drawn and up:
            cut = True
            break
        if drawn:
            up.append(r)
    if cut:
        up.pop()
    worst = [max((r[k] for r in up), default=0.0) for k in (2, 3, 4, 6, 7)]
    margins = a.aspect == '16:9' and a.renderer != 'software'
    for r in sorted(up, key=lambda r: -(max(r[2:5]) if margins else r[3]))[:a.masks]:
        fast_coverage(dumps[r[0]], out / f'{a.arena:02d}-{r[0]}-holes.png')
    lowest = min((p for _, p in pitches), default=0)
    print(f'arena {a.arena}: lowest pitch {lowest}, {len(rows)} frames dumped, {len(up)} counted; worst uncovered: '
          f'left {worst[0]:.4f}, 4:3 {worst[1]:.4f} (sky {worst[3]:.4f}), right {worst[2]:.4f} (sky of the margins {worst[4]:.4f})')
    if not up:
        raise SystemExit(f'FAIL: neither the pose (move {a.pose}) nor a camera looking up (pitch < {a.pitch_from}): '
                         'try another --button')
    # (margins: the software renderer without a window draws the native 368
    # picture only, its 16:9 margins mean nothing, TIPS section 106)
    if worst[1] > a.limit or (margins and max(worst[0], worst[2]) > a.margin_limit):
        raise SystemExit(f'FAIL: the sky leaves the screen uncovered (> {a.limit})')
    print('PASS')


def nearest_pitch(pitches, n):
    """The pitch read closest after GPU frame n (the reads are a few frames apart)."""
    later = [p for f, p in pitches if f >= n]
    return later[0] if later else pitches[-1][1]


def fast_coverage(entries, holes_png=None):
    """stage_check.coverage, counted with numpy (a frame in milliseconds)."""
    import numpy as np
    from PIL import Image, ImageDraw
    sys.path[:0] = [str(S.ROOT / 'tools'), str(S.ROOT / 'tools/perf')]
    from test_force_margins import M, shapes
    im = Image.new('L', (S.SCREEN_W + 2 * M, 480), 0)
    d = ImageDraw.Draw(im)
    for _, pts in shapes(entries):
        d.polygon([(x + M, y) for x, y in pts], fill=255)
    if holes_png:
        im.point(lambda v: 255 - v).save(holes_png)
    hole = np.asarray(im) == 0
    return (float(hole[:, :M].mean()), float(hole[:, M:M + S.SCREEN_W].mean()), float(hole[:, M + S.SCREEN_W:].mean()),
            float(hole[:SKY_ROWS, M:M + S.SCREEN_W].mean()),
            float(max(hole[:SKY_ROWS, :M].mean(), hole[:SKY_ROWS, M + S.SCREEN_W:].mean())))


if __name__ == '__main__':
    main()
