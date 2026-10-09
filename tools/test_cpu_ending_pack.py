#!/usr/bin/env python3
"""B30: a TTT ending's participant as the CPU's opponent, with TTT Cinematics:
Kazuya or Devil, Armor King, or King (a native, on his TTT1 moveset).

    python3 tools/test_cpu_ending_pack.py --case gate|loader [--mode arcade|survival|timeattack|team]
                                          [--guest kazuya|devil|armorking|king] [--build build-rel-lite]

Player 1 picks Jin (stock page, private save slot 7). Arcade: once the
opponents are drawn, stage 2 becomes the guest (list 0x800AFB18, TIPS.md
section 17), stage 1 is won by emptying player 2's life. Survival, Time
Attack, Team Battle (one member): the CPU's fighter is written while the
first fight loads (0x800ADD5E, TIPS.md section 25; the CPU team's first
member too). In the guest's fight:

- gate: the add-on as installed (mods/ttt-cinematics). The CPU's guest must
  take the catalogue's pack: no "<Name> combat: ending pack" in the log
  (src/tekken3_embu_scenes.c, tekken3_ending_pack_wanted).
- loader: the run's catalogue pack is replaced, before the fight, by the
  same pack plus eight copies of the stance record, sharing its cancel list,
  as tools/ttt_cinematics.py's packs do. Player 2's records are moved by
  4096 once (src/tekken3_ttt1_combat.c, load_combat): moved once per record,
  the stance's destinations went past 0x8000 and the CPU looped one record.

- p1: player 1 picks the guest himself (Tag page), Arcade: its pack must be
  the ending's from the first fight, or the cutscene leaves it in guard.

gate and loader check, in guest memory, that player 2's stance cancel list holds
the pack's destinations moved exactly once, and that the CPU plays: over 25 s
it visits several records and no single one holds 80 % of the samples (the
defect: record 699 in 185 of 213). Needs a debug server build (rel-lite or
build-opt-dbg) with the TTT1 catalogue and, for gate, TTT Cinematics prepared.
Exit status 1 on any failure.
"""
import argparse, re, struct, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / 'ttt1'))
import ttt1_live as L
from pack_edit import Pack

LIST, STATE, PHASE, MODE = 0x800AFB18, 0x800AE204, 0x800AE224, 0x800AFA88
MODES = {'arcade': 0, 'team': 2, 'timeattack': 3, 'survival': 4}
CPU_TEAM, CPU_FIGHTER, CPU_COSTUME = 0x800AFAEE, 0x800ADD5E, 0x800ADD9A
P2, P1_LIFE = 0x800AAAB4, 0x800A961E
SLOT_BASE, SLOT_STRIDE = 8192, 4096


def player_one(a, build, name):
    """p1: player 1 picks the guest on the Tag page (R2) in Arcade; its pack,
    read while the cursor is on it, must be the ending's (the cutscene plays
    its clips, B30 validation: Kazuya stood in guard)."""
    want = len(Pack((build / f'mods/ttt-cinematics/{a.guest.capitalize()}-TTT1-combat.jmv').read_bytes()).records)
    s = L.Session(guest=a.guest, build=build, env={'TEKKEN3_NATIVE_MOVES': '0'})
    try:
        s.wait(lambda: s.value(STATE) == 9 and s.value(0x80118648) == 21, 'no stock selector grid', 20)
        s.press(L.PAD_R2); time.sleep(2)
        row, col = L.tag_place(s.index, s.catalogue_size)
        for _ in range(12):
            r, c = L.tag_place(s.value(0x80118650), s.catalogue_size)
            if (r, c) == (row, col): break
            s.press(0xffbf if r < row else 0xffef if r > row else 0xffdf if c < col else 0xff7f)
        s.wait(lambda: s.value(0x80118668) == s.cid, 'cursor on the guest', 10)
        s.press(0x7fff)
        s.wait(lambda: s.value(STATE) == 8 and s.value(PHASE, 2) >= 6, 'first fight', 120)
        log = s.log()
    finally:
        s.stop()
    loaded = [int(n) for n in re.findall(rf'{name} combat: loaded (\d+) source records', log)]
    ok = f'{name} combat: ending pack' in log and loaded and loaded[0] == want
    print(f'p1 arcade {name}: loaded {loaded[:3]}, ending pack {want} records', '\nOK' if ok else '\nECHEC P1 lacks the ending clips')
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--case', choices=('gate', 'loader', 'p1'), required=True)
    ap.add_argument('--mode', choices=tuple(MODES), default='arcade')
    ap.add_argument('--guest', default='kazuya', help='a guest key, or king: the native on his TTT1 moves')
    ap.add_argument('--build', default='build-rel-lite')
    a = ap.parse_args()
    build = L.ROOT / a.build
    # The game's own name in its log ("Armor King combat: ..."); the pack file keeps the key's form.
    name = {'armorking': 'Armor King', 'pjack': 'P. Jack'}.get(a.guest, a.guest.capitalize())
    if a.case != 'loader' and not (build / 'mods/ttt-cinematics/cinematics.txt').is_file():
        sys.exit(f'{build}/mods/ttt-cinematics is not prepared (tools/ttt_cinematics.py)')
    if a.case == 'p1': sys.exit(player_one(a, build, name))
    # King: a Tekken 3 native (id 3) the CPU plays on his TTT1 moveset
    # (TEKKEN3_NATIVE_MOVES=1, every native on TTT1); his pack is King-TTT1.
    native = a.guest == 'king'
    s = L.Session(guest='armorking' if native else a.guest, build=build,
                  env={'TEKKEN3_GUEST_P2': 'armorking' if native else a.guest, 'TEKKEN3_NATIVE_MOVES': '1' if native else '0'})
    if native: s.cid_p2 = 3
    pack_file = s.run / f'mods/ttt1/{a.guest.capitalize()}-TTT1-combat.jmv'
    pack = Pack(pack_file.read_bytes())
    if a.case == 'loader':
        for k in range(8): pack.add_record(pack.neutral, 0x803F0000 + k)
        pack_file.write_bytes(pack.build())
        pack = Pack(pack_file.read_bytes())
    failures, samples = [], []
    try:
        if a.mode == 'team':
            s.write(MODE, 2); s.write(PHASE, 0, 2); s.write(STATE, 10, 2)
            time.sleep(3)
            s.press(0xbfff); time.sleep(.8)                         # a team of one
            for _ in range(6):
                s.press(0xfff7)                                     # Start: the teams are drawn
                if s.value(STATE) != 10: break
                time.sleep(.8)
        else:
            s.wait(lambda: s.value(STATE) == 9 and s.value(0x80118648) == 21, 'no stock selector grid', 20)
            s.write(MODE, MODES[a.mode])
            for _ in range(23):
                if s.value(0x80118668) == 9: break
                s.press(0xff7f)
            s.press(0x7fff)
        s.wait(lambda: s.value(STATE) == 11, 'no loading screen', 15)
        if a.mode == 'arcade': s.write(LIST + 4, s.cid_p2, 1); s.write(LIST + 5, 0, 1)
        # A native: stage 1's opponent as well, loaded through this loading
        # screen (stage 2 loads in the fight, without one, where no moveset is
        # chosen for it: the CPU's native would keep its Tekken 3 moves).
        if a.mode == 'arcade' and native:
            s.write(LIST, 3, 1); s.write(LIST + 1, 0, 1); s.write(CPU_FIGHTER, 3, 2); s.write(CPU_COSTUME, 0, 2)
        t0, start, full, mode = time.monotonic(), None, 0, None
        while time.monotonic() - t0 < 300:
            if s.process.poll() is not None: raise RuntimeError('the game exited')
            state, phase = s.value(STATE), s.value(PHASE, 2)
            if state == 11 and a.mode != 'arcade' and start is None:
                s.write(CPU_FIGHTER, s.cid_p2, 2); s.write(CPU_COSTUME, 0, 2)
                if a.mode == 'team': s.write(CPU_TEAM, s.cid_p2 * 4, 1)
            elif state == 8 and phase >= 6 and s.actor(1)[2] != s.cid_p2 and s.value(P2 + 0x3F4) > 0xFFFF:
                s.write(P2 + 0x3F6, 0, 2)                           # another opponent first: won
            elif state == 8 and phase == 8 and s.actor(1)[2] == s.cid_p2:
                start = start or time.monotonic()
                full = full or s.value(P1_LIFE, 2)
                if full: s.write(P1_LIFE, full, 2)
                samples.append(s.value(P2 + 0x54))
                mode = s.value(MODE)
                if time.monotonic() - start > 25: break
            elif state not in (8, 9, 10, 11): s.press(0xfff7)
            time.sleep(.25)
        if start is None: raise RuntimeError("the guest's fight was not reached")
        if mode != MODES[a.mode]: failures.append(f'the fight ran in mode {mode}, not {a.mode}')
        log = s.log()
        m = re.findall(rf'{name} combat: installed P2 alias table.*records=([0-9A-F]+)', log)
        if not m: raise RuntimeError('no P2 alias table in the log')
        records = int(m[-1], 16)
        if a.case == 'gate' and f'{name} combat: ending pack' in log:
            failures.append('the CPU took the ending pack')
        # The stance's cancel list in guest memory: each destination moved once.
        n = pack.meta[pack.neutral][3]
        cp = s.value(records + pack.neutral * 56 + 12)
        memory = s.read(cp, n * 12)
        wrong = 0
        for j, entry in enumerate(pack.cancels(pack.neutral)):
            want = entry[3] + SLOT_STRIDE if entry[3] >= SLOT_BASE else entry[3]
            if struct.unpack_from('<H', memory, j * 12 + 6)[0] != want: wrong += 1
        if wrong: failures.append(f'{wrong} of {n} stance destinations not moved exactly once')
        index = [(r - records) // 56 for r in samples if records <= r < records + len(pack.records) * 56]
        top = max((index.count(i) for i in set(index)), default=0)
        print(f'{a.case} {a.mode} (mode {mode}) {name}: {len(samples)} samples, {len(set(index))} records, '
              f'most held {top}, stance destinations wrong {wrong}/{n}')
        if len(set(index)) < 5 or top > .8 * len(samples):
            failures.append('the CPU does not play (one record holds the fight)')
    finally:
        s.stop()
    for f in failures: print('ECHEC', f)
    print('OK' if not failures else 'ECHEC')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
