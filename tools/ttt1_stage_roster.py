#!/usr/bin/env python3
"""Rassemble les invites TTT1 importes en un catalogue unique pour le jeu.

  python3 tools/ttt1_stage_roster.py

Chaque invite importe par tools/ttt1_import.py (workspace/ttt1-import/<cle>/guest)
est copie dans workspace/ttt1-import/roster, avec guests.txt : une cle par
ligne, dans l'ordre de tools/data/ttt1_characters.json. Le runtime le lit
depuis mods/ttt1 a cote de l'executable ; chaque construction y copie ce
dossier, et l'outil l'y installe aussi tout de suite pour les builds existants
(build*/). Au selecteur, R2 / L2 sur la case invitee passent a l'invite suivant /
precedent. Donnees du jeu : workspace/ (ignore par git) et dossiers de
construction, jamais le depot.
"""
import json, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'workspace/ttt1-import'
OUT = WORK / 'roster'
FILES = ('T3-ui.jui', 'T3-name.4bpp', 'T3-label.txt', 'TTT1-arcade-P1.3dm', 'TTT1-arcade-P1.relocs',
         'TTT1-arcade-P1.tim', 'TTT1-combat.jmv', 'TTT1-tables.jst', 'TTT1-idle.poses',
         'TTT1-hiteffect.tim')
# Tekken 3 fighter IDs (names read in the game's character records).
T3_IDS = dict(paul=0, law=1, lei=2, king=3, yoshimitsu=4, nina=5, hwoarang=6, xiaoyu=7, eddy=8, jin=9,
              julia=10, kuma=11, bryan=12, heihachi=13, ogre=14, mokujin=15, gunjack=16, gon=17,
              anna=18, drb=19)
OPTIONAL = ('TTT1-voices.juv',           # Tetsujin ne parle pas
            'TTT1-sfx.jus',
            'TTT1-movelist.bin',           # tools/ttt1/movelist.py
            'TTT1-combos.bin',             # tools/ttt1/combos.py (COMBO TRAINING)
            # costumes 2 (Pied) et 3 (Start)
            *(f'TTT1-arcade-P{c}.{e}' for c in (2, 3) for e in ('3dm', 'relocs', 'tim')))


# Carte MOVESET du sélecteur (src/tekken3_native_moves.c) : les natifs de Tekken 3 sur
# leur moveset TTT1. Numero de personnage T3 (TIPS.md, section 25) -> cle.
T3_NATIVES = {0: 'paul', 1: 'law', 2: 'lei', 3: 'king', 4: 'yoshimitsu', 5: 'nina',
              6: 'hwoarang', 7: 'xiaoyu', 8: 'eddy', 9: 'jin', 10: 'julia',
              12: 'bryan', 13: 'heihachi', 18: 'anna'}
NATIVE_FILES = ('combat.jmv', 'tables.jst', 'idle.poses', 'sfx.jus', 'movelist.bin', 'combos.bin')


def stage_natives(table):
    """<Name>-TTT1-* et natives.txt ("<ID T3> <cle> <moveset TTT1>") pour chaque
    natif dont le moveset TTT1 est importe : son import propre
    (workspace/ttt1-import/natives/<cle>), sinon le donneur d'Unknown."""
    donors = table.get('unknown', {}).get('donor_movesets', {})
    lines, staged = [], []
    for t3, key in sorted(T3_NATIVES.items()):
        if key not in donors: continue
        name = key.capitalize()
        own = WORK / 'natives' / key
        sources = {f: own / f'{name}-TTT1-{f}' for f in NATIVE_FILES}
        if not sources['combat.jmv'].is_file():
            unknown = WORK / 'unknown/guest'
            sources = {f: unknown / f'Unknown@{name}-TTT1-{f}' for f in NATIVE_FILES}
        if not all(sources[f].is_file() for f in NATIVE_FILES[:3]): continue
        for f, src in sources.items():
            if src.is_file(): shutil.copyfile(src, OUT / f'{name}-TTT1-{f}')
        lines.append(f'{t3} {key} {donors[key]}\n'); staged.append(key)
    (OUT / 'natives.txt').write_text(''.join(lines))
    print(f'{len(staged)} natifs sur moveset TTT1 : {", ".join(staged) or "aucun"}')


def main():
    table = json.loads((ROOT / 'tools/data/ttt1_characters.json').read_text())['characters']
    if OUT.exists(): shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    staged, missing = [], []
    for key in table:
        name, guest = key.capitalize(), WORK / key / 'guest'
        paths = [guest / f'{name}-{suffix}' for suffix in FILES]
        if not all(p.is_file() for p in paths):
            missing.append(key); continue
        paths += [p for p in (guest / f'{name}-{suffix}' for suffix in OPTIONAL) if p.is_file()]
        # Moveset tire au hasard (Tetsujin) : la liste des donneurs et leurs fichiers.
        if (guest / f'{name}-TTT1-donors.txt').is_file():
            paths += [guest / f'{name}-TTT1-donors.txt', *sorted(guest.glob(f'{name}@*-TTT1-*'))]
        for p in paths: shutil.copyfile(p, OUT / p.name)
        staged.append(key)
    # One guest per line: its key, then its TTT1 moveset key (0x29EF00), which
    # opponent-specific hit rules of the other guest test; '-' when TTT1 draws
    # it at random (Tetsujin). Third column: the Tekken 3 fighter whose arena
    # the guest takes (its ID; '-' keeps the donor's, Jin's).
    def arena(k):
        owner = table[k].get('arena')
        return str(T3_IDS[owner]) if owner else '-'
    (OUT / 'guests.txt').write_text(''.join(f'{k} {table[k].get("moveset", "-")} {arena(k)}\n' for k in staged))
    # Devil Jin easter egg (tools/ttt1_devil_jin.py): a model and a name, read
    # when Jin is confirmed with both punches, so not a guest line; his moves
    # (tools/ttt1_devil_jin_moves.py) when built.
    egg = sorted((WORK / 'devil-jin/guest').glob('Jin-*'))
    moves = sorted((WORK / 'devil-jin/guest').glob('DevilJin-TTT1-*'))
    for p in egg + moves: shutil.copyfile(p, OUT / p.name)
    if egg: print('Devil Jin: model and name staged' + (', with his moves' if moves else ''))
    print(f'{len(staged)} invites : {", ".join(staged)}')
    if missing: print(f'non importes : {", ".join(missing)}')
    stage_natives(table)
    for exe in sorted(ROOT.glob('build*/Tekken_3_Recompiled*')):
        if not exe.is_file(): continue
        dest = exe.parent / 'mods/ttt1'
        if dest.exists(): shutil.rmtree(dest)
        shutil.copytree(OUT, dest)
        print(f'installe : {dest.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
