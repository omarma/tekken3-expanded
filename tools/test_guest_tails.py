#!/usr/bin/env python3
"""Tails, ears, loincloth and hair of the guests swing like King's tail (B31, GH#52, TIPS.md § 68).

    python3 tools/test_guest_tails.py [--build build-rel-lite] [--guest roger alex armorking jun] [--king] [--tag after] [--shots N]

Each guest (or King, --king, the native reference) against a still Jin
(cabinet selector, tools/ttt1_live.py) jumps twice, walks forward and back
through pad input, while the local rotation of its accessory bones 18..21
(actor +0xF74 + 32 * bone, written by the native solver 0x80037CBC) is read
as often as the debug server answers. A rigid bone keeps one matrix: the
check fails unless each bone the arcade swings (SWINGS: Roger's tail and
ears, Alex's tail, Armor King's tail and loincloth, Jun's hair and bow on
her first costume) takes at least MIN_POSES distinct rotations and one of
its terms moves by MIN_SWING (in 4096ths) from the first sample.
Output: workspace/ttt1-live/tails-<tag>/<name>.json (and with --shots N a capture
every N frames, named by the frame of the route).
"""
import argparse, json, struct, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live
from ttt1_live import Session, cabinet, idle, ROOT
from test_ttt1_lasers import P1, P2, JIN, U, R, L, pad

KING = 3
BONES = (18, 19, 20, 21)
SWINGS = dict(roger=(18, 19, 20, 21), alex=(18, 19, 20), armorking=(18, 19, 20, 21), jun=(18, 19), king=(18, 19, 20))
MIN_POSES, MIN_SWING = 8, 200
# Two jumps, then forward and back (facing right), as frames of pad input.
ROUTE = [(8, pad(U)), (70, 0xffff), (8, pad(U)), (70, 0xffff), (90, pad(R)), (40, 0xffff),
         (60, pad(L)), (40, 0xffff)]


def king_fight(s):
    """King (player 1, his T3 moves) against Jin: square on King's cell opens
    the MOVESET card on TEKKEN 3, X takes it (tools/test_native_moves.py)."""
    s.wait(lambda: s.value(0x800ae204) == 9 and s.value(0x80118648) == 21, 'The stock selector grid never appeared', 20)
    time.sleep(1.5)
    for _ in range(48):                              # right along a row, then down a row
        if s.value(0x80118668) == KING: break
        before = s.value(0x80118668)
        s.press(0xffdf)
        if _ % 12 == 11 or s.value(0x80118668) == before: s.press(0xffbf)
    s.press(0x7fff)
    s.wait(lambda: 'P1 opens the MOVESET card' in s.log(), 'Square did not open the MOVESET card', 5)
    s.press(0xbfff)
    s.wait(lambda: s.value(0x800ae204) == 11, 'Loading screen not reached', 15)
    s.write(0x800add5e, JIN, 2); s.write(0x800add9a, 0, 2)
    s.fight(0, KING); s.fight(1, JIN)


def sample(s, out, name, every=0):
    s.q(cmd='input_route_clear')
    for n, b in ROUTE: s.q(cmd='input_route_append', frames=n, buttons=b)
    s.q(cmd='input_route_start')
    samples, shots, start = [], 0, s.q(cmd='frame')['frame']
    while s.q(cmd='input_route_status').get('active'):
        frame = s.q(cmd='frame')['frame'] - start
        raw = s.read(P1 + 0xf74 + 32 * BONES[0], 32 * len(BONES))
        samples.append(dict(frame=frame, head_y=struct.unpack('<i', s.read(P1 + 0x908 + 2 * 68 + 4))[0],
                            bones={b: struct.unpack_from('<9h', raw, 32 * i) for i, b in enumerate(BONES)}))
        if every and frame >= shots * every:          # frames for the before / after GIF
            s.shot(f'{out.name}/{name}-{frame:04d}'); shots = frame // every + 1
    return samples


def swing(samples, bone):
    mats = [x['bones'][bone] for x in samples]
    first = mats[0]
    return len(set(mats)), max(abs(m[i] - first[i]) for m in mats for i in range(9))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--guest', nargs='*', default=['roger', 'alex', 'armorking', 'jun'])
    ap.add_argument('--king', action='store_true', help='King (native) instead of the guests')
    ap.add_argument('--tag', default='after')
    ap.add_argument('--shots', type=int, default=0, metavar='N', help='a capture every N frames')
    args = ap.parse_args()
    out = ttt1_live.WORK / f'tails-{args.tag}'
    out.mkdir(parents=True, exist_ok=True)
    build = Path(args.build)
    if not build.is_absolute(): build = ROOT / build
    failed = []
    for name in (['king'] if args.king else args.guest):
        s = Session(guest='roger' if name == 'king' else name, build=build)
        try:
            if name == 'king': king_fight(s)
            else: cabinet(s, opponent=JIN)
            s.write(P2 + 0xc5, 0, 1)        # Jin stands still (no CPU)
            time.sleep(3)
            if name == 'king': time.sleep(8)      # King's intro: idle() reads a guest's pack
            else: idle(s, 0, 30)
            samples = sample(s, out, name, args.shots)
        finally:
            s.stop()
        result = {b: swing(samples, b) for b in BONES}
        (out / f'{name}.json').write_text(json.dumps(dict(samples=samples, swing=result), indent=0))
        rigid = [b for b in SWINGS[name] if result[b][0] < MIN_POSES or result[b][1] < MIN_SWING]
        ok = not rigid
        print(f"{name}: {len(samples)} samples; distinct rotations / largest swing per bone: "
              + ', '.join(f'{b}: {n} / {d}' for b, (n, d) in result.items()) + ('' if ok else f'  RIGID {rigid}'), flush=True)
        if not ok: failed.append(name)
    if failed: sys.exit(f'rigid accessory bones: {", ".join(failed)}')


if __name__ == '__main__':
    main()
