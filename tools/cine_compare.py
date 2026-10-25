#!/usr/bin/env python3
"""Compare two recordings of a cinematic (TEKKEN3_CINE_RECORD, src/tekken3_cine.c):
two builds' (a reference before a change, then after it), or two runs.

    python tools/cine_compare.py OLD.bin NEW.bin [--from F] [--to F] [--every N]

Per frame and actor: the skeleton's root (actor + 0xF54: rotation, then
translation), its 18 bones' local rotations (+0xF74) and the actor's
position (+0x00); the camera's eye and target. Prints the frames each
recording covers, then the largest differences (root translation and
position in stage units, rotations in 1/4096, camera in stage units) over
the frames both have, and the frames where they are largest.
"""
import argparse, struct
from pathlib import Path

ACTOR = 32 + 576 + 16


def load(path):
    """{frame: {0: bytes, 1: bytes, -1: (eye, target)}}, the last record of each kind a frame."""
    data, out, i = Path(path).read_bytes(), {}, 0
    while i + 8 <= len(data):
        frame, kind = struct.unpack_from('<ii', data, i); i += 8
        if kind < 0:
            out.setdefault(frame, {})[-1] = struct.unpack_from('<6i', data, i); i += 24
        else:
            out.setdefault(frame, {})[kind] = data[i:i + ACTOR]; i += ACTOR
    return out


def actor(b):
    root = struct.unpack_from('<9h', b, 0), struct.unpack_from('<3i', b, 20)
    bones = [struct.unpack_from('<9h', b, 32 + k * 32) for k in range(18)]
    pos = struct.unpack_from('<3i', b, 608)
    facing = struct.unpack_from('<h', b, 608 + 14)[0]
    return root, bones, pos, facing


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('old'); ap.add_argument('new')
    ap.add_argument('--from', dest='first', type=int, default=0)
    ap.add_argument('--to', type=int, default=10 ** 9)
    ap.add_argument('--every', type=int, default=0, help='print each N-th frame')
    a = ap.parse_args()
    old, new = load(a.old), load(a.new)
    for name, rec in (('old', old), ('new', new)):
        fr = sorted(rec)
        print(f'{name}: frames {fr[0]}..{fr[-1]} ({len(fr)})' if fr else f'{name}: empty')
    frames = [f for f in sorted(set(old) & set(new)) if a.first <= f <= a.to]
    worst = {}
    def note(key, value, frame):
        if value > worst.get(key, (-1, 0))[0]: worst[key] = (value, frame)
    for f in frames:
        for k in (0, 1):
            if k not in old[f] or k not in new[f]: continue
            (ro, to), bo, po, fo = actor(old[f][k])
            (rn, tn), bn, pn, fn = actor(new[f][k])
            note(f'P{k + 1} root translation', max(abs(x - y) for x, y in zip(to, tn)), f)
            note(f'P{k + 1} root rotation', max(abs(x - y) for x, y in zip(ro, rn)), f)
            note(f'P{k + 1} bones', max(abs(x - y) for b1, b2 in zip(bo, bn) for x, y in zip(b1, b2)), f)
            note(f'P{k + 1} position', max(abs(x - y) for x, y in zip(po, pn)), f)
            if a.every and not f % a.every:
                print(f, f'P{k + 1}', 'root', to, tn, 'pos', po, pn, 'facing', fo, fn)
        if -1 in old[f] and -1 in new[f]:
            note('camera', max(abs(x - y) for x, y in zip(old[f][-1], new[f][-1])), f)
    print(f'{len(frames)} frames compared')
    for key, (value, frame) in sorted(worst.items()):
        print(f'  {key:22s} max {value:6d} (frame {frame})')


if __name__ == '__main__':
    main()
