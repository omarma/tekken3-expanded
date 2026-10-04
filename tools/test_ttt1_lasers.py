#!/usr/bin/env python3
"""Devil's (or Angel's) lasers in the running game, without a player.

    python3 tools/test_ttt1_lasers.py [--build build-rel-lite] [--guest devil] [--tag after] [--case NAME ...]

Devil against a still Jin (cabinet selector, tools/ttt1_live.py), the two
placed at a set distance, facing each other along x; each case plays a laser
through real pad input and samples, as often as the game lets it, player 1's
record, frame, facing (+0x2C), head and hit capsule (+0x1AC), and Jin's life.
'sidestep' moves Jin sideways (z) during Inferno's start-up, as a sidestep
would: the arcade's beam keeps Devil's facing and misses. Captures (one every
sample during the beam, for GIFs) and a JSON report go to
workspace/ttt1-live/lasers-<tag>/: the test measures the hits, the user
judges the beams.
"""
import argparse, json, struct, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live
from ttt1_live import Session, cabinet, idle, ROOT

P1, P2, STRIDE = 0x800a9228, 0x800aaab4, 0x188c
JIN = 9
CLEAN = 9                              # save state slot (the test's own copy of the saves)
U, R, D, L, TR, CI, CR, SQ = 4, 5, 6, 7, 12, 13, 14, 15


def pad(*bits):
    m = 0xffff
    for b in bits: m &= ~(1 << b)
    return m


# name: inputs (frames, buttons) facing right, distance, Jin's sideways
# shift and the frame of player 1's move it happens on.
CASES = {
    'inferno-1500': dict(steps=[(3, pad(SQ, TR)), (110, 0xffff)], distance=1500),
    'inferno-2500': dict(steps=[(3, pad(SQ, TR)), (110, 0xffff)], distance=2500),
    'inferno-3500': dict(steps=[(3, pad(SQ, TR)), (110, 0xffff)], distance=3500),
    'sidestep': dict(steps=[(3, pad(SQ, TR)), (110, 0xffff)], distance=2500, shift=(10, 900)),
    # Jin crosses under Devil's flight to the other side: the beam must
    # still leave the way Devil faces (it used to follow Jin).
    'cross': dict(steps=[(3, pad(CR, CI)), (200, 0xffff)], distance=2000, cross=40),
    # Jin at 1 point of life: the Inferno ends the round, then Devil's win
    # pose is captured (the arcade's long laser clip 0xAE0088 sweeps the sky).
    'win': dict(steps=[(3, pad(SQ, TR)), (110, 0xffff)], distance=1500, ko=True, after=18),
    'blaster-2000': dict(steps=[(3, pad(CR, CI)), (200, 0xffff)], distance=2000),
    'blaster-3500': dict(steps=[(3, pad(CR, CI)), (200, 0xffff)], distance=3500),
    'reverse-1200': dict(steps=[(3, pad(CR, CI)), (20, 0xffff), (3, pad(CR, CI)), (240, 0xffff)], distance=1200),
    'air-inferno-1500': dict(steps=[(3, pad(U, SQ, TR)), (90, 0xffff)], distance=1500),
    'air-inferno-2500': dict(steps=[(3, pad(U, SQ, TR)), (90, 0xffff)], distance=2500),
}


def ints(s, a, n): return struct.unpack(f'<{n}i', s.read(a, 4 * n))


def put(s, a, *words):
    s.q(cmd='write_ram', addr=f'{a:08x}', bytes=struct.pack(f'<{len(words)}i', *words).hex())


def gap(capsule, spheres):
    """Smallest distance from the capsule segment to a sphere's surface
    (negative: inside), and that sphere's index."""
    a, b = capsule[:3], capsule[3:]
    d = [b[i] - a[i] for i in range(3)]
    dd = sum(x * x for x in d) or 1
    best = None
    for k, (x, y, z, r) in enumerate(spheres):
        t = max(0, min(1, sum((c - a[i]) * d[i] for i, c in enumerate((x, y, z))) / dd))
        q = [a[i] + t * d[i] for i in range(3)]
        g = ((q[0] - x) ** 2 + (q[1] - y) ** 2 + (q[2] - z) ** 2) ** .5 - r
        if best is None or g < best[0]: best = (round(g), k)
    return best


def place(s, distance, z=0):
    """Player 1 at -distance/2, Jin at +distance/2, both at z, standing.
    Each position in one command: the engine copies +0xF68 to +0 every
    frame, and a byte-wise write races it."""
    for p, x in ((0, -distance // 2), (1, distance // 2)):
        a = P1 + p * STRIDE
        put(s, a + 0xf68, x); put(s, a + 0xf70, z); put(s, a, x); put(s, a + 8, z)
    print('  placed', [(ints(s, P1 + p * STRIDE, 3), ints(s, P1 + p * STRIDE + 0xf68, 3)) for p in (0, 1)], flush=True)
    time.sleep(.6)                     # the engine turns both to face each other


def refill(s):
    for p in (0, 1):
        a = P1 + p * STRIDE
        full = s.value(a + 0x3f8)
        if full: put(s, a + 0x3f4, full)


def play(s, name, case, out):
    # Every case from the same moment: both standing, full life (a laser
    # knocks down, and a knock-out would end the round).
    s.q(cmd='clear_input')
    s.q(cmd='savestate', op='load', slot=CLEAN)
    time.sleep(.8)
    place(s, case['distance'])
    life0 = s.value(P2 + 0x3f4)
    if case.get('ko'): put(s, P2 + 0x3f4, 0x10000)
    s.q(cmd='input_route_clear')
    for n, b in case['steps']: s.q(cmd='input_route_append', frames=n, buttons=b)
    s.q(cmd='input_route_start')
    samples, shifted, shot = [], False, 0
    while s.q(cmd='input_route_status').get('active'):
        frame = s.q(cmd='frame')['frame']
        record = s.value(P1 + 0x54)
        move_frame = s.value(P1 + 0x58, 2)
        facing = s.value(P1 + 0x2c, 2)
        head = ints(s, P1 + 0x908 + 2 * 68, 3)
        capsule = ints(s, P1 + 0x1ac, 6)
        jin = ints(s, P2, 3)
        life = s.value(P2 + 0x3f4)
        if 'shift' in case and not shifted and move_frame >= case['shift'][0] and move_frame < 60:
            put(s, P2 + 0xf70, jin[2] + case['shift'][1]); put(s, P2 + 8, jin[2] + case['shift'][1])
            shifted = True
        raw = s.read(P2 + 0x20c, 280)       # Jin's 14 spheres in one read: x, y, z, radius
        spheres = [struct.unpack_from('<3ih', raw, 20 * i) for i in range(14)]
        if 'cross' in case and not shifted and move_frame >= case['cross'] and move_frame < 100:
            put(s, P2 + 0xf68, -jin[0] - 1500); put(s, P2, -jin[0] - 1500)
            shifted = True
        samples.append(dict(frame=frame, gap=gap(capsule, spheres), record=f'{record:08x}', move_frame=move_frame, facing=facing,
                            head=head, capsule=capsule, jin=jin, jin_life=life / 65536))
        # Captures from the start-up to the end of the beam (capped).
        if move_frame >= 8 and shot < 150 and not case.get('after') and (shot or len(samples) > 1 and samples[-2]['record'] == samples[-1]['record']):
            s.q(cmd='screenshot', path=str(out / f'{name}-{shot:03d}.png')); shot += 1
        time.sleep(.005)
    out.mkdir(parents=True, exist_ok=True)
    if case.get('after'):
        # The round's end and the win pose: Devil's moves, one capture
        # every sample.
        end = time.monotonic() + case['after']
        while time.monotonic() < end:
            record, move_frame = s.value(P1 + 0x54), s.value(P1 + 0x58, 2)
            samples.append(dict(frame=s.q(cmd='frame')['frame'], record=f'{record:08x}', move_frame=move_frame,
                                capsule=ints(s, P1 + 0x1ac, 6), facing=s.value(P1 + 0x2c, 2), gap=None))
            s.q(cmd='screenshot', path=str(out / f'{name}-{shot:03d}.png')); shot += 1
            time.sleep(.05)
        moves = []
        for x in samples:
            if not moves or moves[-1][0] != x['record']: moves.append([x['record'], x['move_frame'], x['move_frame']])
            else: moves[-1][2] = x['move_frame']
        print('  moves (record, first frame, last frame):', moves, flush=True)
    time.sleep(.5)
    dealt = (life0 - s.value(P2 + 0x3f4)) / 65536
    return dict(name=name, distance=case['distance'], damage=dealt, samples=samples, shots=shot)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--guest', default='devil')
    ap.add_argument('--tag', default='after')
    ap.add_argument('--case', nargs='*', default=list(CASES))
    args = ap.parse_args()
    out = ttt1_live.WORK / f'lasers-{args.tag}'
    out.mkdir(parents=True, exist_ok=True)
    build = Path(args.build)
    if not build.is_absolute(): build = ROOT / build
    s = Session(guest=args.guest, build=build)
    report = []
    try:
        cabinet(s, opponent=JIN)
        s.write(P2 + 0xc5, 0, 1)        # Jin stands still (no CPU)
        time.sleep(3)
        idle(s, 0, 30)
        s.wait(lambda: ints(s, P2 + 0x20c + 20 * 8, 3)[1] < -1300,
               'Jin is not standing', 30)
        refill(s)
        s.q(cmd='savestate', op='save', slot=CLEAN)
        time.sleep(1)
        for name in args.case:
            if name == 'win':
                # Win poses are drawn at random: replay the round until the
                # one carrying the sky-sweep laser (beam type 5) comes up.
                pack = (s.assets / f'{args.guest.capitalize()}-TTT1-combat.jmv').read_bytes()
                count = struct.unpack_from('<I', pack, 12)[0]; first = 32 + count * 16
                sweep = [i for i in range(count) if pack[first + i * 56 + 40] == 0x3f and pack[first + i * 56 + 41] == 5]
                base = ttt1_live.records(s)[0]
                want = {f'{base + i * 56:08x}' for i in sweep}
                for attempt in range(10):
                    result = play(s, name, CASES[name], out / f'try{attempt}')
                    if want & {x['record'] for x in result['samples']}:
                        print(f'  sweep pose on attempt {attempt + 1}', flush=True); break
                else: print('  sweep pose never drawn', flush=True)
            else: result = play(s, name, CASES[name], out)
            beam = [x for x in result['samples'] if x['capsule'][:3] != x['capsule'][3:]]
            gaps = [x['gap'] for x in beam if x['gap'] and x['capsule'][:3] != x['capsule'][3:]]
            print(f"  closest beam-to-Jin gap {min(gaps) if gaps else '-'}", flush=True)
            print(f"{name}: distance {result['distance']}, damage {result['damage']:.1f}, "
                  f"{len(result['samples'])} samples, {result['shots']} captures, "
                  f"facing {sorted({x['facing'] for x in beam})[:6] if beam else '-'}", flush=True)
            report.append(result)
            (out / 'report.json').write_text(json.dumps(report, indent=1))
    finally:
        s.stop()


if __name__ == '__main__':
    main()
