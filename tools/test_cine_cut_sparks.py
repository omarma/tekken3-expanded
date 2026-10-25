#!/usr/bin/env python3
"""B61: a cinematic's hit sparks never outlive a cut of its camera.

    python tools/test_cine_cut_sparks.py OUT [--cine embu] [--build build-rel-lite] [--visible]

Plays mods/ttt-cinematics/<cine>.cine of the build out of a fight
(tools/cine_scene_drive.py's TEKKEN3_CINE_SCENE_TEST, from the modes menu) and
reads the game's three strong-hit effects all along (0x800A3408, 64 bytes
each, +2 the image shown, one more a frame, 0 when off). Each life of an
effect is a `spark` of the .cine, in order. A spark whose camera cuts before
its end (the cuts as src/tekken3_cine.c finds them in the track) must be off
after the cut: at most cut - spark + 1 images (the Embu: Paul's at 1834, cut
to Jun's shot at 1849, 16 at most; 30 before the fix). One with no cut in its
way plays its whole length. Exit 1 when a spark outlives its cut or one is
cut short, 2 when the lives do not match the sparks. OUT/lives.json. Run
through ressources/slot.py (--kind game).
"""
import argparse, json, struct, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cine_drive as cd

EFFECTS, SIZE, COUNT = 0x800a3408, 0x40, 3
LONGEST = 30            # images of a strong-hit effect (the header table 0x80027950: 22 or 30)


def read_cine(path):
    """The sparks' frames, the cuts' frames (the engine's rule) and the auras' spans."""
    lines = path.read_text().split('\n')
    sparks, auras, cam, first = [], [], [], 0
    for i, l in enumerate(lines):
        w = l.split()
        if not w: continue
        if w[0] == 'spark': sparks.append(int(w[1]))
        elif w[0] == 'aura': auras.append((int(w[2]), int(w[3])))
        elif w[0] == 'camera':
            first = int(w[1]); cam = [list(map(int, lines[i + 1 + k].split())) for k in range(int(w[2]))]

    def jump(i): return max(abs(cam[i][k] - cam[i - 1][k]) for k in range(6)) if 0 < i < len(cam) else 0
    cuts = [first + i for i in range(1, len(cam)) if jump(i) >= 256 and jump(i) > 4 * max(jump(i - 1), jump(i + 1))]
    return sorted(sparks), cuts, auras


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=Path)
    ap.add_argument('--cine', default='embu')
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--visible', action='store_true')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    build = ROOT / a.build
    path = (build / 'mods/ttt-cinematics' / f'{a.cine}.cine').resolve()
    sparks, cuts, auras = read_cine(path)
    print(f'{a.cine}: sparks {sparks}, cuts {cuts}, auras {auras}')
    g = cd.Game(build, a.out, {'TEKKEN3_CINE_SCENE_TEST': f'{path.as_posix()}@4:30:0'}, a.visible)
    lives, shown = [], [0] * COUNT
    try:
        g.q(cmd='turbo', enabled=1)
        end = time.monotonic() + 600
        while 'Cine scene: loading' not in g.log():
            if time.monotonic() > end: raise AssertionError('the scene never started')
            if g.value(cd.STATE) == 3: g.press(cd.START)
            time.sleep(.05)
        g.q(cmd='turbo', enabled=0)
        looked = 0
        while True:
            if time.monotonic() > looked + .5:            # the log read now and then: the reads as close as can be
                if 'Cine scene: over' in g.log(): break
                looked = time.monotonic()
            if time.monotonic() > end: raise AssertionError('the scene never ended')
            raw = g.read(EFFECTS, SIZE * COUNT)
            for k in range(COUNT):
                image = struct.unpack_from('<h', raw, SIZE * k + 2)[0]
                if image > 0 and (shown[k] <= 0 or image < shown[k]): lives.append({'slot': k, 'longest': image})
                if image > 0:
                    life = next(x for x in reversed(lives) if x['slot'] == k)
                    life['longest'] = max(life['longest'], image)
                shown[k] = image
    finally:
        (a.out / 'lives.json').write_text(json.dumps(lives))
        g.stop()
    print('lives (slot, most images seen):', [(x['slot'], x['longest']) for x in lives])
    if any(f <= s <= t for s in sparks for f, t in auras) or len(lives) != len(sparks):
        print(f'{len(lives)} lives for {len(sparks)} sparks (or an aura): not measured as sparks'); sys.exit(2)
    bad = 0
    for s, life in zip(sparks, lives):
        cut = next((c for c in cuts if s < c < s + LONGEST), None)
        n = life['longest']
        if cut is not None:
            ok = n <= cut - s + 1
            print(f'spark {s}: cut at {cut}, {n} images (at most {cut - s + 1}):', 'OK' if ok else 'ECHEC (outlives the cut)')
        else:
            ok = n >= 17          # sampled: under load the last images may fall between reads (19 of 22 seen)
            print(f'spark {s}: no cut, {n} images (its whole length):', 'OK' if ok else 'ECHEC (cut short)')
        bad += not ok
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
