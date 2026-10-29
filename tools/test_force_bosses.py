#!/usr/bin/env python3
"""Tekken Force: each guest's own bosses (F02), the natives' Tekken 3 ones (B112).

    python tools/test_force_bosses.py --player kazuya [--stages 4] [--observe 20] [--shots DIR]
                                      [--build build-rel-lite] [--memcard-dir saves]
                                      [--attract] [--ttt1-moves]

Boots a private copy of the build (software renderer, headless, x1) on a copy
of the memory card, opens Tekken Force (tools/test_force_moveset.py) and picks
the player: a guest on the Tag page (R2), or a native on the stock page.
Player 1 then walks right, invincible, the level clock held. At each boss
(phases 21..23, TIPS Â§ 56): the fighter and costume loaded in actor 1 against
the route expected (src/tekken3_ttt1_combat.c, force_routes), then --observe
seconds of fight with player 1 standing and punching: the game must not hang
(the PC must leave the alias scan 0x80056764..0x800568FF and GTE
projections must go on: B04's freeze), the boss must play (its move record,
actor + 0x54, changes) and take hits. The boss is then knocked out (life 0)
and the next stage follows. Prints one line per stage and fails on the first
boss that does not hold. --attract first leaves the attract on till one of
its fights has a guest, as a player who watched it: the guests' tick then
runs through the Force overlay's load (B112, every native met Paul).
"""
import argparse, json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_force_moveset as fm
from test_force_moveset import Game, to_force_grid, SCREEN, PHASE, ACTOR, LIFE, CLOCK, STAGE, CROSS, SQUARE, RIGHT

ROOT = fm.ROOT
ACTOR_SIZE, BOSS = 0x188c, 1
R2, UP, DOWN, LEFT = 0xfdff, 0xffef, 0xffbf, 0xff7f
WALK, PUNCH = 0xffdf, 0x7fff
GUEST_ID = 23
NATIVES = ['paul', 'law', 'lei', 'king', 'yoshimitsu', 'nina', 'hwoarang', 'xiaoyu', 'eddy', 'jin', 'julia',
           'kuma', 'bryan', 'heihachi', 'ogre', 'mokujin', 'gunjack', 'gon', 'anna', 'drb', 'trueogre', 'crow']
# The validated table (handoff/file-1.2.2.md, F02); stage 4 is Heihachi but for Tetsujin.
ROUTES = {
    'kazuya': ['lee', 'paul', 'jin', 'heihachi'],
    'jun': ['kuma', 'lei', 'kazuya', 'heihachi'],
    'unknown': ['yoshimitsu', 'jin', 'jun', 'heihachi'],
    'devil': ['paul', 'jin', 'angel', 'heihachi'],
    'angel': ['xiaoyu', 'kazuya', 'devil', 'heihachi'],
    'lee': ['law', 'jin', 'kazuya', 'heihachi'],
    'bruce': ['eddy', 'bryan', 'kazuya', 'heihachi'],
    'baek': ['eddy', 'jin', 'hwoarang', 'heihachi'],
    'armorking': ['bryan', 'ganryu', 'king', 'heihachi'],
    'kunimitsu': ['lei', 'michelle', 'yoshimitsu', 'heihachi'],
    'michelle': ['kunimitsu', 'ganryu', 'julia', 'heihachi'],
    'ganryu': ['kuma', 'michelle', 'julia', 'heihachi'],
    'wang': ['lei', 'xiaoyu', 'kazuya', 'heihachi'],
    'jack2': ['kuma', 'pjack', 'gunjack', 'heihachi'],
    'pjack': ['bryan', 'jack2', 'gunjack', 'heihachi'],
    'roger': ['kuma', 'panda', 'alex', 'heihachi'],
    'alex': ['kuma', 'panda', 'roger', 'heihachi'],
    'tetsujin': ['tetsujin'] * 4,
}
# Tekken 3's own routes (B112), the overlay's table at 0x800B6378 read on the
# disc, the punch costume's: costumes only change Eddy's (Tiger: Eddy three
# times) and Kuma's (Panda: Kuma, Xiaoyu, Jin), and the bosses' outfits.
ROUTES.update({
    'paul': ['law', 'kuma', 'jin', 'heihachi'], 'law': ['paul', 'hwoarang', 'eddy', 'heihachi'],
    'lei': ['nina', 'hwoarang', 'bryan', 'heihachi'], 'king': ['lei', 'paul', 'nina', 'heihachi'],
    'yoshimitsu': ['yoshimitsu', 'mokujin', 'bryan', 'heihachi'], 'nina': ['jin', 'anna', 'anna', 'heihachi'],
    'hwoarang': ['eddy', 'law', 'jin', 'heihachi'], 'xiaoyu': ['lei', 'kuma', 'jin', 'heihachi'],
    'eddy': ['julia', 'gunjack', 'eddy', 'heihachi'], 'jin': ['paul', 'nina', 'hwoarang', 'heihachi'],
    'julia': ['king', 'eddy', 'jin', 'heihachi'], 'kuma': ['panda', 'xiaoyu', 'paul', 'heihachi'],
    'bryan': ['lei', 'gunjack', 'yoshimitsu', 'heihachi'], 'heihachi': ['eddy', 'julia', 'jin', 'heihachi'],
    'ogre': ['king', 'hwoarang', 'jin', 'heihachi'], 'mokujin': ['mokujin'] * 4,
    'gunjack': ['gunjack', 'yoshimitsu', 'bryan', 'heihachi'], 'gon': ['kuma', 'panda', 'mokujin', 'heihachi'],
    'anna': ['yoshimitsu', 'gunjack', 'nina', 'heihachi'], 'drb': ['nina', 'anna', 'bryan', 'heihachi'],
    'trueogre': ['king', 'hwoarang', 'jin', 'heihachi'], 'crow': ['heihachi'] * 4,
})
SCAN = (0x80056764, 0x80056900)
SOLDIER = 21


class PatientGame(Game):
    """The debug server answers "emu busy" while the game loads under load:
    asks again for up to 20 s before calling it a hang."""
    def q(self, **r):
        end = time.monotonic() + 20
        while True:
            try: return super().q(**r)
            except RuntimeError as e:
                if 'busy' not in str(e) or time.monotonic() > end:
                    raise AssertionError(f'the game hung ({r.get("cmd")}): {e}') from e
                time.sleep(.2)


def catalogue(build):
    """The guests, none in a build without mods/ttt1 (the mod off: Tekken 3's own routes)."""
    path = build / 'mods/ttt1/guests.txt'
    return [l.split()[0] for l in path.read_text().splitlines() if l.split()] if path.is_file() else []


def fighter_id(key, guests):
    """(ID, costume) of a key: Panda is Kuma's second costume."""
    if key == 'panda': return NATIVES.index('kuma'), 1
    if key in guests: return GUEST_ID + guests.index(key), 0
    return NATIVES.index(key), 0


def name_of(fid, guests):
    if fid >= GUEST_ID and fid - GUEST_ID < len(guests): return guests[fid - GUEST_ID]
    return NATIVES[fid] if fid < len(NATIVES) else f'id{fid}'


def pick(g, player, guests, ttt1=False):
    to_force_grid(g)
    if player in guests:
        k = guests.index(player)
        g.press(R2)
        g.wait(lambda: g.value(0x80118648) == len(guests), 'R2 did not open the Tag page', 10)
        time.sleep(1.5)
        place = lambda i: divmod(i, 8) if i < 16 else (i - 16, 8)
        row, col = place(k)
        for _ in range(20):
            r, c = place(g.value(0x80118650))
            if (r, c) == (row, col): break
            g.press(DOWN if r < row else UP if r > row else RIGHT if c < col else LEFT)
        want = GUEST_ID + k
    else:
        want = NATIVES.index(player)
        for _ in range(4):                     # row by row: right until the row wraps or stops, then down
            row = set()
            while g.value(fm.P1_FIGHTER) not in row | {want}:
                row.add(g.value(fm.P1_FIGHTER)); g.press(RIGHT)
            if g.value(fm.P1_FIGHTER) == want: break
            g.press(DOWN)
    g.wait(lambda: g.value(fm.P1_FIGHTER) == want, f'the grid cursor never reached {player}', 10)
    g.press(SQUARE)
    time.sleep(1)
    if 'P1 opens the MOVESET card' in g.log():
        if ttt1:
            g.press(RIGHT)
            g.wait(lambda: 'P1 highlights TTT1 moves' in g.log(), 'right did not switch to TTT1 moves', 5)
        g.press(CROSS)
    elif ttt1: raise AssertionError(f'{player} has no MOVESET card')
    g.wait(lambda: g.value(SCREEN) == 8 and g.value(PHASE, 2) >= 8, 'the stage never started', 120)
    got = g.value(ACTOR + 0x18, 2)
    assert got == want, f'player 1 is {name_of(got, guests)}, not {player}'


def dump_route(g, guests):
    """The route the overlay reads for player 1 (TIPS § 17): table base from
    its LUI / ADDIU pair at 0x800B2694 / 0x800B2698, entry ID * 4 + costume."""
    hi, lo = g.value(0x800b2694) & 0xffff, g.value(0x800b2698) & 0xffff
    base = (hi << 16) + (lo - 0x10000 if lo & 0x8000 else lo)
    sel = g.value(ACTOR + 0x18, 2) * 4 + (g.value(ACTOR + 0x14, 2) & 3)
    route = g.value(base + sel * 4)
    raw = bytes.fromhex(g.q(cmd='read_ram', addr=f'{route:08x}', len=16)['hex'])
    print(f'route table {base:#x}, selection {sel}, route {route:#x}: {raw.hex(" ")}', flush=True)
    return route


def registers(g):
    try: pc = g.q(cmd='get_registers').get('pc', 0)
    except Exception: return 0
    return int(pc, 16) if isinstance(pc, str) else pc


def observe(g, seconds, shots, tag):
    """The boss fight for that long: player 1 punches now and then."""
    boss = ACTOR + BOSS * ACTOR_SIZE
    records, in_scan, still, samples, hits = set(), 0, 0, 0, 0
    life0 = g.value(boss + 0x3f6, 2)
    full = g.value(LIFE, 2)
    lost = 0
    end, i, shot_at = time.monotonic() + seconds, 0, [seconds * f for f in (.2, .5, .8)]
    start = time.monotonic()
    while time.monotonic() < end:
        i += 1
        g.q(cmd='set_input', buttons=PUNCH if i % 6 < 2 else 0xffff)
        records.add(g.value(boss + 0x54))
        pc = registers(g)
        if SCAN[0] <= pc < SCAN[1]: in_scan += 1
        gpu = g.q(cmd='gpu_state')
        if not gpu.get('ws', {}).get('gte_verts', 1): still += 1
        samples += 1
        life = g.value(LIFE, 2)
        if life < full: lost += full - life; g.write(LIFE, full, 2)
        g.write(CLOCK, 0x7000, 2)
        if shots and shot_at and time.monotonic() - start >= shot_at[0]:
            shot_at.pop(0)
            g.q(cmd='screenshot', path=str(shots / f'{tag}-{3 - len(shot_at)}.png'))
        time.sleep(.05)
    g.q(cmd='set_input', buttons=0xffff)
    return dict(records=len(records), in_scan=in_scan, still=still, samples=samples,
                boss_damage=life0 - g.value(boss + 0x3f6, 2), player_damage=lost)


def run(g, player, stages, seconds, shots, guests, pokes=(), fast=False, ttt1=False):
    pick(g, player, guests, ttt1)
    route = ROUTES.get(player)
    results, met, in_boss, i, started, seen = [], 0, False, 0, time.monotonic(), set()
    stage, full = g.value(STAGE, 2), g.value(LIFE, 2)
    route_at = dump_route(g, guests)
    for p in pokes:                                    # STAGE=KEY: that boss, in RAM, for this run
        n, key = p.split('=')
        fid, costume = fighter_id(key, guests)
        g.write(route_at + 4 * (int(n) - 1), fid, 2)
        if costume: g.write(route_at + 4 * (int(n) - 1) + 2, costume, 2)
        route = list(route or ['?'] * 4); route[int(n) - 1] = key
    if pokes: dump_route(g, guests)
    end = time.monotonic() + 480 * stages
    while met < stages:
        if time.monotonic() > end: raise AssertionError(f'boss {met + 1} never came')
        screen, phase = g.value(SCREEN), g.value(PHASE, 2)
        if screen == 8 and phase >= 6:
            if g.value(LIFE, 2) < full: g.write(LIFE, full, 2)
            g.write(CLOCK, 0x7000, 2)
        # The boss comes in on phases 21..23, a window short enough to miss:
        # also the expected boss in actor 1 during the fight, once per stage.
        index = g.value(STAGE, 2) - 0xf
        boss = ACTOR + BOSS * ACTOR_SIZE
        expected = fighter_id(route[index], guests) if route and 0 <= index < len(route) else None
        boss_entry = screen == 8 and (21 <= phase <= 23 or phase == 8 and expected is not None and
                                      (g.value(boss + 0x18, 2), g.value(boss + 0x14, 2) & 3 if expected[1] else 0) == expected)
        if fast and screen == 8 and phase == 8 and not boss_entry:    # the enemies on the way go down at once
            for k in range(1, 8):                 # Force's soldiers (ID 21) only, alive: other slots hold leftovers
                a = ACTOR + k * ACTOR_SIZE
                if g.value(a + 0x18, 2) == SOLDIER and 0 < g.value(a + 0x3f6, 2) <= 400: g.write(a + 0x3f6, 0, 2)
        if boss_entry and not in_boss and index not in seen:
            seen.add(index)
            met += 1
            g.q(cmd='set_input', buttons=0xffff)
            g.wait(lambda: g.value(SCREEN) == 8 and g.value(PHASE, 2) == 8, f'boss {met}: the fight never started', 90)
            time.sleep(1)
            fid, costume = g.value(boss + 0x18, 2), g.value(boss + 0x14, 2) & 3
            got = name_of(fid, guests)
            if got == 'kuma' and costume == 1: got = 'panda'
            stage = g.value(STAGE, 2)
            m = observe(g, seconds, shots, f'{player}-{index + 1}-{got}')
            want = route[index] if route and 0 <= index < len(route) else '?'
            ok = got == want and m['in_scan'] < m['samples'] // 4 and m['still'] < m['samples'] // 4 and m['records'] >= 3
            line = dict(player=player, stage=index + 1, t=round(time.monotonic() - started), stage_id=hex(stage), boss=got,
                        costume=costume, expected=want, held=ok, **m)
            print(json.dumps(line), flush=True)
            results.append(line)
            if not ok: return results
            g.write(boss + 0x3f6, 0, 2)                                        # K.O.: on to the next stage
        in_boss = boss_entry
        i += 1
        g.q(cmd='set_input', buttons=WALK & PUNCH if i % 4 == 0 and not fast else WALK)
        time.sleep(.05)
    g.q(cmd='set_input', buttons=0xffff)
    return results


END_STATE, BEATEN = 15, 0x800afac9


def end_screen(g, shots, player):
    """The end screen (state 15) shows the bosses beaten from a byte list,
    ID * 4 + costume (0x800AFAC9), by the stock icon sheet: a guest there
    must have been given a stock fighter's slot (its face lent over it)."""
    g.wait(lambda: g.value(SCREEN) == END_STATE, 'the end screen never came', 60)
    time.sleep(2)
    beaten = [g.value(BEATEN + i, 1) for i in range(4)]
    if shots: g.q(cmd='screenshot', path=str(shots / f'{player}-end.png'))
    ok = all(b >> 2 < 22 for b in beaten)
    print(json.dumps(dict(player=player, end_screen=[b >> 2 for b in beaten], held=ok)), flush=True)
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--player', default='kazuya')
    ap.add_argument('--stages', type=int, default=1)
    ap.add_argument('--observe', type=float, default=20)
    ap.add_argument('--shots', default='')
    ap.add_argument('--build', default=str(ROOT / 'build-rel-lite'))
    ap.add_argument('--memcard-dir', default=str(ROOT / 'saves'), help='copied, never written')
    ap.add_argument('--end', action='store_true', help='after stage 4: the boss icons of the end screen')
    ap.add_argument('--fast', action='store_true', help='knock the ordinary enemies out on sight')
    ap.add_argument('--poke', action='append', default=[], help='STAGE=KEY: write that boss in RAM (test only)')
    ap.add_argument('--attract', action='store_true',
                    help='leave the attract on till one of its fights has a guest (B112: the way a player comes in)')
    ap.add_argument('--ttt1-moves', action='store_true', help='a native: take the TTT1 moves on the MOVESET card')
    ap.add_argument('--keep-log', default='', help='copy the game log there')
    a = ap.parse_args()
    build = Path(a.build)
    guests = catalogue(build)
    shots = Path(a.shots) if a.shots else None
    if shots: shots.mkdir(parents=True, exist_ok=True)
    g = PatientGame(build, Path(a.memcard_dir), {})
    try:
        if a.attract:
            g.wait(lambda: 'TTT1 characters: guest in the fight' in g.log(), 'no attract fight with a guest', 400)
        t0 = time.monotonic()
        results = run(g, a.player, a.stages, a.observe, shots, guests, a.poke, a.fast, a.ttt1_moves)
        print(f'{time.monotonic() - t0:.0f} s', flush=True)
        if a.end and len(results) == 4 and all(r['held'] for r in results) and not end_screen(g, shots, a.player):
            results.append(dict(held=False))
        bad = [r for r in results if not r['held']]
        print('FAIL' if bad or len(results) < a.stages else 'OK')
        sys.exit(1 if bad or len(results) < a.stages else 0)
    finally:
        if a.keep_log: Path(a.keep_log).write_text(g.log(), encoding='utf-8')
        g.stop()


if __name__ == '__main__':
    main()
