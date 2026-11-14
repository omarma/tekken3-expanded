#!/usr/bin/env python3
"""Tetsujin's and Kinjin's sword and dagger on Yoshimitsu's and Kunimitsu's moves (B177, GH#223).

    python tools/test_b177_tetsujin_weapons.py --exe build-rel-lite/Tekken_3_Expanded.exe
        [--donor kunimitsu|yoshimitsu|kazuya] [--player 0|1] [--costume 0|2] [--moves "1" "d/f+2" ...]
        [--tag NAME]

TTT1 draws them by code for body 15 at every frame (fighter_quad_strip_f0004_draw_maybe /
_f001a_, ttt-ps1 src/combat/80102A38.c); the mod draws them from the .stick beside Tetsujin's
models (tools/ttt1/stick.py). Practice from the selector save (slot 8, workspace/fixtures/ps1-saves),
Jin on both sides, then the chosen side becomes the Tetsujin guest (ID 23 written at 0x800ADD5C
while the fight loads), costume 0 (Tetsujin, Cross) or 2 (Kinjin, Triangle; also written at 0x800ADD98), on the
donor TEKKEN3_TETSUJIN_MOVESET forces. Checks in the game's log: the model read its weapons
(sword key 4, dagger key 26), the round drew the donor, and the weapon of that moveset was drawn
(TEKKEN3_STICK_LOG=1: one line per player when the drawn weapon changes); with another donor,
none. Screenshots of the guard and of each command (end of the move) go to workspace/b177-bench/<tag>.
Yoshimitsu is not one of Tetsujin's donors (guests only): a test roster copies Unknown@Yoshimitsu's
pack as Tetsujin@Yoshimitsu (--donor yoshimitsu does it in the bench's own copy of mods/ttt1).
Build: rel-lite (debug server lite).
"""
import argparse, os, re, shutil, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt1')]

KEY = {'kunimitsu': 26, 'yoshimitsu': 4}


def yoshimitsu_roster(exe):
    """A copy of the build with Tetsujin@Yoshimitsu (Unknown@Yoshimitsu's pack) in its donors."""
    run = exe.parent.parent / (exe.parent.name + '-b177-yoshi')
    if not run.is_dir():
        shutil.copytree(exe.parent, run, ignore=shutil.ignore_patterns('saves', '*.obj', 'CMakeFiles', '*.ninja*'))
    mods = run / 'mods/ttt1'
    for f in mods.glob('Unknown@Yoshimitsu-TTT1-*'):
        shutil.copy2(f, mods / f.name.replace('Unknown@', 'Tetsujin@'))
    donors = (mods / 'Tetsujin-TTT1-donors.txt').read_text()
    if 'Yoshimitsu' not in donors: (mods / 'Tetsujin-TTT1-donors.txt').write_text(donors + 'Yoshimitsu 4\n')
    return run / exe.name


def start(exe, work, donor, player, costume):
    import combos as K
    os.environ['TEKKEN3_STICK_LOG'] = '1'
    g = K.Game(exe, f'tetsujin@{donor}', work, player=player)
    try:
        g.q(dict(cmd='turbo', enabled=1))
        g.q(dict(cmd='savestate', op='load', slot=8))
        end = time.monotonic() + 60
        while g.u32(K.STATE) != 9:
            if time.monotonic() > end: raise RuntimeError('Practice selector not reached')
            time.sleep(.3)
        g.wait_frames(30)
        for p in (0, 1):
            for move in [K.held(K.L)] + [K.held(K.R)] * 11 + [K.held(K.D)] + [K.held(K.R)] * 11:
                if g.u8(K.CURSOR + p) == K.JIN: break
                g.tap(move); g.wait_frames(6)
            # Triangle gives the third costume (Kinjin for the guest); the loading screen's costume
            # alone is not enough, the actor's +0x14 comes from the selector's entry.
            g.tap(K.held(K.PAD[2] if p == player and costume == 2 else K.PAD[3])); g.wait_frames(30)
        for a in K.CHOICE[player]: g.w8(a, K.GUEST_ID)
        end, nudge = time.monotonic() + 240, time.monotonic() + 10
        while not (g.u32(K.STATE) == 8 and g.u16(K.ACTOR[1] + 0x3f6) > 0):
            if g.u32(K.STATE) == 11:                 # the loading screen reads ID and costume here
                g.q(dict(cmd='write_ram', addr=f'{0x800add5c + 2 * player:08x}', bytes=K.GUEST_ID.to_bytes(2, 'little').hex()))
                g.q(dict(cmd='write_ram', addr=f'{0x800add98 + 2 * player:08x}', bytes=costume.to_bytes(2, 'little').hex()))
                continue
            if time.monotonic() > end: g.shot('not-loaded.png'); raise RuntimeError('fight not loaded')
            if g.u32(K.STATE) == 9 and time.monotonic() > nudge: g.tap(K.held(K.PAD[3])); nudge = time.monotonic() + 3
            time.sleep(.2)
        g.wait_frames(120)
        g.q(dict(cmd='turbo', enabled=0))
        for attempt in range(8):
            g.tap(K.held(K.PAD[3])); g.wait_frames(60)
            before = g.u32(K.ACTOR[0] + 0x54)
            g.route([(4, K.held(K.PAD[1])), (6, K.NONE)])
            if g.u32(K.ACTOR[0] + 0x54) != before: break
            g.wait_frames(30)
        else:
            raise RuntimeError('1P FREESTYLE not reached')
        g.wait_frames(60)
        return g
    except Exception:
        g.close(); raise


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--exe', required=True)
    ap.add_argument('--donor', default='kunimitsu')
    ap.add_argument('--player', type=int, default=0, choices=[0, 1])
    ap.add_argument('--costume', type=int, default=0, choices=[0, 2])
    ap.add_argument('--moves', nargs='*', default=['1', '2', '3', '4', 'd/f+1'])
    ap.add_argument('--tag')
    a = ap.parse_args()
    import combos as K
    exe = Path(a.exe).resolve()
    if a.donor == 'yoshimitsu': exe = yoshimitsu_roster(exe)
    tag = a.tag or f'{a.donor}-p{a.player + 1}-c{a.costume}'
    work = ROOT / 'workspace/b177-bench' / tag
    g = start(exe, work, a.donor, a.player, a.costume)
    p = K.Probe(g, native=True)
    p.forward_is_right = lambda: True
    failures = []
    try:
        g.shot('guard.png')
        if a.player == 0:
            for n, cmd in enumerate(a.moves):
                steps = K.parse(cmd)
                p.play(K.timeline(steps, [1] + [12] * (len(steps) - 1)))
                g.shot(f'move{n}-{re.sub(r"[^0-9a-z]+", "_", cmd.lower()).strip("_")}.png')
        g.wait_frames(30)
    finally:
        g.close()
    text = (work / 'game.log').read_text(errors='replace')
    who = f'P{a.player + 1}'
    read = re.findall(r'Tetsujin model: weapon on moves key (\d+), bone (\d+), (\d+) quads', text)
    print('weapons read:', read)
    if {int(k) for k, _, _ in read} != {4, 26}: failures.append('the model did not read the sword and the dagger')
    drew = re.findall(who + r' Tetsujin draws (\S+) at round start \(moveset (\d+)\)', text)
    print('round draws:', drew)
    if not drew or drew[-1][0].lower() != a.donor: failures.append(f'the round did not draw {a.donor}')
    shown = re.findall(who + r' body 15 weapon: moves key (\d+), (\d+) quads', text)
    print('weapon drawn:', shown)
    want = KEY.get(a.donor)
    if want and not any(int(k) == want for k, _ in shown): failures.append(f'no weapon drawn on moves key {want}')
    if not want and shown: failures.append(f'a weapon drawn on {a.donor}: {shown}')
    for f in failures: print('FAIL', f)
    print('OK' if not failures else f'{len(failures)} failure(s)', '; shots in', work)
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
