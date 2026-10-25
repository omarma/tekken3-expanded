#!/usr/bin/env python3
"""SURVIVAL RESULTS announces "<name> wins" in full (B82, GH#140).

    python tools/test_survival_announce.py --build build-rel-lite --who gunjack-ttt1|gunjack-t3|paul-t3|anna-t3
        [--wins 2] [--tag NAME]

Cold start, Survival from the cabinet selector: player 1 takes the fighter
(TEKKEN3_NATIVE_MOVES=1 puts a native on its TTT1 moves, 0 on T3's), wins
--wins fights (the CPU's life to 0), loses the next one and reaches SURVIVAL
RESULTS (state 14), where from 2 wins on the announcer says the fighter's
name (announce_name 0x800757A8, sound 0xC640 on voice 1), then
results_wins_announce (0x80075864) waits while SpuGetKeyStatus(voice 1)
(0x8008D658, returning to 0x800758B4) gives 1 and says "wins" (0x86DA) 15
frames after. The emulated SPU raises the envelope only when it renders: the
first check read 3 (keyed, envelope 0), and "wins" came 16 frames after the
name, over it ("GUN- WINS", natives on both movesets). Fails when the
runtime does not report the native's name over after at least MIN_CHECKS
checks; a debug-tools build also prints the frames of both sounds.
"""
import argparse, re, struct, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_devil_jin as T
import test_tarzan_crash as Z

T.WORK = ROOT / 'workspace/survival-announce'
WINS, MODE = 0x800afaac, 0x800afa88
WHO = {'gunjack-ttt1': (16, '1'), 'gunjack-t3': (16, '0'), 'paul-t3': (0, '0'), 'anna-t3': (18, '0')}
MIN_CHECKS = 40           # measured: Gun Jack's name 71 checks, Paul's 77; cut, "wins" came after 1
SOUND_PLAY, KEY_STATUS, RESULTS_WINS_RETURN = 0x800753bc, 0x8008d658, 0x800758b4


def fields(g, p=0):
    return struct.unpack('<4H', bytes.fromhex(g.q(cmd='read_ram', addr=f'{T.ACTOR + p * T.STRIDE + 0x14:08x}', len=8)['hex']))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', required=True)
    ap.add_argument('--who', choices=WHO, required=True)
    ap.add_argument('--wins', type=int, default=2)
    ap.add_argument('--tag', default=None)
    a = ap.parse_args()
    T.WORK.mkdir(parents=True, exist_ok=True)
    cid, native_moves = WHO[a.who]
    tag = a.tag or a.who
    g = Z.Game(Path(a.build).resolve(), tag, {'TEKKEN3_NATIVE_MOVES': native_moves, 'TEKKEN3_SURVIVAL_GUESTS': '0,0'})
    try:
        T.to_selector(g)
        g.q(cmd='write_ram', addr=f'{MODE:08x}', bytes='04')
        # Gun Jack is not on the cursor's path: take Paul, then write the ID
        # the pick handler reads (+28 of the player's block) and, at every
        # loading, the one the fight reads (0x800ADD5C), as tools/test_tarzan_crash.py.
        steps = []
        for _ in range(120):
            steps.append(g.value(T.CURSOR_CHAR))
            if steps[-1] == 0: break
            g.q(cmd='press', buttons=T.RIGHT, frames=6, port=1); time.sleep(.5)
        else: raise AssertionError(f'cursor did not reach Paul: {steps[-24:]}')
        g.q(cmd='write_ram', addr=f'{T.CURSOR_CHAR:08x}', bytes=cid.to_bytes(2, 'little').hex())
        g.press(T.SQUARE, frames=12)
        assert g.value(MODE, 1) == 4, f'mode {g.value(MODE, 1)}, not Survival'

        def step():
            state = g.value(T.STATE)
            if state == 9: g.press(T.SQUARE, frames=12)
            if state == 11: g.q(cmd='write_ram', addr='800add5c', bytes=cid.to_bytes(2, 'little').hex())
        fighting = lambda: g.value(T.STATE) == 8 and g.value(T.PHASE, 2) >= 8
        for n in range(a.wins + 1):
            g.wait(fighting, f'fight {n + 1} did not start', 150, step)
            f = fields(g)
            print(f'fight {n + 1}: P1 +0x14..+0x1A = {[hex(v) for v in f]}, wins {g.value(WINS, 2)}', flush=True)
            assert f[2] == cid, f'P1 is {f[2]}, not {cid}'
            time.sleep(1.5)
            life = T.ACTOR + (T.STRIDE if n < a.wins else 0) + T.LIFE
            end = time.monotonic() + 100
            while g.value(T.STATE) == 8 and g.value(WINS, 2) <= n and time.monotonic() < end:
                if fighting(): g.q(cmd='write_ram', addr=f'{life:08x}', bytes='0000')
                g.q(cmd='press', buttons=T.SQUARE if n < a.wins else 0xffff, frames=4); time.sleep(.4)
                if n == a.wins and g.value(T.STATE) == 14: break
        g.wait(lambda: g.value(T.STATE) == 14, 'SURVIVAL RESULTS not reached', 120,
               lambda: g.q(cmd='write_ram', addr=f'{T.ACTOR + T.LIFE:08x}', bytes='0000') if fighting() else None)
        try:
            for target in (SOUND_PLAY, KEY_STATUS): g.q(cmd='fntrace_arm', target=f'{target:08x}')
            traced = True
        except RuntimeError: traced = False
        f = fields(g)
        print(f'results: P1 +0x14..+0x1A = {[hex(v) for v in f]}, wins {g.value(WINS, 2)}', flush=True)
        time.sleep(12)
        g.shot('results')
        if traced:
            calls = g.q(cmd='fntrace_dump', count=4000)['entries'][::-1]
            for c in calls:
                if int(c['target'], 16) == SOUND_PLAY:
                    print(f"  frame {c['frame']}: sound_play({int(c['a0'], 16)}, {int(c['a1'], 16):#06x}) ra {c['ra']}")
            checks = [c for c in calls if int(c['target'], 16) == KEY_STATUS and int(c['ra'], 16) == RESULTS_WINS_RETURN]
            if checks: print(f"  voice 1 checked by the results {len(checks)} times, frames {checks[0]['frame']}..{checks[-1]['frame']}")
        lines = [l for l in g.log().splitlines() if 'announced name' in l or 'SURVIVAL RESULTS' in l]
        for l in lines[-4:]: print('  ', l)
        over = [int(m.group(1)) for l in lines for m in [re.search(r"native's name over after (\d+) checks", l)] if m]
        if not over: raise SystemExit('FAIL: "wins" did not wait for the name (no "name over" line in the log)')
        if over[-1] < MIN_CHECKS: raise SystemExit(f'FAIL: "wins" after {over[-1]} checks, the name is cut')
        print(f'PASS: "wins" waited {over[-1]} checks for the name')
    finally:
        g.stop()


if __name__ == '__main__':
    main()
