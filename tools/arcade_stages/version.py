"""Arcade Stages: the version of the stage packs the setup makes (install.py).

Increase ARCADE_STAGES_VERSION whenever the packs the setup writes change
(pack.FORMAT, decode.py, scene.py, pack.py, faces.py): the setup sees the older stamp
and makes them again from the player's tekken3.zip (launcher/setup_backend.py).
No imports here: the setup reads it without numpy.
"""
from __future__ import annotations

from pathlib import Path

# 2 (B186): the stock fighters' HD selector faces beside the packs (faces.py).
ARCADE_STAGES_VERSION = 2
STAMP = 'version.txt'
STAGES = range(13)          # arenas 0..12; Gon's (13) and Dr. B's (14) keep the PS1 stage
# faces.FRAMES' IDs (no numpy here): their face-NN-tile-hd.bin and -portrait-hd.bin.
FACES = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 20)
# TTT Stages: the 15 TTT packs (pack.py --game ttt, format 4, beside the game
# as mods/ttt-stages). Increase with any change of what they hold (S3: the
# storm's thunder in stage 4; S4: stage 11's floor-light CLUTs exact, its
# light beams, GLOW; 3, B76: the light on the fighters, LGHT). The setup makes
# them from tektagt.zip (install.py --ttt1, TTT Stages S7) and makes them
# again when this increases.
TTT_STAGES_VERSION = 3
TTT_STAGES = range(15)


def pack_name(stage: int) -> str:
    return f'stage{stage:02}.ast'


def face_names() -> list[str]:
    return [f'face-{i:02}-{what}-hd.bin' for i in FACES for what in ('tile', 'portrait')]


def read_stamp(folder: Path) -> int:
    try:
        return int((Path(folder) / STAMP).read_text(encoding='utf-8').strip())
    except (OSError, ValueError):
        return 0


def current(folder: Path) -> bool:
    """The folder holds all the packs of this version."""
    folder = Path(folder)
    return (read_stamp(folder) >= ARCADE_STAGES_VERSION
            and all((folder / pack_name(s)).is_file() for s in STAGES)
            and all((folder / name).is_file() for name in face_names()))


def ttt_current(folder: Path) -> bool:
    """The folder holds all the TTT packs of this version."""
    folder = Path(folder)
    return (read_stamp(folder) >= TTT_STAGES_VERSION
            and all((folder / pack_name(s)).is_file() for s in TTT_STAGES))
