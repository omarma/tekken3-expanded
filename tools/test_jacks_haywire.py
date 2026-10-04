#!/usr/bin/env python3
"""A Jack hit by Devil's (or Angel's) laser goes haywire (TIPS.md § 48).

    python3 tools/test_jacks_haywire.py [--build build-rel-lite] [--guest devil]
        [--opponent jack2|pjack|gunjack|jin] [--moves t3|ttt1] [--tag after] [--assets DIR] [--case NAME ...]

Devil against a still opponent (cabinet selector, tools/ttt1_live.py): a
guest (Jack-2, P.Jack), or a native (Gun Jack 16, Jin 9) on its T3 or TTT1
moves (TEKKEN3_NATIVE_MOVES). Each case reloads the same state, puts the two
2500 apart and fires through pad input, then samples the opponent's record
(+0x54), its frame and both lives, with a capture every sample for the GIFs.
In the arcade (tools/ttt1_jack_haywire.lua) the Jacks play the laser's stun
(alias E23) for 30 frames, then E24 / E25 (the charge) / E26 (the Windmill
Punch, which hits the shooter); anyone else only the stun. The report names
the shooter's pack records the opponent went through, by their TTT1 address.
Output: workspace/ttt1-live/haywire-<opponent>-<moves>-<tag>/.
"""
import argparse, json, struct, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live
from ttt1_live import Session, cabinet, idle, GUEST_ID
from test_ttt1_lasers import P1, P2, CLEAN, CR, CI, SQ, TR, pad, place, refill, ints, gap

NATIVES = dict(gunjack=16, jin=9)
# TTT1 records of the haywire (the same in the three Jacks' RAM).
HAYWIRE = {0x8007c874: 'E23 stun', 0x8005c68c: 'E24 haywire', 0x8005c6c0: 'E25 charge',
           0x8005c6f4: 'E26 windmill', 0x80044400: '1346 clock up', 0x8006517c: 'B52 slide',
           0x80065114: 'B48 slide end'}
CASES = {
    'inferno': dict(steps=[(3, pad(SQ, TR)), (260, 0xffff)]),
    'blaster': dict(steps=[(3, pad(CR, CI)), (300, 0xffff)]),
}


def pack_records(s, guest):
    """Shooter's pack: TTT1 address of each record, by its RAM address."""
    pack = (s.assets / f'{guest.capitalize()}-TTT1-combat.jmv').read_bytes()
    count = struct.unpack_from('<I', pack, 12)[0]
    base = ttt1_live.records(s)[0]
    return {base + i * 56: struct.unpack_from('<I', pack, 32 + i * 16 + 4)[0] for i in range(count)}


def play(s, name, case, out, names, shots=True):
    s.q(cmd='clear_input')
    s.q(cmd='savestate', op='load', slot=CLEAN)
    time.sleep(.8)
    place(s, 2500)
    life0, own0 = s.value(P2 + 0x3f4), s.value(P1 + 0x3f4)
    s.q(cmd='input_route_clear')
    for n, b in case['steps']: s.q(cmd='input_route_append', frames=n, buttons=b)
    s.q(cmd='input_route_start')
    samples, shot = [], 0
    out.mkdir(parents=True, exist_ok=True)
    while s.q(cmd='input_route_status').get('active'):
        record = s.value(P2 + 0x54)
        raw = s.read(P1 + 0x20c, 280)       # the shooter's 14 spheres: x, y, z, radius
        spheres = [struct.unpack_from('<3ih', raw, 20 * i) for i in range(14)]
        capsule = ints(s, P2 + 0x1ac, 6)
        samples.append(dict(frame=s.q(cmd='frame')['frame'], record=f'{record:08x}',
                            ttt1=names.get(record), move_frame=s.value(P2 + 0x58, 2),
                            shooter=names.get(s.value(P1 + 0x54)), shooter_frame=s.value(P1 + 0x58, 2),
                            p2=ints(s, P2, 3), capsule=capsule, gap=gap(capsule, spheres),
                            # Gates of T3's hit test (0x800440F0..0x80044288, 0x80047BBC):
                            # attacker +0xC3, +0x83/+0x84 (per side), +0x64, +0xE3, +0xE6;
                            # defender +0xC3, +0xC5, +0x104.
                            gates=dict(a_c3=s.value(P2 + 0xc3, 1), a_83=s.value(P2 + 0x83, 2), a_64=s.value(P2 + 0x64, 2),
                                       a_e3=s.value(P2 + 0xe3, 1), a_e6=s.value(P2 + 0xe6, 1), d_c3=s.value(P1 + 0xc3, 1),
                                       d_c5=s.value(P1 + 0xc5, 1), d_104=s.value(P1 + 0x104, 2), a_60=s.value(P2 + 0x60, 2)), life=s.value(P2 + 0x3f4) / 65536, devil_life=s.value(P1 + 0x3f4) / 65536))
        if shots and shot < 400 and (shot or s.value(P1 + 0x58, 2) >= 8):
            s.q(cmd='screenshot', path=str(out / f'{name}-{shot:03d}.png')); shot += 1
        time.sleep(.005)
    moves = []
    for x in samples:
        label = HAYWIRE.get(x['ttt1'], f"{x['ttt1']:08x}" if x['ttt1'] else 'own ' + x['record'])
        if not moves or moves[-1][0] != label: moves.append([label, x['move_frame'], x['move_frame'], 1])
        else: moves[-1][2] = x['move_frame']; moves[-1][3] += 1
    return dict(name=name, damage=(life0 - s.value(P2 + 0x3f4)) / 65536,
                devil_damage=(own0 - s.value(P1 + 0x3f4)) / 65536, moves=moves, samples=samples, shots=shot)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--guest', default='devil')
    ap.add_argument('--opponent', default='jack2')
    ap.add_argument('--moves', default='t3', choices=('t3', 'ttt1'))
    ap.add_argument('--tag', default='after')
    ap.add_argument('--no-shots', action='store_true', help='no captures: finer sampling')
    ap.add_argument('--assets', help='another TTT1 catalogue (TEKKEN3_TTT1_ASSETS), e.g. the packs from before')
    ap.add_argument('--case', nargs='*', default=list(CASES))
    args = ap.parse_args()
    native = NATIVES.get(args.opponent)
    out = ttt1_live.WORK / f'haywire-{args.opponent}{"-" + args.moves if native else ""}-{args.tag}'
    build = Path(args.build)
    if not build.is_absolute(): build = ttt1_live.ROOT / build
    env = {'TEKKEN3_NATIVE_MOVES': '1' if args.moves == 'ttt1' else '0'}
    if native is None: env['TEKKEN3_GUEST_P2'] = args.opponent
    if args.assets: env['TEKKEN3_TTT1_ASSETS'] = str(Path(args.assets).resolve())
    s = Session(guest=args.guest, build=build, env=env)
    if args.assets: s.assets = Path(args.assets).resolve()
    report = []
    try:
        cabinet(s, opponent=GUEST_ID if native is None else native)
        s.write(P2 + 0xc5, 0, 1)        # the opponent stands still (no CPU)
        time.sleep(3)
        idle(s, 0, 30)
        s.wait(lambda: ints(s, P2 + 0x20c + 20 * 8, 3)[1] < -1300, 'the opponent is not standing', 30)
        refill(s)
        s.q(cmd='savestate', op='save', slot=CLEAN)
        time.sleep(1)
        names = pack_records(s, args.guest)
        for name in args.case:
            result = play(s, name, CASES[name], out, names, not args.no_shots)
            print(f"{name}: opponent -{result['damage']:.1f}, {args.guest} -{result['devil_damage']:.1f}, "
                  f"{result['shots']} captures", flush=True)
            print('  opponent moves (label, first frame, last frame, samples):', result['moves'], flush=True)
            report.append(result)
            (out / 'report.json').write_text(json.dumps(report, indent=1))
    finally:
        s.stop()


if __name__ == '__main__':
    main()
