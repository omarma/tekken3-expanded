#!/usr/bin/env python3
"""How the CPU answers Devil's (or Angel's) lasers, without a player.

    python3 tools/test_cpu_lasers.py [--build build-rel-lite] [--guest devil] [--tries 8] [--tag NAME]

Devil (player 1, scripted pad input) against a CPU Jin at the PS1 HARD
difficulty (0x80097F06 / 0x800AE208 = 2; TTT1's SUPER HARD is its match,
see the arcade-difficulty notes). One clean state is saved once both stand;
each try reloads it, draws a new random seed (0x800ADCA0, the generator the
CPU's choices read), waits a delay that varies with the try and fires,
Inferno and Devil Blaster in turn: the protocol of tools/ttt1_cpu_lasers.lua
(TTT1 in MAME). The CPU stays in charge of Jin: the test records the
distance, whether the beam left (the record reached its active window),
whether it hit, how far Jin moved across the line between the heads (a side
step) or down (his head), and his moves (+0xA0).
Report: workspace/ttt1-live/cpu-lasers-<tag>/report.json.
"""
import argparse, json, random, struct, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live
from ttt1_live import Session, cabinet, idle, ROOT

P1, P2, STRIDE = 0x800a9228, 0x800aaab4, 0x188c
JIN, CLEAN, SEED = 9, 9, 0x800adca0
PROBE = None           # --probe: the CPU's state each sample
START = 1660           # distance of the fighters at the start of a TTT1 round (tools/ttt1_cpu_lasers.lua)
OPTIONS_DIFFICULTY, DIFFICULTY, HARD = 0x80097f06, 0x800ae208, 2
U, R, D, L, TR, CI, CR, SQ = 4, 5, 6, 7, 12, 13, 14, 15


def pad(*bits):
    m = 0xffff
    for b in bits: m &= ~(1 << b)
    return m


# Same protocol as tools/ttt1_cpu_lasers.lua (TTT1 in MAME): from the saved
# state, a delay that varies with the try, then the shot; the two alternate.
SHOTS = [
    dict(name='inferno', buttons=pad(SQ, TR), watch=130, moves={0x8006b5d4}),
    dict(name='blaster', buttons=pad(CR, CI), watch=210, moves={0x8006b63c}),
]


def ints(s, a, n): return struct.unpack(f'<{n}i', s.read(a, 4 * n))


def put(s, a, *words):
    s.q(cmd='write_ram', addr=f'{a:08x}', bytes=struct.pack(f'<{len(words)}i', *words).hex())


def head(s, a): return ints(s, a + 0x908 + 2 * 68, 3)


def attempt(s, shot, delay, seed, distance=None):
    distance = distance or START
    s.q(cmd='clear_input')
    s.q(cmd='savestate', op='load', slot=CLEAN)
    time.sleep(.4)
    put(s, SEED, seed)
    for p, x in ((0, -distance // 2), (1, distance // 2)):
        a = P1 + p * STRIDE
        put(s, a + 0xf68, x); put(s, a + 0xf70, 0); put(s, a, x); put(s, a + 8, 0)
    put(s, P1 + 0x3f4, s.value(P1 + 0x3f8))
    s.q(cmd='input_route_clear')
    s.q(cmd='input_route_append', frames=4 + delay, buttons=0xffff)
    s.q(cmd='input_route_append', frames=3, buttons=shot['buttons'])
    s.q(cmd='input_route_append', frames=shot['watch'], buttons=0xffff)
    f0 = s.q(cmd='frame')['frame']
    s.q(cmd='input_route_start')
    while s.q(cmd='frame')['frame'] < f0 + 4 + delay: time.sleep(.005)
    (x1, _, z1), (x2, y2, z2) = head(s, P1), head(s, P2)
    ax, az = x2 - x1, z2 - z1
    d = (ax * ax + az * az) ** .5 or 1
    ux, uz = ax / d, az / d
    life0 = s.value(P2 + 0x3f4)
    lat = low = 0; fired = False; moves = []
    while s.q(cmd='input_route_status').get('active'):
        put(s, P1 + 0x3f4, s.value(P1 + 0x3f8))
        record = s.value(P1 + 0x54)
        if record in shot['records'] and s.value(P1 + 0x58, 2) >= s.value(record + 45, 1): fired = True
        m = s.value(P2 + 0xa0, 2)
        if not moves or moves[-1] != m: moves.append(m)
        hx, hy, hz = head(s, P2)
        if PROBE is not None:
            ai = 0x8009f318 + 0x330 * s.value(P2 + 0x1886, 1)
            PROBE.append(dict(frame=s.q(cmd='frame')['frame'], move=m, side=int(abs((hx - x2) * uz - (hz - z2) * ux)),
                              ai=s.read(ai, 0x100).hex()))
        dx, dz = hx - x2, hz - z2
        lat = max(lat, abs(dx * uz - dz * ux)); low = max(low, hy - y2)
        time.sleep(.005)
    life1 = s.value(P2 + 0x3f4)
    return dict(move=shot['name'], delay=delay, distance=int(d), fired=fired, life0=life0, life1=life1,
                hit=life1 < life0, sideways=int(lat), duck=int(low), cpu_moves=moves)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--guest', default='devil')
    ap.add_argument('--tries', type=int, default=20)
    ap.add_argument('--tag', default='now')
    ap.add_argument('--distance', type=int, default=START, help='both put this far apart before each try')
    ap.add_argument('--probe', action='store_true', help="record the CPU's decision state each sample")
    ap.add_argument('--no-dodge', action='store_true', help='TEKKEN3_CPU_LASER_DODGE=0: the CPU does not see the lasers coming')
    args = ap.parse_args()
    out = ttt1_live.WORK / f'cpu-lasers-{args.tag}'
    out.mkdir(parents=True, exist_ok=True)
    build = Path(args.build)
    if not build.is_absolute(): build = ROOT / build
    s = Session(guest=args.guest, build=build, env={'TEKKEN3_CPU_LASER_DODGE': '0'} if args.no_dodge else None)
    global PROBE
    if args.probe: PROBE = []
    rng = random.Random(1234)
    report = {}
    try:
        s.write(OPTIONS_DIFFICULTY, HARD, 1)
        cabinet(s, opponent=JIN)
        s.write(DIFFICULTY, HARD, 2)
        print('difficulty', s.value(DIFFICULTY, 2), 'options', s.value(OPTIONS_DIFFICULTY, 1), flush=True)
        # Devil's intro ignores input: the state once he stands in neutral;
        # each try then puts both back at the arcade's starting distance.
        time.sleep(3)
        idle(s, 0, 30)
        for a in (P1, P2): put(s, a + 0x3f4, s.value(a + 0x3f8))
        s.q(cmd='savestate', op='save', slot=CLEAN)
        time.sleep(1)
        base = ttt1_live.records(s)[0]
        pack = (s.assets / f'{args.guest.capitalize()}-TTT1-combat.jmv').read_bytes()
        count = struct.unpack_from('<I', pack, 12)[0]; first = 32 + count * 16
        laser = lambda t: {base + i * 56 for i in range(count) if pack[first + i * 56 + 40] == 0x3f and pack[first + i * 56 + 41] == t}
        SHOTS[0]['records'], SHOTS[1]['records'] = laser(1), laser(2)
        tries = []
        for k in range(1, args.tries * len(SHOTS) + 1):
            t = attempt(s, SHOTS[(k - 1) % len(SHOTS)], (k * 37) % 61, rng.randrange(1 << 31), args.distance)
            tries.append(t)
            print(k, {x: t[x] for x in ('move', 'delay', 'distance', 'fired', 'hit', 'sideways', 'duck')}, flush=True)
            (out / 'report.json').write_text(json.dumps(tries, indent=1))
            if PROBE is not None: (out / 'probe.json').write_text(json.dumps(PROBE))
        for name in ('inferno', 'blaster'):
            fired = [t for t in tries if t['move'] == name and t['fired']]
            print(f"{name}: fired {len(fired)}, hit {sum(t['hit'] for t in fired)}", flush=True)
    finally:
        s.stop()


if __name__ == '__main__':
    main()
