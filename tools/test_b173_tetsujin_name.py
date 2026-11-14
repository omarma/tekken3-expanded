#!/usr/bin/env python3
"""The announcer calls Tetsujin's name (B173, GH#225).

    python tools/test_b173_tetsujin_name.py --case check --roster RUN/mods/ttt1
    python tools/test_b173_tetsujin_name.py --case play --exe RUN/Tekken_3_Expanded.exe --roster RUN/mods/ttt1
        [--guest tetsujin|tetsujin@lee|kunimitsu ...] [--wav FILE]

TTT1 has no name sample for Tetsujin: its select (8016F68C) asks the sound
driver for sound 0x120 (8016F9FC), which splices it from three samples
(tools/ttt1/sfx.py NAME_RAW). The import keeps the splice under index 1025 of
each of Tetsujin's sound packs, as every guest's name.

check (no game): every Tetsujin*-TTT1-sfx.jus of the catalogue holds index
  1025, about 0.9 s long (the splice: 0.15 + 0.16 + the end of "jin").
play: Practice from the selector save, the guest as player 1, the whole mix
  tapped (TEKKEN3_AUDIO_MIX_TAP, music off) from the selector to 5 s into the
  fight. The log must say "<Guest>: P1 announced name" (not "none in its
  pack"); the tapped audio must hold the pack's name: the best normalised
  correlation of its left channel with the pack's PCM is printed (1.0 = the
  same samples) and must reach 0.9. --wav keeps the tap.
Build: rel-lite (debug server lite).
"""
import argparse, os, struct, sys, wave
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt1')]

NAME = 1025
MAGIC = 0x3153554a


def pack_sounds(path):
    """{index: (frames, pcm bytes)} of a -sfx.jus."""
    d = Path(path).read_bytes()
    magic, _, size, count = struct.unpack_from('<4I', d)
    if magic != MAGIC or size != len(d): raise ValueError(f'{path}: not a sound pack')
    out = {}
    for i in range(count):
        index, offset, frames, _ = struct.unpack_from('<4I', d, 32 + 16 * i)
        out[index] = (frames, d[offset:offset + 2 * frames])
    return out


def check(a):
    failures, packs = [], sorted(Path(a.roster).glob('Tetsujin*-TTT1-sfx.jus'))
    if not packs: return ['no Tetsujin sound pack in the catalogue']
    for p in packs:
        s = pack_sounds(p).get(NAME)
        if not s: failures.append(f'{p.name}: no name (index {NAME})'); continue
        seconds = s[0] / 44100
        print(f'{p.name}: name {s[0]} samples ({seconds:.2f} s)')
        if not .7 < seconds < 1.2: failures.append(f'{p.name}: name {seconds:.2f} s, the splice is ~0.9 s')
    return failures


def correlation(tap, name):
    """Best normalised correlation of the name in the tap (mono s16 arrays)."""
    import numpy as np
    n = len(name)
    if len(tap) < n: return 0.0, 0
    f = 1 << int(np.ceil(np.log2(len(tap) + n)))
    num = np.fft.irfft(np.fft.rfft(tap, f) * np.conj(np.fft.rfft(name, f)), f)[:len(tap) - n + 1]
    energy = np.convolve(tap * tap, np.ones(n), 'valid')
    score = num / (np.sqrt(np.maximum(energy, 1)) * np.sqrt((name * name).sum()))
    k = int(np.argmax(score))
    return float(score[k]), k


def play(a):
    import numpy as np
    import combos as K
    roster = Path(a.roster).resolve()
    name = pack_sounds(next(roster.glob(f'{a.guest.split("@")[0].capitalize()}-TTT1-sfx.jus')))[NAME][1]
    os.environ['TEKKEN3_TTT1_ASSETS'] = str(roster)
    os.environ['TEKKEN3_AUDIO_MIX_TAP'] = '1'
    work = ROOT / 'workspace/b173-bench' / a.guest.replace('@', '-')
    (work / 'saves').mkdir(parents=True, exist_ok=True)
    (work / 'saves' / 'tekken3-sound.ini').write_text('music_volume=0\nsfx_volume=100\n')
    g = K.Game(Path(a.exe).resolve(), a.guest, work)
    failures = []
    try:
        g.q(dict(cmd='turbo', enabled=1))
        g.q(dict(cmd='savestate', op='load', slot=8))
        import time
        end = time.monotonic() + 60
        while g.u32(K.STATE) != 9:
            if time.monotonic() > end: raise RuntimeError('Practice selector not reached')
            time.sleep(.3)
        g.wait_frames(30)
        probe = str((work / 'probe.wav').resolve())
        first = int(g.q(dict(cmd='audio_wav', path=probe, tap=2, count=1))['tap_total'])
        for p in (0, 1):
            for move in [K.held(K.L)] + [K.held(K.R)] * 11 + [K.held(K.D)] + [K.held(K.R)] * 11:
                if g.u8(K.CURSOR + p) == K.JIN: break
                g.tap(move); g.wait_frames(6)
            g.tap(K.held(K.PAD[3])); g.wait_frames(30)
        for adr in K.CHOICE[0]: g.w8(adr, K.GUEST_ID)
        end, nudge = time.monotonic() + 240, time.monotonic() + 10
        while not (g.u32(K.STATE) == 8 and g.u16(K.ACTOR[1] + 0x3f6) > 0):
            if time.monotonic() > end: raise RuntimeError('fight not loaded')
            if g.u32(K.STATE) == 9 and time.monotonic() > nudge: g.tap(K.held(K.PAD[3])); nudge = time.monotonic() + 3
            time.sleep(.3)
        g.wait_frames(300)
        out = str(Path(a.wav or work / 'tap.wav').resolve())
        g.q(dict(cmd='audio_wav', path=out, tap=2, start=str(first)))
    finally:
        g.close()
    log = (work / 'game.log').read_text(errors='replace')
    calls = [l for l in log.splitlines() if 'announced name' in l]
    print(*calls, sep='\n')
    if not any('P1 announced name' in l and 'none in its pack' not in l for l in calls):
        failures.append('player 1\'s name not announced from its pack')
    with wave.open(out) as w:
        data = np.frombuffer(w.readframes(w.getnframes()), '<i2').astype(np.float64)
        ch = w.getnchannels()
    tap = data[0::ch]
    score, at = correlation(tap, np.frombuffer(name, '<i2').astype(np.float64))
    print(f'tap {len(tap) / 44100:.1f} s; the name best matches at {at / 44100:.2f} s, correlation {score:.3f}')
    if score < .9: failures.append(f'the name is not in the tapped audio (correlation {score:.3f})')
    return failures


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--case', default='check', choices=['check', 'play'])
    ap.add_argument('--roster', required=True)
    ap.add_argument('--exe')
    ap.add_argument('--guest', default='tetsujin')
    ap.add_argument('--wav')
    a = ap.parse_args()
    failures = check(a) if a.case == 'check' else play(a)
    for f in failures: print('FAIL', f)
    print('OK' if not failures else f'{len(failures)} failure(s)')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
