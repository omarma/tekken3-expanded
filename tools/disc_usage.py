#!/usr/bin/env python3
"""Which parts of the disc the game reads: a report per disc file and track.

The runtime records the disc sectors it reads when PSX_DISC_SECTOR_LOG names a
file (psxrecomp/runtime/src/disc_sector_log.c; on Android, an APK built with
make_apk.py --disc-sector-log writes Android/data/<app>/files/disc-sectors.bin).
Play every mode, then:

  python3 tools/disc_usage.py disc-sectors.bin
  python3 tools/disc_usage.py disc-sectors.bin --cue "disc/Tekken 3 (USA).cue" --unread unread.txt

For each ISO 9660 file of the data track, each track and the sectors outside
any file, it gives the sectors read by the drive and those the game got (data
delivered, XA or CD audio played); in the data track, also per kind of sector
(subheader: data, video, XA audio, empty). Several logs (several players,
PC and phone) can be given: they add up. Nothing is written to the disc.
See docs/android-size.md.
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CUE = ROOT / "disc/Tekken 3 (USA).cue"
RAW = 2352
USER = 2048
USER_OFFSET = 24          # Mode 2: 12 sync + 4 header + 8 subheader
SUBMODE = 18              # first copy of the submode byte
MAGIC = b"PSXSECT1"


def load_log(path: Path) -> tuple[bytearray, bytearray, int]:
    data = path.read_bytes()
    if len(data) < 16 or data[:8] != MAGIC:
        raise SystemExit(f"{path}: not a disc sector log ({MAGIC.decode()})")
    count = struct.unpack_from("<I", data, 8)[0]
    size = (count + 7) // 8
    if len(data) != 16 + 2 * size:
        raise SystemExit(f"{path}: truncated")
    return bytearray(data[16:16 + size]), bytearray(data[16 + size:]), count


def bit(bitmap: bytes, lba: int) -> bool:
    return lba >> 3 < len(bitmap) and bool(bitmap[lba >> 3] >> (lba & 7) & 1)


@dataclass
class TrackFile:
    path: Path
    number: int
    kind: str          # MODE2/2352, AUDIO...
    start: int         # absolute LBA of the file's first sector
    sectors: int
    index1: int        # absolute LBA of INDEX 01

    @property
    def audio(self) -> bool:
        return self.kind.upper() == "AUDIO"


def msf(text: str) -> int:
    m, s, f = (int(x) for x in text.split(":"))
    return (m * 60 + s) * 75 + f


def parse_cue(cue: Path) -> list[TrackFile]:
    """One FILE per track (Redump), laid end to end as the runtime does
    (cue_sheet.cpp): a file starts where the previous one ends."""
    tracks: list[TrackFile] = []
    current: Path | None = None
    start = 0
    for line in cue.read_text(encoding="utf-8", errors="replace").splitlines():
        words = line.split()
        if not words:
            continue
        key = words[0].upper()
        if key == "FILE":
            quoted = re.search(r'"([^"]+)"', line)
            current = cue.parent / (quoted[1] if quoted else words[1])
            if tracks:
                start = tracks[-1].start + tracks[-1].sectors
        elif key == "TRACK" and current is not None:
            if not current.is_file():
                raise SystemExit(f"{current} is missing")
            sectors = current.stat().st_size // RAW
            tracks.append(TrackFile(current, int(words[1]), words[2], start, sectors, start))
        elif key == "INDEX" and tracks and int(words[1]) == 1:
            tracks[-1].index1 = tracks[-1].start + msf(words[2])
    if not tracks:
        raise SystemExit(f"{cue}: no track")
    return tracks


@dataclass
class IsoFile:
    name: str
    extent: int
    size: int

    @property
    def sectors(self) -> int:
        return max(1, (self.size + USER - 1) // USER)


def iso_files(track: TrackFile) -> tuple[list[IsoFile], list[tuple[int, int]]]:
    """The files of the data track's ISO 9660 tree, and its directories'
    extents (lba, sectors)."""
    with track.path.open("rb") as f:
        def user(lba: int, count: int = 1) -> bytes:
            out = bytearray()
            for n in range(count):
                f.seek((lba - track.start + n) * RAW + USER_OFFSET)
                out += f.read(USER)
            return bytes(out)

        pvd = user(16)
        if pvd[1:6] != b"CD001":
            raise SystemExit(f"{track.path}: no ISO 9660 volume")
        root = pvd[156:190]
        directories = [("", struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0])]
        files: list[IsoFile] = []
        extents: list[tuple[int, int]] = []
        seen = set()
        while directories:
            prefix, extent, size = directories.pop()
            if extent in seen:
                continue
            seen.add(extent)
            count = (size + USER - 1) // USER
            extents.append((extent, count))
            data = user(extent, count)
            pos = 0
            while pos < len(data):
                length = data[pos]
                if length == 0:
                    pos = (pos // USER + 1) * USER
                    continue
                record = data[pos:pos + length]
                name_len = record[32]
                raw_name = record[33:33 + name_len]
                lba, length_bytes = struct.unpack_from("<I", record, 2)[0], struct.unpack_from("<I", record, 10)[0]
                if raw_name not in (b"\x00", b"\x01"):
                    name = prefix + raw_name.decode("ascii", "replace").split(";")[0]
                    if record[25] & 2:
                        directories.append((name + "/", lba, length_bytes))
                    else:
                        files.append(IsoFile(name, lba, length_bytes))
                pos += length
    return files, extents


KINDS = ("data", "video", "XA audio", "empty", "other")


def sector_kinds(track: TrackFile) -> bytearray:
    """Per sector of a data track: an index in KINDS, from its subheader."""
    out = bytearray(track.sectors)
    with track.path.open("rb") as f:
        lba = 0
        while lba < track.sectors:
            block = f.read(RAW * 4096)
            for n in range(len(block) // RAW):
                submode = block[n * RAW + SUBMODE]
                if submode & 0x04:
                    kind = 2
                elif submode & 0x02:
                    kind = 1
                elif submode & 0x08:
                    kind = 0
                elif submode == 0:
                    kind = 3
                else:
                    kind = 4
                out[lba + n] = kind
            lba += len(block) // RAW
            if not block:
                break
    return out


@dataclass
class Tally:
    sectors: int = 0
    read: int = 0
    used: int = 0
    kinds: dict = field(default_factory=dict)   # kind -> [sectors, read, used]

    def add(self, lba: int, read: bytes, used: bytes, kind: str | None = None) -> None:
        r, u = bit(read, lba), bit(used, lba)
        self.sectors += 1
        self.read += r
        self.used += u
        if kind is not None:
            k = self.kinds.setdefault(kind, [0, 0, 0])
            k[0] += 1
            k[1] += r
            k[2] += u


def mb(sectors: int) -> str:
    return f"{sectors * RAW / 1e6:8.1f}"


def line(name: str, t: Tally) -> str:
    pct = 100 * t.read / t.sectors if t.sectors else 0
    return (f"  {name:28.28s} {t.sectors:8d} {mb(t.sectors)} {t.read:8d} {mb(t.read)} "
            f"{pct:5.1f}% {t.used:8d}")


def show(name: str, t: Tally) -> None:
    print(line(name, t))
    if len(t.kinds) > 1:
        for kind, (s, r, u) in sorted(t.kinds.items()):
            print(line("    " + kind, Tally(s, r, u)))


def ranges(lbas: list[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for lba in lbas:
        if out and out[-1][1] == lba - 1:
            out[-1] = (out[-1][0], lba)
        else:
            out.append((lba, lba))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("logs", nargs="+", type=Path, help="disc-sectors.bin file(s)")
    parser.add_argument("--cue", type=Path, default=DEFAULT_CUE)
    parser.add_argument("--unread", type=Path, help="write the never-read LBA ranges here")
    args = parser.parse_args()

    read = used = None
    for path in args.logs:
        r, u, _ = load_log(path)
        read = r if read is None else bytearray(a | b for a, b in zip(read, r))
        used = u if used is None else bytearray(a | b for a, b in zip(used, u))

    tracks = parse_cue(args.cue)
    data_track = next((t for t in tracks if not t.audio), None)
    files, directories = iso_files(data_track) if data_track else ([], [])
    owner: dict[int, str] = {}
    for f in files:
        for lba in range(f.extent, f.extent + f.sectors):
            owner.setdefault(lba, f.name)
    for extent, count in directories:
        for lba in range(extent, extent + count):
            owner.setdefault(lba, "(ISO directories)")
    for lba in range(16, 17):
        owner.setdefault(lba, "(ISO volume descriptor)")
    kinds = sector_kinds(data_track) if data_track else bytearray()

    per_file: dict[str, Tally] = {}
    per_track: dict[int, Tally] = {}
    total = Tally()
    for t in tracks:
        tally = per_track.setdefault(t.number, Tally())
        for lba in range(t.start, t.start + t.sectors):
            kind = KINDS[kinds[lba - t.start]] if t is data_track else ("pregap" if lba < t.index1 else "CD audio")
            tally.add(lba, read, used, kind)
            total.add(lba, read, used)
            name = owner.get(lba) or (f"(track {t.number} pregap)" if lba < t.index1
                                      else "(system area)" if t is data_track and lba < 16
                                      else f"(track {t.number}, outside files)")
            per_file.setdefault(name, Tally()).add(lba, read, used, kind)

    header = (f"  {'':28s} {'sectors':>8s} {'MB':>8s} {'read':>8s} {'MB':>8s} {'read':>6s} {'got':>8s}")
    print(f"Disc: {args.cue.name}, {len(tracks)} tracks, {total.sectors} sectors ({mb(total.sectors).strip()} MB)")
    print(f"Logs: {', '.join(str(p) for p in args.logs)}\n")
    print("Per file (ISO 9660 extents; files into the audio tracks included):")
    print(header)
    for name, t in sorted(per_file.items(), key=lambda kv: -kv[1].sectors):
        show(name, t)
    print("\nPer track:")
    print(header)
    for number, t in per_track.items():
        show(f"track {number}", t)
    print(line("whole disc", total))
    unread = [lba for t in tracks for lba in range(t.start, t.start + t.sectors) if not bit(read, lba)]
    print(f"\nNever read: {len(unread)} sectors ({mb(len(unread)).strip()} MB) in {len(ranges(unread))} ranges.")
    print("'read' counts what the drive read (an XA stream also reads the other channels of its")
    print("interleave); 'got' what the game received (data delivered, XA or CD audio played).")
    if args.unread:
        with args.unread.open("w", encoding="utf-8") as out:
            for first, last in ranges(unread):
                out.write(f"{first} {last} {last - first + 1} {owner.get(first, '')}\n")
        print(f"Never-read ranges (first last count file): {args.unread}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
