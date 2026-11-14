#!/usr/bin/env python3
"""F37: Xiaoyu's hidden TTT1 costume (model 85, the cabinet's variant 7, file P8).

    python tools/test_f37_xiaoyu_random.py --case cpu|fill [--seeds 1-12] [--costume ttt|tekken3]
                                           [--build build-rel-lite] [--shot NAME]

No button picks it. Team Battle, each player a team of one, Start: the teams
are drawn (tools/test_f36_guest_costume.py's path).
  cpu   the CPU's member is made Xiaoyu (as F36 makes it a guest): with CPU
        COSTUME = TEKKEN TAG TOURNAMENT the log has "CPU P2 fighter 7 draws
        its <key> model among 6" (5 buttons and the random cell's), and the
        model read is that variant's ("model: costume <v + 1>", 8 for the
        random cell's); under TEKKEN 3, no draw.
  fill  player 1's first member, placed by the Random fill, is Xiaoyu
        (TEKKEN3_TEAM_FILL_NATIVE, src/tekken3_ttt1_roster.c): "P1 fighter 7 placed by the Random
        fill: its random cell's model | its costume's model", the model read
        costume 8 or the costume's.
One session per seed (TEKKEN3_CPU_MOVESET_SEED): prints each seed's result and
the tally; --shot NAME saves a capture of the fight of the first seed that drew
the random cell's model (workspace/ttt1-live/NAME.png). Exit status 1 on a
failure, or when no seed drew it (ttt / fill).
Headless, software renderer, keyboard only (never the player's pad).
"""
import argparse, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live as L

STATE, PHASE, MODE = 0x800AE204, 0x800AE224, 0x800AFA88
TEAMS, TEAM_STRIDE = 0x800AFA88 + 89, 13
FIGHTER, COSTUME = 0x800ADD5C, 0x800ADD98
XIAOYU = 7


def one(a, seed):
    s = L.Session(guest='jun', build=L.ROOT / a.build, line=2,
                  env={'TEKKEN3_NATIVE_MOVES': '0', 'TEKKEN3_CPU_COSTUME': a.costume,
                       'TEKKEN3_CPU_MOVESET_SEED': str(seed),
                       **({'TEKKEN3_TEAM_FILL_NATIVE': str(XIAOYU)} if a.case == 'fill' else {})})
    p = 1 if a.case == 'cpu' else 0
    try:
        if not s.boot: s.write(MODE, 2); s.write(PHASE, 0, 2); s.write(STATE, 10, 2)
        time.sleep(3)
        s.press(0xbfff); time.sleep(.8)                             # a team of one
        for _ in range(6):
            s.press(0xfff7)                                         # Start: the teams are drawn
            if s.value(STATE) != 10: break
            time.sleep(.8)
        s.wait(lambda: s.value(STATE) in (8, 11), 'no loading screen', 15)
        t0, start = time.monotonic(), None
        while time.monotonic() - t0 < 240:
            if s.process.poll() is not None: raise RuntimeError('the game exited')
            state, phase = s.value(STATE), s.value(PHASE, 2)
            if a.case == 'cpu' and (state == 11 or state == 8 and phase <= 3):
                if s.value(TEAMS + p * TEAM_STRIDE, 1) >> 2 != XIAOYU:   # the roster redrew it: again
                    s.write(TEAMS + p * TEAM_STRIDE, XIAOYU * 4, 1)
                    s.write(FIGHTER + 2 * p, XIAOYU, 2); s.write(COSTUME + 2 * p, 0, 2)
            elif state == 8 and phase == 8 and s.actor(p)[2] == XIAOYU:
                start = start or time.monotonic()
                if time.monotonic() - start > 4: break
            elif state not in (8, 9, 10, 11): s.press(0xfff7)
            time.sleep(.1)
        if start is None: raise RuntimeError("Xiaoyu's fight was not reached")
        log = s.log()
        shot = None
        if a.case == 'cpu':
            draws = re.findall(rf'CPU P2 fighter {XIAOYU} draws its (.+?) model among (\d)', log)
            keys = {'LP': 0, 'LK': 1, 'RP': 2, 'RK': 3, 'Start': 4, "random cell's": 7}
            drawn = [(keys[k], int(n)) for k, n in draws]
        else:
            fills = re.findall(rf'P1 fighter {XIAOYU} placed by the Random fill: (its \S+ cell\'s|its costume\'s) model', log)
            drawn = [(7 if 'cell' in f else 0, 6) for f in fills]
        # Xiaoyu's models read after the draw (both players' models are in the log).
        mark = rf'CPU P2 fighter {XIAOYU} draws' if a.case == 'cpu' else rf'P1 fighter {XIAOYU} placed by the Random fill'
        after = re.split(mark, log)[-1] if re.search(mark, log) else ''
        models = re.findall(r'Xiaoyu \(TTT1 model\) model: costume (\d+)', after)
        if not models and after:          # already in place: Xiaoyu's last model read before the draw
            models = re.findall(r'Xiaoyu \(TTT1 model\) model: costume (\d+)', log[:len(log) - len(after)])[-1:]
        return drawn, models, s, log
    except BaseException:
        s.stop(); raise


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--case', choices=('cpu', 'fill'), default='cpu')
    ap.add_argument('--seeds', default='1-12')
    ap.add_argument('--costume', choices=('ttt', 'tekken3'), default='ttt')
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--shot')
    a = ap.parse_args()
    lo, _, hi = a.seeds.partition('-')
    failures, tally, shot_done = [], {}, False
    p8 = (L.ROOT / a.build / 'mods/ttt1/Xiaoyu-Native-TTT1-arcade-P8.3dm').is_file()
    if not p8: failures.append('no Xiaoyu-Native-TTT1-arcade-P8.3dm in the build')
    for seed in range(int(lo), int(hi or lo) + 1):
        drawn, models, s, log = one(a, seed)
        try:
            last = int(models[-1]) if models else None
            if a.costume == 'tekken3' and a.case == 'cpu':
                if drawn: failures.append(f'seed {seed}: a draw under TEKKEN 3: {drawn}')
                v = 0
            elif len(drawn) < 1:
                failures.append(f'seed {seed}: no draw in the log'); v = None
            else:
                v, among = drawn[-1]
                # 5: the other side shows one of them (known_variant, never twice the same model).
                if a.case == 'cpu' and among not in (5, 6): failures.append(f'seed {seed}: drawn among {among}')
            # None: the drawn model was already in place (read before the draw), nothing read again.
            # fill without the random cell's: the costume's model, punch or kick (P1 or P2), never P8.
            if a.case == 'fill' and v == 0: bad = last not in (1, 2)
            else: bad = v is not None and last not in (v + 1, None)
            if bad:
                failures.append(f'seed {seed}: model read costume {last}, variant {v} drawn')
            tally[v] = tally.get(v, 0) + 1
            print(f'{a.case} seed {seed}: variant {v}, models read {models[-3:]}', flush=True)
            if a.shot and v == 7 and not shot_done:
                s.shot(a.shot); shot_done = True
                print('capture', L.WORK / (a.shot + '.png'))
        finally:
            s.stop()
    print('tally (variant: seeds)', dict(sorted((k if k is not None else -1, n) for k, n in tally.items())))
    if a.costume == 'ttt' and 7 not in tally: failures.append("no seed drew the random cell's model")
    for f in failures: print('ECHEC', f)
    print('OK' if not failures else 'ECHEC')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
