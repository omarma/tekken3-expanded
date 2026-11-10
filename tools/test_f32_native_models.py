#!/usr/bin/env python3
"""F32 pilot: a Tekken 3 native drawn by its TTT1 arcade model, in the running game.

    python tools/test_f32_native_models.py [--case jin|paul|mirror|all] [--off] [--hq]
        [--build build-rel-lite] [--assets DIR]

Practice, player 1 on the native in its punch costume against a native on its
PS1 model (mirror: Jin against Jin), TEKKEN3_TTT1_NATIVE_MODELS naming the
native (--off: not named, the PS1 model, for the "before" captures). Checks
that the runtime grafted the TTT1 model on the native's own PS1 model and
that the fighter still plays its Tekken 3 moves (punches, kicks, a throw:
the move numbers player 1 goes through, the damage dealt), and takes
captures before / during each move (workspace/f32-native-models/; --hq:
supersampling x4 and anti-aliasing, OpenGL shots of the supersampled
surface, for the user to judge). The assets folder is a TTT1 catalogue with
<Name>-Native-TTT1-* in it (tools/ttt1_native_model.py).

Devil Jin's own check stays tools/test_devil_jin.py.
"""
import argparse, os, struct, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_devil_jin as T

WORK = ROOT / 'workspace/f32-native-models'
CASES = {'jin': (9, 0), 'paul': (0, 9), 'mirror': (9, 9), 'both': (0, 9), 'devil': (9, 0)}        # player 1, dummy
KEYS = {9: 'jin', 0: 'paul'}
pad, SQ, TR, CR, CI, R, D = T.pad, T.SQ, T.TR, T.CR, T.CI, T.R, T.D
# Tekken 3 inputs from player 1's stance, facing right: name, steps.
MOVES = [('1', [(3, pad(SQ)), (40, 0xffff)]),
         ('2', [(3, pad(TR)), (40, 0xffff)]),
         ('3', [(3, pad(CR)), (50, 0xffff)]),
         ('4', [(3, pad(CI)), (50, 0xffff)]),
         ('df2', [(3, pad(D, R)), (3, pad(D, R, TR)), (60, 0xffff)]),
         ('throw', [(3, pad(SQ, CR)), (150, 0xffff)]),
         # Supercharge (1+2+3+4): its glows sit on the fists (an ID-indexed PS1 vector).
         ('super', [(4, pad(SQ, TR, CR, CI)), (120, 0xffff)], [.6, 1.1]),
         # E4: up held (True Ogre's wings flap while airborne); blink: no input, a shot as
         # the game shuts the eyes (actor +0x1290) and one 0.3 s later.
         ('jump', [(20, pad(T.U)), (90, 0xffff)], [.4, .75]),
         ('blink', [(2, 0xffff)], [])
         # E5: True Ogre's Hell's Flame (1+2): flames from two points of his own table (0x80098800) turned
         # by the fighter's bone 2 matrix (actor +0x97C), active frames 58..126 (TIPS 33).
         , ('breath', [(4, pad(SQ, TR)), (150, 0xffff)], [.75, 1.0])]
EYES = 0x1290
SHOTS = [.12, .3]                                  # seconds after the input


# Without the user's pad: he may play beside the test (memory: test-instances-no-pad).
NO_PAD = dict(SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS='0', SDL_JOYSTICK_HIDAPI='0', SDL_JOYSTICK_RAWINPUT='0',
              SDL_XINPUT_ENABLED='0', SDL_JOYSTICK_DIRECTINPUT='0', SDL_JOYSTICK_WGI='0', SDL_JOYSTICK_GAMEINPUT='0')


# Player 2's pad in the run's settings. "none": the debug server's port 2 injection (a build with
# PSX_DEBUG_TOOLS=ON) plugs it in; "keyboard" reads the keyboard every frame over that injection.
P2_DEVICE = 'none'


class Game(T.Game):
    """test_devil_jin's game, launched from a folder of its own with copies of
    the build's executable, BIOS and mods (Windows: no links; the build's mods/
    is never touched), headless x1, or --hq: an OpenGL window, x4, anti-aliased."""
    def q(self, **r):
        # A GPU fault halts the emulation but keeps the debug server: say so
        # instead of waiting on a game that no longer runs.
        result = super().q(**r)
        if r.get('cmd') in ('input_route_status', 'press', 'savestate'): self.halted()
        return result

    def write(self, a, v, n=4):
        # write_ram writes one byte.
        for j in range(n): self.q(cmd='write_ram', addr=f'{a + j:08x}', val=f'{v >> (j * 8) & 255:02x}')

    def halted(self):
        with self.log_path.open('rb') as f:
            f.seek(max(0, self.log_path.stat().st_size - 4096))
            tail = f.read().decode(errors='replace')
        fatal = [l for l in tail.splitlines() if l.startswith('FATAL:')]
        if fatal: raise RuntimeError(fatal[-1][:120])

    def __init__(self, build, tag, env, hq=False):
        import shutil, socket, subprocess
        run = WORK / f'run-{os.getpid()}-{tag}'
        shutil.rmtree(run, ignore_errors=True); run.mkdir(parents=True)
        exe = 'Tekken_3_Expanded.exe' if os.name == 'nt' else 'Tekken_3_Expanded'
        shutil.copy2(build / exe, run / exe)
        for name in ('bios', 'mods', 'assets'):
            if (build / name).exists(): shutil.copytree(build / name, run / name)
        video = 'supersampling=4\nantialiasing=true\n' if hq else 'supersampling=1\nantialiasing=false\n'
        (run / 'settings.toml').write_text(f'[video]\n{video}[controller]\np1_device="keyboard"\np2_device="{P2_DEVICE}"\n')
        cards = run / 'cards'; (cards / 'openbios').mkdir(parents=True)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); self.port = listener.getsockname()[1]
        self.log_path = WORK / f'{tag}.log'
        full = {k: v for k, v in os.environ.items() if not k.startswith('TEKKEN3_')}
        full.update(NO_PAD, SDL_AUDIO_DRIVER='dummy', **env)
        args = [str(run / exe), '--game', str(ROOT / 'game.toml'), '--disc', str(ROOT / 'disc/Tekken 3 (USA).cue'),
                '--no-launcher', '--debug-port', str(self.port), '--memcard-dir', str(cards),
                '--renderer', 'opengl' if hq else 'software'] + ([] if hq else ['--headless'])
        with self.log_path.open('w') as out:
            self.process = subprocess.Popen(args, cwd=ROOT, stdout=out, stderr=out, env=full)
        self.run, self.tag = run, tag
        deadline = time.monotonic() + 60
        while True:
            if self.process.poll() is not None: raise RuntimeError(f'game exited; see {self.log_path}')
            try:
                with socket.create_connection(('127.0.0.1', self.port), .2): break
            except OSError:
                if time.monotonic() > deadline: raise RuntimeError('debug endpoint did not start')
                time.sleep(.1)


def pick(g, p1, dummy, egg=False):
    """Practice's selector: player 1's fighter (square, punch costume), then the dummy.
    egg: Devil Jin, square then both punches two frames later (pressed on the
    same frame, triangle picks the Start costume)."""
    T.cursor_to(g, p1)
    if egg:
        T.route(g, [(2, pad(SQ)), (5, pad(SQ, TR)), (10, 0xffff)]); time.sleep(1.5)
    else:
        # Square opens the MOVESET card (punch costume), cross takes its first
        # choice, Tekken 3's moves (src/tekken3_native_moves.c).
        g.press(T.SQUARE, frames=5); time.sleep(1); g.press(T.CROSS, frames=5); time.sleep(1.5)
    # The dummy's cursor is player 2's (+0x7C), moved by pad 1.
    time.sleep(1)
    for _ in range(23):
        if g.value(T.CURSOR_CHAR + 0x7c) == dummy: break
        g.q(cmd='press', buttons=T.RIGHT, frames=4, port=1); time.sleep(.35)
    else: raise AssertionError(f'the dummy cursor did not reach character {dummy}')
    g.wait(lambda: g.value(T.STATE) != 9, 'dummy not chosen', 30,
           lambda: (g.press(T.SQUARE), time.sleep(.8), g.press(T.CROSS), time.sleep(.8)))


def close_menus(g):
    x = lambda: struct.unpack('<i', bytes.fromhex(g.q(cmd='read_ram', addr=f'{T.ACTOR:08x}', len=4)['hex']))[0]
    for _ in range(12):
        g.press(T.CROSS); time.sleep(.8)
        before = x(); T.route(g, [(12, pad(R))]); time.sleep(.6)
        if abs(x() - before) > 20: break
    else: raise AssertionError('the Practice menus did not close')
    time.sleep(1)
    g.q(cmd='write_ram', addr=f'{T.DUMMY:08x}', val='00')


def shot(g, name, hq):
    path = WORK / f'{g.tag}-{name}.png'
    g.q(cmd='screenshot_hires' if hq else 'screenshot', path=str(path))
    return path


def save(g, slot):
    """A savestate of the slot, taken again while the runtime saves it with
    `resume_pc was 0 - using fallback pc` (a save taken while Practice's
    overlay code runs resumes at an approximate pc): the one GPU halt of
    Hwoarang 82 in E2 followed such a save (TIPS 229)."""
    for _ in range(8):
        mark = len(g.log())
        g.q(cmd='savestate', op='save', slot=slot); time.sleep(.5)
        if 'resume_pc was 0' not in g.log()[mark:]: return
        time.sleep(.2)
    print(f'  savestate slot {slot}: every save fell back', flush=True)


def play(g, hq, moves=None):
    """Each move from the same saved stance: the moves player 1 went through, the damage."""
    save(g, 3)
    results = {}
    for name, steps, *when in (MOVES if moves is None else moves):
        g.q(cmd='savestate', op='load', slot=3); time.sleep(1.2)
        before = g.value(T.TOTAL_DMG, 2)
        moves, start = [], time.monotonic()
        T.route(g, steps)
        shots = list(when[0] if when else SHOTS)
        until = max([1] + [t + .1 for t in shots])        # every shot taken (the breath's come late)
        while g.q(cmd='input_route_status').get('active') or time.monotonic() - start < until:
            m = g.value(T.ACTOR + T.MOVE, 2)
            if not moves or moves[-1] != m: moves.append(m)
            if shots and time.monotonic() - start >= shots[0]:
                shot(g, f'{name}-{"ab"[2 - len(shots)]}', hq); shots.pop(0)
            time.sleep(.01)
        results[name] = (moves, g.value(T.TOTAL_DMG, 2) - before)
        if name == 'blink':
            start, shut = time.monotonic(), False
            while time.monotonic() - start < 15 and not shut:
                shut = bool(g.value(T.ACTOR + EYES, 1)); time.sleep(.005)
            if shut: shot(g, 'blink-a', hq); time.sleep(.3); shot(g, 'blink-b', hq)
            results[name] = (moves, int(shut))
        if name in ('super', 'jump'): results[name] = (moves, 1)          # no damage: it charges, it jumps
        print(f'  {name}: moves {moves} damage {results[name][1]}', flush=True)
    return results


def case(build, assets, name, off, hq):
    p1, dummy = CASES[name]
    env = {'TEKKEN3_TTT1_ASSETS': str(assets)}
    # both: the two players on their TTT1 models (player 2's band, moved tiles).
    if not off and name != 'devil': env['TEKKEN3_TTT1_NATIVE_MODELS'] = 'paul,jin' if name == 'both' else KEYS[p1]
    # E6: the TTT1 models are the default with the import; off is the variable at 0, devil the egg alone.
    else: env['TEKKEN3_TTT1_NATIVE_MODELS'] = '0'
    tag = f'{name}-{"ps1" if off else "ttt1"}{"-hq" if hq else ""}'
    g = Game(build, tag, env, hq)
    try:
        T.to_selector(g)
        pick(g, p1, dummy, egg=name == 'devil')
        g.wait(lambda: g.value(T.STATE) == 8 and g.value(T.PHASE, 2) >= 6, 'round did not start', 120)
        close_menus(g)
        time.sleep(1.5)
        shot(g, 'stance', hq)
        results = play(g, hq, [m for m in MOVES if m[0] not in ('jump', 'blink')])      # E1's moves
        ident = [T.actor(g, p) for p in (0, 1)]
        lines = [l for l in g.log().splitlines() if 'TTT1 model' in l or 'Native-TTT1' in l or 'TTT1 native models' in l
                 or l.startswith('Devil Jin model') or l.startswith('Devil Jin: P')]
        return ident, lines, results
    finally:
        g.stop()


# Sweep (E2): every native, one button each (or several), from one savestate at
# Practice's selector. Button -> pad bit, the costume the game gives, the
# cabinet variant (file P<v + 1>, tools/ttt1_native_model.py).
# R1: the third costume of a native drawn by its TTT1 model, the game given triangle (F32,
# tekken3_native_moves.c); triangle (RP) gives the game square there. Its file is Start's.
BUTTONS = {'LP': (SQ, 0, 0), 'LK': (CR, 1, 1), 'RP': (TR, 0, 2), 'RK': (CI, 1, 3), 'Start': (3, 2, 4),
           'R1': (11, 2, 4)}
# The third costumes the benches unlock (0x80097EF4): Law, Nina, Xiaoyu, Eddy, Jin, Gun Jack, Anna.
THIRD = (1, 5, 7, 8, 9, 16, 18)


def table_slot(entry, button):
    return entry['buttons']['Start' if button == 'R1' else button]


def clash_variant(k1, k2):
    """Player 2's model when both players take the same native with keys k1, k2: the game
    gives the second the other costume when both costumes match (sel_costume_clash_fix);
    the model follows the key unless it is player 1's (F32)."""
    v1, v2 = BUTTONS[k1][2], BUTTONS[k2][2]
    if BUTTONS[k1][1] != BUTTONS[k2][1] or BUTTONS[k2][1] == 2: return v2, BUTTONS[k2][1]
    costume = BUTTONS[k2][1] ^ 1
    return (v2 if v2 != v1 else costume), costume
TABLE = ROOT / 'tools/data/ttt1_native_models.json'
EXTRA_ENV = {}                                     # --env NAME=VALUE (probes)
SWEEP_MOVES = [m for m in MOVES if m[0] in ('1', '3', 'throw')]


def sweep_pairs(spec):
    """'all' (every native on LP, plus each Start of the table), or
    native[:BUTTON][/dummy[:BUTTON]],... (BUTTON LP by default; the dummy Paul, Law for Paul,
    picked with square, unless named: the same native is the clash case)."""
    import json
    table = json.loads(TABLE.read_text(encoding='utf-8'))['natives']
    if spec == 'all':
        return [(k, 'LP', None) for k in table] + [(k, 'Start', None) for k, v in table.items()
                                                   if v['buttons']['Start'] is not None and k != 'mokujin'] + [('mokujin', 'RP', None)]
    pairs = []
    for item in spec.split(','):
        item, _, other = item.strip().partition('/')
        k, _, b = item.partition(':')
        d, _, db = other.partition(':')
        for n in (k, d or k):
            if n not in table: raise SystemExit(f'{n}: not a native of {TABLE.name}')
        pairs.append((k, b or 'LP', (d, db or 'LP') if d else None))
    return pairs


def cursor_to(g, cid, block=0):
    """The cursor of player block `block` onto fighter cid, with player 1's pad
    (Practice: it moves the dummy's block too): right along a row, down to the
    next (test_devil_jin.cursor_to only goes right, one row)."""
    for vertical in (0xffbf, 0xffbf, 0xffef, 0xffef, 0xffef, 0xffbf):     # down, then up: no wrap
        for _ in range(12):
            if g.value(T.CURSOR_CHAR + block * 0x7c) == cid: return
            g.q(cmd='press', buttons=T.RIGHT, frames=4, port=1); time.sleep(.3)
        g.q(cmd='press', buttons=vertical, frames=4, port=1); time.sleep(.3)
    raise AssertionError(f'block {block} cursor did not reach character {cid}')


def to_practice(g):
    """The Practice selector, player 1 choosing: Start to the modes menu, three
    lines up, one cross. test_devil_jin.to_selector crosses until the
    selector shows; one cross too many picks player 1's fighter (Xiaoyu, the
    first cell) when it shows early."""
    g.q(cmd='turbo', enabled=1)
    g.wait(lambda: g.value(T.STATE) == 4, 'modes menu not reached', 180, lambda: g.press(T.START))
    g.q(cmd='turbo', enabled=0)
    time.sleep(1)
    # Third costumes (0x80097EF4: Law, Nina, Xiaoyu, Eddy, Jin, Gun Jack, Anna).
    # Not Mokujin's: Tekken 3 has no third Mokujin, the game stops on it (his
    # Start slot, 101, is his triangle's too).
    third = g.value(0x80097ef4) | sum(1 << i for i in THIRD)
    g.write(0x80097ef4, third)
    for _ in range(3): g.press(T.UP)
    time.sleep(.3); g.press(T.CROSS)
    g.wait(lambda: g.value(T.STATE) == 9 and g.value(T.MODE, 1) == 5, 'Practice selector not reached', 60)
    # Player 1's block choosing (1), past the selector's opening.
    g.wait(lambda: g.value(0x8011864c) == 1, 'player 1 not choosing', 60)
    time.sleep(.5)


def sweep(build, assets, spec, hq, off=False, suffix=''):
    """Practice: player 1 on each native with its button against Paul (Law
    for Paul), Tekken 3 moves (TEKKEN3_NATIVE_MOVES=0: no card). Checks the
    model file of that button was read and grafted (or, without one, that
    nothing was), the actor's ID and costume, and that 1, 3 and a throw play.
    Third costumes unlocked for the test (to_practice)."""
    import json
    table = json.loads(TABLE.read_text(encoding='utf-8'))['natives']
    pairs = sweep_pairs(spec)
    env = {'TEKKEN3_TTT1_ASSETS': str(assets), 'TEKKEN3_NATIVE_MOVES': '0', **EXTRA_ENV}
    env['TEKKEN3_TTT1_NATIVE_MODELS'] = '0' if off else 'all'          # E6: on by default
    tag = f'sweep-{"ps1" if off else "ttt1"}{"-hq" if hq else ""}{suffix}'
    results, ok, boots = {}, True, [0]

    def boot():
        g = Game(build, f'{tag}{"-%d" % boots[0] if boots[0] else ""}', env, hq)
        boots[0] += 1
        to_practice(g)
        time.sleep(.5)
        save(g, 5)
        return g

    def one(g, native, button, other=None):
        entry = table[native]; nid = entry['t3_id']
        bit, costume, variant = BUTTONS[button]
        dummy = table[other[0]]['t3_id'] if other else 1 if nid == 0 else 0
        dummy_bit = BUTTONS[other[1]][0] if other else SQ
        name = f'{native}-{button}' + (f'-vs-{other[0]}-{other[1]}' if other else '')
        g.q(cmd='savestate', op='load', slot=5); time.sleep(1.2)
        mark = len(g.log())
        cursor_to(g, nid)
        T.route(g, [(4, pad(bit)), (20, 0xffff)]); time.sleep(2.5)
        shot(g, f'{name}-picked', False)
        if off and button == 'R1':
            # The game's own selector: R1 picks nothing (player 1's block still choosing).
            state = g.value(0x8011864c)
            lines = [l for l in g.log()[mark:].splitlines() if 'Native' in l]
            return dict(ok=state == 1 and not lines, slot=None, read=False, actor=None, moves={},
                        log=lines[:8] + [f'player 1 block state {state} (1: still choosing)'])
        # Option off, the third costume unlocked: triangle is the game's third costume.
        if off and button == 'RP' and nid in THIRD: costume = 2
        # The dummy's cursor is player 2's block, moved by pad 1 (Practice).
        cursor_to(g, dummy, 1)
        # The dummy's button (square), cross takes the STAGE band (tekken3_stage_select.c).
        g.wait(lambda: g.value(T.STATE) != 9, 'dummy not chosen', 30,
               lambda: (g.q(cmd='press', buttons=pad(dummy_bit), frames=4), time.sleep(.8),
                        g.press(T.CROSS), time.sleep(.8)))
        g.wait(lambda: g.value(T.STATE) == 8 and g.value(T.PHASE, 2) >= 6, 'round did not start', 120)
        close_menus(g)
        time.sleep(1.5)
        shot(g, f'{name}-stance', hq)
        saved = MOVES[:]
        MOVES[:] = SWEEP_MOVES
        try: moves = play(g, hq)
        finally: MOVES[:] = saved
        for m in [x[0] for x in SWEEP_MOVES]:
            for suffix in 'ab':
                q = WORK / f'{g.tag}-{m}-{suffix}.png'
                if q.is_file(): q.replace(WORK / f'{g.tag}-{name}-{m}-{suffix}.png')
        ident = T.actor(g, 0)
        lines = [l for l in g.log()[mark:].splitlines() if 'TTT1 model' in l or 'Native' in l]
        slot = table_slot(entry, button)
        want = slot is not None and not off
        own = f'{native.capitalize()} (TTT1 model) model:'
        # The files are read again when they change (the previous case may have read them).
        read = any(l.startswith(own) and f'costume {variant + 1},' in l for l in lines)
        grafted = any(l.startswith(own) and 'P1 model header replaced' in l for l in lines)
        good = ident[2] == nid and ident[0] & 3 == costume and 'missing' not in ' '.join(lines)
        good &= grafted if want else not any('P1 model header replaced' in l for l in lines)
        good &= all(len(m) > 1 or d > 0 for m, d in moves.values()) and sum(d > 0 for _, d in moves.values()) >= 2
        result = dict(ok=good, slot=slot, read=read, actor=ident, moves=moves, log=lines[:8])
        if other and other[0] == native:
            # The clash: player 2's model and the costume the game gave it.
            import re
            v2, c2 = clash_variant(button, other[1])
            ident2 = T.actor(g, 1)
            read2 = {int(c) for c in re.findall(re.escape(own) + r' costume (\d+),', g.log()[mark:])}
            p2 = any(l.startswith(own) and 'P2 model header replaced' in l for l in lines)
            result.update(actor2=ident2, want2=(v2, c2), read_costumes=sorted(read2))
            result['ok'] = good and ident2[2] == nid and ident2[0] & 3 == c2 and (off or p2 and (v2 + 1) in read2)
        return result

    g = boot()
    try:
        for native, button, other in pairs:
            name = f'{native}-{button}' + (f'-vs-{other[0]}-{other[1]}' if other else '')
            for attempt in (1, 2):
                try:
                    results[name] = one(g, native, button, other)
                    break
                except (AssertionError, RuntimeError) as e:
                    results[name] = dict(ok=False, error=str(e))
                    # A case left half-way leaves the game where a savestate does not
                    # bring every mod back (the STAGE band, the menus): a new game.
                    g.stop(); g = boot()
            r = results[name]
            print(f'{name}:', 'OK' if r['ok'] else 'FAIL', r.get('error') or f"slot {r['slot']} actor {r['actor']}" +
                  (f" P2 actor {r['actor2']} want (variant, costume) {r['want2']} costumes read {r['read_costumes']}"
                   if 'actor2' in r else ''), flush=True)
            for l in results[name].get('log', []): print('   ', l)
            ok &= results[name]['ok']
    finally:
        g.stop()
    (WORK / f'{tag}.json').write_text(json.dumps(results, indent=1) + '\n', encoding='utf-8')
    return ok


# Team Battle (E2): two members picked with circle (RK) and triangle (RP),
# the second on its own model once the first is knocked out.
TEAM_GRID, TEAM_CELLS, TEAM_FULL = 0x800b8d70, 0x80022768, 10


def team(build, assets, members=(('king', 'RK'), ('lei', 'RP')), off=False, hq=False):
    """Team Battle from the Arcade selector (mode 2, grid 10 written as
    tools/test_third_costume.py does), a team of two: each member picked with
    its button on the grid. Round 1: member 1 on the model of its button;
    player 1's life set to 0; round 2: member 2 on its own. Returns (ok, lines)."""
    import json
    table = json.loads(TABLE.read_text(encoding='utf-8'))['natives']
    env = {'TEKKEN3_TTT1_ASSETS': str(assets), 'TEKKEN3_NATIVE_MOVES': '0'}
    env['TEKKEN3_TTT1_NATIVE_MODELS'] = '0' if off else 'all'          # E6: on by default
    g = Game(build, 'team-' + ('ps1' if off else 'ttt1') + ('-hq' if hq else '') + ''.join(f'-{n}-{b}' for n, b in members), env, hq)
    ok, lines = True, []
    try:
        # The modes menu: Arcade, QUIT GAME (this build's), VS, Team Battle.
        g.q(cmd='turbo', enabled=1)
        g.wait(lambda: g.value(T.STATE) == 4, 'modes menu not reached', 180, lambda: g.press(T.START))
        g.q(cmd='turbo', enabled=0)
        time.sleep(1)
        g.write(0x80097ef4, g.value(0x80097ef4) | sum(1 << i for i in THIRD))
        for _ in range(8):                     # the line (0x80097F40), 3: a press may move two
            line = g.value(0x80097f40)
            if line == 3: break
            g.press(0xffbf if line < 3 else 0xffef); time.sleep(.5)
        time.sleep(.3); g.press(T.CROSS)
        g.wait(lambda: g.value(T.STATE) == 10 and g.value(T.MODE, 1) == 2 and g.value(TEAM_GRID) == 1,
               'team size not asked', 60)
        time.sleep(1.5)
        g.press(T.RIGHT); time.sleep(.5); g.press(T.CROSS); time.sleep(1)
        g.wait(lambda: g.value(TEAM_GRID) == 2, 'members not asked', 10)
        cells = {g.value(TEAM_CELLS + c * 6 + 4, 1) >> 2: c for c in range(21)}
        mark = len(g.log())                    # the first member's files are read at Start
        for n, (native, button) in enumerate(members):
            c = cells[table[native]['t3_id']]
            g.write(TEAM_GRID + 8, c % 7)
            g.write(TEAM_GRID + 12, c // 7)
            time.sleep(.4)
            if button == 'Start':
                # Start on a native with its third costume: the game draws the team's other
                # places (0x80053968), it picks no third costume.
                g.press(T.START)
                g.wait(lambda: g.value(TEAM_GRID) == TEAM_FULL, f'Start on {native} drew no team', 10)
                print(f'Start on {native}: the team drawn (block {TEAM_FULL}), no pick', flush=True)
                members = members[:n]
                break
            T.route(g, [(4, pad(BUTTONS[button][0])), (20, 0xffff)]); time.sleep(1.2)
            g.wait(lambda: g.value(TEAM_GRID + 44) > n, f'member {n + 1} not picked', 10)
        # Start: the team's other places at random (Random fill), the CPU's team.
        time.sleep(.5); g.press(T.START)
        try:
            g.wait(lambda: g.value(T.STATE) == 8 and g.value(T.PHASE, 2) >= 6, 'round 1 did not start', 120,
                   lambda: (g.press(T.CROSS), time.sleep(1)))
        except AssertionError:
            shot(g, 'stuck', False)
            print('state', g.value(T.STATE), 'phase', g.value(T.PHASE, 2), 'blocks', g.value(TEAM_GRID),
                  g.value(TEAM_GRID + 172), 'picks', g.value(TEAM_GRID + 44), flush=True)
            raise
        time.sleep(2); shot(g, 'round1', hq)
        for n, (native, button) in enumerate(members):
            if n:
                g.write(T.ACTOR + T.LIFE, 0, 2)
                g.wait(lambda: g.value(T.PHASE, 2) < 6, 'round 1 did not end', 60)
                g.wait(lambda: g.value(T.STATE) == 8 and g.value(T.PHASE, 2) >= 6 and T.actor(g, 0)[2] == table[native]['t3_id'],
                       f'round with member {n + 1} did not start', 120, lambda: (g.press(T.CROSS), time.sleep(1)))
                time.sleep(2); shot(g, f'round{n + 1}', hq)
            variant, costume = BUTTONS[button][2], BUTTONS[button][1]
            nid = table[native]['t3_id']
            if off and button == 'RP' and nid in THIRD: costume = 2
            want = table_slot(table[native], button) is not None and not off
            ident = T.actor(g, 0)
            own = f'{native.capitalize()} (TTT1 model) model:'
            text = [l for l in g.log()[mark:].splitlines() if 'TTT1 model' in l or 'Native models' in l]
            read = any(l.startswith(own) and f'costume {variant + 1},' in l for l in text)
            grafted = any(l.startswith(own) and 'P1 model header replaced' in l for l in text)
            good = ident[2] == nid and ident[0] & 3 == costume and (read and grafted if want else not grafted)
            print(f'team member {n + 1} {native} {button}:', 'OK' if good else 'FAIL', 'actor', ident, flush=True)
            ok &= good; lines += text; mark = len(g.log())
    finally:
        g.stop()
    for l in lines: print('   ', l)
    return ok


# E4: what a native drawn by its TTT1 model needs of its own (TIPS 229). The hand probe
# (TEKKEN3_F32_HAND_PROBE) logs each row and pose index the engine asks; the face log each
# open / shut of the eyes; Yoshimitsu's glow points are read while he stands.
E4_SPEC = 'yoshimitsu:LP,kuma:LP,kuma:LK,trueogre:LP,law:LP,lei:LP,jin:LP'
E4_MOVES = ('1', '3', 'super', 'jump', 'blink')
TTT1_STEPS = {0, 5, 11, 16}
YOSHIMITSU_GLOW = [(70, 0, 150), (40, 0, 500), (40, 0, 650), (-50, 0, 950)]


def e4(build, assets, hq=False, off=False):
    import re
    SWEEP_MOVES[:] = [m for m in MOVES if m[0] in E4_MOVES]
    EXTRA_ENV.update(TEKKEN3_F32_HAND_PROBE='1')
    if off: EXTRA_ENV['TEKKEN3_F32_E4'] = '0'
    glow = {}
    played = globals()['play']
    def play_e4(g, hq):
        res = played(g, hq)
        if T.actor(g, 0)[2] == 4:
            words = [g.value(0x8009577c + 4 * i) for i in range(8)]
            h = lambda w, k: struct.unpack('<h', struct.pack('<H', w >> (16 * k) & 0xffff))[0]
            glow['points'] = [(h(words[2 * i], 0), h(words[2 * i], 1), h(words[2 * i + 1], 0)) for i in range(4)]
        return res
    globals()['play'] = play_e4
    try: ok = sweep(build, assets, E4_SPEC, hq, False, '-e4' + ('-off' if off else ''))
    finally: globals()['play'] = played
    tag = f'sweep-ttt1{"-hq" if hq else ""}-e4{"-off" if off else ""}'
    # Its log and those of its restarts (tag-1, tag-2...), not the --off run's (tag-off).
    text = '\n'.join(p.read_text(errors='replace') for p in WORK.glob(f'{tag}*.log')
                     if re.fullmatch(re.escape(tag) + r'(-\d+)?\.log', p.name))
    seen = {}
    for pl, model, nid, row, index in re.findall(r'F32 hand probe: P(\d) (\w+) id (\d+) row (\d+) index (\d+)', text):
        if pl == '1' and model == 'ttt1': seen.setdefault((int(nid), int(row)), set()).add(int(index))
    faces = re.findall(r'F32 face: P1 (shut|open)', text)
    checks = {
        'kuma hand row 19 on the cabinet steps': seen.get((11, 19), {0}) <= TTT1_STEPS,
        'true ogre hand row 21 on the cabinet steps': seen.get((20, 21), {0}) <= TTT1_STEPS,
        'true ogre wings within the 37 poses': max(seen.get((20, 1), {0})) < 37,
        'law / lei: no pose 4 on the TTT1 hands': all(4 not in seen.get((n, r), set()) for n in (1, 2) for r in (13, 17)),
        'eyes shut and open again on the TTT1 face': 'shut' in faces and 'open' in faces,
        "yoshimitsu's glow on the cabinet points": glow.get('points') == YOSHIMITSU_GLOW,
    }
    # --off (before): what the moves played show must be missing; the hands of Kuma and True
    # Ogre and the wings only differ on poses these moves may not reach.
    if off: checks = {k: not v for k, v in checks.items() if k.startswith(('law', 'eyes', 'yoshimitsu'))}
    for k, v in checks.items(): print(f'  E4 {"OK  " if v else "FAIL"} {k}', flush=True)
    print('  E4 hand rows seen:', {k: sorted(v) for k, v in sorted(seen.items())}, 'glow', glow.get('points'))
    return all(checks.values())


def devil(build, assets):
    """Devil Jin unchanged: test_devil_jin.py's own checks (Arcade, cold start),
    its game launched by this file's Game."""
    T.WORK = WORK
    # The selector shows before its cursor value (0x80118648 = 21) settles
    # here: another cross picked a fighter.
    os.environ['SELECTOR_ANY'] = '1'
    T.Game = lambda b, tag, env=None: Game(b, f'devil-{tag}', {'TEKKEN3_TTT1_ASSETS': str(assets), **(env or {})})
    sys.argv = [sys.argv[0], '--case', 'both', '--build', str(build)]
    try: T.main()
    except SystemExit as e: return e.code


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--case', choices=(*CASES, 'all'), default='all')
    ap.add_argument('--off', action='store_true', help='the native on its PS1 model (before)')
    ap.add_argument('--hq', action='store_true', help='supersampling x4, anti-aliasing, OpenGL window')
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--assets', type=Path, default=ROOT / 'workspace/f32-e1-assets/ttt1')
    ap.add_argument('--devil', action='store_true', help="tools/test_devil_jin.py's egg and jin cases, "
                    'launched as here (Windows), without TEKKEN3_TTT1_NATIVE_MODELS')
    ap.add_argument('--sweep', metavar='SPEC', help="E2: 'all' (each native on LP, and the Start costumes) or "
                    "native[:LP|RP|LK|RK|Start],... from one savestate, every model of the table")
    ap.add_argument('--team', nargs='?', const='king:RK,lei:RP', metavar='SPEC',
                    help='E2: Team Battle, members picked with their button (default king:RK,lei:RP, also R1), '
                    'the next member after a K.O.; Start then draws the rest (--off: PS1 models)')
    ap.add_argument('--suffix', default='', help='--sweep: appended to the tag (logs, captures), to run several at once')
    ap.add_argument('--env', action='append', default=[], metavar='NAME=VALUE', help='--sweep: passed to the game')
    ap.add_argument('--moves', help="--sweep: the moves played (default 1,3,throw; also 2, 4, df2, super, jump, blink)")
    ap.add_argument('--e4', action='store_true', help='E4: Yoshimitsu, Kuma, Panda, True Ogre, Law, Lei, Jin; hands, '
                    "eyes, sword glow checked in the game's log (--off: TEKKEN3_F32_E4=0, the checks must fail)")
    a = ap.parse_args()
    EXTRA_ENV.update(e.split('=', 1) for e in a.env)
    if a.moves: SWEEP_MOVES[:] = [m for m in MOVES if m[0] in a.moves.split(',')]
    if a.e4:
        T.PRACTICE = True; T.WORK = WORK; WORK.mkdir(parents=True, exist_ok=True)
        sys.exit(0 if e4((ROOT / a.build).resolve(), a.assets.resolve(), a.hq, a.off) else 1)
    if a.devil: sys.exit(devil(ROOT / a.build, a.assets.resolve()))
    if a.team:
        T.WORK = WORK; WORK.mkdir(parents=True, exist_ok=True)
        members = [(m.split(':')[0], m.split(':')[1] if ':' in m else 'LP') for m in a.team.split(',')]
        sys.exit(0 if team((ROOT / a.build).resolve(), a.assets.resolve(), members, a.off, a.hq) else 1)
    if a.sweep:
        T.PRACTICE = True; T.WORK = WORK; WORK.mkdir(parents=True, exist_ok=True)
        sys.exit(0 if sweep((ROOT / a.build).resolve(), a.assets.resolve(), a.sweep, a.hq, a.off, a.suffix) else 1)
    T.PRACTICE = True
    T.WORK = WORK
    WORK.mkdir(parents=True, exist_ok=True)
    build = (ROOT / a.build).resolve()
    ok = True
    for name in (CASES if a.case == 'all' else [a.case]):
        ident, lines, results = case(build, a.assets.resolve(), name, a.off, a.hq)
        print(f'{name}: actors {ident}'); print('\n'.join('  ' + l for l in lines[:12]))
        grafted = any('P1 model header replaced' in l for l in lines)
        if name == 'both': grafted &= any('P2 model header replaced' in l for l in lines)
        good = grafted != (a.off and name != 'devil') and ident[0][2] == CASES[name][0] and ident[0][0] & 3 == 0
        good &= 'missing' not in ' '.join(lines) and (name != 'devil' or not any('TTT1 model' in l for l in lines))
        # Tekken 3 moves: every input started a move and the strikes hit.
        good &= all(len(m) > 1 for m, _ in results.values()) and sum(d > 0 for _, d in results.values()) >= 4
        print(f'{name}:', 'OK' if good else 'FAIL'); ok &= good
    print('captures:', WORK)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
