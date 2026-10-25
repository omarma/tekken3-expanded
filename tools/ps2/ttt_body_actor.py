#!/usr/bin/env python3
"""A static body of a TTT (PS2) ending (tools/ps2/ttt_static_bodies.py) as a
player of the converted cutscene: a retarget file (tools/ps2/ttt_retarget.py's
format) for the old ttt_ending_pack.py --p2 (removed with the old way of the
TTT cinematics, docs/CINE-LEGACY-REMOVAL.md), the body out of sight until the shot
it lies in, then still in its pose.

    ~/TekkenProject/venv-import/bin/python3 tools/ps2/ttt_body_actor.py \\
        PILE.json INDEX GUEST MAIN_RETARGET.json CAPTURE.jsonl OUT.json [--from S:F] [--yaw DEG] [--mirror]
        # e.g. bruce-pile.json 5 kazuya bruce-ttt1.json theater/bruce.jsonl kazuya-body.json --from 0:841 --yaw 180 --mirror

The body's pose is the TTT1 skeleton's (57 channels, its whole orientation
in the hips); the PS2 shows it, hips at the record's matrix, as
hips + 1.2 * Ry(yaw) * diag(-1 if --mirror else 1, -1, 1) * (skeleton - hips)
(Bruce's pile: --yaw 180 --mirror, checked by Omar in the game on
2026-10-03; yaw 0 showed Kazuya's back first instead of his head). Its segment directions go through the main
actor's calibration (C) into the cutscene's frame: G = C W is a plain
rotation, applied to the hips' rotation alone (bone 0, whose world rotation
is diag(1, -1, -1) times its local one), the other channels kept as the PS2
has them (twists included; a solve on the segment directions lost them).
The hips' position goes through the same C, scale and origin. Until --from (sequence:frame of the capture, the cut
the bodies appear at) the body stands 20000 units away.
"""
import json, math, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt_retarget as R

AWAY = 20000


def main():
    a = sys.argv
    pile, index, guest, main_path, capture, out = Path(a[1]), int(a[2]), a[3], Path(a[4]), Path(a[5]), Path(a[6])
    opt = lambda k, d=None: a[a.index(k) + 1] if k in a else d
    yaw = math.radians(float(opt('--yaw', 0))); sx = -1.0 if '--mirror' in a else 1.0
    s0, f0 = map(int, opt('--from', '0:0').split(':'))
    body = next(b for b in json.loads(pile.read_text())['bodies'] if b['index'] == index)
    main = json.loads(main_path.read_text()); cal = main['calibration']
    C, scale, origin = np.array(cal['C']), cal['scale'], np.array(cal['origin'])
    frames = [json.loads(l) for l in capture.read_text().splitlines()[1:]]
    name = guest.capitalize()
    sk = R.Skeleton(R.WORK / guest / 'guest' / f'{name}-TTT1-arcade-P1.3dm')
    idle = [R.s16(v) for v in np.frombuffer((R.WORK / guest / 'guest' / f'{name}-TTT1-idle.poses').read_bytes()[:114], '<u2')]
    prior = np.array(idle[3:], dtype=float)

    # The body as the PS2 shows it, then in the cutscene's frame.
    P = sk.points(np.array(body['pose'][3:], dtype=float))
    Ry = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]])
    W = Ry @ np.diag([sx, -1.0, 1.0])
    G = C @ W
    U, _, Vt = np.linalg.svd(G); G = U @ Vt                          # the nearest rotation
    N = np.diag([1.0, -1.0, -1.0])
    joints = np.array(body['pose'][3:], dtype=float)
    joints[0:3] = R.euler(N @ G @ N @ sk.rotation(joints[0:3]))
    target = [C @ R.unit(W @ (P[b] - P[a_])) for a_, b in R.SEGMENTS]
    err = max(np.degrees(np.arccos(np.clip(np.dot(m, t_), -1, 1))) for m, t_ in zip(sk.directions(joints), target))
    print(f'hips turned by G (det {np.linalg.det(G):+.2f}); worst segment off its target by {err:.1f} degrees')
    hips = scale * (C @ (np.array(body['position']) - origin))
    heading = math.atan2(hips[0], hips[2]) / R.K
    lying = [int(round(v)) & 0xffff for v in (heading, -hips[1], math.hypot(hips[0], hips[2]), *joints)]
    away = list(lying); away[2] = AWAY                               # same pose, far out of sight

    seen, poses = False, []
    for d in frames:
        seen = seen or (d.get('s', 0), d['f']) >= (s0, f0)
        poses.append(lying if seen else away)
    out.write_text(json.dumps(dict(guest=guest, actor=-1, calibration=cal, sequences=main['sequences'],
                                   poses=poses, camera=main['camera'],
                                   body=dict(index=index, type=body['type'], yaw=math.degrees(yaw), mirror=sx < 0, start=[s0, f0]))))
    print(out, len(poses), 'frames;', sum(p is lying for p in poses), 'lying')


if __name__ == '__main__':
    main()
