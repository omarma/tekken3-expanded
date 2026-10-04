"""Voices of a TTT1 character: its original arcade samples as a runtime pack.

The character's sound profile (0x29EF00 + 0x14) points at its voice table:
four category counts (attack, damage, KO, victory) and the sample IDs. Each
sample is decoded from the C352 ROM with the registers the chip was given
at key-on, measured once in MAME by tools/ttt1_voice_oracle.lua and kept, as
numbers only, in tools/data/ttt1_voice_registers.json: the driver's pitch
field does not predict the frequency, and above ID 673 (P. Jack) the driver
table no longer matches what the chip plays, so the measured registers win
and the report says so. A new voice: run the oracle, then
`python3 tools/ttt1/voices.py --measure <key>-voice-oracle.csv...`.

C352 mu-law and interpolation follow MAME's BSD-3-Clause implementation by
R. Belmont and superctr (commit aab5dcadb6025303ba019d0189344a5df536a623):
https://github.com/mamedev/mame/blob/aab5dcadb6025303ba019d0189344a5df536a623/src/devices/sound/c352.cpp

The pack keeps its payloads end to end in entry order, which the runtime
checks: a sample used twice is written twice.
"""
from __future__ import annotations
import csv, hashlib, json, struct, wave
from pathlib import Path

REGISTERS = Path(__file__).resolve().parents[1] / 'data/ttt1_voice_registers.json'
FIELDS = ('frequency', 'bank', 'start', 'end', 'flags')
SUB_SHA = '5b5ffddf6df97be32919462c23a7d0896498bbf01af547566ff45449ae0811f8'
C352_SHA = 'cb68614775f792b6bf97149396a1cf12645802f8ec1b8da014554142e579f281'
FREQUENCY = 0x18af       # Jun's twelve samples; the oracle measures each one
ROLE = {2: 'attack', 3: 'damage', 4: 'ko', 5: 'victory'}
KEYS = 0x29ef00          # highlighted character: moveset, body, sound, asset


def mulaw_table():
    positive = []
    level = 0
    for i in range(128):
        positive.append(level << 5)
        level += 1 if i < 16 else 2 if i < 24 else 4 if i < 48 else 8 if i < 100 else 16
    return positive + [-v - 32 for v in positive]


def decode_sample(rom, bank, start, end, flags, frequency=FREQUENCY):
    """Render a forward, one-shot C352 voice to 44100 Hz mono PCM.

    Crossing a 64 KiB bank boundary is legal (Jun's damage sample 162 does).
    The terminal byte silences the channel in the original C352. Simulate its
    88200 Hz interpolation clock, then average pairs for the host output rate.
    Gain/panning belong to the runtime mixer, not the extracted waveform.
    """
    # flags 8: mu-law (Jun, Kazuya); 0: signed 8-bit linear PCM (Roger).
    # Bit 0 plays the sample backwards, from start down to end (Unknown's
    # voices 1739..1747 are Jun's 1730..1738, start and end swapped): the
    # address counts down across the bank boundary.
    backwards = flags & 1
    if flags & ~1 not in (0, 8) or not 1 <= frequency <= 65535:
        raise ValueError('Expected a non-looping mu-law or linear voice')
    count = ((start - end if backwards else end - start) & 65535) + 1
    address = bank * 65536 + start
    if backwards: address -= count - 1
    if address < 0 or address + count > len(rom):
        raise ValueError('Sample extends outside its ROM')
    if backwards: rom, address = rom[address:address + count][::-1], 0
    table = mulaw_table() if flags & 8 else [(b - 256 if b > 127 else b) << 8 for b in range(256)]
    counter, sample, last, index = 65535, 0, 0, 0
    pcm, pair = [], []
    while index < count:
        next_counter = counter + frequency
        if next_counter & 65536:
            last, sample = sample, table[rom[address + index]]
            index += 1
            if index == count:
                sample = 0
        counter = next_counter & 65535
        pair.append(last + ((counter * (sample - last)) >> 16))
        if len(pair) == 2:
            pcm.append((pair[0] + pair[1]) // 2)
            pair.clear()
    # End without a discontinuity, including the chip's terminal sample.
    pcm.extend([0] * 32)
    return struct.pack('<' + 'h' * len(pcm), *pcm)


def sound_table(ram: bytes, profile: int) -> tuple[tuple, tuple]:
    """(category counts, sample IDs) of a sound profile."""
    pointer = struct.unpack_from('<I', ram, 0x11e1c + profile * 20)[0] & 0x3fffff
    groups = struct.unpack_from('<4H', ram, pointer)
    return groups, struct.unpack_from(f'<{sum(groups)}H', ram, pointer + 8)


def read_oracle(path: Path) -> dict:
    """C352 registers recorded at key-on, by requested sample ID."""
    oracle = {}
    for r in csv.DictReader(path.open()):
        sid = int(r['requested_id'])
        if sid:
            oracle[sid] = {k: int(r[k]) for k in FIELDS}
    return oracle


def read_registers(path: Path = REGISTERS) -> dict:
    """The measured table: sample ID -> registers at key-on."""
    return {int(i): dict(zip(FIELDS, v)) for i, v in json.loads(path.read_text())['voices'].items()}


def measure(oracles) -> None:
    """Adds the IDs of oracle CSVs to the measured table; an ID measured
    twice must match."""
    table = json.loads(REGISTERS.read_text()) if REGISTERS.is_file() else dict(
        _comment='Registres du C352 au key-on de chaque voix TTT1 que l import utilise, '
                 'releves une fois dans MAME (tools/ttt1_voice_oracle.lua) : identifiant -> '
                 '[frequence, banque, debut, fin, drapeaux]. Des nombres seulement, aucun echantillon.',
        voices={})
    for path in oracles:
        for sid, o in read_oracle(Path(path)).items():
            row, old = [o[k] for k in FIELDS], table['voices'].get(str(sid))
            if old not in (None, row): raise SystemExit(f'{path}: ID {sid} {row}, deja mesure {old}')
            table['voices'][str(sid)] = row
    rows = sorted(table['voices'].items(), key=lambda kv: int(kv[0]))
    REGISTERS.write_text('{\n "_comment": %s,\n "voices": {\n%s\n }\n}\n' % (
        json.dumps(table['_comment']), ',\n'.join(f'  "{i}": {json.dumps(v)}' for i, v in rows)))
    print(f'{REGISTERS.name}: {len(table["voices"])} voix')


def build(ram: bytes, profile: int, sub: bytes, c352: bytes,
          out: Path, name: str) -> dict:
    """Writes out/<name>-TTT1-voices.juv, out/voices/*.wav and
    out/voice-report.json. sub, c352: the TTT1 sound ROMs."""
    if len(ram) != 0x400000:
        raise ValueError('expected a 4 MiB RAM capture')
    if hashlib.sha256(sub).hexdigest() != SUB_SHA or hashlib.sha256(c352).hexdigest() != C352_SHA:
        raise ValueError('unexpected TTT1 sound ROMs')
    measured = read_registers()
    moves, body, sound, asset2 = struct.unpack_from('<4H', ram, KEYS + 0x10)
    groups, ids = sound_table(ram, profile)
    if not 1 <= len(ids) <= 32:                    # MAX_SAMPLES of the runtime
        raise ValueError(f'unexpected voice table: categories {groups}')

    # (sample ID, category, rank in the category), in slot order
    slots, k = [], 0
    for g, n in enumerate(groups):
        for index in range(n):
            slots.append((ids[k], g + 2, index)); k += 1

    out.mkdir(parents=True, exist_ok=True)
    directory = out / 'voices'; directory.mkdir(exist_ok=True)
    blob = bytearray(32 + len(slots) * 16)
    report = []
    for i, (sample_id, group, index) in enumerate(slots):
        bank, flags, start, end, pitch = struct.unpack_from('<5H', sub, 0x9436 + sample_id * 10)
        if sample_id not in measured:
            raise ValueError(f'sample {sample_id} not measured in {REGISTERS.name} (run the voice oracle)')
        o = measured[sample_id]
        # The driver table (sub 0x9436) describes the lower IDs; for the
        # higher ones (P. Jack: 673..683) it no longer matches what the C352
        # plays. The measured registers are the voice actually programmed: they
        # win, and the difference is reported.
        if (bank, start, end) != (o['bank'], o['start'], o['end']):
            bank, start, end = o['bank'], o['start'], o['end']
            flags = o['flags'] & 0xff                  # without the key-on bit 0x4000
            source = 'oracle'
        else:
            source = 'table'
        pcm = decode_sample(c352, bank, start, end, flags, o['frequency'])
        struct.pack_into('<4I', blob, 32 + i * 16,
                         sample_id, len(blob), len(pcm) // 2, group << 16 | index)
        blob.extend(pcm)
        role = ROLE[group]
        with wave.open(str(directory / f'{sample_id:03d}-{role}-{index+1}.wav'), 'wb') as wav:
            wav.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
            wav.writeframes(pcm)
        report.append(dict(slot=i, id=sample_id, role=role, index=index, bank=bank,
                           start=start, end=end, flags=flags,
                           driver_pitch=pitch, frequency=o['frequency'], source=source,
                           frames=len(pcm) // 2,
                           pcm_sha256=hashlib.sha256(pcm).hexdigest()))
    struct.pack_into('<8I', blob, 0, 0x3156554a, 1, len(blob), len(slots), 44100, 0, 0, 0)
    (out / f'{name}-TTT1-voices.juv').write_bytes(blob)
    result = dict(format_version=1, sha256=hashlib.sha256(blob).hexdigest(),
                  bytes=len(blob), samples=report, sound_profile=profile,
                  group_counts=list(groups), group_ids=list(ids),
                  distinct_ids=sorted(set(ids)),
                  character_keys=dict(moveset=moves, body=body, sound=sound, asset=asset2 // 2),
                  frequencies=sorted({measured[i]['frequency'] for i in ids}),
                  registers_sha256=hashlib.sha256(REGISTERS.read_bytes()).hexdigest(),
                  source_c352_sha256=C352_SHA, source_sub_sha256=SUB_SHA,
                  capture_sha256=hashlib.sha256(ram).hexdigest())
    (out / 'voice-report.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    import sys
    if sys.argv[1:2] != ['--measure'] or len(sys.argv) < 3: raise SystemExit(__doc__)
    measure(sys.argv[2:])
