"""TTT Stages: the version of the music file the setup makes (music_install.py).

Increase MUSIC_VERSION whenever the file the setup writes changes (FORMAT,
tools/data/ttt_stage_music.json.gz, music_install.py): the setup sees the
older stamp and makes it again from the player's tektagt.zip. No imports
here: the setup reads it without numpy.
"""
from __future__ import annotations

from pathlib import Path

MUSIC_VERSION = 1
FORMAT = 1                  # music.ttm, read by src/tekken3_ttt_music.c
FILE = 'music.ttm'
STAMP = 'version.txt'


def read_stamp(folder: Path) -> int:
    try:
        return int((Path(folder) / STAMP).read_text(encoding='utf-8').strip())
    except (OSError, ValueError):
        return 0


def current(folder: Path) -> bool:
    """The folder holds the music file of this version."""
    folder = Path(folder)
    return read_stamp(folder) >= MUSIC_VERSION and (folder / FILE).is_file()


# The PS2 music of the stages (ps2_music_install.py, from the player's TTT PS2
# disc), in its own folder: increase PS2_VERSION whenever that file changes.
PS2_VERSION = 1
PS2_FORMAT = 1              # ps2-music.ttp, read by src/tekken3_ttt_music.c
PS2_FILE = 'ps2-music.ttp'


def ps2_current(folder: Path) -> bool:
    """The folder holds the PS2 music file of this version."""
    folder = Path(folder)
    return read_stamp(folder) >= PS2_VERSION and (folder / PS2_FILE).is_file()
