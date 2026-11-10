#!/usr/bin/env python3
"""B139 (GH#66): Gun Jack's Piston Gun Assault (b+2, TTT1 moves) and its strong-hit effect.

    python ressources/slot.py --kind game --who b139 --prio 2 -- \\
        python tools/test_b139_piston_gun_spark.py [--build build-dbg] [--data <install>/mods]
            [--hitspark on|off] [--ps2 on|off] [--full auto|on|off] [--moves b2,12] [--frames OUT]

Build: PSX_DEBUG_TOOLS=ON (the frame history: set_snapshot / read_frame_ram). --data: the mods folder of an
install (its TTT1 catalogue with Gun Jack's TTT1 moves, read in place; tools/test_b131_embu_ps2_sparks.py view_of).

Practice, player 1 Gun Jack on its TTT1 moves (MOVESET card), Jin the STAND dummy, face to face (savestate 1).
Each move from the save state; every frame for 110 frames the history keeps the three hit sprites (0x800A3408,
64 bytes each: life +2, base x +0x14, palette row +0x22), player 1's move number (+0xA0) and the dummy's two
contact rows (+0x13C, +0x168: the struck zone at +24, its percentage at 0x8001DEEC). Printed: the moves played,
the damage dealt (Practice's TOTAL DMG, 0x800B8B94) and the zones, then each sprite spawn (frame, slot, kind,
life reached). Player 1's strong-hit effect is the sprite at base 368, palette row 503.

TTT1 (MAME, tools/ttt1_piston_gun_probe.lua, the same move landing: hit_impact 0x801208C8 with power 27, then
hit_fx_spawn 0x80120420 nine more times from the move's timed properties) takes its hit sprites from a ring of
three (hit_fx_next); the third spark after the hit lands on the strong-hit effect's slot and ends it after 6 of
its 30 images. Tekken 3 has the same ring (0x8007641C) and the import keeps the properties: the same cut, unless
TTT Hitspark is on (src/tekken3_ttt1_combat.c, __wrap_func_80076884): then the sparks take the other slots and
the effect plays all its images. --full on|off sets TEKKEN3_FULL_STRONG_HITS, which overrides the feature.

Exit 1 when b+2 did not play 184-185-186 of the pack or did not land, or when player 1's strong-hit effect of b+2
did not end where expected: at its last image with TTT Hitspark on (or --full on), cut before it with TTT
Hitspark off (or --full off).
"""
import argparse, os, shutil, struct, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/arcade_stages'), str(ROOT / 'psxrecomp/tools')]
import test_b67_machine_gun_cannon as B
import test_hit_effect_64 as H
from test_b131_embu_ps2_sparks import DATA, view_of

GUNJACK = 16
FX_SPRITES, FX_SPRITE = 0x800a3408, 64
P1, P2 = B.ACTOR, B.ACTOR + B.STRIDE
MOVE, CONTACTS, ZONES = 0xa0, 0x13c, 0x8001deec
STRONG_BASE, STRONG_ROW = 368, 503
PIECES = [8192 + 184, 8192 + 185, 8192 + 186]
N = 0xffff
# Player 1 faces right: back is left.
MOVES = {'b2': ('Piston Gun Assault (b+2)', [(2, B.pad(B.B_L)), (3, B.pad(B.B_L, B.B_TR)), (120, N)]),
         '12': ('1+2', [(3, B.pad(B.B_SQ, B.B_TR)), (120, N)])}
WATCH = 110


def history(g, f, addr, n):
    try: return bytes.fromhex(g.q(cmd='read_frame_ram', frame=f, addr=f'{addr:08x}', len=n)['hex'])
    except Exception: return None


def kind(base, row):
    if base == STRONG_BASE and row == STRONG_ROW: return 'P1 strong-hit effect'
    if base == 496 and row == STRONG_ROW: return 'P2 strong-hit effect'
    return f'spark (base {base}, row {row})'


def play(g, steps):
    """From savestate 1: the move; per frame the sprites, player 1's move, the contacts; and the damage."""
    g.q(cmd='savestate', op='load', slot=1); time.sleep(1.0)
    for slot, addr in enumerate((FX_SPRITES, FX_SPRITES + 2 * FX_SPRITE, P1 + 0x80, P2 + CONTACTS)):
        g.q(cmd='set_snapshot', slot=slot, addr=f'{addr:08x}')
    g.frames(2)
    total0 = g.value(B.TOTAL_DMG, 2)
    f0 = g.frame(); B.route(g, steps)
    while g.frame() < f0 + WATCH: time.sleep(.01)
    rows = []
    for f in range(f0, f0 + WATCH):
        a, b, m, c = (history(g, f, x, n) for x, n in ((FX_SPRITES, 128), (FX_SPRITES + 128, 64), (P1 + MOVE, 2),
                                                       (P2 + CONTACTS, 88)))
        if a is None or b is None or m is None or c is None: continue
        sprites = [struct.unpack_from('<hhh', a + b, i * FX_SPRITE) + struct.unpack_from('<H', a + b, i * FX_SPRITE + 0x14)
                   + struct.unpack_from('<H', a + b, i * FX_SPRITE + 0x22) for i in range(3)]
        zones = [struct.unpack_from('<H', c, 0x2c * h + 24)[0] for h in range(2) if any(c[0x2c * h:0x2c * h + 24])]
        rows.append((f - f0, sprites, struct.unpack('<H', m)[0], zones))
    after = g.value(B.TOTAL_DMG, 2)
    return rows, after - total0 if after > total0 else after     # TOTAL DMG starts again with a new combo


def report(name, rows, damage):
    moves = []
    for _, _, m, _ in rows:
        if not moves or moves[-1] != m: moves.append(m)
    zones = sorted({z for *_, zs in rows for z in zs if z < 14})
    print(f'{name}: moves {[m - 8192 if m >= 8192 else hex(m) for m in moves]}, damage {damage:g}, '
          f'zones {zones} ({", ".join(str(B_zone_pct.get(z, "?")) + " %" for z in zones)})')
    spawns, prev = [], [(0, 0, 0, 0, 0)] * 3
    for f, sprites, _, _ in rows:
        for i, s in enumerate(sprites):
            tick, life, life_max, base, row = s
            if life > 0 and (prev[i][1] <= 0 or life < prev[i][1] or (base, row) != (prev[i][3], prev[i][4])):
                spawns.append(dict(frame=f, slot=i, kind=kind(base, row), life_max=life_max, last=life, end=f))
            elif life > 0 and spawns:
                for sp in reversed(spawns):
                    if sp['slot'] == i: sp['last'], sp['end'] = life, f; break
            prev[i] = s
    for sp in spawns:
        print(f'  frame {sp["frame"]:3d} slot {sp["slot"]}: {sp["kind"]}, life 1..{sp["last"]} of {sp["life_max"]} '
              f'(alive to frame {sp["end"]})')
    return moves, spawns


B_zone_pct = {}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--build', default='build-dbg')
    ap.add_argument('--data', type=Path, default=Path(DATA))
    ap.add_argument('--hitspark', choices=('on', 'off'), default='on')
    ap.add_argument('--ps2', choices=('on', 'off'), default='off')
    ap.add_argument('--full', choices=('auto', 'on', 'off'), default='auto',
                    help='strong-hit effects played to their end (auto: while TTT Hitspark is on)')
    ap.add_argument('--moves', default='b2,12')
    ap.add_argument('--frames', type=Path, help='displayed images of b+2 (frames 14..62), in this folder')
    a = ap.parse_args()
    build, data = (ROOT / a.build).resolve(), a.data.resolve()
    catalogue = [l.split()[0] for l in (data / 'ttt1/guests.txt').read_text().splitlines() if l.split()]
    H.WORK.mkdir(parents=True, exist_ok=True)
    view = view_of(build, data, f'b139-{a.hitspark}-{a.ps2}')
    stale = view / 'mods/arcade-models'           # a feature branch's folder left in the build, not dev's
    if stale.exists() and not (ROOT / 'mods/arcade-models').exists():
        subprocess.run(['cmd', '/c', 'rmdir', str(stale)], capture_output=True)
    env = [('TEKKEN3_PS2_EFFECTS', a.ps2), ('TEKKEN3_TTT_PS2_LASER_DIR', str(data / 'ttt-ps2-laser')),
           *([('TEKKEN3_FULL_STRONG_HITS', '1' if a.full == 'on' else '0')] if a.full != 'auto' else [])]
    full = a.full == 'on' or a.full == 'auto' and a.hitspark == 'on'
    g = H.Game(view, f'b139-{a.hitspark}-{a.ps2}', env, 'off', (), a.hitspark == 'on')
    failures = []
    try:
        julia = B.JULIA
        B.JULIA = GUNJACK
        try: B.to_practice(g, 'julia-ttt', catalogue)
        finally: B.JULIA = julia
        for z in range(14): B_zone_pct[z] = g.value(ZONES + 2 * z, 2)
        g.write(B.DUMMY, bytes([0]))                 # STAND: no guard
        B.place(g)
        g.q(cmd='savestate', op='save', slot=1); time.sleep(1.5)
        print(f'TTT Hitspark {a.hitspark}, PS2 EFFECTS {a.ps2}, effects to their end {"on" if full else "off"}')
        for key in a.moves.split(','):
            name, steps = MOVES[key]
            rows, damage = play(g, steps)
            moves, spawns = report(name, rows, damage)
            if key == 'b2':
                if not all(p in moves for p in PIECES): failures.append(f'b+2 did not play {[p - 8192 for p in PIECES]}')
                if damage <= 0: failures.append('b+2 did not land')
                strong = [sp for sp in spawns if sp['kind'] == 'P1 strong-hit effect']
                if not strong: failures.append('b+2: no strong-hit effect of player 1')
                elif (strong[0]['last'] == strong[0]['life_max']) != full:
                    failures.append(f"b+2: the strong-hit effect ended at image {strong[0]['last']} of {strong[0]['life_max']}")
        if a.frames:
            a.frames.mkdir(parents=True, exist_ok=True)
            for w0 in range(14, 62, 8):
                g.q(cmd='savestate', op='load', slot=1); time.sleep(1.0)
                f1 = g.frame(); B.route(g, MOVES['b2'][1])
                while g.frame() < f1 + w0 + 9: pass
                for k in range(w0, w0 + 8):
                    try: g.q(cmd='display_ring_get', frame=f1 + k, path=str(a.frames / f'{k:03d}.png'))
                    except RuntimeError: pass
                while g.frame() < f1 + 90: time.sleep(.01)
            print(f'images: {a.frames}')
    finally:
        g.stop()
        for p in (view / 'mods').iterdir():
            if p.is_dir(): subprocess.run(['cmd', '/c', 'rmdir', str(p)], capture_output=True)
        shutil.rmtree(view, ignore_errors=True)
    print('FAILED: ' + '; '.join(failures) if failures else 'all checks passed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
