#!/usr/bin/env python3
"""audio_analyze.py - turn a recomp_audio_debug dump into a 'first dirty tap' verdict.

Reads a dump directory written by recomp_audio_debug_dump():
    <tap>.wav   (one per tap; names like t0_pulse1, t1_emu, t2_bridge_in,
                 t3_bridge_out, t4_callback)
    events.csv  (t_ms,type,metadata)
    summary.txt

Runs the detectors from the round-2 plan and applies the cross-tap decision tree:
    anomaly in T1            -> synthesis / upstream
    T2 but not T1            -> per-system conversion / decimation
    T3 but not T2            -> shared bridge / resampler
    only T4                  -> SDL callback fill / conversion / starvation

Usage:
    python audio_analyze.py <dump_dir> [--block 735] [--click-k 6.0]

Only dependency is numpy.
"""
import os, sys, wave, struct, glob, argparse
import numpy as np


def load_wav(path):
    with wave.open(path, "rb") as w:
        ch = w.getnchannels()
        rate = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch)
        mono = x.mean(axis=1)
    else:
        mono = x
    return mono, rate, ch


def discontinuity(x, rate, k=6.0, rms_ms=10.0):
    """Return (click_indices, click_score array). A click = isolated |d1|/|d2|
    spike that towers over the local RMS."""
    if x.size < 4:
        return np.array([], dtype=int), np.array([])
    d1 = np.abs(np.diff(x, prepend=x[0]))
    d2 = np.abs(np.diff(x, n=2, prepend=[x[0], x[0]]))
    win = max(8, int(rate * rms_ms / 1000.0))
    # rolling RMS via cumulative sum of squares
    cs = np.cumsum(np.concatenate([[0.0], x * x]))
    lo = np.maximum(0, np.arange(x.size) - win)
    hi = np.minimum(x.size, np.arange(x.size) + win)
    local_rms = np.sqrt((cs[hi] - cs[lo]) / np.maximum(1, hi - lo))
    eps = 1e-4
    score = np.maximum(d1, d2) / np.maximum(local_rms, eps)
    idx = np.where(score > k)[0]
    # keep only isolated spikes (gap >= 3 samples) to avoid counting one event many times
    if idx.size:
        keep = [idx[0]]
        for i in idx[1:]:
            if i - keep[-1] >= 3:
                keep.append(i)
        idx = np.array(keep, dtype=int)
    return idx, score


def repeat_runs(x):
    """Longest run of identical consecutive samples, and count of runs >= 4."""
    if x.size < 2:
        return 0, 0
    same = np.diff(x) == 0.0
    longest = cur = 0
    runs4 = 0
    for s in same:
        if s:
            cur += 1
            longest = max(longest, cur)
        else:
            if cur + 1 >= 4:
                runs4 += 1
            cur = 0
    if cur + 1 >= 4:
        runs4 += 1
    return longest + (1 if longest else 0), runs4


def boundary_hist(click_idx, block):
    """Fraction of clicks within +/-2 samples of a block boundary."""
    if click_idx.size == 0 or block <= 0:
        return 0.0, None
    mod = click_idx % block
    near = np.sum((mod <= 2) | (mod >= block - 2))
    return near / click_idx.size, mod


def fft_signature(x, rate):
    """Return dominant peaks and a crude aliasing/broadband read."""
    if x.size < 2048:
        return {}
    n = 1 << int(np.floor(np.log2(min(x.size, 1 << 18))))
    seg = x[:n] * np.hanning(n)
    mag = np.abs(np.fft.rfft(seg))
    freqs = np.fft.rfftfreq(n, 1.0 / rate)
    mag_db = 20 * np.log10(np.maximum(mag, 1e-9))
    nyq = rate / 2.0
    # broadband floor = median of upper half; peak = max
    upper = mag_db[freqs > nyq * 0.5]
    floor_db = float(np.median(upper)) if upper.size else -120.0
    peak_db = float(np.max(mag_db))
    # top 5 peaks
    order = np.argsort(mag_db)[::-1]
    peaks = []
    seen = []
    for i in order:
        f = freqs[i]
        if any(abs(f - s) < rate / n * 8 for s in seen):
            continue
        seen.append(f)
        peaks.append((round(float(f), 1), round(float(mag_db[i]) - peak_db, 1)))
        if len(peaks) >= 5:
            break
    near_nyq = float(np.max(mag_db[freqs > nyq * 0.85]) - peak_db) if np.any(freqs > nyq * 0.85) else -120.0
    return {"floor_dbfs_rel": round(floor_db - peak_db, 1),
            "near_nyquist_rel": round(near_nyq, 1),
            "peaks": peaks}


def canonical(tapname):
    n = tapname.lower()
    for t in ("t0", "t1", "t2", "t3", "t4"):
        if n.startswith(t) or ("_" + t) in n:
            return t
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump_dir")
    ap.add_argument("--block", type=int, default=735,
                    help="synthesis block size for boundary correlation (NES=735)")
    ap.add_argument("--click-k", type=float, default=6.0)
    args = ap.parse_args()

    wavs = sorted(glob.glob(os.path.join(args.dump_dir, "*.wav")))
    if not wavs:
        print("no .wav stems in", args.dump_dir)
        return 2

    print("=" * 78)
    print("recomp audio analysis:", args.dump_dir)
    print("=" * 78)

    per_tap = {}
    for path in wavs:
        name = os.path.splitext(os.path.basename(path))[0]
        x, rate, ch = load_wav(path)
        dur = x.size / rate if rate else 0
        idx, score = discontinuity(x, rate, k=args.click_k)
        cps = idx.size / dur if dur else 0.0
        longest, runs4 = repeat_runs(x)
        frac_b, _ = boundary_hist(idx, args.block)
        sig = fft_signature(x, rate)
        per_tap[name] = dict(rate=rate, ch=ch, dur=dur, clicks=idx.size, cps=cps,
                             longest_repeat=longest, runs4=runs4, frac_boundary=frac_b,
                             sig=sig, canon=canonical(name))
        print(f"\n[{name}]  rate={rate} ch={ch} dur={dur:.2f}s")
        print(f"  clicks={idx.size} ({cps:.2f}/s)   longest_repeat={longest}   "
              f"repeat_runs>=4: {runs4}")
        if idx.size:
            print(f"  clicks within +/-2 of {args.block}-sample boundary: {frac_b*100:.0f}%")
        if sig:
            print(f"  fft: floor={sig['floor_dbfs_rel']}dB  near-Nyquist={sig['near_nyquist_rel']}dB")
            print(f"       peaks(rel dB): {sig['peaks']}")

    # ---- cross-tap decision tree ----
    print("\n" + "=" * 78)
    print("CROSS-TAP VERDICT")
    print("=" * 78)

    def dirty(canon):
        # a canonical stage is "dirty" if any tap mapped to it has a meaningful click rate
        worst = 0.0
        for n, d in per_tap.items():
            if d["canon"] == canon:
                worst = max(worst, d["cps"])
        return worst

    THR = 0.5  # clicks/sec considered meaningful
    t1, t2, t3, t4 = dirty("t1"), dirty("t2"), dirty("t3"), dirty("t4")
    print(f"  stage click rates (clicks/s): T1={t1:.2f} T2={t2:.2f} T3={t3:.2f} T4={t4:.2f}")

    verdict = None
    if t1 > THR:
        verdict = ("T1", "synthesis / upstream — the emulated console/APU/HLE is "
                   "producing discontinuous PCM. Fix the generator, not the bridge.")
    elif t2 > THR:
        verdict = ("T2", "per-system conversion / decimation / staging between native "
                   "synthesis and the bridge input.")
    elif t3 > THR:
        verdict = ("T3", "shared bridge / resampler (ratio jumps, phase reset, "
                   "emergency fade, input starvation).")
    elif t4 > THR:
        verdict = ("T4", "SDL callback path (underfill, memset/zero fill, callback "
                   "starvation, format mismatch).")

    if verdict:
        print(f"\n  >>> FIRST DIRTY TAP: {verdict[0]}\n      {verdict[1]}")
    else:
        print("\n  >>> No impulse-class clicks above threshold in any canonical tap.")
        print("      If the user still hears static, it is NOT impulse crackle —")
        print("      check aliasing (near-Nyquist energy), level/clipping, or tuning.")

    # boundary hint
    for n, d in per_tap.items():
        if d["clicks"] and d["frac_boundary"] > 0.6:
            print(f"\n  NOTE: in [{n}], {d['frac_boundary']*100:.0f}% of clicks sit on a "
                  f"{args.block}-sample boundary -> block-generation discontinuity "
                  f"(fix continuous phase/time accumulator).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
