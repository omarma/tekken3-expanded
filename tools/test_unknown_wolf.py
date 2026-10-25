#!/usr/bin/env python3
"""Unknown's wolf spirit in a fight (F08, GH#42).

    python tools/test_unknown_wolf.py [--build build-rel-lite] [--side 1|2|3] [--samples 40]
                                      [--off] [--shots N] [--visible]

Cold start (a blank memory card), Arcade; player 1 takes the fighter under
the cursor (his MOVESET card, if it opens, left on its default), and Unknown
(the guest of the catalogue's guests.txt) is written while the fight loads,
for the CPU (--side 2), for player 1 (--side 1) or for both (--side 3: two
wolves). In the fight, past the intros, the bench samples the game and each
wolf's actor (their addresses from the log):

- pose: the wolf's 18 local bone rotations are Unknown's (0x80169968 takes
  hers each frame), read under the pause menu (between two reads of a
  running game her pose moves on);
- place: its root trails hers by about 800 behind (0x8016968C: target 800
  behind and 150 above, x / 6 and y, z / 8 a frame), on the side away from
  the opponent;
- drawing: its packets read the upper VRAM half (texpage bit 11) additively
  (ABR 1) with the semi-transparent bit, and some are linked in the frame.

--off: TEKKEN3_UNKNOWN_WOLF=0, the same fight without the wolf (the checks then
expect none). --shots N: N captures, a quarter of a second apart, in
out/f08/side<N>[-off]/. Exit status 1 when a check fails.
"""
import argparse, os, re, shutil, socket, struct, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'psxrecomp/tools'))
import debug_client

WORK = ROOT / 'out/f08'
STATE, PHASE, GRID = 0x800ae204, 0x800ae224, 0x80118648
ACTOR, STRIDE = 0x800a9228, 0x188c
LOCALS, ROOT_M = 0xf74, 0xf54
START, CROSS, SQUARE = 0xfff7, 0xbfff, 0x7fff
GUEST_ID, PACKETS = 23, 0x12000


class Game:
    def __init__(self, build, tag, visible=False, env=None,
                 settings='[video]\nsupersampling=1\nantialiasing=false\n', renderer=None):
        run = WORK / f'run-{os.getpid()}-{tag}'
        shutil.rmtree(run, ignore_errors=True); run.mkdir(parents=True)
        built = next(p for p in (build / 'Tekken_3_Expanded.exe', build / 'Tekken_3_Expanded') if p.exists())
        shutil.copy2(built, run / built.name)
        for name in ('bios', 'mods'):       # links, not copies: the catalogue is large
            if os.name == 'nt':
                subprocess.run(['cmd', '/c', 'mklink', '/J', str(run / name), str(build / name)], check=True, capture_output=True)
            else: (run / name).symlink_to(build / name)
        (run / 'settings.toml').write_text(settings + '[controller]\np1_device="keyboard"\np2_device="none"\n')
        cards = run / 'cards'; cards.mkdir()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); self.port = listener.getsockname()[1]
        self.log_path = WORK / f'{tag}.log'
        environ = {k: v for k, v in os.environ.items() if not k.startswith('TEKKEN3_')}
        environ['SDL_AUDIO_DRIVER'] = 'dummy'
        environ.update(env or {})
        args = [str(run / built.name), '--game', str(ROOT / 'game.toml'), '--disc', str(ROOT / 'disc/Tekken 3 (USA).cue'),
                '--no-launcher', '--renderer', renderer or ('opengl' if visible else 'software'), '--debug-port', str(self.port),
                '--memcard-dir', str(cards)] + ([] if visible else ['--headless'])
        self.out = self.log_path.open('w')
        self.process = subprocess.Popen(args, cwd=ROOT, stdout=self.out, stderr=self.out, env=environ)
        self.run = run
        deadline = time.monotonic() + 60
        while True:
            if self.process.poll() is not None: raise RuntimeError(f'game exited; see {self.log_path}')
            try:
                with socket.create_connection(('127.0.0.1', self.port), .2): break
            except OSError:
                if time.monotonic() > deadline: raise RuntimeError('debug endpoint did not start')
                time.sleep(.2)

    def q(self, **r):
        for _ in range(600):
            result = debug_client.query('127.0.0.1', self.port, r)
            if result.get('err') != 'emu busy or frozen': break
            time.sleep(.1)
        if result.get('ok') is False: raise RuntimeError((r, result))
        return result

    def read(self, a, n=4): return bytes.fromhex(self.q(cmd='read_ram', addr=f'{a:08x}', len=n)['hex'])
    def value(self, a, n=4): return int.from_bytes(self.read(a, n), 'little')
    def write(self, a, data): self.q(cmd='write_ram', addr=f'{a:08x}', bytes=data.hex())
    def press(self, b, frames=4): self.q(cmd='press', buttons=b, frames=frames); time.sleep(.25)
    def log(self): return self.log_path.read_text(errors='replace')
    def shot(self, path): self.q(cmd='screenshot', path=str(path))

    def wait(self, predicate, what, seconds=120, step=None):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if predicate(): return
            if step: step()
            time.sleep(.1)
        raise AssertionError(what)

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=10)
            except subprocess.TimeoutExpired: self.process.kill()
        self.out.close()
        for name in ('bios', 'mods'):
            if os.name == 'nt': subprocess.run(['cmd', '/c', 'rmdir', str(self.run / name)], capture_output=True)
            else: (self.run / name).unlink(missing_ok=True)
        shutil.rmtree(self.run, ignore_errors=True)


def unknown_id(build):
    keys = [l.split()[0] for l in (build / 'mods/ttt1/guests.txt').read_text().splitlines() if l.split()]
    return GUEST_ID + keys.index('unknown')


def to_fight(g, sides, unknown):
    """Arcade, player 1 on the fighter under the cursor (Square, then Cross on
    the MOVESET card if it opens), Unknown written for `sides` while the fight
    loads."""
    g.q(cmd='turbo', enabled=1)
    g.wait(lambda: g.value(STATE) == 4, 'mode menu not reached', 240, lambda: g.press(START))
    g.q(cmd='turbo', enabled=0)
    time.sleep(1)
    g.write(0x80097f40, bytes([0]))                 # ARCADE
    g.wait(lambda: g.value(STATE) == 9 and g.value(GRID) == 21, 'selector not reached', 90,
           lambda: (g.press(CROSS), time.sleep(.4)))
    time.sleep(1.5)
    g.q(cmd='turbo', enabled=0)
    # The loading choice (0x800ADD5C + 2 x side) written as soon as the
    # loading screen shows: it may last a few frames only, so the loop polls
    # the state alone and reads the log (the MOVESET card) twice a second.
    confirmed, end, pressed, looked = False, time.monotonic() + 60, 0.0, 0.0
    while True:
        state = g.value(STATE)
        if state == 11: break
        if time.monotonic() > end: raise AssertionError('loading screen not reached')
        if state == 9 and time.monotonic() - looked > .5:
            looked = time.monotonic()
            if 'P1 opens the MOVESET card' in g.log():
                if not confirmed: g.q(cmd='press', buttons=CROSS, frames=4); confirmed = True
            elif time.monotonic() - pressed > 1.5:
                g.q(cmd='press', buttons=SQUARE, frames=4); pressed = time.monotonic()
    for s in sides:
        g.write(0x800add5c + 2 * (s - 1), struct.pack('<H', unknown))
        g.write(0x800add98 + 2 * (s - 1), b'\0\0')
    g.wait(lambda: g.value(STATE) == 8 and g.value(PHASE, 2) >= 6, 'round did not start', 120)
    for s in sides:
        g.wait(lambda: g.value(ACTOR + (s - 1) * STRIDE + 0x18, 2) == unknown, f'Unknown is not P{s}', 30)


def s32(b, o): return struct.unpack_from('<i', b, o)[0]


def place(g, side, wolf):
    """Distance on the floor of the wolf's root from hers, whether it is on the
    side away from the opponent, both roots."""
    her = g.read(ACTOR + (side - 1) * STRIDE + ROOT_M, 0x20)
    other = g.read(ACTOR + (2 - side) * STRIDE + ROOT_M, 0x20)
    w = g.read(wolf + ROOT_M, 0x20)
    r, o, p = ([s32(b, 0x14 + 4 * k) for k in range(3)] for b in (her, other, w))
    f = (o[0] - r[0], o[2] - r[2])
    return ((p[0] - r[0]) ** 2 + (p[2] - r[2]) ** 2) ** .5, (p[0] - r[0]) * f[0] + (p[2] - r[2]) * f[1] < 0, r, p


def packets_check(g, block_address):
    """The wolf's packets (the layout of make_packets): how many, how many
    additive in the upper half with the semi-transparent bit, how many linked."""
    block = g.read(block_address, PACKETS)
    sizes, q, cmds, upper, linked = {4: 32, 5: 40, 6: 40, 7: 52}, 0, 0, 0, 0
    while q + 8 <= len(block):
        tag_word, w1 = struct.unpack_from('<2I', block, q)
        op = w1 >> 24
        if not 0x24 <= op <= 0x3f: q += 32; continue
        tp = struct.unpack_from('<I', block, q + (24 if op >= 0x34 else 20))[0] >> 16
        cmds += 1
        upper += bool(op & 2) and tp & 0x800 and (tp >> 5 & 3) == 1
        linked += tag_word >> 24 != 0
        q += sizes[op >> 3]
    return cmds, upper, linked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--side', type=int, choices=(1, 2, 3), default=2,
                    help="Unknown's side: 2 the CPU, 1 player 1, 3 both (two wolves)")
    ap.add_argument('--samples', type=int, default=40)
    ap.add_argument('--off', action='store_true', help='TEKKEN3_UNKNOWN_WOLF=0')
    ap.add_argument('--shots', type=int, default=0)
    ap.add_argument('--visible', action='store_true')
    a = ap.parse_args()
    build = (ROOT / a.build).resolve()
    sides = (1, 2) if a.side == 3 else (a.side,)
    tag = f'side{a.side}' + ('-off' if a.off else '')
    out = WORK / tag; out.mkdir(parents=True, exist_ok=True)
    env = {'TEKKEN3_WOLF_TRACE': '1'}
    if a.off: env['TEKKEN3_UNKNOWN_WOLF'] = '0'
    g = Game(build, tag, a.visible, env)
    failures = []
    try:
        to_fight(g, sides, unknown_id(build))
        time.sleep(3)                                # past the intros
        m = re.search(r"Unknown's wolf: model \d+ B at ([0-9A-F]+), packets at ([0-9A-F]+), "
                      r"actors at ([0-9A-F]+) ([0-9A-F]+)", g.log())
        wolves = {}
        if a.off:
            if m: failures.append('a wolf with TEKKEN3_UNKNOWN_WOLF=0')
        else:
            if not m: raise AssertionError("no wolf in the log (Unknown's wolf: model ...)")
            packets = int(m.group(2), 16)
            wolves = {s: int(m.group(2 + s), 16) for s in sides}
        same = {s: 0 for s in sides}; near = dict(same); behind = dict(same); n = paused = 0
        drawn = {}
        for i in range(a.samples):
            if wolves and i % 8 == 4:
                # Under the pause menu the game is frozen and still draws them.
                g.press(START); time.sleep(.6)
                for s, w in wolves.items():
                    her, wolf = g.read(ACTOR + (s - 1) * STRIDE + LOCALS, 18 * 32), g.read(w + LOCALS, 18 * 32)
                    same[s] += all(her[b * 32:b * 32 + 18] == wolf[b * 32:b * 32 + 18] for b in range(18))
                    drawn[s] = packets_check(g, packets + (s - 1) * PACKETS)
                g.press(START); time.sleep(.4)
                paused += 1
                continue
            if a.shots and i < a.shots: g.shot(out / f'shot{i:02d}.png')
            if not wolves: time.sleep(.25); continue
            n += 1
            for s, w in wolves.items():
                d, back, r, p = place(g, s, w)
                near[s] += 200 <= d <= 2500; behind[s] += back
                if i % 10 == 0: print(f'sample {i}: P{s} root {r}, wolf {p} ({d:.0f} away)', flush=True)
            time.sleep(.25)
        for s in wolves:
            print(f'P{s}: pose equal {same[s]}/{paused} (paused), 200..2500 away {near[s]}/{n}, '
                  f'behind {behind[s]}/{n}', flush=True)
            if not paused or same[s] < paused: failures.append(f'P{s}: pose copied in {same[s]}/{paused} paused samples only')
            if near[s] < n * .8: failures.append(f'P{s}: wolf 200..2500 from her in {near[s]}/{n} samples only')
            if behind[s] < n * .6: failures.append(f'P{s}: wolf behind her in {behind[s]}/{n} samples only')
            cmds, upper, linked = drawn.get(s, (0, 0, 0))
            print(f'P{s}: packets {cmds}, semi-transparent additive in the upper half {upper}, linked {linked} '
                  f'(paused)', flush=True)
            if not cmds or upper < cmds: failures.append(f'P{s}: packets {upper}/{cmds} additive in the upper half')
            if not linked: failures.append(f'P{s}: no packet linked')
    finally:
        g.stop()
    for f in failures: print('FAIL:', f)
    if failures: sys.exit(1)
    print('OK')


if __name__ == '__main__': main()
