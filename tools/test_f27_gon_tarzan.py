#!/usr/bin/env python3
"""Gon's "Tarzan" win pose ends on a flesh fall, the Jacks' on their crash (F27, GH#32).

    python tools/test_f27_gon_tarzan.py --build build-rel-lite
        [--who gon jack2 gunjack-ttt1 gunjack-t3] [--button cross circle square triangle]
        [--ttt1-assets DIR] [--trace] [--wav FILE] [--all]

Cold start per fighter, Arcade selector, player 1 takes it (Jack-2 on the Tag
page; Gon and Gun Jack written over Paul's pick), player 2's life goes to 0
and the button is held through the K.O. and the win pose. Every sound event
from the K.O. on is logged (TEKKEN3_TTT1_SOUND_LOG: SOUNDLOG lines of
0x80040DF4 and of the voices, 0x80040C90).

Gon's pose, one move per button (0xD67 square, 0xD68 triangle, 0xD69 cross,
0xD6A circle, the same animation), cries 0x5000 (the Tarzan yell) then
0x2007, which his voice table 18 maps to key 0xD986: tone 6 of his own bank,
a metal crash. Gon is run with each --button (default all four), the Jacks
with Cross (their Tarzan pose).
The runtime plays key 0x5981 instead (common bank, tone 1: the landing 0x104F)
and logs "Gon: Tarzan pose fall". Fails when Gon's pose does not take that
path, or when a Jack's pose (script 490) loses its crash 0x7098 (B50) or
takes Gon's path. Jack-2 and Gun Jack on TTT1's moves need the TTT1 catalogue:
--ttt1-assets (TEKKEN3_TTT1_ASSETS), default the build's own mods/ttt1.
--wav records the pose (SPU voices only, and FILE-music.wav as heard).
"""
import argparse, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_devil_jin as T
import test_tarzan_crash as TC

T.WORK = ROOT / 'workspace/f27-gon-tarzan'
BUTTONS = dict(TC.BUTTONS, square=T.pad(T.SQ), triangle=T.pad(T.TR))
WHO = dict(TC.WHO, gon=(17, '0'))
GON_POSES, YELL, CRY, FALL = range(0xd67, 0xd6b), 0x5000, 0x2007, 0x5981
CRASH = 0x7098                     # the Jacks' crash; with bit 0x800 on TTT1's moves


def start_fight(build, cid, tag, env):
    """A fresh game at the start of the first round, player 1 on cid."""
    g = TC.Game(build, tag, env)
    try:
        T.to_selector(g)
        if cid >= 23:
            g.press(TC.PAD_R2); time.sleep(1.5)
            T.cursor_to(g, cid)
        else:
            seen = []
            for _ in range(120):
                seen.append(g.value(T.CURSOR_CHAR))
                if seen[-1] == 0: break
                g.q(cmd='press', buttons=T.RIGHT, frames=6, port=1); time.sleep(.5)
            else: raise AssertionError(f'cursor did not reach Paul: {seen[-24:]}')
        # The pick handler (0x8010DAB8) reads the fighter at +28 of the
        # player's block: written over and over while the button is down (the
        # cursor puts its own back between frames).
        g.q(cmd='press', buttons=T.SQUARE, frames=12)
        end = time.monotonic() + .6
        while cid < 23 and time.monotonic() < end:
            g.q(cmd='write_ram', addr=f'{T.CURSOR_CHAR:08x}', bytes=cid.to_bytes(2, 'little').hex())
        states = []
        def step():
            state = g.value(T.STATE)
            if not states or states[-1][0] != state: states.append((state, g.value(0x800add5c, 2)))
            if state == 9: g.press(T.SQUARE, frames=12)
            if state not in (8, 9) and cid < 23: g.q(cmd='write_ram', addr='800add5c', bytes=cid.to_bytes(2, 'little').hex())
        g.wait(lambda: g.value(T.STATE) == 8 and g.value(T.PHASE, 2) >= 8, 'round did not start', 150, step)
        if T.actor(g, 0)[2] == cid: return g
        print(f'P1 is {T.actor(g, 0)[2]}, not {cid} (state, 0x800ADD5C: {states}): again')
    except AssertionError as e:
        print(f'{e}: again')
    g.stop()


def pose(a, who, button):
    """One cold start: the K.O., the pose, and the P1 sound lines after it."""
    cid, native_moves = WHO[who]
    env = {'TEKKEN3_TTT1_SOUND_LOG': '1'}
    if native_moves is not None: env['TEKKEN3_NATIVE_MOVES'] = native_moves
    if a.ttt1_assets: env['TEKKEN3_TTT1_ASSETS'] = str(Path(a.ttt1_assets).resolve())
    tag = f'{a.tag or who}-{button}'
    for _ in range(4):
        g = start_fight(Path(a.build).resolve(), cid, tag, env)
        if g: break
    else: raise SystemExit(f'FAIL: player 1 never got fighter {cid}')
    try:
        print(f'{who}: P1 actor +0x14,+0x16,+0x18 =', T.actor(g, 0)[:3])
        time.sleep(1.5)
        mark = len(g.log())
        if a.wav:
            probe = str(T.WORK / f'{tag}-probe.wav')
            # tap 3: the 24 SPU voices only (no CD music); tap 0: what is heard
            first = {tap: int(g.q(cmd='audio_wav', path=probe, tap=tap, count=1)['tap_total']) for tap in (0, 3)}
        # Player 2's life to 0, again for a few seconds: one write right after
        # the round starts can come before the life is set.
        start = time.monotonic(); end = start + 16; moves = set()
        while time.monotonic() < end:
            if time.monotonic() < start + 4:
                g.q(cmd='write_ram', addr=f'{T.ACTOR + T.STRIDE + T.LIFE:08x}', bytes='0000')
            g.q(cmd='press', buttons=BUTTONS[button], frames=20); time.sleep(.3)
            moves.add(g.value(T.ACTOR + T.MOVE, 2))
            if a.trace:
                n = int(time.monotonic() - start)
                sounds = [l for l in g.log()[mark:].splitlines() if 'SOUNDLOG P1' in l]
                print(f'{time.monotonic() - start:5.1f}s phase {g.value(T.PHASE, 2)} P1 move {g.value(T.ACTOR + T.MOVE, 2):#x} '
                      f'P2 life {g.value(T.ACTOR + T.STRIDE + T.LIFE, 2)} P1 sounds {len(sounds)} {sounds[-1:]}')
                if not (T.WORK / f'{tag}-t{n:02d}.png').exists(): g.shot(f't{n:02d}')
        g.shot('pose')
        if a.wav:
            for tap, name in ((3, Path(a.wav)), (0, Path(a.wav).with_name(Path(a.wav).stem + '-music.wav'))):
                r = g.q(cmd='audio_wav', path=str(name.resolve()), tap=tap, start=str(first[tap]))
                print(f"{name}: {r['frames'] / r['rate']:.1f} s at {r['rate']} Hz")
        log = g.log()
        lines = [l for l in log[mark:].splitlines() if 'SOUNDLOG' in l or 'TTT1 characters:' in l or 'Gon:' in l]
        (T.WORK / f'{tag}.sounds.txt').write_text('\n'.join(lines))
        for l in lines if a.all else [l for l in lines if 'P1' in l]: print('  ', l)
        return [l for l in lines if 'P1' in l], moves, [l for l in log.splitlines() if 'tables rejected' in l]
    finally:
        g.stop()


def check(who, lines, moves, rejected):
    """None when the pose is right, else what is wrong."""
    events = [int(m.group(1), 16) for l in lines for m in [re.search(r'SOUNDLOG P1 ([0-9A-F]{4})', l)] if m]
    voices = [int(m.group(1), 16) for l in lines for m in [re.search(r'SOUNDLOG P1 voice ([0-9A-F]{4})', l)] if m]
    gon = [l for l in lines if l.startswith('Gon: Tarzan pose fall')]
    if who == 'gon':
        if not moves & set(GON_POSES): return f'no win pose 0xd67..0xd6a (moves {sorted(map(hex, moves))})'
        if YELL not in voices or CRY not in voices: return f'pose cries {[hex(v) for v in voices]}, not {YELL:#x} then {CRY:#x}'
        if not gon or f'common sound {FALL:04X}' not in gon[0]: return f'the cry {CRY:#x} kept its metal crash'
        return None
    if rejected: return f'not on the TTT1 moves {rejected[:1]}'
    if gon: return f"a Jack took Gon's path: {gon[0]}"
    if not any(e & ~0x800 == CRASH for e in events): return f'Tarzan pose without its crash {CRASH:#06x}'
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', required=True)
    ap.add_argument('--who', choices=WHO, nargs='+', default=['gon', 'jack2', 'gunjack-ttt1', 'gunjack-t3'])
    ap.add_argument('--button', choices=BUTTONS, nargs='+', default=['cross', 'circle', 'square', 'triangle'],
                    help="Gon's buttons (the Jacks: cross)")
    ap.add_argument('--ttt1-assets', help="TTT1 catalogue for Jack-2 / Gun Jack TTT1 (default: the build's mods/ttt1)")
    ap.add_argument('--tag', default=None)
    ap.add_argument('--all', action='store_true', help="print player 2's sounds too")
    ap.add_argument('--trace', action='store_true', help='phase, move and a capture each second')
    ap.add_argument('--wav', help='record the pose to this WAV (one fighter, one button)')
    a = ap.parse_args()
    T.WORK.mkdir(parents=True, exist_ok=True)
    failed = []
    for who in a.who:
        for button in a.button if who == 'gon' else ['cross']:
            wrong = check(who, *pose(a, who, button))
            done = (f'{CRY:#06x} -> {FALL:#06x} (common bank, tone 1, the landing 0x104F)' if who == 'gon'
                    else f'crash {CRASH:#06x} kept')
            print(f"{'FAIL' if wrong else 'PASS'} {who} {button}: {wrong or done}")
            if wrong: failed.append(f'{who} {button}')
    if failed: raise SystemExit(f'FAIL: {failed}')
    print('PASS: Gon falls on flesh, the Jacks keep their crash')


if __name__ == '__main__':
    main()
