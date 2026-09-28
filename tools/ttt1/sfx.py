"""TTT1 sounds other than voices, as a runtime pack per character.

A TTT1 move or event script names these sounds by an index into the arcade's
sound table (main RAM 80194CA8, 220 words: driver sound ID in the low half,
channel parameter in the high half), which 80113C78 hands to the H8 sound
driver (80125438: parameter at shared 0x208, request 0x4103 at 0x12E, driver
ID at 0x226). The driver plays them with envelopes and several C352 voices,
so tools/ttt1_sfx_oracle.lua asks it for each index, as the game does for
player 1, and MAME records the output; every other request of the game is
held back, so the recording holds nothing else. Each sound is recorded in a
fresh MAME (tools/ttt1_import.py): in a series the driver carries state
from one sound to the next and cuts or lengthens some (Lee's whip 0x7072:
0.12 s instead of 0.82 s; the Jacks' laugh 0x709f: 0.35 s instead of 1.02). This module cuts that
recording at each request, keeps the character's own indexes (the moves
conversion lists them: moves.convert report 'sound_indexes') and writes
<name>-TTT1-sfx.jus for src/tekken3_ttt1_sfx.c.
"""
from __future__ import annotations
import array, csv, hashlib, json, struct, wave
from pathlib import Path

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
    with wave.open(str(wav_path)) as w:
        if w.getframerate() != RATE or w.getsampwidth() != 2 or w.getnchannels() != 2:
            raise ValueError('expected a 44100 Hz 16-bit stereo recording (-samplerate 44100)')
        data = array.array('h', w.readframes(w.getnframes()))
    rows = [r for r in csv.DictReader(csv_path.open()) if r['index'].isdigit()]
    starts = [round(float(r['time']) * RATE) for r in rows]
    out = {}
    for k, r in enumerate(rows):
        a = starts[k]
        b = starts[k + 1] if k + 1 < len(rows) else len(data) // 2
        seg = data[a * 2:b * 2]
        mono = [(seg[i] + seg[i + 1]) // 2 for i in range(0, len(seg), 2)]
        loud = [i for i, v in enumerate(mono) if abs(v) > SILENCE]
        info = dict(index=int(r['index']), driver_id=int(r['driver_id']), param=int(r['param']))
        if not loud:
            info.update(frames=0, silent=True); out[info['index']] = (b'', info); continue
        first, last = loud[0], loud[-1] + 1
        pcm = [max(-32768, min(32767, round(v * GAIN))) for v in mono[first:last]] + [0] * 32
        left = sum(abs(seg[i]) for i in range(0, len(seg), 2)); right = sum(abs(seg[i + 1]) for i in range(0, len(seg), 2))
        info.update(frames=len(pcm), delay_frames=first, peak=max(abs(v) for v in pcm),
                    balance=round((right - left) / max(1, left + right), 3),
                    # Still sounding when the next request came: a loop or a
                    # sound longer than the oracle's step, cut there.
                    truncated=last >= len(mono) - RATE // 50)
        out[info['index']] = (struct.pack(f'<{len(pcm)}h', *pcm), info)
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
    directory = out / 'sounds'; directory.mkdir(exist_ok=True)
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
    (out / 'sfx-report.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
