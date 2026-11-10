#!/usr/bin/env python3
"""B134 (GH#183): a native on its TTT1 moves keeps its 64 x 64 strong-hit effect after a guest.

    python ressources/slot.py --kind game --who b134 --prio 2 -- \\
        python tools/test_b134_native_ttt1_hit_effect.py [--build build-rel-lite] [--data <install>/mods]
            [--ps2 on|off] [--before lee|<guest>|paul|<native>] [--native heihachi|jin|<native>]
            [--frames OUT] [--visible]

Build: a debug server (rel-lite or PSX_DEBUG_TOOLS=ON). --data: the mods folder of an install (TTT1 catalogue at
import version 10 or later and the PS2 EFFECTS packs, read in place; tools/test_b131_embu_ps2_sparks.py view_of).

The pack a fighter's 64 x 64 is drawn from (src/tekken3_ttt1_combat.c hit_effect_64_pack, ps2_hfx_for) is the
slot's own, a guest's, while hit_effect_in_fight[player] is set: place_hit_effect sets it once it has put a guest's
32 x 32 in VRAM. The fight tick cleared it for a player off TTT1 moves only; a native on its TTT1 moves (motion
mode 4) never places a pack, so it kept the value of the guest before it. Its slot (Heihachi-TTT1) has no 32 x 32
and so no 64 x 64: the 32 x 32 of Tekken 3 played, and under PS2 EFFECTS no PS2 pack either (the guest branch looks
for Kazuya, Devil and Angel only). Team Battle gives that order without a selector in between (GH#183: the CPU's
Unknown, then its Heihachi on TTT1 moves, player 1's Armor King in both fights). Not every time: any tick between
the two fights where the player is off TTT1 moves or its moves are not ready (player 1 changing fighters, no guest
left in the fight) cleared it on the way.

Team Battle from the menu (no save state), every native on TTT1 moves (TEKKEN3_NATIVE_MOVES=1), no guest drawn
for the CPU. Once the first fight has loaded the CPU's team becomes (first), --before, --native and player 1's
(first), --p1, --p1: player 1 is knocked out until --p1 fights, then stands (its life written back) while the
CPU's knock-outs are written until --native fights. Then, for up to 120 s:

  - its effect entry (0x800A35C8 + 16): under PS2 EFFECTS for Jin and Heihachi, our header (not the stock one at
    0x80027950 + 6 * ID) with the PS2 pack's length;
  - every frame the CPU's strong-hit sprite lives (TEKKEN3_HIT_EFFECT_TRACE: base 496, palette row 503), whether
    its quad was replaced by a 64 x 64 one.

Exit 1 when the entry is not ours (PS2 on) or fewer than 90 % of the living frames have a 64 x 64 quad.
--frames OUT: a screenshot of each of the first 12 effects seen (life 6..14), OUT/NN-lifeL.png.
"""
import argparse, re, shutil, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/arcade_stages'), str(ROOT / 'psxrecomp/tools')]
import ttt1_live as L
import test_hit_effect_64 as H
from test_b131_embu_ps2_sparks import DATA, view_of

STATE, PHASE = 0x800AE204, 0x800AE224
TEAMS, TEAM_STRIDE = 0x800AFA88 + 89, 13
ACTOR, STRIDE, LIFE = 0x800A9228, 0x188C, 0x3F6
EFFECT_ROWS, HEADERS, HEADER, FX_SPRITES = 0x800A35C8, 0x80027950, 6, 0x800A3408
STOCK = ['paul', 'law', 'lei', 'king', 'yoshimitsu', 'nina', 'hwoarang', 'xiaoyu', 'eddy', 'jin', 'julia', 'kuma',
         'bryan', 'heihachi', 'ogre', 'mokujin', 'gunjack']
PS2 = {'jin': 'Jin', 'heihachi': 'Heihachi'}
SPRITE = re.compile(r'TTT Hitspark trace: sprite (\d) life (-?\d+) clut row (\d+) base (\d+)')
QUAD = re.compile(r'TTT Hitspark trace: quad [0-9A-F]+ slot (\d+), replaced')


def fighter(s, p): return s.value(ACTOR + p * STRIDE + 0x18, 2)


def frames(log):
    """The CPU's living strong-hit frames in a stretch of trace, and how many had their quad replaced."""
    alive = replaced = 0
    base = {}
    for line in log.splitlines():
        m = SPRITE.search(line)
        if m:
            i, life, row, b = map(int, m.groups())
            base[i] = b if row == 503 and life > 0 else None
            if base[i] == 496: alive += 1
            continue
        m = QUAD.search(line)
        if m and base.get(int(m.group(1))) == 496: replaced += 1
    return alive, replaced


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--data', default=DATA)
    ap.add_argument('--ps2', choices=('on', 'off'), default='on')
    ap.add_argument('--before', default='lee', help="the CPU's member before --native: a guest or a native")
    ap.add_argument('--native', default='heihachi')
    ap.add_argument('--p1', default='armorking', help="player 1's guest through the CPU's fights")
    ap.add_argument('--seconds', type=float, default=120)
    ap.add_argument('--frames', type=Path)
    ap.add_argument('--visible', action='store_true')
    a = ap.parse_args()
    build, data = (ROOT / a.build).resolve(), Path(a.data).resolve()
    catalogue = [l.split()[0] for l in (data / 'ttt1/guests.txt').read_text().splitlines() if l.split()]
    before = L.GUEST_ID + catalogue.index(a.before) if a.before in catalogue else STOCK.index(a.before)
    native = STOCK.index(a.native)
    p1 = L.GUEST_ID + catalogue.index(a.p1)
    ps2 = a.ps2 == 'on' and a.native in PS2
    want = H.hfx(data / f'ttt-ps2-laser/{PS2[a.native]}-PS2-hiteffect64.hfx')[0] if ps2 else None
    view = view_of(build, data, f'b134-{a.native}-{a.ps2}')
    env = {'TEKKEN3_NATIVE_MOVES': '1', 'TEKKEN3_TEAM_GUESTS': '1,0,0', 'TEKKEN3_HIT_EFFECT_TRACE': '1',
           'TEKKEN3_PS2_EFFECTS': a.ps2, 'TEKKEN3_TTT_PS2_LASER_DIR': str(data / 'ttt-ps2-laser')}
    s = L.Session(guest=a.before if a.before in catalogue else catalogue[0], build=view, line=2, visible=a.visible,
                  env=env)
    failures = []
    full = [0]

    def stand():
        """Player 1's life back to the most it had."""
        life = s.value(ACTOR + LIFE, 2)
        if life > full[0]: full[0] = life
        elif life < full[0]: s.write(ACTOR + LIFE, full[0], 2)

    def until(p2, seconds=300):
        """Knock out player 1 until --p1 fights, then the CPU's fighters until p2 fights and the round runs."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if s.process.poll() is not None: raise RuntimeError('the game exited')
            if s.value(STATE) != 8 or s.value(PHASE, 2) != 8: time.sleep(.05); continue
            if fighter(s, 0) != p1: s.write(ACTOR + LIFE, 0, 2); time.sleep(.3)
            elif fighter(s, 1) != p2: stand(); s.write(ACTOR + STRIDE + LIFE, 0, 2); time.sleep(.3)
            else: stand(); time.sleep(1.5); return
        raise AssertionError(f'the CPU never fought with {p2}')

    try:
        time.sleep(3)
        for _ in range(2): s.press(0xffdf)                                       # three members
        s.press(0xbfff); time.sleep(.8)
        for _ in range(6):
            s.press(0xfff7)                                                     # Start: the teams are drawn
            if s.value(STATE) != 10: break
            time.sleep(.8)
        s.wait(lambda: s.value(STATE) == 8 and s.value(PHASE, 2) >= 6, 'the first fight did not load', 180)
        if s.value(TEAMS + TEAM_STRIDE + 12, 1) < 3: raise RuntimeError('the CPU has fewer than 3 members')
        for i, cid in enumerate((before, native)): s.write(TEAMS + TEAM_STRIDE + 1 + i, cid * 4, 1)
        for i in (1, 2): s.write(TEAMS + i, p1 * 4, 1)
        s.write(TEAMS + 10, s.value(TEAMS + 12, 1), 1)                          # all picked: no redraw at a loading
        until(before)
        for _ in range(12): stand(); time.sleep(.25)
        until(native)
        start = len(s.log())
        moves = [l for l in s.log().splitlines() if f'P2 {a.native.capitalize()} on the TTT1 moveset' in l]
        if not moves: failures.append(f'the CPU\'s {a.native} is not on its TTT1 moves')
        end, entries, grabbed, polled = time.monotonic() + a.seconds, set(), 0, 0
        if a.frames: a.frames.mkdir(parents=True, exist_ok=True)
        while time.monotonic() < end:
            if s.process.poll() is not None: raise RuntimeError('the game exited')
            if s.value(STATE) == 8 and fighter(s, 1) == native:
                stand()
                at = s.value(EFFECT_ROWS + 16)
                entries.add((at, s.value(at, 2)))
                if a.frames and grabbed < 12:
                    sprites = s.read(FX_SPRITES, 3 * 64)
                    life = max([int.from_bytes(sprites[64 * i + 2:64 * i + 4], 'little', signed=True) for i in range(3)
                                if int.from_bytes(sprites[64 * i + 0x14:64 * i + 0x16], 'little') == 496
                                and int.from_bytes(sprites[64 * i + 0x22:64 * i + 0x24], 'little') == 503], default=0)
                    if 6 <= life <= 14:
                        s.q(cmd='screenshot_file', path=str(a.frames / f'{grabbed:02d}-life{life}.png')); grabbed += 1
                        time.sleep(.6)
            if time.monotonic() - polled > .5:
                polled = time.monotonic()
                if frames(s.log()[start:])[0] >= 60: break
            time.sleep(.03)
        alive, replaced = frames(s.log()[start:])
        stock = HEADERS + HEADER * native
        print(f'P2 {a.native} after {a.before}, PS2 EFFECTS {a.ps2}: entries ' +
              ', '.join(f'{e:08X} ({n} images{", stock" if e == stock else ""})' for e, n in sorted(entries)) +
              f'; strong-hit frames {alive}, 64 x 64 quads {replaced}', flush=True)
        if ps2 and not any(e != stock and n == want for e, n in entries):
            failures.append(f'the effect entry never held the PS2 pack\'s header ({want} images)')
        if alive < 10: failures.append(f'only {alive} living frames of the CPU\'s effect: no strong hit landed')
        elif replaced < .9 * alive: failures.append(f'{replaced} of {alive} frames drawn in 64 x 64')
    finally:
        s.stop()
        for p in [view / 'bios'] + [p for p in (view / 'mods').iterdir() if p.is_dir()]:
            subprocess.run(['cmd', '/c', 'rmdir', str(p)], capture_output=True)
        shutil.rmtree(view, ignore_errors=True)
    for f in failures: print('FAIL', f)
    print('B134:', 'OK' if not failures else 'FAILED')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
