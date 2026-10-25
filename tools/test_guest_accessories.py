#!/usr/bin/env python3
"""Guests' accessories (tails, hair, skirts, coat tails...) swing as in the arcade (F03, TIPS.md § 78).

    python tools/test_guest_accessories.py [--guest roger jun:3 ...] [--build build-rel-lite]
                                           [--memcard-dir saves] [--tag after] [--arcade DIR] [--shots N]

Boots a private copy of the build (software renderer, headless, x1) on a copy
of the memory card, takes Arcade from the modes menu, opens the Tag page (R2)
and confirms each guest; during the loading screen the costume (0x800ADD98)
and the opponent (Jin, standing still: no CPU) are set. The guest jumps twice,
walks forward and back (the route of tools/ttt1_tails.lua), while the local
rotation of its accessory bones 18..23 (actor +0xF74 + 32 * bone) is read every
frame the debug server answers.

What should swing comes from the costume's .acc file in the catalogue
(tools/ttt1/accessories.py, from the arcade's own table 0x8019D674): each bone
with a block must take at least MIN_POSES rotations and turn by MIN_DEGREES
from its first sample; every other accessory bone must stay still. --arcade
DIR prints the arcade's amplitude next to ours (DIR/<guest>-c<n>.csv, written
by tools/ttt1_tails.lua). Default: every guest and costume in the catalogue,
and Tetsujin on Roger's moves (no tail in the arcade: B47, GH#76).
Output: workspace/ttt1-live/accessories-<tag>/<guest>-c<n>.json.
"""
import argparse, csv, json, math, struct, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / 'ttt1'))
from test_force_moveset import Game, SCREEN, PHASE, LINE, START, CROSS
import accessories

ROOT = Path(__file__).resolve().parent.parent
GUEST_ID, JIN, P1, P2 = 23, 9, 0x800a9228, 0x800a9228 + 0x188c
GRID_COUNT, CURSOR, CURSOR_ID = 0x80118648, 0x80118650, 0x80118668
COSTUME, OPPONENT, OPPONENT_COSTUME = 0x800add98, 0x800add5e, 0x800add9a
LIFE, CLOCK = 0x800a961e, 0x800adbcc
R2, UP, DOWN, LEFT, RIGHT = 0xfdff, 0xffef, 0xffbf, 0xff7f, 0xffdf
BONES = (18, 19, 20, 21, 22, 23)        # 22 / 23: second meshes on their own bone (B59)
MIN_POSES, MIN_DEGREES, STILL_DEGREES = 8, 5.0, 0.5
# tools/ttt1_tails.lua's route: idle, two jumps, forward, back (facing right).
ROUTE = [(120, 0xffff), (8, UP), (70, 0xffff), (8, UP), (70, 0xffff), (90, RIGHT), (40, 0xffff),
         (60, LEFT), (40, 0xffff)]


def tag_place(k, count):
    """(row, column) of guest k on the Tag page (src/tekken3_ttt1_roster.c tag_place)."""
    return divmod(k, 8) if k < 16 else (k - 16, 8)


def angle(a, b):
    """Degrees between two 3x3 rotations in 4096ths."""
    tr = sum(a[i] * b[i] for i in range(9)) / 4096 / 4096
    return math.degrees(math.acos(max(-1.0, min(1.0, (tr - 1) / 2))))


def to_tag_page(g, count):
    def menu():
        if g.value(SCREEN) == 3: g.press(START)
        return g.value(SCREEN) == 4
    g.wait(menu, 'the modes menu never came', 180)
    time.sleep(.3)
    g.write(LINE, 0); g.press(CROSS)                     # Arcade
    g.wait(lambda: g.value(SCREEN) == 9 and g.value(GRID_COUNT) == 21, 'the Arcade selector never came', 20)
    time.sleep(1.5)
    g.press(R2)
    g.wait(lambda: g.value(GRID_COUNT) == count, 'R2 did not open the Tag page', 10)
    time.sleep(1.5)


def fight(g, index, count, costume):
    row, col = tag_place(index, count)
    for _ in range(16):
        r, c = tag_place(g.value(CURSOR), count)
        if (r, c) == (row, col): break
        g.press(DOWN if r < row else UP if r > row else RIGHT if c < col else LEFT)
    g.wait(lambda: g.value(CURSOR_ID) == GUEST_ID + index, 'the cursor did not reach the guest cell', 10)
    g.press(CROSS)
    g.wait(lambda: g.value(SCREEN) == 11, 'loading screen not reached', 15)
    g.write(COSTUME, costume - 1, 2)
    g.write(OPPONENT, JIN, 2); g.write(OPPONENT_COSTUME, 0, 2)
    g.wait(lambda: g.value(SCREEN) == 8 and g.value(PHASE, 2) >= 8 and g.value(P1 + 0x18, 2) == GUEST_ID + index,
           'the fight never started', 120)
    g.write(P2 + 0xc5, 0, 1)                             # Jin stands still (no CPU)
    time.sleep(2)


def sample(g, every, out, name, world=False):
    g.q(cmd='input_route_clear')
    for n, b in ROUTE: g.q(cmd='input_route_append', frames=n, buttons=b)
    g.q(cmd='input_route_start')
    # Two queries a sample: the matrices change every frame and the debug
    # server answers a few times a frame at best.
    full, samples, shots, start = g.value(LIFE, 2), [], 0, g.q(cmd='frame')['frame']
    length = sum(n for n, _ in ROUTE)
    while (frame := g.q(cmd='frame')['frame'] - start) < length:
        raw = bytes.fromhex(g.q(cmd='read_ram', addr=f'{P1 + 0xf74 + 32 * BONES[0]:08x}', len=32 * len(BONES))['hex'])
        samples.append(dict(frame=frame, bones={b: struct.unpack_from('<9h', raw, 32 * i) for i, b in enumerate(BONES)}))
        if world:                       # bone records 0..23: world matrix +0, position +0x14 (B59)
            raw = bytes.fromhex(g.q(cmd='read_ram', addr=f'{P1 + 0x8f4:08x}', len=68 * 24)['hex'])
            samples[-1]['world'] = {b: struct.unpack_from('<9h', raw, 68 * b) + struct.unpack_from('<3i', raw, 68 * b + 0x14)
                                    for b in range(24)}
        if len(samples) % 50 == 0:
            g.write(CLOCK, 0x7000, 2)
            if g.value(LIFE, 2) < full: g.write(LIFE, full, 2)
        if every and frame >= shots * every:
            g.q(cmd='screenshot', path=str(out / f'{name}-{frame:04d}.png')); shots = frame // every + 1
    return samples


def arcade(folder, name):
    """TTT1 bone 18..23 -> its rotation by frame in a tools/ttt1_tails.lua capture (same route)."""
    path = folder / f'{name}.csv'
    if not path.is_file(): return {}
    mats = {}
    for r in csv.DictReader(path.open()):
        mats.setdefault(int(r['bone']), {})[int(r['frame'])] = [int(r[f'm{i}{j}']) for i in range(3) for j in range(3)]
    return {b: m for b, m in mats.items() if len(set(map(tuple, m.values()))) > 1}


def correlation(ours, theirs):
    """Median over the nine terms of the correlation of two rotations frame by frame."""
    frames = [f for f in ours if f in theirs]
    out = []
    for k in range(9):
        a, b = [ours[f][k] for f in frames], [theirs[f][k] for f in frames]
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        va, vb = sum((x - ma) ** 2 for x in a), sum((x - mb) ** 2 for x in b)
        if va and vb: out.append(sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb))
    return sorted(out)[len(out) // 2] if out else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--guest', nargs='*', help='key or key:costume (default: all, every costume)')
    ap.add_argument('--build', default=str(ROOT / 'build-rel-lite'))
    ap.add_argument('--memcard-dir', default=str(ROOT / 'saves'), help='copied, never written')
    ap.add_argument('--tag', default='after')
    ap.add_argument('--arcade', type=Path, help='folder of tools/ttt1_tails.lua captures, <guest>-c<n>.csv')
    ap.add_argument('--shots', type=int, default=0, metavar='N', help='a capture every N frames')
    ap.add_argument('--world', action='store_true', help='also the world frames of bones 0..23 in the JSON (B59: tools/b59_collision.py)')
    ap.add_argument('--native', action='store_true', help="T3's solver on the arcade's blocks (TEKKEN3_ACCESSORIES=native)")
    a = ap.parse_args()
    build = Path(a.build)
    roster = build / 'mods/ttt1'
    catalogue = [l.split()[0] for l in (roster / 'guests.txt').read_text().splitlines() if l.split()]
    if a.guest:
        cases = [(g.split(':')[0], int(g.split(':')[1]) if ':' in g else 1) for g in a.guest]
    else:
        cases = [(k, c) for k in catalogue for c in (1, 2, 3)
                 if c == 1 or (roster / f'{k.capitalize()}-TTT1-arcade-P{c}.3dm').is_file()]
    out = ROOT / 'workspace/ttt1-live' / f'accessories-{a.tag}'
    out.mkdir(parents=True, exist_ok=True)
    failed = []
    for key, costume in cases:
        name = f'{key}-c{costume}'
        expected = accessories.read(roster / f'{key.capitalize()}-TTT1-arcade-P{costume}.acc')
        env = {'TEKKEN3_TETSUJIN_MOVESET': 'roger'} if key == 'tetsujin' else {}
        if a.native: env['TEKKEN3_ACCESSORIES'] = 'native'
        g = Game(build, Path(a.memcard_dir), env)
        try:
            to_tag_page(g, len(catalogue))
            fight(g, catalogue.index(key), len(catalogue), costume)
            samples = sample(g, a.shots, out, name, a.world)
        except Exception as e:
            print(f'{name}: {e}', flush=True); failed.append(name); continue
        finally:
            g.stop()
        result = {}
        for b in BONES:
            mats = [s['bones'][b] for s in samples]
            result[b] = (len(set(mats)), max(angle(mats[0], m) for m in mats))
        ref = arcade(a.arcade, name) if a.arcade else {}
        (out / f'{name}.json').write_text(json.dumps(dict(samples=samples, swing=result, expected=expected), indent=0))
        bad = [b for b in BONES if (b in expected and (result[b][0] < MIN_POSES or result[b][1] < MIN_DEGREES))
               or (b not in expected and result[b][0] > 1 and result[b][1] > STILL_DEGREES)]
        cells = []
        for b in BONES:
            n, d = result[b]
            src = expected.get(b, {}).get('ttt1_bone')
            more = ''
            if src in ref:
                theirs = ref[src]; first = theirs[min(theirs)]
                corr = correlation({s['frame']: s['bones'][b] for s in samples}, theirs)
                more = f', arcade {max(angle(first, m) for m in theirs.values()):.0f}°' + (f', r {corr:.2f}' if corr is not None else '')
            cells.append(f'{b}: {n} / {d:.0f}°' + (f' (TTT1 {src}{more})' if src is not None else ''))
        print(f'{name}: {len(samples)} samples; rotations / largest angle: ' + ', '.join(cells)
              + (f'  WRONG {bad}' if bad else ''), flush=True)
        if bad: failed.append(name)
    if failed: sys.exit(f'accessories not as in the arcade: {", ".join(failed)}')


if __name__ == '__main__':
    main()
