#!/usr/bin/env python3
"""A native fighter on its TTT1 moves, without a player.

    python3 tools/test_native_moves.py [--native paul] [--t3] [--visible]

From the private Arcade selector save (slot 7), or Practice's (slot 8, the
one kept in workspace/fixtures), walks to the native, picks it with square
(the MOVESET card opens on TEKKEN 3), presses right (TEKKEN TAG TOURNAMENT)
unless --t3 and takes the card with X (in Practice, player 1's pad then
picks the CPU on T3 moves the same way), and fights
Jin. Checks: the identity (its own ID, key and model), where its moves come
from (the TTT1 pack in guest memory, or its own T3 file with --t3), that
each button starts a move of the pack, and that the opponent is untouched.
Screenshots of each attack go to workspace/ttt1-live for the player to judge.
Build: build-opt-dbg (tools/ttt1_live.py).
"""
import argparse, json, re, struct, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live as L

NATIVES = {'paul': 0, 'law': 1, 'lei': 2, 'king': 3, 'yoshimitsu': 4, 'nina': 5,
           'hwoarang': 6, 'xiaoyu': 7, 'eddy': 8, 'jin': 9, 'julia': 10, 'kuma': 11,
           'bryan': 12, 'heihachi': 13, 'ogre': 14, 'gunjack': 16, 'anna': 18, 'trueogre': 20}
PAD_RIGHT, PAD_LEFT, PAD_DOWN, PAD_SQUARE, PAD_CROSS = 0xffdf, 0xff7f, 0xffbf, 0x7fff, 0xbfff
ACTOR = 0x800a9228; STRIDE = 0x188c


def in_pack(address): return 0x9f000000 <= address < 0x9f400000


def run(s, native, cid, ttt1):
    s.wait(lambda: s.value(0x800ae204) == 9 and s.value(0x80118648) == 21,
           'The stock selector grid never appeared', 20)
    time.sleep(1.5)
    for _ in range(48):                              # right along a row, then down a row
        if s.value(0x80118668) == cid: break
        before = s.value(0x80118668)
        s.press(PAD_RIGHT)
        if _ % 12 == 11 or s.value(0x80118668) == before: s.press(PAD_DOWN)
    else: raise AssertionError(f'Cabinet navigation did not reach {native}')
    def pick(player, ttt1):
        """Square picks the native under the cursor: its MOVESET card opens
        (unless it has no TTT1 moves); right switches it, X takes it."""
        opened = f'P{player} opens the MOVESET card'
        before = s.log().count(opened)
        s.press(PAD_SQUARE)
        try: s.wait(lambda: s.log().count(opened) > before, 'no card', 3)
        except AssertionError: return False
        if ttt1:
            s.press(PAD_RIGHT)
            s.wait(lambda: f'P{player} highlights TTT1 moves' in s.log(), 'Right did not switch to TTT1 moves', 5)
        s.shot(f'native-{native}-card-p{player}')
        s.press(PAD_CROSS)
        s.wait(lambda: f'P{player} takes {"TTT1" if ttt1 else "T3"} moves' in s.log(), 'X did not take the card', 5)
        return True
    s.shot(f'native-{native}-grid')
    assert pick(1, ttt1), 'Square on the native did not open its MOVESET card'
    if s.value(0x800afa88) == 5:                     # Practice: then the CPU
        s.wait(lambda: s.value(0x8011864c + 0x7c) == 3, 'Player 1 never picked the CPU', 5)
        pick(2, False)
    s.wait(lambda: s.value(0x800ae204) == 11, 'Loading screen not reached', 15)
    s.write(0x800add5e, 9, 2); s.write(0x800add9a, 0, 2)      # Jin, costume 1
    def ready():
        return (s.value(0x800ae204) == 8 and s.value(0x800ae224, 2) >= 6 and
                s.actor(0)[2] == cid and s.value(ACTOR + 0x54) != 0)
    s.wait(ready, f'{native} did not reach the fight', 90)
    identity = s.actor(0)
    header = s.value(0x800adc20)
    report = dict(native=native, ttt1=ttt1, identity=identity, header=hex(header))
    # Its own ID; its own key, which the opponent's rules test.
    assert identity[2] == cid, identity
    if ttt1:
        s.wait(lambda: in_pack(s.value(0x800adc20)), 'The TTT1 moves were never installed', 30)
        header = s.value(0x800adc20)
        log = s.log()
        name = native.capitalize()
        assert f'P1 {name} on the TTT1 moveset' in log, 'No TTT1 identity at the loading screen'
        assert re.search(rf'{name} combat: loaded \d+ source records', log), 'The TTT1 pack did not load'
        assert 'installed P1 alias table' in log, 'The alias table was not installed'
        assert s.value(header + 1, 1) == identity[1], ('The native key was replaced', s.value(header + 1, 1))
        assert 'Jin model header replaced' not in log, 'A guest model replaced the native one'
        report['records'] = int(re.findall(rf'{name} combat: loaded (\d+)', log)[-1])
    else:
        assert not in_pack(header), 'T3 moves requested, the TTT1 pack was installed'
    assert not in_pack(s.value(0x800adc24)), 'The opponent took TTT1 moves'
    s.write(ACTOR + STRIDE + 0xc5, 0, 1)             # the opponent stays idle
    time.sleep(4)
    s.shot(f'native-{native}-fight')
    seen = {}
    for label, button in (('1', 0x7fff), ('2', 0xefff), ('3', 0xbfff), ('4', 0xdfff)):
        records = set()
        s.q(cmd='press', buttons=button, frames=3)
        until = s.game_until(1.2); shot = False
        while until():
            s.write(ACTOR + STRIDE, 3000)             # keep the opponent away
            records.add(s.value(ACTOR + 0x54))
            if not shot and s.value(ACTOR + 0x58, 2) >= 8:
                s.shot(f'native-{native}-{"ttt1" if ttt1 else "t3"}-button{label}'); shot = True
        from_pack = sorted(hex(r) for r in records if in_pack(r))
        seen[label] = sorted(hex(r) for r in records)
        if ttt1: assert from_pack, (f'Button {label} played no TTT1 record', [hex(r) for r in records])
        else: assert not from_pack, (f'Button {label} played a TTT1 record with T3 moves', from_pack)
    report['buttons'] = seen
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--native', default='paul', choices=sorted(NATIVES))
    ap.add_argument('--t3', action='store_true', help='keep the T3 moves (R1 not pressed)')
    ap.add_argument('--visible', action='store_true')
    ap.add_argument('--slot', type=int, default=7, help='selector save: 7 Arcade, 8 Practice')
    ap.add_argument('--build', default=str(L.ROOT / 'build-opt-dbg'), help='build directory')
    a = ap.parse_args()
    s = L.Session(visible=a.visible, guest='jun', slot=a.slot, build=Path(a.build))
    try:
        report = run(s, a.native, NATIVES[a.native], not a.t3)
        print(json.dumps(report, indent=2))
        print('OK')
    finally:
        s.stop()


if __name__ == '__main__':
    main()
