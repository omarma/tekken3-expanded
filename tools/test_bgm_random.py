#!/usr/bin/env python3
"""BGM SELECT's RANDOM (F11, src/tekken3_bgm_select.c), checked in the game.

    python tools/test_bgm_random.py menu   [--build build-dbg]
    python tools/test_bgm_random.py fights [--fights 6] [--lose 2] [--seed 5]
    python tools/test_bgm_random.py fights --ttt [--no-ps2] [--stage 1]
    python tools/test_bgm_random.py savestate [--seed 5]

Runs a private copy of the build as tools/test_stage_options.py does (its
Game: headless, software renderer, a copy of saves/card1.mcd), its runs in
workspace/f11.

menu: Options, GAME OPTION, the cursor on BGM SELECT, Right five times: the
  row must go REMIXED, ARCADE, SILENT, RANDOM and round (from the card's
  value), 0x80097F05 (the memory card's byte) never 3 (REMIXED while RANDOM
  shows), bgm-select.txt beside the card "random" while RANDOM shows, "game"
  otherwise.
fights: Arcade with TEKKEN3_BGM_SELECT=random, won fights one after the
  other (player 2's life set to 0); --lose N: player 1 loses the first fight
  N times and continues. Every fight must make one draw, every Continue keep
  it, the music of each fight (music_play's "music n in X" line) must be
  the drawn version, both versions must come out, the two columns of the
  fight's pieces be different XA tracks, and 0x80097F05 stay 0. --ttt: the
  fights on TTT stages (TEKKEN3_STAGES=ttt, TEKKEN3_STAGES_TTT=1, the TTT1
  catalogue of --mods, TEKKEN3_TTT_MUSIC_STAGE=--stage): REMIXED must play
  the stage's PS2 piece, ARCADE its arcade piece; with --no-ps2 (no PS2
  pieces) the arcade piece every time. A Continue's piece must go on, not
  start again (--seed 1: an ARCADE draw continued, the card being REMIXED).
savestate: Arcade, RANDOM; a save state in the first fight, then fights
  until one draws the other version, then the state loaded: the draw (mod
  memory, "the fight's draw kept at" in the log) must be the first fight's.
"""
import argparse, re, shutil, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_stage_options as tso
from test_stage_options import CROSS, START, DOWN, RIGHT, LEVEL, ENTRY, PHASE, P1_LIFE, P2_LIFE

tso.WORK = ROOT / 'workspace/f11'
BGM_SELECT, ENTRIES, HUMAN, STAGE_INDEX = 0x80097f05, 0x80024fd0, 0x800ae1f8, 0x800afaac
DRAW = re.compile(r'BGM SELECT: RANDOM, fight (\d+).* -> (REMIXED|ARCADE)')
KEEP = re.compile(r'BGM SELECT: Continue, the same fight keeps (REMIXED|ARCADE)')
MUSIC = re.compile(r'BGM SELECT: music (\d+) in (REMIXED|ARCADE) \(entry 0x([0-9A-F]{4})\)')
TTT = re.compile(r"TTT music: (PS2 piece|piece) 0x([0-9A-F]{2}) for")
STAGE_PIECES = [0x11, 0x1E, 0x16, 0x10, 0x19, 0x13, 0x1C, 0x1B, 0x17, 0x15, 0x18, 0x14, 0x1A, 0x18, 0x12]
STAGE_PS2_PIECES = [0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x13, 0x16]


def bgm_lines(g): return [l.strip() for l in g.log().splitlines() if l.startswith(('BGM SELECT:', 'TTT music:'))]


def menu(a):
    g = tso.Game(Path(a.build), None, {}, 'bgm-menu')
    try:
        g.modes_menu(); g.mode('OPTION MODE')
        g.wait(lambda: g.screen() == 5, 'no OPTIONS screen'); time.sleep(1.5)
        g.press(CROSS); time.sleep(1.5)
        assert g.value(LEVEL, 1) == 1, 'GAME OPTION did not open'
        while tso.page(g)[2] != 'BGM SELECT': g.tap(DOWN)
        rows = g.value(ENTRY + 0x20); row = rows + 20 * g.value(ENTRY)
        print(f'BGM SELECT row: {g.value(row + 13, 1)} values, value byte at {g.value(row):#010x}', flush=True)
        assert g.value(row + 13, 1) == 4, 'the row does not have four values'
        order = ['REMIXED', 'ARCADE', 'SILENT', 'RANDOM']
        seen = [tso.page(g)[3]]
        for step in range(5):
            before = tso.page(g)
            while tso.page(g) == before: g.tap(RIGHT)
            time.sleep(.3)
            value, card = tso.page(g)[3], g.value(BGM_SELECT, 1)
            word = (g.saves / 'bgm-select.txt').read_text().strip()
            print(f'BGM SELECT {value:8} card byte {card}  bgm-select.txt {word}', flush=True)
            assert card < 3, 'the card byte holds RANDOM'
            assert word == ('random' if value == 'RANDOM' else 'game'), (value, word)
            assert value == 'RANDOM' and card == 0 or value != 'RANDOM' and card == order.index(value), (value, card)
            seen.append(value)
        start = order.index(seen[0])
        assert seen == [order[(start + k) % 4] for k in range(6)], seen
        print('menu: OK')
    finally:
        g.stop()
        for line in bgm_lines(g): print('log:', line)


def run_fights(g, a, until):
    """Arcade from the modes menu, fights won one after the other, the first
    one lost --lose times, until until(lines) or 10 minutes."""
    lose, end = a.lose, time.monotonic() + 600
    g.modes_menu(); g.mode('ARCADE MODE')
    g.wait(lambda: g.screen() in (9, 10), 'no selector'); time.sleep(2)
    while not until(bgm_lines(g)) and time.monotonic() < end:
        s = g.screen()
        if s in (9, 10): g.press(CROSS)
        elif s == 8 and lose and g.value(PHASE, 2) >= 8:          # player 1 loses, continues
            if g.value(HUMAN, 2) == 0: g.press(START); lose -= 1
            elif g.value(PHASE, 2) == 8 and g.value(P1_LIFE, 2) > 0: g.write(P1_LIFE, 0, 2)
        elif s == 8 and g.value(PHASE, 2) == 8:
            if g.value(P2_LIFE, 2) > 0: g.write(P2_LIFE, 0, 2)
        elif s in (12, 16, 17): g.press(START)
        time.sleep(.3)


def fights(a):
    env = {'TEKKEN3_BGM_SELECT': 'random', 'TEKKEN3_BGM_SEED': str(a.seed)}
    no_ps2 = None
    if a.ttt:
        env.update(TEKKEN3_STAGES='ttt', TEKKEN3_STAGES_TTT='1', TEKKEN3_TTT_MUSIC_STAGE=str(a.stage))
        if a.no_ps2:
            no_ps2 = tempfile.mkdtemp(prefix='no-ps2-music-'); env['TEKKEN3_TTT_PS2_MUSIC_DIR'] = no_ps2
    g = tso.Game(Path(a.build), a.mods if a.ttt else None, env, 'bgm-fights')
    want = a.fights + a.lose
    try:
        if a.ttt and not (g.run / 'mods/ttt-music/music.ttm').is_file(): raise SystemExit('no mods/ttt-music in the build')
        run_fights(g, a, lambda lines: sum(1 for l in lines if DRAW.match(l) or KEEP.match(l)) > want)
        card = g.value(BGM_SELECT, 1)
        played = {int(m.group(1)) for m in map(MUSIC.match, bgm_lines(g)) if m}
        columns = {n: (g.value(ENTRIES + n * 4, 2), g.value(ENTRIES + n * 4 + 2, 2)) for n in sorted(played)}
    finally:
        g.stop()
        if no_ps2: shutil.rmtree(no_ps2, ignore_errors=True)
    lines = bgm_lines(g)
    print('\n'.join(lines), flush=True)
    # The lines of each fight: from its draw (or Continue) to the next one.
    fights_seen, current = [], None
    for l in lines:
        m, k = DRAW.match(l), KEEP.match(l)
        if m or k:
            if k: assert current and k.group(1) == current['version'], f'a Continue changed the version: {l}'
            current = {'version': (m or k).group(m and 2 or 1), 'continue': bool(k), 'music': [], 'ttt': []}
            fights_seen.append(current)
        elif current and MUSIC.match(l): current['music'].append(MUSIC.match(l).groups())
        elif current and TTT.match(l): current['ttt'].append(TTT.match(l).groups())
    fights_seen = fights_seen[:want]                     # the last one may not have reached its music
    drawn = [f['version'] for f in fights_seen if not f['continue']]
    kept = sum(f['continue'] for f in fights_seen)
    print(f'draws {drawn}, {kept} Continues kept, card byte {card}', flush=True)
    assert card == 0, f'0x80097F05 is {card} outside music_play'
    assert not any('(at its music)' in l for l in lines), 'a draw outside 0x8004F3B0 (the selector\'s music?)'
    assert kept >= a.lose, f'{kept} Continues seen, {a.lose} expected'
    assert set(drawn) == {'REMIXED', 'ARCADE'}, f'one version only in {len(drawn)} fights: try another --seed'
    entries = {}
    for f in fights_seen:
        assert f['music'], f'a fight without its music line: {f}'
        for n, version, entry in f['music']:
            assert version == f['version'], f'music {n} in {version} in a fight drawn {f["version"]}'
            entries.setdefault(n, {})[version] = entry
        if a.ttt:
            # A Continue's piece goes on (T3's same music): it must not start again.
            if f['continue']: assert not f['ttt'], f'the piece started again at a Continue: {f}'
            else: assert f['ttt'], f'no TTT piece in a fight: {f}'
            for kind, piece in f['ttt']:
                ps2 = f['version'] == 'REMIXED' and not a.no_ps2
                want_kind, want_piece = ('PS2 piece', STAGE_PS2_PIECES[a.stage]) if ps2 else ('piece', STAGE_PIECES[a.stage])
                assert (kind, int(piece, 16)) == (want_kind, want_piece), (f['version'], kind, piece)
    print('music_play table, REMIXED / ARCADE column of each piece played:',
          ', '.join(f'{n}: {c[0]:#06x} / {c[1]:#06x}' for n, c in columns.items()), flush=True)
    assert all(c[0] != c[1] for c in columns.values()), 'a piece has the same track in both columns'
    for n, e in entries.items():
        for version, entry in e.items():
            assert int(entry, 16) == columns[int(n)][version == 'ARCADE'], f'music {n} not from its {version} column'
    print('fights: OK')


def savestate(a):
    env = {'TEKKEN3_BGM_SELECT': 'random', 'TEKKEN3_BGM_SEED': str(a.seed)}
    g = tso.Game(Path(a.build), None, env, 'bgm-savestate')
    try:
        g.wait(lambda: re.search(r'draw kept at 0x([0-9A-F]{8})', g.log()), 'no draw address in the log')
        at = int(re.search(r'draw kept at 0x([0-9A-F]{8})', g.log()).group(1), 16)
        first = {}
        def saved(lines):
            if not first and g.screen() == 8 and g.value(PHASE, 2) >= 6 and any(DRAW.match(l) for l in lines):
                first['draw'] = g.value(at, 1); first['stage'] = g.value(STAGE_INDEX, 1)
                g.q(cmd='savestate', op='save', slot=1)
                print(f'saved in fight {first["stage"]} with draw byte {first["draw"]}', flush=True)
            return first and g.value(at, 1) not in (0, first['draw'])
        a.lose = 0
        run_fights(g, a, saved)
        other = g.value(at, 1)
        assert first and other not in (0, first['draw']), 'no fight drew the other version'
        print(f'fight {g.value(STAGE_INDEX, 1)} drew {other}; loading the state', flush=True)
        g.q(cmd='savestate', op='load', slot=1); time.sleep(2)
        back, stage = g.value(at, 1), g.value(STAGE_INDEX, 1)
        print(f'after the load: fight {stage}, draw byte {back}', flush=True)
        assert stage == first['stage'] and back == first['draw'], 'the state did not bring its draw back'
        print('savestate: OK')
    finally:
        g.stop()
        for line in bgm_lines(g): print('log:', line)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('case', choices=['menu', 'fights', 'savestate'])
    ap.add_argument('--build', default=str(ROOT / 'build-dbg'))
    ap.add_argument('--mods', default=str(ROOT / 'workspace/f11/mods-extra'), help='--ttt: a folder with ttt1/')
    ap.add_argument('--fights', type=int, default=6)
    ap.add_argument('--lose', type=int, default=0)
    ap.add_argument('--seed', type=int, default=5)
    ap.add_argument('--ttt', action='store_true')
    ap.add_argument('--no-ps2', action='store_true')
    ap.add_argument('--stage', type=int, default=1)
    a = ap.parse_args()
    {'menu': menu, 'fights': fights, 'savestate': savestate}[a.case](a)


if __name__ == '__main__': main()
