#!/usr/bin/env python3
"""B130 (GH#174): the first frame of TTT's stage 6 after each load, in Team
Battle with Devil, Angel and True Ogre (Ogre's arena, TTT's stage 6).

    python ressources/slot.py --kind game --who b130 --prio 2 -- \\
        python tools/test_b130_first_frame.py [--fights 4] [--cast devil,kazuya,angel,...] [--film]
            [--build build-rel-lite] [--data <install>/mods] [--out DIR]

(a PSX_DEBUG_SERVER_LITE build; --data: the mods folder of an install, its
stage packs, TTT1 catalogue, music and PS2 EFFECTS pack read in place)

Stage 6's pack leaves a stand-in, a white smiling face, where its switched
images land, (0, 0x200) and (0, 0x240), until the animation's first copy
there (src/tekken3_arcade_stages.c, tanm_prime). Team Battle, STAGES TTT,
both teams drawn by Start (the mod adds no guest: TEKKEN3_TEAM_GUESTS
4,0,0); during the first fight the CPU's members 2.. are written from
--cast, so that stage 6 is loaded again after other stages. The engine's
probe file (TEKKEN3_ARCADE_STAGES_PROBE) then tells, for the first frame
after each load of stage 6 ("pack ttt 6"), whether the copy to (0, 0x200)
("tm sx sy 16 64 0 512") came before it: if not, that frame drew the face
(the bug). Exit 1 on any such frame, or with no stage 6 load at all.

--film: also every VBlank's PS1 display area, from each loading screen to a
second into the fight, as raw BGRA under --out/fight-N (the local `film`
command of the debug server, not in the repository: TIPS.md section 206);
frames mostly black with white in them are listed (the face's flash).
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

TEAMS, TEAM_STRIDE = 0x800afa88 + 89, 13
NATIVE = {'paul': 0, 'law': 1, 'lei': 2, 'king': 3, 'yoshimitsu': 4, 'nina': 5, 'hwoarang': 6, 'xiaoyu': 7,
          'eddy': 8, 'jin': 9, 'julia': 10, 'kuma': 11, 'bryan': 12, 'heihachi': 13, 'ogre': 14,
          'trueogre': 20, 'gunjack': 16, 'gon': 17, 'anna': 18, 'drb': 19}
DATA = 'C:/Users/omarm/Desktop/Tekken3Expanded-1.4.1-Windows/tekken3-expanded-1.4.1/build-release/mods'


def fid(g, who):
    return NATIVE[who] if who in NATIVE else b122.GUEST_ID + g.catalogue.index(who)


def stage6_first_frames(probe: Path):
    """The first frame of stage 6 after each of its loads ("pack ttt 6"):
    (frame, the face replaced before it)."""
    out, loaded, placed = [], False, False
    for line in probe.read_text(errors='replace').splitlines():
        f = line.split()
        if line.startswith('pack '):
            loaded, placed = f[1:3] == ['ttt', '6'], False
        elif line.startswith('tm ') and loaded:
            if f[3:7] == ['16', '64', '0', '512']: placed = True
        elif line.startswith('ttanim ') and loaded:
            out.append((int(f[1]), placed))
            loaded = False
    return out


def flashes(d: Path):
    """Frames mostly black with white in them, on a grid of pixels."""
    found = []
    for k, f in enumerate(sorted(d.glob('*.bgra'))):
        w, h = map(int, re.search(r'_(\d+)x(\d+)', f.name).groups())
        b = f.read_bytes()
        white = black = n = 0
        for y in range(0, h, 4):
            for x in range(0, w, 4):
                i = 4 * (y * w + x)
                px = b[i:i + 3]
                n += 1
                if min(px) > 235: white += 1
                elif max(px) < 8: black += 1
        if black > .4 * n and white > .01 * n: found.append(k)
    return found


def film(g, d: Path, on: bool):
    if on:
        d.mkdir(parents=True, exist_ok=True)
        for f in d.glob('*.bgra'): f.unlink()
        g.q(cmd='film', dir=str(d).replace('\\', '/'), frames=100000)
    g.wait(lambda: g.value(b122.SCREEN) == 8 and g.value(b122.PHASE, 2) >= 6, f'{d.name}: no round', 240)
    time.sleep(1.0)
    if on:
        g.q(cmd='film', dir=str(d).replace('\\', '/'), frames=0)
        return flashes(d)
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cast', default='devil,kazuya,angel,paul,trueogre,jin,devil',
                    help="the CPU's members 2.. (guests.txt keys or natives)")
    ap.add_argument('--fights', type=int, default=4)
    ap.add_argument('--film', action='store_true')
    ap.add_argument('--build', default=str(ROOT / 'build-rel-lite'))
    ap.add_argument('--data', default=DATA)
    ap.add_argument('--seed', default='1')
    ap.add_argument('--out', default=str(ROOT / 'workspace/b130'))
    a = ap.parse_args()
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    g = b122.Game(Path(a.build).resolve(), out / 'run', Path(a.data), 'ttt', a.seed,
                  {'TEKKEN3_TEAM_GUESTS': '4,0,0', 'TEKKEN3_PS2_EFFECTS': 'on',
                   'TEKKEN3_TTT_PS2_LASER_DIR': str(Path(a.data) / 'ttt-ps2-laser')})
    seen = {}
    try:
        b122.to_menu(g, 1)
        b122.to_mode(g, b122.TEAM, 10)
        g.press(b122.CROSS); time.sleep(.8)
        for _ in range(8):
            if g.value(b122.SCREEN) != 10: break
            g.press(b122.START); time.sleep(.8)
        g.wait(lambda: g.value(b122.SCREEN) in (11, 8), 'no first fight', 60)
        seen[1] = film(g, out / 'fight-1', a.film)
        size = g.value(TEAMS + TEAM_STRIDE + 12, 1)
        for i, who in enumerate(w for w in a.cast.split(',') if w):
            if i + 1 >= size: break
            old = g.value(TEAMS + TEAM_STRIDE + i + 1, 1)
            g.write(TEAMS + TEAM_STRIDE + i + 1, fid(g, who) * 4 + (old & 3))
        print(f"the CPU's team of {size}: {g.read(TEAMS + TEAM_STRIDE, 8).hex()}", flush=True)
        for n in range(2, min(a.fights, size) + 1):
            def next_fight():
                if g.value(b122.SCREEN) == 8 and g.value(b122.PHASE, 2) >= 6:
                    g.write(b122.P2_LIFE, 0, 2)          # the CPU's member loses
                return g.value(b122.SCREEN) == 11
            g.wait(next_fight, f'fight {n} never came', 240)
            seen[n] = film(g, out / f'fight-{n}', a.film)
    finally:
        g.stop()
    log = g.logtext()
    for l in log.splitlines():
        if l.startswith('TTT Stages:') or ' loaded from ' in l: print('   ', l.split(' from ')[0])
    if a.film:
        for n, frames in seen.items(): print(f'fight {n}: frames with the white flash {frames or "none"}')
    first = stage6_first_frames(g.run / 'probe.txt')
    for frame, placed in first:
        print(f"stage 6's first frame {frame}: {'the switched images placed' if placed else 'THE STAND-IN FACE DRAWN'}")
    bad = [f for f, placed in first if not placed]
    ok = first and not bad
    print('B130: ' + ('OK' if ok else 'no stage 6 load seen' if not first else f'face drawn at frames {bad}'))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
