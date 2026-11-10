#!/usr/bin/env python3
"""Dark Resurrection's move cameras, for Tekken 3 (src/tekken3_dr_camera.c, PSP-DR.md A3 "Caméra").

    python tools/psp/dr_camera.py tracks take.frames.json... [--char jin] [--out tools/psp/data/dr_camera_<char>.json]
    python tools/psp/dr_camera.py pack OUT/Paul-DR-camera.txt --report report.json [--tracks ...] [--sheet ...]

`tracks` turns takes into a track per DR move, kept in tools/psp/data (numbers, 21 KB for Paul: the
user's choice of 2026-10-25, the takes need PPSSPP and the game). `pack` writes the runtime's file for
a pack from dr_pack.py's report (its records); tools/dr_setup.py calls it after dr_pack.py.

In DR a move's extra property 0x815f (entry (0x8001 | 0x815f << 16, value), read as the move starts)
picks a camera of the engine, not a track of the moveset: 6 cuts to a close shot a few frames after
the move's hit (the Deathfist family), 82..90 and 27 turn round the fighters during a throw. The
cameras are taken from takes of DR filmed frame by frame (PPSSPP's memory, a frame per tick of the
player's counter +0x2D8): the camera 0x09B0FFB0 (eye +0x140, point looked at +0x150, view rows
+0x00 / +0x10 / +0x20 and their translation -R . eye +0x30, horizontal field of view in degrees +0x164,
55 in a fight), both players' hips (translation +0x760 / +0x768 of their
world matrix +0x730) and moves. The floor is at y 0.

A track is written in the attacker's frame at its first frame: origin on the floor under his hips,
forward towards the opponent's hips, up, and across the side the camera is on (Tekken 3 mirrors it
to the side its camera is on). Distances x 0.96 across the floor, x 0.95 up (the root's scale of
tools/psp/dr_convert.py). The target is the eye plus the view's third row, as far as the point
looked at: a hit's cut shakes the view's rotation, not its eye or that point. The projection
distance gives Tekken 3's 368-pixel wide screen DR's field of view (184 / tan(fov / 2): 353 for
DR's 55, Tekken 3's own is 500 with a camera farther away).

A hit's track starts `delay` frames after the opponent's move changes in the attacker's move (the
first frame of the cut) and lasts as long as the field of view is not 55; a cut, no blend. Its eye
is on a circle round the point looked at, across from it or 60 degrees towards either end of the
fight's line, drawn by DR (two takes of a move gave both ends): written across, with that point
(the pivot), and Tekken 3 turns it. A throw's
starts with its record and lasts until the field of view is back to 55, blended in and out with
Tekken 3's camera. Records: each pack record whose DR move has a track; a move without one uses the
track of the move named in SHARED.

DR draws a throw's camera among several (Jin's 1+3: three in 24 takes, PSP-DR.md J7). `tracks` sorts
a throw's takes into variants (eye turned the same way round the thrower, within VARIANT degrees all
along) and keeps each variant's middle take, weighted by its takes; Tekken 3 then draws among them as
camera_seq_load draws its own (rand() & 0xFFF against cumulative thresholds).

Out: "DRCAM 1" ("DRCAM 2" when a record has variants), then per track
"track <record> <hit|throw> <delay> <blend in> <blend out> <frames>" (DRCAM 2 adds the threshold, 0..4095:
a record's tracks in order, the first not below the draw plays; a hit then adds its pivot: across, forward)
and a line per frame: eye (across, up, forward), target, projection distance.
"""
import argparse, csv, json, math, struct, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / 'tools/t5')]

CAMERA = 0x815f
HIT = {6}
DR_FOV = 55.0
ACROSS, UP = 0.96, 0.95
BLEND_IN, BLEND_OUT = 8, 16
# Moves with no take of their own, played with another's: the just frame's late press.
SHARED = {'Pl_hazlp01': 'Pl_hazlpJST'}


def camera_values(name='Paul'):
    """{DR move name: value of its property 0x815f}, read from the ISO."""
    import dr_iso as D
    import t5_moveset as T
    disc = D.Disc()
    mot = D.moveset_from_iso(disc, name, D.H1, D.ANIMS1, D.COMMON1)
    ram = D.fake_ram(mot, D.H1)
    m = T.Moveset(ram, 0, T.DR)
    a, _ = m.lists['move']
    out = {}
    for i, v in enumerate(m.moves):
        p = m.u32(a + i * 76 + 0x30)
        for k in range(64) if p else ():
            x, val = struct.unpack_from('<II', ram, m.off(p + 8 * k))
            if not x and not val: break
            if x >> 16 == CAMERA: out[v['name']] = val
    return out


def records(report, sheet):
    """{DR move name: [pack records]}: a command's record (the sheet's DR move, or the report's own
    name for moves off the sheet) and the records a throw lists."""
    dr_of = {r['commande']: r['DR coup'] for r in csv.DictReader(open(sheet, encoding='utf-8'), delimiter='\t')}
    out = {}
    for cmd, m in report['moves'].items():
        name = dr_of.get(cmd) or cmd
        if isinstance(m.get('record'), int): out.setdefault(name, []).append(m['record'])
        for r, n in m.get('throw_records', ()):
            out.setdefault(n, []).append(r)
        # A new throw's sides (dr_pack new_throw: record, DR move, its victim's record and move, damage).
        for r, n, *_ in m.get('sides_made', ()):
            out.setdefault(n, []).append(r)
    return {k: sorted(set(v)) for k, v in out.items()}


def track(frames, move, hit):
    """(delay, frames of the track) of the take's camera in `move`, or None."""
    at = [i for i, f in enumerate(frames) if f['m1'] == move]
    if not at: return None
    wide = lambda f: abs(f['fov'] - DR_FOV) < 0.01
    if hit:
        before = frames[at[0]]['m2']
        h = next((i for i in at if frames[i]['m2'] != before), None)
        if h is None: return None
        c = next((i for i in range(h, len(frames)) if not wide(frames[i])), None)
        if c is None: return None
        e = c
        while e + 1 < len(frames) and not wide(frames[e + 1]): e += 1
        return c - h, frames[c:e + 1]
    s = at[0]
    turned = [i for i in range(s, len(frames)) if not wide(frames[i])]
    e = turned[0] if turned else at[-1]
    while turned and e + 1 < len(frames) and not wide(frames[e + 1]): e += 1
    return 0, frames[s:max(e, at[-1]) + 1]


def local(frames):
    """Each frame's eye, target and projection distance in the first frame's attacker frame."""
    f0 = frames[0]
    ox, oz = f0['h1']
    dx, dz = f0['h2'][0] - ox, f0['h2'][1] - oz
    n = math.hypot(dx, dz) or 1.0
    fx, fz = dx / n, dz / n
    sx, sz = fz, -fx                        # across, as the runtime (side then picked by the camera)
    e0 = f0['eye']
    side = 1 if (e0[0] - ox) * sx + (e0[2] - oz) * sz >= 0 else -1
    def point(p):
        x, z = p[0] - ox, p[2] - oz
        return [round(side * (x * sx + z * sz) * ACROSS), round(p[1] * UP), round((x * fx + z * fz) * ACROSS)]
    out = []
    for f in frames:
        e, v = f['eye'], f['view']
        d = math.dist(e, f['target'])
        out.append(point(e) + point([e[k] + v[k] * d for k in range(3)]) + [round(184 / math.tan(math.radians(f['fov']) / 2))])
    return out


def to_side(keys):
    """A hit's cut turned round the point looked at (its first frame's target) so that its eye is
    straight across from it, and that point: DR draws the cut's angle, across or 60 degrees
    towards either end of the fight's line (the same move gave both ends in two takes)."""
    ps, pf = keys[0][3], keys[0][5]
    a = math.atan2(keys[0][2] - pf, keys[0][0] - ps)
    c, s = math.cos(-a), math.sin(-a)
    out = []
    for k in keys:
        row = list(k)
        for i in (0, 3):
            x, z = k[i] - ps, k[i + 2] - pf
            row[i], row[i + 2] = round(ps + x * c - z * s), round(pf + x * s + z * c)
        out.append(row)
    return out, (ps, pf), round(math.degrees(a))


VARIANT = 30.0     # degrees: two takes of a throw whose eyes turn apart more than that are two variants


def turn(keys):
    """The eye's angle round the thrower (degrees, across against forward), per frame."""
    return [math.degrees(math.atan2(k[0], k[2])) for k in keys]


def apart(a, b):
    """The largest angle between two takes' eyes over their common frames."""
    return max((abs((x - y + 180) % 360 - 180) for x, y in zip(turn(a), turn(b))), default=0.0)


def variants(takes):
    """takes: [(name, keys)] of one throw. [(middle take's name, its keys, number of takes)], most taken first."""
    groups = []
    for name, keys in takes:
        g = next((g for g in groups if apart(g[0][1], keys) <= VARIANT), None)
        if g is None: groups.append([(name, keys)])
        else: g.append((name, keys))
    out = []
    for g in groups:
        mid = min(g, key=lambda t: sum(apart(t[1], u[1]) for u in g))
        out.append((mid[0], mid[1], len(g)))
    return sorted(out, key=lambda v: -v[2])


NL = '\n'
TRACKS = HERE / 'data/dr_camera_paul.json'


def cmd_tracks(a):
    values = camera_values(a.char.capitalize())
    a.out = a.out or HERE / f'data/dr_camera_{a.char}.json'
    found, takes = {}, {}
    for path in a.takes:
        frames = json.loads(path.read_text())['frames']
        for move in dict.fromkeys(f['m1'] for f in frames):
            if move not in values: continue
            hit = values[move] in HIT
            if hit and move in found: continue
            got = track(frames, move, hit)
            if not got or len(got[1]) < 2: continue
            keys, pivot, angle = local(got[1]), None, None
            if hit:
                keys, pivot, angle = to_side(keys)
                found[move] = dict(value=values[move], hit=hit, delay=got[0], pivot=pivot, take=path.name, keys=keys)
                print(f'{move}: hit {values[move]}, {len(keys)} frames, delay {got[0]}, taken at {angle} degrees ({path.name})')
            else:
                takes.setdefault(move, []).append((path.name, keys))
    for move, ts in takes.items():
        vs = variants(ts)
        found[move] = dict(value=values[move], hit=False, delay=0, pivot=None, take=vs[0][0], keys=vs[0][1])
        if len(vs) > 1:
            found[move]['variants'] = [dict(take=n, takes=c, keys=k) for n, k, c in vs]
        print(f'{move}: throw {values[move]}, {len(ts)} takes, '
              + ', '.join(f'{c} x {len(k)} frames ({n}, ends at {turn(k)[-1]:.0f} degrees)' for n, k, c in vs))
    missing = [m for m, v in sorted(values.items()) if (v in HIT or v >= 27) and m not in found and SHARED.get(m) not in found]
    if missing: print('no take: ' + ', '.join(missing))
    a.out.write_text(json.dumps(dict(_='tools/psp/dr_camera.py tracks; distances in Tekken 3 units', tracks=found),
                                separators=(',', ':')) + '\n')
    print(f'{a.out}: {len(found)} tracks')


def pack(out, report, tracks=TRACKS, sheet=ROOT / 'fiches/dr-paul.tsv', log=print):
    """<Name>-DR-camera.txt for a pack: the tracks on the records of dr_pack.py's report (a dict).
    Returns the number of tracks written."""
    found = json.loads(Path(tracks).read_text())['tracks']
    recs = records(report, sheet)
    drawn = any('variants' in found[m if m in found else SHARED.get(m)] for m in recs
                if (m if m in found else SHARED.get(m)) in found)
    lines = ['DRCAM 2' if drawn else 'DRCAM 1']
    for move, recs_of in sorted(recs.items()):
        src = move if move in found else SHARED.get(move)
        if src not in found: continue
        t = found[src]
        vs = t.get('variants') or [dict(takes=1, keys=t['keys'])]
        total, seen = sum(v['takes'] for v in vs), 0
        for r in recs_of:
            seen = 0
            for v in vs:
                seen += v['takes']
                # camera_seq_load's cumulative threshold: rand() & 0xFFF not above it plays this one
                thr = f' {4095 if seen == total else round(seen * 4096 / total) - 1}' if drawn else ''
                lines.append(f"track {r} {'hit' if t['hit'] else 'throw'} {t['delay']} {0 if t['hit'] else BLEND_IN} "
                             f"{0 if t['hit'] else BLEND_OUT} {len(v['keys'])}{thr}" + (' %d %d' % tuple(t['pivot']) if t['hit'] else ''))
                lines += [' '.join(map(str, k)) for k in v['keys']]
        log(f'{move}: records {recs_of}' + (f' (track of {src})' if src != move else '')
            + (f", {len(vs)} variants ({' / '.join(str(v['takes']) for v in vs)} takes)" if len(vs) > 1 else ''))
    unused = sorted(m for m in found if m not in recs)
    if unused: log('no pack record plays: ' + ', '.join(unused))
    out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(NL.join(lines) + NL)
    n = sum(l.startswith('track') for l in lines)
    log(f'{out}: {n} tracks')
    return n


def cmd_pack(a):
    pack(a.out, json.loads(a.report.read_text(encoding='utf-8', errors='replace')), a.tracks, a.sheet)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    t = sub.add_parser('tracks')
    t.add_argument('takes', type=Path, nargs='+')
    t.add_argument('--char', default='paul')
    t.add_argument('--out', type=Path, help='default tools/psp/data/dr_camera_<char>.json')
    p = sub.add_parser('pack')
    p.add_argument('out', type=Path)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--tracks', type=Path, default=TRACKS)
    p.add_argument('--sheet', type=Path, default=ROOT / 'fiches/dr-paul.tsv')
    a = ap.parse_args()
    {'tracks': cmd_tracks, 'pack': cmd_pack}[a.cmd](a)


if __name__ == '__main__':
    main()
