#!/usr/bin/env python3
"""The ball's hit effect in Tekken Ball at 64 x 64, PS2's under PS2 EFFECTS (B133, GH#179).

    python ressources/slot.py --kind game --who b133 --prio 2 -- \\
        python tools/test_b133_ball_spark_64.py OUT [--build build-dbg] [--data <install>/mods]
            [--fighter jin|heihachi|paul|<guest>] [--ps2 on|off] [--memcard-dir saves] [--tries 12] [--film] [--debug]

Build: PSX_DEBUG_TOOLS=ON (gpu_frame_dump, high_vram). --data: the mods folder of an install (TTT1 catalogue at
import version 10 or later and the PS2 EFFECTS pack, read in place; tools/test_b131_embu_ps2_sparks.py view_of).

A hit that charges the ball (power from 1 to 99, ovl3 ball_squash_color_update) spawns a decor effect of type 15
(ball_fx15_spawn, link 0): fx_type15_anim loops 12 frames of the hitter's strong-hit effect, 32 x 32
cells of its rectangle (x 368 / 496, frames 9 to 20 of the pack: fx_type15_cell_steps, y + 128), on a POLY_FT4 of
the effect (+0x50 + 40 * buffer, palette row 503) that follows the ball. TTT Hitspark (F12) only took the fighters'
sprites: that one stayed 32 x 32.

From the serve (the ball floating, state 9, saved), the ball is put in front of player 1, which starts one of its
moves that charge the ball (move id 0x217 or 0x31F, ovl3 ball_move; through the pending transition, +0x1A0,
tools/test_ball_sword.py), farther each try until an effect of type 15, link 0, lives. Each frame it lives, its GP0
commands read back from the ring (gpu_frame_dump, some 850 frames): the effect's own POLY_FT4 drawn = 32 x 32;
else a POLY_FT4 from the upper half on player 1's palettes (560, 896 on) = 64 x 64, its 16 x 64 cell read in the upper
half (high_vram) and found among the packs' images (the catalogue's *-TTT1-hiteffect64.hfx, the PS2 pack's
*-PS2-hiteffect64.hfx).

Checks (exit 1 otherwise): every frame drawn 64 x 64, from the pack of player 1's fighter: <Name>-PS2 with
--ps2 on for Jin, Heihachi, Kazuya, Devil, Angel, else <Name>-TTT1; its images among 9 to 20 (the loop kept).

--film: every VBlank's display as raw BGRA under OUT/film (the local `film` command of the debug server, not in the
repository), from the trial that connected; OUT/film.txt gives the film frame the effect was first seen at,
OUT/effects.json each frame's film frame, pack, image and quad on screen (for a before / after sheet). --debug: the
GP0 commands near the effect.

Driving: the grid takes the fighter on an edge of X held through set_input in hex (a 4-frame press of X, or an int,
was not taken), once the cursor has settled.
"""
import argparse, json, shutil, struct, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/arcade_stages'), str(ROOT / 'psxrecomp/tools')]
import test_hit_effect_64 as H
import test_b67_machine_gun_cannon as B
from test_b131_embu_ps2_sparks import DATA, view_of

SCREEN, PHASE, MODE, LINE = 0x800ae204, 0x800ae224, 0x800afa88, 0x80097f40
BLOCKS, LOADING_P1, BALL_STATE = 0x800b8d70, 0x800add5c, 0x800add74
ACTOR, STRIDE = 0x800a9228, 0x188c
FX_ACTIVE, FX_SPRITES = 0x800a0988, 0x800a3408
START, CROSS, RIGHT, LEFT, UP, DOWN, NONE = 0xfff7, 0xbfff, 0xffdf, 0xff7f, 0xffef, 0xffbf, 0xffff
BALL_CELLS = {'law': (0, 0), 'paul': (6, 0), 'xiaoyu': (0, 1), 'yoshimitsu': (1, 1), 'nina': (2, 1),
              'heihachi': (3, 1), 'king': (4, 1), 'lei': (5, 1), 'jin': (6, 1), 'hwoarang': (0, 2),
              'bryan': (2, 2), 'anna': (5, 2), 'eddy': (6, 2)}
PACK = {'jin': 'Jin', 'heihachi': 'Heihachi', 'paul': 'Paul', 'law': 'Law', 'xiaoyu': 'Xiaoyu', 'nina': 'Nina',
        'yoshimitsu': 'Yoshimitsu', 'king': 'King', 'lei': 'Lei', 'hwoarang': 'Hwoarang', 'bryan': 'Bryan',
        'anna': 'Anna', 'eddy': 'Eddy'}
MISHIMA = ('Jin', 'Heihachi', 'Kazuya', 'Devil', 'Angel')
CHARGING = (0x217, 0x31f)          # ball_move: the move ids that charge the ball on the ground (power += damage)
DISTANCES = (500, 650, 800, 950, 1100, 1250, 1400)
SLOT, LOOP = 10, range(9, 21)
DEBUG = False


def packs(data):
    """{name: its 64 x 64 images} of the catalogue's and the PS2 pack's."""
    out = {}
    for f in list((data / 'ttt1').glob('*-hiteffect64.hfx')) + list((data / 'ttt-ps2-laser').glob('*-hiteffect64.hfx')):
        try: out[f.name[:-len('-hiteffect64.hfx')]] = H.hfx(f)[2]
        except AssertionError: pass
    return out


def to_ball(g):
    def menu():
        if g.value(SCREEN) == 3:
            g.write(0x80097f26, b'\1\1'); g.press(START)     # Tekken Ball unlocked on the new card
        return g.value(SCREEN) == 4
    g.wait(menu, 'the modes menu never came', 240)
    time.sleep(.3)
    g.write(LINE, struct.pack('<I', 6)); g.press(CROSS)
    g.wait(lambda: g.value(SCREEN) == 10 and g.value(MODE) == 7 and g.value(BLOCKS) == 3, 'TEKKEN BALL SELECT', 30)
    time.sleep(1.5)


def pick(g, native):
    col, row = BALL_CELLS[native]
    for _ in range(20):
        x, y = g.value(BLOCKS + 8), g.value(BLOCKS + 12)
        if (x, y) == (col, row): break
        g.press(DOWN if y < row else UP if y > row else RIGHT if x < col else LEFT)
    else: raise AssertionError(f'the grid cursor never reached {native}')
    # X held (set_input takes hex; a 4-frame press of X was not taken here): the fighter, then the ball, and the
    # short loading screen (11) read in a tight loop.
    def take():                  # one edge of X once the cursor has settled
        time.sleep(1)
        g.q(cmd='set_input', buttons=f'{CROSS:04x}', port=1); time.sleep(.6); g.q(cmd='set_input', buttons=f'{NONE:04x}', port=1)
        return g.value(BLOCKS) == 15
    g.wait(take, 'the ball choice never came', 20)
    time.sleep(.5)
    for _ in range(4):
        g.q(cmd='set_input', buttons=f'{CROSS:04x}', port=1)
        end = time.monotonic() + 3
        while g.value(SCREEN) != 11 and time.monotonic() < end: pass
        g.q(cmd='set_input', buttons=f'{NONE:04x}', port=1)
        if g.value(SCREEN) == 11: return
        time.sleep(.2)
    raise AssertionError('the loading screen never came')


def charging(g):
    """Player 1's records whose move id charges the ball, by alias, from its alias table (0x800ADC20 + 12;
    tools/test_ball_sword.py unblockables)."""
    words = g.read(g.value(g.value(0x800adc20) + 12), 0x4000 * 4)
    seen, found = set(), []
    for alias in range(0x4000):
        record = struct.unpack_from('<I', words, alias * 4)[0]
        if record < 0x80000000 or record in seen: continue
        seen.add(record)
        try: rec = g.read(record, 0x38)
        except RuntimeError: continue
        move_id, damage = struct.unpack_from('<H', rec, 8)[0], struct.unpack_from('<h', rec, 0x14)[0]
        if move_id in CHARGING and 0 < damage < 60 and rec[0x2d]: found.append((alias, record, move_id, damage))
    return found


def signed(v): return v - (1 << 32) if v >= 1 << 31 else v


def ball_effects(g):
    """The living effects of type 15, link 0 (the hitter's strong-hit loop on the ball): {address: (base x, frame)}."""
    out, e = {}, g.value(FX_ACTIVE + 4)
    for _ in range(0x50):
        if not e or e == FX_ACTIVE: break
        rec = g.read(e, 0x50)
        if rec[0xc] == 15 and rec[0xe] == 1 and struct.unpack_from('<i', rec, 0x4c)[0] == 0:
            out[e] = struct.unpack_from('<Hi', rec, 0x44)[0], struct.unpack_from('<i', rec, 0x48)[0]
        e = struct.unpack_from('<I', rec, 4)[0]
    return out


def fighter_sprites(g):
    fx = g.read(FX_SPRITES, 192)
    return any(struct.unpack_from('<h', fx, 64 * i + 2)[0] > 0 and struct.unpack_from('<H', fx, 64 * i + 0x22)[0] == 503
               and struct.unpack_from('<H', fx, 64 * i + 0x14)[0] in (368, 496) for i in range(3))


def drawn(g, frame, effects):
    """How frame `frame` drew the ball's effect: ('32', (x, y), box) its own quad (its 32 x 32 cell), ('64', (x, y),
    box) a quad from the upper half on player 1's palettes (its cell), (None, None, None) neither; box: the quad's
    corners on screen."""
    own = {(e + 0x50 + 40 * b + 4) & 0x1fffff for e in effects for b in (0, 1)}   # src: the word after the tag
    up = None
    entries = g.q(cmd='gpu_frame_dump', frame=frame, count=16384).get('entries', [])
    if DEBUG:
        ft4 = [c for c in entries if 0x2c <= int(c['op'], 16) <= 0x2f]
        print(f'    dump {frame}: {len(entries)} entries, {len(ft4)} FT4, own {[hex(o) for o in own]}, '
              f'ring {g.q(cmd="gpu_ring_stats")}', flush=True)
        for c in ft4:
            if (int(c['w'][2], 16) >> 16) >> 6 in (503, 384, 416) or int(c['src'], 16) & 0x1fffff in own:
                print('     ', c['src'], c['w'][:5], flush=True)
    def box(w): return [((v & 0xffff) - ((v & 0x8000) << 1), (v >> 16) - ((v >> 15 & 1) << 16)) for v in w[1:9:2]]
    for c in entries:
        if not 0x2c <= int(c['op'], 16) <= 0x2f or len(c['w']) < 9: continue
        w = [int(v, 16) for v in c['w']]
        if int(c['src'], 16) & 0x1fffff in own:     # its 32 x 32 cell, in the lower half
            u, tpage = min(w[2] & 0xff, w[4] & 0xff), w[4] >> 16 & 0xffff
            return '32', ((tpage & 15) * 64 + u // 4, (tpage >> 4 & 1) * 256 + (w[2] >> 8 & 0xff)), box(w)
        clut, tpage = w[2] >> 16, w[4] >> 16 & 0xffff
        # Player 1's palettes: column 560, rows 896 on (one an image for a pack fading by palettes), upper half.
        if clut & 0x8000 and clut & 0x3f == 560 >> 4 and 896 <= 512 + (clut >> 6 & 0x1ff) < 928 and tpage & 0x800:
            u = min(w[2] & 0xff, w[4] & 0xff)
            up = ((tpage & 15) * 64 + u // 4, 512 + (tpage >> 4 & 1) * 256 + (w[2] >> 8 & 0xff)), box(w)
    return ('64',) + up if up else (None, None, None)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=Path)
    ap.add_argument('--build', default='build-dbg')
    ap.add_argument('--data', default=DATA)
    ap.add_argument('--fighter', default='jin')
    ap.add_argument('--ps2', choices=('on', 'off'), default='on')
    ap.add_argument('--tries', type=int, default=12, help='charging moves tried at most')
    ap.add_argument('--film', action='store_true')
    ap.add_argument('--memcard-dir', default=str(ROOT / 'saves'), help='cards copied in (read only)')
    ap.add_argument('--debug', action='store_true')
    a = ap.parse_args()
    global DEBUG; DEBUG = a.debug
    out = a.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    build, data = (ROOT / a.build).resolve(), Path(a.data).resolve()
    images = packs(data)
    guest = a.fighter not in BALL_CELLS
    if guest:
        names = [l.split()[0] for l in (data / 'ttt1/guests.txt').read_text().splitlines() if l.split()]
        gid = 23 + [n.lower() for n in names].index(a.fighter.lower())
        name = names[gid - 23].split('-')[0].capitalize()
    else: name = PACK[a.fighter]
    want = f"{name}-{'PS2' if a.ps2 == 'on' and name in MISHIMA else 'TTT1'}"
    film = out / 'film'
    if a.film:
        shutil.rmtree(film, ignore_errors=True); film.mkdir()

    view = view_of(build, data, f'b133-{a.ps2}')
    env = [('TEKKEN3_PS2_EFFECTS', a.ps2), ('TEKKEN3_TTT_PS2_LASER_DIR', str(data / 'ttt-ps2-laser'))]
    real = subprocess.Popen
    def popen(args, **kw):                   # a copy of the cards in the game's own folder, as it starts
        if '--memcard-dir' in args:
            for card in ('card1.mcd', 'card2.mcd'):
                if (Path(a.memcard_dir) / card).is_file(): shutil.copy2(Path(a.memcard_dir) / card, args[args.index('--memcard-dir') + 1])
        return real(args, **kw)
    subprocess.Popen = popen
    try: g = H.Game(view, f'b133-{a.ps2}', env=env)
    finally: subprocess.Popen = real
    rows, frames, first, hi_path = [], {}, None, out / 'high-vram.bin'
    try:
        g.wait(lambda: g.value(SCREEN) >= 2, 'the game did not boot', 120)
        to_ball(g)
        pick(g, 'jin' if guest else a.fighter)
        if guest:
            for _ in range(30): g.write(LOADING_P1, struct.pack('<H', gid)); time.sleep(.01)
        g.wait(lambda: g.value(SCREEN) == 8 and g.value(PHASE, 2) >= 6 and g.value(ACTOR + 0x54) != 0,
               'the fight never started', 90)
        ball = g.value(BALL_STATE)
        g.wait(lambda: g.value(ball, 2) == 9, 'the ball never floated at the serve', 30)
        g.wait(lambda: g.value(ACTOR + 0x1a4) == 0, 'player 1 never settled', 10)
        g.q(cmd='turbo', enabled=0)
        g.q(cmd='savestate', op='save', slot=SLOT)
        rows.append(f'B133 {a.fighter} ({name}) PS2 EFFECTS {a.ps2}: ball {ball:#x}, {want} wanted')
        moves = charging(g)
        rows.append(f'charging moves (alias, id, damage): {[(al, hex(mid), dmg) for al, _, mid, dmg in moves]}')
        assert moves, "no move of player 1's charges the ball"
        for alias, record, move_id, damage in moves[:a.tries]:
            move = f'alias {alias} ({move_id:#x}, {damage})'
            for d in DISTANCES:
                g.q(cmd='savestate', op='load', slot=SLOT); g.frames(2)
                x1, x2 = signed(g.value(ACTOR)), signed(g.value(ACTOR + STRIDE))
                g.write(ball + 0x68, struct.pack('<i', x1 + (d if x2 > x1 else -d)))
                g.write(ball + 0x70, struct.pack('<i', signed(g.value(ACTOR + 8))))
                if a.film: g.q(cmd='film', dir=film.as_posix(), frames=1000000)
                f0 = g.frame()
                g.write(ACTOR + 0x1a0, struct.pack('<HHI', alias, g.value(ACTOR + 0x1a2, 2), record))   # one write: one frame
                seen, ball_seen = {}, set()
                while g.frame() < f0 + 150:
                    fx = ball_effects(g)
                    b = g.read(ball, 0x148)
                    ball_seen.add((struct.unpack_from('<h', b, 0)[0], struct.unpack_from('<h', b, 0x140)[0], b[0x146]))
                    if not fx:
                        if seen: break
                        continue
                    f = g.frame() - 1
                    if first is None: first = (move, d, f, g.q(cmd='film')['written'] if a.film else -1)
                    seen.setdefault('fx', set()).update(fx); seen['last'] = f; seen.setdefault('first', f)
                    if fighter_sprites(g): seen['fighter'] = True
                if a.film: g.q(cmd='film', dir=film.as_posix(), frames=0)
                print(f'  {move} at {d}: ball (state, power, mode) {sorted(ball_seen)}, effect frames {len(seen)}', flush=True)
                if seen:
                    # Each frame it lived, read back from the GP0 ring (some 850 frames): the effects' quads, both buffers.
                    span = range(seen['first'], seen['last'] + 2)
                    rows.append(f"{move} with the ball at {d}: the effect lived from frame {span[0]} to {span[-1]}"
                                + (", a fighter's strong-hit sprite alive too" if seen.get('fighter') else ''))
                    frames = {f: drawn(g, f, seen['fx']) for f in span}
                    break
                first = None
            if frames: break
        if not frames: raise AssertionError('no hit charged the ball')
        g.q(cmd='high_vram', path=hi_path.as_posix()); hi = hi_path.read_bytes()
        failures, shots = [], []
        for f in sorted(frames):
            how, at, corners = frames[f]
            if how is None: continue                     # neither in that frame's commands (not in the ring)
            which, k = '?', None
            if how == '32': which, k = '32 x 32', [2 * (at[1] // 32) + (at[0] - 368) // 8]
            if how == '64':
                x, y = at
                read = b''.join(hi[2 * ((y - 512 + r) * 1024 + x):2 * ((y - 512 + r) * 1024 + x + 16)] for r in range(64))
                hits = sorted((n, i) for n, ims in images.items() for i, im in enumerate(ims) if im == read)
                which = '|'.join(sorted({n for n, _ in hits})) or '?'
                k = sorted({i for _, i in hits})
            bad = []
            if how == '32': bad.append('drawn 32 x 32')
            elif want not in which.split('|'): bad.append(f'not {want}')
            elif not set(k) & set(LOOP): bad.append(f'images {k}, not among 9 to 20')
            rows.append(f'  frame {f}: {how} x {how}' + (f' at {at}, {which} images {k}' if at else '')
                        + (' -- FAIL: ' + ', '.join(bad) if bad else ''))
            if bad: failures.append(rows[-1])
            shots.append({'frame': f, 'film': f - first[2] + first[3] if a.film else -1, 'how': how, 'pack': which,
                          'images': k, 'box': corners})
        if sum(how is not None for how, *_ in frames.values()) < 3: failures.append('fewer than 3 frames read')
        log = g.log()
    finally:
        g.stop()
        for p in [view / 'bios'] + [p for p in (view / 'mods').iterdir() if p.is_dir()]:
            subprocess.run(['cmd', '/c', 'rmdir', str(p)], capture_output=True)
        shutil.rmtree(view, ignore_errors=True)
    (out / 'game.log').write_text(log)
    if a.film and first: (out / 'film.txt').write_text(f'{first[0]} at {first[1]}: effect first seen at film frame {first[3]}\n')
    (out / 'effects.json').write_text(json.dumps(shots, indent=1))
    (out / 'effects.txt').write_text('\n'.join(rows) + '\n')
    print('\n'.join(rows))
    if failures:
        print('B133: FAILED\n  ' + '\n  '.join(failures)); sys.exit(1)
    print('B133: OK')


if __name__ == '__main__':
    main()
