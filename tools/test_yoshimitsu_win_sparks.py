#!/usr/bin/env python3
"""Yoshimitsu's win poses light their effect on the blade (B48, B60, GH#73).

    python tools/test_yoshimitsu_win_sparks.py --build build-rel-lite [--moves ttt1|t3]
        [--fighter yoshimitsu|unknown] [--button square|triangle|cross|circle] [--trace] [--tag NAME]

Cold start. Yoshimitsu: Arcade selector, player 1 takes him
(TEKKEN3_NATIVE_MOVES=1 puts him on his TTT1 moves, 0 on T3's). Unknown: the
Tag page, against a still Jin, on Yoshimitsu's moves
(TEKKEN3_TETSUJIN_MOVESET=yoshimitsu). Once the round runs, player 2's life
goes to 0 and --button is held through the K.O. and the replay: it picks the
win pose. The pose's timed properties 6..10 (T3 0x800458C8) light an effect
at the world position of the bone in their argument (actor + 0x908 + 68 * bone).

TTT1's poses (Square, Triangle, Cross; Circle lights nothing) light the
player's strong-hit effect on point 22 at frames 190 / 205, the tip of
Yoshimitsu's sword in TTT1 (fighter + 0xA8C + 22 * 0x50), of Unknown's blade
on her (100, 0, 727 in her hand bone 10). Yoshimitsu's T3 model has the tip
as bone 18 (the middle of the blade 19), which his own T3 poses light at the
same frames; Unknown has no bone there. Bones 20..23 stay at (0, 0, 0), the
arena's centre, where the TTT1 poses lit theirs. The bench samples the actor
once per read (record, frame, bones), finds the effect in the slot
0x80076884 fills (0x800A3408, position << 7 at +0x24) and prints how long it
stays on the blade, the segment from the hand (bone 10) to the tip. It fails
when the effect is not on the sword (300 to 1200 units from the hand). On
T3's moves it prints his own pose as the reference. --trace writes every
sample to <tag>-trace.csv.

Triangle plays the sitting pose (TTT1 0x1293, T3 0xD68), the same animation
in both games: a forward cut (frames 184..191), the blade held out until 206,
then whipped back. The arcade starts the next round at its frame 201, before
its effect at 205; T3 lights it at 205 and the spark stayed in the air as the
blade went back. On TTT1 moves it lights at 191, as the cut arrives: the
bench fails at any other frame.
"""
import argparse, os, shutil, socket, struct, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_devil_jin as T
import test_guest_accessories as A

T.WORK = ROOT / 'workspace/yoshimitsu-win-sparks'
YOSHIMITSU, HAND = 4, 10
BONES, BONE = 0x8f4, 68                 # bone matrices; translation at +0x14
SHOTS = tuple(int(x) for x in os.environ.get('B48_SHOTS', '3,8,14').split(','))   # frames after the effect
BUTTONS = dict(square=T.pad(T.SQ), triangle=T.pad(T.TR), cross=T.pad(T.CR), circle=T.pad(T.CI))


class Game(T.Game):
    """T.Game run from the build folder itself (Windows: no symbolic links
    without developer mode), cards in a fresh folder, headless software
    renderer. The build's settings.toml stays as it is."""
    def __init__(self, build, tag, env=None):
        cards = T.WORK / f'cards-{os.getpid()}-{tag}'
        shutil.rmtree(cards, ignore_errors=True); cards.mkdir(parents=True)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); self.port = listener.getsockname()[1]
        self.log_path = T.WORK / f'{tag}.log'
        full = {k: v for k, v in os.environ.items() if not k.startswith('TEKKEN3_')}
        full.update(env or {}); full['SDL_AUDIO_DRIVER'] = 'dummy'
        exe = next(p for p in (build / 'Tekken_3_Expanded.exe', build / 'Tekken_3_Expanded') if p.is_file())
        args = [str(exe), '--game', str(ROOT / 'game.toml'), '--disc', str(ROOT / 'disc/Tekken 3 (USA).cue'),
                '--no-launcher', '--renderer', 'software', '--headless',
                '--debug-port', str(self.port), '--memcard-dir', str(cards)]
        with self.log_path.open('w') as out:
            self.process = subprocess.Popen(args, cwd=ROOT, stdout=out, stderr=out, env=full)
        self.run, self.tag = cards, tag
        deadline = time.monotonic() + float(os.environ.get('GAME_START_TIMEOUT', 60))
        while True:
            if self.process.poll() is not None: raise RuntimeError(f'game exited; see {self.log_path}')
            try:
                with socket.create_connection(('127.0.0.1', self.port), .2): break
            except OSError:
                if time.monotonic() > deadline: raise RuntimeError('debug endpoint did not start')
                time.sleep(.1)

    def read(self, a, n):
        return bytes.fromhex(self.q(cmd='read_ram', addr=f'{a:08x}', len=n)['hex'])

    def write(self, a, v, n=4):
        self.q(cmd='write_ram', addr=f'{a:08x}', bytes=(v & (1 << 8 * n) - 1).to_bytes(n, 'little').hex())


SWORD = (18, 19, 22, 23)                # T3 and TTT1 points of the sword (others: other moves' effects)


def effect_props(g, record):
    """(frame, kind, bone) of the record's effect properties 6..10 on the sword."""
    p = struct.unpack('<I', g.read(record + 32, 4))[0]
    out = []
    if not (0x80000000 <= p < 0x80200000 or 0x9f000000 <= p < 0xa0000000): return out
    for frame, op in struct.iter_unpack('<HH', g.read(p, 4 * 32)):
        if not frame: break
        if 6 <= op >> 8 <= 10 and op & 255 in SWORD: out.append((frame, op >> 8, op & 255))
    return out


SNAPSHOT = BONES + 24 * BONE             # the actor up to its 24th bone, read at once (one frame)


def bone(snap, b):
    return struct.unpack_from('<3i', snap, BONES + b * BONE + 0x14)


def hand_frame(snap):
    """Hand bone 10: rotation (rows, 4.12) and translation."""
    return struct.unpack_from('<9h', snap, BONES + HAND * BONE), bone(snap, HAND)


def in_hand_space(snap, point):
    r, t = hand_frame(snap)
    d = [point[i] - t[i] for i in range(3)]
    # The engine's matrix maps the bone's local axes to world (v = R l + t):
    # the transpose takes a world offset back to the hand's frame.
    return tuple(round(sum(r[j * 3 + i] * d[j] for j in range(3)) / 4096) for i in range(3))


SITTING_CUT = 191                      # the sitting pose's effect frame (src: WIN_SITTING_CUT)
BLADE_TIP = (100, 0, 727)              # Unknown's blade tip in her hand bone 10 (limb_position)
EFFECTS, EFFECT, EFFECT_COUNT = 0x800a3408, 64, 3    # 0x80076884's slots: position << 7 at +0x24
ON_BLADE = 150                         # spark to blade distance that still reads "on the blade"


def effects(g):
    raw = g.read(EFFECTS, EFFECT * EFFECT_COUNT)
    return [tuple(v >> 7 for v in struct.unpack_from('<3i', raw, k * EFFECT + 0x24)) for k in range(EFFECT_COUNT)]


def to_blade(snap, spark, tip):
    """Distance from the spark to the blade, the segment hand -> tip."""
    h = bone(snap, HAND)
    d = [tip[i] - h[i] for i in range(3)]
    v = [spark[i] - h[i] for i in range(3)]
    t = max(0.0, min(1.0, sum(d[i] * v[i] for i in range(3)) / (sum(x * x for x in d) or 1)))
    return sum((v[i] - t * d[i]) ** 2 for i in range(3)) ** .5


def point(snap, local):
    """World position of a point given in the hand bone's frame."""
    r, t = hand_frame(snap)
    return tuple(t[i] + round(sum(r[i * 3 + j] * local[j] for j in range(3)) / 4096) for i in range(3))


def start_native(g, ttt1):
    T.to_selector(g)
    T.cursor_to(g, YOSHIMITSU)
    g.press(T.SQUARE, frames=12)
    def step():
        if g.value(T.STATE) == 9: g.press(T.SQUARE, frames=12)
    g.wait(lambda: g.value(T.STATE) == 8 and g.value(T.PHASE, 2) >= 8, 'round did not start', 150, step)
    assert T.actor(g, 0)[2] == YOSHIMITSU, f'P1 is {T.actor(g, 0)[2]}'
    if ttt1: assert 'P1 Yoshimitsu on the TTT1 moveset' in g.log_path.read_text(errors='replace'), 'not on his TTT1 moves'


def start_guest(g, key, build):
    """Tag page (R2), the guest on player 1 against a still Jin
    (tools/test_guest_accessories.py), on Yoshimitsu's moves
    (TEKKEN3_TETSUJIN_MOVESET, set by main)."""
    catalogue = [l.split()[0] for l in (build / 'mods/ttt1/guests.txt').read_text().splitlines() if l.split()]
    A.to_tag_page(g, len(catalogue))
    A.fight(g, catalogue.index(key), len(catalogue), 1)
    assert 'yoshimitsu' in g.log_path.read_text(errors='replace').lower(), "not on Yoshimitsu's moves"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', required=True)
    ap.add_argument('--moves', choices=('ttt1', 't3'), default='ttt1')
    ap.add_argument('--fighter', choices=('yoshimitsu', 'unknown', 'tetsujin'), default='yoshimitsu',
                    help="a guest on Yoshimitsu's moves instead of the native")
    ap.add_argument('--button', choices=BUTTONS, default='square')
    ap.add_argument('--trace', action='store_true', help='write every sample of the pose to <tag>-trace.csv')
    ap.add_argument('--tag', default=None)
    a = ap.parse_args()
    T.WORK.mkdir(parents=True, exist_ok=True)
    build = Path(a.build).resolve()
    guest = a.fighter != 'yoshimitsu'
    env = {'TEKKEN3_TETSUJIN_MOVESET': 'yoshimitsu'} if guest else {'TEKKEN3_NATIVE_MOVES': '1' if a.moves == 'ttt1' else '0'}
    tag = a.tag or (f'{a.fighter}-{a.button}' if guest else f'{a.moves}-{a.button}')
    g = Game(build, tag, env)
    actor = T.ACTOR
    trace = (T.WORK / f'{tag}-trace.csv').open('w') if a.trace else None
    if trace: trace.write('record,frame,bone18,bone22,hand,tip18_in_hand,tip22_in_hand,blade_tip\n')
    try:
        if guest: start_guest(g, a.fighter, build)
        else: start_native(g, a.moves == 'ttt1')
        time.sleep(1.5)
        g.q(cmd='write_ram', addr=f'{T.ACTOR + T.STRIDE + T.LIFE:08x}', bytes='0000')
        g.q(cmd='press', buttons=BUTTONS[a.button], frames=60 * 32)
        seen, fired, end = {}, [], time.monotonic() + 35
        last, shots, before = None, [], None    # pictures of the effect, a few frames on
        while time.monotonic() < end:
            snap = g.read(actor, SNAPSHOT)
            record, frame = struct.unpack_from('<Ih', snap, 0x54)
            if record not in seen:
                seen[record] = effect_props(g, record)
                print(f'record {record:08X} effect properties {seen[record]}')
            # Unknown's blade has no bone: the tip is a point of her hand.
            tip = point(snap, BLADE_TIP) if guest else bone(snap, 18)
            if trace and (record, frame) != last:
                b18, b22 = bone(snap, 18), bone(snap, 22)
                cells = [b18, b22, bone(snap, HAND), in_hand_space(snap, b18), in_hand_space(snap, b22),
                         point(snap, BLADE_TIP)]
                trace.write(f'{record:08X},{frame},' + ','.join(' '.join(map(str, c)) for c in cells) + '\n')
            for f, kind, b in seen[record]:
                key = (record, f)
                if key in {x['key'] for x in fired}: continue
                if f - 8 <= frame < f: before = effects(g)
                elif before and f <= frame <= f + 4:
                    new = [e for e, o in zip(effects(g), before) if e != o]
                    if not new: continue
                    pos = new[0]
                    local = in_hand_space(snap, pos)
                    fired.append(dict(key=key, kind=kind, bone=b, pos=pos, local=local, frame=frame, on=[]))
                    shots += [(record, f, f + d) for d in SHOTS]
                    print(f'  frame {frame} (property at {f}) kind {kind} bone {b}: effect at {pos}, '
                          f'hand {bone(snap, HAND)}, in the hand frame {local}')
            for x in fired:
                if x['key'][0] == record and x['frame'] <= frame <= x['key'][1] + 30 and frame not in {o[0] for o in x['on']}:
                    x['on'].append((frame, to_blade(snap, x['pos'], tip)))
            for shot in [x for x in shots if x[0] == record and frame >= x[2]]:
                g.shot(f'{shot[1]}+{shot[2] - shot[1]:02d}'); shots.remove(shot)
            last = (record, frame)
        if not fired: raise SystemExit(f'FAIL: no effect property fired (last {last}); try another --button')
        for x in fired:
            on = sorted(x['on'])
            gone = next((fr for fr, d in on if d > ON_BLADE), None)
            x['until'] = gone
            print(f'  effect of frame {x["key"][1]}: on the blade (< {ON_BLADE}) until frame '
                  f'{gone if gone is not None else "> " + str(x["key"][1] + 30)}; distances '
                  + ' '.join(f'{fr}:{d:.0f}' for fr, d in on))
        bad = [x for x in fired if not 300 < sum(v * v for v in x['local']) ** .5 < 1200]
        if a.moves == 't3' and not guest: return
        if bad: raise SystemExit(f'FAIL: effect away from the blade: {bad}')
        sitting = [x for x in fired if x['key'][1] != SITTING_CUT] if a.button == 'triangle' else []
        if sitting: raise SystemExit(f'FAIL: the sitting pose lights its effect at frame {sitting[0]["key"][1]}, '
                                     f'not as the cut arrives ({SITTING_CUT})')
        print('PASS: every effect of the pose lights on the blade')
    finally:
        if trace: trace.close()
        g.q(cmd='clear_input') if g.process.poll() is None else None
        g.stop()


if __name__ == '__main__':
    main()
