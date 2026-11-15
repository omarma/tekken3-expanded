#!/usr/bin/env python3
"""Continue after a lost fight (B190): the game must not crash.

    python tools/test_b190_continue.py --who native|guest|jin-dr [--mode arcade|timeattack]
        [--continues 3] [--change 0|1] [--guest jun] [--build build-rel-lite] [--visible]

Boots from a copy of the memory card (no save states), opens the mode from
the modes menu, picks player 1 on the selector: a Tekken 3 fighter on his own
moves (Jin, MOVESET card TEKKEN 3), a TTT1 guest (Tag page, R2), or Jin on
Tekken 5 DR's moves (card: Right twice). Player 1 loses (life 0) and takes
the Continue with Start, --continues times, with CHARACTER CHANGE AT CONTINUE
(0x80097F0A, read when the mode starts) NO (the same fight again) or YES
(back through the selector, the same choice taken again).
Passes when every Continue comes back to a running fight and the game is
still alive; on a crash prints the exit code and psx_crash.txt.
"""
import argparse, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live as L
from test_cpu_moveset_draw import MODES

NO_PAD = dict(SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS='0', SDL_JOYSTICK_HIDAPI='0', SDL_JOYSTICK_RAWINPUT='0',
              SDL_XINPUT_ENABLED='0', SDL_JOYSTICK_DIRECTINPUT='0', SDL_JOYSTICK_WGI='0', SDL_JOYSTICK_GAMEINPUT='0')
START_SELECT, UP, RIGHT, LEFT, CROSS, SQUARE, START = 0xfff6, 0xffef, 0xffdf, 0xff7f, 0xbfff, 0x7fff, 0xfff7
STATE, PHASE, HUMAN, CHANGE, P1_LIFE, P1_CHAR = 0x800ae204, 0x800ae224, 0x800ae1f8, 0x80097f0a, 0x800a961c, 0x80118668
JIN = 9


def alive(s):
    if s.process.poll() is not None:
        raise SystemExit(f'CRASH: the game exited with code {s.process.returncode}')


def wait(s, predicate, what, seconds):
    end, seen = time.monotonic() + seconds, []
    while time.monotonic() < end:
        alive(s)
        if predicate(): return
        st = (s.value(STATE), s.value(HUMAN, 1), s.value(PHASE, 2))
        if not seen or seen[-1] != st: seen.append(st)
        time.sleep(.1)
    raise AssertionError(f'{what}; (state, P1 human, phase) seen: {seen[-12:]}')


def pick(s, who):
    """Player 1's choice on the selector grid (state 9), then the fight's loading."""
    if who == 'guest':
        time.sleep(1)
        if s.value(0x80118648) != s.catalogue_size: s.press(L.PAD_R2)   # a Continue's selector keeps the page
        wait(s, lambda: s.value(0x80118648) == s.catalogue_size, 'R2 did not open the Tag page', 10)
        time.sleep(1.5)
        for k in range(40):                                # each row in turn (Right wraps in its row)
            if s.value(P1_CHAR) == s.cid: break
            s.press(0xffbf if k % 10 == 9 else RIGHT); time.sleep(.3)
        wait(s, lambda: s.value(P1_CHAR) == s.cid, 'the cursor did not reach the guest', 10)
        s.press(SQUARE)
        return
    for _ in range(30):
        if s.value(P1_CHAR) == JIN: break
        s.press(LEFT); time.sleep(.25)                     # as ttt1_live.cabinet
    else: raise AssertionError('the cursor never reached Jin')
    s.press(SQUARE); time.sleep(.6)                       # the MOVESET card opens on TEKKEN 3
    if who == 'jin-dr':
        s.press(RIGHT); time.sleep(.6); s.press(RIGHT); time.sleep(.6)   # T3 -> TTT1 -> DR
    s.press(CROSS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--who', default='native', choices=['native', 'guest', 'jin-dr'])
    ap.add_argument('--mode', default='arcade', choices=['arcade', 'timeattack'])
    ap.add_argument('--continues', type=int, default=3)
    ap.add_argument('--change', type=int, default=0, choices=[0, 1])
    ap.add_argument('--guest', default='jun')
    ap.add_argument('--build', default=str(L.ROOT / 'build-rel-lite'))
    ap.add_argument('--visible', action='store_true')
    a = ap.parse_args()
    os.environ.update(NO_PAD)
    s = L.Session(visible=a.visible, guest=a.guest, build=Path(a.build), env={'TEKKEN3_NATIVE_MOVES': ''})
    crash = L.ROOT / 'psx_crash.txt'
    if crash.exists(): crash.unlink()
    snap = lambda: (s.value(STATE), s.value(HUMAN, 1))
    done = 0
    try:
        # The session booted to the Arcade selector; the mode chosen again from the menu sets the option.
        s.press(START_SELECT); wait(s, lambda: s.value(STATE) == 4, 'the modes menu', 15); time.sleep(.8)
        s.write(CHANGE, a.change, 1)
        s.write(0x80097f40, {'arcade': 0, 'timeattack': 4}[a.mode])
        for _ in range(10):
            if s.value(STATE) == 9: break
            s.press(CROSS); time.sleep(.5)
        wait(s, lambda: s.value(STATE) == 9 and s.value(0x80118648) == 21, 'the selector', 20); time.sleep(1.5)
        pick(s, a.who)
        while True:
            wait(s, lambda: snap() == (8, 1) and s.value(PHASE, 2) >= 8, f'the fight (after {done} Continues)', 120)
            time.sleep(2)
            alive(s)
            print(f'fight {done + 1}: running, P1 character {s.actor(0)[1]}', flush=True)
            if done == a.continues: break
            while snap()[1]:
                alive(s); s.write(P1_LIFE, 0); time.sleep(.05)   # loses: the countdown
            time.sleep(.6)
            s.q(cmd='set_input', buttons=START); time.sleep(.15); s.q(cmd='set_input', buttons=65535)
            done += 1
            print(f'Continue {done} taken', flush=True)
            if a.change:
                wait(s, lambda: s.value(STATE) == 9, 'the selector after the Continue', 60); time.sleep(1.5)
                pick(s, a.who)
        time.sleep(3); alive(s)
        # The player's side is never the CPU's in its fight, the Continue countdown included.
        drawn = [l for l in s.log().splitlines() if 'models: CPU P1 ' in l or 'moves: CPU P1 ' in l]
        if drawn: raise AssertionError('player 1 drawn as the CPU: ' + '; '.join(drawn))
    except SystemExit as e:
        print(e)
        time.sleep(1)
        if crash.exists(): print(crash.read_text(errors='replace'))
        tail = s.log().splitlines()[-25:]
        print('--- log tail ---'); print('\n'.join(tail))
        s.stop(); sys.exit(1)
    except BaseException:
        try:
            shot = L.WORK / f'b190-{a.who}-{a.mode}-{a.change}.png'
            s.q(cmd='screenshot', path=str(shot)); print('screenshot:', shot)
        except Exception as e: print('no screenshot:', e)
        lines = [l for l in s.log().splitlines() if "Anna's third" not in l and '[FPS]' not in l]
        print('--- log tail ---'); print('\n'.join(lines[-60:]))
        s.stop(); raise
    s.stop()
    print(f'ok: {a.continues} Continues ({a.who}, {a.mode}, change {a.change}), no crash')


if __name__ == '__main__': main()
