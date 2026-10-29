#!/usr/bin/env python3
"""Reading the player's Tekken Tag Tournament PS2 disc (USA, SLUS-20001):
its ISO 9660 files, the files packed in TEKKEN.BIN, and the GS uploads (GIF
packets) stored in them.

    python tools/ps2/ttt_disc.py DISC                 # the disc's files
    python tools/ps2/ttt_disc.py DISC --entry 585     # one TEKKEN.BIN file's uploads

DISC: a .cue (its first FILE), a .bin of 2 352-byte sectors (MODE2: 2 048
bytes of data at +24) or an .iso of 2 048-byte sectors.

TEKKEN.BIN (LBA 24 on the USA disc) holds the game's data files. Their table
is in SLUS_200.01 (USA build only): 679 entries of 16 bytes, u32 sector (from
TEKKEN.BIN's first), u32 size + 0x350A, u32 unknown, u32 id. Entries of size
0 do not end the table. Two versions of the USA disc are known (TABLES): 1.00
and 2.00 (Greatest Hits). 2.00's program has 256 more bytes before the table,
which is 0x100 further; its files lie at the same sectors, and the ones read
by the setup's tools are the same (2.00 changed other parts of some files).

Characters' files hold their effect textures as GIF packets ready for the GS:
a PACKED tag of 4 A+D registers (BITBLTBUF, TRXPOS, TRXREG, TRXDIR), an IMAGE
tag, then the pixels. On the disc BITBLTBUF's destination is relative (the
game adds its own base). A 4-bit image (PSMT4) is followed by its palette, an
8 x 2 PSMCT32 upload (16 colours, CSM1, in index order).

Nothing read here goes into git.
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

TOC_ENTRIES, SIZE_BIAS = 679, 0x350A
BOOT = 'SLUS_200.01'
# The known versions of the USA disc (SYSTEM.CNF's VER): where SLUS_200.01
# has the TEKKEN.BIN table, and the sha256 of its 679 entries.
TABLES = (
    ('1.00', 0x1CAD40, '59a4d524a723c22ca4e9ef74df11156dcc9e34f010724426b8f7f219c872951d'),
    ('2.00', 0x1CAE40, 'aa0fd3353960035e6b0b8fb0ab28446094ec05a48172254eb3adac97b98cf844'),
)

PSMCT32, PSMT4 = 0x00, 0x14
AD_TAG = struct.pack('<QQ', 0x4000000000000001, 0xEEEE)   # NLOOP 1, PACKED, 4 registers, all A+D
BITBLTBUF, TRXPOS, TRXREG, TRXDIR = 0x50, 0x51, 0x52, 0x53


class DiscError(ValueError):
    """Not the disc expected (another game, another version, a damaged image)."""


def image_file(disc: Path):
    """(image file, sector size, data offset in a sector) of a .cue, .bin or .iso."""
    disc = Path(disc)
    if disc.suffix.lower() == '.cue':
        try:
            line = next(l for l in disc.read_text(errors='replace').splitlines() if l.strip().upper().startswith('FILE'))
            disc = disc.parent / line.split('"')[1]
        except (StopIteration, IndexError):
            raise DiscError(f'{disc}: no FILE line in this .cue') from None
    with disc.open('rb') as f:
        raw = f.read(12) == b'\0' + b'\xff' * 10 + b'\0'
    return disc, (2352 if raw else 2048), (24 if raw else 0)


class Disc:
    """The disc's sectors (2 048 data bytes each) and ISO 9660 files."""

    def __init__(self, disc: Path):
        self.path, self.sector, self.offset = image_file(disc)
        self.f = self.path.open('rb')
        self._files = None

    def close(self):
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *error):
        self.close()

    def read(self, lba: int, size: int) -> bytes:
        out = bytearray()
        for n in range(lba, lba + (size + 2047) // 2048):
            self.f.seek(n * self.sector + self.offset)
            out += self.f.read(2048)
        if len(out) < size:
            raise DiscError(f'{self.path}: the image ends before sector {lba + len(out) // 2048} (incomplete?)')
        return bytes(out[:size])

    def files(self) -> dict:
        """{'/NAME': (lba, size)} of every file on the disc."""
        if self._files is None:
            pvd = self.read(16, 2048)
            if pvd[1:6] != b'CD001':
                raise DiscError(f'{self.path}: not an ISO 9660 disc image')
            files = {}

            def walk(lba, size, path, depth=0):
                d = self.read(lba, size)
                i = 0
                while i < len(d):
                    n = d[i]
                    if n == 0:                      # records do not cross a sector: go to the next one
                        i = (i // 2048 + 1) * 2048
                        continue
                    at, length = struct.unpack_from('<I', d, i + 2)[0], struct.unpack_from('<I', d, i + 10)[0]
                    name = d[i + 33:i + 33 + d[i + 32]]
                    if name not in (b'\0', b'\1'):
                        name = name.decode('ascii', 'replace').split(';')[0]
                        if d[i + 25] & 2:
                            if depth < 8:
                                walk(at, length, path + name + '/', depth + 1)
                        else:
                            files[path + name] = (at, length)
                    i += n
            root = pvd[156:190]
            walk(struct.unpack_from('<I', root, 2)[0], struct.unpack_from('<I', root, 10)[0], '/')
            self._files = files
        return self._files

    def file(self, name: str) -> bytes:
        try:
            lba, size = self.files()['/' + name]
        except KeyError:
            raise DiscError(f'{self.path}: no {name} on this disc') from None
        return self.read(lba, size)

    def system(self, key: str) -> str | None:
        """A value of SYSTEM.CNF (BOOT2, VER), None without it."""
        for line in self.file('SYSTEM.CNF').decode('ascii', 'replace').splitlines():
            if line.split('=')[0].strip().upper() == key:
                return line.split('=', 1)[1].strip()
        return None

    def boot(self) -> str:
        """The program SYSTEM.CNF starts (BOOT2 = cdrom0:\\SLUS_200.01;1)."""
        boot = self.system('BOOT2')
        if boot is None:
            raise DiscError(f'{self.path}: SYSTEM.CNF names no program')
        return boot.replace('cdrom0:', '').lstrip('\\/').split(';')[0]


class TekkenBin:
    """The files of TEKKEN.BIN, from the table of the USA program (`version`:
    the one of TABLES it is)."""

    def __init__(self, disc: Disc):
        boot = disc.boot()
        if boot.upper() != BOOT:
            raise DiscError(f'{disc.path}: program {boot}, not {BOOT}')
        program = disc.file(BOOT)
        table = next(((version, at) for version, at, sha256 in TABLES
                      if hashlib.sha256(program[at:at + 16 * TOC_ENTRIES]).hexdigest() == sha256), None)
        if table is None:
            raise DiscError(f"{disc.path}: {BOOT} of an unknown version (SYSTEM.CNF: VER = {disc.system('VER')}), "
                            f"not {' or '.join(t[0] for t in TABLES)}")
        self.version, at = table
        self.disc = disc
        self.lba = disc.files().get('/TEKKEN.BIN', (None,))[0]
        if self.lba is None:
            raise DiscError(f'{disc.path}: no TEKKEN.BIN on this disc')
        self.entries = [struct.unpack_from('<4I', program, at + 16 * k) for k in range(TOC_ENTRIES)]

    def size(self, k: int) -> int:
        return max(self.entries[k][1] - SIZE_BIAS, 0)

    def read(self, k: int) -> bytes:
        return self.disc.read(self.lba + self.entries[k][0], self.size(k))


@dataclass
class Upload:
    """One GS upload of a file: where its packet starts, the destination
    format and size, the pixels, and where the packet ends."""
    at: int
    psm: int
    width: int
    height: int
    data: bytes
    end: int


def uploads(data: bytes) -> list[Upload]:
    """The host-to-GS uploads (4 A+D registers, then IMAGE) in DATA, in order."""
    out = []
    i = data.find(AD_TAG)
    while i >= 0:
        if i % 16 == 0 and i + 96 <= len(data):
            regs = {struct.unpack_from('<Q', data, i + 24 + 16 * r)[0]: struct.unpack_from('<Q', data, i + 16 + 16 * r)[0]
                    for r in range(4)}
            tag = struct.unpack_from('<Q', data, i + 80)[0]
            if set(regs) == {BITBLTBUF, TRXPOS, TRXREG, TRXDIR} and (tag >> 58) & 3 == 2:
                size = 16 * (tag & 0x7FFF)
                out.append(Upload(i, regs[BITBLTBUF] >> 56 & 0x3F, regs[TRXREG] & 0xFFF, regs[TRXREG] >> 32 & 0xFFF,
                                  data[i + 96:i + 96 + size], i + 96 + size))
        i = data.find(AD_TAG, i + 16)
    return out


def textures(data: bytes) -> list[tuple[Upload, Upload]]:
    """The 4-bit images of DATA, each with the 16-colour palette uploaded right after it."""
    ups = uploads(data)
    return [(u, p) for u, p in zip(ups, ups[1:])
            if u.psm == PSMT4 and len(u.data) == u.width * u.height // 2
            and p.psm == PSMCT32 and (p.width, p.height) == (8, 2) and len(p.data) == 64 and p.at == u.end]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('disc', type=Path)
    ap.add_argument('--entry', type=int, help="list this TEKKEN.BIN file's 4-bit textures")
    args = ap.parse_args(argv)
    with Disc(args.disc) as disc:
        if args.entry is None:
            for name, (lba, size) in sorted(disc.files().items(), key=lambda f: f[1]):
                print(f'{lba:8d} {size:10d} {name}')
            return 0
        tekken = TekkenBin(disc)
        for u, p in textures(tekken.read(args.entry)):
            print(f'+{u.at:#08x} {u.width}x{u.height}, palette +{p.at:#x}')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (DiscError, OSError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
