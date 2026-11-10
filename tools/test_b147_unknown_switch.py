#!/usr/bin/env python3
"""B147 (GH#198): Unknown's style switch (L1) must leave her opponent alone.

    python tools/test_b147_unknown_switch.py [--build build-rel-lite] [--data <install>/mods]
           [--case juggle|stun|back|all|ko] [--trials 3] [--exe EXE] [--film DIR] [--shots DIR]
    python tools/test_b147_unknown_switch.py --case ko [--juggle | --timeout]

Practice from a cold start, Unknown written for player 1 at the selector and
started on Jin's moveset (TEKKEN3_TETSUJIN_MOVESET=Jin), the dummy standing,
700 apart. L1 every third frame from the attack on, until she switches (her
stance record moves to her other area); both fighters read on every request.

- juggle: u/f+4 launches the dummy (Jin's pack record 0x22C3 while he flies);
- stun: crouch dash + 2 (record 0x22C1, a long stun);
- back: her facing turned half a turn in her stance, then L1: she must stay
  turned away (TTT PS2 / PS3; transition 6 of TTT1's switch rule);
- ko (Arcade): the CPU left a point and knocked out (--timeout: the clock runs
  out, her in her stance), then L1 until the replay: no switch. --juggle: a
  switch with the CPU flying on her pack, then his life taken: the K.O. fall
  and its replay must never show a stray record nor the round start's moves.
  Arcade is noisy (the CPU guards): up to 12 tries a switch in the air.

Past each switch, 150 frames of the dummy (+0x54 record, +0xA0 move, +0xF68
root): fails on a move from her old pack to her new one, a jump over 400
units on the ground plane between two reads, alias 0..2 (the round start) or
a frame counter that stops. Before B147 (dev 466d5f60, --exe): the dummy
stuck on its record, sent to alias 0 or to a stray pointer (FE850386); she
turned to face him. After: clean, and switches with him on her old pack.

--data: the mods folder of an install (the TTT1 catalogue, read through a view
of the build). --exe: another executable of the same build (before / after).
--film: each trial filmed every frame into DIR/<case>-<n> (raw BGRA, take.json
with the switch's film frame): needs the local film patch of the debug
server (side-session notes, b130-film-patch.diff), never committed.
`probe` (first argument): the candidate launchers, the dummy read each frame.
Build: rel-lite (debug server lite).
"""
import argparse, os, re, shutil, struct, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_unknown_wolf as tw
tw.WORK = ROOT / 'out/b147'
LINE, PRACTICE_LINE = 0x80097f40, 8
CHOICE_P1 = (0x80118688, 0x80118690)       # Practice: player 1's confirmed choice (tools/ttt1/balance.py)
LIFE = 0x3f6
START, CROSS = 0xfff7, 0xbfff

DATA = 'C:/Users/omarm/Desktop/Tekken3Expanded-1.4.1-Windows/tekken3-expanded-1.4.1/build-release/mods'
FROM_DATA = ('ttt1', 'arcade-stages', 'ttt-stages', 'ttt-cinematics', 'ttt-music', 'ttt-ps2-music', 'ttt-ps2-laser')
STATE, PHASE = tw.STATE, tw.PHASE
P1, P2 = tw.ACTOR, tw.ACTOR + tw.STRIDE
ACTOR = P1
NONE, L1 = 0xffff, 0xfbff
UP, RIGHT, DOWN, LEFT = 0xffef, 0xffdf, 0xffbf, 0xff7f
B1, B2, B3, B4 = 0x7fff, 0xefff, 0xbfff, 0xdfff


# From tools/test_unknown_switch.py (which runs its checks on import).
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


def into_freestyle(g):
    """Practice opens on MODE SELECT, then 1P FREESTYLE: Cross, then a step forward until player 1 moves."""
    for _ in range(12):
        x = actor(g, P1)['pos'][0]
        route(g, [(RIGHT, 12), (NONE, 20)]); wait_route(g)
        if actor(g, P1)['pos'][0] != x: return
        g.press(CROSS); time.sleep(1)
    raise AssertionError('player 1 never moved: still in the Practice menus')


def view_of(build, data, tag, exe=None):
    """The build's executable, BIOS and mods files, the data folders of the install."""
    view = tw.WORK / f'view-{os.getpid()}-{tag}'
    shutil.rmtree(view, ignore_errors=True); (view / 'mods').mkdir(parents=True)
    junction = lambda link, target: subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                                                   check=True, capture_output=True)
    for p in (build / 'mods').iterdir():
        if p.is_file(): shutil.copy2(p, view / 'mods' / p.name)
        elif p.name not in FROM_DATA: junction(view / 'mods' / p.name, p)
    for name in FROM_DATA:
        if (data / name).is_dir(): junction(view / 'mods' / name, data / name)
    built = next(p for p in (build / 'Tekken_3_Expanded.exe', build / 'Tekken_3_Expanded') if p.exists())
    shutil.copy2(exe or built, view / built.name)
    junction(view / 'bios', build / 'bios')
    return view


def drop_view(view):
    for p in list((view / 'mods').iterdir()) + [view / 'bios']:
        if p.is_dir(): subprocess.run(['cmd', '/c', 'rmdir', str(p)], capture_output=True)
    shutil.rmtree(view, ignore_errors=True)


def packs(log):
    """[(style, records base)] of each pack player 1 installed, in order."""
    out, style = [], 'start'
    for line in log.splitlines():
        m = re.search(r'P1 Unknown (?:switches to|starts on) (?:Unknown@)?(\w+)', line)
        if m: style = m.group(1)
        m = re.search(r'installed P1 alias table, .* records=([0-9A-F]{8})', line)
        if m: out.append((style, int(m.group(1), 16)))
    return out


def actor(g, a):
    """The fighter's move and its body's place (+0xF68, the root: +0 is the move's anchor)."""
    b = g.read(a, 0xf74)
    x, y, z = struct.unpack_from('<iii', b, 0xf68)
    return dict(pos=(x, y, z), anchor=struct.unpack_from('<iii', b, 0), record=struct.unpack_from('<I', b, 0x54)[0], frame=struct.unpack_from('<H', b, 0x58)[0],
                move=struct.unpack_from('<H', b, 0xa0)[0], angle=struct.unpack_from('<H', b, 0x30)[0],
                rot=struct.unpack_from('<H', b, 0xe)[0], angle_opp=struct.unpack_from('<H', b, 0x2a)[0], transition=struct.unpack_from('<H', b, 0x19a)[0],
                next=struct.unpack_from('<I', b, 0x1a4)[0])


def wait_route(g):
    while g.q(cmd='input_route_status').get('active'): time.sleep(.03)


def l1_until_switch(g, frames=60):
    n = g.log().count('P1 Unknown switches to')
    route(g, [(L1, 1), (NONE, 2)] * (frames // 3))
    end = time.monotonic() + frames / 30 + 2
    while time.monotonic() < end:
        if g.log().count('P1 Unknown switches to') > n:
            g.q(cmd='input_route_clear'); return True
        time.sleep(.01)
    return False


def watch(g, frames, shots=None, tag=''):
    """Samples of the dummy (and of her) for `frames` game frames."""
    rows, f0, last_f, still = [], frame(g), None, 0
    while True:
        f = frame(g)
        if f - f0 >= frames: break
        if f == last_f:
            still += 1
            if still > 400: rows.append(('frozen', f)); break
        else: still = 0
        last_f = f
        rows.append((f - f0, actor(g, P2), actor(g, P1)))
        if shots and len(rows) % 8 == 1: g.shot(shots / f'{tag}-{len(rows):03d}.png')
    return rows


def judge(rows, old, new):
    """Faults of a switch: (old pack base, size guess), (new base)."""
    faults = []
    def owner(r):
        for name, (lo, hi) in (('old', old), ('new', new)):
            if lo <= r < hi: return name
        return 'other'
    prev = None
    for row in rows:
        if row[0] == 'frozen': faults.append(f'game frozen at frame {row[1]}'); break
        f, d, u = row
        if prev:
            # On the ground plane: a fall moves y by 300 a sample.
            jump = max(abs(d['pos'][k] - prev['pos'][k]) for k in (0, 2))
            if jump > 400: faults.append(f'f{f}: dummy jumps {jump} units')
            if d['move'] < 3 and prev['move'] >= 3:
                faults.append(f'f{f}: dummy on move {d["move"]} (the round start)')
            if owner(prev['record']) == 'old' and owner(d['record']) == 'new':
                faults.append(f'f{f}: dummy from her old pack ({prev["record"]:08X}) to her new one ({d["record"]:08X})')
        prev = d
    return faults


def show(rows, every=5):
    for row in rows[::every]:
        if row[0] == 'frozen': print('   frozen'); continue
        f, d, u = row
        print(f'   f{f:3d} dummy rec {d["record"]:08X} fr {d["frame"]:3d} move {d["move"]:04X} pos {d["pos"]} '
              f'anchor {d["anchor"]} | her rec {u["record"]:08X} move {u["move"]:04X} rot {u["rot"]:04X}')


def place(g):
    """Both back in place, 700 apart, facing each other, still."""
    a, b = actor(g, P1), actor(g, P2)
    g.write(P1, struct.pack('<i', -350)); g.write(P1 + 8, struct.pack('<i', 0))
    g.write(P2, struct.pack('<i', 350)); g.write(P2 + 8, struct.pack('<i', 0))
    time.sleep(.5)


FILM = None          # --film: each trial filmed, every frame (local film patch of the debug server)


def film_start(g, name):
    if not FILM: return
    d = FILM / name
    shutil.rmtree(d, ignore_errors=True); d.mkdir(parents=True)
    g.q(cmd='film', dir=d.as_posix(), frames=100000)


def film_mark(g):
    return g.q(cmd='film')['written'] if FILM else -1


def film_stop(g, name, meta):
    if not FILM: return
    import json
    g.q(cmd='film', dir=(FILM / name).as_posix(), frames=0)
    (FILM / name / 'take.json').write_text(json.dumps(meta))


def trial(g, name, steps, shots, verbose=False):
    """Inputs `steps`, then L1 every third frame until she switches (her
    stance record moves to her other area), the two read on every request
    from the attack on; 150 frames watched past the switch."""
    base = len(packs(g.log()))
    first = actor(g, P1)['record']
    film_start(g, name)
    route(g, steps + [(L1, 1), (NONE, 2)] * 30)
    mark = None
    rows, f0, switched, still, last = [], frame(g), None, 0, None
    while True:
        f = frame(g)
        if f == last:
            still += 1
            if still > 400: rows.append(('frozen', f)); break
        else: still = 0
        last = f
        d, u = actor(g, P2), actor(g, P1)
        rows.append((f - f0, d, u))
        if switched is None and abs(u['record'] - first) > 0x40000:
            switched = len(rows) - 1; g.q(cmd='input_route_clear')     # one switch
            mark = film_mark(g)
        if shots and switched is not None and (len(rows) - switched) % 8 == 1:
            g.shot(shots / f'{name}-{len(rows) - switched:03d}.png')
        if switched is not None and f - rows[switched][0] - f0 >= 150: break
        if switched is None and f - f0 > 300: break
    g.q(cmd='input_route_clear')
    if switched is None: return [f'{name}: L1 did not switch her']
    time.sleep(.5)
    p = packs(g.log())
    if len(p) <= base: return [f'{name}: no pack installed after the switch']
    old_base, new_base = p[base - 1][1], p[-1][1]
    span = 0x20000
    def kind(r):
        return 'old' if old_base <= r < old_base + span else 'new' if new_base <= r < new_base + span else 'other'
    at = rows[switched][1]
    print(f'{name}: {p[base - 1][0]} -> {p[-1][0]} at f{rows[switched][0]}; the dummy then on '
          f'{at["record"]:08X} ({kind(at["record"])}) move {at["move"]:04X} frame {at["frame"]}')
    on_old = sum(1 for r in rows[switched:] if r[0] != 'frozen' and kind(r[1]['record']) == 'old')
    print(f'   samples past the switch with the dummy on her old pack: {on_old}')
    if verbose: show(rows[max(0, switched - 6):switched + 30], 1)
    faults = judge(rows[max(0, switched - 1):], (old_base, old_base + span), (new_base, new_base + span))
    film_stop(g, name, {'switch': mark, 'dummy': kind(at['record']), 'faults': faults})
    return [f'{name}: {x}' for x in faults], kind(at['record'])



def turned_away(u):
    """Her facing off the opponent's direction, in degrees (180: back to him)."""
    d = (u['rot'] - u['angle_opp']) & 0xffff
    return round(min(d, 0x10000 - d) * 360 / 0x10000)


def back_trial(g, name):
    """Her back to the dummy (her facing turned half a turn in her stance),
    then L1: her facing over the next 60 frames."""
    time.sleep(.5)
    u = actor(g, P1)
    back = (u['angle_opp'] + 0x8000) & 0xffff
    for off in (0xe, 0x2c, 0x34): g.write(P1 + off, struct.pack('<H', back))
    time.sleep(.5)
    held = turned_away(actor(g, P1))
    first = actor(g, P1)['record']
    film_start(g, name); mark = None
    route(g, [(L1, 1), (NONE, 2)] * 20)
    f0, switched, seen = frame(g), None, []
    while frame(g) - f0 < 200:
        u = actor(g, P1)
        if switched is None and abs(u['record'] - first) > 0x40000:
            switched = frame(g); g.q(cmd='input_route_clear'); mark = film_mark(g)
        if switched is not None:
            seen.append((frame(g) - switched, turned_away(u), u['transition']))
            if frame(g) - switched > 60: break
    g.q(cmd='input_route_clear')
    if switched is None: return [f'{name}: L1 did not switch her']
    print(f'{name}: turned away {held} deg before L1; after the switch (frame, deg, her +0x19A): '
          f'{seen[:3]} ... {seen[-1]}')
    film_stop(g, name, {'switch': mark, 'held': held, 'after': [d for _, d, _ in seen]})
    if held < 150: return [f'{name}: could not turn her back ({held} deg)']
    worst = min(d for _, d, _ in seen)
    return [f'{name}: she turned to face him after the switch ({worst} deg)'] if worst < 150 else []


# From tools/test_b137_unknown_replay.py (which runs its checks on import).
MODE, BLOCKS, SQUARE = 0x800afa88, 0x800b8d70, 0x7fff
MODES = {'arcade': (0, 0), 'timeattack': (4, 3), 'survival': (5, 4), 'ball': (6, 7)}   # menu line, mode
ROUND_END_FLAGS = 0x800ade78                     # 1 time, 2 K.O., 4 double K.O., 8 perfect, 0x10 great
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
    g.wait(lambda: g.value(P1 + (side - 1) * tw.STRIDE + 0x18, 2) == unknown, f'Unknown is not P{side}', 30)


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


def ko_run(g, tries, timeout=False):
    """Arcade, the CPU left a point: Unknown knocks him out, then L1 every
    third frame until the replay: no switch from the K.O. on (1.3). Before
    B147: a switch in the K.O. fall, the fallen CPU sent into the new pack."""
    faults = []
    for t in range(tries):
        g.wait(lambda: g.value(STATE) == 8 and g.value(PHASE, 2) >= 8 and not g.value(ROUND_END_FLAGS, 2) & 0x1f,
               'next round', 120)
        time.sleep(1)
        g.write(P2 + LIFE - 2, struct.pack('<i', 1 << 16))
        DF = DOWN & RIGHT
        end = time.monotonic() + 30
        if timeout:                  # she stands in her stance as the clock runs out
            g.write(0x800adbcc, struct.pack('<I', 40))
        while timeout and not g.value(ROUND_END_FLAGS, 2) & 0x1f:
            g.write(P1 + LIFE, struct.pack('<H', 130))
            if time.monotonic() > end: return faults + [f'ko-{t + 1}: no time out']
        while not g.value(ROUND_END_FLAGS, 2) & 0x1f:
            if time.monotonic() > end: return faults + [f'ko-{t + 1}: no K.O.']
            g.write(P1 + LIFE, struct.pack('<H', 130)); g.write(0x800adbcc, struct.pack('<I', 2000))
            g.write(P2 + LIFE - 2, struct.pack('<i', min(g.value(P2 + LIFE - 2), 1 << 16)))
            if not g.q(cmd='input_route_status').get('active'):
                route(g, [(RIGHT, 8), (UP & RIGHT & B4, 3), (NONE, 20), (B1, 3), (NONE, 8)])
            time.sleep(.03)
        g.q(cmd='input_route_clear')
        n = g.log().count('P1 Unknown switches to')
        route(g, [(L1, 1), (NONE, 2)] * 100)
        f0 = frame(g)
        trace = []
        while frame(g) - f0 < 300 and g.value(0x8009bca8) not in range(1, 7):
            u, d = actor(g, P1), actor(g, P2)
            k = (u['move'], d['move'], g.value(PHASE, 2), g.value(0x8009bca8))
            if not trace or trace[-1][1:] != k: trace.append((frame(g) - f0,) + k)
        print(f'ko-{t + 1}: (frame, her move, his move, phase, replay state): {trace}')
        g.q(cmd='input_route_clear')
        after = g.log().count('P1 Unknown switches to') - n
        print(f'ko-{t + 1}: K.O. (flags {g.value(ROUND_END_FLAGS, 2):#x}); switches from the K.O. to the replay: {after}')
        if after: faults.append(f'ko-{t + 1}: {after} switch(es) after the K.O.')
        g.wait(lambda: g.value(PHASE, 2) < 6 or g.value(STATE) != 8, 'round end', 120)
    return faults


def valid_record(r):
    return 0x80010000 <= r < 0x80200000 or 0x9f000000 <= r < 0xa0000000


def juggle_ko_run(g, tries):
    """Arcade (1.3 as the player saw it): u/f+4 launches the CPU, L1 until she
    switches with him in the air on her pack, then his life taken: the K.O.
    and its replay play his fall. Every frame of both, his record must be a
    record (not a stray pointer) and never the round start's moves."""
    faults, done = [], 0
    for t in range(tries * 12):
        if done == tries: break
        g.wait(lambda: g.value(STATE) == 8 and g.value(PHASE, 2) >= 8 and not g.value(ROUND_END_FLAGS, 2) & 0x1f,
               'next round', 120)
        time.sleep(.7)
        g.write(P1, struct.pack('<i', actor(g, P2)['anchor'][0] - 700)); g.write(P1 + 8, struct.pack('<i', actor(g, P2)['anchor'][2]))
        first = actor(g, P1)['record']
        film_start(g, f'juggle-ko-{t + 1}'); mark = None
        route(g, [(UP & RIGHT & B4, 3), (NONE, 6)] + [(L1, 1), (NONE, 2)] * 25)
        f0, at = frame(g), None
        while frame(g) - f0 < 120:
            g.write(P1 + LIFE, struct.pack('<H', 130)); g.write(0x800adbcc, struct.pack('<I', 2000))
            u, d = actor(g, P1), actor(g, P2)
            if abs(u['record'] - first) > 0x40000: at = d; mark = film_mark(g); break
        g.q(cmd='input_route_clear')
        if at is None or not 0x9f000000 <= at['record'] < 0xa0000000 or not 0x2000 <= at['move'] < 0x3000:
            print(f'juggle-ko try {t + 1}: no switch with him on her pack ({at and hex(at["record"])})')
            film_stop(g, f'juggle-ko-{t + 1}', {'switch': None}); shutil.rmtree(FILM / f'juggle-ko-{t + 1}', ignore_errors=True) if FILM else None
            time.sleep(3); continue
        done += 1
        g.write(P2 + LIFE - 2, struct.pack('<i', 0))
        seen, bad, replayed = [], [], 0
        f0 = frame(g)
        while frame(g) - f0 < 900:
            state = g.value(0x8009bca8)
            d = actor(g, P2)
            if not g.value(ROUND_END_FLAGS, 2) & 0x1f: break          # the next round
            replayed += 1 <= state <= 6
            if not valid_record(d['record']): bad.append(f'record {d["record"]:08X}')
            elif d['move'] < 3: bad.append(f'move {d["move"]}')
            if g.value(STATE) != 8 or (replayed and not 1 <= state <= 6 and frame(g) - f0 > 200): break
        film_stop(g, f'juggle-ko-{t + 1}', {'switch': mark, 'bad': bad[:20], 'replayed': replayed})
        print(f'juggle-ko {done}: switched with him on {at["record"]:08X} move {at["move"]:04X}; '
              f'{replayed} samples of replay; faults {bad[:5]}')
        if bad: faults.append(f'juggle-ko {done}: {len(bad)} bad samples, first {bad[0]}')
        if not replayed: faults.append(f'juggle-ko {done}: no replay seen')
        g.wait(lambda: g.value(PHASE, 2) < 6 or g.value(STATE) != 8, 'round end', 120)
    if done < tries: faults.append(f'juggle-ko: {done} of {tries} switches in the air')
    return faults

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--data', default=DATA)
    ap.add_argument('--case', default='juggle')
    ap.add_argument('--trials', type=int, default=2)
    ap.add_argument('--shots', type=Path)
    ap.add_argument('--juggle', action='store_true', help='ko: switch in a juggle, then the K.O. and its replay')
    ap.add_argument('--timeout', action='store_true', help='ko: the round ends on time, her in her stance')
    ap.add_argument('--film', type=Path, help='film every trial in DIR/<case>-<n> (needs the local film patch)')
    ap.add_argument('--exe', type=Path, help='another executable of the same build (before / after)')
    a = ap.parse_args()
    global FILM
    FILM = a.film.resolve() if a.film else None
    build, data = (ROOT / a.build).resolve(), Path(a.data).resolve()
    if a.shots: a.shots.mkdir(parents=True, exist_ok=True)
    view = view_of(build, data, a.case, a.exe)
    unknown = tw.unknown_id(view)
    if a.case == 'ko':
        g = tw.Game(view, 'b147-ko', env={'TEKKEN3_UNKNOWN_WOLF': '0', 'TEKKEN3_TETSUJIN_MOVESET': 'Jin'})
        try:
            to_fight(g, 'arcade', 1, unknown)
            faults = juggle_ko_run(g, a.trials) if a.juggle else ko_run(g, a.trials, a.timeout)
        finally:
            g.stop(); drop_view(view)
        print(chr(10).join(faults) or 'OK')
        return 1 if faults else 0
    g = tw.Game(view, f'b147-{a.case}', env={'TEKKEN3_UNKNOWN_WOLF': '0', 'TEKKEN3_TETSUJIN_MOVESET': 'Jin'})
    faults, hits = [], []
    try:
        to_practice(g, unknown); into_freestyle(g)
        DF = DOWN & RIGHT
        cases = ['juggle', 'stun', 'back'] if a.case == 'all' else [a.case]
        for case in cases:
            for t in range(a.trials):
                place(g)
                if case == 'juggle':
                    steps = [(UP & RIGHT & B4, 3), (NONE, 4 + 3 * t)]
                elif case == 'stun':
                    steps = [(RIGHT, 2), (NONE, 2), (DOWN, 2), (DF & B2, 3), (NONE, 4 + 3 * t)]
                elif case == 'back':
                    faults += back_trial(g, f'back-{t + 1}'); time.sleep(2); continue
                else:
                    raise SystemExit(f'unknown case {case}')
                r = trial(g, f'{case}-{t + 1}', steps, a.shots)
                if isinstance(r, tuple): faults += r[0]; hits.append(r[1])
                else: faults += r
                time.sleep(3)
                if g.value(STATE) != 8: faults.append(f'{case}: left the fight (state {g.value(STATE)})'); break
    finally:
        g.stop(); drop_view(view)
    print('\n'.join(faults) or 'OK')
    return 1 if faults else 0




def probe(build, data):
    """Interactive probe: candidate launchers from 800 apart, the dummy read each frame."""
    view = view_of(build, data, 'probe')
    g = tw.Game(view, 'b147-probe', env={'TEKKEN3_UNKNOWN_WOLF': '0', 'TEKKEN3_TETSUJIN_MOVESET': 'Jin'})
    DF = DOWN & RIGHT
    tries = {'df2': [(DF & B2, 3), (NONE, 70)], 'uf4': [(UP & RIGHT & B4, 3), (NONE, 70)],
             'cd2': [(RIGHT, 2), (NONE, 2), (DOWN, 2), (DF & B2, 3), (NONE, 70)],
             'b12': [(B1 & B2, 3), (NONE, 70)], 'ws2': [(DOWN, 20), (B2, 3), (NONE, 70)]}
    try:
        to_practice(g, tw.unknown_id(view)); into_freestyle(g)
        for name, steps in tries.items():
            for dist in (700, 1000):
                g.write(P1, struct.pack('<i', -dist // 2)); g.write(P2, struct.pack('<i', dist // 2))
                time.sleep(.7)
                route(g, steps)
                seen, low, hers, f0 = [], 0, 0, frame(g)
                while frame(g) - f0 < 80:
                    b = g.read(P2, 0x1a8)
                    y = struct.unpack_from('<i', b, 4)[0]; rec = struct.unpack_from('<I', b, 0x54)[0]
                    mv = struct.unpack_from('<H', b, 0xa0)[0]
                    low = min(low, y); hers += rec >= 0x9f000000
                    if not seen or seen[-1] != mv: seen.append(mv)
                print(f'{name} @{dist}: dummy moves {[hex(m) for m in seen]} min y {low} samples on her pack {hers}')
                wait_route(g); time.sleep(1.5)
    finally:
        g.stop(); drop_view(view)

if __name__ == '__main__':
    if sys.argv[1:2] == ['probe']: probe((ROOT / 'build-rel-lite').resolve(), Path(DATA))
    else: sys.exit(main())
