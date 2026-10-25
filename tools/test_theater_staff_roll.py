#!/usr/bin/env python3
"""Theater's MUSIC PLAYER, 5: STAFF ROLL (B91, GH#145), checked in the game.

    python tools/test_theater_staff_roll.py [--build build-rel-lite] [--disc CUE] [--no-mods]

Runs a private copy of the build as tools/test_stage_options.py does
(headless, software renderer, a copy of saves/card1.mcd), Theater unlocked
(0x80097F26/27), its MUSIC PLAYER, then 5: STAFF ROLL in the remixed and in
the arcade list. The staff roll is the game's only CD-DA piece (track 2,
music_play_source 0x8006B194: Setloc to the TOC time of the track, which
GetTD gives in minutes and seconds, then Play). Each version must send that
Play, the CD audio must reach the SPU (the cd_in tap grows) and the game must
keep answering (the cursor moves, frames go on). Before the fix the runtime
left out the cue's PREGAP 00:02:00: track 2 sat two seconds early, the Play
landed in the data track and the drive stayed in a silent PLAY state.
"""
import argparse, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_stage_options as tso
from test_stage_options import CROSS, START, UP, DOWN, LEFT, RIGHT

tso.WORK = ROOT / 'workspace/b91'
MENU, TOC, UNLOCK = 0x800adc90, 0x800a0798, 0x80097f26
REMIXED, ARCADE = 2, 3                      # EndingMenu.state in the music player
STAFF_ROLL = 4                              # its row (5: STAFF ROLL)


def bcd(b): return (b >> 4) * 10 + (b & 15)


def menu(g):
    m = g.read(MENU, 16)
    return dict(state=m[0], cursor=m[6], sub=int.from_bytes(m[10:12], 'little', signed=True))


def cd_audio(g):
    return next(t['frames'] for t in g.q(cmd='audio_stats')['taps'] if t['name'] == 'cd_in')


def staff_roll(g, version):
    """Plays 5: STAFF ROLL in `version`; returns the Setloc of its Play."""
    if menu(g)['state'] != version:                  # BGM SELECT: right, down, Cross, back left
        g.tap(RIGHT); g.tap(DOWN)
        assert menu(g)['sub'] == 4, f'not on BGM SELECT: {menu(g)}'
        g.press(CROSS); g.wait(lambda: menu(g)['state'] == version, f'no list {version}', 10)
        g.tap(LEFT)
    g.wait(lambda: menu(g)['sub'] == 0, 'the cursor is not in the list', 10)
    while menu(g)['cursor'] < STAFF_ROLL: g.tap(DOWN)
    while menu(g)['cursor'] > STAFF_ROLL: g.tap(UP)
    seq = g.q(cmd='cdrom_command_history')['entries'][0]['seq']
    g.press(CROSS)
    time.sleep(2)
    entries = [e for e in g.q(cmd='cdrom_command_history')['entries'] if e['seq'] > seq]
    plays = [e for e in entries if e['cmd'] == '0x03']
    assert plays, f'no Play sent: {[e["cmd"] for e in entries]}'
    setloc = next((e['params'] for e in entries if e['cmd'] == '0x02' and e['seq'] < plays[0]['seq']), None)
    before, frame = cd_audio(g), g.frame()
    time.sleep(3)
    flowing = cd_audio(g) - before
    g.tap(UP)
    moved = menu(g)['cursor'] == STAFF_ROLL - 1
    if not moved:                               # what the game is doing
        f0 = g.frame(); time.sleep(1)
        print(f'STUCK? frames +{g.frame() - f0} in 1 s, screen {g.screen()}, menu {menu(g)}, '
              f'menu bytes {g.read(MENU, 16).hex()}, stream {g.read(0x800a05d8, 16).hex()}', flush=True)
        g.shot(f'stuck-{version}')
        g.tap(UP); time.sleep(.5)
        print(f'again: menu {menu(g)}', flush=True)
    print(f'{"REMIXED" if version == REMIXED else "ARCADE "}: Setloc {setloc}, Play, CD audio +{flowing} frames in 3 s, '
          f'{g.frame() - frame} frames, cursor {"moves" if moved else "STUCK"}', flush=True)
    assert moved, 'the game no longer answers'
    assert flowing > 44100, 'the staff roll is silent: no CD audio reaches the SPU'
    g.tap(DOWN)
    return setloc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--disc', help='a cue other than disc/Tekken 3 (USA).cue')
    ap.add_argument('--no-mods', action='store_true', help='--mods none: no packages (the compiled mods stay)')
    a = ap.parse_args()
    g = launch(a)
    try:
        end = time.monotonic() + 180
        while g.screen() != 4:
            if time.monotonic() > end: raise RuntimeError('the modes menu never came')
            g.write(UNLOCK, 1, 1); g.write(UNLOCK + 1, 1, 1)
            if g.screen() in (1, 3, 6, 8): g.press(START)
            time.sleep(.3)
        time.sleep(.6)
        g.mode('THEATER MODE')
        g.wait(lambda: g.screen() == 19, 'no Theater'); time.sleep(4)
        while menu(g)['sub'] == 0: g.tap(DOWN)          # the bottom bar: DISC 3, MUSIC 2, EXIT 1
        for _ in range(3):
            if menu(g)['sub'] == 2: break
            g.tap(LEFT if menu(g)['sub'] == 1 else RIGHT)
        assert menu(g)['sub'] == 2, f'not on MUSIC: {menu(g)}'
        g.press(CROSS)
        g.wait(lambda: menu(g)['state'] in (REMIXED, ARCADE), f'no MUSIC PLAYER: {menu(g)}', 20); time.sleep(1)
        toc = g.read(TOC, 12)
        print(f'TOC: track 2 at {bcd(toc[8]):02d}:{bcd(toc[9]):02d}', flush=True)
        for version in (REMIXED, ARCADE): staff_roll(g, version)
        print('staff roll: OK')
    finally:
        g.stop()


def launch(a):
    """tso.Game, with another cue or without the mods: its __init__ builds the command line."""
    real = tso.subprocess.Popen
    def popen(cmd, *args, **kw):
        if a.disc: cmd = [a.disc if c.endswith('Tekken 3 (USA).cue') else c for c in cmd]
        if a.no_mods: cmd = cmd + ['--mods', 'none']
        return real(cmd, *args, **kw)
    tso.subprocess.Popen = popen
    try: return tso.Game(ROOT / a.build, None, {}, 'staff-roll')
    finally: tso.subprocess.Popen = real


if __name__ == '__main__':
    main()
