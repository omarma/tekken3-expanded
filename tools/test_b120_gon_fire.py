#!/usr/bin/env python3
"""True Ogre's fire on Gon, T3 moves against TTT1 moves (B120, GH#170), without a player.

    python tools/test_b120_gon_fire.py [--build build-rel-lite] [--fighters trueogre-t3,trueogre-ttt]
        [--dummy gon] [--moves 12,df12,ub12,b12] [--exe <before>]

Build: PSX_DEBUG_SERVER_LITE=ON is enough. Cold start, Practice: player 1
takes True Ogre with his MOVESET card (T3 or TTT1 moves), the dummy is Gon
(or another native: --dummy jin) on CONTROLLER, idle. Both are placed face to
face once (savestate 1); each move reloads it. Every sample reads both
actors: player 1's move and frame, the dummy's move, its life (+0x3F4, high
half) and the Practice's TOTAL DMG. Prints, per move: player 1's moves
(8192 + n = a pack record), the hits (TOTAL DMG's steps), the dummy's life
lost and its reactions.

    python tools/test_b120_gon_fire.py --mode arcade|survival --p1 trueogre --cpu gon [--seconds 90]

Arcade or Survival (TEKKEN3_NATIVE_MOVES=1: every native in the fight on its
TTT1 moves, the CPU's too; Gon has none and keeps his T3 moves). Player 1
picks its fighter at the grid, the CPU's is written while the first fight
loads (0x800ADD5E; Arcade: stage 1 of the list 0x800AFB18 too). In the
fight both lives are filled again after each sample; True Ogre on player 1
plays 1+2 whenever he stands, on the CPU he plays as he likes. Prints each
hit the defender takes, with the attacker's moves just before it.
"""
import argparse, re, struct, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'tools')]
import test_b67_machine_gun_cannon as B

TRUE_OGRE, OGRE = 20, 14
DUMMIES = dict(gon=17, jin=9, paul=1)
FIGHTERS = {'trueogre-t3': (TRUE_OGRE, False), 'trueogre-ttt': (TRUE_OGRE, True),
            'ogre-t3': (OGRE, False), 'ogre-ttt': (OGRE, True)}
P = B.pad
MOVES = {'12': P(B.B_SQ, B.B_TR), 'df12': P(B.B_D, B.B_R, B.B_SQ, B.B_TR), 'ub12': P(4, B.B_L, B.B_SQ, B.B_TR),
         'b12': P(B.B_L, B.B_SQ, B.B_TR), 'db12': P(B.B_D, B.B_L, B.B_SQ, B.B_TR), 'd12': P(B.B_D, B.B_SQ, B.B_TR),
         'f12': P(B.B_R, B.B_SQ, B.B_TR), 'u12': P(4, B.B_SQ, B.B_TR), 'uf12': P(4, B.B_R, B.B_SQ, B.B_TR)}


def force(g, index):
    """Player 1 starts its pack record `index` as the runtime's own switch
    does (switch_moveset): move ID +0x1A0, record +0x54 / +0x4C / +0x1A4,
    frame +0x58 and +0x198 = 1."""
    record = int(re.findall(r'combat: installed P1 alias table.*records=([0-9A-F]+)', g.log())[-1], 16) + index * 56
    B.gated(g, [(B.ACTOR + 0x1a0, struct.pack('<H', B.PACK + index))] +
            [(B.ACTOR + o, struct.pack('<I', record)) for o in (0x54, 0x4c, 0x1a4)] +
            [(B.ACTOR + o, struct.pack('<H', 1)) for o in (0x58, 0x198)])


def try_move(g, buttons, frames=260, dump=False, start=None):
    g.q(cmd='savestate', op='load', slot=1); time.sleep(1.0)
    if start is not None: force(g, start); g.frames(2)
    rows = []
    def sample():
        a, b = g.read(B.ACTOR, 0xa2), g.read(B.ACTOR + B.STRIDE, 0x3f8)
        total = struct.unpack('<h', g.read(B.TOTAL_DMG, 2))[0]
        return dict(f=g.frame(), m1=struct.unpack_from('<H', a, 0xa0)[0], t1=struct.unpack_from('<h', a, 0x58)[0],
                    m2=struct.unpack_from('<H', b, 0xa0)[0], life=struct.unpack_from('<i', b, 0x3f4)[0] >> 16,
                    total=total)
    rows.append(sample())
    B.route(g, [(4, buttons), (frames, 0xffff)])
    end = g.frame() + frames
    seen = {}
    while g.frame() < end:
        rows.append(sample())
        m = rows[-1]['m1']
        if dump and m not in seen and m != 3: seen[m] = g.read(g.value(B.ACTOR + 0x54), 0x38)
        time.sleep(.002)
    for m, info in seen.items(): print_info(g, m, info)
    return rows


def print_info(g, m, info):
    """A move's record (MoveInfo, 0x38 bytes) and its cancel list."""
    w = struct.unpack_from('<4I', info)
    dmg, = struct.unpack_from('<h', info, 0x14)
    at = struct.unpack_from('<I', info, 0x28)[0]
    limbs = g.read(at, 4) if at >= 0x80000000 else b''
    print(f'  move {m:#x}: attrs {w[1]:#x} id {w[2]:#x} damage {dmg} ({dmg & 0x3fff}, kind {(dmg & 0xffff) >> 14}) '
          f'limbs {list(limbs)} active {info[0x2d]}..{info[0x2e]} hitstun {info[0x2c]} '
          f'reaction {struct.unpack_from("<H", info, 0x32)[0]:#x} alt {struct.unpack_from("<H", info, 0x34)[0]:#x}')
    c = w[3]
    for k in range(40):
        e = g.read(c + 12 * k, 12)
        cmd, key, cond, val, mv, kind, fmin, fmax, cnt = struct.unpack('<HBBHHBBBB', e)
        print(f'    cancel {cmd:#06x} key {key:#x} cond {cond:#x} value {val:#x} -> {mv:#x} kind {kind:#x} {fmin}..{fmax} count {cnt}')
        if cmd == 0xc000: break


class Game(B.Game):
    """B.Game with environment variables of its own (TEKKEN3_ ones included)."""
    def __init__(self, *a, env=None, **k):
        real = B.subprocess.Popen
        def popen(args, **kw):
            if 'env' in kw: kw['env'] = {**kw['env'], **(env or {})}
            return real(args, **kw)
        B.subprocess.Popen = popen
        try: super().__init__(*a, **k)
        finally: B.subprocess.Popen = real


LIST, CPU_FIGHTER, CPU_COSTUME, ARCADE, SURVIVAL = 0x800afb18, 0x800add5e, 0x800add9a, 0, 4
P2 = B.ACTOR + B.STRIDE


def cpu_fight(build, mode, p1, cpu, seconds, exe=None):
    """Player 1 against the CPU in Arcade or Survival; returns the hits."""
    g = Game(build, f'{mode}-{p1}-{cpu}', exe=exe, env={'TEKKEN3_NATIVE_MOVES': '1'})
    try:
        def menu():
            if g.value(B.STATE) == 3:
                g.write(0x80097ef0, struct.pack('<I', 0x1fffff)); g.write(0x80097f1e, b''); g.write(0x80097f26, b'')
                g.press(B.START)
            return g.value(B.STATE) == 4
        g.q(cmd='turbo', enabled=1)
        g.wait(menu, 'mode menu not reached', 240)
        g.q(cmd='turbo', enabled=0)
        time.sleep(.5)
        g.write(B.LINE, struct.pack('<I', 0)); g.press(B.CROSS)
        g.wait(lambda: g.value(B.STATE) == 9 and g.value(B.GRID) == 21, 'the Arcade grid never came', 30)
        if mode == SURVIVAL: g.write(B.MODE, struct.pack('<I', SURVIVAL))
        time.sleep(1.5)
        B.seek(g, p1, f'character {p1}')
        g.press(B.SQUARE)
        g.wait(lambda: g.value(B.STATE) in (8, 11), 'no loading screen', 30)
        if g.value(B.MODE) != mode: raise AssertionError(f'mode {g.value(B.MODE)}, not {mode}')
        if mode == ARCADE: g.write(LIST, bytes([cpu, 0]))
        g.write(CPU_FIGHTER, struct.pack('<HH', cpu, 0))
        identity = lambda p: struct.unpack('<HH', g.read(B.ACTOR + p * B.STRIDE + 0x16, 4))
        def fighting():
            if g.value(B.STATE) == 11 or g.value(B.STATE) == 8 and g.value(B.PHASE, 2) <= 3:
                g.write(CPU_FIGHTER, struct.pack('<H', cpu))
            return g.value(B.STATE) == 8 and g.value(B.PHASE, 2) == 8 and identity(1)[1] == cpu
        g.wait(fighting, f'no fight against character {cpu}', 120)
        print(f'{mode and "survival" or "arcade"} (mode {g.value(B.MODE)}): P1 key/id {identity(0)}, CPU {identity(1)}', flush=True)
        hits, history, end = [], [], time.monotonic() + seconds
        full = [struct.unpack('<H', g.read(a + 0x3f6, 2))[0] for a in (B.ACTOR, P2)]
        while time.monotonic() < end:
            if g.value(B.STATE) != 8: g.press(B.START); time.sleep(.5); continue
            a, b = g.read(B.ACTOR, 0x3f8), g.read(P2, 0x3f8)
            moves = (struct.unpack_from('<H', a, 0xa0)[0], struct.unpack_from('<H', b, 0xa0)[0])
            life = (struct.unpack_from('<H', a, 0x3f6)[0], struct.unpack_from('<H', b, 0x3f6)[0])
            history = (history + [moves])[-40:]
            for p in (0, 1):
                if full[p] and life[p] < full[p]:
                    hits.append((p, full[p] - life[p], [h[1 - p] for h in history]))
                    g.write((B.ACTOR, P2)[p] + 0x3f6, struct.pack('<H', full[p]))
            if p1 == TRUE_OGRE and moves[0] == 3: B.route(g, [(4, MOVES['12']), (20, 0xffff)])
            time.sleep(.03)
        return hits
    finally:
        g.stop()


def name(m): return f'{(m - B.PACK) % 4096}p' if m >= B.PACK else hex(m)


def summary(rows):
    def seq(k):
        out = []
        for r in rows:
            m = r[k]; m = f'{m - B.PACK}p' if m >= B.PACK else hex(m)
            if not out or out[-1] != m: out.append(m)
        return out
    hits = [b['total'] - a['total'] for a, b in zip(rows, rows[1:]) if b['total'] != a['total']]
    return dict(p1=seq('m1'), dummy=seq('m2'), hits=hits, life=rows[0]['life'] - min(r['life'] for r in rows))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--fighters', default='trueogre-t3,trueogre-ttt')
    ap.add_argument('--dummy', default='gon')
    ap.add_argument('--moves', default='12,df12,ub12,b12')
    ap.add_argument('--exe')
    ap.add_argument('--visible', action='store_true')
    ap.add_argument('--dump', action='store_true', help="print player 1's move records and cancel lists")
    ap.add_argument('--start', type=int, help="player 1's pack record to start each move from (502: rising)")
    ap.add_argument('--mode', choices=('practice', 'arcade', 'survival'), default='practice')
    ap.add_argument('--p1', default='trueogre')
    ap.add_argument('--cpu', default='gon')
    ap.add_argument('--seconds', type=int, default=90)
    a = ap.parse_args()
    build = (ROOT / a.build).resolve()
    if a.mode != 'practice':
        B.WORK = ROOT / 'out/b120'
        B.WORK.mkdir(parents=True, exist_ok=True)
        ids = dict(trueogre=TRUE_OGRE, ogre=OGRE, **DUMMIES)
        for p, damage, before in cpu_fight(build, ARCADE if a.mode == 'arcade' else SURVIVAL, ids[a.p1], ids[a.cpu], a.seconds, a.exe and Path(a.exe)):
            seq = []
            for m in before:
                if not seq or seq[-1] != name(m): seq.append(name(m))
            print(f'  P{p + 1} -{damage}: attacker {seq[-6:]}', flush=True)
        return
    catalogue = [l.split()[0] for l in (build / 'mods/ttt1/guests.txt').read_text().splitlines() if l.split()]
    B.WORK = ROOT / 'out/b120'
    B.WORK.mkdir(parents=True, exist_ok=True)
    for fighter in a.fighters.split(','):
        native, ttt = FIGHTERS[fighter]
        g = B.Game(build, fighter, a.visible, a.exe and Path(a.exe))
        julia, jin = B.JULIA, B.JIN
        B.JULIA, B.JIN = native, DUMMIES[a.dummy]
        try:
            B.to_practice(g, 'julia-ttt' if ttt else 'julia-t3', catalogue)
            B.place(g)
            g.q(cmd='savestate', op='save', slot=1); time.sleep(1.5)
            for move in a.moves.split(','):
                s = summary(try_move(g, MOVES[move], dump=a.dump, start=a.start))
                print(f'{fighter} vs {a.dummy} {move}: hits {s["hits"]} life -{s["life"]} '
                      f'p1 {s["p1"][:8]} dummy {s["dummy"][:10]}', flush=True)
        finally:
            B.JULIA, B.JIN = julia, jin
            g.stop()


if __name__ == '__main__':
    main()
