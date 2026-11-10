#!/usr/bin/env python3
"""The light a PS2 strong-hit effect casts on the models takes the PS2 effect's colour (B132, GH#180).

    python ressources/slot.py --kind game --who b132 --prio 2 -- \\
        python tools/test_b132_ps2_spark_light.py OUT [--build build-dbg] [--data <install>/mods]
            [--fighter angel|jin|kazuya|devil|heihachi|unknown|paul|<guest>] [--ps2 on|off] [--frames]

Build: PSX_DEBUG_TOOLS=ON. --data: the mods folder of an install (TTT1 catalogue at import version 10 or later and
the PS2 EFFECTS pack, read in place; tools/test_b131_embu_ps2_sparks.py view_of).

A strong hit spawns the attacker's effect (0x8007641C) and lights the models with the colour of the 6-byte header
its effect entry points at (0x800A35C8 + 16 * player; hit_light_set 0x80039F0C: the colour matrix 0x8009E5C0,
entries 1, 4, 7 = R, G, B << 4, for 48 frames, timer 0x8009E5EC). Under a PS2 pack the entry points at our header
(src/tekken3_ttt1_combat.c ps2_hfx_lengths), whose light was the header it replaced: Tekken 3's blue (0, 192, 255)
for Jin and Heihachi, the nearest stock header for the guests.

Practice, player 1 the fighter against the Jin dummy, face to face (savestate 1), a strong hit that lands
(tools/test_hit_effect_64.py's moves; the EWGF for Devil and Angel). While the light lives its colour is read from
the colour matrix, and the header the entry points at.

Checks (exit 1 otherwise): a light was set; with --ps2 on for Jin, Heihachi, Kazuya, Devil, Angel and Unknown (F33), its colour is
the PS2 pack's (every pixel of every image in its palette, summed, scaled to 255 at the strongest channel:
ps2_light below, the engine's ps2_hfx_light); otherwise the colour of a stock header (0x80027950 + 6 * ID), the
one the entry points at.

--frames: the displayed images around the hit (display ring, one replay per slice of 8), OUT/frames/NNN.png.
"""
import argparse, shutil, struct, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/arcade_stages'), str(ROOT / 'psxrecomp/tools')]
import test_hit_effect_64 as H
import test_b67_machine_gun_cannon as B
from test_b131_embu_ps2_sparks import DATA, view_of

COLOUR_MATRIX, LIGHT_TIMER, EFFECT_ROWS = 0x8009e5c0, 0x8009e5ec, 0x800a35c8
HEADERS, HEADER, STOCK = 0x80027950, 6, 22
# The fighters with a PS2 pack: the Mishima, and Unknown (F33: her own, whatever style she copies; here Kazuya's,
# TEKKEN3_TETSUJIN_MOVESET, for the EWGF).
MISHIMA = {'jin': 'Jin', 'heihachi': 'Heihachi', 'kazuya': 'Kazuya', 'devil': 'Devil', 'angel': 'Angel',
           'unknown': 'Unknown'}


def ps2_light(path):
    """The light of a PS2 pack: its pixels' colours summed, the strongest channel at 255."""
    n, pals, images = H.hfx(path)
    total = [0, 0, 0]
    for k, image in enumerate(images):
        pal = struct.unpack('<16H', pals[k if len(pals) == n else 0])
        rgb = [((v & 31) << 3, (v >> 5 & 31) << 3, (v >> 10 & 31) << 3) for v in pal]
        for byte in image:
            for i in (byte & 15, byte >> 4):
                for c in range(3): total[c] += rgb[i][c]
    top = max(total)
    return tuple(t * 255 // top for t in total) if top else None


def lights(g, moves):
    """From savestate 1: the move; every light colour set while it plays, and the header the entry points at."""
    g.q(cmd='savestate', op='load', slot=1); time.sleep(1.5)
    f0 = g.frame(); B.route(g, moves)
    seen, headers = [], set()
    while g.frame() < f0 + 120:
        m = g.read(COLOUR_MATRIX, 18)
        if g.value(LIGHT_TIMER) > 0:
            rgb = tuple(struct.unpack_from('<h', m, o)[0] >> 4 for o in (2, 8, 14))
            if rgb not in seen: seen.append(rgb)
        headers.add(g.value(EFFECT_ROWS))
    return seen, headers, f0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=Path)
    ap.add_argument('--build', default='build-dbg')
    ap.add_argument('--data', default=DATA)
    ap.add_argument('--fighter', default='angel')
    ap.add_argument('--ps2', choices=('on', 'off'), default='on')
    ap.add_argument('--frames', action='store_true')
    ap.add_argument('--trace', action='store_true', help='TEKKEN3_HIT_EFFECT_TRACE=1: each living sprite in game.log')
    a = ap.parse_args()
    out = a.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    build, data = (ROOT / a.build).resolve(), Path(a.data).resolve()
    want = ps2_light(data / f'ttt-ps2-laser/{MISHIMA[a.fighter]}-PS2-hiteffect64.hfx') \
        if a.ps2 == 'on' and a.fighter in MISHIMA else None
    moves = H.SINGLE.get(a.fighter) or (H.EWGF if a.fighter in ('devil', 'angel', 'unknown') else
                                        [(3, B.pad(B.B_SQ, B.B_TR)), (120, H.N)])
    catalogue = [l.split()[0] for l in (data / 'ttt1/guests.txt').read_text().splitlines() if l.split()]
    H.WORK.mkdir(parents=True, exist_ok=True)
    view = view_of(build, data, f'b132-{a.fighter}-{a.ps2}')
    env = [('TEKKEN3_PS2_EFFECTS', a.ps2), ('TEKKEN3_TTT_PS2_LASER_DIR', str(data / 'ttt-ps2-laser'))]
    if a.fighter == 'unknown': env.append(('TEKKEN3_TETSUJIN_MOVESET', 'kazuya'))
    if a.trace: env.append(('TEKKEN3_HIT_EFFECT_TRACE', '1'))
    g = H.Game(view, f'b132-{a.fighter}-{a.ps2}', env=env, stages='off')
    failures = []
    def check(ok, what):
        print(('ok   ' if ok else 'FAIL ') + what, flush=True)
        if not ok: failures.append(what)
    try:
        H.to_practice(g, a.fighter, catalogue)
        g.write(B.DUMMY, bytes([0]))                 # STAND: no guard
        B.place(g)
        g.q(cmd='savestate', op='save', slot=1); time.sleep(1.5)
        seen, headers, f0 = lights(g, moves)
        stock = {HEADERS + HEADER * i: tuple(g.read(HEADERS + HEADER * i + 2, 3)) for i in range(STOCK)}
        entry = {h: tuple(g.read(h + 2, 3)) for h in headers}
        print(f'{a.fighter}, PS2 EFFECTS {a.ps2}: lights {seen}; entry ' +
              ', '.join(f'{h:08x} {"stock" if h in stock else "ours"} {rgb}' for h, rgb in entry.items()), flush=True)
        check(bool(seen), 'a strong-hit light was set')
        if want:
            check(seen == [want], f'the light is the PS2 pack\'s {want}')
        else:
            check(all(h in stock for h in headers), 'the entry points at a stock header')
            check(bool(seen) and all(rgb in entry.values() for rgb in seen), 'the light is that header\'s')
        if a.frames:
            frames = out / 'frames'; frames.mkdir(exist_ok=True)
            for w0 in range(-4, 44, 8):
                g.q(cmd='savestate', op='load', slot=1); time.sleep(1.0)
                f1 = g.frame(); B.route(g, moves)
                while g.frame() < f1 + 12 + w0 + 9: pass
                for k in range(w0, w0 + 8):
                    try: g.q(cmd='display_ring_get', frame=f1 + 12 + k, path=str(frames / f'{k + 4:03d}.png'))
                    except RuntimeError: pass
                while g.frame() < f1 + 120: time.sleep(.01)
            print(f'images: {frames}')
    finally:
        (out / 'game.log').write_text(g.log())
        g.stop()
        for p in [view / 'bios'] + [p for p in (view / 'mods').iterdir() if p.is_dir()]:
            subprocess.run(['cmd', '/c', 'rmdir', str(p)], capture_output=True)
        shutil.rmtree(view, ignore_errors=True)
    print('FAILED: ' + '; '.join(failures) if failures else 'B132: OK')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
