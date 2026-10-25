#!/usr/bin/env python3
"""Unknown's style switch (F14, GH#48): player 1's L1, and the CPU's switches.

    python tools/test_unknown_switch.py [--build build-rel-lite] [--player] [--cpu] [--rounds]
                                        [--trials 4] [--frames 18000]

--player: Practice from a cold start, Unknown written for player 1 at the
selector, the dummy standing. Each trial: L1 from her stance, then a jab
held from the next frame (the debug server's input route); the frames from
L1 to her first attack record (+45, the first hit frame, non-zero) are read
on the game's frame counter. TTT1's switch is a cancel into the new stance,
whose moves start at once (F14: 4 to 6 frames in MAME); before F14 the
stance was queued for its 60 frames and took no move (nothing within 60
frames). Fails past 15 frames, or when no switch happened.

--cpu: Arcade, Unknown written for the CPU while the fight loads, player 1
attacking without pause (1, 2, 3, 4, forward), his life and the clock held,
hers given back under 50. Counts the CPU's switches in --frames game frames
(game log): TTT1's CPU switches about once every 750 frames under attack
(F14, MAME); before F14 here, once every ~1,300, each request waiting up to
120 frames. Fails when the mean gap is outside 400..1,100 frames or a
request did not switch.

--rounds: Arcade, Unknown written for player 1; L1 switches her, the CPU's
life is taken, and the next round must start on her own moveset (Jun's), as
TTT1's rounds do: the game log says "P1 Unknown back to her own moveset"
after the switch. Before F14 she kept the moveset she ended the round on.

--regen: Arcade, Unknown for both players (player 1 is not regenerated, the
CPU is). Each loses 40 points (written to her life: the runtime takes it as a
hit); then, player 1 idle and his life held, their lives are sampled for
--regen-frames frames (player 1's life held past the first 300). The CPU's
must climb at TTT1's 1.95 points a second (1.6..2.3) up to 40 % of the 40
points (16, within 1.5) and no further; player 1's must not rise in the first
300 frames. Before: no regeneration.

Without an option: --player, --cpu, --rounds and --regen. Build: rel-lite (debug server lite).
"""
import argparse, re, struct, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_unknown_wolf as tw
tw.WORK = ROOT / 'out/f14'

STATE, PHASE, LINE = tw.STATE, tw.PHASE, 0x80097f40
ACTOR, STRIDE = tw.ACTOR, tw.STRIDE
PRACTICE_LINE = 8
CHOICE_P1 = (0x80118688, 0x80118690)       # Practice: player 1's confirmed choice (tools/ttt1/balance.py)
CLOCK, LIFE = 0x800adbcc, 0x3f6
NONE, START, CROSS = 0xffff, 0xfff7, 0xbfff
L1, B1, B2, B3, B4, FWD = 0xfbff, 0x7fff, 0xefff, 0xbfff, 0xdfff, 0xffdf


def frame(g): return g.q(cmd='frame')['frame']


def attack(g):
    """Player 1's record has a hit window (+45, its first hit frame)."""
    record = g.value(ACTOR + 0x54)
    return 0x80000000 <= record < 0xa0000000 and g.value(record + 45, 1) != 0


def to_practice(g, unknown):
    g.q(cmd='turbo', enabled=1)

    def menu():
        if g.value(STATE) == 3:
            g.write(0x80097f26, b'\1'); g.write(0x80097f27, b'\1'); g.press(START)
        return g.value(STATE) == 4
    g.wait(menu, 'mode menu not reached', 240)
    g.q(cmd='turbo', enabled=0)
    time.sleep(.5)
    g.write(LINE, struct.pack('<I', PRACTICE_LINE)); g.press(CROSS)
    g.wait(lambda: g.value(STATE) == 9, 'Practice selector not reached', 30)
    time.sleep(1.5)
    g.press(CROSS); time.sleep(1)                      # player 1 confirms; his pad then picks the CPU
    for _ in range(12):
        for a in CHOICE_P1: g.write(a, bytes([unknown]))
        if g.value(STATE) != 9: break
        g.press(CROSS); time.sleep(.7)
    g.wait(lambda: g.value(STATE) == 8 and g.value(PHASE, 2) >= 8, 'fight not started', 120)
    g.wait(lambda: g.value(ACTOR + 0x18, 2) == unknown, 'Unknown is not player 1', 10)
    time.sleep(3)


def route(g, steps):
    g.q(cmd='input_route_clear')
    for buttons, frames in steps: g.q(cmd='input_route_append', buttons=buttons, frames=frames)
    g.q(cmd='input_route_start')


def player_trials(g, trials):
    """Frames from L1 to the first attack record, one per trial (None: no attack in 60)."""
    results = []
    # A jab first: Practice's banner may hold the first inputs.
    for _ in range(10):
        route(g, [(B1, 3), (NONE, 60)])
        end = frame(g) + 20
        while frame(g) < end and not attack(g): time.sleep(.01)
        if attack(g): break
    else: raise AssertionError('a jab never started')
    time.sleep(1.5)
    for _ in range(trials):
        switches = g.log().count('P1 Unknown switches to')
        route(g, [(L1, 1), (B1, 40), (NONE, 60)])
        start = frame(g)
        seen = None
        while frame(g) - start < 60:
            if attack(g): seen = frame(g) - start; break
            time.sleep(.005)
        assert g.log().count('P1 Unknown switches to') > switches, 'L1 did not switch her moveset'
        results.append(seen)
        while g.q(cmd='input_route_status').get('active'): time.sleep(.05)
        time.sleep(1)
    return results


def cpu_run(g, frames):
    p2 = ACTOR + STRIDE
    lap = [(B1, 2), (NONE, 3), (B2, 2), (NONE, 3), (B1 & FWD, 2), (NONE, 5), (B3, 2), (NONE, 3),
           (B4, 2), (NONE, 6), (FWD, 20), (B2 & B1, 2), (NONE, 8)]
    f0, hits, last = frame(g), 0, None
    while frame(g) - f0 < frames:
        if not g.q(cmd='input_route_status').get('active'): route(g, lap * 6)
        life = g.value(p2 + LIFE, 2)
        hits += last is not None and life < last
        last = life
        g.write(CLOCK, struct.pack('<I', 2000))
        g.write(ACTOR + LIFE, struct.pack('<H', 130))
        if g.value(p2 + LIFE, 2) < 50: g.write(p2 + LIFE, struct.pack('<H', 130)); last = 130
        if g.value(STATE) != 8: raise AssertionError('the fight ended')
        time.sleep(.2)
    log = g.log()
    requests = log.count('P2 Unknown (CPU) switches under pressure')
    switches = log.count('P2 Unknown switches to')
    print(f'CPU: her life fell at {hits} samples (5 a second)')
    return requests, switches, frame(g) - f0


def rounds_run(g):
    """L1, then the CPU knocked out: the log lines from the switch on."""
    time.sleep(2)
    for _ in range(10):
        if 'P1 Unknown switches to' in g.log(): break
        route(g, [(L1, 2), (NONE, 30)]); time.sleep(1.5)
    else: raise AssertionError('L1 did not switch her moveset')
    tail = len(g.log())
    g.write(ACTOR + STRIDE + LIFE, bytes(2))
    g.wait(lambda: g.value(PHASE, 2) < 6, 'the round did not end', 60)
    # The next round's start (0x8002A914) logs the moveset she takes back.
    end = time.monotonic() + 120
    while time.monotonic() < end and 'P1 Unknown back to her own moveset' not in g.log()[tail:]: time.sleep(.5)
    return g.log()[tail:]


def regen_run(g, frames):
    """Both lose 40 points, then (frame, P1 life, P2 life) samples, lives in points."""
    p2 = ACTOR + STRIDE
    time.sleep(2)
    full = [g.value(a + LIFE - 2) / 65536 for a in (ACTOR, p2)]
    for a in (ACTOR, p2): g.write(a + LIFE - 2, struct.pack('<i', g.value(a + LIFE - 2) - (40 << 16)))
    f0, samples = frame(g), []
    p1_life = g.value(ACTOR + LIFE - 2)
    while frame(g) - f0 < frames:
        g.write(CLOCK, struct.pack('<I', 2000))
        if frame(g) - f0 > 300: g.write(ACTOR + LIFE - 2, struct.pack('<i', p1_life))   # past the check, held
        samples.append((frame(g) - f0, g.value(ACTOR + LIFE - 2) / 65536, g.value(p2 + LIFE - 2) / 65536))
        if g.value(STATE) != 8: raise AssertionError('the fight ended')
        time.sleep(.1)
    return full, samples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--player', action='store_true')
    ap.add_argument('--cpu', action='store_true')
    ap.add_argument('--rounds', action='store_true')
    ap.add_argument('--regen', action='store_true')
    ap.add_argument('--regen-frames', type=int, default=1500)
    ap.add_argument('--trials', type=int, default=4)
    ap.add_argument('--frames', type=int, default=18000)
    a = ap.parse_args()
    if not (a.player or a.cpu or a.rounds or a.regen): a.player = a.cpu = a.rounds = a.regen = True
    build = (ROOT / a.build).resolve()
    unknown = tw.unknown_id(build)
    failures = []
    if a.player:
        g = tw.Game(build, 'switch-player', env={'TEKKEN3_UNKNOWN_WOLF': '0'})
        try:
            to_practice(g, unknown)
            results = player_trials(g, a.trials)
        finally:
            g.stop()
        print('player 1, L1 to the first attack (frames):', results)
        if any(r is None or r > 15 for r in results):
            failures.append(f'no move right after L1: {results} (before F14: none within 60 frames)')
    if a.cpu:
        g = tw.Game(build, 'switch-cpu', env={'TEKKEN3_UNKNOWN_WOLF': '0'})
        try:
            tw.to_fight(g, (2,), unknown)
            requests, switches, frames = cpu_run(g, a.frames)
        finally:
            g.stop()
        gap = frames / switches if switches else None
        print(f'CPU: {switches} switches for {requests} requests in {frames} frames'
              + (f', one every {gap:.0f}' if gap else ''))
        if not gap or not 400 <= gap <= 1100:
            failures.append(f'CPU switches once every {gap} frames (TTT1: ~750)')
        if switches < requests:
            failures.append(f'{requests - switches} CPU requests did not switch')
    if a.rounds:
        g = tw.Game(build, 'switch-rounds', env={'TEKKEN3_UNKNOWN_WOLF': '0'})
        try:
            tw.to_fight(g, (1,), unknown)
            g.wait(lambda: g.value(PHASE, 2) >= 8, 'fight phase', 60)
            after = rounds_run(g)
        finally:
            g.stop()
        back = 'P1 Unknown back to her own moveset' in after
        print('next round on her own moveset:', back)
        if not back: failures.append('the next round kept the moveset she switched to')
    if a.regen:
        g = tw.Game(build, 'switch-regen', env={'TEKKEN3_UNKNOWN_WOLF': '0', 'TEKKEN3_UNKNOWN_CPU_SWITCH': '100000,4,300'})
        try:
            tw.to_fight(g, (1, 2), unknown)
            g.wait(lambda: g.value(PHASE, 2) >= 8, 'fight phase', 60)
            full, samples = regen_run(g, a.regen_frames)
        finally:
            g.stop()
        f_end, p1_end, p2_end = samples[-1]
        p2_start = samples[0][2]
        rising = [s_ for s_ in samples if s_[2] < full[1] - 40 + 15]
        rate = (rising[-1][2] - rising[0][2]) / ((rising[-1][0] - rising[0][0]) / 60) if len(rising) > 2 else 0
        gained = max(s_[2] for s_ in samples) - (full[1] - 40)
        print(f'regen: CPU {p2_start:.1f} -> {p2_end:.1f} (gained {gained:.1f} of 40, {rate:.2f} points a second); '
              f'player 1 {samples[0][1]:.1f}, at most {max(s_[1] for s_ in samples if s_[0] <= 300):.1f} in 300 frames')
        if not 1.6 <= rate <= 2.3: failures.append(f'CPU regeneration {rate:.2f} points a second (TTT1: 1.95)')
        if abs(gained - 16) > 1.5: failures.append(f'CPU got back {gained:.1f} points of 40 (TTT1: 40 %, 16)')
        if max(s_[1] for s_ in samples if s_[0] <= 300) > samples[0][1] + .01:
            failures.append('player 1 regenerated')
    for f in failures: print('FAIL:', f)
    print('OK' if not failures else 'FAILED')
    sys.exit(1 if failures else 0)


main()
