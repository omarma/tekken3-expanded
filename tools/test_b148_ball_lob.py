#!/usr/bin/env python3
"""Tekken Ball: the lob of a stopped ball no longer crashes the game (B148, GH#197).

    python tools/test_b148_ball_lob.py [--case hit lob] [--build build-rel-lite] [--memcard-dir saves]
        [--data <install>/build-release/mods] [--ps2 on|off] [--laser DIR] [--guest angel]

The player's case: the opponent's charged ball, caught with a throw (a hit
without damage while the ball has power: state 3), then hit with a move of
id 0x412: ball_move (ovl3, t3-ps1 src/ovl3_ball/800B065C.c) sets state 4, a
lob that rises to -0x1400, then falls homing on the opponent (state 2).
Before: on the first state-4 frame, after `lw v0, 0x6C(s1)` at 0x800B128C,
the dirty-RAM interpreter handed ball_move to the compiled one-word piece
func_800B1290 (EXE padding, a nop like the overlay's load-delay slot), which
fell through into the stale pieces after it: "FATAL: FAIL-FAST unknown
dispatch: addr=0x800B74B0 ra=0x800B0A08" (dirty_ram_text_flow_matches).

Cases, each from a cold start (private copy of the build, software,
headless, a copy of the memory card; tools/test_ball_backdash.py's bench),
Tekken Ball, player 1 Jin (or --guest), from the serve:
    hit  Jin's T3 move alias 614 (id 0x412) started, then the ball stopped in
         state 3 in front of him; tried at a few distances, one boot each,
         until the move meets the ball: state 4, then state 2 homing on
         player 2, and no crash.
    lob  the ball written as that hit leaves it (state 4, rising, homing on
         player 2): it must leave state 4 without a crash.
--data junctions the install's data folders (TTT1 catalogue, PS2 pack...)
into the copy's mods and removes them with `cmd /c rmdir` before the copy is
deleted; --ps2 sets TEKKEN3_PS2_EFFECTS, --laser the PS2 pack folder (it must
be of this build's LASER_VERSION, or the effects stay the arcade's).
"""
import argparse, os, shutil, struct, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_ball_backdash as bench
from test_ball_backdash import ACTOR, STRIDE, SCREEN, PHASE, LOADING_P1, Game, to_mode, pick, signed

BALL_STATE = 0x800add74                      # BallState pointer (ovl3 ball_frame)
GRAVITY, POWER = 0x800b6614, 0x800b6610      # ball_kind_gravity, ball_kind_power
ALIAS_TABLE, LOB_MOVE, LOB_ID = 0x800adc20, 614, 0x412
DISTANCES = (1050, 1100, 1000, 950, 1150, 900)
FRAMES = 400
FROM_DATA = ('ttt1', 'arcade-stages', 'ttt-stages', 'ttt-cinematics', 'ttt-music', 'ttt-ps2-music',
             'ttt-ps2-laser', 'difficulty')


def mods_view(data):
    """shutil.copytree for the bench's copy: the build's own mods copied, the
    install's data folders as junctions (no multi-GB copy)."""
    copytree = shutil.copytree

    def copy(src, dst, *k, **kw):
        if Path(src).name != 'mods': return copytree(src, dst, *k, **kw)
        Path(dst).mkdir(parents=True)
        for p in Path(src).iterdir():
            if p.name in FROM_DATA: continue
            if p.is_file(): shutil.copy2(p, Path(dst) / p.name)
            else: copytree(p, Path(dst) / p.name)
        for name in FROM_DATA:
            if (data / name).is_dir():
                subprocess.run(['cmd', '/c', 'mklink', '/J', str(Path(dst) / name), str(data / name)],
                               check=True, capture_output=True)
    return copy


def stop(g):
    """Junctions out first (never a delete through them), then the bench's stop."""
    mods = g.dir / 'run' / 'mods'
    for name in FROM_DATA:
        if os.path.isjunction(mods / name):
            subprocess.run(['cmd', '/c', 'rmdir', str(mods / name)], capture_output=True)
    left = [n for n in FROM_DATA if os.path.lexists(mods / n)]
    if left:
        print(f'  junctions left, {g.dir} kept: {left}', flush=True)
        if g.process.poll() is None: g.process.kill()
    else:
        g.stop()


def crashed(g):
    return g.process.poll() is not None or 'FATAL' in g.log()[-4000:]


def run(a, case, distance):
    """One boot. Returns (crashed, states seen as (state, homing, target is P2))."""
    env = {'TEKKEN3_NATIVE_MOVES': '0'}
    if a.ps2: env['TEKKEN3_PS2_EFFECTS'] = a.ps2
    if a.laser: env['TEKKEN3_TTT_PS2_LASER_DIR'] = str(Path(a.laser))
    g = Game(Path(a.build), Path(a.memcard_dir), env)
    seen, crash = [], False
    try:
        to_mode(g, 'ball')
        pick(g, 'ball', 'jin')
        if a.guest:
            names = [l.split()[0] for l in (Path(a.data) / 'ttt1/guests.txt').read_text().splitlines() if l.split()]
            for _ in range(30): g.write(LOADING_P1, 23 + names.index(a.guest), 2); time.sleep(.01)
        g.wait(lambda: g.value(SCREEN) == 8 and g.value(PHASE, 2) >= 6 and g.value(ACTOR + 0x54) != 0,
               'the fight never started', 90)
        ball = g.value(BALL_STATE)
        g.wait(lambda: g.value(ball, 2) == 9, 'the ball never floated at the serve', 30)
        g.q(cmd='turbo', enabled=0)
        time.sleep(1)
        me, other = ACTOR, ACTOR + STRIDE
        W = lambda addr, data: g.q(cmd='write_ram', addr=f'{addr:08x}', bytes=data.hex())
        z = signed(g.value(me + 8))
        if case == 'hit':
            record = g.value(g.value(g.value(ALIAS_TABLE) + 12) + 4 * LOB_MOVE)
            assert g.value(record + 8, 2) == LOB_ID, f'alias {LOB_MOVE} is not a {LOB_ID:#x} move'
            W(me + 0x1a0, struct.pack('<HHI', LOB_MOVE, g.value(me + 0x1a2, 2), record))
            t0 = g.frame()
            while g.value(me + 0xa0, 2) != LOB_MOVE and g.frame() < t0 + 600: pass
            assert g.value(me + 0xa0, 2) == LOB_MOVE, 'the move never started'
            # The ball stopped by the catch (state 3, no power, still): each block
            # written while the ball floats at the serve, its position and state last,
            # so the move cannot meet it half written.
            x1, x2 = signed(g.value(me)), signed(g.value(other))
            b = bytearray(g.read(ball + 0xa8, 0x26))
            struct.pack_into('<i', b, 0, 0); struct.pack_into('<h', b, 0xa, 0); b[0x24] = 0
            W(ball + 0xa8, bytes(b))
            W(ball + 0x130, struct.pack('<IIIhhhh', other, me, 0, 0, 30, 0, 0x1800))
            W(ball + 0x68, struct.pack('<11i', x1 + (distance if x2 > x1 else -distance), -0x800, z, *[0] * 8))
            W(ball, struct.pack('<h', 3))
        else:
            # As case 0x412 leaves a state-3 ball: rising, homing on player 2.
            grav = struct.unpack('<h', g.read(GRAVITY, 2))[0]
            power = struct.unpack('<h', g.read(POWER, 2))[0]
            W(ball + 0x68, struct.pack('<11i', signed(g.value(me)) + 700, -0xA00, z, 0, 0, -grav * 72, 0, 0, 0, 0, 0))
            W(ball + 0x88, struct.pack('<3i', 0, grav, 0))
            b = bytearray(g.read(ball + 0xa8, 0x26))
            struct.pack_into('<i', b, 0, power * 10); struct.pack_into('<h', b, 0xa, 1); b[0x24] = 5
            W(ball + 0xa8, bytes(b))
            W(ball + 0x130, struct.pack('<IIIhhhh', me, other, other, 20, 0, 20, 0x800))
            W(ball, struct.pack('<h', 4))
        end = g.frame() + FRAMES
        while g.frame() < end:
            if crashed(g): crash = True; break
            bb = g.read(ball, 0x138)
            row = (struct.unpack_from('<h', bb, 0)[0], struct.unpack_from('<h', bb, 0xb2)[0],
                   struct.unpack_from('<I', bb, 0x134)[0] == other)
            if not seen or seen[-1] != row: seen.append(row)
    except (ConnectionError, OSError):
        crash = True
    finally:
        log = g.log()
        if crash and 'FATAL' in log: print('  ' + log[log.find('FATAL'):].splitlines()[0][:160], flush=True)
        for l in log.splitlines():
            if l.startswith('PS2 effects:') or l.startswith('PS2 lasers: pack'): print('  log:', l[:120], flush=True)
        stop(g)
    return crash, seen


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--case', nargs='+', default=['hit', 'lob'], choices=['hit', 'lob'])
    ap.add_argument('--build', default=str(ROOT / 'build-rel-lite'))
    ap.add_argument('--memcard-dir', default=str(ROOT / 'saves'))
    ap.add_argument('--data', help="the install's mods folder (TTT1 catalogue, PS2 pack...), junctioned in")
    ap.add_argument('--ps2', choices=('on', 'off'))
    ap.add_argument('--laser', help='PS2 pack folder (TEKKEN3_TTT_PS2_LASER_DIR)')
    ap.add_argument('--guest', help='player 1 a guest of the catalogue (lob case; needs --data)')
    a = ap.parse_args()
    if a.data: bench.shutil.copytree = mods_view(Path(a.data))
    verdicts = {}
    for case in a.case:
        ok = False
        for distance in (DISTANCES if case == 'hit' else (0,)):
            crash, seen = run(a, case, distance)
            print(f'  {case}' + (f' at {distance}' if case == 'hit' else '') +
                  f': crash {crash}, states (state, homing, on P2) {seen}', flush=True)
            states = [s for s, _, _ in seen]
            if case == 'hit' and not crash and 4 not in states: continue      # the move missed: farther
            if crash: break
            after = states[states.index(4) + 1:] if 4 in states else []
            ok = bool(after) and (case == 'lob' or any(s == 2 and on for s, _, on in seen[states.index(4) + 1:]))
            break
        verdicts[case] = ok
        print(f'RESULT {case}: {"OK" if ok else "KO"}', flush=True)
    print('SUMMARY', ' '.join(f'{c}={"OK" if v else "KO"}' for c, v in verdicts.items()))
    sys.exit(0 if all(verdicts.values()) else 1)


if __name__ == '__main__':
    main()
