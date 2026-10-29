"""The two versions of the Tekken Tag Tournament USA PS2 disc (tools/ps2/ttt_disc.py
TABLES): 1.00 and 2.00 (Greatest Hits) give the same packs, byte for byte.

    python -m unittest tools.tests.test_ttt_disc_versions

Runs only where both discs are: by default in C:\\TekkenProject\\discs or
~/TekkenProject/discs under their Redump names (.cue or .bin),
TEKKEN3_TTT_DISC / TEKKEN3_TTT_DISC_V2: other paths. About 5 s.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ps2'), str(ROOT / 'tools/ttt_stages')]
import ps2_music_install  # noqa: E402
import ttt_cinematics  # noqa: E402
import ttt_disc  # noqa: E402
import ttt_laser_install  # noqa: E402


def find(variable: str, version: str):
    names = [f'Tekken Tag Tournament (USA) ({version}).{ext}' for ext in ('cue', 'bin')]
    places = [Path(r'C:\TekkenProject\discs'), Path.home() / 'TekkenProject/discs']
    given = [Path(os.environ[variable])] if os.environ.get(variable) else []
    return next((p for p in given + [d / n for d in places for n in names] if p.is_file()), None)


DISCS = {'1.00': find('TEKKEN3_TTT_DISC', 'v1.00'), '2.00': find('TEKKEN3_TTT_DISC_V2', 'v2.00')}


def packs(disc: Path, out: Path) -> dict:
    """{file: sha256} of every pack the setup reads on DISC, made in OUT."""
    ps2_music_install.install(disc, out / 'ps2-music-pack', say=lambda line: None)
    ttt_laser_install.install(disc, out / 'laser-pack', say=lambda line: None)
    cine = out / 'ttt-cinematics'
    cine.mkdir()
    ttt_cinematics.music(disc, cine)
    embu = json.loads((ttt_cinematics.DATA / 'embu.ending.json').read_text(encoding='utf-8'))
    ttt_cinematics.own_music(embu, disc, cine)
    return {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(out.rglob('*')) if p.is_file()}


@unittest.skipUnless(all(DISCS.values()), 'the two Tekken Tag Tournament USA PS2 discs are not both here')
class TwoVersions(unittest.TestCase):
    def test_versions(self):
        for version, disc in DISCS.items():
            with ttt_disc.Disc(disc) as d:
                self.assertEqual(d.system('VER'), version)
                self.assertEqual(ttt_disc.TekkenBin(d).version, version)

    def test_same_packs(self):
        with tempfile.TemporaryDirectory() as temp:
            made = {version: packs(disc, Path(temp) / version) for version, disc in DISCS.items()}
        self.assertEqual(len(made['1.00']), 12)
        self.assertEqual(made['1.00'], made['2.00'])


if __name__ == '__main__':
    unittest.main()
