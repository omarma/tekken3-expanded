#!/usr/bin/env python3
"""Arcade Stages: the 13 stage packs the game reads, made from your tekken3.zip.

    python tools/arcade_stages/install.py --tekken3 tekken3.zip [--out DIR]
    python tools/arcade_stages/install.py --ttt1 tektagt.zip [--out DIR]

Run by the setup (launcher/setup_backend.py) when it is given tekken3.zip
(Tekken 3 arcade, TET2/VER.E1): no MAME, a few seconds. Writes
stage00.ast .. stage12.ast (pack.py, format pack.FORMAT) and version.txt
(version.ARCADE_STAGES_VERSION) into a temporary folder, then puts it in
place of DIR (default workspace/arcade-stages/pack). CMakeLists.txt stages
that folder beside the game as mods/arcade-stages, on PC and Android, where
the Arcade Stages mod reads it (src/tekken3_arcade_stages.c). Without it the
mod keeps the PS1 stages. Nothing from the ROM goes into git.

--ttt1 (TTT Stages S7): the 15 TTT stage packs from tektagt.zip instead
(pack.save_ttt, format 4, stage 4's thunder replayed over the c352 ROM),
same bytes as pack.py --game ttt, and version.txt
(version.TTT_STAGES_VERSION); default DIR workspace/ttt-stages/pack, staged
beside the game as mods/ttt-stages and read with the TTT1 package's feature
TTT Stages. No MAME, a few seconds.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/arcade_stages')]
import version  # noqa: E402

DEFAULT_OUT = ROOT / 'workspace/arcade-stages/pack'
DEFAULT_TTT_OUT = ROOT / 'workspace/ttt-stages/pack'


def install(tekken3: Path, out: Path = DEFAULT_OUT, say=print) -> Path:
    import decode
    import pack
    import scene
    start = time.time()
    arcade = decode.Arcade(tekken3, cache=False)
    temp = out.with_name(out.name + '.new')
    shutil.rmtree(temp, ignore_errors=True)
    temp.mkdir(parents=True)
    for s in version.STAGES:
        path = temp / version.pack_name(s)
        pack.save(scene.Stage(arcade, s), path)
        say(f'stage {s:2}: {path.name} {path.stat().st_size} bytes')
    (temp / version.STAMP).write_text(f'{version.ARCADE_STAGES_VERSION}\n', encoding='utf-8')
    shutil.rmtree(out, ignore_errors=True)
    temp.replace(out)
    say(f'Arcade stages version {version.ARCADE_STAGES_VERSION} in {out} ({time.time() - start:.0f} s)')
    return out


def install_ttt(ttt1: Path, out: Path = DEFAULT_TTT_OUT, say=print) -> Path:
    import pack
    import ttt
    sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt_stages')]
    import music_install
    start = time.time()
    src = ttt.Ttt(ttt1, cache=False)
    rom = music_install.c352_rom(ttt1)          # stage 4's thunder
    temp = out.with_name(out.name + '.new')
    shutil.rmtree(temp, ignore_errors=True)
    temp.mkdir(parents=True)
    for s in version.TTT_STAGES:
        path = temp / version.pack_name(s)
        pack.save_ttt(ttt.Stage(src, s), path, src, rom)
        say(f'TTT stage {s:2}: {path.name} {path.stat().st_size} bytes')
    (temp / version.STAMP).write_text(f'{version.TTT_STAGES_VERSION}\n', encoding='utf-8')
    shutil.rmtree(out, ignore_errors=True)
    temp.replace(out)
    say(f'TTT stages version {version.TTT_STAGES_VERSION} in {out} ({time.time() - start:.0f} s)')
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    which = ap.add_mutually_exclusive_group(required=True)
    which.add_argument('--tekken3', type=Path, help='tekken3.zip (Tekken 3 arcade, TET2/VER.E1)')
    which.add_argument('--ttt1', type=Path, help="tektagt.zip (Tekken Tag Tournament arcade): TTT's stages")
    ap.add_argument('--out', type=Path)
    args = ap.parse_args(argv)
    if args.ttt1:
        install_ttt(args.ttt1.resolve(), (args.out or DEFAULT_TTT_OUT).resolve())
    else:
        install(args.tekken3.resolve(), (args.out or DEFAULT_OUT).resolve())
    return 0


if __name__ == '__main__':
    sys.exit(main())
