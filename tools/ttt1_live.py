#!/usr/bin/env python3
"""Live checks of the TTT1 characters in the running game, without a player.

    python3 tools/ttt1_live.py --case guest|jin|team|p2|mirror|hit|jab|push|push-p2|versus-stock-guest|versus-guest-stock [--guest jun] [--visible]

Session starts an isolated debug build (build-opt-dbg: Release +
PSX_DEBUG_TOOLS=ON) on the staged catalogue (mods/ttt1), from the private
selector save (slot 7), opens the Tag page with R2 and walks to the guest's
cell as a player would. cabinet() then selects it (or Jin) and waits for the native
fight. The cases below also back tools/test_ttt1_solo.py and
tools/test_ttt1_recovery.py, whose clip addresses are Jun's.

Inputs are real pad input; fixtures only arrange a dummy or a reaction, they
never synthesize a hit result. Captures and reports go to workspace/ttt1-live.
"""
import argparse, json, os, re, shutil, socket, struct, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'psxrecomp/tools'))
import debug_client

WORK = ROOT / 'workspace/ttt1-live'
SAVES = ROOT / 'workspace/fixtures/ps1-saves'          # private selector / fight saves
STOCK_VRAM = ROOT / 'workspace/fixtures/ps1-slot7-vram.bin'
GUEST_ID, GUEST_MODEL = 23, 52


def guest_id(player, index):
    """Move ID of the index-th record of a player's guest: player 2's guest
    moves live at 8192+4096+i (src/tekken3_ttt1_combat.c)."""
    return 8192 + 4096 * player + index
PAD_R2, PAD_L2 = 0xfdff, 0xfeff


def tag_place(k, count):
    """(row, column) of guest k on the Tag page (tag_place in
    src/tekken3_ttt1_roster.c): the first sixteen on eight columns by two
    rows, the others in a ninth column, one per row."""
    return divmod(k, 8) if k < 16 else (k - 16, 8)


class Session:
    def __init__(self, visible=False, guest='jun', build=ROOT / 'build-opt-dbg', env=None, slot=7):
        self.visible, self.guest, self.work, self.slot = visible, guest, WORK, slot
        self.assets = build / 'mods/ttt1'
        catalogue = [line.split()[0] for line in (self.assets / 'guests.txt').read_text().splitlines() if line.split()]
        if guest not in catalogue:
            raise RuntimeError(f'{guest} is not in {self.assets}/guests.txt; run tools/ttt1_stage_roster.py')
        self.index, self.catalogue_size = catalogue.index(guest), len(catalogue)
        # Each guest is its own character: 23 + its place in the catalogue.
        # Player 2's guest (a mirror unless TEKKEN3_GUEST_P2 says otherwise)
        # is set by the loading-phase opponent write in cabinet().
        other = (env or {}).get('TEKKEN3_GUEST_P2') or os.environ.get('TEKKEN3_GUEST_P2') or guest
        if other not in catalogue: raise RuntimeError(f'{other} is not in {self.assets}/guests.txt')
        self.cid, self.cid_p2 = GUEST_ID + self.index, GUEST_ID + catalogue.index(other)
        # A private copy of the build, so its settings (native resolution:
        # these checks run in real time) never touch the player's.
        # Per process: several sessions (other checks, other agents) may run
        # at once and must not delete each other's copy.
        self.run = run = WORK / f'run-{os.getpid()}'
        if run.exists(): shutil.rmtree(run)
        run.mkdir(parents=True)
        shutil.copy2(build / 'Tekken_3_Expanded', run / 'Tekken_3_Expanded')
        for name in ('bios', 'mods'): shutil.copytree(build / name, run / name)
        (run / 'settings.toml').write_text('[video]\nsupersampling=1\n[controller]\np1_device="keyboard"\np2_device="none"\n')
        self.saves = saves = WORK / f'saves-{os.getpid()}'
        if saves.exists(): shutil.rmtree(saves)
        shutil.copytree(SAVES, saves)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
        args = [str(run / 'Tekken_3_Expanded'), '--game', str(ROOT / 'game.toml'),
                '--disc', str(ROOT / 'disc/Tekken 3 (USA).cue'), '--no-launcher', '--renderer', 'software',
                '--debug-port', str(port), '--memcard-dir', str(saves)]
        if not visible: args.append('--headless')
        # Players pick their guests on the Tag page (R2) in cabinet().
        extra = {k: v for k, v in (env or {}).items() if k != 'TEKKEN3_GUEST_P2'}
        env = {k: v for k, v in os.environ.items() if not k.startswith('TEKKEN3_') or k.endswith('_LOG')}
        env.update(extra)
        if not visible: env['SDL_AUDIO_DRIVER'] = 'dummy'     # a window someone watches keeps its sound
        log = WORK / f'session-{os.getpid()}.log'
        with log.open('w') as out:
            self.process = subprocess.Popen(args, cwd=ROOT, stdout=out, stderr=out, env=env)
        self.info = dict(pid=self.process.pid, port=port, log=str(log), assets=str(self.assets), guest=guest)
        try: self.start(log, port)
        except BaseException:
            self.stop(); raise                  # a failed start must not leave the game running

    def start(self, log, port):
        deadline = time.monotonic() + 30
        while True:
            if self.process.poll() is not None: raise RuntimeError(f'the game exited during startup; see {log}')
            try:
                with socket.create_connection(('127.0.0.1', port), .2): break
            except OSError:
                if time.monotonic() > deadline: raise RuntimeError('debug endpoint did not start')
                time.sleep(.1)
        self.q(cmd='savestate', op='load', slot=self.slot)
        self.wait(lambda: 'registered as character 23' in log.read_text(errors='replace'),
                  'the TTT1 characters mod did not register its guest', 30)
        self.q(cmd='clear_input')
        self.loading_captured = False

    def q(self, **r):
        result = debug_client.query('127.0.0.1', self.info['port'], r)
        if result.get('ok') is False: raise RuntimeError((r, result))
        return result

    def read(self, a, n=4):
        result = self.q(cmd='read_ram', addr=f'{a:08x}', len=n)
        if 'hex' not in result: raise RuntimeError(result)
        return bytes.fromhex(result['hex'])

    def value(self, a, n=4): return int.from_bytes(self.read(a, n), 'little')

    def write(self, a, v, n=4):
        for j in range(n): self.q(cmd='write_ram', addr=f'{a + j:08x}', val=f'{v >> (j * 8) & 255:02x}')

    def press(self, b):
        self.q(cmd='set_input', buttons=b); time.sleep(.16)
        self.q(cmd='set_input', buttons=65535); time.sleep(.16)

    def game_until(self, seconds):
        """A deadline in game time (60 frames a second): a check sampling a
        move must see the same span of it however loaded the machine is.
        Wall clock is capped at twenty times the span."""
        end = self.q(cmd='frame')['frame'] + int(seconds * 60)
        wall = time.monotonic() + seconds * 20
        return lambda: self.q(cmd='frame')['frame'] < end and time.monotonic() < wall

    def wait(self, predicate, description, seconds=35):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if predicate(): return
            time.sleep(.06)
        raise AssertionError(description)

    def log(self): return Path(self.info['log']).read_text(errors='replace')

    def shot(self, name):
        path = self.work / (name + '.png')
        self.q(cmd='screenshot', path=str(path))
        if self.visible:
            assert self.q(cmd='ws_nw')['nw_extra'] > 0, 'Visible test did not engage widescreen'
            assert struct.unpack_from('>I', path.read_bytes(), 16)[0] > 368, 'Capture missed widescreen'

    def vram(self, x, y, w, h):
        words = self.q(cmd='vram_peek', x=x, y=y, w=w, h=h)['hex']
        return b''.join(struct.pack('<H', int(words[i:i + 4], 16)) for i in range(0, len(words), 4))

    def fonts(self):
        """The guest's selector art must leave the native font atlas alone."""
        if not STOCK_VRAM.is_file(): return
        stock = STOCK_VRAM.read_bytes()
        for y in (0, 128):
            expected = b''.join(stock[row * 2048 + 1792:row * 2048 + 1888] for row in range(y, y + 128))
            assert self.vram(896, y, 48, 128) == expected, 'The guest overwrote the native font atlas'

    def effects(self):
        """Native blue guard spark: its palette must come back after loading."""
        if not STOCK_VRAM.is_file(): return
        expected = STOCK_VRAM.read_bytes()[503 * 2048 + 64 * 2:503 * 2048 + 80 * 2]
        self.wait(lambda: self.vram(64, 503, 16, 1) == expected,
                  'Guest loading artwork corrupted the guard effect palette', 2)

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=10)
            except subprocess.TimeoutExpired: self.process.kill()
        shutil.rmtree(self.run, ignore_errors=True)      # the private copy of the build
        shutil.rmtree(self.saves, ignore_errors=True)

    def actor(self, p):
        return struct.unpack('<5H', self.read(0x800a923c + p * 0x188c, 10))

    def fight(self, p, cid):
        def ready():
            mode = self.value(0x800ae204)
            if mode == 11 and self.value(0x800ae224, 2) == 2 and not self.loading_captured:
                self.shot('loading-' + str(self.value(0x800afa88)))
                self.loading_captured = True
            if mode != 8 or self.value(0x800ae224, 2) < 6 or self.actor(p)[2] != cid: return False
            base = self.value(0x8009bd28 + p * 4)
            moves = self.value(0x800adc20 + p * 4)
            record = self.value(0x800a927c + p * 0x188c)
            return ((0x9f000000 <= moves < 0x9f400000 and 0x9f000000 <= record < 0x9f400000)
                    if cid >= GUEST_ID else 0x80100000 <= base < 0x80200000 and record != 0)
        # Loading a fight takes well over 35 s when other sessions load the
        # machine; the conditions below are exact, a longer wait is safe.
        self.wait(ready, f'P{p + 1} character {cid} did not reach the native fight', 90)
        identity = self.actor(p)
        # A guest's actor carries its own ID, and 23 as its move key (+0x16).
        assert identity[1:3] == ((GUEST_ID, cid) if cid >= GUEST_ID else (cid, cid)), identity
        if cid >= GUEST_ID or cid == 9:     # Jin's model is 18; other stock fighters have their own
            assert identity[4] == (GUEST_MODEL if cid >= GUEST_ID else 18), identity
        if cid >= GUEST_ID:
            header = self.value(0x800adc20 + p * 4)
            assert self.value(header + 1, 1) == GUEST_ID
            radii = [self.value(0x800a9228 + p * 0x188c + 0x218 + i * 20, 2) for i in range(14)]
            assert radii == [200, 200, 120, 120, 300, 300, 100, 100, 250, 300, 300, 200, 400, 400], radii
        self.fonts()
        self.effects()
        return identity


def cabinet(s, guest=True, opponent=None):
    """Select the session's guest (Tag page) or Jin (stock page) at the cabinet
    selector and fight. opponent: a character ID for player 2, GUEST_ID
    meaning player 2's guest."""
    def grid(n):
        rows = s.read(0x801296c8, n * 12)
        return [struct.unpack_from('<H', rows, i * 12 + 6)[0] for i in range(n)]
    s.wait(lambda: s.value(0x800ae204) == 9 and s.value(0x80118648) == 21, 'The stock selector grid never appeared', 20)
    assert set(grid(21)) == set(range(21)), grid(21)
    if guest:
        s.press(PAD_R2)
        tag = list(range(GUEST_ID, GUEST_ID + s.catalogue_size))
        s.wait(lambda: s.value(0x80118648) == s.catalogue_size and grid(s.catalogue_size) == tag,
               'R2 did not open the Tag page', 10)
        time.sleep(1.5)      # each cursor steps off its cell and back after a switch
        row, col = tag_place(s.index, s.catalogue_size)
        for _ in range(12):
            r, c = tag_place(s.value(0x80118650), s.catalogue_size)
            if (r, c) == (row, col): break
            s.press(0xffbf if r < row else 0xffef if r > row else 0xffdf if c < col else 0xff7f)
        s.wait(lambda: s.value(0x80118668) == s.cid, 'The cursor did not reach the guest cell', 10)
    else:
        for _ in range(23):
            if s.value(0x80118668) == 9: break
            s.press(0xff7f)
        else: raise AssertionError('Cabinet navigation did not reach Jin')
    s.shot('cabinet-' + (s.guest if guest else 'jin'))
    s.fonts()
    s.press(0x7fff)
    if opponent == GUEST_ID: opponent = s.cid_p2
    if opponent is not None:
        # Arrange a deterministic opponent during the native loading phase;
        # selection and navigation above remain real player input.
        s.wait(lambda: s.value(0x800ae204) == 11, 'Loading screen not reached', 15)
        s.write(0x800add5e, opponent, 2); s.write(0x800add9a, 0, 2)
    identity = s.fight(0, s.cid if guest else 9)
    if opponent is not None:
        s.fight(1, opponent)
        if guest:
            h1, h2 = s.value(0x800adc20), s.value(0x800adc24)
            assert h1 != h2 and s.value(h1 + 12) != s.value(h2 + 12), 'Mirror actors share combat tables'
        else:
            h1 = s.value(0x800adc20)
            assert s.value(h1 + 1, 1) == 9 and s.value(h1 + 12) < 0x80200000, 'Jin inherited guest combat data'
    s.shot('fight-' + (s.guest if guest else 'jin') + ('-mirror' if opponent == s.cid else ''))
    return identity


def versus(s, p1_guest):
    """Two players on two pages: one picks a stock fighter on the Tekken 3
    grid, the other joins (Start on pad 2, "new challenger"), switches to
    the Tag page with R2 and picks the session's guest; or the reverse. The
    confirmed player's frame must leave the other page and come back."""
    def p2(b): s.q(cmd='press', buttons=b, frames=3, port=2); time.sleep(.35)
    def cell(p): return s.value(0x80118650 + p * 0x7c)
    def char(p): return s.value(0x80118668 + p * 0x7c)
    s.wait(lambda: s.value(0x800ae204) == 9 and s.value(0x80118648) == 21, 'The stock selector grid never appeared', 20)
    time.sleep(1.5)
    p2(0xfff7)
    s.wait(lambda: char(1) < GUEST_ID, 'Player 2 did not join with Start', 5)
    guest, stock = (0, 1) if p1_guest else (1, 0)
    move = s.press if stock == 0 else p2
    # One step inward: player 2 starts on the right edge, next to Gon, whose
    # move key (19) is not his ID.
    move(0xffdf if stock == 0 else 0xff7f); time.sleep(.5); move(0x7fff); time.sleep(1)
    chosen, frame = char(stock), cell(stock)
    tag = s.press if guest == 0 else p2
    tag(PAD_R2); time.sleep(2.5)
    assert s.value(0x80118648) == s.catalogue_size, 'R2 did not open the Tag page'
    assert cell(stock) == 21, ('The confirmed player\'s frame stayed on the Tag page', cell(stock))
    for _ in range(12):
        r, c = tag_place(cell(guest), s.catalogue_size); row, col = tag_place(s.index, s.catalogue_size)
        if (r, c) == (row, col): break
        tag(0xffbf if r < row else 0xffef if r > row else 0xffdf if c < col else 0xff7f)
    s.wait(lambda: char(guest) == s.cid, 'The cursor did not reach the guest cell', 10)
    s.shot('versus-hover')
    tag(0x7fff); time.sleep(1)
    assert char(stock) == chosen, 'The confirmed stock choice changed'
    s.fight(stock, chosen)
    s.fight(guest, s.cid)
    s.shot('versus-fight')
    return dict(stock=(stock + 1, chosen, frame), guest=(guest + 1, s.cid))


def records(s, p=0):
    """Guest record address -> TTT1 clip, from its combat pack and the log."""
    pack = (s.assets / f'{s.guest.capitalize()}-TTT1-combat.jmv').read_bytes()
    count = struct.unpack_from('<I', pack, 12)[0]
    base = int(re.findall(rf'installed P{p + 1} alias table,.*records=([0-9A-F]+)', s.log())[-1], 16)
    return base, count, {base + i * 56: struct.unpack_from('<I', pack, 32 + i * 16)[0] for i in range(count)}


def idle(s, p=0, seconds=20):
    """Wait for the guest's neutral stance: its intro ignores input, and how
    long it lasts in real time depends on the emulation speed."""
    pack = (s.assets / f'{s.guest.capitalize()}-TTT1-combat.jmv').read_bytes()
    neutral = records(s, p)[0] + struct.unpack_from('<I', pack, 16)[0] * 56
    s.wait(lambda: s.value(0x800a927c + p * 0x188c) == neutral, f'P{p + 1} never reached its neutral stance', seconds)


def body_collision(s):
    """Walk into the opponent through actual inputs and native separation."""
    s.write(0x800aaab4 + 0xc5, 0, 1)
    time.sleep(3)  # Finish the native intro before applying movement.
    for p, x in enumerate((-1600, 1600)):
        a = 0x800a9228 + p * 0x188c
        s.write(a, x); s.write(a + 8, 0)
        if s.actor(p)[2] >= GUEST_ID:
            radii = [s.value(a + 0x330 + i * 16, 2) for i in range(8)]
            assert radii == [240, 96, 96, 300, 120, 120, 120, 120], radii
    history = []
    s.q(cmd='set_input', buttons=0xffdf)
    try:
        end = time.monotonic() + 3
        while time.monotonic() < end:
            x1 = struct.unpack('<i', s.read(0x800a9228))[0]
            x2 = struct.unpack('<i', s.read(0x800aaab4))[0]
            history.append((x1, x2))
            assert x2 > x1, ('Fighters walked through one another', x1, x2)
            time.sleep(.03)
    finally: s.q(cmd='clear_input')
    assert history[-1][0] > 0 and history[-1][1] > 2000, history[-1]
    return dict(minimum_separation=min(b - a for a, b in history), final_positions=history[-1])


def attacks(s, p=0):
    """Each button reaches its original attack (Jun's clips) with an idle opponent."""
    s.write(0x800aaab4 + 0xc5, 0, 1)
    source = records(s, p)[2]
    idle(s, p)
    def sample(seconds):
        seen = set(); end = time.monotonic() + seconds
        while time.monotonic() < end:
            s.write(0x800aaab4, 3000)
            rec = s.value(0x800a927c + p * 0x188c); seen.add(source.get(rec, rec)); time.sleep(.01)
        return seen
    sample(1.5)
    results = {}
    for name, button, expected in [('1', 0x7fff, 0x1a20b4), ('2', 0xefff, 0x1aac64),
                                   ('3', 0xbfff, 0x1b96d0), ('4', 0xdfff, 0x1c0fe8)]:
        s.q(cmd='press', buttons=button, frames=3)
        seen = sample(1.4); assert expected in seen, (name, [hex(x) for x in seen]); results[name] = hex(expected)
    return results


def team(s):
    s.write(0x800afa88, 2); s.write(0x800ae224, 0, 2); s.write(0x800ae204, 10, 2)
    time.sleep(1.2)
    s.press(0x7fff)
    # The stock grid (7 x 3) has no guest: R2 opens the Tag page, the
    # guests on eight columns by two rows. The player block still holds the
    # game's seven-column cell (x, y at +8 / +12): walk the grid as drawn.
    state = 0x800b8d70
    s.press(PAD_R2); time.sleep(1)
    # The game keeps seven columns (cell y * 7 + x = guest k); the page is
    # drawn and navigated in rows of six (VS_TAG_COLS in roster.c).
    row, col = divmod(s.index, 6)
    for _ in range(16):
        y, x = divmod(s.value(state + 12) * 7 + s.value(state + 8), 6)
        if (x, y) == (col, row): break
        s.press(0xffbf if y < row else 0xffef if y > row else 0xffdf if x < col else 0xff7f)
    else: raise AssertionError('Team grid did not reach the guest')
    s.shot('team-' + s.guest)
    s.fonts()
    s.press(0x7fff)
    assert s.value(state + 44) == 1 and s.value(state + 56) == s.cid * 4
    s.shot('team-confirmed')
    identity = s.fight(0, s.cid)
    s.shot('team-fight')
    return identity


def receive_hit(s):
    before = s.value(0x800a961c)
    s.wait(lambda: s.value(0x800a961c) < before, 'The guest took no damage from opponent attacks', 30)
    after = s.value(0x800a961c)
    s.shot('received-hit')
    return dict(hp_before=before / 65536, hp_after=after / 65536)


def jab_damage(s):
    """Jun's jab against Jin: original base damage 4, times the struck body zone."""
    s.write(0x800aaab4 + 0xc5, 0, 1)
    time.sleep(3)  # Let the guest's intro finish before sending input.
    s.q(cmd='set_input', buttons=0xffdf)
    try:
        def in_range():
            a = struct.unpack('<3i', s.read(0x800a9228, 12))
            b = struct.unpack('<3i', s.read(0x800aaab4, 12))
            return (a[0] - b[0]) ** 2 + (a[2] - b[2]) ** 2 < 1250 ** 2
        s.wait(in_range, 'Could not walk into jab range', 6)
        time.sleep(.8)  # Reach body-contact distance, inside the short jab.
    finally: s.q(cmd='clear_input')
    time.sleep(.05)
    # Native neutral guards a high jab automatically. Put the dummy into a
    # non-attacking victory animation so this measures normal damage, without
    # a guard or the counter-hit bonus of a ki-charge fixture.
    dummy = 0x800aaab4; alias = 0xd67
    table = s.value(s.value(0x800adc24) + 12)
    s.write(dummy + 0xc3, 0, 1)
    for offset, value in ((0x6e, 0), (0x198, 1), (0x19a, 6), (0x19c, 0), (0x19e, 0), (0x1a0, alias)):
        s.write(dummy + offset, value, 2)
    s.write(dummy + 0x1a4, s.value(table + alias * 4)); s.write(dummy + 0xc3, 1, 1)
    time.sleep(.06)
    before = s.value(0x800aaab4 + 0x3f4)
    s.q(cmd='press', buttons=0x7fff, frames=3)
    s.wait(lambda: s.value(0x800aaab4 + 0x3f4) < before, 'The jab did not contact Jin', 3)
    after = s.value(0x800aaab4 + 0x3f4)
    # The native collision result names the struck body zone, whose
    # percentage 80045038 applies: a raised arm in this pose can take 130%.
    contacts = [s.read(dummy + offset, 44) for offset in (0x13c, 0x168)]
    contacts = [row for row in contacts if any(row[:24])]
    assert len(contacts) == 1, contacts
    body_zone = struct.unpack_from('<H', contacts[0], 24)[0]
    assert body_zone < 14, body_zone
    percentage = s.value(0x8001deec + body_zone * 2, 2)
    assert not any(s.value(dummy + offset, 1) for offset in (0xcf, 0xd3, 0xd4)), 'Fixture added guard/counter/range modifiers'
    expected = 4 * percentage // 100
    assert before - after == expected * 65536, (before, after, body_zone, percentage)
    s.shot('jab-hit')
    return dict(hp_before=before / 65536, hp_after=after / 65536, base_damage=4,
                body_zone=body_zone, zone_percentage=percentage, damage=expected)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--case', choices=['guest', 'jin', 'team', 'p2', 'mirror', 'hit', 'jab', 'push', 'push-p2', 'versus-stock-guest', 'versus-guest-stock'], required=True)
    ap.add_argument('--guest', default='jun', help='catalogue key (default jun, whose clips the attack case checks)')
    ap.add_argument('--visible', action='store_true', help='Verify the real widescreen frontend and captures')
    a = ap.parse_args(); s = Session(a.visible, a.guest)
    try:
        if a.case == 'team': result = team(s)
        elif a.case.startswith('versus'): result = versus(s, a.case == 'versus-guest-stock')
        else:
            result = cabinet(s, a.case not in ('jin', 'p2', 'push-p2'),
                             GUEST_ID if a.case in ('p2', 'mirror', 'push-p2') else 9 if a.case in ('jab', 'push') else None)
            if a.case == 'guest': result = dict(identity=result, attacks=attacks(s))
            if a.case == 'hit': result = dict(identity=result, damage=receive_hit(s))
            if a.case == 'jab': result = dict(identity=result, damage=jab_damage(s))
            if a.case in ('push', 'push-p2'): result = dict(identity=result, collision=body_collision(s))
        (WORK / f'live-{a.case}.json').write_text(json.dumps(dict(case=a.case, result=result, session=s.info), indent=2) + '\n')
        print('PASS', a.case, result, flush=True)
    finally: s.stop()
