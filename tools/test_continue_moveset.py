#!/usr/bin/env python3
"""Movesets across a Continue (B35, GH#54), without a player.

    python3 tools/test_continue_moveset.py [--change 0|1] [--mode arcade] [--continues 3] [--seed 1]

From Practice's selector save (slot 8, workspace/fixtures): the modes menu,
the mode, Xiaoyu on her TTT1 moves (MOVESET card), CPU MOVESET RANDOM with a
fixed seed. Player 1 loses (life 0) and continues with Start --continues
times, with CHARACTER CHANGE AT CONTINUE (0x80097F0A, read when the mode
starts) NO: the same fight again, or YES: through the selector, taking TTT1
again. Checks in the log: the player is never drawn for and never leaves the
TTT1 moves; the CPU keeps its draw over every Continue (the same fight
again), through the selector too. Build: build-rel-lite.
"""
import argparse, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live as L
from test_cpu_moveset_draw import MODES

START_SELECT, UP, CROSS, START = 0xfff6, 0xffef, 0xbfff, 0xfff7
RIGHT = 0xffdf
STATE, HUMAN, CHANGE, P1_LIFE = 0x800ae204, 0x800ae1f8, 0x80097f0a, 0x800a961c
SELECTOR, FIGHT = 9, 8
DRAW = re.compile(r'Native moves: CPU P(\d) fighter (\d+) draws \d+ choice\(s\) -> (\S+)')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--change', type=int, default=0, choices=[0, 1])
    ap.add_argument('--mode', default='arcade', choices=['arcade', 'timeattack', 'survival'])
    ap.add_argument('--continues', type=int, default=3)
    ap.add_argument('--seed', default='1')
    ap.add_argument('--build', default=str(L.ROOT / 'build-rel-lite'))
    a = ap.parse_args()
    s = L.Session(build=Path(a.build), slot=8,
                  env={'TEKKEN3_NATIVE_MOVES': '', 'TEKKEN3_CPU_MOVESET': 'random', 'TEKKEN3_CPU_MOVESET_SEED': a.seed})
    def snap():
        b = s.read(HUMAN, 16)
        return int.from_bytes(b[12:16], 'little'), b[0]
    def take_ttt1(first):
        s.press(CROSS); time.sleep(.5)
        if first: s.press(RIGHT); time.sleep(.3)     # the card remembers it after
        s.press(CROSS)
    try:
        s.wait(lambda: snap()[0] == SELECTOR, 'the Practice selector', 20); time.sleep(.5)
        s.press(START_SELECT); s.wait(lambda: snap()[0] == 4, 'the modes menu', 15); time.sleep(.8)
        s.write(CHANGE, a.change, 1)
        for _ in range(MODES[a.mode]): s.press(UP)
        for _ in range(10):
            if snap()[0] == SELECTOR: break
            s.press(CROSS); time.sleep(.5)
        s.wait(lambda: snap()[0] == SELECTOR, 'the selector', 15); time.sleep(1.5)
        take_ttt1(True)
        done, draws = 0, []
        while True:
            s.wait(lambda: snap() == (FIGHT, 1), 'the fight', 60); time.sleep(1.5)
            draws.append(len(DRAW.findall(s.log())))
            if done == a.continues: break
            while snap()[1]: s.write(P1_LIFE, 0); time.sleep(.05)  # loses: the countdown
            time.sleep(.5)
            s.q(cmd='set_input', buttons=START); time.sleep(.1); s.q(cmd='set_input', buttons=65535)
            done += 1
            if a.change:
                s.wait(lambda: snap()[0] == SELECTOR, 'the selector after the Continue', 30); time.sleep(1.5)
                take_ttt1(False)
        log = s.log()
    finally:
        s.stop()
    lines = DRAW.findall(log)
    print('CPU draws:', lines)
    print('draw count at each fight:', draws)
    assert not [l for l in lines if l[0] == '1'], 'player 1 was drawn for'
    assert 'P1 back to the native moveset' not in log, 'player 1 left the TTT1 moves'
    assert log.count('P1 Xiaoyu on the TTT1 moveset') == 1, 'player 1 TTT1 moves set again'
    expected = [draws[0]] * (a.continues + 1)
    assert draws == expected, f'CPU draws {draws}, expected {expected}'
    print('ok: player 1 kept TTT1 over', a.continues, 'Continues; the CPU kept its draw')

if __name__ == '__main__': main()
