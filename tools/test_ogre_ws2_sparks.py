#!/usr/bin/env python3
"""Ogre's and True Ogre's moves that hit with a limb of their own on their TTT1 moves: where the hit lands
(B106, GH#152), without a player.

    python tools/test_ogre_ws2_sparks.py [--build build-rel-lite] [--fighters ogre,trueogre] [--moves ws2,wsf2,horn] [--reps 6]

Build: PSX_DEBUG_SERVER_LITE=ON is enough, its mods/ttt1 at import version 11
(the natives' own limbs, tools/ttt1_retrofit_native_limbs.py). First the
packs: the six left-arm records of TTT1 limb 19 (ws2 and WS f+2 among them)
must hit with Ogre's left hand 6 / True Ogre's arm tip 19, never the empty
slot 20 (Ogre) or the tail (True Ogre); True Ogre's two records of TTT1 limb
23 (Buffalo Horn, the end of Demon's Feast) with his horn tip 23, not his
hips 0. Then in the game: cold start, Practice, the native with its MOVESET
card on TTT1 moves, Jin as the dummy in GUARD ALL, placed face to face once
(savestate). Each replay plays the move: ws2 (d held, then n + 2), WS f+2 (d
held, then f + 2), Buffalo Horn (f held, then d/f + 1 + 2, True Ogre). The
headless game runs unthrottled: each sample reads both actors at once
(record, frame, joints and the dummy's hit records of the same image), the
replays merged. Checks: the move is guarded, and the guard's contact point
(ActorHit +0x00, the spark's place: hit_received_fx -> hit_spark_spawn_rec)
lies within 300 of the hit's point in the move's active frames: the left
hand / the arm tip, and for the horn joint 2 moved by (800, 0, 600), the
point TTT1 computes (MAME: fighter + 0xA8C + 23 * 0x50, 1 000 from joint 2
on every frame) - worked out here from joint 2, not read from joint 23.
Before the fix: (0, 0, 0), the arena's centre, for Ogre's arm; True Ogre's
tail, about 2 000 from his arm tip; his hips for the horn. Exit status 1
when a check fails.
"""
import argparse, json, math, struct, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt1')]
import test_b67_machine_gun_cannon as B
from pack_edit import Pack
from ttt1_retrofit_native_limbs import NATIVE

FIGHTERS = dict(ogre=(14, 'Ogre', 6), trueogre=(20, 'Trueogre', 19))   # T3 ID, pack, bone of the arm's hit
HORN, HORN_JOINT, HORN_OFFSET = 23, 2, (800, 0, 600)                    # True Ogre's horn tip (T3 0x8001DC40)
# Move -> (TTT1 records, pad route, fighters): the ws2 (Heavy Body Blow), Ogre plays the first
# record, True Ogre the second; WS f+2 (0x80066E20, both); Buffalo Horn (True Ogre).
MOVES = dict(ws2=((0x800489ac, 0x800489e0), [(14, B.pad(B.B_D)), (4, B.pad(B.B_TR)), (90, 0xffff)], ('ogre', 'trueogre')),
             wsf2=((0x80066e20,), [(14, B.pad(B.B_D)), (4, B.pad(B.B_R, B.B_TR)), (90, 0xffff)], ('ogre', 'trueogre')),
             horn=((0x80047388,), [(30, B.pad(B.B_R)), (4, B.pad(B.B_D, B.B_R, B.B_SQ, B.B_TR)), (110, 0xffff)], ('trueogre',)))
GUARD_ALL = 4


def s32(b, o): return struct.unpack_from('<i', b, o)[0]


def check_pack(build, name, check):
    """Every record the update step rewrites carries its new limbs; returns the pack."""
    pack = Pack((build / f'mods/ttt1/{name}-TTT1-combat.jmv').read_bytes())
    want = NATIVE[f'{name}-TTT1-combat.jmv']
    rows = {m[1]: list(pack.records[i][40:44]) for i, m in enumerate(pack.meta) if m[1] in want}
    bad = {f'{a:08x}': r for a, r in rows.items() if r != list(want[a][1])}
    check(len(rows) == len(want) and not bad, f'{name}: the {len(want)} records hit with their own limbs ({bad or "all"})')
    return pack


def point(b, bone):
    """The hit's point of `bone` in an actor's bytes: its joint, or for the
    horn joint 2's matrix (3 x 3 in 4096ths, +0x8F4 + 68 * joint) applied to
    the horn's offset, plus its translation (+0x14)."""
    if bone != HORN: return [s32(b, 0x908 + 68 * bone + 4 * i) for i in range(3)]
    m = 0x8f4 + 68 * HORN_JOINT
    return [s32(b, m + 0x14 + 4 * i) + sum(struct.unpack_from('<h', b, m + (3 * i + j) * 2)[0] * HORN_OFFSET[j]
                                           for j in range(3)) // 4096 for i in range(3)]


def guard_contacts(g, moves, window, route, bone, reps):
    """The guard's contact points of the move, each with its distance to the
    hit's point in the active window: the closest position sampled there,
    all replays together (they are the same; the hit record stays while the
    limb goes on)."""
    points, contacts = [], []
    for _ in range(reps):
        g.q(cmd='savestate', op='load', slot=1); time.sleep(1.0)
        f0 = g.frame(); B.route(g, route)
        while g.frame() < f0 + sum(n for n, _ in route) + 10:
            b = g.read(B.ACTOR, 2 * B.STRIDE)
            if struct.unpack_from('<H', b, 0xa0)[0] not in moves: continue
            if window[0] <= struct.unpack_from('<h', b, 0x58)[0] <= window[1]:
                points.append(point(b, bone))
            for h in range(2):
                o = B.STRIDE + 0x13c + 0x2c * h
                if b[o + 0x21] and b[o + 0x22] and b[o + 0x20] == 0:
                    contacts.append([s32(b, o + 4 * i) for i in range(3)])
    return [dict(contact=c, near=min((math.dist(c, v) for v in points), default=math.inf)) for c in contacts]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--fighters', default='ogre,trueogre')
    ap.add_argument('--moves', default=','.join(MOVES))
    ap.add_argument('--reps', type=int, default=6)
    ap.add_argument('--visible', action='store_true')
    a = ap.parse_args()
    build = (ROOT / a.build).resolve()
    catalogue = [l.split()[0] for l in (build / 'mods/ttt1/guests.txt').read_text().splitlines() if l.split()]
    B.WORK = ROOT / 'out/b106'
    B.WORK.mkdir(parents=True, exist_ok=True)
    failures = []
    def check(ok, what):
        print(('ok   ' if ok else 'FAIL ') + what, flush=True)
        if not ok: failures.append(what)
    for fighter in a.fighters.split(','):
        native, name, arm = FIGHTERS[fighter]
        pack = check_pack(build, name, check)
        g = B.Game(build, f'limbs-{fighter}', a.visible)
        try:
            julia = B.JULIA
            B.JULIA = native
            try: B.to_practice(g, 'julia-ttt', catalogue)
            finally: B.JULIA = julia
            g.write(B.DUMMY, bytes([0]))
            B.place(g)
            g.write(B.DUMMY, bytes([GUARD_ALL])); g.frames(20)
            g.q(cmd='savestate', op='save', slot=1); time.sleep(1.5)
            for move in a.moves.split(','):
                records, route, who = MOVES[move]
                if fighter not in who: continue
                bone = HORN if move == 'horn' else arm
                index = [pack.index(r) for r in records]
                window = (min(pack.records[i][45] for i in index), max(pack.records[i][46] for i in index))
                found = guard_contacts(g, {8192 + i for i in index}, window, route, bone, a.reps)
                (B.WORK / f'{move}-{fighter}.json').write_text(json.dumps(found))
                check(bool(found), f'{fighter} {move}: guarded, {len(found)} samples of the guard')
                if found:
                    far = max(s['near'] for s in found)
                    check(far <= 300, f'{fighter} {move}: guard contact within {far:.0f} of the hit point '
                                      f'(bone {bone}) in frames {window[0]}..{window[1]} (first {found[0]["contact"]})')
        finally:
            g.stop()
    print('FAILED: ' + '; '.join(failures) if failures else 'all checks passed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
