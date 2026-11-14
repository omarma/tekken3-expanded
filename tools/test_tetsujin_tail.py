#!/usr/bin/env python3
"""Tetsujin's and Kinjin's tail on Roger's and Alex's moves (feat/tetsujin-tail, GH#223).

    python tools/test_tetsujin_tail.py --exe build-rel-lite/Tekken_3_Expanded.exe
        [--donor roger|kazuya|...] [--player 0|1] [--costume 0|2] [--moves "1" "d+4" ...] [--tag NAME]

The mod draws the tail from the .tail beside Tetsujin's models (tools/ttt1/tail.py) while the
drawn donor's moveset is Roger's (31, Alex's too). Same start as the B177 bench
(tools/test_b177_tetsujin_weapons.py): Practice from the selector save, the chosen side becomes the
Tetsujin guest, costume 0 (Tetsujin) or 2 (Kinjin), on the donor TEKKEN3_TETSUJIN_MOVESET forces.
Checks in the game's log (TEKKEN3_TAIL_LOG=1): the model read its tail, the round drew the donor,
the tail was drawn on Roger and never on another donor; prints the chain's root and tip and the
lowest bone every 30 frames. Screenshots go to workspace/tail-bench/<tag>. Build: rel-lite.
"""
import argparse, os, re, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt1')]
import test_b177_tetsujin_weapons as B


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--exe', required=True)
    ap.add_argument('--donor', default='roger')
    ap.add_argument('--player', type=int, default=0, choices=[0, 1])
    ap.add_argument('--costume', type=int, default=0, choices=[0, 2])
    ap.add_argument('--moves', nargs='*', default=['1', '3', '4', 'b+4', 'd+4', 'f+3+4'])
    ap.add_argument('--every', type=int, default=0, help='also a screenshot every N frames during each move')
    ap.add_argument('--tag')
    a = ap.parse_args()
    import combos as K
    os.environ.setdefault('TEKKEN3_TAIL_LOG', '1')
    exe = Path(a.exe).resolve()
    tag = a.tag or f'{a.donor}-p{a.player + 1}-c{a.costume}'
    work = ROOT / 'workspace/tail-bench' / tag
    g = B.start(exe, work, a.donor, a.player, a.costume)
    p = K.Probe(g, native=True)
    p.forward_is_right = lambda: True
    try:
        g.shot('guard.png')
        if a.player == 0:
            for n, cmd in enumerate(a.moves):
                steps = K.parse(cmd)
                name = re.sub(r'[^0-9a-z]+', '_', cmd.lower()).strip('_')
                tl = K.timeline(steps, [1] + [12] * (len(steps) - 1))
                if not a.every:
                    p.play(tl); g.shot(f'move{n}-{name}.png'); continue
                # during the move: a screenshot every `every` frames, for the tail's swing
                K.place(g)
                g.q(dict(cmd='input_route_clear'))
                for b, d, k in tl:
                    if k: g.q(dict(cmd='input_route_append', frames=int(k), buttons=int(K.pad(b, d, True))))
                g.q(dict(cmd='input_route_append', frames=60, buttons=K.NONE))
                g.q(dict(cmd='input_route_start'))
                nxt, shot = g.frame(), 0
                while g.q(dict(cmd='input_route_status')).get('active'):
                    if g.frame() >= nxt:
                        g.shot(f'move{n}-{name}-{shot:02d}.png'); shot += 1; nxt = g.frame() + a.every
                    time.sleep(.01)
        g.wait_frames(30)
    finally:
        g.close()
    text = (work / 'game.log').read_text(errors='replace')
    who = f'P{a.player + 1}'
    failures = []
    read = re.findall(r'Tetsujin model: tail of (\d+) segments on moves key (\d+)', text)
    print('tail read:', read)
    if not read: failures.append('the model did not read its tail')
    drew = re.findall(who + r' Tetsujin draws (\S+) at round start \(moveset (\d+)\)', text)
    print('round draws:', drew)
    if not drew or drew[-1][0].lower() != a.donor: failures.append(f'the round did not draw {a.donor}')
    shown = re.findall(who + r' body 15 tail: moves key (\d+)', text)
    print('tail drawn:', shown)
    if a.donor == 'roger' and not shown: failures.append('no tail drawn on Roger')
    if a.donor != 'roger' and shown: failures.append(f'a tail drawn on {a.donor}')
    for line in re.findall(r'tail ' + who + r': .*', text)[:12]: print(' ', line)
    for f in failures: print('FAIL', f)
    print('OK' if not failures else f'{len(failures)} failure(s)', '; shots in', work)
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
