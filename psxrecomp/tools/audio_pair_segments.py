#!/usr/bin/env python3
"""audio_pair_segments.py - find the SAME musical content in two archived
ring dumps (runtime vs beetle attract cycles are phase-shifted) and emit the
best-matching aligned window pair for A/B analysis.

Method: concatenate each side's numbered arch WAVs into one continuous
timeline (they were dumped gaplessly with absolute start indices in the
filename). Compute a coarse spectral fingerprint sequence (log-mel-ish band
energies per 0.5 s hop), normalized-cross-correlate runtime-vs-beetle
fingerprints at every offset, take the best offset, and cut the overlapping
region (minus silent edges) from both sides to <out>/pair_runtime.wav and
<out>/pair_beetle.wav.

Usage: python audio_pair_segments.py <archive_dir> [--min-secs 20]
Requires numpy.
"""
import argparse
import glob
import os
import re
import sys
import wave

import numpy as np

HOP_S = 0.5
BANDS = 24

def load_side(archive_dir, side):
    files = []
    for p in glob.glob(os.path.join(archive_dir, f"{side}_arch*_*.wav")):
        m = re.search(rf"{side}_arch(\d+)_(\d+)\.wav$", p)
        if m:
            files.append((int(m.group(1)), int(m.group(2)), p))
    files.sort()
    chunks = []
    rate = 44100
    for _idx, _start, p in files:
        w = wave.open(p)
        rate = w.getframerate()
        n = w.getnframes()
        data = np.frombuffer(w.readframes(n), dtype=np.int16).reshape(-1, 2)
        w.close()
        chunks.append(data)
    if not chunks:
        raise SystemExit(f"no {side}_arch*.wav in {archive_dir}")
    return np.concatenate(chunks), rate

def fingerprint(x, rate):
    """Band-energy sequence, one row per HOP_S, log-compressed, per-row norm."""
    mono = x.astype(np.float32).mean(axis=1) / 32768.0
    hop = int(rate * HOP_S)
    nfft = 4096
    rows = []
    for i in range(0, len(mono) - nfft, hop):
        seg = mono[i:i + nfft] * np.hanning(nfft)
        mag = np.abs(np.fft.rfft(seg))
        # log-spaced band edges 60 Hz .. 16 kHz
        edges = np.geomspace(60, 16000, BANDS + 1) / (rate / 2) * (nfft // 2)
        band = np.array([mag[int(a):max(int(a) + 1, int(b))].mean()
                         for a, b in zip(edges[:-1], edges[1:])])
        rows.append(np.log1p(band * 1000.0))
    fp = np.array(rows)
    # per-row zero-mean so correlation keys on spectral SHAPE sequence
    fp -= fp.mean(axis=1, keepdims=True)
    n = np.linalg.norm(fp, axis=1, keepdims=True)
    fp /= np.maximum(n, 1e-9)
    return fp

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archive_dir")
    ap.add_argument("--min-secs", type=float, default=20.0)
    args = ap.parse_args()

    rt, rate = load_side(args.archive_dir, "runtime")
    bt, _ = load_side(args.archive_dir, "beetle")
    print(f"runtime: {len(rt)/rate:.0f}s  beetle: {len(bt)/rate:.0f}s")

    frt = fingerprint(rt, rate)
    fbt = fingerprint(bt, rate)

    # slide beetle over runtime (both directions), score mean row-dot
    best = (-1.0, 0)
    min_rows = int(args.min_secs / HOP_S)
    for off in range(-(len(fbt) - min_rows), len(frt) - min_rows):
        a0, b0 = max(0, off), max(0, -off)
        n = min(len(frt) - a0, len(fbt) - b0)
        if n < min_rows:
            continue
        score = float(np.einsum("ij,ij->i", frt[a0:a0 + n], fbt[b0:b0 + n]).mean())
        if score > best[0]:
            best = (score, off)
    score, off = best
    a0, b0 = max(0, off), max(0, -off)
    n = min(len(frt) - a0, len(fbt) - b0)
    print(f"best offset {off * HOP_S:+.1f}s score {score:.3f} overlap {n * HOP_S:.0f}s")

    # cut the overlapping window, trimming rows where either side is silent
    energy_rt = np.abs(rt[:, 0].astype(np.int32)) > 256
    energy_bt = np.abs(bt[:, 0].astype(np.int32)) > 256
    s_rt = int(a0 * HOP_S * rate)
    s_bt = int(b0 * HOP_S * rate)
    length = int(n * HOP_S * rate)
    cut_rt = rt[s_rt:s_rt + length]
    cut_bt = bt[s_bt:s_bt + length]

    def write(path, data):
        w = wave.open(path, "wb")
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.astype(np.int16).tobytes())
        w.close()
        print("wrote", path, f"{len(data)/rate:.0f}s")

    write(os.path.join(args.archive_dir, "pair_runtime.wav"), cut_rt)
    write(os.path.join(args.archive_dir, "pair_beetle.wav"), cut_bt)
    # rough level comparison on the matched content
    def rms_db(x):
        f = x.astype(np.float64) / 32768.0
        act = f[np.abs(f[:, 0]) > 0.001]
        if len(act) == 0:
            return -120.0
        return 20 * np.log10(np.sqrt((act ** 2).mean()))
    print(f"matched-content RMS: runtime {rms_db(cut_rt):.1f} dBFS, "
          f"beetle {rms_db(cut_bt):.1f} dBFS")

if __name__ == "__main__":
    main()
