#!/usr/bin/env python3
"""Machine Gun Cannon (1, 2, 1 on a counter hit) of the Changs on TTT1 moves (B67, GH#124), without a player.

    python tools/test_b67_machine_gun_cannon.py [--build build-rel-lite]
        [--fighters michelle,julia-ttt,unknown@michelle,unknown@julia,tetsujin@michelle]
        [--offsets 0,2,4] [--p2 4] [--normal] [--exe <before>] [--trace]

Build: pad 2 needs the debug server's port 2 (PSX_DEBUG_TOOLS=ON). Cold start
(a blank memory card), every line of the modes menu open, Practice: player 1
takes the fighter (a guest on the Tag page, Unknown / Tetsujin on the donor
TEKKEN3_TETSUJIN_MOVESET names, Julia with her MOVESET card: julia-ttt, or
julia-t3 for the reference), Jin is the dummy, 1P FREESTYLE, the dummy on
CONTROLLER (pad 2). Both are placed face to face once (savestate 1); each try
reloads it, player 1 plays 1, 2, 1 and player 2 starts its 4 at once: the jab
lands in the kick's start-up, a counter hit. The headless game runs
unthrottled: waits count frames.
The third hit (TTT1 0x8005684C) has no hit box: its victim plays the paired
reaction (T3 alias 0xCC6), waits on 0x9A6, then the hit lands. Tekken 3 keeps
its combo counter (victim +0x80, the Practice's COMBO and combo damage)
through those two aliases only, written in its code; a guest's victim plays
the pack's records of them and the third hit started a new combo: 2 Combo,
Damage 26. Checks: three hits, a combo count of 3 and a combo damage equal
to their sum. Exit status 1 when one is wrong, 2 when a fighter never got
the counter hit on any offset (nothing measured).
"""
import argparse, os, shutil, socket, struct, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'psxrecomp/tools'))
import debug_client

WORK = ROOT / 'out/b67'
STATE, PHASE, CURSOR_CHAR, CELL, GRID = 0x800ae204, 0x800ae224, 0x80118668, 0x80118650, 0x80118648
ACTOR, STRIDE = 0x800a9228, 0x188c
START, CROSS, SQUARE, R2, RIGHT, LEFT, DOWN, UP = 0xfff7, 0xbfff, 0x7fff, 0xfdff, 0xffdf, 0xff7f, 0xffbf, 0xffef
GUEST_ID, PACK = 23, 8192
MODE, LINE, PRACTICE, PRACTICE_LINE, JIN, JULIA = 0x800afa88, 0x80097f40, 5, 8, 9, 10
DUMMY, CONTROLLER = 0x800b8bdd, 8                  # Practice dummy action (TIPS section 6)
TOTAL_DMG, PRACTICE_BLOCK = 0x800b8b94, 0x800b8b60     # TOTAL DMG +0x34, combo damage +0x38, COMBO +0x48
CANNON = 0x8005684c                               # TTT1 record of the cannon's third hit (the Changs')


def pad(*bits):
    m = 0xffff
    for b in bits: m &= ~(1 << b)
    return m
B_R, B_D, B_L, B_TR, B_CI, B_X, B_SQ = 5, 6, 7, 12, 13, 14, 15     # Triangle 2, Circle 4, Cross 3, Square 1
# Player 2's attack (it faces left: forward is left on its pad).
P2_MOVES = {'df2': pad(B_D, B_L, B_TR), '4': pad(B_CI), 'f4': pad(B_L, B_CI), 'b2': pad(B_R, B_TR),
            '12': pad(B_SQ, B_TR), 'f2': pad(B_L, B_TR), '3': pad(B_X), 'b1': pad(B_R, B_SQ)}


class Game:
    def __init__(self, build, tag, visible=False, exe=None, donor=None):
        run = WORK / f'run-{os.getpid()}-{tag}'
        shutil.rmtree(run, ignore_errors=True); run.mkdir(parents=True)
        built = next(p for p in (build / 'Tekken_3_Expanded.exe', build / 'Tekken_3_Expanded') if p.exists())
        shutil.copy2(exe or built, run / built.name)
        for name in ('bios', 'mods'):       # links, not copies: the catalogue is large
            if os.name == 'nt':
                subprocess.run(['cmd', '/c', 'mklink', '/J', str(run / name), str(build / name)], check=True, capture_output=True)
            else: (run / name).symlink_to(build / name)
        (run / 'settings.toml').write_text('[video]\nsupersampling=1\nantialiasing=false\n'
                                           '[controller]\np1_device="keyboard"\np2_device="none"\n')
        cards = run / 'cards'; cards.mkdir()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); self.port = listener.getsockname()[1]
        self.log_path = WORK / f'{tag}-{os.getpid()}.log'
        env = {k: v for k, v in os.environ.items() if not k.startswith('TEKKEN3_')}
        env['SDL_AUDIO_DRIVER'] = 'dummy'
        if donor: env['TEKKEN3_TETSUJIN_MOVESET'] = donor     # Tetsujin / Unknown on that guest's moves
        args = [str(run / built.name), '--game', str(ROOT / 'game.toml'), '--disc', str(ROOT / 'disc/Tekken 3 (USA).cue'),
                '--no-launcher', '--renderer', 'opengl' if visible else 'software', '--debug-port', str(self.port),
                '--memcard-dir', str(cards)] + ([] if visible else ['--headless'])
        self.out = self.log_path.open('w')
        self.process = subprocess.Popen(args, cwd=ROOT, stdout=self.out, stderr=self.out, env=env)
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
        for _ in range(100):
            result = debug_client.query('127.0.0.1', self.port, r)
            if result.get('err') != 'emu busy or frozen': break
            time.sleep(.2)
        if result.get('ok') is False: raise RuntimeError((r, result))
        return result

    def log(self):
        self.out.flush(); return self.log_path.read_text(errors='replace')
    def read(self, a, n=4): return bytes.fromhex(self.q(cmd='read_ram', addr=f'{a:08x}', len=n)['hex'])
    def value(self, a, n=4): return int.from_bytes(self.read(a, n), 'little')
    def write(self, a, data): self.q(cmd='write_ram', addr=f'{a:08x}', bytes=data.hex())
    def press(self, b, port=1): self.q(cmd='press', buttons=b, frames=4, port=port); time.sleep(.25)
    def p2(self, b): self.q(cmd='set_input', buttons=f'{b:04x}', port=2)
    def frame(self): return self.q(cmd='frame')['frame']
    def frames(self, n):
        end = self.frame() + n
        while self.frame() < end: time.sleep(.002)

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


def route(g, steps):
    g.q(cmd='input_route_clear')
    for n, b in steps: g.q(cmd='input_route_append', frames=n, buttons=b)
    g.q(cmd='input_route_start')


def tag_place(k): return divmod(k, 8) if k < 16 else (k - 16, 8)


def seek(g, target, what):
    """The grid cursor that moves (player 1's, or the dummy's once player 1
    has picked a fighter of this page) onto a Tekken 3 fighter: right along
    a row, down to the next one (test_b42_megaton)."""
    cursors = (CURSOR_CHAR, CURSOR_CHAR + 0x7c)
    for k in range(48):
        before = [g.value(c) for c in cursors]
        if target in before: return
        g.press(RIGHT)
        after = [g.value(c) for c in cursors]
        if target in after: return
        if k % 12 == 11 or after == before:      # the other row (two rows: down, else up)
            g.press(DOWN)
            if [g.value(c) for c in cursors] == after: g.press(UP)
    raise AssertionError(f'the grid cursor never reached {what}')


def card(g, ttt1):
    """The native's MOVESET card (square): TEKKEN 3 or TEKKEN TAG TOURNAMENT."""
    before = g.log().count('P1 opens the MOVESET card')
    g.press(SQUARE)
    g.wait(lambda: g.log().count('P1 opens the MOVESET card') > before, 'square did not open the MOVESET card', 5)
    if ttt1:
        g.press(RIGHT)
        g.wait(lambda: 'P1 highlights TTT1 moves' in g.log(), 'right did not switch to TTT1 moves', 5)
    g.press(CROSS)
    want = f'P1 takes {"TTT1" if ttt1 else "T3"} moves'
    g.wait(lambda: want in g.log(), f'X did not take the card ({want})', 5)


def to_practice(g, fighter, catalogue):
    """Cold start, every line of the modes menu open (TIPS section 6),
    Practice; player 1 takes the fighter (a guest on the Tag page, or Julia
    with her MOVESET card), then picks Jin as the dummy."""
    def menu():
        if g.value(STATE) == 3:
            g.write(0x80097ef0, struct.pack('<I', 0x1fffff)); g.write(0x80097f1e, b'\1'); g.write(0x80097f26, b'\1\1')
            g.press(START)
        return g.value(STATE) == 4
    g.q(cmd='turbo', enabled=1)
    g.wait(menu, 'mode menu not reached', 240)
    g.q(cmd='turbo', enabled=0)
    time.sleep(.5)
    g.write(LINE, struct.pack('<I', PRACTICE_LINE)); g.press(CROSS)
    g.wait(lambda: g.value(STATE) == 9 and g.value(MODE) == PRACTICE, 'the Practice selector never came', 30)
    time.sleep(1.5)
    if fighter.startswith('julia'):
        seek(g, JULIA, 'Julia')
        card(g, fighter == 'julia-ttt')
    else:
        g.press(R2); time.sleep(2.5)
        row, col = tag_place(catalogue.index(fighter.partition('@')[0]))
        for _ in range(14):
            r, c = tag_place(g.value(CELL))
            if (r, c) == (row, col): break
            g.press(DOWN if r < row else UP if r > row else RIGHT if c < col else LEFT)
        g.wait(lambda: g.value(CURSOR_CHAR) >= GUEST_ID, 'player 1 did not reach the guest', 10)
        g.press(SQUARE)
    time.sleep(1.5)
    # Player 1's pad now picks the dummy: Jin, on the Tekken 3 page.
    if g.value(CURSOR_CHAR) >= GUEST_ID: g.press(R2); time.sleep(2.5)
    seek(g, JIN, 'Jin')
    for _ in range(10):
        if g.value(STATE) == 8: break
        g.press(CROSS); time.sleep(.7)
    g.wait(lambda: g.value(STATE) == 8 and g.value(PHASE, 2) >= 8, 'the fight never started', 120)
    time.sleep(3)
    # MODE SELECT -> 1P FREESTYLE (X); a press during the banner is lost:
    # again until a jab plays (tools/ttt1/combos.py).
    for _ in range(8):
        g.press(CROSS); g.frames(60)
        route(g, [(4, pad(B_SQ)), (30, 0xffff)]); g.frames(12)
        if g.value(ACTOR + 0xa0, 2) != 3: break
    else: raise AssertionError('1P FREESTYLE not reached')
    g.frames(60)
    g.write(DUMMY, bytes([CONTROLLER]))       # the dummy on pad 2


def gated(g, writes):
    """Actor fields written with both actors' updates held (test_ttt1_solo)."""
    for p in (0, 1): g.write(ACTOR + p * STRIDE + 0xc3, b'\0')
    for a, data in writes: g.write(a, data)
    for p in (0, 1): g.write(ACTOR + p * STRIDE + 0xc3, b'\1')


def place(g):
    x = lambda p: struct.unpack('<i', g.read(ACTOR + p * STRIDE, 4))[0]
    g.wait(lambda: g.value(ACTOR + 0xa0, 2) == 3, 'player 1 did not reach its stance', 30)
    for _ in range(10):
        writes = []
        for p, xp, facing in ((0, -450, 0x4000), (1, 450, 0xc000)):
            a_ = ACTOR + p * STRIDE
            writes += [(a_, struct.pack('<3i', xp, 0, 0)), (a_ + 0xf68, struct.pack('<3i', xp, 0, 0)),
                       (a_ + 0xe, struct.pack('<H', facing)), (a_ + 0x2c, struct.pack('<H', facing))]
        gated(g, writes)
        g.frames(30)
        if abs(x(1) - x(0)) < 1600 and g.value(ACTOR + 0xa0, 2) == 3: break
    else: raise AssertionError(f'could not place the fighters ({x(0)}, {x(1)})')


def cannon_number(build, fighter):
    """Player 1's move number of the cannon's third hit: the pack record of
    TTT1 0x8005684C (8192 + its index), or Julia's T3 move 0x506."""
    if fighter == 'julia-t3': return 0x506
    key = 'julia' if fighter == 'julia-ttt' else fighter
    name = '@'.join(k.capitalize() for k in key.split('@'))
    pack = (build / f'mods/ttt1/{name}-TTT1-combat.jmv').read_bytes()
    n = struct.unpack_from('<8I', pack)[3]
    return next(PACK + i for i in range(n) if struct.unpack_from('<4I', pack, 32 + i * 16)[1] == CANNON)


def attempt(g, offset, p2_move, counter=True, trace=False):
    """From savestate 1: player 1 plays 1, 2, 1 after `offset` idle frames,
    player 2 starts its move at once (counter) or walks forward (no guard).
    Returns the samples: both move numbers and the Practice's COMBO (hits of
    the combo under way), TOTAL DMG and combo damage."""
    g.q(cmd='savestate', op='load', slot=1); time.sleep(1.5)
    g.p2(0xffff)

    def sample():
        p = g.read(PRACTICE_BLOCK + 0x34, 0x18)
        row = dict(f=g.frame(), m1=g.value(ACTOR + 0xa0, 2), m2=g.value(ACTOR + STRIDE + 0xa0, 2),
                   count=p[0x14], total=struct.unpack_from('<h', p, 0)[0], combo=struct.unpack_from('<h', p, 4)[0])
        if trace:
            row['a'], row['b'] = g.read(ACTOR, STRIDE), g.read(ACTOR + STRIDE, STRIDE)
            row['g'] = g.read(PRACTICE_BLOCK, 0x100)
        return row
    rows = [sample()]                   # before: TOTAL DMG's first step is the jab
    steps = ([(offset, 0xffff)] if offset else []) + [
        (3, pad(B_SQ)), (2, 0xffff), (3, pad(B_TR)), (4, 0xffff), (3, pad(B_SQ)), (120, 0xffff)]
    if counter:
        # Player 1's route first, player 2's attack right after: two commands
        # back to back, about a frame apart, so the jab lands in its start-up.
        route(g, steps)
        g.p2(p2_move)
        g.frames(4); g.p2(0xffff)
    else:
        g.p2(pad(B_L))
        route(g, steps)
    end = g.frame() + 150
    while g.frame() < end:
        row = sample()
        if trace or any(rows[-1][k] != row[k] for k in ('m1', 'm2', 'count', 'total', 'combo')): rows.append(row)
        time.sleep(.002)
    g.p2(0xffff)
    return rows


def verdict(rows, cannon):
    """The hits of a try (TOTAL DMG's steps), the highest combo count, the
    combo damage at the end; 'MISS' when the cannon never came (no counter hit)."""
    hits = [b['total'] - a['total'] for a, b in zip(rows, rows[1:]) if b['total'] > a['total']]
    count, combo = max(r['count'] for r in rows), rows[-1]['combo']
    if cannon not in [r['m1'] for r in rows]: state = 'MISS'
    else: state = 'OK' if len(hits) == 3 and count >= 3 and combo == sum(hits) else 'FAIL'
    return state, hits, count, combo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--fighters', default='michelle,julia-ttt,unknown@michelle,unknown@julia,tetsujin@michelle',
                    help='guests (unknown@<donor>, tetsujin@<donor>), julia-ttt, julia-t3 (the reference)')
    ap.add_argument('--offsets', default='0,2,4', help="player 1's idle frames before the jab, tried in turn")
    ap.add_argument('--p2', default='4', help=', '.join(P2_MOVES))
    ap.add_argument('--normal', action='store_true', help='also print 1, 2, 1 without the counter')
    ap.add_argument('--exe', help="another executable for the build's data (the build before a change)")
    ap.add_argument('--visible', action='store_true')
    ap.add_argument('--trace', action='store_true', help='keep every sample (actors, Practice block) in out/b67')
    a = ap.parse_args()
    build = (ROOT / a.build).resolve()
    catalogue = [l.split()[0] for l in (build / 'mods/ttt1/guests.txt').read_text().splitlines() if l.split()]
    WORK.mkdir(parents=True, exist_ok=True)
    results = {}
    for fighter in a.fighters.split(','):
        cannon = cannon_number(build, fighter)
        g = Game(build, fighter.replace('@', '-'), a.visible, a.exe and Path(a.exe), fighter.partition('@')[2])
        try:
            to_practice(g, fighter, catalogue)
            place(g)
            g.q(cmd='savestate', op='save', slot=1); time.sleep(1.5)
            if a.normal:
                rows = attempt(g, 0, P2_MOVES[a.p2], counter=False)
                _, hits, count, combo = verdict(rows, cannon)
                print(f'{fighter} 1, 2, 1 without the counter: hits {hits}, combo {count}, combo damage {combo}', flush=True)
            results[fighter] = ('MISS',)
            for offset in map(int, a.offsets.split(',')):
                rows = attempt(g, offset, P2_MOVES[a.p2], trace=a.trace)
                if a.trace:
                    import pickle
                    pickle.dump(rows, open(WORK / f'trace-{fighter}-{offset}.pkl', 'wb'))
                state, hits, count, combo = verdict(rows, cannon)
                moves = []
                for r in rows:
                    m = r['m1'] - PACK if r['m1'] >= PACK else hex(r['m1'])
                    if not moves or moves[-1] != m: moves.append(m)
                print(f'{fighter} counter hit, offset {offset}: {state} hits {hits}, combo {count}, '
                      f'combo damage {combo} (player 1 {moves[:8]})', flush=True)
                results[fighter] = (state, hits, count, combo)
                if state != 'MISS': break
        finally:
            g.stop()
    states = [r[0] for r in results.values()]
    print('B67:', 'FAIL' if 'FAIL' in states else 'INCOMPLETE (no counter hit for some fighter)' if 'MISS' in states else 'OK')
    sys.exit(1 if 'FAIL' in states else 2 if 'MISS' in states else 0)


if __name__ == '__main__':
    main()
