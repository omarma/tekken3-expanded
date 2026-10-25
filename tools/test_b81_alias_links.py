#!/usr/bin/env python3
"""B81 (GH#135): a fighter on TTT1 moves keeps the engine's links of the two alias tables.

    python3 tools/test_b81_alias_links.py [--build build-dbg] [--members angel,mokujin] [--mokujin 12]
                                          [--tries 12] [--visible]

As a fight loads, 0x8002D07C links the two players' alias tables: an alias
missing from one fighter's file takes the other fighter's record (Paul hit by
Bryan's d/f+4 plays 0xAD6, a record of Bryan's file). A fighter on TTT1 moves
(a guest, a native on its TTT1 moveset) plays through a copy of its table
(src/tekken3_ttt1_combat.c, ready()), made again by the VBlank tick whenever
its move header changes. The routine is sliced over frames: a copy made
between two slices kept the links to the fighter met before. In Team Battle,
Paul on his TTT1 moves facing Mokujin on Bryan's moves after Angel: the d/f+4
sent him to 0xAD6 at the address it had in Jin's file (Angel's), then to his
stance at once ("Paul combat: unmapped native entry 012C"), as if put back to
the start (B81).

Team Battle from the menu (no save state), the CPU's natives on their TTT1
moves (TEKKEN3_CPU_MOVESET=ttt1), Mokujin on --mokujin's moves
(TEKKEN3_MOKUJIN_MOVESET). Once the first fight has loaded, player 1's next
members become --members (Angel, Mokujin), the CPU's Paul: the first CPU
member is beaten until Paul comes, player 1's first member until Angel's
fight. There (Paul stays, player 1 changed) and after each knock-out of
Angel from a state saved in her fight (--tries, 7 frames apart), at
Mokujin's round start: every alias of a copied table (Paul's; Angel's) that
the engine linked into the other player's file must name the same record in
the copy, but where the pack plays a move of its own. Before (2026-10-23):
Angel's fight 0, Mokujin's 146 stale links in Paul's copy (0x3A8...,
0xA37, 0xAD6), in each try of two runs; after: none in 12 tries. Needs a
debug server build (rel-lite or PSX_DEBUG_TOOLS=ON) with the TTT1 catalogue.
Exit status 1 on any failure.
"""
import argparse, re, struct, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live as L

STATE, PHASE = 0x800AE204, 0x800AE224
TEAMS, TEAM_STRIDE = 0x800AFA88 + 89, 13            # members (ID * 4 + costume), +10 picked by hand, +12 size
ACTOR, STRIDE, LIFE = 0x800A9228, 0x188C, 0x3F6
SLOTS = 0x800ADC20                                   # each player's move header
PAUL, ALIASES = 0, 4023
STOCK = ['paul', 'law', 'lei', 'king', 'yoshimitsu', 'nina', 'hwoarang', 'xiaoyu', 'eddy', 'jin', 'julia', 'kuma',
         'bryan', 'heihachi', 'ogre', 'mokujin', 'gunjack']


def fighter(s, p): return s.value(ACTOR + p * STRIDE + 0x18, 2)


def table(s, address):
    raw = b''.join(s.read(address + k, 2048) for k in range(0, ALIASES * 4, 2048))
    return struct.unpack_from(f'<{ALIASES}I', raw)


def bank(s, p):
    """Player p's file: its move records (the header's +8, count in the high half of its first word)."""
    header = s.value(SLOTS + 4 * p)
    return s.value(header + 8), s.value(header + 8) + (s.value(header) >> 16) * 56


def installed(log, p):
    """(original, custom) alias tables of player p's last copy, from the log."""
    found = re.findall(rf'combat: installed P{p + 1} alias table, original=([0-9A-F]+) custom=([0-9A-F]+)', log)
    return tuple(int(x, 16) for x in found[-1]) if found else None


def stale(s, p):
    """Aliases of player p's own table linked into the other player's file
    that its copy names otherwise: [(alias, own, copy)]."""
    tables = installed(s.log(), p)
    header = s.value(SLOTS + 4 * p)
    if not tables or not 0x9F000000 <= header < 0x9F400000: return None   # its own table, no copy
    if s.value(header + 12) != tables[1]: raise RuntimeError(f'player {p + 1} plays a copy the log does not name')
    original, custom = map(lambda a: table(s, a), tables)
    lo, hi = bank(s, 1 - p)
    # The pack's own moves (dashes, stance...) stand in guest memory: those
    # are its choice, but its stance (alias 3) is the copy's "none".
    own = lambda c: 0x9F000000 <= c < 0x9F400000 and c != custom[3]
    return [(i, original[i], custom[i]) for i in range(ALIASES)
            if lo <= original[i] < hi and custom[i] != original[i] and not own(custom[i])]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', default='build-dbg')
    ap.add_argument('--mokujin', default='12', help="Mokujin's moves key (TEKKEN3_MOKUJIN_MOVESET; 12 Bryan's)")
    ap.add_argument('--members', default='angel,mokujin',
                    help="player 1's members after the first, in order: guest keys or stock names")
    ap.add_argument('--fight', type=float, default=8, help="seconds the first member fights Paul before the state is saved")
    ap.add_argument('--tries', type=int, default=12, help="knock-outs of the first member, 7 frames apart")
    ap.add_argument('--visible', action='store_true')
    a = ap.parse_args()
    members = a.members.split(',')
    catalogue = [line.split()[0] for line in (L.ROOT / a.build / 'mods/ttt1/guests.txt').read_text().splitlines() if line.split()]
    guest = next((m for m in members if m not in STOCK), 'angel')
    s = L.Session(guest=guest, build=L.ROOT / a.build, line=2, visible=a.visible,
                  env={'TEKKEN3_CPU_MOVESET': 'ttt1', 'TEKKEN3_TEAM_GUESTS': '1,0', 'TEKKEN3_MOKUJIN_MOVESET': a.mokujin})
    failures, checked = [], []
    try:
        time.sleep(3)
        for _ in range(len(members)): s.press(0xffdf)
        s.press(0xbfff); time.sleep(.8)                                         # the first member, then these
        for _ in range(6):
            s.press(0xfff7)                                                     # Start: the teams are drawn
            if s.value(STATE) != 10: break
            time.sleep(.8)
        s.wait(lambda: s.value(STATE) == 8 and s.value(PHASE, 2) >= 6, 'the first fight did not load', 180)
        ids = [STOCK.index(m) if m in STOCK else L.GUEST_ID + catalogue.index(m) for m in members]
        names = dict(zip(ids, members))
        for i, cid in enumerate(ids): s.write(TEAMS + 1 + i, cid * 4, 1)
        s.write(TEAMS + 10, s.value(TEAMS + 12, 1), 1)                        # all picked: no redraw at a loading
        for i in (1, 2): s.write(TEAMS + TEAM_STRIDE + i, PAUL * 4, 1)
        first, second = ids[0], ids[1]

        def check(name):
            if 'Paul on the TTT1 moveset' not in s.log(): raise RuntimeError('Paul is not on his TTT1 moves')
            worst = 0
            for p in (1, 0):
                found = stale(s, p)
                if found is None: continue                                      # player p plays its own table
                who = 'Paul' if p else name
                print(f"{name} against Paul: {who}'s copy, {len(found)} stale links"
                      + (': ' + ', '.join(f'{i:04X} {o:08X} copy {c:08X}' for i, o, c in found[:6]) if found else ''),
                      flush=True)
                if found: failures.append(f'{name} against Paul: {who} has {len(found)} stale links')
                worst = max(worst, len(found))
            return worst

        def fight(cid, seconds):
            """Until player 1's cid fights Paul (the round started), beating whoever else stands."""
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                if s.process.poll() is not None: raise RuntimeError('the game exited')
                if s.value(STATE) != 8 or s.value(PHASE, 2) != 8: time.sleep(.05); continue
                p1, p2 = fighter(s, 0), fighter(s, 1)
                if p2 != PAUL: s.write(ACTOR + STRIDE + LIFE, 0, 2); time.sleep(.3)
                elif p1 == cid: time.sleep(1); return
                else: s.write(ACTOR + LIFE, 0, 2); time.sleep(.3)                # the random first member
            raise AssertionError(f'player 1 never fought Paul with {cid}')

        fight(first, 600)
        check(members[0])
        time.sleep(a.fight)                                                     # the CPU plays a while
        s.q(cmd='savestate', op='save', slot=3); time.sleep(1.5)
        # The next member loads while a frame goes on: player 1 knocked out k
        # frames later each time, the engine's link falls elsewhere in it.
        counts = []
        for k in range(a.tries):
            s.q(cmd='savestate', op='load', slot=3); time.sleep(1)
            end = s.q(cmd='frame')['frame'] + 7 * k
            while s.q(cmd='frame')['frame'] < end: time.sleep(.01)
            s.write(ACTOR + LIFE, 0, 2)
            fight(second, 180)
            counts.append(check(f'{members[1]} (try {k + 1})'))
        print('stale links per try:', counts, flush=True)
    finally:
        s.stop()
    for f in failures: print('FAIL', f)
    print('B81:', 'OK' if not failures else 'FAIL')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
