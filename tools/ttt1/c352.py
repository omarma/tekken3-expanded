"""The C352 of TTT1 replayed from a register log, as MAME 0.289 records it.

tools/ttt1/sfx.py keeps, for each sound, the writes the H8 sound driver made
to the chip (tools/ttt1_sfx_oracle.lua, TTT1_REGS) at the 88200 Hz sample
they took effect: rendering them over the user's c352.bin gives what MAME
wrote with -wavwrite, sample for sample.

The chip follows MAME's BSD-3-Clause c352.cpp by R. Belmont and superctr
(System 12: 25401600 Hz / 288 = 88200 Hz, front outputs only); the output
stage follows MAME 0.289's sound.cpp and resampler.cpp (lofi resampler, the
default): -wavwrite records the speaker input, before the audio effects.
https://github.com/mamedev/mame/blob/mame0289/src/devices/sound/c352.cpp
https://github.com/mamedev/mame/blob/mame0289/src/emu/resampler.cpp
"""
from __future__ import annotations

RATE = 88200
BUSY, KEYON, KEYOFF, LOOPHIST = 0x8000, 0x4000, 0x2000, 0x800
PHASEFL, PHASEFR, LDIR, LINK, NOISE, MULAW, FILTER, LOOP, REVERSE = 0x100, 0x80, 0x40, 0x20, 0x10, 8, 4, 2, 1
KEY = 0x202                      # word register: execute key-ons / key-offs


def _s16(x):
    x &= 0xffff
    return x - 0x10000 if x & 0x8000 else x


def _mulaw():
    table, j = [0] * 256, 0
    for i in range(128):
        table[i] = j << 5
        j += 1 if i < 16 else 2 if i < 24 else 4 if i < 48 else 8 if i < 100 else 16
    for i in range(128): table[i + 128] = _s16(~table[i] & 0xffe0)
    return table


MU = _mulaw()
LINEAR = [_s16(b << 8) for b in range(256)]


class _Voice:
    __slots__ = ('regs', 'pos', 'counter', 'sample', 'last', 'vol')

    def __init__(self):
        self.regs = [0] * 8          # vol_f, vol_r, freq, flags, bank, start, end, loop
        self.pos = self.counter = self.sample = self.last = 0
        self.vol = [0, 0]            # current front left / right volume (ramped)


def render(rom: bytes, init, writes, start: int, end: int, effective=None):
    """Left and right s16 samples of the chip, 88200 Hz, samples start..end-1.

    init: (word register, value) at `start`, every voice silent. writes:
    (sample, word register, value, mask) in order; a write takes effect
    before that sample is computed. effective: a list that receives, for
    each write, whether it changed anything (the measure drops the others)."""
    vs = [_Voice() for _ in range(32)]
    for reg, value in init:
        vs[reg // 8].regs[reg % 8] = value & ~BUSY
    noise = 0x1234                   # reset value; nothing plays noise before
    left, right = [0] * (end - start), [0] * (end - start)
    busy, k, n = [], 0, start
    while n < end:
        while k < len(writes) and writes[k][0] <= n:
            _, reg, value, mask = writes[k]; k += 1
            changed = False
            if reg < 0x100:
                v = vs[reg // 8]; r = reg % 8
                new = (v.regs[r] & ~mask) | (value & mask)
                changed, v.regs[r] = new != v.regs[r], new
            elif reg == KEY and mask == 0xffff:
                for v in vs:
                    f = v.regs[3]
                    if f & KEYON:
                        v.pos = (v.regs[4] << 16) | v.regs[5]
                        v.sample = v.last = 0
                        v.counter = 0xffff
                        f = (f | BUSY) & ~(KEYON | LOOPHIST)
                        v.vol = [0, 0]
                    if f & KEYOFF:
                        f &= ~(BUSY | KEYOFF)
                        v.counter = 0xffff
                    changed |= f != v.regs[3]
                    v.regs[3] = f
            if effective is not None: effective.append(changed)
            busy = [v for v in vs if v.regs[3] & BUSY]
        if not busy:                 # silence up to the next write
            n = min(end, writes[k][0]) if k < len(writes) else end
            continue
        stop = min(end, writes[k][0]) if k < len(writes) else end
        for i in range(n - start, stop - start):
            o0 = o1 = 0
            for v in busy:
                f = v.regs[3]
                if not f & BUSY: continue
                c = v.counter
                nc = c + v.regs[2]
                if nc & 0x10000:
                    v.last = v.sample
                    if f & NOISE:
                        noise = (noise >> 1) ^ ((-(noise & 1)) & 0xfff6)
                        v.sample = _s16(noise)
                    else:
                        b = rom[v.pos & 0xffffff]
                        v.sample = MU[b] if f & MULAW else LINEAR[b]
                        p = v.pos & 0xffff
                        if f & LOOP and f & REVERSE:
                            if f & LDIR and p == v.regs[7]: f &= ~LDIR
                            elif not f & LDIR and p == v.regs[6]: f |= LDIR
                            v.pos += -1 if f & LDIR else 1
                        elif p == v.regs[6]:
                            if f & LINK and f & LOOP: v.pos = (v.regs[5] << 16) | v.regs[7]; f |= LOOPHIST
                            elif f & LOOP: v.pos = (v.pos & 0xff0000) | v.regs[7]; f |= LOOPHIST
                            else: f = (f | KEYOFF) & ~BUSY; v.sample = 0
                        else:
                            v.pos += -1 if f & REVERSE else 1
                        v.pos &= 0xffffffff
                    v.regs[3] = f
                if (nc ^ c) & 0x18000:   # volume ramp, one step at a time
                    vol, vf = v.vol, v.regs[0]
                    for ch, target in ((0, vf >> 8), (1, vf & 0xff)):
                        if vol[ch] != target: vol[ch] += 1 if vol[ch] < target else -1
                v.counter = nc & 0xffff
                s = v.sample
                if not f & FILTER: s = v.last + ((v.counter * (s - v.last)) >> 16)
                o0 += ((-s if f & PHASEFL else s) * v.vol[0]) >> 8
                o1 += ((-s if f & PHASEFR else s) * v.vol[1]) >> 8
            left[i], right[i] = _s16(o0 >> 3), _s16(o1 >> 3)
        n = stop
        busy = [v for v in busy if v.regs[3] & BUSY]
    return left, right


def _lofi_tables():
    import numpy as np
    f32 = np.float32
    f0, f1 = np.zeros(0x1001, f32), np.zeros(0x1001, f32)
    for i in range(1, 4096):
        p = f32(i / 4096.0); f0[i] = (p - p * p * p) / f32(6)
    for i in range(1, 2049):
        p = f32(i / 4096.0); f1[i] = p + (p * p - p * p * p) / f32(2)
    for i in range(2049, 4096):        # in double in MAME (1.0 is a double)
        f1[i] = f32(1.0 + float(f0[i]) + float(f0[4096 - i]) - float(f1[4096 - i]))
    f1[0x1000] = 1.0
    return f0, f1


def output(chip, first: int, start: int, end: int):
    """MAME's 44100 Hz s16 samples start..end-1 of one channel, from the chip's
    88200 Hz samples (chip[0] being sample `first`, zero outside).

    MAME 0.289's lofi resampler, 88200 to 44100: averages of 3 source samples
    (from sample 0), a 4-point interpolation 4 averages late, and a phase
    re-derived at each sound update (50 Hz: 883 samples, then 882) and
    accumulated within it in steps that run slightly short. Then float to
    s16 by truncation (sound_manager::output_push)."""
    import numpy as np
    f32 = np.float32
    f0, f1 = _lofi_tables()
    x = np.zeros(len(chip) + 12, f32)
    x[12:] = np.asarray(chip, f32) / f32(32768)
    d = np.arange(start, end)
    update = d - (d - 1) % 882
    delta = (2 * update) % 3
    phase = (((delta << 12) // 3) << 12) + (d - update) * 11184810
    k = (2 * update - delta) // 3 - 4 + (phase >> 24)
    c = (phase & 0xffffff) >> 12

    def average(g):
        i = 3 * g - first + 12
        if i.min() < 0: raise ValueError('the chip samples start too late')
        return ((f32(0) + x[i] + x[i + 1]) + x[i + 2]) / f32(3)
    y = -average(k) * f0[4096 - c] + average(k + 1) * f1[4096 - c]
    y = y + average(k + 2) * f1[c]
    y = y - average(k + 3) * f0[c]
    return np.clip((y * f32(32768)).astype(np.int64), -32768, 32767)
