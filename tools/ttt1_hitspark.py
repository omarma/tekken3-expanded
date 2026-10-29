#!/usr/bin/env python3
"""Effets de coup fort de TTT1 pour les natifs de Tekken 3 (mod TTT Hitspark, F12).

  python3 tools/ttt1_hitspark.py [--ttt1 tektagt.zip]

TTT1 a sa propre planche 64 x 64 pour chaque personnage de Tekken 3 sauf Gon et
Dr. B (archives 3 + 4, tools/ttt1/rom_ram.py, sans MAME). Pour chaque natif :
<Nom>-TTT1-hiteffect64.hfx (tools/ttt1/hit_effect.py, hfx_pack), de la longueur
que T3 joue pour lui (en-tete 0x80027950 : 22 pour l'eclair de Jin et de
Heihachi, 30 sinon), dans workspace/ttt1-import/hitspark (ignore par git) ;
tools/ttt1_stage_roster.py les met dans le catalogue (mods/ttt1). Le runtime
les dessine a la place de l'effet 32 x 32 du natif (src/tekken3_ttt1_combat.c).
Aussi Jin-TTT1-hiteffect.tim, l'eclair rouge de Jin en paquet T3 32 x 32, que
les cinematiques TTT emportent (tools/ttt_cinematics.py). Remplace l'ancien mod
de l'eclair rouge de Jin (tools/ttt1_jin_hit_effect.py).

Et les deux etincelles communes de TTT1, 30 images 64 x 64 chacune, que le
runtime montre a la place de celles de T3 : Spark-TTT1-hiteffect64.hfx, la
gerbe d'un coup qui touche (ligne 28 de 8001AD30, sa palette rouge de la ROM ;
MAME la montre verte avec le reglage d'usine de l'option des Service Options),
et Guard-TTT1-hiteffect64.hfx, les etincelles d'un coup garde (ligne 30, teinte
du jeu 80 / 96 / 128 : gris bleute). tools/ttt1/rom_ram.py SPARK_ROW, GUARD_ROW.
Puis (F22) Throw-TTT1-hiteffect64.hfx, l'etincelle rose d'une projection (ligne
29, 28 images, teinte 128 / 80 / 128), Smoke-TTT1-hiteffect64.hfx, la fumee
d'une mise a terre (ligne 33, 30 images), et Mist-TTT1-hiteffect64.hfx, le
brouillard empoisonne de Nina et Yoshimitsu : 21 images prises dans la planche
de la fumee, avec sa propre palette (rom_ram.mist) ; le runtime les retrouve
dans les cases de la fumee et n'en place que la palette.
"""
import argparse, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import ttt1_import as I

OUT = I.WORK / 'hitspark'
# Natif de Tekken 3 (ID) -> son personnage dans TTT1 (le meme numero) ; Gon (17)
# et Dr. B (19) ne sont pas dans TTT1 : le runtime leur donne le paquet de Heihachi,
# leur paquet T3 de 22 images etant le sien a l'octet (F22).
NATIVES = dict(paul=0, law=1, lei=2, king=3, yoshimitsu=4, nina=5, hwoarang=6, xiaoyu=7, eddy=8, jin=9, julia=10,
               kuma=11, bryan=12, heihachi=13, ogre=14, mokujin=15, gunjack=16, anna=18, trueogre=20)
MISHIMA = (9, 13)                      # 22 images, comme l'en-tete T3 ; 30 pour les autres
COMMON = dict(Spark='SPARK_ROW', Guard='GUARD_ROW', Throw='THROW_ROW', Smoke='SMOKE_ROW')   # la longueur de TTT1


def write(out=OUT):
    import hit_effect as H, rom_ram as R
    out.mkdir(parents=True, exist_ok=True)
    for key, character in NATIVES.items():
        frames = 22 if character in MISHIMA else 30
        vram = R.effect_vram(I.TTT1, character, 0)
        (out / f'{key.capitalize()}-TTT1-hiteffect64.hfx').write_bytes(H.hfx_pack(vram, 0, frames))
        if key == 'jin': (out / 'Jin-TTT1-hiteffect.tim').write_bytes(H.t3_pack(vram, 0, frames))
    for name, row in COMMON.items():
        vram = R.effect_row_vram(I.TTT1, getattr(R, row))
        (out / f'{name}-TTT1-hiteffect64.hfx').write_bytes(H.hfx_pack(vram, 0, R.effect_row_frames(I.TTT1, getattr(R, row))))
    order, palette = R.mist(I.TTT1)
    (out / 'Mist-TTT1-hiteffect64.hfx').write_bytes(H.hfx_pack(R.effect_row_vram(I.TTT1, R.SMOKE_ROW), 0, order=order, palette=palette))
    print(f'TTT Hitspark : {len(NATIVES)} natifs, {len(COMMON)} etincelles communes et le brouillard dans {out.relative_to(ROOT)}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--ttt1', type=Path, help='ton tektagt.zip non fusionne (World TEG2/VER.C1, US TEG3/VER.C1 ou VER.B, Japon TEG1/VER.C1)')
    a = ap.parse_args()
    I.sources(a)
    write()


if __name__ == '__main__':
    main()
