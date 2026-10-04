"""TTT1 sounds other than voices, as a runtime pack per character.

A TTT1 move or event script names these sounds by an index into the arcade's
sound table (main RAM 80194CA8, 220 words: driver sound ID in the low half,
channel parameter in the high half), which 80113C78 hands to the H8 sound
driver (80125438: parameter at shared 0x208, request 0x4103 at 0x12E, driver
ID at 0x226). The driver programs the C352 itself (one voice for most sounds,
three reprogrammed at every tick for the lasers), so tools/ttt1_sfx_oracle.lua
asks it for each index, as the game does for player 1, and MAME records the
output; every other request of the game is held back, so the recording holds
nothing else. Each sound is recorded in a fresh MAME: in a series the driver
carries state from one sound to the next and cuts or lengthens some (Lee's
whip 0x7072: 0.12 s instead of 0.82 s; the Jacks' laugh 0x709f: 0.35 s
instead of 1.02).

That was done once: the oracle also logs the driver's writes to the chip, and
measure() keeps them in tools/data/ttt1_sfx_registers.json (numbers only), so
the import replays them over the user's c352.bin (tools/ttt1/c352.py) and gets
MAME's recording sample for sample, without MAME. A new sound: run the oracle
with TTT1_REGS, then `sfx.py --measure <c352.bin> <folder>`. trim() cuts each
request, build() keeps the character's own indexes (the moves conversion lists
them: moves.convert report 'sound_indexes') and writes <name>-TTT1-sfx.jus for
src/tekken3_ttt1_sfx.c.
"""
from __future__ import annotations
import csv, hashlib, json, struct, wave
from pathlib import Path
import c352

REGISTERS = Path(__file__).resolve().parents[1] / 'data/ttt1_sfx_registers.json'

TABLE = 0x194ca8          # main RAM offset of the sound table
TABLE_SIZE = 0xdc
RATE = 44100
SILENCE = 24              # |sample| at or below this ends a sound (MAME output, 16 bits)
MAGIC = 0x3153554a        # "JUS1"
# MAME's output is quieter than the voices, which the runtime mixes at a
# quarter of their decoded C352 level. Measured on 2026-09-24: Devil's voice
# 612 decodes to a peak of 31264 (7816 once quartered); asked through this
# oracle with the voices' parameter 16, MAME outputs a peak of 2287. The
# sounds are scaled by that ratio, so a sound keeps its arcade level
# relative to the voices (the table parameter still sets its own level).
GAIN = 7816 / 2287


# Sounds the TTT1 engine asks for directly, outside the table: index in the
# pack -> (driver request slot, request word). The lasers of Devil / Angel:
# 80116EA4 calls 801253B0(0x112F, 27) when a beam starts (80116F8C), for
# every beam type, on the frame the move's active window opens.
LASER = 1024
RAW = {LASER: (27, 0x112f)}


# The announcer calling the character's name, as TTT1 does when the character
# is picked (8016FA28 -> 80114CD8, request 0x4100 in slot 20): the event is
# half-word +16 of the character's sound profile (80011E1C + 20 * profile,
# the profile of voices.sound_table), a table index like the others, so the
# oracle has already recorded it. The pack keeps it under NAME, which T3
# plays when its own announcer calls the fighter (src/tekken3_ttt1_sfx.c).
NAME = 1025
# Sounds of a hit on a metallic fighter (sound profile 18 Gun Jack, 30 Jack-2, 35 P.Jack):
# events 0x705D, 0x7098, 0x7099 (TTT1 801148D0, T3 80041B70).
METAL_PROFILES = (30, 35)
METAL_HIT_SOUNDS = (0x5d, 0x98, 0x99)
PROFILES = 0x11e1c


def name_index(ram: bytes, profile: int) -> int:
    """Table index of the character's announced name; 0 if it has none
    (Tetsujin's profile)."""
    return struct.unpack_from('<H', ram, PROFILES + profile * 20 + 16)[0] & 0xfff


def raw_list() -> str:
    """TTT1_RAW for the oracle."""
    return ','.join(f'{i}:{slot}:{word}' for i, (slot, word) in RAW.items())


def table(ram: bytes) -> list[tuple[int, int]]:
    """(driver ID, parameter) of each index; index 0 is empty."""
    return [(w & 0xffff, w >> 16) for w in struct.unpack_from(f'<{TABLE_SIZE}I', ram, TABLE)]


def oracle_list(ram: bytes) -> str:
    """TTT1_SFX for the oracle: index:driver_id:param for every index."""
    return ','.join(f'{i}:{d}:{p}' for i, (d, p) in enumerate(table(ram)) if i and d)


def cut_all(recordings) -> dict:
    """cut() over several (wav, csv) recordings, merged."""
    out = {}
    for wav_path, csv_path in recordings: out.update(cut(wav_path, csv_path))
    return out


def cut(wav_path: Path, csv_path: Path) -> dict:
    """index -> (mono PCM bytes, report), from the oracle recording."""
    import numpy as np                                 # the sample loops below, vectorised: same integer math
    with wave.open(str(wav_path)) as w:
        if w.getframerate() != RATE or w.getsampwidth() != 2 or w.getnchannels() != 2:
            raise ValueError('expected a 44100 Hz 16-bit stereo recording (-samplerate 44100)')
        data = np.frombuffer(w.readframes(w.getnframes()), '<i2').astype(np.int64)
    rows = [r for r in csv.DictReader(csv_path.open()) if r['index'].isdigit()]
    starts = [round(float(r['time']) * RATE) for r in rows]
    out = {}
    for k, r in enumerate(rows):
        a = starts[k]
        b = starts[k + 1] if k + 1 < len(rows) else len(data) // 2
        info = dict(index=int(r['index']), driver_id=int(r['driver_id']), param=int(r['param']))
        out[info['index']] = trim(data[a * 2:b * 2], info)
    return out


def trim(seg, info: dict):
    """(mono PCM bytes, report) of one request: seg, the interleaved stereo
    s16 output from the request on (as int64)."""
    import numpy as np
    mono = (seg[0::2][:len(seg) // 2] + seg[1::2]) // 2   # floor division, as Python's //
    loud = np.flatnonzero(np.abs(mono) > SILENCE)
    if not len(loud):
        info.update(frames=0, silent=True); return b'', info
    first, last = int(loud[0]), int(loud[-1]) + 1
    # np.round rounds half to even, as round() does.
    pcm = np.concatenate([np.clip(np.round(mono[first:last] * GAIN), -32768, 32767).astype(np.int64),
                          np.zeros(32, np.int64)])
    left = int(np.abs(seg[0::2]).sum()); right = int(np.abs(seg[1::2]).sum())
    info.update(frames=len(pcm), delay_frames=first, peak=int(np.abs(pcm).max()),
                balance=round((right - left) / max(1, left + right), 3),
                # Still sounding when the next request came: a loop or a
                # sound longer than the oracle's step, cut there.
                truncated=last >= len(mono) - RATE // 50)
    return pcm.astype('<i2').tobytes(), info


def read_log(regs: Path, wav: Path, requests: Path) -> dict:
    """One oracle recording (TTT1_REGS log, -wavwrite, TTT1_OUT) as a table
    entry: chip writes at the 88200 Hz sample they take effect (the chip
    computes up to the current sample included, then writes: the next one),
    the request and the end of the recording in 44100 Hz samples."""
    init, writes, start = [], [], None
    for line in regs.open():
        p = line.strip().split(',')
        if p[0] == 'init':
            if int(p[2], 16): init.append(((int(p[1], 16) - 0x280000) // 2, int(p[2], 16)))
        elif p[0] == 'start': start = int(p[1]) + 1
        else: writes.append((int(p[0]) + 1, (int(p[1], 16) - 0x280000) // 2, int(p[2], 16), int(p[3], 16)))
    row = next(r for r in csv.DictReader(requests.open()) if r['index'].isdigit())
    with wave.open(str(wav)) as w: end = w.getnframes()
    return dict(index=int(row['index']), driver_id=int(row['driver_id']), param=int(row['param']),
                request=round(float(row['time']) * RATE), end=end, start=start, init=init, writes=writes)


def replay(rom: bytes, e: dict, effective=None):
    """MAME's recording of a table entry, interleaved stereo s16 (int64), from
    the request to the end."""
    import numpy as np
    left, right = c352.render(rom, e['init'], e['writes'], e['start'], 2 * e['end'], effective)
    seg = np.empty(2 * (e['end'] - e['request']), np.int64)
    seg[0::2] = c352.output(left, e['start'], e['request'], e['end'])
    seg[1::2] = c352.output(right, e['start'], e['request'], e['end'])
    return seg


def measure(rom: bytes, folder: Path) -> None:
    """Adds the recordings of folder (<index>-regs.csv, .wav, .csv of
    tools/ttt1_sfx_oracle.lua with TTT1_REGS) to the table. Each must replay
    to its recording sample for sample; writes that change nothing are dropped
    (the driver rewrites registers and asks for key-ons at every tick)."""
    import numpy as np
    table = json.loads(REGISTERS.read_text()) if REGISTERS.is_file() else dict(
        _comment='Ecritures du pilote son TTT1 dans le C352 pour chaque son hors voix que l import '
                 'utilise, relevees une fois dans MAME 0.289 (tools/ttt1_sfx_oracle.lua, TTT1_REGS) : '
                 'index -> demande et fin (echantillons a 44100 Hz), depart (echantillons a 88200 Hz), '
                 'registres non nuls au depart [registre, valeur], ecritures [ecart en echantillons, '
                 'registre, valeur(, masque)]. Des nombres seulement, aucun echantillon.',
        sounds={})
    for regs in sorted(folder.glob('*-regs.csv'), key=lambda p: int(p.name.split('-')[0])):
        stem = regs.name.split('-')[0]
        e = read_log(regs, folder / f'{stem}.wav', folder / f'{stem}.csv')
        with wave.open(str(folder / f'{stem}.wav')) as w:
            want = np.frombuffer(w.readframes(w.getnframes()), '<i2').astype(np.int64)[2 * e['request']:]
        effective = []
        if not np.array_equal(replay(rom, e, effective), want): raise SystemExit(f'{regs}: replay differs from the recording')
        e['writes'] = [w for w, kept in zip(e['writes'], effective) if kept]
        if not np.array_equal(replay(rom, e), want): raise SystemExit(f'{regs}: replay differs once pruned')
        last, writes = e['start'], []
        for n, reg, value, mask in e['writes']:
            writes.append([n - last, reg, value] + ([mask] if mask != 0xffff else [])); last = n
        index = e.pop('index')
        table['sounds'][str(index)] = dict(e, init=[list(r) for r in e['init']], writes=writes)
        print(f'{stem}: {len(writes)} writes')
    rows = sorted(table['sounds'].items(), key=lambda kv: int(kv[0]))
    REGISTERS.write_text('{\n "_comment": %s,\n "sounds": {\n%s\n }\n}\n' % (
        json.dumps(table['_comment']), ',\n'.join(f'  "{i}": {json.dumps(e, separators=(",", ":"))}' for i, e in rows)))


def measured(rom: bytes, indexes) -> dict:
    """index -> (mono PCM bytes, report), replayed from the table over the
    user's c352.bin: what cut() gives from the oracle's recordings."""
    import voices
    if hashlib.sha256(rom).hexdigest() != voices.C352_SHA: raise ValueError('unexpected TTT1 sound ROM (c352.bin)')
    table = json.loads(REGISTERS.read_text())['sounds']
    missing = sorted(set(indexes) - set(map(int, table)))
    if missing: raise ValueError(f'sounds {missing} not measured in {REGISTERS.name} (run the sound oracle, then --measure)')
    out = {}
    for index in sorted(set(indexes)):
        e = dict(table[str(index)]); n, writes = e['start'], []
        for w in e['writes']:
            n += w[0]; writes.append((n, w[1], w[2], w[3] if len(w) > 3 else 0xffff))
        e['writes'] = writes
        out[index] = trim(replay(rom, e), dict(index=index, driver_id=e['driver_id'], param=e['param']))
    return out


def build(indexes, sounds: dict, out: Path, name: str) -> dict:
    """Writes out/<name>-TTT1-sfx.jus for the given sound indexes."""
    entries, report, missing = [], [], []
    for index in sorted(set(indexes)):
        pcm, info = sounds.get(index, (b'', dict(index=index, missing=True)))
        if not pcm:
            missing.append(index); report.append(info); continue
        entries.append((index, len(pcm) // 2, info['driver_id'], pcm))
        report.append(dict(info, pcm_sha256=hashlib.sha256(pcm).hexdigest()))
    # A donor moveset (Tetsujin@Lee) shares out/ with the other donors, imported
    # in parallel: its own listing and report, or they delete each other's files.
    own = '@' + name.split('@', 1)[1] if '@' in name else ''
    directory = out / f'sounds{own}'; directory.mkdir(exist_ok=True)
    for old in directory.glob('*.wav'): old.unlink()
    for index, frames, driver, pcm in entries:
        with wave.open(str(directory / f'{index:03d}-{index:#05x}-driver-{driver:#05x}.wav'), 'wb') as w:
            w.setparams((1, 2, RATE, 0, 'NONE', 'not compressed')); w.writeframes(pcm)
    blob = bytearray(32 + len(entries) * 16)
    for i, (index, frames, driver, pcm) in enumerate(entries):
        struct.pack_into('<4I', blob, 32 + i * 16, index, len(blob), frames, driver)
        blob.extend(pcm)
    struct.pack_into('<8I', blob, 0, MAGIC, 1, len(blob), len(entries), RATE, 0, 0, 0)
    path = out / f'{name}-TTT1-sfx.jus'
    path.write_bytes(blob)
    result = dict(format_version=1, bytes=len(blob), sounds=len(entries), sha256=hashlib.sha256(blob).hexdigest(),
                  silent_or_missing=missing, truncated=[r['index'] for r in report if r.get('truncated')],
                  entries=report)
    (out / f'sfx-report{own}.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    import sys
    if sys.argv[1:2] != ['--measure'] or len(sys.argv) != 4: raise SystemExit('sfx.py --measure <c352.bin> <recordings folder>')
    measure(Path(sys.argv[2]).read_bytes(), Path(sys.argv[3]))
