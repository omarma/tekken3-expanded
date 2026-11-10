#!/usr/bin/env python3
"""Jin's DR move sounds (F35): DR's cries, swings and impacts on his DR moves, nothing else changed.

    python tools/test_f35_jin_dr_sounds.py --case check --roster RUN/mods/ttt1 [--expect-dr 1|0]
    python tools/test_f35_jin_dr_sounds.py --case play --exe RUN/Tekken_3_Expanded.exe --roster RUN/mods/ttt1
        [--moveset dr|ttt1|t3] [--moves "1" "1, 2" ...] [--expect-dr 1|0] [--wav DIR] [--log FILE] [--tag NAME]

check (no game): in the catalogue, no TTT1 pack's sounds list has a marked swing (category 6 with bit
  0x800: the only entry src/tekken3_ttt1_sfx.c reads for 0x604A) and no native has a voice bank but
  Jin-DR-voices.juv. With --expect-dr 1: Jin-DR-voices.juv is there, its draw set (header words 5, 6),
  and Jin-DR-combat.jmv's attacks carry DR's swings. With --expect-dr 0 (dev before F35, or no DR
  content): neither.
play: Practice from the selector save (slot 8, workspace/fixtures/ps1-saves), no player, Jin as player
  1 on the given moveset (tools/ttt1/combos.py start; ttt1 is TEKKEN3_NATIVE_MOVES=1), the dummy Jin on
  Tekken 3's moves. Each command from the same distance (combos.place), the sounds logged
  (TEKKEN3_TTT1_SOUND_LOG):
  - dr with --expect-dr 1: every cry of player 1 goes to the DR bank ("Jin voice:" after each "SOUNDLOG
    P1 voice", or DR's draw without a cry), every command swings with DR's sample;
  - otherwise (Jin on T3's or TTT1's moves, or a catalogue without F35): no DR line at all.
  The game's random draws (cries, T3's light impacts) and hit or miss differ from one run to the next:
  two runs are compared by these rules, not line by line (--log keeps the lines).
--wav DIR: each command's sound as heard (host tap 2 of the debug server), the music off.
Build: rel-lite (debug server lite).
"""
import argparse, os, re, struct, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt1')]

DEFAULT_MOVES = ['1', '1, 2', '2', '3', '4', 'd/f+1', 'd/f+2', 'f,N,d,d/f+2', 'f,N,d,d/f+1', '1+3', '2+4',
                 'u/f+1+2', 'b+1+2', 'f+2, 3, 3, 3, 2, 1, 2, 3, 4, 2']
SOUND = re.compile(r'SOUNDLOG P1 .*|Jin voice: P1 .*|TTT1 characters: P1 (?:swing|sound|engine sound|stop) .*')
DR_LINE = re.compile(r'Jin voice:|\(DR\)|DR draw')


def lists(pack):
    """{record: sounds list} of a combat pack."""
    import pack_edit
    p = pack_edit.Pack(Path(pack).read_bytes())
    out = {}
    for i in range(len(p.records)):
        a, l = p.word(i, 7), []
        if a >= p.data_at:
            o = a - p.data_at
            for k in range(4):
                v = struct.unpack_from('<H', p.data, o + 2 * k)[0]
                if v == 0xffff: break
                l.append(v)
        out[i] = l
    return out


def check(a):
    roster, failures = Path(a.roster), []
    marked = lambda l: any(v >> 12 == 6 and v & 0x800 for v in l)
    for pack in sorted(roster.glob('*-combat.jmv')):
        if pack.name.startswith('Jin-DR-'): continue
        n = sum(marked(l) for l in lists(pack).values())
        if n: failures.append(f'{pack.name}: {n} records with a marked swing')
    natives = {l.split()[1].capitalize() for l in (roster / 'natives.txt').read_text().splitlines() if len(l.split()) >= 3}
    for juv in roster.glob('*-voices.juv'):
        radical = juv.name.split('-')[0]
        if radical in natives and juv.name != 'Jin-DR-voices.juv': failures.append(f'{juv.name}: a native voice bank')
    juv, pack = roster / 'Jin-DR-voices.juv', roster / 'Jin-DR-combat.jmv'
    swings = sum(marked(l) for l in lists(pack).values()) if pack.is_file() else 0
    if a.expect_dr:
        if not juv.is_file(): failures.append('no Jin-DR-voices.juv')
        else:
            pool, odds = struct.unpack_from('<2I', juv.read_bytes(), 20)
            print(f'Jin-DR-voices.juv: draw among {pool} attack cries, {odds}/256')
            if not pool or not odds: failures.append('Jin-DR-voices.juv without DR\'s draw')
        print(f'Jin-DR-combat.jmv: {swings} records with DR\'s swing')
        if swings < 100: failures.append(f'Jin-DR-combat.jmv: {swings} records with DR\'s swing')
    else:
        if juv.is_file(): failures.append('Jin-DR-voices.juv present')
        if swings: failures.append(f'Jin-DR-combat.jmv: {swings} records with DR\'s swing')
    return failures


def gaps_for(cmd):
    """The measured timing of a string (tools/data/combos/dr-jin.json), else 12 frames between presses."""
    import json
    data = json.loads((ROOT / 'tools/data/combos/dr-jin.json').read_text(encoding='utf-8'))
    return next((c['gaps'] for c in data['combos'] if c['command'] == cmd), None)


def play(a):
    import subprocess
    import combos as K
    os.environ['TEKKEN3_DR_ROSTER'] = str(Path(a.roster).resolve())
    os.environ['TEKKEN3_TTT1_SOUND_LOG'] = '1'
    work = ROOT / 'workspace/f35-bench' / (a.tag or a.moveset)
    # combos.Game starts the game with TEKKEN3_NATIVE_MOVES=0 (Tekken 3's moves) or dr; ttt1 is =1
    # (every native in the fight on its TTT1 moves): the game's environment rewritten at its launch.
    popen = subprocess.Popen
    def launch(args, **kw):
        if a.moveset == 'ttt1' and kw.get('env'): kw['env'] = dict(kw['env'], TEKKEN3_NATIVE_MOVES='1')
        return popen(args, **kw)
    subprocess.Popen = launch
    if a.wav:                                   # the sounds alone: the music off (src: tekken3_sound_options.c)
        os.environ['TEKKEN3_AUDIO_MIX_TAP'] = '1'     # the whole mix in the host tap (src/tekken3_ttt1_voices.c)
        (work / 'saves').mkdir(parents=True, exist_ok=True)
        (work / 'saves' / 'tekken3-sound.ini').write_text('music_volume=0\nsfx_volume=100\n')
    try: g = K.start(Path(a.exe).resolve(), 'dr-jin' if a.moveset == 'dr' else None, work)
    finally: subprocess.Popen = popen
    p = K.Probe(g, native=True)
    # combos.place puts player 1 on the dummy's left: forward is right (the lite server has no
    # read_frame_ram for Probe.forward_is_right).
    p.forward_is_right = lambda: True
    out, failures, log = [], [], work / 'game.log'
    try:
        for cmd in a.moves:
            steps = K.parse(cmd)
            if not steps: failures.append(f'{cmd}: not parsed'); continue
            tl = K.timeline(steps, gaps_for(cmd) or [1] + [12] * (len(steps) - 1))
            mark = len(log.read_text(errors='replace'))
            if a.wav:
                probe = str((work / 'probe.wav').resolve())
                first = int(g.q(dict(cmd='audio_wav', path=probe, tap=2, count=1))['tap_total'])
            p.play(tl)
            if a.wav:
                Path(a.wav).mkdir(parents=True, exist_ok=True)
                name = Path(a.wav) / (re.sub(r'[^0-9a-z]+', '_', cmd.lower()).strip('_') + '.wav')
                g.q(dict(cmd='audio_wav', path=str(name.resolve()), tap=2, start=str(first)))
            lines = [m.group(0) for m in SOUND.finditer(log.read_text(errors='replace')[mark:])]
            out.append((cmd, lines))
            print(f'{cmd}:', *lines[:14], sep='\n  ', flush=True)
            dr = a.moveset == 'dr' and a.expect_dr
            if dr:
                for i, l in enumerate(lines):
                    if l.startswith('SOUNDLOG P1 voice') and not (i + 1 < len(lines) and lines[i + 1].startswith('Jin voice:')):
                        failures.append(f'{cmd}: a cry not from the DR bank ({l})')
                if not any(' swing ' in l for l in lines): failures.append(f'{cmd}: no DR swing')
            elif any(DR_LINE.search(l) for l in lines):
                failures.append(f'{cmd}: a DR sound on {a.moveset} moves')
    finally:
        g.close()
    if a.log: Path(a.log).write_text(''.join(f'== {c}\n' + ''.join(l + '\n' for l in ls) for c, ls in out))
    return failures


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--case', default='play', choices=['check', 'play'])
    ap.add_argument('--exe')
    ap.add_argument('--roster', required=True)
    ap.add_argument('--moveset', default='dr', choices=['dr', 'ttt1', 't3'])
    ap.add_argument('--moves', nargs='+', default=DEFAULT_MOVES)
    ap.add_argument('--expect-dr', type=int, default=1, choices=[0, 1])
    ap.add_argument('--wav')
    ap.add_argument('--log')
    ap.add_argument('--tag', help='work folder name (default: the moveset)')
    a = ap.parse_args()
    failures = check(a) if a.case == 'check' else play(a)
    for f in failures: print('FAIL', f)
    print('OK' if not failures else f'{len(failures)} failure(s)')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
