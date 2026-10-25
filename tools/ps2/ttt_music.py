#!/usr/bin/env python3
"""The music of Tekken Tag Tournament's (PS2) in-engine endings, from the
disc, as raw PCM Tekken 3 can play in a cinematic (a .cine's `music`).

    ~/TekkenProject/venv-import/bin/python3 tools/ps2/ttt_music.py OUT.pcm [DISC.bin]

The music lives in TEKKEN.BIN as headerless PS-ADPCM, stereo interleaved by
1 024-byte blocks (left, right), 44 100 Hz; each piece opens on a pair of
loop-start flags (4) 1 024 bytes apart. The endings' piece starts inside a
longer stream, at disc sector 110 777 (found in the IOP's stream state of a
save state taken during Kazuya's ending), and runs to that stream's end,
sector 111 953. OUT.pcm: 16-bit little-endian stereo; OUT.wav next to it to
listen. Game data: keep both out of the repository.
"""
import sys, wave
from pathlib import Path
import numpy as np

FIRST, LAST = 110777, 111953            # disc sectors (MODE2/2352, 2 048 bytes of data each)
BLOCK, RATE = 1024, 44100
F0 = np.array([0, 60, 115, 98, 122]); F1 = np.array([0, 0, -52, -55, -60])


def decode(raw):
    """PS-ADPCM, 16-byte frames of 28 samples, into int16."""
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 16)
    shift = (fr[:, 0] & 15).astype(np.int32); shift[shift > 12] = 9
    flt = np.minimum(fr[:, 0] >> 4, 4)
    nib = np.empty((len(fr), 28), np.int32)
    nib[:, 0::2] = fr[:, 2:] & 15; nib[:, 1::2] = fr[:, 2:] >> 4
    s = (np.where(nib >= 8, nib - 16, nib) << 12) >> shift[:, None]
    out = np.empty(len(fr) * 28, np.int16); h1 = h2 = 0; k = 0
    for i in range(len(fr)):
        a, b = int(F0[flt[i]]), int(F1[flt[i]])
        for v in s[i].tolist():
            v += (h1 * a + h2 * b + 32) >> 6
            v = -32768 if v < -32768 else 32767 if v > 32767 else v
            out[k] = v; k += 1; h2 = h1; h1 = v
    return out


def main():
    out = Path(sys.argv[1])
    name = 'Tekken Tag Tournament (USA) (v1.00).bin'
    disc = sys.argv[2] if len(sys.argv) > 2 else next(
        (str(d / name) for d in (Path(__file__).resolve().parents[3] / 'discs', Path.home() / 'TekkenProject/discs')
         if (d / name).exists()), name)
    with open(disc, 'rb') as f:
        raw = b''
        for n in range(FIRST, LAST):
            f.seek(n * 2352 + 24); raw += f.read(2048)
    pairs = len(raw) // (2 * BLOCK)
    left = b''.join(raw[i * 2 * BLOCK:i * 2 * BLOCK + BLOCK] for i in range(pairs))
    right = b''.join(raw[i * 2 * BLOCK + BLOCK:(i + 1) * 2 * BLOCK] for i in range(pairs))
    pcm = np.stack([decode(left), decode(right)], 1)
    out.write_bytes(pcm.tobytes())
    with wave.open(str(out.with_suffix('.wav')), 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm.tobytes())
    print(f'{out}: {len(pcm) / RATE:.1f} s')


if __name__ == '__main__':
    main()
