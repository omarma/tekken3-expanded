#!/usr/bin/env python3
"""PS2 EFFECTS in the attract's Embus (B131, GH#176): the Mishima's PS2 strong-hit effects there too.

    python ressources/slot.py --kind game --who b131 --prio 2 -- \\
        python tools/test_b131_embu_ps2_sparks.py OUT [--build build-dbg] [--data <install>/mods] [--ps2 on|off]
            [--embus 3] [--film]

Build: PSX_DEBUG_TOOLS=ON (the debug server's high_vram). --data: the mods folder of an install (TTT1 catalogue at
import version 10 or later, TTT Stages, TTT Cinematics and the PS2 EFFECTS pack, read in place). A new card, the
attract left alone from the modes menu: the Embus' rotation (TIPS section 135 on, B104) plays the TTT Embu (the
cinematic engine, state 8, its player 1's `effect` Jin's), then the guests' Embu (Tekken 3's variant 0, state 6,
Kazuya in Jin's part), then variant 0 with the natives. tools/test_embu_guest_sparks.py's way of reading the effects:
each strong-hit effect (a sprite of 0x800A3408 alive, palette row 503, pack at x 368 for player 1, 496 for player 2)
noted with the length of its player's effect entry (0x800A35C8 + 16 * player) and whose 64 x 64 lies in the player's
cells of the upper half (images and palette 0 at (560, 896 + 32 * player), against the catalogue's
*-TTT1-hiteffect64.hfx and the PS2 pack's *-PS2-hiteffect64.hfx).

Checks (exit 1 otherwise): with --ps2 on, every effect of player 1 in Jin's part (the TTT Embu's, the guests' Embu's
Kazuya, variant 0's Jin) draws the PS2 pack of whoever plays it (Jin-PS2, or Kazuya-PS2 for the guest), its entry
of that pack's length; player 2's (Yoshimitsu's part, Kunimitsu, Paul in the TTT Embu) are no Mishima: never a PS2
pack. With --ps2 off, no PS2 pack anywhere. At least one effect of player 1 in each Embu.

--film: every VBlank's PS1 display area as raw BGRA under OUT/film (the local `film` command of the debug server,
not in the repository: TIPS.md section 206), from each Embu's first frame (OUT/film/embu-N), OUT/film.txt giving
the film frame each effect was first seen at.
"""
import argparse, os, shutil, struct, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/arcade_stages'), str(ROOT / 'psxrecomp/tools')]
import test_hit_effect_64 as H
from test_embu_guest_sparks import cell, whose

DATA = 'C:/Users/omarm/Desktop/Tekken3Expanded-1.4.1-Windows/tekken3-expanded-1.4.1/build-release/mods'
SCREEN, START = 0x800ae204, 0xfff7
ACTOR, STRIDE = 0x800a9228, 0x188c
FX_SPRITES, EFFECT_ROWS = 0x800a3408, 0x800a35c8
FROM_DATA = ('ttt1', 'arcade-stages', 'ttt-stages', 'ttt-cinematics', 'ttt-music', 'ttt-ps2-music', 'ttt-ps2-laser')


def packs(data):
    """{name: palette 0 and images} of every 64 x 64 pack (TTT1's and PS2's), and each one's length."""
    big, frames = {}, {}
    for f in list((data / 'ttt1').glob('*-hiteffect64.hfx')) + list((data / 'ttt-ps2-laser').glob('*-hiteffect64.hfx')):
        try: n, pals, images = H.hfx(f)
        except AssertionError: continue
        name = f.name[:-len('-hiteffect64.hfx')]
        big[name], frames[name] = [pals[0]] + images, n
    return big, frames


def turn(log):
    """The Embus' rotation's last choice in the log: ttt (the cinematic), guests, v0, v1, v2."""
    for l in reversed(log.splitlines()):
        if 'Cine trigger: Embu rotation, ' in l:
            w = l.split('Embu rotation, ')[1].split()[0]
            return 'ttt' if w.endswith('.cine') else w
    return '?'


def view_of(build, data, tag):
    """A build to run: the build's executable, BIOS and mods files, the data folders of the install."""
    view = H.WORK / f'b131-view-{os.getpid()}-{tag}'
    shutil.rmtree(view, ignore_errors=True); (view / 'mods').mkdir(parents=True)
    junction = lambda link, target: subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                                                   check=True, capture_output=True)
    for p in (build / 'mods').iterdir():
        if p.is_file(): shutil.copy2(p, view / 'mods' / p.name)
        elif p.name not in FROM_DATA: junction(view / 'mods' / p.name, p)
    for name in FROM_DATA:
        if (data / name).is_dir(): junction(view / 'mods' / name, data / name)
    exe = next(p for p in (build / 'Tekken_3_Expanded.exe', build / 'Tekken_3_Expanded') if p.exists())
    os.link(exe, view / exe.name)
    junction(view / 'bios', build / 'bios')
    return view


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=Path)
    ap.add_argument('--build', default='build-dbg')
    ap.add_argument('--data', default=DATA)
    ap.add_argument('--ps2', choices=('on', 'off'), default='on')
    ap.add_argument('--embus', type=int, default=3)
    ap.add_argument('--film', action='store_true')
    a = ap.parse_args()
    out = a.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    build, data = (ROOT / a.build).resolve(), Path(a.data).resolve()
    big, frames = packs(data)
    film = out / 'film'
    if a.film:
        shutil.rmtree(film, ignore_errors=True); film.mkdir()

    view = view_of(build, data, a.ps2)
    env = [('TEKKEN3_PS2_EFFECTS', a.ps2), ('TEKKEN3_TTT_PS2_LASER_DIR', str(data / 'ttt-ps2-laser'))]
    g = H.Game(view, f'b131-{a.ps2}', env=env)
    rows, effects, filmed, turns = [], [], [], []
    try:
        g.wait(lambda: g.value(SCREEN) >= 2, 'the game did not boot', 120)
        def menu():
            if g.value(SCREEN) == 3: g.press(START)
            return g.value(SCREEN) == 4
        g.wait(menu, 'the modes menu never came', 240)
        embu, armed, cines, ended, seen, hi_path = 0, True, 0, 0, {}, out / 'high-vram.bin'
        kind, checked = None, 0.0
        deadline = time.monotonic() + 1800
        while time.monotonic() < deadline:
            state = g.value(SCREEN)
            # An Embu: Tekken 3's (state 6, over when the state changes) or the TTT Embu (the scene, state 8, from
            # the log's 'Cine: "embu" plays' to its 'over'). The attract's demo fights (state 8) are left out.
            if kind == 6 and state != 6: kind = None
            if kind == 'ttt' and time.monotonic() > checked + .5:
                checked = time.monotonic()
                if g.log().count('Cine: "embu" over') > ended: ended, kind = ended + 1, None
            if kind is None:
                if a.film and embu and not armed: g.q(cmd='film', dir=(film / f'embu-{embu}').as_posix(), frames=0)
                armed = True
                if embu >= a.embus: break
                log = g.log() if state in (6, 8) else ''
                if state == 6 and turn(log) != 'ttt': kind = 6       # the TTT Embu's turn: state 6, then its scene
                elif state == 8 and log.count('Cine: "embu" plays') > cines: kind, cines = 'ttt', cines + 1
                else: time.sleep(.05); continue
                armed, embu = False, embu + 1
                turns.append(turn(log))
                rows.append(f'Embu {embu} ({turns[-1]}) from frame {g.frame()}, state {state}, variant {g.value(0x80097f20, 1)}')
                if a.film:
                    (film / f'embu-{embu}').mkdir()
                    g.q(cmd='film', dir=(film / f'embu-{embu}').as_posix(), frames=1000000)
            fx = g.read(FX_SPRITES, 192)
            for i in range(3):
                life, = struct.unpack_from('<h', fx, 64 * i + 2)
                base, = struct.unpack_from('<H', fx, 64 * i + 0x14)
                clut_y, = struct.unpack_from('<H', fx, 64 * i + 0x22)
                key = (i, base)
                if life <= 0 or clut_y != 503 or base not in (368, 496):
                    seen.pop(key, None); continue
                if key in seen: continue
                seen[key] = life
                p = base == 496
                at_film = g.q(cmd='film')['written'] if a.film else -1     # no dir: the count, not a new film
                g.frames(3)
                native = g.value(ACTOR + p * STRIDE + 0x14, 2) >> 2
                header = g.value(EFFECT_ROWS + 16 * p)
                images = g.value(header, 2)
                g.q(cmd='high_vram', path=hi_path.as_posix()); hi = hi_path.read_bytes()   # slashes: no escapes in its JSON
                at = 2 * ((896 + 32 * p - 512) * 1024 + 560)
                read64 = [hi[at:at + 32]]
                for k in range(32):
                    x, y = cell(p, k)
                    read64.append(b''.join(hi[2 * ((y - 512 + r) * 1024 + x):2 * ((y - 512 + r) * 1024 + x + 16)] for r in range(64)))
                pack64 = whose(big, read64)
                effects.append({'embu': embu, 'state': g.value(SCREEN), 'frame': g.frame(), 'player': p + 1,
                                'native': native, 'images': images, 'life': life, 'pack64': pack64, 'film': at_film})
                if a.film: filmed.append(f"embu {embu} P{p + 1} {pack64}: film frame {at_film} at life {life}")
        log = g.log()
    finally:
        if a.film:
            try: g.q(cmd='film', dir=(film / f'embu-{embu}').as_posix(), frames=0)
            except Exception: pass
        g.stop()
        for p in [view / 'bios'] + [p for p in (view / 'mods').iterdir() if p.is_dir()]:
            subprocess.run(['cmd', '/c', 'rmdir', str(p)], capture_output=True)
        shutil.rmtree(view, ignore_errors=True)
    (out / 'game.log').write_text(log)
    if a.film: (out / 'film.txt').write_text('\n'.join(filmed) + '\n')

    # Jin's part (player 1): Jin in the TTT Embu and in Tekken 3's variants, the guest cast in it in the guests' Embu
    # ("TTT1 Embu: P1 Kazuya on jin's model").
    guest = next((l.split('TTT1 Embu: P1 ')[1].split()[0] for l in log.splitlines()
                  if 'TTT1 Embu: P1 ' in l and "on jin's model" in l), None)
    rows.append(f"Jin's part in the guests' Embu: {guest}")
    failures = []
    for e in effects:
        bad, names = [], e['pack64'].split('|')
        ps2 = [n for n in names if n.endswith('-PS2')]
        if a.ps2 == 'off' and ps2: bad.append('a PS2 pack with PS2 EFFECTS off')
        elif a.ps2 == 'on' and e['player'] == 1:
            who = (guest or '?') if turns[e['embu'] - 1] == 'guests' else 'Jin'
            if f'{who}-PS2' not in names: bad.append(f'not {who}-PS2')
            elif e['images'] != frames[f'{who}-PS2']: bad.append(f"entry of {e['images']} images, {frames[f'{who}-PS2']} wanted")
        elif a.ps2 == 'on' and ps2: bad.append('a PS2 pack for player 2')
        rows.append(f"Embu {e['embu']} (state {e['state']}) frame {e['frame']} P{e['player']} ID {e['native']}: entry of "
                    f"{e['images']} images, 64 x 64 {e['pack64']}" + (' -- FAIL: ' + ', '.join(bad) if bad else ''))
        if bad: failures.append(rows[-1])
    for n in range(1, a.embus + 1):
        if not any(e['embu'] == n and e['player'] == 1 for e in effects): failures.append(f'no effect of player 1 in Embu {n}')
    (out / 'effects.txt').write_text('\n'.join(rows) + '\n')
    print('\n'.join(rows))
    if failures:
        print('B131: FAILED\n  ' + '\n  '.join(failures)); sys.exit(1)
    print('B131: OK')


if __name__ == '__main__':
    main()
