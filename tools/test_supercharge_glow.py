#!/usr/bin/env python3
"""The Supercharge's glows sit on the fists of guests as of natives (B66, GH#123).

    python tools/test_supercharge_glow.py --build build-rel-lite [--fighter kazuya,michelle,jin ...]
        [--native-moves ttt1|t3] [--shots N] [--tag NAME] [--rom workspace/ttt1-import/ttt1]

Cold start for each fighter. A guest: the Tag page, player 1 against a still
Jin (tools/test_guest_accessories.py). A native (jin, paul): the Arcade
selector, on its TTT1 moves (TEKKEN3_NATIVE_MOVES, --native-moves). Once the
round runs, player 1 presses 1+2+3+4. The charge leaves two effects
(callback 0x80025310 at +8, limb 6 or 10 | player << 15 at +0x40), which
0x800707F4 puts every frame on the hand bone plus a vector of the 21-entry
table 0x80025334 + 16 x the actor's ID, turned by the hand's matrix: the
fist. A guest's ID (23 on) read past the table (Kazuya (-30, -30, 0), Jack-2
or Bruce thousands of units off). The bench reads each glow's position back
into its hand bone's frame and fails unless it is TTT1's vector for that
character (80157650, table 80023084 + 16 x body: (80, 0, 0) but Roger and
Alex 58, Tetsujin and Unknown 90) within TOLERANCE, or T3's own for a
native. --rom rebuilds TTT1's table from the ROM (tools/ttt1/rom_ram.py)
and checks the expected vectors against it first. --shots N: N pictures of
each fighter's charge (workspace/supercharge-glow), for the eye.
"""
import argparse, json, struct, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_yoshimitsu_win_sparks as Y

T, A = Y.T, Y.A
T.WORK = ROOT / 'workspace/supercharge-glow'
ALL4 = T.pad(T.SQ, T.TR, T.CR, T.CI)
GLOW_CALLBACK, LIMBS = 0x80025310, (6, 10)
SCAN = (0x800c0000, 0x80100000)          # where the effect objects live (0x800E89E8 in a fight)
NATIVES = dict(paul=0, jin=9)            # character IDs; T3's table: Paul 80, Jin 80
T3_REACH = {0: 80, 9: 80}
TTT1_TABLE, TTT1_ENTRIES = 0x23084, 34   # TTT1's glow table in its RAM (rom_ram.boot)
# The guests' TTT1 body codes (tools/data/ttt1_characters.json) give their
# entry: (reach, 0, 0) on both hands.
REACH = dict(roger=58, alex=58, tetsujin=90, unknown=90)
TOLERANCE = 3


def expected(key):
    return T3_REACH[NATIVES[key]] if key in NATIVES else REACH.get(key, 80)


def check_rom(folder):
    """The expected vectors against TTT1's table, rebuilt from the ROM."""
    sys.path.insert(0, str(ROOT / 'tools/ttt1'))
    import rom_ram
    image = rom_ram.boot(folder)
    table = [struct.unpack_from('<8h', image, TTT1_TABLE + 16 * i) for i in range(TTT1_ENTRIES)]
    characters = json.loads((ROOT / 'tools/data/ttt1_characters.json').read_text())['characters']
    bad = []
    for key, c in characters.items():
        entry = table[c['body']]
        want = (expected(key), 0, 0, 0)
        if entry[:4] != want or entry[4:] != want: bad.append((key, c['body'], entry))
    if bad: raise SystemExit(f'FAIL: TTT1 table differs from the bench: {bad}')
    print(f'TTT1 table 80023084 agrees for {len(characters)} guests')


def glows(g):
    """Address and limb of player 1's lit glows. The pool holds one effect
    per limb (fists 6, 10, feet 14, 17, each player) for the whole fight;
    0x800707F4 lights one (+0x0D bit 0x40) while its limb's bit is set in the
    player's mask (0x800A8660, 0x800A8664): the charge sets 6 and 10."""
    lo, hi = SCAN
    raw = b''.join(g.read(a, 0x10000) for a in range(lo, hi, 0x10000))
    out = []
    for a in range(0, len(raw) - 0x48, 4):
        if struct.unpack_from('<I', raw, a + 8)[0] != GLOW_CALLBACK: continue
        limb = struct.unpack_from('<I', raw, a + 0x40)[0]
        if limb in LIMBS and raw[a + 0xd] & 0x40: out.append((lo + a, limb))
    return out


def local(g, glow, limb):
    """The glow's position in its hand bone's frame. Read with the game
    paused: running, the glow (computed at another point of the frame than
    the bones) lags the moving fist by up to 100 units."""
    p = struct.unpack('<3i', g.read(glow + 0x28, 12))
    snap = g.read(T.ACTOR, Y.SNAPSHOT)
    r = struct.unpack_from('<9h', snap, Y.BONES + limb * Y.BONE)
    t = Y.bone(snap, limb)
    d = [p[i] - t[i] for i in range(3)]
    return tuple(round(sum(r[j * 3 + i] * d[j] for j in range(3)) / 4096) for i in range(3))


def pause(g):
    """Start: the pause menu, once the fist stands still between two reads."""
    for _ in range(3):
        g.press(T.START); time.sleep(.6)
        a = g.read(T.ACTOR + Y.BONES, Y.SNAPSHOT - Y.BONES); time.sleep(.3)
        if g.read(T.ACTOR + Y.BONES, Y.SNAPSHOT - Y.BONES) == a: return
    raise AssertionError('Start did not pause the fight')


def run(build, key, moves, shots, tag=''):
    native = key in NATIVES
    env = {'TEKKEN3_NATIVE_MOVES': '1' if moves == 'ttt1' else '0'} if native else {}
    g = Y.Game(build, tag + (f'{key}-{moves}' if native else key), env)
    try:
        if native:
            T.to_selector(g)
            T.cursor_to(g, NATIVES[key])
            g.press(T.SQUARE, frames=12)
            def step():
                if g.value(T.STATE) == 9: g.press(T.SQUARE, frames=12)
            g.wait(lambda: g.value(T.STATE) == 8 and g.value(T.PHASE, 2) >= 8, 'round did not start', 150, step)
            g.write(T.ACTOR + T.STRIDE + 0xc5, 0, 1)            # the opponent stands still
            time.sleep(2)                                       # past READY / FIGHT
        else:
            catalogue = [l.split()[0] for l in (build / 'mods/ttt1/guests.txt').read_text().splitlines() if l.split()]
            A.to_tag_page(g, len(catalogue))
            A.fight(g, catalogue.index(key), len(catalogue), 1)
        time.sleep(1)
        assert not glows(g), 'glows before the charge'
        found = []
        for _ in range(3):                  # a press lost to the round's start: again
            g.q(cmd='press', buttons=ALL4, frames=10)
            end = time.monotonic() + 4
            while len(found) < 2 and time.monotonic() < end:
                time.sleep(.3); found = glows(g)
            if len(found) == 2: break
        if len(found) < 2: raise SystemExit(f'FAIL {key}: the charge left {len(found)} glows')
        time.sleep(.5)
        for k in range(shots): g.shot(f'charge-{k:02d}'); time.sleep(.08)
        pause(g)
        want = expected(key)
        result = []
        for glow, limb in sorted(found, key=lambda x: x[1]):
            v = local(g, glow, limb)
            off = sum((v[i] - (want, 0, 0)[i]) ** 2 for i in range(3)) ** .5
            result.append((limb, v, off))
        return want, result
    finally:
        g.q(cmd='clear_input') if g.process.poll() is None else None
        g.stop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', required=True)
    ap.add_argument('--fighter', default='kazuya,michelle,jun,jin')
    ap.add_argument('--native-moves', choices=('ttt1', 't3'), default='ttt1')
    ap.add_argument('--shots', type=int, default=0, help='pictures of the charge, for the eye')
    ap.add_argument('--tag', default='', help='prefix of the logs and pictures')
    ap.add_argument('--rom', help='TTT1 regions folder (bankedroms.bin, maincpu_rom.bin)')
    a = ap.parse_args()
    T.WORK.mkdir(parents=True, exist_ok=True)
    if a.rom: check_rom(a.rom)
    build = Path(a.build).resolve()
    keys = a.fighter.split(',')
    if keys == ['all']:
        keys = [l.split()[0] for l in (build / 'mods/ttt1/guests.txt').read_text().splitlines() if l.split()] + ['jin']
    failed = []
    for key in keys:
        want, result = run(build, key, a.native_moves, a.shots, a.tag)
        for limb, v, off in result:
            ok = off <= TOLERANCE
            print(f'{key:10s} hand {limb:2d}: glow at {v} in the hand frame, TTT1 ({want}, 0, 0), '
                  f'{off:.0f} off {"ok" if ok else "FAIL"}', flush=True)
            if not ok: failed.append(key)
    if failed: raise SystemExit(f'FAIL: glows off the fist: {sorted(set(failed))}')
    print('PASS: every glow on its fist')


if __name__ == '__main__':
    main()
