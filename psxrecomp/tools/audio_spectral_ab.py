#!/usr/bin/env python3
"""audio_spectral_ab.py - deep TIMBRE/tone differential of recomp audio vs an
accuracy-grade reference. Where audio_ab_diff.py answers "same notes, same
timing?", this answers "same TONE?" - the spectral envelope / harmonic content
that onset & correlation metrics are blind to.

It is drift-tolerant by construction: it compares TIME-AVERAGED spectra over a
matched musical passage, so small timing drift between the streams does not
affect the result. That isolates synthesis/timbre error from timing error.

Metrics:
  - third-octave band energy difference (dB), recomp - reference, 25 Hz..16 kHz
  - spectral centroid / 85% rolloff / flatness for each stream
  - overall log-spectral distance (dB RMS)
  - PNG: overlaid average spectra + both spectrograms

Uses scipy (resample_poly, welch, spectrogram) + matplotlib. Usage:
    python audio_spectral_ab.py --ref REF.wav --test TEST.wav
        [--rate 32040] [--win-s 6] [--png out.png] [--json out.json]
"""
import sys, os, wave, argparse, json
import numpy as np
from scipy import signal
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load_wav(path):
    """Robust to unfinalized (force-killed) headers: fall back to raw parse."""
    try:
        with wave.open(path, "rb") as w:
            ch, rate, n = w.getnchannels(), w.getframerate(), w.getnframes()
            raw = w.readframes(n)
        if n > 0 and len(raw) >= n * ch * 2:
            x = np.frombuffer(raw, "<i2").astype(np.float64) / 32768.0
            return (x.reshape(-1, ch).mean(1) if ch > 1 else x), rate
    except Exception:
        pass
    b = open(path, "rb").read()
    assert b[:4] == b"RIFF" and b[8:12] == b"WAVE", "not a WAV"
    ch, rate, bits, off, doff, dlen = 2, 32040, 16, 12, None, 0
    while off + 8 <= len(b):
        cid = b[off:off + 4]; sz = int.from_bytes(b[off + 4:off + 8], "little"); body = off + 8
        if cid == b"fmt ":
            ch = int.from_bytes(b[body + 2:body + 4], "little")
            rate = int.from_bytes(b[body + 4:body + 8], "little")
            bits = int.from_bytes(b[body + 14:body + 16], "little")
        elif cid == b"data":
            doff = body; dlen = sz if 0 < sz <= len(b) - body else len(b) - body; break
        off = body + sz + (sz & 1)
    raw = b[doff:doff + dlen - dlen % (ch * bits // 8)]
    x = np.frombuffer(raw, "<i2").astype(np.float64) / 32768.0
    return (x.reshape(-1, ch).mean(1) if ch > 1 else x), rate


def to_rate(x, src, dst):
    if src == dst:
        return x
    from math import gcd
    g = gcd(int(src), int(dst))
    return signal.resample_poly(x, dst // g, src // g)


def active(x, thr=1e-4):
    nz = np.where(np.abs(x) > thr)[0]
    return (0, x.size) if nz.size == 0 else (int(nz[0]), int(nz[-1]) + 1)


def coarse_lag(a, b, rate, max_s=8):
    ml = int(max_s * rate)
    n = 1 << int(np.ceil(np.log2(a.size + b.size)))
    cc = np.fft.irfft(np.fft.rfft(a - a.mean(), n) * np.conj(np.fft.rfft(b - b.mean(), n)), n)
    cc = np.concatenate([cc[-ml:], cc[:ml + 1]])
    return int(np.arange(-ml, ml + 1)[int(np.argmax(cc))])


def welch_psd(x, rate):
    f, p = signal.welch(x, rate, nperseg=8192, noverlap=4096, scaling="spectrum")
    return f, p


def third_octave(f, p, lo=25.0, hi=16000.0):
    bands, centers = [], []
    fc = lo
    while fc <= hi:
        f1 = fc / (2 ** (1 / 6)); f2 = fc * (2 ** (1 / 6))
        m = (f >= f1) & (f < f2)
        bands.append(p[m].sum() if m.any() else 0.0); centers.append(fc)
        fc *= 2 ** (1 / 3)
    return np.array(centers), np.array(bands)


def descriptors(f, p):
    p = np.maximum(p, 1e-20); tot = p.sum()
    centroid = float((f * p).sum() / tot)
    cs = np.cumsum(p); rolloff = float(f[np.searchsorted(cs, 0.85 * tot)])
    gm = np.exp(np.mean(np.log(p))); flatness = float(gm / (p.mean()))
    return centroid, rolloff, flatness


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True); ap.add_argument("--test", required=True)
    ap.add_argument("--rate", type=int, default=32040)
    ap.add_argument("--win-s", type=float, default=6.0)
    ap.add_argument("--png", default=None); ap.add_argument("--json", default=None)
    a = ap.parse_args()
    rate = a.rate

    xr, rr = load_wav(a.ref); xt, rt = load_wav(a.test)
    xr = to_rate(xr, rr, rate); xt = to_rate(xt, rt, rate)
    r0, r1 = active(xr); t0, t1 = active(xt); xr = xr[r0:r1]; xt = xt[t0:t1]
    lag = coarse_lag(xr, xt, rate)
    if lag >= 0:
        xr = xr[lag:]
    else:
        xt = xt[-lag:]
    n = min(xr.size, xt.size); xr = xr[:n]; xt = xt[:n]
    # pick the loudest matched win-s window (most musical content) for the average
    w = int(a.win_s * rate)
    if n > w:
        env = np.convolve(np.abs(xr) + np.abs(xt), np.ones(rate) / rate, "same")
        c = int(np.argmax(env)); s = max(0, min(c - w // 2, n - w)); xr = xr[s:s + w]; xt = xt[s:s + w]

    fr, pr = welch_psd(xr, rate); ft, pt = welch_psd(xt, rate)
    cen_r, ce = third_octave(fr, pr); _, te = third_octave(ft, pt)
    # normalize each to equal total energy in the analysis band (compare SHAPE,
    # not absolute level - level differences are a separate, trivial fix)
    ce_n = ce / (ce.sum() or 1.0); te_n = te / (te.sum() or 1.0)
    db = 10 * np.log10(np.maximum(te_n, 1e-12) / np.maximum(ce_n, 1e-12))

    dr = descriptors(fr, pr); dt = descriptors(ft, pt)
    # overall log-spectral distance on normalized PSD shape
    lo = (fr >= 50) & (fr <= 16000)
    prn = pr / pr[lo].sum(); ptn = pt / pt[lo].sum()
    lsd = float(np.sqrt(np.mean((10 * np.log10(ptn[lo] + 1e-12) - 10 * np.log10(prn[lo] + 1e-12)) ** 2)))

    print(f"\n=== SPECTRAL / TONE diff: {os.path.basename(a.test)} vs REF {os.path.basename(a.ref)} ===")
    print(f"  window {a.win_s:.0f}s @ {rate} Hz (shape-normalized; level ignored)")
    print(f"  log-spectral distance : {lsd:.1f} dB RMS  ({'CLOSE' if lsd<3 else 'AUDIBLE timbre diff' if lsd<6 else 'LARGE timbre diff'})")
    print(f"  centroid  ref {dr[0]:6.0f} Hz  test {dt[0]:6.0f} Hz  ({dt[0]-dr[0]:+.0f})")
    print(f"  rolloff85 ref {dr[1]:6.0f} Hz  test {dt[1]:6.0f} Hz  ({dt[1]-dr[1]:+.0f})")
    print(f"  flatness  ref {dr[2]:.4f}    test {dt[2]:.4f}")
    print(f"  --- third-octave band energy (test - ref, dB; |delta|>3 dB flagged) ---")
    for c, d in zip(cen_r, db):
        flag = "  <<<" if abs(d) > 3 else ""
        bar = ("+" if d >= 0 else "-") * min(20, int(abs(d)))
        print(f"   {c:7.0f} Hz : {d:+5.1f} dB {bar}{flag}")

    result = {"ref": os.path.basename(a.ref), "test": os.path.basename(a.test),
              "lsd_db": lsd,
              "centroid": {"ref": dr[0], "test": dt[0]},
              "rolloff85": {"ref": dr[1], "test": dt[1]},
              "flatness": {"ref": dr[2], "test": dt[2]},
              "third_octave_db": {float(c): float(d) for c, d in zip(cen_r, db)}}
    if a.json:
        json.dump(result, open(a.json, "w"), indent=2); print(f"\n  wrote {a.json}")

    png = a.png or (os.path.splitext(a.test)[0] + "_spectral.png")
    fig, ax = plt.subplots(3, 1, figsize=(10, 11))
    ax[0].semilogx(fr, 10 * np.log10(prn + 1e-12), label="ref (bsnes)", lw=1)
    ax[0].semilogx(ft, 10 * np.log10(ptn + 1e-12), label="test (recomp)", lw=1, alpha=0.8)
    ax[0].set_xlim(40, 16000); ax[0].set_xlabel("Hz"); ax[0].set_ylabel("dB (norm)")
    ax[0].set_title(f"avg spectrum (LSD {lsd:.1f} dB)"); ax[0].legend(); ax[0].grid(True, which="both", alpha=0.3)
    for k, (x, t) in enumerate([(xr, "ref (bsnes)"), (xt, "test (recomp)")]):
        f2, tt, Sxx = signal.spectrogram(x, rate, nperseg=2048, noverlap=1024)
        ax[k + 1].pcolormesh(tt, f2, 10 * np.log10(Sxx + 1e-12), shading="gouraud", cmap="magma")
        ax[k + 1].set_ylim(0, 16000); ax[k + 1].set_ylabel("Hz"); ax[k + 1].set_title(t)
    fig.tight_layout(); fig.savefig(png, dpi=90); print(f"  wrote {png}")


if __name__ == "__main__":
    main()
