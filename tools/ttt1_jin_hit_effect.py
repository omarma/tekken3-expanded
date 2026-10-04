#!/usr/bin/env python3
"""Importe l'effet de coup fort de Jin dans TTT1 (eclair rouge) pour le mod
tekken3.visual.jin-ttt1-hit-effect, qui le montre a la place de son eclair bleu.

  python3 tools/ttt1_jin_hit_effect.py [--ttt1 tektagt.zip]

Meme chaine que l'etape 5 de tools/ttt1_import.py : planche de Jin lue dans la
ROM (archives 3 + 4, tools/ttt1/rom_ram.py), planche
convertie en paquet Tekken 3 de 22 images (sa longueur dans TTT1) (tools/ttt1/hit_effect.py), range
dans workspace/ttt1-import/jin (ignore par git). Chaque construction le copie
dans mods/jin-ttt1-hit-effect a cote de l'executable, ou le lit le mod ;
l'outil l'y installe aussi tout de suite pour les builds existants (build*/).
"""
import argparse, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import ttt1_import as I

KEY, NAME, CHARACTER = 'jin', 'Jin', 9
FOLDER = 'jin-ttt1-hit-effect'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--ttt1', type=Path, help='ton tektagt.zip non fusionne (World TEG2/VER.C1)')
    a = ap.parse_args()
    I.sources(a)
    work = I.WORK / KEY
    work.mkdir(parents=True, exist_ok=True)
    I.hit_effect(KEY, dict(body=CHARACTER, hit_frames=22), work, NAME, work)   # eclair des Mishima : 22 images
    pack = work / f'{NAME}-TTT1-hiteffect.tim'
    installed = []
    for exe in sorted(ROOT.glob('build*/Tekken_3_Expanded*')):
        if not exe.is_file(): continue
        dest = exe.parent / 'mods' / FOLDER
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pack, dest / pack.name)
        installed.append(dest.relative_to(ROOT))
    for d in installed: print(f'installe : {d}/{pack.name}')
    if not installed:
        print(f'aucun executable construit : copier {pack.relative_to(ROOT)} dans mods/{FOLDER}/ a cote du jeu')


if __name__ == '__main__':
    main()
