#!/usr/bin/env python3
"""The poison mist of the TTT1 moves hits (B65, GH#122).

    python tools/test_poison_mist.py --build build-rel-lite [--fighter nina|yoshimitsu|unknown@nina|unknown@yoshimitsu]
        [--move evil-mist|poison-breath|flash] [--t3] [--distance 900,1300] [--shots] [--trace] [--tag NAME]

TTT1 spits the mist through a virtual limb 25 (Nina's Evil Mist, Yoshimitsu's
Poison Breath out of Bad Stomach): no bone, the hit test goes to the
capsules of an effect object, the cloud (TTT1 80116290). T3 has the same
limb 25 for its own mist (0x8006F0F4 -> 0x8006ECA4, an effect object of
type 10 from the head). The import used to drop the limb (hit limb 0): no
cloud, no capsule, nothing hit.

Cold start, Arcade selector. A native takes its TTT1 moves
(TEKKEN3_NATIVE_MOVES=1); Unknown goes by the Tag page on the moveset after
the @ (TEKKEN3_TETSUJIN_MOVESET). The opponent is forced to Jin and stands
still. At each distance the mist's record is launched from a saved state
(the pending transition, actor +0x1A0 / +0x1A4) and followed frame by frame:
player 1's effect capsules (count 0x800ADEAC), player 2's life and moves. It
fails unless the cloud appears and player 2 is hit at the nearest distance:
it loses life or a contact slot is written (actor +316; the Evil Mist does
no damage, in T3 as in TTT1). --move flash plays
Yoshimitsu's Flash (b+1+4, a cut from the hand to the sword's tip), which
must hit without a cloud. --t3: the native on its T3 moves, whose own mist
(the reference) is the record of its alias table on limb 25. --shots writes
pictures of the move. --trace prints, each sample of the move, player 1's
capsules and how far each passes from player 2's spheres (+0x20C, 14 of 20
bytes, radius at +0xC).
"""
import argparse, os, re, struct, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_devil_jin as T
import test_guest_accessories as A
from test_yoshimitsu_win_sparks import Game

T.WORK = ROOT / 'workspace/poison-mist'
NATIVES = {'nina': 5, 'yoshimitsu': 4}
# The move's TTT1 record (its address in TTT1's RAM, the pack's provenance),
# its moveset and whether it spits the mist.
MOVES = {'evil-mist': (0x80050428, 'nina', True), 'poison-breath': (0x80054730, 'yoshimitsu', True),
         'flash': (0x80054764, 'yoshimitsu', False)}
ACTOR, STRIDE, LIFE = T.ACTOR, T.STRIDE, T.LIFE
EFFECT_CAPSULES = 0x800adeac            # effect-object capsules, a word per player
OPPONENT, OPPONENT_COSTUME = 0x800add5e, 0x800add9a
ROUND_CLOCK = 0x800adbcc
FRAMES = 110
SHOTS = 12                              # --shots: a picture every 4 frames from frame 14 (the mist)
CONTACT, CONTACT_SIZE = 316, 88         # actor +316: the two contact slots of the hits taken (44 bytes each)


def word(b, o): return struct.unpack_from('<I', b, o)[0]


def pack_index(path, provenance):
    """Index of the record converted from that TTT1 record, and its hit limbs."""
    b = path.read_bytes()
    for i in range(word(b, 12)):
        source, prov, rp, _ = struct.unpack_from('<4I', b, 32 + i * 16)
        if prov == provenance: return i, b[rp + 40:rp + 44].hex()
    raise AssertionError(f'no record from {provenance:08x} in {path.name}')


def cursor_to(g, cid):
    """Right along a row, then down a row (tools/test_native_moves.py): the
    cursor does not always start on the row of the native."""
    for n in range(60):
        if g.value(T.CURSOR_CHAR) == cid: return
        before = g.value(T.CURSOR_CHAR)
        g.q(cmd='press', buttons=T.RIGHT, frames=4); time.sleep(.35)
        if n % 12 == 11 or g.value(T.CURSOR_CHAR) == before:
            g.q(cmd='press', buttons=0xffbf, frames=4); time.sleep(.35)     # down
    raise AssertionError(f'P1 cursor did not reach character {cid}')


def start_native(g, name, t3=False):
    T.to_selector(g)
    cursor_to(g, NATIVES[name])
    # Square until the loading screen (state 11, a fifth of a second; state 8
    # phase 1 just before), read without pauses.
    end, pressed = time.monotonic() + 60, 0
    while (state := g.value(T.STATE)) != 11:
        if state == 8 and g.value(T.PHASE, 2) >= 3: raise AssertionError('the fight started before the loading screen was seen')
        if time.monotonic() > end: raise AssertionError('loading screen not reached')
        if state == 9 and time.monotonic() - pressed > 1:
            g.q(cmd='press', buttons=T.SQUARE, frames=12); pressed = time.monotonic()
    g.write(OPPONENT, 9, 2); g.write(OPPONENT_COSTUME, 0, 2)          # Jin
    g.wait(lambda: g.value(T.STATE) == 8 and g.value(T.PHASE, 2) >= 8, 'round did not start', 150)
    assert T.actor(g, 0)[2] == NATIVES[name], f'P1 is {T.actor(g, 0)[2]}'
    assert T.actor(g, 1)[2] == 9, f'P2 is {T.actor(g, 1)[2]}, not Jin'
    assert t3 != (f'P1 {name.capitalize()} on the TTT1 moveset' in g.log()), 'not on the moves asked for'


def start_guest(g, key, build):
    catalogue = [l.split()[0] for l in (build / 'mods/ttt1/guests.txt').read_text().splitlines() if l.split()]
    A.to_tag_page(g, len(catalogue))
    A.fight(g, catalogue.index(key), len(catalogue), 1)


def records_base(g):
    found = re.findall(r'installed P1 alias table, original=\w+ custom=\w+ records=([0-9A-F]{8})', g.log())
    assert found, 'no alias table installed for player 1'
    return int(found[-1], 16)


def place(g, distance):
    """Player 2 at that distance in front of player 1, both idle."""
    p1, p2 = (struct.unpack('<3i', g.read(ACTOR + p * STRIDE, 12)) for p in (0, 1))
    dx, dz = p2[0] - p1[0], p2[2] - p1[2]
    n = (dx * dx + dz * dz) ** .5 or 1
    x, z = int(p1[0] + dx / n * distance), int(p1[2] + dz / n * distance)
    for off, v in ((0, x), (8, z), (0xf68, x), (0xf70, z)): g.write(ACTOR + STRIDE + off, v)


def launch(g, number, record):
    """Pending transition: +0x1A0 = move number, +0x1A4 = record, in one write."""
    keep = g.read(ACTOR + 0x1a2, 2)
    data = struct.pack('<H', number) + keep + struct.pack('<I', record)
    g.q(cmd='write_ram', addr=f'{ACTOR + 0x1a0:08x}', bytes=data.hex())


def gap(seg, spheres):
    """Smallest distance from a capsule segment to a sphere's surface."""
    a, b = seg[:3], seg[3:]
    d = [b[i] - a[i] for i in range(3)]
    n = sum(x * x for x in d) or 1
    best = None
    for c, r in spheres:
        t = max(0.0, min(1.0, sum((c[i] - a[i]) * d[i] for i in range(3)) / n))
        e = sum((c[i] - a[i] - t * d[i]) ** 2 for i in range(3)) ** .5 - r
        best = e if best is None else min(best, e)
    return best


def follow(g, record, shots, name, trace=False, every=(14, 4)):
    """Samples until FRAMES frames have gone: one read of both actors (one
    frame), then the effect capsules."""
    span = STRIDE + LIFE + 2 - 0x54
    rows, f0, taken = [], g.q(cmd='frame')['frame'], 0
    while (f := g.q(cmd='frame')['frame']) < f0 + FRAMES:
        both = g.read(ACTOR + 0x54, span)
        caps = g.read(EFFECT_CAPSULES, 4)
        rows.append(dict(frame=f - f0, record=word(both, 0), move_frame=struct.unpack_from('<h', both, 4)[0],
                         victim=word(both, STRIDE), life=struct.unpack_from('<h', both, span - 2)[0],
                         contact=both[STRIDE + CONTACT - 0x54:STRIDE + CONTACT - 0x54 + CONTACT_SIZE],
                         capsules=word(caps, 0)))
        if trace and word(both, 0) == record:
            caps1 = struct.unpack_from('<12i', both, 0x1ac - 0x54)
            n = both[0xe3 - 0x54]
            sph = [(struct.unpack_from('<3i', both, STRIDE + 0x20c + 20 * k - 0x54),
                    struct.unpack_from('<i', both, STRIDE + 0x20c + 20 * k + 12 - 0x54)[0]) for k in range(14)]
            print(f'    frame {rows[-1]["move_frame"]:3d} capsules {n}: ' + '  '.join(
                f'{caps1[6 * k:6 * k + 6]} gap {gap(caps1[6 * k:6 * k + 6], sph):.0f}' for k in range(2)))
        if shots and taken < SHOTS and f >= f0 + every[0] + every[1] * taken:
            g.shot(f'{name}-{taken:02d}'); taken += 1
    return rows


def t3_mist(g):
    """Index and address of the native's own mist: the record of its T3 alias
    table whose first hit limb is 25."""
    aliases = g.value(g.value(0x800adc20) + 12)
    table = g.read(aliases, 4023 * 4)
    for i in range(4023):
        r = word(table, 4 * i)
        if not 0x80000000 <= r < 0x80200000: continue
        limbs = word(g.read(r + 40, 4), 0)
        if 0x80000000 <= limbs < 0x80200000 and g.read(limbs, 1)[0] == 25 and g.read(r + 45, 1)[0] > 15: return i, r
    raise AssertionError('no T3 record on limb 25')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', required=True)
    ap.add_argument('--fighter', default='nina', choices=('nina', 'yoshimitsu', 'unknown@nina', 'unknown@yoshimitsu'))
    ap.add_argument('--move', choices=MOVES, help="default: the moveset's mist")
    ap.add_argument('--t3', action='store_true', help='the native on its T3 moves (reference)')
    ap.add_argument('--distance', default='900,1300')
    ap.add_argument('--shots', action='store_true')
    ap.add_argument('--trace', action='store_true')
    ap.add_argument('--tag', default=None)
    a = ap.parse_args()
    T.WORK.mkdir(parents=True, exist_ok=True)
    build = Path(a.build).resolve()
    guest, moveset = a.fighter.startswith('unknown@'), a.fighter.split('@')[-1]
    assert not (a.t3 and guest), '--t3 is for a native'
    env = {'TEKKEN3_TETSUJIN_MOVESET': moveset} if guest else {'TEKKEN3_NATIVE_MOVES': '0' if a.t3 else '1'}
    title = a.move or {'nina': 'evil-mist', 'yoshimitsu': 'poison-breath'}[moveset]
    provenance, owner, mist = MOVES[title]
    assert owner == moveset, f'{title} is not on {moveset} moves'
    tag = a.tag or f"{a.fighter.replace('@', '-')}-{title}" + ('-t3' if a.t3 else '')
    pack = build / 'mods/ttt1' / (f'Unknown@{moveset.capitalize()}-TTT1-combat.jmv' if guest else
                                  f'{moveset.capitalize()}-TTT1-combat.jmv')
    if not a.t3:
        index, limbs = pack_index(pack, provenance)
        print(f'{a.fighter}: {title} = pack record {index}, hit limbs {limbs} ({pack.name})')
    g = Game(build, tag, env)
    results = []
    try:
        if guest: start_guest(g, 'unknown', build)
        else: start_native(g, moveset, a.t3)
        g.write(ACTOR + STRIDE + 0xc5, 0, 1)            # Jin stands still
        clock = g.value(ROUND_CLOCK, 2)                 # past ROUND 1 / READY: the clock runs
        g.wait(lambda: g.value(ROUND_CLOCK, 2) != clock, 'the round clock never ran', 30)
        time.sleep(.5)
        if a.t3:
            index, record = t3_mist(g); number = index
            print(f'{a.fighter} on T3 moves: its mist is alias {index:#x}, record {record:08X}')
        else: record, number = records_base(g) + index * 56, T.PACK + index
        g.q(cmd='savestate', op='save', slot=9)
        for d in (int(x) for x in a.distance.split(',')):
            g.q(cmd='savestate', op='load', slot=9); time.sleep(.3)
            g.write(ROUND_CLOCK, 0x7000, 2)
            place(g, d); time.sleep(.6)
            life = g.value(ACTOR + STRIDE + LIFE, 2)
            launch(g, number, record)
            rows = follow(g, record, a.shots, f'{d}', a.trace, (14, 4) if mist else (1, 2))
            mine = [r for r in rows if r['record'] == record]
            lost = life - min(r['life'] for r in rows)
            victim = []
            for r in rows:
                if not victim or victim[-1][1] != r['victim']: victim.append((r['frame'], r['victim']))
            # Hit: life lost, or a contact slot written (the Evil Mist does no damage).
            hit = lost > 0 or any(r['contact'] != rows[0]['contact'] for r in rows)
            caps = max(r['capsules'] for r in rows)
            print(f'  distance {d}: {title} record for {len(mine)} samples (move frames '
                  f'{mine[0]["move_frame"] if mine else "-"}..{mine[-1]["move_frame"] if mine else "-"}), '
                  f'effect capsules up to {caps}, player 2 lost {lost}, its records '
                  + ' '.join(f'{f}:{v:08X}' for f, v in victim) + (' HIT' if hit else ' missed'))
            results.append(dict(distance=d, frames=len(mine), capsules=caps, lost=lost, hit=hit))
    finally:
        if g.process.poll() is None: g.q(cmd='clear_input')
        g.stop()
    near = results[0]
    if not near['frames']: raise SystemExit(f'FAIL: the {title} record never played')
    if mist and not near['capsules']: raise SystemExit(f'FAIL: no mist cloud (no effect capsule) for the {title}')
    if not near['hit']: raise SystemExit(f'FAIL: the {title} did not hit at {near["distance"]}')
    print(f'PASS: {a.fighter}: the {title} ' + ('spits the mist and ' if mist else '') + 'hits')


if __name__ == '__main__':
    main()
