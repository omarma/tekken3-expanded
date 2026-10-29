#!/usr/bin/env python3
"""Fingerprints of a Tekken Tag Tournament PS2 disc image, to compare two
versions of the disc without sharing them: every ISO file (sector, size,
sha256), SYSTEM.CNF, the TEKKEN.BIN table of the program (if it is where
a known version has it, ttt_disc.TABLES) with each TEKKEN.BIN file's
sha256, and the runs of sectors the setup checks.

    python tools/ps2/ttt_disc_fingerprint.py DISC [--out FILE.json]

DISC: a .cue, a .bin (2 352-byte sectors) or an .iso. The output holds
digests and positions only, nothing of the game: it can be sent as it is.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt_disc  # noqa: E402

# The runs of disc sectors the setup checks by sha256 (end excluded).
RUNS = {
    'endings music (tools/ttt_cinematics.py)': (110777, 111953),
    'Embu music (tools/data/ttt_cinematics/embu.ending.json)': (111953, 112875),
    'stage music (tools/ttt_stages/ps2_music_install.py)': (112875, 142915),
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(path: Path) -> dict:
    out = {}
    with ttt_disc.Disc(path) as d:
        size = d.path.stat().st_size
        out['image'] = {'file': d.path.name, 'bytes': size, 'sector': d.sector, 'sectors': size // d.sector}
        pvd = d.read(16, 2048)
        out['volume'] = {'id': pvd[40:72].decode('ascii', 'replace').strip(),
                         'sectors': struct.unpack_from('<I', pvd, 80)[0],
                         'created': pvd[813:830].decode('ascii', 'replace')}
        files = d.files()
        out['files'] = {}
        for name, (lba, length) in sorted(files.items(), key=lambda f: f[1]):
            h = hashlib.sha256()
            for at in range(0, length, 1 << 24):
                h.update(d.read(lba + at // 2048, min(1 << 24, length - at)))
            out['files'][name] = {'lba': lba, 'size': length, 'sha256': h.hexdigest()}
        try:
            out['system.cnf'] = d.file('SYSTEM.CNF').decode('ascii', 'replace').splitlines()
            out['boot'] = d.boot()
        except ttt_disc.DiscError as error:
            out['boot'] = str(error)
        out['runs'] = {}
        for what, (a, b) in RUNS.items():
            try:
                out['runs'][what] = {'sectors': [a, b], 'sha256': sha(d.read(a, (b - a) * 2048))}
            except ttt_disc.DiscError as error:
                out['runs'][what] = {'sectors': [a, b], 'error': str(error)}
        boot = '/' + out['boot'] if ('/' + str(out['boot'])) in files else None
        if boot:
            program = d.file(boot[1:])
            out['program'] = {'name': boot[1:], 'size': len(program), 'sha256': sha(program)}
            for version, at, _ in ttt_disc.TABLES:
                out['program'][f'table at {at:#X} ({version}) sha256'] = sha(program[at:at + 16 * ttt_disc.TOC_ENTRIES])
            try:
                tekken = ttt_disc.TekkenBin(d)
                out['program']['version'] = tekken.version
                out['tekken.bin'] = []
                for k, e in enumerate(tekken.entries):
                    entry = {'k': k, 'sector': e[0], 'size': tekken.size(k), 'word2': e[2], 'id': e[3]}
                    try:
                        entry['sha256'] = sha(tekken.read(k)) if tekken.size(k) else None
                    except ttt_disc.DiscError:
                        entry['sha256'] = 'past the end of the image'
                    out['tekken.bin'].append(entry)
            except ttt_disc.DiscError as error:
                out['tekken.bin'] = str(error)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('disc', type=Path)
    ap.add_argument('--out', type=Path, help='write the JSON here (default: print it)')
    args = ap.parse_args(argv)
    text = json.dumps(fingerprint(args.disc), indent=1)
    if args.out:
        args.out.write_text(text + '\n', encoding='utf-8')
        print(f'{args.out}: written')
    else:
        print(text)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ttt_disc.DiscError, OSError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
