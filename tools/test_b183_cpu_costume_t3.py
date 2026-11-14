#!/usr/bin/env python3
"""B183 (GH#237): under CPU COSTUME = TEKKEN 3 the CPU's natives wear Tekken 3's costume, drawn
by the TTT1 model of that costume (RP punch, RK kick, Start third; Mokujin LP, LK; Anna LP, LK), never
one of the costumes TTT added.

    python tools/test_b183_cpu_costume_t3.py --mode arcade|timeattack|survival|team
        [--button square|cross|triangle|circle|start] [--costume tekken3|ttt] [--seed N]
        [--fights 9] [--mods <dir holding ttt1/>]

A private copy of the build (test_stage_options.Game: headless, software x1, keyboard pads, a copy
of saves/), TEKKEN3_CPU_COSTUME=--costume, TEKKEN3_CPU_MOVESET_SEED=--seed, TEKKEN3_NATIVE_MOVES=0
(no MOVESET card), turbo. Player 1 picks with --button; the CPU's life is emptied in each fight,
so that the run goes up the ladder. Each fight: the CPU's fighter and game costume, and the TTT1
model grafted on its side (the "<Name> (TTT1 model) model: costume k" line read before
"model: P<n> model header replaced"). FAIL under tekken3 if a CPU native's model is not its
costume's (P3 punch, P4 kick, P5 third; Mokujin P1, P2; Anna P1, P2), or (Arcade, Time Attack) its costume
not Tekken 3's rule: punch when the player is in the punch costume (square, triangle), kick
otherwise (Ogre and True Ogre punch); a mirror match only checks the model.
Anna (B188) is checked under --costume ttt too: red P1, blue P2, never drawn.
"""
import argparse, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_stage_options as S

FIGHTERS, COSTUMES, HUMAN = 0x800add5c, 0x800add98, 0x800ae1f8
BUTTONS = {'square': 0x7fff, 'cross': 0xbfff, 'triangle': 0xefff, 'circle': 0xdfff, 'start': 0xfff7, 'r1': 0xf7ff}
NATIVES = {0: 'Paul', 1: 'Law', 2: 'Lei', 3: 'King', 4: 'Yoshimitsu', 5: 'Nina', 6: 'Hwoarang', 7: 'Xiaoyu',
           8: 'Eddy', 9: 'Jin', 10: 'Julia', 11: 'Kuma', 12: 'Bryan', 13: 'Heihachi', 14: 'Ogre', 15: 'Mokujin',
           16: 'Gunjack', 18: 'Anna', 20: 'Trueogre'}
LOAD = re.compile(r'^(.+?) model: costume (\d)', re.M)
GRAFT = re.compile(r'^(.+?) model: P(\d) model header replaced', re.M)


def grafts(log):
    """[(player 1|2, name, model k)] in the log's order."""
    last, out = {}, []
    for line in log.splitlines():
        m = LOAD.match(line)
        if m: last[m[1]] = int(m[2]); continue
        m = GRAFT.match(line)
        if m and m[1] in last: out.append((int(m[2]), m[1], last[m[1]]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', default='arcade', choices=['arcade', 'timeattack', 'survival', 'team'])
    ap.add_argument('--button', default='cross', choices=list(BUTTONS))
    ap.add_argument('--costume', default='tekken3', choices=['tekken3', 'ttt'])
    ap.add_argument('--seed', default='1')
    ap.add_argument('--fights', type=int, default=9)
    ap.add_argument('--build', default=str(ROOT / 'build-rel-lite'))
    ap.add_argument('--mods', default='')
    ap.add_argument('--minutes', type=float, default=15)
    a = ap.parse_args()
    env = {'TEKKEN3_CPU_COSTUME': a.costume, 'TEKKEN3_CPU_MOVESET_SEED': a.seed, 'TEKKEN3_NATIVE_MOVES': '0',
           'TEKKEN3_STAGES': 't3', 'TEKKEN3_STAGES_TTT': '1', 'TEKKEN3_STAGES_SEED': a.seed}
    g = S.Game(Path(a.build), a.mods or None, env, f'b183-{a.mode}-{a.button}-{a.costume}-{a.seed}')
    rows, fails, decisions, loaded, picked = [], 0, 0, False, 0
    try:
        g.modes_menu(); g.mode(S.MODES[a.mode])
        g.wait(lambda: g.screen() in (9, 10), 'no selector'); time.sleep(2)
        g.q(cmd='turbo', enabled=1)
        end = time.monotonic() + a.minutes * 60
        while len(rows) < a.fights and time.monotonic() < end:
            s = g.screen()
            n = len(S.DECISION.findall(g.log()))
            if n > decisions: decisions, loaded = n, True
            if s in (9, 10):
                # The player's pick; Team Battle: its team size first (cross), then each member.
                g.press(BUTTONS[a.button] if picked or a.mode != 'team' else S.CROSS); picked += 1
                if a.mode == 'team': g.press(S.RIGHT)
            elif s == 8 and g.value(S.PHASE, 2) == 8:
                cpu = 1 if g.value(HUMAN + 2, 2) == 0 else 0
                fid, costume = g.value(FIGHTERS + 2 * cpu, 2), g.value(COSTUMES + 2 * cpu, 2) & 3
                pid, pcostume = g.value(FIGHTERS + 2 * (1 - cpu), 2), g.value(COSTUMES + 2 * (1 - cpu), 2) & 3
                if loaded:
                    loaded = False
                    time.sleep(.3)
                    side = [k for p, name, k in grafts(g.log()) if p == cpu + 1 and name.startswith(NATIVES.get(fid, '?') + ' (')]
                    model = side[-1] if side else None
                    verdict = ''
                    if a.costume == 'tekken3' and fid in NATIVES:
                        # Tekken 3's costume by its TTT1 model: RP, RK, Start (Anna, Mokujin: LP, LK).
                        tk = costume + 1 if fid == 15 else costume + 3
                        if fid == 18: tk = (1, 2, None)[costume]   # B188: red LP, blue LK; no TTT1 third
                        if costume >= 2 and fid in (5, 15): tk = None   # Nina's Anna, Mokujin's third
                        if model is None: verdict = 'FAIL (no TTT1 model)'
                        elif tk is not None and model != tk: verdict = f'FAIL (P{model}, want P{tk}: Tekken 3 costume {costume + 1})'
                        elif a.mode in ('arcade', 'timeattack') and fid != pid:
                            want = 0 if fid in (14, 20) or pcostume == 0 else 1
                            verdict = 'OK' if costume == want else f'FAIL (costume {costume + 1}, want {want + 1})'
                        else: verdict = 'OK'
                    elif fid == 18:   # B188: a CPU Anna wears Tekken 3's costume under TTT's draw too
                        tk = (1, 2, None)[costume]
                        verdict = 'OK' if tk is None or model == tk else f'FAIL (P{model}, want P{tk}: Anna, Tekken 3 costume {costume + 1})'
                    elif a.costume == 'tekken3' and fid >= 23:   # a guest: the game's costume
                        side = [k for p, name, k in grafts(g.log()) if p == cpu + 1]
                        model = side[-1] if side else None
                        # A guest with one costume (Tetsujin, Alex): "no costume k, costume 1 instead".
                        single = model == 1 and f'no costume {costume + 1}, costume 1 instead' in g.log()
                        verdict = 'OK' if model in (None, costume + 1) or single else f'FAIL (want P{costume + 1})'
                    if verdict.startswith('FAIL'): fails += 1
                    rows.append((fid, costume, model))
                    print(f'fight {len(rows)}: player {NATIVES.get(pid, pid)} costume {pcostume}, CPU P{cpu + 1} '
                          f'{NATIVES.get(fid, fid)} costume {costume}: model P{model} {verdict}', flush=True)
                if g.value(S.P2_LIFE if cpu else S.P1_LIFE, 2) > 0: g.write(S.P2_LIFE if cpu else S.P1_LIFE, 0, 2)
            elif s in (12, 16, 17): g.press(S.START)
            time.sleep(.2)
    finally:
        g.stop()
        for line in g.log().splitlines():
            if 'Native models: CPU' in line or 'CPU COSTUME' in line: print('log:', line)
    print(f'{a.mode} {a.button} {a.costume} seed {a.seed}: {len(rows)} fights, {fails} FAIL')
    if fails or not rows: sys.exit(1)


if __name__ == '__main__': main()
