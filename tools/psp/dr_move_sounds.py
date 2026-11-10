#!/usr/bin/env python3
"""A native's Dark Resurrection move sounds, read from the player's ISO (F35: Jin).

Measured in DR (PPSSPP, SAS calls logged frame by frame; PSP-DR.md "F35", TIPS 238):
- cries: the character's bank (group +12, tools/psp/dr_sounds.py), played at the table's pitch;
  a move's `voiceclip` (+0x2C) names a cry as 0x20nn (sample n of the attack cries, image 1),
  else DR draws one of the first `pool` attack cries `odds` times in 256;
- swing (whoosh) and impact: samples of the common bank 4991, each at its own SAS pitch
  (0x1000 = 44 100 Hz), measured move by move (`moves` of the table), with rules for the moves
  not measured (`rules`);
- timed sounds of a move (extra property 0x815A at a frame: throws, Hell Sweep's follow-ups):
  0x2nnn / 0x3nnn a cry, 0x60nn / 0x70nn sample nn of 4991 at 16 000 Hz, 0x9000 a body falling.

Writes nothing of the game in the repository: the table (data/dr_sounds_<key>.json) holds numbers
only; the samples are decoded at install time from the player's ISO.

    python tools/psp/dr_move_sounds.py listen <key> <dir>    every sound of the table as WAV (44 100 Hz)
"""
import json, struct, sys, wave
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dr_iso as D
import dr_sounds as SND

OUT_RATE = 44100
COMMON_BANK = 4991
SOUND_BASE = 1200                 # .jus index of the first move sound (dr_sounds: 1024 laser, 1025 name, 1026+ lines, 1100+ commons)
MARK = 0x800                      # a marked sound: played from the pack (src/tekken3_ttt1_sfx.c SFX_MARK)
DR_DRAW = 0x2fff                  # DR's own draw of an attack cry (src/tekken3_ttt1_voices.c DR_DRAW)


def table(key):
    path = HERE / 'data' / f'dr_sounds_{key}.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None


KNEE = 0.75                       # soft limiter of the cries: linear below 75 % of full scale


def level(pcm, gain):
    """PCM s16 at `gain`, peaks past the knee bent smoothly under full scale (no hard clipping): DR's cries
    peak near full scale with less body than TTT1's, brought to TTT1's level (the user, 2026-11-10)."""
    import numpy as np
    x = np.frombuffer(pcm, '<i2').astype(np.float64) / 32768 * gain
    k = KNEE
    over = np.abs(x) > k
    x[over] = np.sign(x[over]) * (k + (1 - k) * np.tanh((np.abs(x[over]) - k) / (1 - k)))
    return np.clip(np.round(x * 32767), -32768, 32767).astype('<i2').tobytes()


def voices_juv(disc, t):
    """<Name>-DR-voices.juv: the bank by category (dr_sounds.juv) at the table's gain (TTT1's cries'
    level), DR's draw in header words 5 and 6."""
    v = t['voice']
    clips = [level(c, v.get('gain', 1.0)) for c in SND.samples(disc, v)]
    blob = bytearray(SND.juv(clips, v))
    struct.pack_into('<2I', blob, 20, v['pool'], v['odds'])
    return bytes(blob)


class Banks:
    """Decoded samples of the banks a sound uses: 'voice' (the character's +12) or a TKPDATA1 file."""
    def __init__(s, disc, t):
        s.disc, s.t, s.cache = disc, t, {}

    def sample(s, bank, n):
        key = (bank, n)
        if key not in s.cache:
            data = s.disc.file(D.group_of(s.t['voice']['dr']) + SND.VOICES if bank == 'voice' else int(bank))
            a, z = SND.split(data)[n]
            s.cache[key] = SND.decode(data[a:z])
        return s.cache[key]


def render(banks, layers):
    """A sound: its layers [bank, sample, SAS pitch, gain, delay in seconds] mixed, PCM s16 44 100 Hz."""
    import numpy as np
    out = np.zeros(0)
    for bank, n, pitch, gain, at in layers:
        rate = OUT_RATE * pitch / 0x1000
        x = np.frombuffer(SND.resample(banks.sample(bank, n), rate), '<i2').astype(np.float64) * gain
        start = int(round(at * OUT_RATE))
        if len(out) < start + len(x): out = np.pad(out, (0, start + len(x) - len(out)))
        out[start:start + len(x)] += x
    return np.clip(np.round(out), -32768, 32767).astype('<i2').tobytes()


def sounds(t):
    """The table's sounds in .jus index order: {name: index}."""
    return {name: SOUND_BASE + i for i, name in enumerate(sorted(t['sounds']))}


def jus(base, extra):
    """The base .jus (its TTT1 sounds, which the engine's own sounds and the moves left on TTT1 still
    play) with the extra entries {index: PCM}, in index order."""
    magic, _, _, n, rate = struct.unpack_from('<5I', base)
    if rate != OUT_RATE: raise SystemExit(f'base .jus at {rate} Hz')
    entries = {}
    for i in range(n):
        index, at, frames, driver = struct.unpack_from('<4I', base, 32 + 16 * i)
        entries[index] = (driver, base[at:at + 2 * frames])
    for index, pcm in extra.items():
        if index in entries: raise SystemExit(f'.jus index {index} already taken')
        if index >= MARK: raise SystemExit(f'.jus index {index} past the marked range')
        entries[index] = (0, pcm)
    blob = bytearray(32 + 16 * len(entries))
    for i, index in enumerate(sorted(entries)):
        driver, pcm = entries[index]
        struct.pack_into('<4I', blob, 32 + 16 * i, index, len(blob), len(pcm) // 2, driver)
        blob += pcm
    struct.pack_into('<8I', blob, 0, magic, 1, len(blob), len(entries), OUT_RATE, 0, 0, 0)
    return bytes(blob)


def sfx_entries(disc, t):
    """{.jus index: PCM} of the table's sounds."""
    banks, idx = Banks(disc, t), sounds(t)
    return {idx[name]: render(banks, layers) for name, layers in t['sounds'].items()}


def build(key, out, base_sfx, iso=None):
    """<Radical>-DR-voices.juv and <Radical>-DR-sfx.jus (the TTT1 .jus with the DR sounds) into out."""
    t = table(key)
    disc = D.Disc(iso or D.ISO)
    radical = t['radical']
    files = {f'{radical}-DR-voices.juv': voices_juv(disc, t),
             f'{radical}-DR-sfx.jus': jus(Path(base_sfx).read_bytes(), sfx_entries(disc, t))}
    for name, data in files.items():
        path = Path(out) / name
        path.unlink(missing_ok=True)                # a roster of hard links: never write through one
        path.write_bytes(data)
    return t


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--iso', type=Path, default=D.ISO)
    sp = ap.add_subparsers(dest='cmd', required=True)
    c = sp.add_parser('listen'); c.add_argument('key'); c.add_argument('out', type=Path)
    a = ap.parse_args()
    t = table(a.key); disc = D.Disc(a.iso); a.out.mkdir(parents=True, exist_ok=True)
    banks = Banks(disc, t)
    pcms = {f'sound-{name}': render(banks, layers) for name, layers in t['sounds'].items()}
    clips = [level(c, t['voice'].get('gain', 1.0)) for c in SND.samples(disc, t['voice'])]
    pcms.update({f'voice-{i:02d}': c for i, c in enumerate(clips)})
    for name, pcm in pcms.items():
        with wave.open(str(a.out / f'{name}.wav'), 'wb') as w:
            w.setparams((1, 2, OUT_RATE, 0, 'NONE', 'not compressed')); w.writeframes(pcm)
    print(len(pcms), 'WAV ->', a.out)


if __name__ == '__main__':
    main()
