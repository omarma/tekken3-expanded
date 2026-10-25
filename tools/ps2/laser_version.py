"""The version of Devil's and Angel's PS2 laser file the setup makes
(ttt_laser_install.py, from the player's TTT PS2 disc).

Increase LASER_VERSION whenever the file the setup writes changes (its
format, the conversion, ttt_laser_install.py): the setup sees the older stamp
and makes it again from the disc. No imports here: the setup reads it without
numpy.
"""
from __future__ import annotations

from pathlib import Path

LASER_VERSION = 3           # 2: Angel's yellow (ANGEL_FILE); 3: the Mishima's strong-hit effects (HITSPARK_FILES)
FILE = 'ps2-laser.tim'      # Devil's: 32 TIMs, read by the game (step 3 of the PS2 laser)
ANGEL_FILE = 'ps2-laser-angel.tim'   # Angel's: the same images, yellow palettes
# The Mishima's PS2 strong-hit effects (ttt_hitspark_ps2.py), 64 x 64 packs of TTT Hitspark's format.
HITSPARK_FILES = tuple(f'{name}-PS2-hiteffect64.hfx' for name in ('Jin', 'Heihachi', 'Kazuya', 'Devil', 'Angel'))
STAMP = 'version.txt'


def read_stamp(folder: Path) -> int:
    try:
        return int((Path(folder) / STAMP).read_text(encoding='utf-8').strip())
    except (OSError, ValueError):
        return 0


def current(folder: Path) -> bool:
    """The folder holds the laser and strong-hit effect files of this version."""
    folder = Path(folder)
    return read_stamp(folder) >= LASER_VERSION and all((folder / f).is_file() for f in (FILE, ANGEL_FILE, *HITSPARK_FILES))
