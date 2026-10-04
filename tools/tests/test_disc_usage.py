from __future__ import annotations

import contextlib
import io
import struct
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from tools import disc_usage

RAW, USER = disc_usage.RAW, disc_usage.USER


def record(name: bytes, extent: int, size: int, directory: bool = False) -> bytes:
    length = 33 + len(name) + (len(name) + 1) % 2
    out = bytearray(length)
    out[0] = length
    struct.pack_into("<I", out, 2, extent)
    struct.pack_into(">I", out, 6, extent)
    struct.pack_into("<I", out, 10, size)
    struct.pack_into(">I", out, 14, size)
    out[25] = 2 if directory else 0
    out[32] = len(name)
    out[33:33 + len(name)] = name
    return bytes(out)


def raw_sector(user: bytes, submode: int = 0x08) -> bytes:
    sector = bytearray(RAW)
    sector[0:12] = b"\x00" + b"\xff" * 10 + b"\x00"
    sector[15] = 2
    sector[16:24] = bytes([0, 0, submode, 0]) * 2
    sector[24:24 + len(user)] = user
    return bytes(sector)


def make_disc(folder: Path) -> Path:
    """Track 1: system area, PVD at 16, root directory at 18, A.DAT (3
    sectors at 20), B.XA (4 XA audio sectors at 23), an empty sector at 27,
    28 sectors in all. Track 2: audio, 150 sectors of pregap then 50."""
    users = [bytes(USER)] * 28
    submodes = [0x08] * 28
    root = (record(b"\x00", 18, USER, True) + record(b"\x01", 18, USER, True)
            + record(b"A.DAT;1", 20, 3 * USER) + record(b"B.XA;1", 23, 4 * USER)
            + record(b"MUSIC.DA;1", 28 + 150, 50 * USER))
    pvd = bytearray(USER)
    pvd[0:6] = b"\x01CD001"
    pvd[156:190] = record(b"\x00", 18, USER, True)
    users[16] = bytes(pvd)
    users[18] = root.ljust(USER, b"\x00")
    for lba in range(23, 27):
        submodes[lba] = 0x64
    submodes[27] = 0x00
    track1 = folder / "Game (Track 1).bin"
    track1.write_bytes(b"".join(raw_sector(u, s) for u, s in zip(users, submodes)))
    (folder / "Game (Track 2).bin").write_bytes(bytes(200 * RAW))
    cue = folder / "Game.cue"
    cue.write_text('FILE "Game (Track 1).bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n'
                   'FILE "Game (Track 2).bin" BINARY\n  TRACK 02 AUDIO\n    INDEX 00 00:00:00\n'
                   '    INDEX 01 00:02:00\n')
    return cue


def make_log(path: Path, read: list[int], used: list[int]) -> None:
    count = 1000
    maps = [bytearray((count + 7) // 8), bytearray((count + 7) // 8)]
    for bitmap, lbas in zip(maps, (read, used)):
        for lba in lbas:
            bitmap[lba >> 3] |= 1 << (lba & 7)
    path.write_bytes(disc_usage.MAGIC + struct.pack("<II", count, 0) + maps[0] + maps[1])


class DiscUsageTests(unittest.TestCase):
    def test_report_per_file_and_track(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            cue = make_disc(folder)
            tracks = disc_usage.parse_cue(cue)
            self.assertEqual([(t.start, t.sectors, t.index1) for t in tracks],
                             [(0, 28, 0), (28, 200, 178)])
            files, directories = disc_usage.iso_files(tracks[0])
            self.assertEqual([(f.name, f.extent, f.sectors) for f in files],
                             [("A.DAT", 20, 3), ("B.XA", 23, 4), ("MUSIC.DA", 178, 50)])
            self.assertEqual(directories, [(18, 1)])
            self.assertEqual(list(disc_usage.sector_kinds(tracks[0])[22:28]), [0, 2, 2, 2, 2, 3])

            # Two sessions: they add up.
            make_log(folder / "a.bin", [16, 18, 20, 21, 23, 24], [16, 18, 20, 21, 23])
            make_log(folder / "b.bin", [178, 179], [178])
            out = io.StringIO()
            with contextlib.redirect_stdout(out), unittest.mock.patch(
                    "sys.argv", ["disc_usage.py", str(folder / "a.bin"), str(folder / "b.bin"),
                                 "--cue", str(cue), "--unread", str(folder / "unread.txt")]):
                self.assertEqual(disc_usage.main(), 0)
            report = out.getvalue()
            self.assertRegex(report, r"A\.DAT\s+3\s+[\d.]+\s+2\s")
            self.assertRegex(report, r"B\.XA\s+4\s+[\d.]+\s+2\s")
            self.assertRegex(report, r"MUSIC\.DA\s+50\s+[\d.]+\s+2\s")
            self.assertRegex(report, r"track 2 pregap\)\s+150\s+[\d.]+\s+0\s")
            self.assertIn("Never read: 220 sectors", report)
            first = (folder / "unread.txt").read_text().splitlines()[0]
            self.assertEqual(first.split()[:3], ["0", "15", "16"])


if __name__ == "__main__":
    unittest.main()
