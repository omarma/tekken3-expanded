"""TTT1 joint motion: the System 12 pose decoder, and a character's clips.

Format recovered from the arcade decoder at 0x80105B34. export() writes the
poses of every clip the character's own move records use, and its idle
stance (<Name>-TTT1-idle.poses, read by the runtime).
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import struct

CHANNELS = 57
SENTINEL = 0x8009374C          # alias of a missing move
ALIASES, IDLE_ALIAS = 0x2A7350, 56
KEYS = 0x29EF00                # highlighted character: moveset, body, sound, asset


def decode(bank: bytes, base: int, frame: int, channels: int = CHANNELS) -> list[int]:
    """Return original unsigned 16-bit channel values for one animation frame.

The first three channels are polar root motion (heading, height, distance),
followed by 18 XYZ joint rotations. Values deliberately retain their original
integer precision and wraparound. Conversion to a target skeleton is separate.
"""
    if frame < 0 or not 1 <= channels <= CHANNELS:
        raise ValueError("Invalid frame or channel count")
    if base < 0 or base + 0x130 > len(bank):
        raise ValueError("Truncated animation header")
    count = bank[base]
    if not count:
        raise ValueError("Animation has no frames")
    if frame + 1 >= count:
        return list(struct.unpack_from(f"<{channels}H", bank, base + 0x74))
    values = list(struct.unpack_from(f"<{channels}H", bank, base + 2))
    if frame == 0:
        return values
    block, within = divmod(frame - 1, 16)
    cursor = base + struct.unpack_from("<H", bank, base + 0xE6 + block * 2)[0] * 2
    for channel in range(channels):
        initial = cursor
        bits = remaining = consumed = 0

        def take(n: int) -> int:
            nonlocal bits, remaining, cursor, consumed
            while remaining < n:
                if cursor < 0 or cursor + 2 > len(bank):
                    raise ValueError("Truncated animation channel")
                bits |= struct.unpack_from("<H", bank, cursor)[0] << remaining
                cursor += 2
                remaining += 16
            value = bits & ((1 << n) - 1)
            bits >>= n
            remaining -= n
            consumed += n
            return value

        span = take(4)
        next_channel = initial + span * 2
        if not span or next_channel > len(bank):
            raise ValueError("Invalid channel block span")
        shift = 2 if channel in (1, 2) else 4
        value = values[channel]
        repeat = code = 0
        for _ in range(within + 1):
            if repeat:
                repeat -= 1
            else:
                code = take(4)
                if code >= 8:
                    repeat = (take(4) + 1) & 15
                    code -= 8
            if code == 7:
                value = take(12) << shift
            elif code:
                width, bias = {1: (6, -84), 2: (4, -20), 3: (2, -4),
                               4: (2, 1), 5: (4, 5), 6: (6, 21)}[code]
                value += (take(width) + bias) << shift
            if consumed > span * 16:
                raise ValueError("Animation bits exceed the declared channel span")
        values[channel] = value & 65535
        cursor = next_channel
    return values


def validate_capture(bank: bytes, capture: Path) -> dict:
    """Compare against poses sampled at return from the original MAME decoder."""
    poses = samples = 0
    clips = set()
    for row in csv.DictReader(capture.open(encoding="utf-8")):
        source, frame, channels = int(row["source"], 16), int(row["frame"]), int(row["channels"])
        actual = [int(x, 16) for x in row["pose"].split()]
        decoded = decode(bank, source, frame, channels)
        if actual != decoded:
            raise ValueError(f"Arcade pose mismatch: clip 0x{source:x}, frame {frame}")
        clips.add(source)
        poses += 1
        samples += channels
    if not poses:
        raise ValueError("Capture contains no decoded poses")
    return dict(poses=poses, channel_samples=samples, clips=len(clips), mismatches=0,
                capture_sha256=hashlib.sha256(capture.read_bytes()).hexdigest())


def export(ram: bytes, witness: bytes, bank: bytes, work: Path, name: str,
           witness_name: str = "") -> dict:
    """Clips of the character highlighted in `ram`, a 4 MiB selector capture.

    Its own records are the alias entries that differ from `witness`, the
    same capture with another character (Xiaoyu): shared reactions and entries
    the witness lacks are not the character's moves. Writes work/motion/
    (one .poses per clip, manifest.json) and work/<name>-TTT1-idle.poses."""
    moves, body, sound, asset2 = struct.unpack_from("<4H", ram, KEYS + 0x10)
    aliases = struct.unpack_from("<5515I", ram, ALIASES)
    reference = struct.unpack_from("<5515I", witness, ALIASES)
    changed = [(i, a) for i, (a, b) in enumerate(zip(aliases, reference))
               if a != b and a != SENTINEL]
    records = []
    for address in sorted({a for _, a in changed}):
        fields = struct.unpack_from("<13I", ram, address & 0x3FFFFF)
        records.append(dict(address=address, aliases=[i for i, a in changed if a == address],
                            animation=fields[0], raw_words=list(fields)))
    idle = struct.unpack_from("<13I", ram, aliases[IDLE_ALIAS] & 0x3FFFFF)[0]
    sources = sorted({r["animation"] for r in records})
    out = work / "motion"
    out.mkdir(parents=True, exist_ok=True)
    clips = []
    for source in sources:
        count = bank[source]
        poses = b"".join(struct.pack(f"<{CHANNELS}H", *decode(bank, source, f))
                         for f in range(count))
        fn = f"{source:08x}.poses"
        (out / fn).write_bytes(poses)
        if source == idle:
            (work / f"{name}-TTT1-idle.poses").write_bytes(poses)
        clips.append(dict(source=source, frames=count, channels=CHANNELS, file=fn,
                          sha256=hashlib.sha256(poses).hexdigest()))
    if idle not in sources:
        raise ValueError(f"idle clip 0x{idle:x} is not among the exported sources")
    report = dict(schema_version=1, character=asset2 // 2,
                  character_keys=dict(moveset=moves, body=body, sound=sound),
                  witness=witness_name, idle_source=idle,
                  records=records, clips=clips,
                  total_frames=sum(c["frames"] for c in clips),
                  status="Animations decoded; the solo combat conversion follows (moves.convert)",
                  unresolved=["Tag-only transitions are excluded from the solo conversion"])
    (out / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
