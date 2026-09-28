#!/usr/bin/env python3
"""audio_ab_diff.py - drift-tolerant A/B comparison of recomp audio vs an
accuracy-grade emulator reference.

WHY drift-tolerant (not bit-exact): the SNES recomp drives its SPC700/S-DSP on
a *synthetic* clock (cpu_state.c pace_cycles = +256 master cycles per HW-register
touch, converted to APU cycles), not a real cycle count. So even a perfect DSP
will phase-drift against hardware. A sample-exact diff is therefore meaningless
here; what matters is whether the *music* matches: same notes, same onsets, same
pitch, same timbre, with bounded time drift. This tool measures exactly those.

Inputs are two WAVs at (possibly) different native rates:
  - REF  : the oracle. Best = bsnes Accuracy via tools/snesref (embeds blargg's
           cycle-exact S-DSP). bsnes libretro emits 48000 Hz.
  - TEST : the recomp. Dump its always-on native PCM ring (32040 Hz) via the
           debug server:  audio_wav <path>   (runner/src/audio_trace.c).

Both are resampled to a common rate (default 32040; SNES content is band-limited
well below 16 kHz so nothing is lost). Then:
  1. global alignment   - FFT cross-correlation -> best lag + peak correlation
  2. drift             - per-window local lag; a growing lag = clock/tempo drift
                          (reported as ms/s and ppm). This is the headline SNES
                          metric: it quantifies "off-cue".
  3. onset timing      - spectral-flux onsets matched across streams -> timing
                          error distribution (median / IQR / p90), in ms.
  4. pitch / tuning    - dominant-pitch track ratio in cents -> "off-tune".
  5. timbre            - log-spectral distance + spectral-centroid delta.
  6. per-stream quality- click rate + noise floor (reused round-2 detectors).

Only dependency is numpy. Usage:
    python audio_ab_diff.py --ref REF.wav --test TEST.wav [--rate 32040]
                            [--start-s 0] [--dur-s 10] [--json out.json]
"""
import sys, os, wave, argparse, json
import numpy as np


# ----------------------------------------------------------------------------- io
def load_wav(path):
    """Robust WAV loader: tolerates an UNFINALIZED header (data-size==0 or wrong)
    from a force-killed capture by taking all bytes after the data chunk start.
    Falls back to raw parse if the stdlib wave module rejects the header."""
    try:
        with wave.open(path, "rb") as w:
            ch, rate, n = w.getnchannels(), w.getframerate(), w.getnframes()
            raw = w.readframes(n)
        if len(raw) >= (n * ch * 2) and n > 0:
            x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
            return (x.reshape(-1, ch).mean(axis=1) if ch > 1 else x), rate
    except Exception:
        pass
    # manual parse
    b = open(path, "rb").read()
    assert b[:4] == b"RIFF" and b[8:12] == b"WAVE", "not a WAV"
    ch, rate, bits, off = 2, 32040, 16, 12
    data_off, data_len = None, 0
    while off + 8 <= len(b):
        cid = b[off:off + 4]; sz = int.from_bytes(b[off + 4:off + 8], "little"); body = off + 8
        if cid == b"fmt ":
            ch = int.from_bytes(b[body + 2:body + 4], "little")
            rate = int.from_bytes(b[body + 4:body + 8], "little")
            bits = int.from_bytes(b[body + 14:body + 16], "little")
        elif cid == b"data":
            data_off = body
            data_len = sz if 0 < sz <= len(b) - body else (len(b) - body)
            break
        off = body + sz + (sz & 1)
    raw = b[data_off:data_off + (data_len - data_len % (ch * (bits // 8)))]
    x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    return (x.reshape(-1, ch).mean(axis=1) if ch > 1 else x), rate


def resample_linear(x, src, dst):
    if src == dst or x.size == 0:
        return x
    n_out = int(round(x.size * dst / src))
    t = np.arange(n_out) * (src / dst)
    i0 = np.floor(t).astype(int)
    i0 = np.clip(i0, 0, x.size - 2)
    frac = t - i0
    return x[i0] * (1.0 - frac) + x[i0 + 1] * frac


def active_region(x, thr=1e-4):
    nz = np.where(np.abs(x) > thr)[0]
    if nz.size == 0:
        return 0, x.size
    return int(nz[0]), int(nz[-1]) + 1


# --------------------------------------------------------------------- alignment
def best_lag(a, b, max_lag):
    """Lag (in samples) that best aligns b onto a, via FFT cross-correlation,
    restricted to |lag| <= max_lag. Returns (lag, peak_norm_corr)."""
    n = 1 << int(np.ceil(np.log2(a.size + b.size)))
    fa = np.fft.rfft(a - a.mean(), n)
    fb = np.fft.rfft(b - b.mean(), n)
    cc = np.fft.irfft(fa * np.conj(fb), n)
    cc = np.concatenate([cc[-max_lag:], cc[: max_lag + 1]])
    lags = np.arange(-max_lag, max_lag + 1)
    k = int(np.argmax(cc))
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
    return int(lags[k]), float(cc[k] / denom)


def drift_track(a, b, rate, win_s=0.75, hop_s=0.375, search_ms=120):
    """Local lag per window -> drift slope. a,b already globally aligned."""
    win = int(win_s * rate); hop = int(hop_s * rate); ml = int(search_ms * rate / 1000)
    n = min(a.size, b.size)
    centers, lags, corrs = [], [], []
    pos = 0
    while pos + win <= n:
        aw = a[pos:pos + win]; bw = b[pos:pos + win]
        if np.linalg.norm(aw) > 1e-3 and np.linalg.norm(bw) > 1e-3:
            lag, c = best_lag(aw, bw, ml)
            centers.append((pos + win / 2) / rate); lags.append(lag / rate * 1000.0); corrs.append(c)
        pos += hop
    if len(centers) < 3:
        return None
    centers = np.array(centers); lags = np.array(lags); corrs = np.array(corrs)
    # weighted least-squares slope (weight by local correlation quality)
    wts = np.clip(corrs, 0, None)
    if wts.sum() < 1e-6:
        wts = np.ones_like(corrs)
    A = np.vstack([centers, np.ones_like(centers)]).T
    W = np.diag(wts)
    coef = np.linalg.lstsq(W @ A, W @ lags, rcond=None)[0]
    slope_ms_per_s = float(coef[0])
    return {
        "n_windows": len(centers),
        "lag_ms_mean": float(lags.mean()),
        "lag_ms_std": float(lags.std()),
        "drift_ms_per_s": slope_ms_per_s,
        "drift_ppm": slope_ms_per_s * 1000.0,  # ms/s -> ppm
        "local_corr_median": float(np.median(corrs)),
    }


# ------------------------------------------------------------------------ onsets
def onsets(x, rate, fft=1024, hop=256, k=1.5):
    if x.size < fft:
        return np.array([])
    win = np.hanning(fft)
    frames = 1 + (x.size - fft) // hop
    mag = np.empty((frames, fft // 2 + 1))
    for i in range(frames):
        seg = x[i * hop:i * hop + fft] * win
        mag[i] = np.abs(np.fft.rfft(seg))
    flux = np.maximum(0.0, np.diff(mag, axis=0)).sum(axis=1)
    if flux.size == 0:
        return np.array([])
    flux /= (flux.max() or 1.0)
    # adaptive threshold: local mean + k*local std
    w = 16
    thr = np.array([flux[max(0, i - w):i + w].mean() + k * flux[max(0, i - w):i + w].std()
                    for i in range(flux.size)])
    pk = (flux[1:-1] > flux[:-2]) & (flux[1:-1] >= flux[2:]) & (flux[1:-1] > thr[1:-1])
    idx = np.where(pk)[0] + 1
    return idx * hop / rate  # seconds


def onset_match(ref_t, test_t, lag_s, tol_ms=50):
    """Match test onsets (shifted by -lag) to nearest ref onset; report errors."""
    if ref_t.size == 0 or test_t.size == 0:
        return None
    tt = test_t - lag_s
    errs = []
    matched = 0
    for t in tt:
        d = np.abs(ref_t - t)
        j = int(np.argmin(d))
        if d[j] * 1000.0 <= tol_ms:
            errs.append((t - ref_t[j]) * 1000.0); matched += 1
    if not errs:
        return {"matched": 0, "ref_onsets": int(ref_t.size), "test_onsets": int(test_t.size)}
    errs = np.array(errs)
    return {
        "ref_onsets": int(ref_t.size), "test_onsets": int(test_t.size),
        "matched": matched,
        "match_rate": matched / max(1, test_t.size),
        "err_ms_median": float(np.median(errs)),
        "err_ms_abs_median": float(np.median(np.abs(errs))),
        "err_ms_iqr": float(np.percentile(errs, 75) - np.percentile(errs, 25)),
        "err_ms_p90": float(np.percentile(np.abs(errs), 90)),
    }


# ---------------------------------------------------------------- pitch & timbre
def avg_spectrum(x, rate, fft=4096, hop=2048):
    if x.size < fft:
        return None, None
    win = np.hanning(fft); frames = 1 + (x.size - fft) // hop
    acc = np.zeros(fft // 2 + 1)
    for i in range(frames):
        acc += np.abs(np.fft.rfft(x[i * hop:i * hop + fft] * win))
    acc /= frames
    freqs = np.fft.rfftfreq(fft, 1.0 / rate)
    return freqs, acc


def dominant_pitch_track(x, rate, fft=4096, hop=2048, fmin=80, fmax=2000):
    if x.size < fft:
        return np.array([])
    win = np.hanning(fft); frames = 1 + (x.size - fft) // hop
    freqs = np.fft.rfftfreq(fft, 1.0 / rate)
    band = (freqs >= fmin) & (freqs <= fmax)
    out = []
    for i in range(frames):
        sp = np.abs(np.fft.rfft(x[i * hop:i * hop + fft] * win))
        if sp[band].max() < 1e-3:
            continue
        out.append(freqs[band][int(np.argmax(sp[band]))])
    return np.array(out)


def cents(ratio):
    return 1200.0 * np.log2(ratio) if ratio > 0 else float("nan")


# ----------------------------------------------------------- per-stream quality
def click_rate(x, rate, k=6.0, rms_ms=10.0):
    if x.size < 4:
        return 0.0
    d1 = np.abs(np.diff(x, prepend=x[0])); d2 = np.abs(np.diff(x, n=2, prepend=[x[0], x[0]]))
    w = max(8, int(rate * rms_ms / 1000.0))
    cs = np.cumsum(np.concatenate([[0.0], x * x]))
    lo = np.maximum(0, np.arange(x.size) - w); hi = np.minimum(x.size, np.arange(x.size) + w)
    rms = np.sqrt((cs[hi] - cs[lo]) / np.maximum(1, hi - lo))
    score = np.maximum(d1, d2) / np.maximum(rms, 1e-4)
    idx = np.where(score > k)[0]
    if idx.size:
        keep = [idx[0]]
        for i in idx[1:]:
            if i - keep[-1] >= 3:
                keep.append(i)
        idx = np.array(keep)
    return idx.size / (x.size / rate)


def noise_floor_db(x):
    if x.size == 0:
        return float("nan")
    q = np.sqrt(np.mean(np.sort(x * x)[: max(1, x.size // 10)]))  # quietest 10% RMS
    return 20.0 * np.log10(q + 1e-12)


# ------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True, help="oracle WAV (bsnes)")
    ap.add_argument("--test", required=True, help="recomp WAV (audio_wav dump)")
    ap.add_argument("--rate", type=int, default=32040, help="common analysis rate")
    ap.add_argument("--start-s", type=float, default=0.0)
    ap.add_argument("--dur-s", type=float, default=0.0, help="0 = all")
    ap.add_argument("--max-lag-s", type=float, default=2.0)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    rate = a.rate
    xr, rr = load_wav(a.ref); xt, rt = load_wav(a.test)
    xr = resample_linear(xr, rr, rate); xt = resample_linear(xt, rt, rate)
    # trim leading silence on each independently, then optional window
    r0, r1 = active_region(xr); t0, t1 = active_region(xt)
    xr = xr[r0:r1]; xt = xt[t0:t1]
    if a.start_s or a.dur_s:
        s = int(a.start_s * rate); e = xr.size if a.dur_s == 0 else s + int(a.dur_s * rate)
        xr = xr[s:e]; xt = xt[s:min(e, xt.size)]
    n = min(xr.size, xt.size)
    xr = xr[:n]; xt = xt[:n]
    if n < rate:
        print("ERROR: <1s of overlapping active audio; check captures.", file=sys.stderr)
        sys.exit(2)

    ml = int(a.max_lag_s * rate)
    glag, gcorr = best_lag(xr, xt, ml)
    # apply global lag so downstream operate aligned
    if glag >= 0:
        xa, xb = xr[glag:], xt[: n - glag]
    else:
        xa, xb = xr[: n + glag], xt[-glag:]
    m = min(xa.size, xb.size); xa = xa[:m]; xb = xb[:m]

    drift = drift_track(xa, xb, rate)
    o_ref = onsets(xa, rate); o_test = onsets(xb, rate)
    onset = onset_match(o_ref, o_test, 0.0)

    fr, sr_ = avg_spectrum(xa, rate); _, st_ = avg_spectrum(xb, rate)
    timbre = {}
    if sr_ is not None and st_ is not None:
        lo = (fr >= 50) & (fr <= 16000)
        ls = np.log(sr_[lo] + 1e-9); lt = np.log(st_[lo] + 1e-9)
        timbre["log_spectral_dist_db"] = float(np.sqrt(np.mean((ls - lt) ** 2)) * (20 / np.log(10)))
        cen = lambda s: float((fr[lo] * s[lo]).sum() / (s[lo].sum() + 1e-9))
        timbre["centroid_ref_hz"] = cen(sr_); timbre["centroid_test_hz"] = cen(st_)
        timbre["centroid_delta_hz"] = timbre["centroid_test_hz"] - timbre["centroid_ref_hz"]

    pr = dominant_pitch_track(xa, rate); pt = dominant_pitch_track(xb, rate)
    pitch = {}
    if pr.size and pt.size:
        ratio = np.median(pt) / np.median(pr)
        pitch = {"median_ref_hz": float(np.median(pr)), "median_test_hz": float(np.median(pt)),
                 "tuning_error_cents": float(cents(ratio))}

    quality = {
        "ref": {"click_per_s": click_rate(xa, rate), "noise_floor_db": noise_floor_db(xa)},
        "test": {"click_per_s": click_rate(xb, rate), "noise_floor_db": noise_floor_db(xb)},
    }

    result = {
        "ref": os.path.basename(a.ref), "test": os.path.basename(a.test),
        "rate": rate, "overlap_s": round(m / rate, 2),
        "global_align": {"lag_ms": glag / rate * 1000.0, "peak_corr": gcorr},
        "drift": drift, "onset": onset, "pitch": pitch, "timbre": timbre, "quality": quality,
    }

    # ----- human verdict -----
    print(f"\n=== A/B audio diff: {result['test']}  vs  REF {result['ref']} ===")
    print(f"  overlap {result['overlap_s']}s @ {rate} Hz")
    ga = result["global_align"]
    print(f"  global align : lag {ga['lag_ms']:+.1f} ms, peak corr {ga['peak_corr']:.3f} "
          f"({'STRONG' if ga['peak_corr']>0.5 else 'WEAK - streams may differ structurally'})")
    if drift:
        print(f"  drift        : {drift['drift_ms_per_s']:+.2f} ms/s ({drift['drift_ppm']:+.0f} ppm), "
              f"lag std {drift['lag_ms_std']:.1f} ms, local corr {drift['local_corr_median']:.2f}")
    if onset:
        if onset.get("matched"):
            print(f"  onsets       : {onset['matched']}/{onset['test_onsets']} matched "
                  f"({onset['match_rate']*100:.0f}%), |err| median {onset['err_ms_abs_median']:.1f} ms, "
                  f"p90 {onset['err_ms_p90']:.1f} ms")
        else:
            print(f"  onsets       : 0 matched (ref {onset['ref_onsets']}, test {onset['test_onsets']})")
    if pitch:
        print(f"  tuning       : test {pitch['median_test_hz']:.1f} Hz vs ref "
              f"{pitch['median_ref_hz']:.1f} Hz -> {pitch['tuning_error_cents']:+.0f} cents")
    if timbre:
        print(f"  timbre       : log-spectral dist {timbre['log_spectral_dist_db']:.1f} dB, "
              f"centroid delta {timbre['centroid_delta_hz']:+.0f} Hz")
    q = quality
    print(f"  quality      : clicks ref {q['ref']['click_per_s']:.2f}/s test {q['test']['click_per_s']:.2f}/s; "
          f"noise floor ref {q['ref']['noise_floor_db']:.0f} dB test {q['test']['noise_floor_db']:.0f} dB")
    print()

    if a.json:
        with open(a.json, "w") as f:
            json.dump(result, f, indent=2)
        print(f"  wrote {a.json}")


if __name__ == "__main__":
    main()
