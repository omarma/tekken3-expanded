#!/usr/bin/env python3
"""Tetsujin's metal with Down held at round start (B174).

    python tools/test_b174_tetsujin_metal.py --exe RUN/Tekken_3_Expanded.exe [--down 1|0] [--pad1]
        [--moves "1" "2" ...] [--wav DIR] [--tag NAME]

Practice from the selector save (slot 8, workspace/fixtures/ps1-saves): Jin as player 1, the dummy
(player 2) is the Tetsujin guest (its ID 23 written at 0x800ADD5E while the fight loads). The lite
debug server has no pad 2: with --down 1, TEKKEN3_TETSUJIN_DOWN=2 makes the round start (0x8002A914,
where T3 reads Down for Mokujin's wood) count Down as held for player 2. --pad1: Tetsujin is player 1
instead, Down really held on pad 1 through the loading; only the round start's reading is checked.
Player 1 then plays each command from the same distance. The sounds are logged (TEKKEN3_TTT1_SOUND_LOG).
  --down 1: the game says "Tetsujin round start, Down held", every hit on the dummy plays T3's metal
    (0x705D, 0x7098 / 0x7099, answered by hit_sfx_metal 0x80041B70) and no flesh impact
    (0x7000..0x704C on player 2's side from the hit handler), every guard plays 0x705D;
  --down 0: "Down not held", no metal at all.
--wav DIR: each command's sound as heard (host tap 2), the music off.
Build: rel-lite (debug server lite).
"""
import argparse, os, re, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt1')]

DEFAULT_MOVES = ['1', '2', '3', '4', 'd/f+1', 'd/f+2', 'f,N,d,d/f+2', 'b+1+2']
LINE = re.compile(r'SOUNDLOG P\d .*|TTT1 characters: P\d (?:Tetsujin|metal hit|engine sound).*')
METAL = {0x705D, 0x7098, 0x7099}


def start(exe, work, down, player=1):
    """combos.start with Tetsujin as `player`; with down and player 0, Down held on pad 1 through the loading."""
    import combos as K
    os.environ.pop('TEKKEN3_TETSUJIN_DOWN', None)
    if down and player: os.environ['TEKKEN3_TETSUJIN_DOWN'] = '2'
    g = K.Game(exe, 'tetsujin', work, player=player)
    try:
        g.q(dict(cmd='turbo', enabled=1))
        g.q(dict(cmd='savestate', op='load', slot=8))
        end = time.monotonic() + 60
        while g.u32(K.STATE) != 9:
            if time.monotonic() > end: raise RuntimeError('Practice selector not reached')
            time.sleep(.3)
        g.wait_frames(30)
        for p in (0, 1):
            for move in [K.held(K.L)] + [K.held(K.R)] * 11 + [K.held(K.D)] + [K.held(K.R)] * 11:
                if g.u8(K.CURSOR + p) == K.JIN: break
                g.tap(move); g.wait_frames(6)
            g.tap(K.held(K.PAD[3])); g.wait_frames(30)
        end, nudge = time.monotonic() + 240, time.monotonic() + 10
        while not (g.u32(K.STATE) == 8 and g.u16(K.ACTOR[1] + 0x3f6) > 0):
            # The loading screen reads each player's ID at 0x800ADD5C (one half per player).
            if g.u32(K.STATE) == 11:                 # no sleep: the window is short
                g.q(dict(cmd='write_ram', addr=f'{0x800add5c + 2 * player:08x}', bytes=K.GUEST_ID.to_bytes(2, 'little').hex()))
                continue
            if down and not player: g.q(dict(cmd='press', buttons=K.held(K.D), frames=60))
            if time.monotonic() > end: g.shot('not-loaded.png'); raise RuntimeError('fight not loaded')
            if g.u32(K.STATE) == 9 and time.monotonic() > nudge: g.tap(K.held(K.PAD[3])); nudge = time.monotonic() + 3
            time.sleep(.2)
        if down and not player: g.q(dict(cmd='press', buttons=K.NONE, frames=2))
        g.wait_frames(120)
        g.q(dict(cmd='turbo', enabled=0))
        for attempt in range(8):
            g.tap(K.held(K.PAD[3])); g.wait_frames(60)
            before = g.u32(K.ACTOR[0] + 0x54)
            g.route([(4, K.held(K.PAD[1])), (6, K.NONE)])
            if g.u32(K.ACTOR[0] + 0x54) != before: break
            g.wait_frames(30)
        else:
            raise RuntimeError('1P FREESTYLE not reached')
        g.wait_frames(60)
        return g
    except Exception:
        g.close(); raise


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--exe', required=True)
    ap.add_argument('--down', type=int, default=1, choices=[0, 1])
    ap.add_argument('--pad1', action='store_true')
    ap.add_argument('--moves', nargs='+', default=DEFAULT_MOVES)
    ap.add_argument('--wav')
    ap.add_argument('--tag')
    a = ap.parse_args()
    import combos as K
    os.environ['TEKKEN3_TTT1_SOUND_LOG'] = '1'
    work = ROOT / 'workspace/b174-bench' / (a.tag or f'down{a.down}' + ('-pad1' if a.pad1 else ''))
    if a.wav:
        os.environ['TEKKEN3_AUDIO_MIX_TAP'] = '1'
        (work / 'saves').mkdir(parents=True, exist_ok=True)
        (work / 'saves' / 'tekken3-sound.ini').write_text('music_volume=0\nsfx_volume=100\n')
    who = 'P1' if a.pad1 else 'P2'
    for attempt in range(4):                    # the ID written while loading can miss its window
        g = start(Path(a.exe).resolve(), work, a.down, 0 if a.pad1 else 1)
        if f'{who} Tetsujin round start' in (work / 'game.log').read_text(errors='replace'): break
        print('Tetsujin not loaded, again'); g.close()
    p = K.Probe(g, native=True)
    p.forward_is_right = lambda: True
    log, failures = work / 'game.log', []
    try:
        text = log.read_text(errors='replace')
        said = re.findall(who + r' Tetsujin round start, Down (held|not held)', text)
        print('round start:', said)
        if not said: failures.append('no Tetsujin round start line')
        elif said[-1] != ('held' if a.down else 'not held'): failures.append(f'round start read Down as {said[-1]}')
        for cmd in ([] if a.pad1 else a.moves):
            steps = K.parse(cmd)
            tl = K.timeline(steps, [1] + [12] * (len(steps) - 1))
            mark = len(log.read_text(errors='replace'))
            if a.wav:
                probe = str((work / 'probe.wav').resolve())
                first = int(g.q(dict(cmd='audio_wav', path=probe, tap=2, count=1))['tap_total'])
            p.play(tl)
            if a.wav:
                Path(a.wav).mkdir(parents=True, exist_ok=True)
                name = Path(a.wav) / (re.sub(r'[^0-9a-z]+', '_', cmd.lower()).strip('_') + '.wav')
                g.q(dict(cmd='audio_wav', path=str(name.resolve()), tap=2, start=str(first)))
            lines = [m.group(0) for m in LINE.finditer(log.read_text(errors='replace')[mark:])]
            print(f'{cmd}:', *lines[:16], sep='\n  ', flush=True)
            events = [(int(m.group(1)), int(m.group(2), 16), int(m.group(3), 16)) for m in
                      re.finditer(r'SOUNDLOG P(\d) ([0-9A-F]{4}) ra=([0-9A-F]{8})', '\n'.join(lines))]
            # The log line is written before the mod's choice: the metal is hit_sfx_metal's answer
            # (returning to 0x80041C2C), the flesh is hit_sfx_impact's (0x80041CB4..0x80041F4C).
            metal = [e for e in events if e[0] == 2 and e[1] in METAL and e[2] == 0x80041C2C]
            flesh = [e for e in events if 0x80041CB4 <= e[2] < 0x80041F4C]
            guard = [e for e in events if e[2] in (0x8004127C, 0x8004129C)]
            guard_metal = [l for l in lines if 'Tetsujin metal 705D (was 704' in l]
            if a.down:
                if flesh: failures.append(f'{cmd}: flesh impact on Tetsujin {[hex(e[1]) for e in flesh]}')
                if len(guard_metal) != len(guard): failures.append(f'{cmd}: {len(guard)} guards, {len(guard_metal)} metal')
                # A hit makes the dummy cry (voice 3xxx): one without metal is a failure, a miss is not.
                cried = any(re.match(r'SOUNDLOG P2 voice 3', l) for l in lines)
                if cried and not metal and not guard: failures.append(f'{cmd}: hit without metal')
                if not cried and not metal and not guard: print('  (missed)')
            elif metal or guard_metal: failures.append(f'{cmd}: metal without Down')
            print(f'  -> metal hits {len(metal)}, guards {len(guard)} (metal {len(guard_metal)}), flesh {len(flesh)}')
    finally:
        g.close()
    for f in failures: print('FAIL', f)
    print('OK' if not failures else f'{len(failures)} failure(s)')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
