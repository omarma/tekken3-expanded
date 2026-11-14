#!/usr/bin/env python3
"""The Tekken 3 data track (track 1) in a disc/ folder the setup wrote.

psxrecomp's prepare_disc (game.toml [prepare_disc]) always writes the cue as
disc/Tekken 3 (USA).cue, but the track files keep the names the player's dump
gives them: a Redump set its own ("Tekken 3 (USA) (Track 1).bin"), a
single-file dump the setup split (launcher/setup_backend.py single_bin) its
stem + " (Track N).bin" ("Tekken 3 (Track 1).bin" for "Tekken 3.bin"). So a
tool reads the track 1 the cue names, never a name of its own (B187).

    from disc_track import data_track
    data_track(ROOT / 'disc')
"""
from __future__ import annotations

import re
from pathlib import Path

CUE = 'Tekken 3 (USA).cue'
# Without a cue (an older checkout): the names the setup has written.
KNOWN = ('Tekken 3 (USA) (Track 1).bin', 'Tekken 3 (Track 1).bin')


def data_track(disc: Path) -> Path:
    """disc's track 1: the first FILE of its cue, else a known name, else the
    one '* (Track 1).bin'. FileNotFoundError says what was looked for."""
    disc = Path(disc)
    cues = [disc / CUE] + sorted(p for p in disc.glob('*.cue') if p.name != CUE)
    for cue in cues:
        if not cue.is_file():
            continue
        found = re.search(r'FILE\s+"([^"]+)"', cue.read_text(encoding='utf-8', errors='replace'), re.I)
        if found and (disc / found[1]).is_file():
            return disc / found[1]
    for name in KNOWN:
        if (disc / name).is_file():
            return disc / name
    tracks = sorted(disc.glob('* (Track 1).bin')) + sorted(disc.glob('* (Track 01).bin'))
    if len(tracks) == 1:
        return tracks[0]
    raise FileNotFoundError(f'no Tekken 3 data track in {disc} (its cue {CUE} names none that exists)')


if __name__ == '__main__':
    import sys
    print(data_track(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / 'disc'))
