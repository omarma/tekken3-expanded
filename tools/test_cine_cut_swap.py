#!/usr/bin/env python3
"""A cinematic's character changes land on its camera's cuts: no actor seen
as its previous character in a new shot.

    python tools/test_cine_cut_swap.py [--build build-rel-lite] [--game OUT] [--cine embu] [--visible]

The .cine files: the build's mods/ttt-cinematics, or without --build made
again from tools/data/ttt_cinematics (tools/ttt_cinematics.py). In each one
an actor's `swap`, `show` and `hide` near a cut of the camera (the cuts as
src/tekken3_cine.c finds them in the track) must be on it: one a frame or
two before or after it is the old character, or the actor shown or gone,
in the other shot. The Embu before the fix: `show 0 2016`, `swap 0 xiaoyu
0 2017`, cut at 2017: Jun in Paul's shot one frame (the `show`s and `hide`s
taken at the script's command frame, the capture's camera and skeletons at
the frame after, tools/ps2/ttt_to_cine.py hidden_spans).

--game OUT also plays the --cine one in the build out of a fight
(tools/cine_scene_drive.py's TEKKEN3_CINE_SCENE_TEST, from the modes menu)
and reads in the log the frame each change is made at ("Cine: actor P
becomes X ... at tick T", the frame T - 2 - pre-roll): it must be its
`swap`'s, so that the frame of the cut is drawn with the new character.
Run it through ressources/slot.py (--kind game).

Exit 1 when a change misses its cut or lands on another frame in the game.
"""
import argparse, gzip, json, re, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
NEAR = 2                # frames off a cut that are a miss (beyond: a change inside the shot, as Devil Jin's at 2079)


def read_cine(path):
    """{actor: [(frame, what)]} of its `swap`s, `show`s and `hide`s (frame 0's apart), the cuts (the engine's rule)."""
    lines = path.read_text().split('\n')
    changes, cam, first = {}, [], 0
    for i, l in enumerate(lines):
        w = l.split()
        if not w: continue
        if w[0] == 'swap': changes.setdefault(int(w[1]), []).append((int(w[4]), f'swap {w[2]}'))
        elif w[0] in ('show', 'hide') and int(w[2]) > 0: changes.setdefault(int(w[1]), []).append((int(w[2]), w[0]))
        elif w[0] == 'camera':
            first = int(w[1]); cam = [list(map(int, lines[i + 1 + k].split())) for k in range(int(w[2]))]

    def jump(i): return max(abs(cam[i][k] - cam[i - 1][k]) for k in range(6)) if 0 < i < len(cam) else 0
    cuts = [first + i for i in range(1, len(cam)) if jump(i) >= 256 and jump(i) > 4 * max(jump(i - 1), jump(i + 1))]
    return changes, cuts


def misses(changes, cuts):
    return [(p, f, what, c) for p, v in changes.items() for f, what in v for c in cuts if 0 < abs(c - f) <= NEAR]


def made_cines(folder):
    """Each converted cinematic of tools/data/ttt_cinematics as a .cine in folder."""
    import ttt_cinematics as tc
    for d in sorted(tc.DATA.glob('*.json.gz')):
        key = d.name[:-len('.json.gz')]
        e = json.loads((tc.DATA / f'{key}.ending.json').read_text(encoding='utf-8'))
        tc.converted_cine(key, e, json.loads(gzip.decompress(d.read_bytes())), folder)
    return sorted(folder.glob('*.cine'))


def game(build, cine, out, visible):
    """The frame of each change the engine made, in order ([(actor, character, frame)])."""
    import cine_drive as cd
    out.mkdir(parents=True, exist_ok=True)
    g = cd.Game(build, out, {'TEKKEN3_CINE_SCENE_TEST': f'{cine.as_posix()}@4:30:0'}, visible)
    try:
        g.q(cmd='turbo', enabled=1)
        end = time.monotonic() + 900
        while 'Cine scene: over' not in g.log():
            if time.monotonic() > end: raise AssertionError('the scene never ended')
            if 'Cine scene: loading' not in g.log() and g.value(cd.STATE) == 3: g.press(cd.START)
            time.sleep(.2)
        log = g.log()
    finally:
        g.stop()
    m = re.search(r'Cine: "[^"]+" plays, \d+ frames after (\d+) of pre-roll', log)
    if not m: raise AssertionError('no "plays" line in the log')
    pre = int(m.group(1))
    return [(int(p), who, int(t) - 2 - pre) for p, who, t in re.findall(r'Cine: actor (\d) becomes (\S+) \(.*?\) at tick (\d+)', log) if int(t) > 0]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', help='the .cine files of this build (default: made again from tools/data)')
    ap.add_argument('--game', type=Path, metavar='OUT', help='also play --cine in the build, its log and pictures in OUT')
    ap.add_argument('--cine', default='embu')
    ap.add_argument('--visible', action='store_true')
    a = ap.parse_args()
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        files = sorted((ROOT / a.build / 'mods/ttt-cinematics').glob('*.cine')) if a.build else made_cines(Path(tmp))
        if not files: print('no .cine'); sys.exit(2)
        for path in files:
            changes, cuts = read_cine(path)
            miss = misses(changes, cuts)
            n = sum(len(v) for v in changes.values())
            print(f'{path.stem}: {n} changes, {len(cuts)} cuts:', 'OK' if not miss else 'ECHEC')
            for p, f, what, c in miss: print(f'  actor {p}: {what} at {f}, cut at {c}')
            bad += bool(miss)
    if a.game:
        if not a.build: print('--game needs --build'); sys.exit(2)
        cine = (ROOT / a.build / 'mods/ttt-cinematics' / f'{a.cine}.cine').resolve()
        changes, _ = read_cine(cine)
        want = sorted((p, w.split()[1], f) for p, v in changes.items() for f, w in v if w.startswith('swap'))
        got = sorted(game(ROOT / a.build, cine, a.game, a.visible))
        for (p, who, f), g in zip(want, got + [None] * len(want)):
            ok = g == (p, who, f)
            print(f'actor {p} becomes {who} at {f}: made at {g[2] if g else "never"}', 'OK' if ok else 'ECHEC')
            bad += not ok
        if len(got) > len(want): print('changes the .cine has not:', got[len(want):]); bad += 1
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
