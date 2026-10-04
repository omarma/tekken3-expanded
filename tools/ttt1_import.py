#!/usr/bin/env python3
"""Importe un personnage de Tekken Tag Tournament (arcade) comme invite natif de Tekken 3.

    python3 tools/ttt1_import.py <personnage> [--ttt1 tektagt.zip]

<personnage> est une cle de tools/data/ttt1_characters.json (kunimitsu, bruce...) ;
une cle de sa section natives (kuma, ogre, gunjack, trueogre) importe seulement le
moveset TTT1 de ce natif de Tekken 3 (carte MOVESET du selecteur).
Enchaine, sans code propre au personnage :

1. RAM de l'ecran de selection du personnage et du temoin Xiaoyu, refaite
   depuis la ROM (tools/ttt1/rom_ram.py) et rangee sous
   workspace/ttt1-import/captures/ ; les cles lues a 0x29EF00 doivent
   correspondre a la table ;
2. modele : banque TTT1 -> format PS1 (tools/ttt1/model/convert.py, placement
   deduit du modele) et textures rangees dans la bande costume (texpack.py) ;
3. animations, combat solo, voix et sons (tools/ttt1/motion.py, moves.py,
   voices.py, sfx.py : registres du C352 releves une fois dans MAME et gardes
   dans tools/data/, rejoues sur le c352.bin de l'utilisateur, sans MAME) ;
4. nom (police PS1, tools/ttt1/glyphs.py) et interface : grand portrait de
   l'ecran de chargement TTT1 et vignette de grille, lus dans la ROM, et les
   cases recadrees dessus (tools/ttt1/ui_art.py, ui.py) ;
5. effet de coup fort : la planche du personnage (archives 3 + 4 de la ROM,
   placee comme dans la VRAM d'un combat), convertie en paquet d'effet
   Tekken 3 (tools/ttt1/hit_effect.py).

Tout vient des fichiers de l'utilisateur : son tektagt.zip non fusionne (World TEG2/VER.C1, chaque puce verifiee par SHA-1 par
arcade_model_probe.reconstruct) et son disque Tekken 3 USA (disc/, pour
l'executable et la police des noms). Le depot ne contient aucune donnee du jeu :
ni modele, ni texture, ni portrait, ni son.

Sortie : workspace/ttt1-import/<personnage>/guest/, que
tools/ttt1_stage_roster.py range dans le catalogue du jeu ; seul, lancer avec
TEKKEN3_GUEST=<personnage> TEKKEN3_TTT1_ASSETS=<dossier>.
Donnees du jeu : tout reste sous workspace/ (ignore par git).
"""
import argparse, json, os, shutil, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt1'), str(ROOT / 'tools/ttt1/model')]
TABLE = ROOT / 'tools/data/ttt1_characters.json'
WORK = ROOT / 'workspace/ttt1-import'
CAPTURES = WORK / 'captures'
TTT1 = WORK / 'ttt1'                                 # regions ROM reconstruites et verifiees
SOURCE = WORK / 'source.json'                        # chemins choisis par l'utilisateur
KEYS, DIRECTORY = 0x29ef00, 0x302238


def choose(title, pattern):
    import tkinter as tk
    from tkinter import filedialog
    window = tk.Tk(); window.withdraw()
    value = filedialog.askopenfilename(title=title, filetypes=[('Fichier requis', pattern)])
    window.destroy()
    if not value: raise SystemExit('Import annule.')
    return Path(value).resolve()


def sources(args):
    """ROM TTT1 de l'utilisateur, verifiee puce par puce ; memorisee."""
    if not (ROOT / 'disc/SLUS_004.02').is_file():
        raise SystemExit('Il faut d abord generer le jeu depuis ton disque Tekken 3 USA (disc/SLUS_004.02).')
    known = json.loads(SOURCE.read_text()) if SOURCE.exists() else {}
    zip_path = args.ttt1 or (Path(known['ttt1']) if known.get('ttt1') and Path(known['ttt1']).is_file() else None)
    zip_path = (zip_path or choose('Ton tektagt.zip (TTT1 arcade, non fusionne)', '*.zip')).resolve()
    WORK.mkdir(parents=True, exist_ok=True)
    # Lu et ecrit par les imports paralleles : n'ecrire que s'il change, et
    # d'un bloc (sinon un autre import peut lire un fichier vide).
    text = json.dumps(dict(ttt1=str(zip_path)), indent=2) + '\n'
    if not SOURCE.is_file() or SOURCE.read_text() != text:
        tmp = SOURCE.with_name(f'.source-{os.getpid()}.json'); tmp.write_text(text); os.replace(tmp, SOURCE)
    names = ('bankedroms.bin', 'c352.bin', 'sub.bin', 'maincpu_rom.bin')
    if not all((TTT1 / n).is_file() for n in names):
        import arcade_model_probe as probe
        print('Verification des puces de tektagt.zip...', flush=True)
        definition = json.loads(probe.MANIFEST.read_text())['sets']['tektagt']
        regions, _ = probe.reconstruct(zip_path, definition)
        TTT1.mkdir(exist_ok=True)
        for k, data in regions.items(): (TTT1 / (k.replace(':', '_') + '.bin')).write_bytes(data)


def capture_select(key, entry):
    """RAM de l'ecran de selection, curseur sur le personnage : refaite depuis la
    ROM (tools/ttt1/rom_ram.py, identique aux captures MAME pour ce que lit
    l'import), rangee sous captures/ comme l'etaient les captures."""
    import rom_ram as R
    ram = CAPTURES / f'{key}-select-ram.bin'
    if ram.exists(): return ram
    CAPTURES.mkdir(parents=True, exist_ok=True)
    ram.write_bytes(R.select(R.boot(TTT1), *R.character(key, entry), entry.get('force_moveset')))
    print(f'RAM de selection (ROM) -> {ram.name}')
    return ram


def check_keys(ram, key, entry):
    moveset, body, sound, asset2 = struct.unpack_from('<4H', ram.read_bytes(), KEYS + 0x10)
    got = dict(asset=asset2 // 2, moveset=moveset, body=body, sound=sound)
    want = {k: entry[k] for k in got if k in entry}
    if any(got[k] != v for k, v in want.items()):
        raise SystemExit(f'{key} : cles lues {got}, attendues {want} -- le curseur est ailleurs')
    return dict(got, slot=asset2)                        # emplacement du modele, costume compris


# Costumes supplementaires (emplacements 109..) : (texture, modele) releves en
# combat TTT1, 2026-09-24 -- modele retrouve dans la RAM du combat, compare au
# meme invite au Poing ; texture retrouvee dans la VRAM (images et palettes).
# Textures 223.., modeles 246.., sans lien avec l'ordre des emplacements : la
# regle 246 + (emplacement - 109) donnait des costumes d'Anna. Le jeu prend
# ces paires dans sa table 0x8019E3B4 (emplacement a l'indice k -> archives
# 26/k et 27/k, tools/ttt1/extract.py) : Devil au Pied = texture 230 et modele
# 253 (Devil violet), confirme par capture le 2026-10-04 ; le modele 175 du
# costume 1 laissait 272 coins de texture decales.
EXTRA = {109: (227, 250), 110: (230, 253), 115: (236, 259), 116: (237, 260),
         117: (238, 261), 118: (239, 262),
         # Unknown (index 33, force_index) : modeles retrouves au survol (0x354108),
         # releve du 2026-09-25 ; 114 (variante 7) est le loup, pas un costume.
         112: (233, 256), 113: (234, 257)}


def entries(slot):
    """Entrees (texture, modele) du repertoire 0x302238 pour un emplacement.
    Emplacements 0..108 : textures 0..108, modeles 109..217. Au-dela : table
    EXTRA."""
    if slot < 109: return slot, 109 + slot
    if slot not in EXTRA: raise SystemExit(f'emplacement {slot} : costume supplementaire non releve en combat (EXTRA)')
    return EXTRA[slot]


# Expressions du visage (TTT1 0x80104C64 et voisines, RAM du selecteur). Par emplacement,
# 8 octets en 0x801945D8 : octet 0 = case de l'image affichee, octet 1 = taille, octet 2 =
# case ou le jeu sauve l'image neutre (hors atlas), octets 3.. = cases des expressions
# 1, 2... jusqu'a -1. Case k = (x, y) en 0x80193FE0 + 4k, taille k = (l, h) en 0x801940CC
# + 4k, en demi-mots depuis le coin de l'atlas. Expression e d'une propriete 0x25 + e (duree
# = argument, combat_semantics) ; quand la duree s'acheve, neutre pour 1..255 trames au
# hasard puis l'expression de clignement 0x801949C0[emplacement] pour 3 trames (0x80105978).
# A chaque trame (0x80105904), un enregistrement au drapeau 0x800 (+0x24) impose
# 0x80194A40[emplacement], sinon un au drapeau 4 (+4) sans le bit 22 (+0x24) 0x80194AC0.
FACES, FACE_POS, FACE_SIZE, FACE_BLINK = 0x1945d8, 0x193fe0, 0x1940cc, 0x1949c0
FACE_FLAG_A, FACE_FLAG_B = 0x194a40, 0x194ac0


def faces(d, slot):
    """(rectangle affiche, [cases des expressions 1..], expressions de clignement et des
    drapeaux A et B) ou None."""
    e = struct.unpack_from('8b', d, FACES + slot * 8)
    if e[0] < 0: return None
    pos = lambda k: struct.unpack_from('<2h', d, FACE_POS + 4 * k)
    w, h = struct.unpack_from('<2h', d, FACE_SIZE + 4 * e[1])
    sources = []
    for k in e[3:]:
        if k < 0: break
        sources.append(pos(k))
    return (*pos(e[0]), w, h), sources, (d[FACE_BLINK + slot], d[FACE_FLAG_A + slot], d[FACE_FLAG_B + slot])


def model(ram, slot, out, name, work, costume=1):
    import convert, texpack, check_texpack
    from fmt import load
    bank = (TTT1 / 'bankedroms.bin').read_bytes(); d = ram.read_bytes()
    work.mkdir(parents=True, exist_ok=True)
    ti, mi = entries(slot)
    mo, mn = struct.unpack_from('<II', d, DIRECTORY + mi * 8)
    to, tn = struct.unpack_from('<II', d, DIRECTORY + ti * 8)
    (work / 'ttt1.3dm').write_bytes(bank[mo:mo + mn]); (work / 'ttt1.tex').write_bytes(bank[to:to + tn])
    src, tex = load(work / 'ttt1.3dm'), bank[to:to + tn]
    face = faces(d, slot)
    shown, sources, (blink, flag_a, flag_b) = face or ((), [], (0, 0, 0))
    try:
        report = texpack.plan(tex, src, [shown] + [(x, y) + shown[2:] for x, y in sources] if face else ())
    except ValueError as e:
        if not str(e).startswith('visage'): raise
        print(f'ATTENTION : {e} ; costume sans expressions du visage')
        face = None; report = texpack.plan(tex, src)
    ps1, relocs = convert.convert(src)
    base = out / f'{name}-TTT1-arcade-P{costume}'
    base.with_suffix('.3dm').write_bytes(ps1)
    base.with_suffix('.relocs').write_bytes(struct.pack(f'<{len(relocs)}I', *relocs))
    base.with_suffix('.tim').write_bytes(texpack.repack(tex))
    # Lu par tekken3_ttt1_face_tick() : 'FACE', image affichee (x, y, l, h) a sa place dans
    # le .tim, expression de clignement, nombre d'expressions, leurs images (x, y), puis
    # les expressions des drapeaux A et B.
    base.with_suffix('.face').unlink(missing_ok=True)
    placed = face and [texpack.face_at(*shown)] + [texpack.face_at(x, y, *shown[2:]) for x, y in sources]
    if face and None in placed:
        print('ATTENTION : textures rognees (texpack, etape 5) : costume sans expressions du visage')
    elif face:
        base.with_suffix('.face').write_bytes(b'FACE' + struct.pack(
            f'<6H{2 * len(sources)}H2H', *placed[0], *shown[2:], blink, len(sources), *sum(placed[1:], ()),
            flag_a, flag_b))
        report['face'] = dict(shown=placed[0], size=shown[2:], expressions=placed[1:], blink=blink,
                              flag_a=flag_a, flag_b=flag_b)
    layout = {s: t for s, t in convert.S2T.items() if s > 20}
    print(f'modele : {len(ps1)} o, {len(relocs)} relocalisations, lignes 21..26 <- {layout}, '
          f'seconds maillages {convert.SECOND}')
    lost = convert.unplaced(src)
    if lost: print(f'ATTENTION : lignes TTT1 a maillage sans place PS1, non dessinees : {lost}')
    print(f'textures : {report["total"]} demi-mots, {len(report["moved"])} deplacees, '
          f'{len(report["reduced"])} reduites en 16 couleurs')
    bad = check_texpack.main(work / 'ttt1.3dm', work / 'ttt1.tex', base.with_suffix('.3dm'), base.with_suffix('.tim'))
    return dict(bytes=len(ps1), relocations=len(relocs), layout=layout, second=convert.SECOND, limbs=convert.limb_map(src), unplaced_rows=lost,
                textures=report, texture_mismatches=bad)


def motion(ram, witness, out, name, work):
    import motion as M
    r = M.export(ram.read_bytes(), witness.read_bytes(), (TTT1 / 'bankedroms.bin').read_bytes(),
                 work, name, witness.name)
    shutil.copyfile(work / f'{name}-TTT1-idle.poses', out / f'{name}-TTT1-idle.poses')
    print(f'animations : {len(r["records"])} enregistrements, {len(r["clips"])} clips')
    return dict(records=len(r['records']), clips=len(r['clips']), idle=r['idle_source'], manifest=r)


def capture_aliases(moveset):
    """Table d'alias (0x2A7350) du personnage qui a ce moveset, lue dans sa
    capture de selection (faite au besoin) : les regles des Jacks sur la
    reaction aux lasers de Devil / Angel (tools/ttt1/moves.py SELF_MOVESET)."""
    table = json.loads(TABLE.read_text())
    for key, entry in list(table['characters'].items()) + list(table['natives'].items()):
        if entry.get('moveset', entry.get('t3')) != moveset or 'capture' in entry or 'path' not in entry and \
                entry.get('force_index') is None: continue
        data = capture_select(key, entry).read_bytes()
        if struct.unpack_from('<H', data, KEYS + 0x10)[0] == moveset:
            return struct.unpack_from('<5515I', data, 0x2a7350)
    return None


def moves(ram, keys, records, limb_map, out, name, suffix=''):
    import moves as C
    combat, tables, report = C.convert(ram.read_bytes(), (TTT1 / 'bankedroms.bin').read_bytes(),
                                       records, keys['moveset'], keys['body'], limb_map, aliases_of=capture_aliases)
    if suffix:                                         # costume : seulement ce qui differe du costume 1
        same = (out / f'{name}-TTT1-combat.jmv').read_bytes() == combat and \
               (out / f'{name}-TTT1-tables.jst').read_bytes() == tables
        for f in (f'{name}-TTT1-combat{suffix}.jmv', f'{name}-TTT1-tables{suffix}.jst'): (out / f).unlink(missing_ok=True)
        if same: return dict(shared=True)
    (out / f'{name}-TTT1-combat{suffix}.jmv').write_bytes(combat)
    (out / f'{name}-TTT1-tables{suffix}.jst').write_bytes(tables)
    print(f'combat : {report["records"]} enregistrements, {report["cancel_entries"]} annulations, '
          f'regles ecartees {report["omitted_rules"]}')
    if report['truncated_event_scripts']:
        print(f'ATTENTION : scripts d evenements tronques a une entree inconnue : {report["truncated_event_scripts"]}')
    if report['defender_specific_cancel_rules']:
        print(f'reaction aux lasers : {report["defender_specific_cancel_rules"]} regles des Jacks, '
              f'{report["laser_reaction_moves"]} enregistrements a eux')
    return {k: report[k] for k in ('records', 'clips', 'cancel_entries', 'omitted_rules',
                                   'defender_specific_cancel_rules', 'laser_reaction_moves',
                                   'omitted_conditions', 'truncated_event_scripts', 'sound_indexes')}


def costumes(ram, keys, entry, records, limbs, out, name, work):
    """Costumes 2 et 3 (Pied, Start au selecteur TTT1), emplacements releves
    par tools/ttt1_select_probe.lua : <Name>-TTT1-arcade-P2 / -P3. Un fichier
    de coups -P<n> seulement si le squelette du costume change les coups. Un
    costume qui ne se convertit pas est signale et ecarte, sans bloquer.
    null dans la liste : pas de costume a ce rang (Tetsujin au Pied)."""
    slots = entry.get('costumes', [keys['slot']])
    for c in (2, 3):
        for e in ('3dm', 'relocs', 'tim', 'face'): (out / f'{name}-TTT1-arcade-P{c}.{e}').unlink(missing_ok=True)
        for f in (f'{name}-TTT1-combat-P{c}.jmv', f'{name}-TTT1-tables-P{c}.jst'): (out / f).unlink(missing_ok=True)
    report = {'1': dict(slot=slots[0])}
    for c, slot in enumerate(slots[1:], 2):
        if slot is None: continue                          # pas de costume : le jeu reprend le costume 1
        print(f'costume {c} (emplacement {slot}) :')
        try:
            m = model(ram, slot, out, name, work / f'costume{c}', c)
        except ValueError as e:
            print(f'ATTENTION : costume {c} non converti, ecarte : {str(e).splitlines()[-1]}')
            for e in ('3dm', 'relocs', 'tim', 'face'): (out / f'{name}-TTT1-arcade-P{c}.{e}').unlink(missing_ok=True)
            report[str(c)] = dict(slot=slot, error=str(e))
            continue
        mv = moves(ram, keys, records, m['limbs'], out, name, f'-P{c}') if m['limbs'] != limbs else dict(shared=True)
        report[str(c)] = dict(slot=slot, model=m, moves=mv)
    return report


def voices(ram, keys, out, name):
    import voices as V
    data = ram.read_bytes()
    if not V.sound_table(data, keys['sound'])[1]:
        print('ATTENTION : aucun echantillon de voix dans son profil son (Tetsujin) : pas de pack de voix')
        return dict(samples=0)
    r = V.build(data, keys['sound'], (TTT1 / 'sub.bin').read_bytes(),
                (TTT1 / 'c352.bin').read_bytes(), out, name)
    print(f'voix : {len(r["samples"])} echantillons, groupes {r["group_counts"]}')
    return dict(samples=len(r['samples']), groups=r['group_counts'])


def sounds(ram, indexes, profile, out, name):
    import sfx
    # TTT1 (8011418x, 801148D0) answers a hit on a fighter of sound profile 18, 30 or 35
    # (Gun Jack, Jack-2, P.Jack) with a metallic clang instead of the limb's impact; T3 does so
    # for its ID 16 only. The Jacks' packs carry the clang (tekken3_ttt1_sfx.c).
    if profile in sfx.METAL_PROFILES: indexes = sorted(set(indexes) | set(sfx.METAL_HIT_SOUNDS))
    data = ram.read_bytes()
    announced = sfx.name_index(data, profile)
    # Without MAME: the driver's C352 writes, measured once (tools/data/
    # ttt1_sfx_registers.json), replayed over the user's c352.bin. Empty
    # entries of the table (Tetsujin's name: 0) have no sound.
    table = sfx.table(data)
    need = {i for i in set(indexes) | {announced} if i in sfx.RAW or (0 < i < len(table) and table[i][0])}
    recorded = sfx.measured((TTT1 / 'c352.bin').read_bytes(), need)
    if announced in recorded:
        pcm, info = recorded[announced]
        recorded[sfx.NAME] = (pcm, dict(info, index=sfx.NAME, name_of_index=announced))
        indexes = list(indexes) + [sfx.NAME]
    r = sfx.build(indexes, recorded, out, name)
    print(f'sons hors voix : {r["sounds"]} sons ({r["bytes"]} o)' +
          (f', muets ou absents {r["silent_or_missing"]}' if r['silent_or_missing'] else '') +
          (f', coupes au pas de l oracle {r["truncated"]}' if r['truncated'] else ''))
    return {k: r[k] for k in ('sounds', 'bytes', 'silent_or_missing', 'truncated')}


def name_bitmap(label, out, name):
    import glyphs
    img, prov = glyphs.name_image(label)
    px = img.tobytes()
    (out / f'{name}-T3-name.4bpp').write_bytes(bytes(px[i] | px[i + 1] << 4 for i in range(0, len(px), 2)))
    img.point(lambda p: min(255, p * 17)).save(out / f'{name}-T3-name.png')
    (out / f'{name}-T3-label.txt').write_text(label + '\n')    # texte du selecteur, lu par le runtime
    print(f'nom : {label}, {img.width} px')
    return dict(label=label, width=img.width, glyphs=prov)


def hit_effect(key, entry, out, name, work):
    """Effet de coup fort du personnage, tel que TTT1 l'envoie en VRAM au combat
    (planche des archives 3 + 4, refaite depuis la ROM par rom_ram.effect_vram),
    converti en paquet d'effet Tekken 3."""
    import hit_effect as H, rom_ram as R
    # Longueur de l'effet dans TTT1 (hit_frames : 22 pour les Mishima, 30 sinon)
    pack = H.t3_pack(R.effect_vram(TTT1, *R.character(key, entry)), 0, entry.get('hit_frames', H.T3_FRAMES))
    (out / f'{name}-TTT1-hiteffect.tim').write_bytes(pack)
    H.preview(pack).save(work / 'coup-fort.png')
    print(f'effet de coup fort : {len(pack) // 576} images 32 x 32 (apercu {(work / "coup-fort.png").relative_to(ROOT)})')
    return dict(frames=len(pack) // 576, bytes=len(pack))


def ui_ttt1(key, entry, out, name, work):
    """Interface reprise de TTT1, lue dans la ROM : grand portrait de chargement
    (rom_ram.portrait) ; cases de grille et icones de chargement recadrees dans
    ce portrait a l'endroit que montre la vignette de grille TTT1 (thumbnail :
    archive et fichier, releves sur les captures MAME ; vignette agrandie si le
    portrait est un autre rendu). Sans vignette a lui (case partagee avec un
    autre : Angel, Alex ; case cachee : Tetsujin), cadrage tile_box de la
    table, sinon tete recadree."""
    import ui_art, ui as U, rom_ram as R
    w, h, pixels, pal = R.portrait(TTT1, *R.character(key, entry))
    portrait = ui_art.rgba(pixels, w, h, pal)
    portrait.save(work / 'ttt1-portrait.png')
    thumb = None
    if entry.get('thumbnail'):
        w, h, pixels, pal = R.tim8(R.file(TTT1, *entry['thumbnail']))
        thumb = ui_art.rgba(pixels, w, h, pal, clear_zero=False).convert('RGB')
        thumb.save(work / 'ttt1-vignette-grille.png')
    else:
        (work / 'ttt1-vignette-grille.png').unlink(missing_ok=True)
    images, how = ui_art.t3_images(portrait, thumb, entry.get('tile_box'))
    print(f'cases de grille : {how}')
    pack, tims = U.pack(images)
    for (iname, *_), tim in zip(U.SPECS, tims):
        images[iname].save(out / f'{name}-T3-{iname}-source.png')
        (out / f'{name}-T3-{iname}.tim').write_bytes(tim)
    (out / f'{name}-T3-ui.jui').write_bytes(pack)
    print(f'interface : {len(pack)} o, portrait et cases depuis la ROM TTT1')
    return dict(source='ttt1', bytes=len(pack), thumbnail=entry.get('thumbnail'))


def donor_moveset(entry, table, donor_key):
    """Moveset TTT1 d'un donneur : celui d'un invite de la table, ou d'un natif
    de Tekken 3 que TTT1 a aussi (donor_movesets, Unknown)."""
    if donor_key in table and 'moveset' in table[donor_key]: return table[donor_key]['moveset']
    return entry['donor_movesets'][donor_key]


# Un donneur qui est aussi un invite : ses fichiers de coups, deja convertis
# pour lui, valent la conversion sur l'hote (la ROM, verifiee a l'installation,
# est la meme pour tous), sauf pour les paires de REUSE, que tient a jour
# tools/ttt1_setup.py --check-donor-reuse. Liste d'une autre version de
# l'import : tout est converti.
REUSE = ROOT / 'tools/data/ttt1_donor_reuse.json'
REUSED = ('combat.jmv', 'tables.jst', 'idle.poses')


def reusable(key, donor_key):
    """Les sons du moveset de l'invite donor_key si ses fichiers de coups
    servent tels quels a key@donor_key ; None : convertir."""
    import ttt1_import_version as V
    rules, report = json.loads(REUSE.read_text()), WORK / donor_key / 'import-report.json'
    if rules['import_version'] != V.TTT1_IMPORT_VERSION or donor_key in rules['convert'].get(key, []) \
            or not report.is_file(): return None
    report = json.loads(report.read_text())               # ecrit en dernier : l'invite est complet
    if report.get('import_version') != V.TTT1_IMPORT_VERSION: return None
    return report['moves']['sound_indexes']


def donor(key, entry, table, donor_key, witness, own, convert_all=False):
    """Tetsujin avec le moveset d'un donneur : TTT1 le tire au hasard (0x801293F0)
    a la selection, a chaque round et a chaque entree par tag. La capture de
    selection impose le tirage (tools/ttt1_select_probe.lua, TTT1_MOVESET) : le
    jeu charge lui-meme ce moveset sur Tetsujin, dont le corps (code 15) reste
    celui que voient les regles de coups. Sortie : <Name>@<Donneur>-TTT1-combat.jmv,
    -tables.jst, -idle.poses et -sfx.jus a cote des fichiers de Tetsujin."""
    import convert
    from fmt import load
    moveset = donor_moveset(entry, table, donor_key)
    work = WORK / key; out = work / 'guest'
    name = f'{key.capitalize()}@{donor_key.capitalize()}'
    sound_indexes = None if convert_all else reusable(key, donor_key)
    if sound_indexes is not None:
        print(f'\n{name} (moveset {moveset}) : coups repris de {donor_key}/guest')
        for e in REUSED:
            shutil.copyfile(WORK / donor_key / 'guest' / f'{donor_key.capitalize()}-TTT1-{e}', out / f'{name}-TTT1-{e}')
        # Les sons suivent le corps de l'hote. Table des sons et profils : les
        # memes dans toutes les captures de selection, celle de l'hote suffit.
        keys = check_keys(own, key, entry)
        return dict(donor=donor_key, reused=True, sounds=sounds(own, sound_indexes, keys['sound'], out, name))
    print(f'\n{name} (moveset {moveset}) :')
    ram = capture_select(f'{key}@{donor_key}', dict(entry, force_moveset=moveset))
    keys = check_keys(ram, key, dict(entry, moveset=moveset))
    convert.convert(load(work / 'ttt1.3dm'))            # placement du modele, lu par limb_map
    limbs = convert.limb_map(load(work / 'ttt1.3dm'))
    report = dict(donor=donor_key, keys=keys)
    report['motion'] = motion(ram, witness, out, name, work / f'@{donor_key}')
    records = report['motion'].pop('manifest')['records']
    report['moves'] = moves(ram, keys, records, limbs, out, name)
    # Le nom annonce est celui du corps (profil de son de l'invite), quel que soit le donneur.
    report['sounds'] = sounds(ram, report['moves']['sound_indexes'], keys['sound'], out, name)
    (work / f'@{donor_key}' / 'import-report.json').write_text(json.dumps(report, indent=2, default=str) + '\n')
    return report


def native(key, entry):
    """Natif de Tekken 3 sur son moveset TTT1 quand Unknown ne le prend pas
    (Kuma, Ogre, Gun Jack, True Ogre : regle d'annulation, tools/data/ttt1_characters.json,
    natives). Capture du natif TTT1 lui-meme a son index (force_index, comme
    Unknown) : moveset et corps sont les siens. Sortie
    workspace/ttt1-import/natives/<cle>/<Nom>-TTT1-combat.jmv, -tables.jst,
    -idle.poses et -sfx.jus, que tools/ttt1_stage_roster.py range (natives.txt)."""
    import convert
    from fmt import load
    work = WORK / 'natives' / key; work.mkdir(parents=True, exist_ok=True)
    name = key.capitalize()
    print(f'\n{entry["label"]} (natif, index {entry["force_index"]}) :')
    # True Ogre : le selecteur TTT1 ne sait pas le montrer (modele eclate, cles
    # vides) ; il a le moveset d'Ogre (14) et ses propres corps et son
    # (enregistrement de l'index 20) : la capture d'Ogre, ses cles a lui.
    own = {k: entry[k] for k in ('body', 'sound') if 'capture' in entry and k in entry}
    ram = capture_select(entry.get('capture', key), entry)
    witness = capture_select('xiaoyu', dict(path=''))
    keys = dict(check_keys(ram, key, {k: v for k, v in entry.items() if k not in own}), **own)
    print(f'{entry["label"]} : {keys}')
    # Placement des membres lu sur le modele TTT1 du natif (les regles de
    # toucher), comme pour un donneur sur celui d'Unknown.
    bank, d = (TTT1 / 'bankedroms.bin').read_bytes(), ram.read_bytes()
    mo, mn = struct.unpack_from('<II', d, DIRECTORY + entries(keys['slot'])[1] * 8)
    (work / 'ttt1.3dm').write_bytes(bank[mo:mo + mn])
    convert.convert(load(work / 'ttt1.3dm'))
    limbs = convert.limb_map(load(work / 'ttt1.3dm'))
    report = dict(native=key, label=entry['label'], keys=keys)
    report['motion'] = motion(ram, witness, work, name, work / 'motion')
    records = report['motion'].pop('manifest')['records']
    report['moves'] = moves(ram, keys, records, limbs, work, name)
    report['sounds'] = sounds(ram, report['moves']['sound_indexes'], keys['sound'], work, name)
    (work / 'import-report.json').write_text(json.dumps(report, indent=2, default=str) + '\n')
    print(f'\nnatif pret : {work.relative_to(ROOT)} ; catalogue du jeu : python3 tools/ttt1_stage_roster.py')
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('character')
    ap.add_argument('--ttt1', type=Path, help='ton tektagt.zip non fusionne (World TEG2/VER.C1)')
    ap.add_argument('--moveset', action='append', metavar='DONNEUR',
                    help='personnage a moveset tire au hasard (Tetsujin) : importer ce moveset donneur '
                         '(repetable ; all = tous les donneurs de la table)')
    ap.add_argument('--convert', action='store_true',
                    help='avec --moveset : convertir meme un donneur deja importe comme invite')
    a = ap.parse_args()
    data = json.loads(TABLE.read_text())
    table, key = data['characters'], a.character.lower()
    if key in data.get('natives', {}):                 # natif sans donneur d'Unknown (Kuma, Ogre...)
        sources(a)
        native(key, data['natives'][key])
        return
    if key not in table: raise SystemExit(f'{key} inconnu ; au choix : {", ".join(table)}')
    entry = table[key]
    if ('path' not in entry and 'force_index' not in entry) or 'asset' not in entry:
        raise SystemExit(f'{key} : trajet ou cles non verifies ({entry.get("unverified", "")})')
    name = key.capitalize()
    sources(a)
    work = WORK / key; out = work / 'guest'
    out.mkdir(parents=True, exist_ok=True)
    if a.moveset:
        donors = entry.get('donors')
        if not donors: raise SystemExit(f'{key} a un moveset fixe : --moveset ne s applique pas')
        wanted = donors if 'all' in a.moveset else a.moveset
        unknown = [d for d in wanted if d not in donors]
        if unknown: raise SystemExit(f'{", ".join(unknown)} : pas donneur de {key} ; au choix : {", ".join(donors)}')
        if not (work / 'ttt1.3dm').is_file(): raise SystemExit(f'importer d abord {key} lui-meme')
        witness = capture_select('xiaoyu', dict(path=''))
        # The witness is Xiaoyu: her own moveset as a donor (Unknown) would
        # leave nothing apart from it. Take the guest's own capture instead.
        own = capture_select(key, entry)
        for d in wanted:
            same = donor_moveset(entry, table, d) == struct.unpack_from('<H', witness.read_bytes(), KEYS + 0x10)[0]
            donor(key, entry, table, d, own if same else witness, own, a.convert)
        # Liste lue par le runtime : les donneurs dont le combat est importe.
        ready = [d for d in donors if (out / f'{name}@{d.capitalize()}-TTT1-combat.jmv').is_file()]
        # "switch button" : bascule sur L1 en combat (Unknown), sinon tirage a chaque round (Tetsujin).
        mode = 'switch button\n' if entry.get('donor_switch') == 'button' else ''
        (out / f'{name}-TTT1-donors.txt').write_text(mode + ''.join(f'{d.capitalize()} {donor_moveset(entry, table, d)}\n' for d in ready))
        print(f'\ndonneurs prets : {", ".join(wanted)} ; catalogue du jeu : python3 tools/ttt1_stage_roster.py')
        return

    ram = capture_select(key, entry)
    witness = capture_select('xiaoyu', dict(path=''))
    keys = check_keys(ram, key, entry)
    print(f'{entry["label"]} : {keys}')

    import ttt1_import_version as V
    report = dict(character=key, label=entry['label'], keys=keys, import_version=V.TTT1_IMPORT_VERSION)
    report['model'] = model(ram, keys['slot'], out, name, work)   # 0x29EF16, costume compris (Angel 67)
    report['motion'] = motion(ram, witness, out, name, work)
    records = report['motion'].pop('manifest')['records']
    report['moves'] = moves(ram, keys, records, report['model']['limbs'], out, name)
    report['costumes'] = costumes(ram, keys, entry, records, report['model']['limbs'], out, name, work)
    report['voices'] = voices(ram, keys, out, name)
    report['sounds'] = sounds(ram, report['moves']['sound_indexes'], keys['sound'], out, name)
    report['name'] = name_bitmap(entry['label'], out, name)
    report['ui'] = ui_ttt1(key, entry, out, name, work)
    report['hit_effect'] = hit_effect(key, entry, out, name, work)
    (work / 'import-report.json').write_text(json.dumps(report, indent=2, default=str) + '\n')
    print(f'\ninvite pret : {out.relative_to(ROOT)}')
    print(f'catalogue du jeu : python3 tools/ttt1_stage_roster.py ; seul : '
          f'TEKKEN3_GUEST={key} TEKKEN3_TTT1_ASSETS={out.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
