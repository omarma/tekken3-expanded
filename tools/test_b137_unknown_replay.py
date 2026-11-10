#!/usr/bin/env python3
"""B137 (GH#187): the KO replay must play Unknown's styles as the fight had them.

    python tools/test_b137_unknown_replay.py [--build build-rel-lite]
           [--mode arcade|survival|timeattack|ball] [--side 2|1] [--switches 1] [--l1-in-replay]
           [--ko-after 150] [--timeout] [--switch 300,1,100000] [--runs 1]

The check (the bug back: she switches while the replay plays, and the frames
it plays from her first pack find another one there):
    --mode arcade --runs 3                     (before: 2 of 3 switch, one with 9 frames changed)
    --mode arcade --side 1 --l1-in-replay --runs 2       (before: 1 of 2 switches on L1)
and, the same rule elsewhere, --mode survival, timeattack, ball (OK before
too: Tekken Ball replays few frames, where she is seldom free to switch).

T3's replay (0x80031D0C in t3-ps1) does not re-simulate the fight: each frame
it records, for each fighter, the record played (+0x54), the clips blended
and the frame, in a ring of 300 frames (0x800ADE68 -> [slot 0x8009BCAC][2
fighters][300] x 0x34 bytes; state 0x8009BCA8: 7 recording, 1 playing;
frame recorded 0x8009BCB8, frame played 0x8009BCBC in half frames), and the
replay writes them back. Unknown's records and clips are in her pack, in
guest memory (two areas a player, the one she plays and the one a switch
left): the replay shows her styles only while the packs the recorded frames
name are still there. A style switch while the replay plays (her CPU
trigger, or L1) loads a pack over the area the first replayed frames name.

Unknown written at the loading screen for the CPU (--side 2) or for player 1
(--side 1: L1 until she has switched --switches times; --l1-in-replay: L1
again as the replay starts). Player 1 attacks, his life and the clock held,
the CPU's given back under 50, a point taken at the start (pressure for her
CPU switch). --ko-after game frames after her last switch, player 2 is left
one point and player 1 knocks him out (--timeout: the clock runs out);
nothing is pressed from then on. The bench then reads:

- until the replay starts (state 7), the ring (her 300 frames) and the
  guest memory around every record and clip they name: the fight's packs;
- while the replay plays, again and again, the frame played and the same
  memory: each frame played since the last read must find its record and
  clips as the fight left them;
- the game log: her switches while the replay plays (there must be none),
  and each pack loaded (switch line, then "custom=": its alias table), to
  name the style a record belongs to ("?": a record outside her packs, a
  reaction the opponent's moves put her on).

The debug server answers one request a frame: the ring, not polling, gives
every frame. The style of each replayed frame is printed in runs, fight /
replay. Fails on a switch during the replay or on a replayed frame whose
memory changed. --switch is TEKKEN3_UNKNOWN_CPU_SWITCH (min gap, chance,
pressure): the default has her CPU switch at once once 300 frames have
passed; her own (600,4,300) switches during the replay when the KO comes 600
frames or more after her last switch and less than 300 after she was hit.
Build: rel-lite (debug server lite).
"""
import argparse, re, struct, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_unknown_wolf as tw
tw.WORK = ROOT / 'out/b137'

STATE, PHASE, ACTOR, STRIDE = tw.STATE, tw.PHASE, tw.ACTOR, tw.STRIDE
REPLAY, RING, FRAMES, REC = 0x8009bca8, 0x800ade68, 300, 0x34   # state, slot +4, recorded +0x10, played +0x14
RECORDING, PLAYING = 7, 1
CLOCK, LIFE = 0x800adbcc, 0x3f6
NONE, L1, B1, B2, B3, B4, FWD = 0xffff, 0xfbff, 0x7fff, 0xefff, 0xbfff, 0xdfff, 0xffdf
LAP = [(B1, 2), (NONE, 3), (B2, 2), (NONE, 3), (B1 & FWD, 2), (NONE, 5), (B3, 2), (NONE, 3),
       (B4, 2), (NONE, 6), (FWD, 20), (B2 & B1, 2), (NONE, 8)]
MODE, LINE, BLOCKS = 0x800afa88, 0x80097f40, 0x800b8d70
MODES = {'arcade': (0, 0), 'timeattack': (4, 3), 'survival': (5, 4), 'ball': (6, 7)}   # menu line, mode
START, CROSS, SQUARE = 0xfff7, 0xbfff, 0x7fff
GUEST = (0x9f000000, 0xa0000000)         # guest memory, where the packs are
CLIP_BYTES = 64
POOL = 0x88000                           # one guest-memory area (tekken3_ttt1_roster.c POOL_SIZE)
MIN_CHECKED = 10                         # Tekken Ball may replay only its last 30 frames (mode 7)


def route(g, steps):
    g.q(cmd='input_route_clear')
    for buttons, frames in steps: g.q(cmd='input_route_append', buttons=buttons, frames=frames)
    g.q(cmd='input_route_start')


def to_menu(g):
    """The modes menu, Tekken Ball unlocked (0x80097F26 / 27)."""
    g.q(cmd='turbo', enabled=1)

    def menu():
        if g.value(STATE) == 3:
            g.write(0x80097f26, bytes([1])); g.write(0x80097f27, bytes([1])); g.press(START)
        return g.value(STATE) == 4
    g.wait(menu, 'mode menu not reached', 240)
    g.q(cmd='turbo', enabled=0)
    time.sleep(1)


def loading(g, side, unknown):
    """The loading screen (state 11), Unknown written for her side, then her round."""
    for _ in range(4):
        g.q(cmd='set_input', buttons=CROSS)
        end = time.monotonic() + 3
        while g.value(STATE) != 11 and time.monotonic() < end: pass
        g.q(cmd='set_input', buttons=NONE)
        if g.value(STATE) == 11: break
        time.sleep(.2)
    else: raise AssertionError('loading screen not reached')
    g.write(0x800add5c + 2 * (side - 1), struct.pack('<H', unknown))
    g.write(0x800add98 + 2 * (side - 1), bytes(2))
    g.wait(lambda: g.value(STATE) == 8 and g.value(PHASE, 2) >= 6, 'round did not start', 120)
    g.wait(lambda: g.value(ACTOR + (side - 1) * STRIDE + 0x18, 2) == unknown, f'Unknown is not P{side}', 30)


def to_fight(g, mode, side, unknown):
    """Arcade, Time Attack or Survival (the Arcade grid: player 1 on the
    fighter under the cursor), or Tekken Ball (the VS grid, the fighter under
    the cursor, then the ball under it); Unknown written while it loads."""
    line, number = MODES[mode]
    to_menu(g)
    g.write(LINE, struct.pack('<I', line)); g.press(CROSS)
    if mode == 'ball':
        g.wait(lambda: g.value(STATE) == 10 and g.value(MODE) == 7 and g.value(BLOCKS) == 3, 'TEKKEN BALL SELECT', 20)
        time.sleep(1.5)
        g.press(CROSS)
        g.wait(lambda: g.value(BLOCKS) == 15, 'the ball choice', 10)
    else:
        g.wait(lambda: g.value(STATE) == 9 and g.value(0x80118648) == 21, 'selector not reached', 30)
        time.sleep(1.5)
        if g.value(MODE) != number: raise AssertionError(f'mode {g.value(MODE)}, not {mode}')
        g.press(SQUARE); time.sleep(.5)
        if 'P1 opens the MOVESET card' in g.log(): g.press(CROSS)
    loading(g, side, unknown)


def frame(g): return g.q(cmd='frame')['frame']


def replay_vars(g):
    b = g.read(REPLAY, 0x18)
    state, slot = struct.unpack_from('<2I', b)
    played = struct.unpack_from('<I', b, 0x14)[0]
    return state, slot, played >> 1


def ring(g, side):
    """Her 300 frames: (record, clip blended from, clip blended to)."""
    slot = replay_vars(g)[1]
    b = g.read(g.value(RING) + slot * 2 * FRAMES * REC + (side - 1) * FRAMES * REC, FRAMES * REC)
    return [struct.unpack_from('<3I', b, k * REC) for k in range(FRAMES)]


def spans(frames):
    """Guest-memory ranges covering every record (56 bytes) and clip header the frames name."""
    points = sorted({a for f in frames for a in f if GUEST[0] <= a < GUEST[1]})
    out = []
    for a in points:
        if out and a - out[-1][1] < 0x8000: out[-1][1] = max(out[-1][1], a + CLIP_BYTES)
        else: out.append([a, a + CLIP_BYTES])
    return out


def memory(g, ranges):
    return [(lo, g.read(lo, hi - lo)) for lo, hi in ranges]


def at(mem, a, n):
    for lo, b in mem:
        if lo <= a and a + n <= lo + len(b): return b[a - lo:a + n - lo]
    return None


def same(mem0, mem1, f):
    """The frame's record and clips read the same in both reads."""
    return all(at(mem0, a, n) == at(mem1, a, n) for a, n in zip(f, (56, CLIP_BYTES, CLIP_BYTES))
               if GUEST[0] <= a < GUEST[1])


def loads(log, side):
    """(start, style) of each pack loaded for her, in order: its alias table, then its records."""
    out, style = [], 'own'
    for line in log.splitlines():
        m = re.search(rf'P{side} Unknown switches to (\S+)', line)
        if m: style = m.group(1); continue
        if f'P{side} Unknown back to her own moveset' in line: style = 'own'; continue
        m = re.search(rf'installed P{side} alias table.* custom=([0-9A-Fa-f]+)', line)
        if m: out.append((int(m.group(1), 16), style))
    return out


def style(packs, record):
    """The style of the pack last loaded in the record's area: each player has
    two areas of POOL bytes (tekken3_guest_pool_alloc), the record is
    in the one whose pack starts nearest."""
    if not packs or not GUEST[0] <= record < GUEST[1]: return '?'
    near = min((abs(record - base), base) for base, _ in packs)[1]
    return [s for base, s in packs if abs(base - near) < POOL // 2][-1]


def run(g, side, ko_after, timeout, wanted, l1_in_replay):
    switched = f'P{side} Unknown switches to'
    g.wait(lambda: g.value(PHASE, 2) >= 8, 'fight phase', 60)
    f0, switch_frame = frame(g), None
    p2 = ACTOR + STRIDE
    g.write(p2 + LIFE - 2, struct.pack('<i', g.value(p2 + LIFE - 2) - (1 << 16)))   # a hit: her CPU's pressure
    while True:
        if not g.q(cmd='input_route_status').get('active'):
            more = side == 1 and g.log().count(switched) < wanted
            route(g, ([(L1, 2), (NONE, 20)] if more else []) + LAP * 4)
        g.write(CLOCK, struct.pack('<I', 2000))
        g.write(ACTOR + LIFE, struct.pack('<H', 130))
        if g.value(p2 + LIFE, 2) < 50: g.write(p2 + LIFE, struct.pack('<H', 130))
        if switch_frame is None and g.log().count(switched) >= wanted: switch_frame = frame(g)
        if switch_frame is not None and frame(g) - switch_frame >= ko_after: break
        if frame(g) - f0 > 40000: raise AssertionError('she never switched')
        if g.value(STATE) != 8: raise AssertionError('the fight ended')
    if timeout:
        # The clock runs out (Tekken Ball: the ball is not aimed).
        g.q(cmd='input_route_stop')
        g.write(CLOCK, struct.pack('<I', 30))
    else:
        # Player 1 knocks player 2 out (the CPU: her, or her opponent): one point left.
        g.write(p2 + LIFE - 2, struct.pack('<i', 1 << 16))
    # Until the replay starts, the fight's last frames are read again and
    # again (Tekken Ball's comes right after the KO).
    end, fight, knocked = time.monotonic() + 120, None, timeout
    while True:
        if time.monotonic() > end: raise AssertionError('no replay played')
        if not knocked:
            knocked = not g.value(p2 + LIFE - 2, 4)
            if knocked: g.q(cmd='input_route_stop')
            else:
                if not g.q(cmd='input_route_status').get('active'): route(g, LAP)
                g.write(ACTOR + LIFE, struct.pack('<H', 130))
        frames = ring(g, side)
        mem = memory(g, spans(frames))
        log = g.log()
        if replay_vars(g)[0] != RECORDING: break
        fight = frames, mem, log
    switches_fight = fight[2].count(switched) if fight else 0
    if fight is None: raise AssertionError('the replay started before a read')
    frames, mem0, log0 = fight
    packs0, ranges = loads(log0, side), spans(frames)
    # The replay: each frame played since the last read checked against the fight's memory.
    shown, previous, end = {}, None, time.monotonic() + 60
    while time.monotonic() < end:
        state, _, played = replay_vars(g)
        if state != PLAYING:
            if shown: break
            continue
        if l1_in_replay and previous is None: g.q(cmd='press', buttons=L1, frames=2)
        mem, packs = memory(g, ranges), loads(g.log(), side)
        ks = [played] if previous is None else \
             [k % FRAMES for k in range(previous + 1, played + 1 + (FRAMES if played < previous else 0))]
        for k in ks:
            f, ok = frames[k], same(mem0, mem, frames[k])
            shown[k] = (style(packs0, f[0]), style(packs, f[0]) if ok else 'other memory', ok)
        previous = played
    return shown, switches_fight, g.log()[len(log0):].count(switched)


def runs_of(shown):
    """[first, last, fight style, replay style] over consecutive frames played."""
    out = []
    for k, (a, b, _) in shown.items():
        if out and out[-1][2:] == [a, b] and k == (out[-1][1] + 1) % FRAMES: out[-1][1] = k
        else: out.append([k, k, a, b])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--mode', choices=tuple(MODES), default='arcade')
    ap.add_argument('--side', type=int, choices=(1, 2), default=2)
    ap.add_argument('--timeout', action='store_true', help='end the round on the clock (Tekken Ball: always)')
    ap.add_argument('--ko-after', type=int, default=150, help='game frames from her first switch to the KO')
    ap.add_argument('--switch', default='300,1,100000', help='TEKKEN3_UNKNOWN_CPU_SWITCH')
    ap.add_argument('--switches', type=int, default=1, help='--side 1: L1 until she has switched that many times')
    ap.add_argument('--l1-in-replay', action='store_true', help='--side 1: L1 pressed as the replay starts')
    ap.add_argument('--runs', type=int, default=1)
    a = ap.parse_args()
    build = (ROOT / a.build).resolve()
    unknown = tw.unknown_id(build)
    failures = []
    for n in range(a.runs):
        g = tw.Game(build, f'b137-{a.mode}-side{a.side}-{n}',
                    env={'TEKKEN3_UNKNOWN_WOLF': '0', 'TEKKEN3_UNKNOWN_CPU_SWITCH': a.switch})
        try:
            to_fight(g, a.mode, a.side, unknown)
            shown, switches_fight, switches_replay = run(g, a.side, a.ko_after, a.timeout, a.switches, a.l1_in_replay)
        finally:
            g.stop()
        wrong = [k for k, (_, _, ok) in shown.items() if not ok]
        print(f'run {n}: {switches_fight} switches in the fight, {switches_replay} during the replay; '
              f'{len(shown)} of {FRAMES} frames played checked, {len(wrong)} with their pack changed')
        for first, last, fought, replayed in runs_of(shown):
            print(f'  frames {first:3}..{last:3}: fight {fought:12} replay {replayed}')
        if switches_replay: failures.append(f'run {n}: {switches_replay} switches during the replay')
        if wrong: failures.append(f'run {n}: {len(wrong)} replayed frames show another pack than the fight')
        if len(shown) < MIN_CHECKED: failures.append(f'run {n}: only {len(shown)} replay frames checked')
    for f in failures: print('FAIL:', f)
    print('OK' if not failures else 'FAILED')
    sys.exit(1 if failures else 0)


main()
