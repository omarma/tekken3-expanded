#!/usr/bin/env python3
"""B129 (GH#178): the merged reaction tables hold the fight's own fighters only.

    python tools/test_b129_reaction_tables.py [--build build-rel-lite] [--guests lee,ganryu]
                                              [--natives paul,law] [--visible]

A fighter on TTT1 moves (a guest, a native on its TTT1 moveset) brings its
pack's reaction rows, pushback and counters: install_tables()
(src/tekken3_ttt1_combat.c) merges the two players' packs after Tekken 3's own
tables and points the engine at the copy, rewriting seven lui/addiu pairs
(event scripts 0x80041400, reaction rows 0x8002D7AC, 0x80044590, 0x80044608,
0x80044664, counters 0x800445C4, 0x80044AC0). Before (v1.4.1): a slot whose
player went on with a native on Tekken 3 moves stayed in the merge ("Lee +
Ganryu" with Lee gone), and once nobody was on TTT1 moves the engine kept
reading the last copy: a Team Battle rematch, the attract mode's next fight.

Team Battle from the menu (no save state), the CPU's natives on Tekken 3
moves and no guest drawn for its team. Once the first fight has loaded, the
teams become player 1: (first), guest 1, native 1; the CPU: (first), guest 2,
native 2. Knock-outs then give, in order:

  guest 1 against the CPU's first   merged: guest 1
  guest 1 against guest 2           merged: guest 1 + guest 2
  native 1 against guest 2          merged: guest 2 only (before: both)
  native 1 against native 2         Tekken 3's own bases (before: the copy)

Each step reads the seven pairs in RAM: the merged copy's size (the counters'
base minus the rows' base: rows * 42 + pushback bytes) against the live packs'
(mods/ttt1/<Name>-TTT1-tables.jst), and, in the last fight, every word against
SLUS_004.02. Needs a debug server build (rel-lite or PSX_DEBUG_TOOLS=ON) with
the TTT1 catalogue in its mods/ttt1. Exit status 1 on any failure.
"""
import argparse, struct, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live as L

STATE, PHASE = 0x800AE204, 0x800AE224
TEAMS, TEAM_STRIDE = 0x800AFA88 + 89, 13            # members (ID * 4 + costume), +10 picked by hand, +12 size
ACTOR, STRIDE, LIFE = 0x800A9228, 0x188C, 0x3F6
STOCK = ['paul', 'law', 'lei', 'king', 'yoshimitsu', 'nina', 'hwoarang', 'xiaoyu', 'eddy', 'jin', 'julia', 'kuma',
         'bryan', 'heihachi', 'ogre', 'mokujin', 'gunjack']
# (high word, low word) of each base install_tables() rewrites.
PAIRS = [(0x80041400, 0x80041404), (0x8002D7AC, 0x8002D7B4), (0x80044590, 0x80044598), (0x80044608, 0x80044610),
         (0x80044664, 0x8004466C), (0x800445C4, 0x800445CC), (0x80044AC0, 0x80044AC4)]
NATIVE_ROWS, NATIVE_PUSH = 633, 0xCE8 - 0x75C


def stock_words():
    exe = (L.ROOT / 'disc/SLUS_004.02').read_bytes()
    load = struct.unpack_from('<I', exe, 0x18)[0]
    word = lambda a: struct.unpack_from('<I', exe, a - load + 0x800)[0]
    return {a: word(a) for pair in PAIRS for a in pair}


def target(high, low):
    """The address a lui/addiu pair builds."""
    return ((high & 0xFFFF) << 16) + ((low & 0xFFFF) ^ 0x8000) - 0x8000 & 0xFFFFFFFF


def pack_bytes(assets, prefix):
    """A pack's own reaction rows and pushback bytes beyond Tekken 3's (rows * 42 + pushback)."""
    h = (assets / f'{prefix}-TTT1-tables.jst').read_bytes()[:32]
    nr, np = struct.unpack_from('<II', h, 12)
    return (nr - NATIVE_ROWS) * 42 + np - NATIVE_PUSH


def fighter(s, p): return s.value(ACTOR + p * STRIDE + 0x18, 2)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--guests', default='lee,ganryu', help="player 1's guest, then the CPU's (catalogue keys)")
    ap.add_argument('--natives', default='paul,law', help="player 1's native, then the CPU's, on Tekken 3 moves")
    ap.add_argument('--visible', action='store_true')
    a = ap.parse_args()
    guests, natives = a.guests.split(','), a.natives.split(',')
    build = L.ROOT / a.build
    assets = build / 'mods/ttt1'
    catalogue = [line.split()[0] for line in (assets / 'guests.txt').read_text().splitlines() if line.split()]
    gid = [L.GUEST_ID + catalogue.index(g) for g in guests]
    nid = [STOCK.index(n) for n in natives]
    stock = stock_words()
    # Each guest's pack: its key capitalized the catalogue's way (lee: Lee-TTT1-tables.jst).
    packs = {p.name.lower(): p.name[:-len('-TTT1-tables.jst')] for p in assets.glob('*-TTT1-tables.jst')}
    prefix = {g: packs[f'{g}-ttt1-tables.jst'] for g in guests}
    s = L.Session(guest=guests[0], build=build, line=2, visible=a.visible,
                  env={'TEKKEN3_CPU_MOVESET': 'original', 'TEKKEN3_TEAM_GUESTS': '1,0,0'})
    failures = []

    def measure(name, live):
        words = {addr: s.value(addr) for pair in PAIRS for addr in pair}
        rows = target(words[0x8002D7AC], words[0x8002D7B4])
        counters = target(words[0x800445C4], words[0x800445CC])
        merged = [l.split('reaction tables merged: ')[1] for l in s.log().splitlines() if 'reaction tables merged' in l]
        if not live:
            moved = [f'{addr:08X} {words[addr]:08X} (game {stock[addr]:08X})' for addr in words if words[addr] != stock[addr]]
            print(f'{name}: {"Tekken 3 bases" if not moved else f"{len(moved)} words still on the copy: " + ", ".join(moved[:4])}'
                  f'; rows at {rows:08X}, counters at {counters:08X}; last merge: {merged[-1] if merged else "none"}', flush=True)
            if moved: failures.append(f'{name}: the engine still reads the merged copy ({len(moved)} words)')
            return
        expected = NATIVE_ROWS * 42 + NATIVE_PUSH + sum(pack_bytes(assets, prefix[g]) for g in live)
        got = counters - rows
        print(f'{name}: merged copy {got} bytes, {" + ".join(live)} alone {expected}; rows at {rows:08X}; '
              f'last merge: {merged[-1] if merged else "none"}', flush=True)
        if rows == stock_target: failures.append(f'{name}: the engine reads Tekken 3 tables, {"+".join(live)} expected')
        elif got != expected: failures.append(f'{name}: merged copy of {got} bytes, {expected} for {" + ".join(live)}')

    stock_target = target(stock[0x8002D7AC], stock[0x8002D7B4])

    def fight(p1, p2, seconds=300):
        """Until p1 fights p2 (None: anyone) and the round runs, knocking out whoever else stands."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if s.process.poll() is not None: raise RuntimeError('the game exited')
            if s.value(STATE) != 8 or s.value(PHASE, 2) != 8: time.sleep(.05); continue
            a1, a2 = fighter(s, 0), fighter(s, 1)
            if a1 != p1: s.write(ACTOR + LIFE, 0, 2); time.sleep(.3)
            elif p2 is not None and a2 != p2: s.write(ACTOR + STRIDE + LIFE, 0, 2); time.sleep(.3)
            else: time.sleep(1.5); return
        raise AssertionError(f'player 1 never fought with {p1} against {p2}')

    try:
        time.sleep(3)
        for _ in range(2): s.press(0xffdf)                                       # three members
        s.press(0xbfff); time.sleep(.8)
        for _ in range(6):
            s.press(0xfff7)                                                     # Start: the teams are drawn
            if s.value(STATE) != 10: break
            time.sleep(.8)
        s.wait(lambda: s.value(STATE) == 8 and s.value(PHASE, 2) >= 6, 'the first fight did not load', 180)
        sizes = [s.value(TEAMS + p * TEAM_STRIDE + 12, 1) for p in (0, 1)]
        if min(sizes) < 3: raise RuntimeError(f'teams of {sizes} members, 3 needed')
        for p, members in ((0, (gid[0], nid[0])), (1, (gid[1], nid[1]))):
            for i, cid in enumerate(members): s.write(TEAMS + p * TEAM_STRIDE + 1 + i, cid * 4, 1)
        s.write(TEAMS + 10, s.value(TEAMS + 12, 1), 1)                          # all picked: no redraw at a loading
        first = fighter(s, 1)
        fight(gid[0], first)
        measure(f'{guests[0]} against the CPU\'s first', [guests[0]])
        fight(gid[0], gid[1])
        measure(f'{guests[0]} against {guests[1]}', guests)
        fight(nid[0], gid[1])
        measure(f'{natives[0]} against {guests[1]}', [guests[1]])
        fight(nid[0], nid[1])
        measure(f'{natives[0]} against {natives[1]}', [])
        moves = [l for l in s.log().splitlines() if 'on the TTT1 moveset' in l]
        if moves: failures.append('a native fought on TTT1 moves: ' + moves[0])
    finally:
        s.stop()
    for f in failures: print('FAIL', f)
    print('B129:', 'OK' if not failures else 'FAIL')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
