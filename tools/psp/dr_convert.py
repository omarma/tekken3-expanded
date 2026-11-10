#!/usr/bin/env python3
"""Dark Resurrection (PSP) animations converted to TTT1 clips for the Tekken 3 runtime.

    python tools/psp/dr_convert.py fetch-b1 [rev]          the pose code of session B1, pinned
    python tools/psp/dr_convert.py calibrate [--char Paul]  bone offsets from the identical moves
    python tools/psp/dr_convert.py check <command> [...]    a converted identical move against TTT1

A DR fighter on its DR moveset plays packs in the TTT1 format (motion mode 4,
src/tekken3_native_moves.c; PSP-DR.md "A3 : conception"): a clip is 57
channels a frame, the polar root (heading, height, distance) then 18 local
rotations for the TTT1 skeleton, which the runtime turns onto the native's own.

DR side: the animation's quaternions and the game's own pass to local bone
matrices (0x089AE50C, spine rebuilt from its fixed points), transcribed to
the bit by session B1 (tools/psp/dr_pose.py of wip/dr/b1-model, read from
workspace/dr-a3/b1, fetch-b1), then world frames through the skeleton
(sub-file 12 of the model). The knees the animation drives are joints 29 and
30; their twins 16 and 19, which carry the shins in the file's hierarchy,
take the same local.

TTT1 side: each of the 18 rows takes the world frame of a DR joint, times a
constant rotation per row (the two skeletons' rest frames differ), in TTT1's
world (a constant basis C); its local rotation is then its parent's frame
inverted times its own, written as the runtime reads it (Rz(z) Ry(-y) Rx(-x),
16-bit angles). calibrate fits C and the per-row offsets on the moves the
balance sheet calls identical (same frames in DR and TTT1): Paul's DR and
TTT1 clips of those moves are the same motion, re-encoded. TTT1's pose k is
DR's frame k (frame 0: the animation's base pose), measured: one frame either
way fits 2 to 3 degrees worse.

Run with a Python that has numpy (C:\\TekkenProject\\venv-import).
"""
import argparse, copy, itertools, json, math, struct, subprocess, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = ROOT / 'workspace/dr-a3'
B1 = WORK / 'b1'
B1_REV = 'cc442059'                    # wip/dr/b1-model, 2026-10-24
sys.path[:0] = [str(HERE), str(ROOT / 'tools/t5')]

K = 2 * math.pi / 65536
# TTT1 skeleton (tools/ttt1/anim_model.py, src/tekken3_ttt1_basis.h): the
# parent of each row, and the bone (3 channels) that turns it.
P2R = [0, 1, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23, 24]
PART_BONE = [0, 1, 11, 12, 13, 14, 15, 16, 17, 3, 4, 5, 6, 7, 8, 9, 10, 2, 18, 19, 20, 21]
ROW_PARENT = {1: 0, 3: 0, 5: 3, 6: 5, 7: 6, 8: 3, 9: 8, 10: 9, 11: 1, 12: 11, 13: 12, 14: 13,
              15: 1, 16: 15, 17: 16, 18: 17, 19: 1}
ROWS = [0] + list(ROW_PARENT)
ROW_BONE = {0: 0, **{r: PART_BONE[P2R.index(r)] for r in ROW_PARENT}}
# TTT1 row -> DR joint: hips (row 0 / joint 1, the lower body 3 / 4), chest
# (1 / 3, DR's two spine joints in one), head (19 / 6, neck 5 left out), the
# arms (clavicle, upper arm, forearm, hand: 11-14 and 15-18 / 7-10 and 11-14),
# the legs (thigh, shin, foot: 5-7 and 8-10 / 15-17 and 18-20). Which arm and
# leg is which: calibrate tries both.
ROW_JOINT = {0: 1, 1: 3, 19: 6, 3: 4, 11: 7, 12: 8, 13: 9, 14: 10, 15: 11, 16: 12, 17: 13, 18: 14,
             5: 15, 6: 16, 7: 17, 8: 18, 9: 19, 10: 20}
SWAP_ARMS = {11: 15, 12: 16, 13: 17, 14: 18}
SWAP_LEGS = {5: 8, 6: 9, 7: 10}
KNEES = {16: 29, 19: 30}               # joint the file hangs the shin on: joint the animation turns


def s16(v): return ((int(v) + 32768) % 65536) - 32768


def rotation(a):
    """TTT1 bone rotation from 16-bit angles, in floats (anim_model.rotation): Rz(z) Ry(-y) Rx(-x)."""
    x, y, z = -a[0] * K, -a[1] * K, a[2] * K
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    return np.array([[cy * cz, sx * sy * cz - cx * sz, sx * sz + cx * sy * cz],
                     [cy * sz, cx * cz + sx * sy * sz, cx * sy * sz - sx * cz],
                     [-sy, sx * cy, cx * cy]])


def euler(M):
    """Inverse of rotation() (16-bit units, floats)."""
    y = math.asin(max(-1.0, min(1.0, -M[2, 0])))
    return np.array([-math.atan2(M[2, 1], M[2, 2]), -y, math.atan2(M[1, 0], M[0, 0])]) / K


def nearest(e, prev):
    """The angles of rotation e written closest to prev: (x, y, z) and
    (x + 1/2, 1/2 - y, z + 1/2) turn are the same rotation."""
    options = [e, np.array([e[0] + 32768, 32768 - e[1], e[2] + 32768])]
    near = lambda o: o + 65536 * np.round((prev - o) / 65536)
    return min((near(o) for o in options), key=lambda o: np.abs(o - prev).sum())


def ttt1_world(pose):
    """World rotation of each row for a 57-channel pose (signed or unsigned)."""
    local = [rotation([s16(c) for c in pose[3 + 3 * b:6 + 3 * b]]) for b in range(18)]
    local[0] = local[0].copy(); local[0][1:, :] *= -1
    W = {0: local[0]}
    for r in ROW_PARENT:
        W[r] = W[ROW_PARENT[r]] @ local[ROW_BONE[r]]
    return W


def ttt1_joints(W, prev=None):
    """54 joint channels (floats, 16-bit units) whose world rotations are W."""
    out = np.zeros(54)
    for r in ROWS:
        L = W[0].copy() if r == 0 else W[ROW_PARENT[r]].T @ W[r]
        if r == 0: L[1:, :] *= -1
        b = ROW_BONE[r]
        e = euler(L)
        out[3 * b:3 * b + 3] = e if prev is None else nearest(e, prev[3 * b:3 * b + 3])
    return out


def so3(M):
    U, _, Vt = np.linalg.svd(M)
    return U @ np.diag([1, 1, np.sign(np.linalg.det(U @ Vt))]) @ Vt


def angle(R): return float(np.degrees(math.acos(max(-1.0, min(1.0, (np.trace(R) - 1) / 2)))))


def slerp_matrix(A, B, t):
    rel = A.T @ B
    a = math.acos(max(-1.0, min(1.0, (np.trace(rel) - 1) / 2)))
    if a < 1e-9: return A.copy()
    if a > math.pi - 1e-4:
        w, v = np.linalg.eigh((rel + rel.T) / 2); axis = v[:, np.argmax(w)]
    else:
        axis = np.array([rel[2, 1] - rel[1, 2], rel[0, 2] - rel[2, 0], rel[1, 0] - rel[0, 1]]) / (2 * math.sin(a))
    X = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return A @ (np.eye(3) + math.sin(t * a) * X + (1 - math.cos(t * a)) * X @ X)


# ---------------------------------------------------------------- DR

def b1_pose():
    # B1's pose code at B1_REV, committed as dr_pose_a3.py (the animations were fitted and validated on
    # it); fetch-b1 still copies another revision into workspace/dr-a3/b1 for comparisons.
    import dr_pose_a3
    return dr_pose_a3


def fetch_b1(rev):
    """B1's tools/psp at `rev`, into workspace/dr-a3/b1 (its worktree is in use: read the branch)."""
    names = subprocess.run(['git', 'ls-tree', '--name-only', rev, 'tools/psp/'], cwd=ROOT, check=True,
                           capture_output=True, text=True).stdout.split()
    (B1 / 'data').mkdir(parents=True, exist_ok=True)
    for n in names + subprocess.run(['git', 'ls-tree', '--name-only', rev, 'tools/psp/data/'], cwd=ROOT, check=True,
                                    capture_output=True, text=True).stdout.split():
        if not n.endswith(('.py', '.json')): continue
        blob = subprocess.run(['git', 'show', f'{rev}:{n}'], cwd=ROOT, check=True, capture_output=True).stdout
        (B1 / ('data' if '/data/' in n else '') / Path(n).name).write_bytes(blob)
    (B1 / 'REV').write_text(subprocess.run(['git', 'rev-parse', rev], cwd=ROOT, check=True, capture_output=True,
                                           text=True).stdout)
    print(f'B1 pose code of {rev} -> {B1}')


class DRChar:
    """A DR fighter read from the ISO: moveset, animations, skeleton."""
    def __init__(s, name='Paul', costume=0):
        import dr_iso as D, dr_anim as A
        s.D, s.A, s.P = D, A, b1_pose()
        disc = D.Disc(D.ISO)
        g = D.group_of(name, costume)
        s.mot = disc.lz(g + D.GROUP['moveset'])
        c = disc.raw(g + D.GROUP['anims']); o, size = struct.unpack_from('<II', c, 4)
        s.packs = (c[o:o + size], disc.raw(D.COMMON_ANIM))
        model = disc.raw(g + D.GROUP['model'])
        subs = [model[o:o + n] for o, n in (struct.unpack_from('<II', model, 4 + 8 * k)
                                            for k in range(struct.unpack_from('<I', model, 0)[0]))]
        s.skeleton = sk = subs[12]
        n = struct.unpack_from('<H', sk, 2)[0]
        s.scale = struct.unpack_from('<f', sk, 4)[0]          # Paul 1,04 (dr_pose.anim_pose, echelle)
        po = struct.unpack_from('<I', sk, 8)[0]
        s.parent = [struct.unpack_from('<i', sk, po + 4 * i)[0] for i in range(n)]
        s.rest_os, s.rest_eu = s.P.os_repos(sk)
        T, E = s.P.squelette(sk)
        s.rest = [np.array(s.P.euler_matrix(E[j], [None, None, None, T[j] + [1.0]])).T for j in range(n)]

    def move(s, i):
        """(animation bytes, root yaw flag) of move i (dr_iso cmd_anim, dr_pose fichiers_iso)."""
        D = s.D
        mv = D.HDR + D.u32(s.mot, 0x1E0) + 76 * i
        v = D.u32(s.mot, mv + 8)
        pack = s.packs[1] if v & 0x8000 else s.packs[0]
        return pack[s.A.pack_offsets(pack)[v & 0x3FFF]:], not D.u32(s.mot, mv + 0x3C) >> 31

    def frames(s, anim):
        return struct.unpack_from('<H', anim, 0)[0]

    def world(s, anim, frame, lacet=True):
        """World matrices (4 x 4) of joints 0..22 at an animation frame, and the root position."""
        P = s.P
        q = P.anim_pose(anim, frame, lacet, (s.scale, s.scale, 0.0))
        os_ = P.pose_locales([list(x) for x in q], copy.deepcopy(s.rest_os), s.rest_eu)
        loc = list(s.rest)
        for k, j in enumerate(P.OS_JOINT[:23]):
            if j is not None: loc[j] = np.array(os_[k], dtype=float).T
        for twin, knee in KNEES.items(): loc[twin] = loc[knee]
        W = {}
        def get(j):
            if j not in W: W[j] = loc[j] if s.parent[j] < 0 else get(s.parent[j]) @ loc[j]
            return W[j]
        for j in range(23): get(j)
        return W, np.array(q[0][:3]), np.array(q[1][:3])


# ---------------------------------------------------------------- calibration

def fighter(name):
    """(DR name, Tekken 3 key, pack radical) of a moveset key (move_sheet.FIGHTERS): paul is Paul / paul /
    Paul; deviljin, a DR character with no native, Devil Jin / jin / DevilJin."""
    import move_sheet as MS
    return MS.FIGHTERS[name]


def identical_pairs(name='paul', pack_dir=None):
    """(command, DR move, TTT1 record) for the moves the balance sheet calls identical."""
    import csv, move_sheet as MS
    rows = list(csv.DictReader(open(ROOT / f'fiches/dr-{name}.tsv', encoding='utf-8'), delimiter='\t'))
    dr_name, key, radical = fighter(name)
    dr = MS.DR(dr_name); ttt1 = MS.TTT1(key, Path(pack_dir) if pack_dir else MS.main_pack_dir(), radical)
    by_name = {m['name']: m['index'] for m in dr.m.moves}
    by_addr = {f'{ttt1.meta(i)[1]:08x}': i for i in range(ttt1.count)}
    return [(r['commande'], by_name[r['DR coup']], by_addr[r['TTT1 coup']]) for r in rows
            if r['statut'] == 'identique' and r['DR coup'] in by_name and r['TTT1 coup'] in by_addr], dr, ttt1


def ttt1_clip(ttt1, rec):
    """Poses (57 channels) of a TTT1 pack record."""
    clip = ttt1.rec(rec)[0]
    head, ch = struct.unpack_from('<II', ttt1.pack, clip)
    n = head & 0xff
    return [struct.unpack_from('<57H', ttt1.pack, clip + 8 + 114 * k) for k in range(n)]


def samples(name='paul', limit=None, pack_dir=None):
    """Frames of the identical moves, DR world frames beside TTT1's; kept in workspace/dr-a3
    (computing DR's pose to the bit takes minutes)."""
    import pickle
    rev = B1_REV
    cache = WORK / f'samples-{name}-{limit or "all"}.pkl'
    if cache.is_file():
        saved = pickle.loads(cache.read_bytes())
        if saved['b1'] == rev: return saved['samples']
    pairs, dr, ttt1 = identical_pairs(name, pack_dir)
    ch = DRChar(fighter(name)[0])
    out = []
    for cmd, mi, ri in pairs[:limit]:
        anim, lacet = ch.move(mi)
        n, poses = ch.frames(anim), ttt1_clip(ttt1, ri)
        if abs(n - len(poses)) > 1:
            print(f'  {cmd}: DR {n} frames, TTT1 {len(poses)}: left out'); continue
        for k in range(min(n, len(poses))):
            Wd, r0, r1 = ch.world(anim, k, lacet)
            out.append(dict(cmd=cmd, k=k, Wd={j: M[:3, :3] for j, M in Wd.items()}, root=(r0, r1),
                            Wt=ttt1_world(poses[k]), pose=poses[k]))
        print(f'  {cmd}: {n} frames')
    WORK.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(pickle.dumps(dict(b1=rev, samples=out)))
    return out


def floor(r0, r1):
    """The hips' place on the floor, (x, z): bone 0 plus bone 1's own offset. TTT1's root is the
    hips (the identical moves: 1, 2, 3, 2 frame 0 is 92 degrees / 158 in TTT1 and bone 0 + 1, 180 /
    6 by bone 0 alone); Tetsuzan's hips lead bone 0 by 145 at its hit, the shoulder fell short."""
    return r0[0] + r1[0], r0[2] + r1[2]


def root_fit(S):
    """TTT1's polar root from DR's: the animation's position channels (dr_pose.anim_pose:
    bone 0 = the floor offset x, z; bone 1 = the hips, offset x, z and height). Heading =
    atan2(x, z) of the hips over the floor (bone 0 + bone 1), distance and height linear in DR's
    (fitted)."""
    d = np.array([math.hypot(*floor(x['root'][0], x['root'][1])) for x in S])
    h = np.array([x['root'][1][1] for x in S])
    td = np.array([x['pose'][2] for x in S], dtype=float)
    th = np.array([s16(x['pose'][1]) for x in S], dtype=float)
    kd, cd = np.polyfit(d, td, 1); kh, ch = np.polyfit(h, th, 1)
    moving = d > 50
    head = np.degrees(np.arctan2(*np.array([floor(x['root'][0], x['root'][1]) for x in S]).T)) * 65536 / 360
    herr = np.abs((head - np.array([s16(x['pose'][0]) for x in S]) + 32768) % 65536 - 32768)[moving]
    return dict(distance=[kd, cd], height=[kh, ch],
                distance_error=float(np.median(np.abs(kd * d + cd - td))), height_error=float(np.median(np.abs(kh * h + ch - th))),
                heading_error=float(np.median(herr)) if len(herr) else None)


def fit(S, rj, iters=40):
    """C (DR world -> TTT1 world) and Q[row] with Wt = C Wd Q, alternating, from the 24
    axis-aligned starts; the best."""
    D = {r: np.stack([x['Wd'][rj[r]] for x in S]) for r in ROWS}          # frames x 3 x 3
    T = {r: np.stack([x['Wt'][r] for x in S]) for r in ROWS}
    def angles(M):
        tr = np.clip((np.trace(M, axis1=1, axis2=2) - 1) / 2, -1, 1)
        return np.degrees(np.arccos(tr))
    best = None
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            C = np.zeros((3, 3))
            for i, p in enumerate(perm): C[i, p] = signs[i]
            if np.linalg.det(C) < 0: continue
            for _ in range(iters):
                # Q = argmax sum tr(Q^T (C D)^T T); C = argmax sum tr(C^T T Q^T D^T)
                Q = {r: so3(np.einsum('kji,kjl->il', C @ D[r], T[r])) for r in ROWS}
                C = so3(sum(np.einsum('kij,kjl->il', T[r] @ Q[r].T, np.transpose(D[r], (0, 2, 1))) for r in ROWS))
            err = {r: float(np.median(angles(np.transpose(C @ D[r] @ Q[r], (0, 2, 1)) @ T[r]))) for r in ROWS}
            total = float(np.median(list(err.values())))
            if best is None or total < best[0]: best = (total, C, Q, err)
    return best


def calibrate(name='paul', limit=None, pack_dir=None):
    S = samples(name, limit, pack_dir)
    print(f'{len(S)} frames')
    results = []
    for arms, legs in itertools.product((False, True), repeat=2):
        rj = dict(ROW_JOINT)
        if arms:
            for a, b in SWAP_ARMS.items(): rj[a], rj[b] = ROW_JOINT[b], ROW_JOINT[a]
        if legs:
            for a, b in SWAP_LEGS.items(): rj[a], rj[b] = ROW_JOINT[b], ROW_JOINT[a]
        total, C, Q, err = fit(S, rj)
        print(f'arms {"swapped" if arms else "as is"}, legs {"swapped" if legs else "as is"}: median {total:.1f}°')
        results.append((total, rj, C, Q, err))
    total, rj, C, Q, err = min(results, key=lambda r: r[0])
    for r in ROWS: print(f'  row {r:2d} <- joint {rj[r]:2d}: median {err[r]:5.1f}°')
    root = root_fit(S)
    print(f'root: distance x{root["distance"][0]:.3f} {root["distance"][1]:+.0f} (median error {root["distance_error"]:.0f}), '
          f'height x{root["height"][0]:.3f} {root["height"][1]:+.0f} (median error {root["height_error"]:.0f}), '
          f'heading median error {root["heading_error"]:.0f} units')
    cal = dict(char=name, b1=B1_REV,
               row_joint={str(r): j for r, j in rj.items()}, C=C.tolist(), Q={str(r): Q[r].tolist() for r in ROWS},
               error_deg={str(r): err[r] for r in ROWS}, frames=len(S), root=root)
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / f'calibration-{name}.json').write_text(json.dumps(cal, indent=1))
    print(f'-> {WORK / f"calibration-{name}.json"}')


# ---------------------------------------------------------------- conversion

def retime(src, dst):
    """DR time of each target frame: piecewise linear through the bounds (frame 0, first
    active, last active, free frame, last frame) of the source and the target (PSP-DR.md
    A2 rule 16): the impact lands on the target's first active frame."""
    knots = []
    for a, b in zip(src, dst):
        if knots and b <= knots[-1][1]: continue
        knots.append((float(a), float(b)))
    xs, ys = [k[1] for k in knots], [k[0] for k in knots]
    stretch = [(ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]) for i in range(len(xs) - 1) if xs[i + 1] > xs[i]]
    return [float(np.interp(t, xs, ys)) for t in range(int(dst[-1]) + 1)], stretch


class Converter:
    def __init__(s, name='paul', ch=None):
        cal = json.loads((WORK / f'calibration-{name}.json').read_text())
        s.cal, s.C = cal, np.array(cal['C'])
        s.rj = {int(r): j for r, j in cal['row_joint'].items()}
        s.Q = {int(r): np.array(q) for r, q in cal['Q'].items()}
        s.ch = ch or DRChar(fighter(name)[0])
        s.cache = {}

    def frame(s, anim, f, lacet):
        """TTT1 world rotations of the rows and DR's root (floor offset, hips height) at DR frame f."""
        # Keyed by the animation's bytes, not id(anim): the slices die and their ids come back for
        # other animations, which then played a move's frames (roots at 0, moves missing).
        # (the slice runs to the end of its pack: its length and header, base pose included, tell it).
        key = (len(anim), bytes(anim[:0xB2]), f, lacet)
        if key not in s.cache:
            Wd, r0, r1 = s.ch.world(anim, f, lacet)
            s.cache[key] = ({r: s.C @ Wd[s.rj[r]][:3, :3] @ s.Q[r] for r in ROWS}, r0, r1)
        return s.cache[key]

    def poses(s, anim, lacet, times):
        """57-channel poses at (fractional) DR frames: rows slerped between the two frames
        around, the root interpolated, angles written continuously from one pose to the next."""
        n = s.ch.frames(anim)
        root = s.cal['root']
        out, prev, heading = [], None, 0.0
        for t in times:
            t = min(max(t, 0.0), n - 1.0)
            f0 = int(math.floor(t)); f1 = min(f0 + 1, n - 1); u = t - f0
            A, a0, a1 = s.frame(anim, f0, lacet)
            B, b0, b1 = s.frame(anim, f1, lacet)
            W = {r: slerp_matrix(A[r], B[r], u) if u > 1e-9 else A[r] for r in ROWS}
            r0 = a0 * (1 - u) + b0 * u; r1 = a1 * (1 - u) + b1 * u
            x, z = floor(r0, r1)
            d = math.hypot(x, z)
            if d > 1e-3: heading = math.degrees(math.atan2(x, z)) * 65536 / 360
            joints = ttt1_joints(W, prev)
            prev = joints
            dist = max(0.0, root['distance'][0] * d + root['distance'][1])
            height = root['height'][0] * r1[1] + root['height'][1]
            out.append([int(round(v)) & 0xffff for v in (heading, height, dist, *joints)])
        return out


def check(name, commands):
    """Identical moves converted and compared with TTT1's clip, row by row (degrees)."""
    pairs, dr, ttt1 = identical_pairs(name)
    cv = Converter(name)
    for cmd, mi, ri in pairs:
        if commands and cmd not in commands: continue
        anim, lacet = cv.ch.move(mi)
        ref = ttt1_clip(ttt1, ri)
        mine = cv.poses(anim, lacet, list(range(len(ref))))
        err = {r: [] for r in ROWS}
        for p, q in zip(mine, ref):
            A, B = ttt1_world(p), ttt1_world(q)
            for r in ROWS: err[r].append(angle(A[r].T @ B[r]))
        rootd = [abs(p[2] - q[2]) for p, q in zip(mine, ref)]
        worst = sorted(ROWS, key=lambda r: -np.median(err[r]))[:4]
        print(f'{cmd:>12}: rows median {np.median([np.median(v) for v in err.values()]):5.1f}°, worst '
              + ', '.join(f'{r} {np.median(err[r]):.0f}°' for r in worst) + f'; distance median error {np.median(rootd):.0f}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='action', required=True)
    f = sub.add_parser('fetch-b1'); f.add_argument('rev', nargs='?', default=B1_REV)
    c = sub.add_parser('calibrate'); c.add_argument('--char', default='paul'); c.add_argument('--limit', type=int)
    k = sub.add_parser('check'); k.add_argument('commands', nargs='*'); k.add_argument('--char', default='paul')
    a = ap.parse_args()
    if a.action == 'fetch-b1': fetch_b1(a.rev)
    elif a.action == 'calibrate': calibrate(a.char, a.limit)
    elif a.action == 'check': check(a.char, a.commands)


if __name__ == '__main__':
    main()
