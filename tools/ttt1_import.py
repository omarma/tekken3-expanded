#!/usr/bin/env python3
"""Importe un personnage de Tekken Tag Tournament (arcade) comme invite natif de Tekken 3.

    python3 tools/ttt1_import.py <personnage> [--ttt1 tektagt.zip] [--mame mame]

<personnage> est une cle de tools/data/ttt1_characters.json (kunimitsu, bruce...).
Enchaine, sans code propre au personnage :

1. captures MAME (ecran de selection du personnage et du temoin Xiaoyu, oracle
   des voix), mises en cache sous workspace/ttt1-import/captures/ ; les cles
   lues a 0x29EF00 doivent correspondre a la table ;
2. modele : banque TTT1 -> format PS1 (tools/ttt1/model/convert.py, placement
   deduit du modele) et textures rangees dans la bande costume (texpack.py) ;
3. animations, combat solo, voix (tools/ttt1/motion.py, moves.py, voices.py) ;
4. nom (police PS1, tools/ttt1/glyphs.py) et interface : grand portrait de
   l'ecran de chargement TTT1, releve en VRAM (tools/ttt1_ui_capture.lua), et
   les cases recadrees dessus (tools/ttt1/ui_art.py, ui.py) ;
5. effet de coup fort : la planche du personnage, relevee dans la VRAM d'un
   combat TTT1 en mode versus (tools/ttt1_hit_effect_capture.lua), convertie en
   paquet d'effet Tekken 3 (tools/ttt1/hit_effect.py).

Tout vient des fichiers de l'utilisateur : son tektagt.zip non fusionne (World TEG2/VER.C1, chaque puce verifiee par SHA-1 par
arcade_model_probe.reconstruct) et son disque Tekken 3 USA (disc/, pour
l'executable et la police des noms). Le depot ne contient aucune donnee du jeu :
ni modele, ni texture, ni portrait, ni son.

Sortie : workspace/ttt1-import/<personnage>/guest/, que
tools/ttt1_stage_roster.py range dans le catalogue du jeu ; seul, lancer avec
TEKKEN3_GUEST=<personnage> TEKKEN3_TTT1_ASSETS=<dossier>.
Donnees du jeu : tout reste sous workspace/ (ignore par git).
"""
import argparse, csv, json, os, shutil, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt1'), str(ROOT / 'tools/ttt1/model')]
TABLE = ROOT / 'tools/data/ttt1_characters.json'
WORK = ROOT / 'workspace/ttt1-import'
CAPTURES = WORK / 'captures'
TTT1 = WORK / 'ttt1'                                 # regions ROM reconstruites et verifiees
SOURCE = WORK / 'source.json'                        # chemins choisis par l'utilisateur
ROMS = WORK / 'roms'                                 # copie privee pour MAME (tektagt.zip)
# MAME passe par SDL : sans ceci, chaque lancement prend le focus sur macOS.
# Sous SDL3 (MAME 0.289 de Homebrew), -video none ouvre quand meme une fenetre
# noire plein ecran qui prend le focus : le pilote video factice n'en cree aucune.
BACKGROUND = {'SDL_MAC_BACKGROUND_APP': '1'}
if sys.platform == 'darwin':
    BACKGROUND['SDL_VIDEO_DRIVER'] = 'dummy'
MAME = None
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
    """ROM TTT1 de l'utilisateur (verifiee puce par puce) et MAME ; memorises."""
    global MAME
    if not (ROOT / 'disc/SLUS_004.02').is_file():
        raise SystemExit('Il faut d abord generer le jeu depuis ton disque Tekken 3 USA (disc/SLUS_004.02).')
    known = json.loads(SOURCE.read_text()) if SOURCE.exists() else {}
    zip_path = args.ttt1 or (Path(known['ttt1']) if known.get('ttt1') and Path(known['ttt1']).is_file() else None)
    zip_path = (zip_path or choose('Ton tektagt.zip (TTT1 arcade, non fusionne)', '*.zip')).resolve()
    mame = args.mame or (Path(known['mame']) if known.get('mame') else None) or shutil.which('mame')
    if not mame: mame = choose('Executable MAME 0.289', '*')
    MAME = str(Path(mame).resolve())
    WORK.mkdir(parents=True, exist_ok=True)
    # Lu et ecrit par les imports paralleles : n'ecrire que s'il change, et
    # d'un bloc (sinon un autre import peut lire un fichier vide).
    text = json.dumps(dict(ttt1=str(zip_path), mame=MAME), indent=2) + '\n'
    if not SOURCE.is_file() or SOURCE.read_text() != text:
        tmp = SOURCE.with_name(f'.source-{os.getpid()}.json'); tmp.write_text(text); os.replace(tmp, SOURCE)
    ROMS.mkdir(exist_ok=True)
    link = ROMS / 'tektagt.zip'
    # Plusieurs imports en parallele : ne jamais laisser le lien absent, un
    # MAME d'un autre import pourrait l'ouvrir a cet instant.
    # Windows refuse les liens symboliques sans admin ni mode developpeur :
    # lien physique (meme disque), sinon copie (copy2 garde la date).
    same = link.resolve() == zip_path if link.is_symlink() else link.is_file() and (
        os.path.samefile(link, zip_path) or (link.stat().st_size, link.stat().st_mtime_ns)
        == (zip_path.stat().st_size, zip_path.stat().st_mtime_ns))
    if not same:
        tmp = ROMS / f'.tektagt-{os.getpid()}.zip'
        tmp.unlink(missing_ok=True)
        try: tmp.symlink_to(zip_path)
        except OSError:
            try: os.link(zip_path, tmp)
            except OSError: shutil.copy2(zip_path, tmp)
        os.replace(tmp, link)
    names = ('bankedroms.bin', 'c352.bin', 'sub.bin', 'maincpu_rom.bin')
    if not all((TTT1 / n).is_file() for n in names):
        import arcade_model_probe as probe
        print('Verification des puces de tektagt.zip...', flush=True)
        definition = json.loads(probe.MANIFEST.read_text())['sets']['tektagt']
        regions, _ = probe.reconstruct(zip_path, definition)
        TTT1.mkdir(exist_ok=True)
        for k, data in regions.items(): (TTT1 / (k.replace(':', '_') + '.bin')).write_bytes(data)


def mame(lua, env, cwd, debug=False, seconds=120):
    for d in ('nvram', 'cfg', 'snap'): (cwd / d).mkdir(exist_ok=True)
    subprocess.run([MAME, 'tektagt', *(('-debug', '-debugger', 'none') if debug else ()),
                    '-rompath', str(ROMS), '-video', 'none', '-sound', 'none',
                    '-nothrottle', '-skip_gameinfo', '-autoboot_script', str(lua), '-autoboot_delay', '0',
                    '-nvram_directory', 'nvram', '-cfg_directory', 'cfg', '-snapshot_directory', 'snap',
                    '-seconds_to_run', str(seconds)],
                   cwd=cwd, env={**os.environ, **env, **BACKGROUND}, check=True, timeout=600,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def forced_index(entry):
    """Personnage sans case au selecteur (Unknown) : index impose (8 x code +
    variante, table 0x801958C4) par un point d'arret des scripts Lua."""
    return {} if entry.get('force_index') is None else dict(TTT1_INDEX=str(entry['force_index']))


def capture_select(key, entry):
    """RAM de l'ecran de selection, curseur sur le personnage (NVRAM neuf)."""
    ram, shot = CAPTURES / f'{key}-select-ram.bin', CAPTURES / f'{key}-select.png'
    if ram.exists() and shot.exists(): return ram
    CAPTURES.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=WORK) as tmp:
        tmp = Path(tmp)
        env = dict(TTT1_PATH=entry.get('path', ''), TTT1_OUT='probe')
        if entry.get('confirm'): env['TTT1_CONFIRM'] = entry['confirm']
        forced = entry.get('force_moveset')
        if forced is not None: env['TTT1_MOVESET'] = str(forced)
        env.update(forced_index(entry))
        mame(ROOT / 'tools/ttt1_select_probe.lua', env, tmp, debug=forced is not None or 'TTT1_INDEX' in env)
        tag = 'confirm' if entry.get('confirm') else 'hover'
        shutil.copyfile(tmp / f'probe-{tag}-ram.bin', ram)
        shots = sorted((tmp / 'snap/tektagt').glob('*.png'))
        shutil.copyfile(shots[-1], shot)
    print(f'capture de selection -> {ram.name}')
    return ram


def check_keys(ram, key, entry):
    moveset, body, sound, asset2 = struct.unpack_from('<4H', ram.read_bytes(), KEYS + 0x10)
    got = dict(asset=asset2 // 2, moveset=moveset, body=body, sound=sound)
    want = {k: entry[k] for k in got if k in entry}
    if any(got[k] != v for k, v in want.items()):
        raise SystemExit(f'{key} : cles lues {got}, attendues {want} -- le curseur est ailleurs')
    return dict(got, slot=asset2)                        # emplacement du modele, costume compris


def capture_oracle(key, ram, profile):
    csv = CAPTURES / f'{key}-voice-oracle.csv'
    if csv.exists(): return csv
    import voices
    ids = list(voices.sound_table(ram.read_bytes(), profile)[1])
    if not ids: return csv                             # pas de voix : pas d'oracle
    with tempfile.TemporaryDirectory(dir=WORK) as tmp:
        mame(ROOT / 'tools/ttt1_voice_oracle.lua',
             dict(TTT1_VOICE_IDS=','.join(map(str, sorted(set(ids)))), TTT1_OUT=str(csv)), Path(tmp))
    print(f'oracle des voix -> {csv.name} ({len(set(ids))} identifiants)')
    return csv


def capture_sfx_oracle(ram):
    """Sons hors voix TTT1, enregistres une fois pour tous les personnages
    (tools/ttt1_sfx_oracle.lua, tools/ttt1/sfx.py). Chaque son dans un MAME
    neuf : en serie, le pilote garde un etat d'un son a l'autre et en coupe
    ou en allonge certains (le fouet de Lee, 0x7072 : 0,12 s au lieu de
    0,82 s). Cache captures/sfx-oracle/<index>.wav|csv."""
    import sfx
    from concurrent.futures import ThreadPoolExecutor
    folder = CAPTURES / 'sfx-oracle'; folder.mkdir(parents=True, exist_ok=True)
    jobs = [(f'{i}', dict(TTT1_SFX=f'{i}:{d}:{p}')) for i, (d, p) in enumerate(sfx.table(ram.read_bytes())) if i and d]
    jobs += [(f'{i}', dict(TTT1_RAW=f'{i}:{slot}:{word}')) for i, (slot, word) in sfx.RAW.items()]
    def one(job):
        stem, env = job
        wav, csv = folder / f'{stem}.wav', folder / f'{stem}.csv'
        if wav.exists() and csv.exists(): return wav, csv
        with tempfile.TemporaryDirectory(dir=WORK) as tmp:
            tmp = Path(tmp)
            for d in ('nvram', 'cfg'): (tmp / d).mkdir()
            subprocess.run([MAME, 'tektagt', '-rompath', str(ROMS), '-video', 'none', '-sound', 'none',
                            '-nothrottle', '-skip_gameinfo', '-autoboot_script', str(ROOT / 'tools/ttt1_sfx_oracle.lua'),
                            '-autoboot_delay', '0', '-nvram_directory', 'nvram', '-cfg_directory', 'cfg',
                            '-samplerate', '44100', '-wavwrite', 'sfx.wav', '-seconds_to_run', '40'],
                           cwd=tmp, env={**os.environ, **env, **BACKGROUND, 'TTT1_OUT': 'sfx.csv', 'TTT1_STEP': '360'},
                           check=True, timeout=600, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            shutil.move(tmp / 'sfx.csv', csv); shutil.move(tmp / 'sfx.wav', wav)
        return wav, csv
    missing = sum(1 for stem, _ in jobs if not (folder / f'{stem}.wav').exists())
    if missing: print(f'oracle des sons : {missing} sons a enregistrer, chacun seul...')
    with ThreadPoolExecutor(4) as pool:
        return list(pool.map(one, jobs))


# Costumes supplementaires (emplacements 109..) : (texture, modele) releves en
# combat TTT1, 2026-09-24 -- modele retrouve dans la RAM du combat, compare au
# meme invite au Poing ; texture retrouvee dans la VRAM (images et palettes).
# Textures 223.., modeles 246.., sans lien avec l'ordre des emplacements : la
# regle 246 + (emplacement - 109) donnait des costumes d'Anna. Devil au Pied
# garde le modele de son costume 1 (175) avec une autre texture (230).
EXTRA = {109: (227, 250), 110: (230, 175), 115: (236, 259), 116: (237, 260),
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
    report = texpack.plan(tex, src)
    ps1, relocs = convert.convert(src)
    base = out / f'{name}-TTT1-arcade-P{costume}'
    base.with_suffix('.3dm').write_bytes(ps1)
    base.with_suffix('.relocs').write_bytes(struct.pack(f'<{len(relocs)}I', *relocs))
    base.with_suffix('.tim').write_bytes(texpack.repack(tex))
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


def moves(ram, keys, records, limb_map, out, name, suffix=''):
    import moves as C
    combat, tables, report = C.convert(ram.read_bytes(), (TTT1 / 'bankedroms.bin').read_bytes(),
                                       records, keys['moveset'], keys['body'], limb_map)
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
    return {k: report[k] for k in ('records', 'clips', 'cancel_entries', 'omitted_rules',
                                   'omitted_conditions', 'truncated_event_scripts', 'sound_indexes')}


def costumes(ram, keys, entry, records, limbs, out, name, work):
    """Costumes 2 et 3 (Pied, Start au selecteur TTT1), emplacements releves
    par tools/ttt1_select_probe.lua : <Name>-TTT1-arcade-P2 / -P3. Un fichier
    de coups -P<n> seulement si le squelette du costume change les coups. Un
    costume qui ne se convertit pas est signale et ecarte, sans bloquer."""
    slots = entry.get('costumes', [keys['slot']])
    for c in (2, 3):
        for e in ('3dm', 'relocs', 'tim'): (out / f'{name}-TTT1-arcade-P{c}.{e}').unlink(missing_ok=True)
        for f in (f'{name}-TTT1-combat-P{c}.jmv', f'{name}-TTT1-tables-P{c}.jst'): (out / f).unlink(missing_ok=True)
    report = {'1': dict(slot=slots[0])}
    for c, slot in enumerate(slots[1:], 2):
        print(f'costume {c} (emplacement {slot}) :')
        try:
            m = model(ram, slot, out, name, work / f'costume{c}', c)
        except ValueError as e:
            print(f'ATTENTION : costume {c} non converti, ecarte : {str(e).splitlines()[-1]}')
            for e in ('3dm', 'relocs', 'tim'): (out / f'{name}-TTT1-arcade-P{c}.{e}').unlink(missing_ok=True)
            report[str(c)] = dict(slot=slot, error=str(e))
            continue
        mv = moves(ram, keys, records, m['limbs'], out, name, f'-P{c}') if m['limbs'] != limbs else dict(shared=True)
        report[str(c)] = dict(slot=slot, model=m, moves=mv)
    return report


def voices(ram, keys, oracle, out, name):
    import voices as V
    data = ram.read_bytes()
    if not V.sound_table(data, keys['sound'])[1]:
        print('ATTENTION : aucun echantillon de voix dans son profil son (Tetsujin) : pas de pack de voix')
        return dict(samples=0)
    r = V.build(data, keys['sound'], oracle, (TTT1 / 'sub.bin').read_bytes(),
                (TTT1 / 'c352.bin').read_bytes(), out, name)
    print(f'voix : {len(r["samples"])} echantillons, groupes {r["group_counts"]}')
    return dict(samples=len(r['samples']), groups=r['group_counts'])


def sounds(ram, indexes, profile, out, name):
    import sfx
    recorded = sfx.cut_all(capture_sfx_oracle(ram))
    announced = sfx.name_index(ram.read_bytes(), profile)
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


def capture_ui(key, entry):
    """Images d'interface envoyees en VRAM par TTT1 (grille, ecran de chargement)."""
    folder = CAPTURES / f'{key}-ui'
    if (folder / 'ui-uploads.csv').exists(): return folder
    folder.mkdir(parents=True, exist_ok=True)
    env = dict(TTT1_PATH=entry.get('path', ''), **forced_index(entry))
    if entry.get('confirm'): env['TTT1_CONFIRM'] = entry['confirm']
    mame(ROOT / 'tools/ttt1_ui_capture.lua', env, folder, debug='TTT1_INDEX' in env)
    print(f'images d interface TTT1 -> {folder.name}')
    return folder


def capture_final_portrait(key):
    """Grand portrait d'un boss sans case (Unknown) : TTT1 l'envoie au chargement
    du stage final de l'Arcade (tools/ttt1_final_stage_capture.lua), le premier
    envoye a ce niveau apres celui du joueur 1."""
    import ui_art
    folder = CAPTURES / f'{key}-final'
    if not (folder / 'ui-uploads.csv').exists():
        folder.mkdir(parents=True, exist_ok=True)
        # Huit stages gagnes au premier coup : environ 8 000 images.
        mame(ROOT / 'tools/ttt1_final_stage_capture.lua', {}, folder, seconds=600)
        print(f'chargement du stage final TTT1 -> {folder.name}')
    rows = list(csv.DictReader(open(folder / 'ui-uploads.csv')))
    final = [i for i, r in enumerate(rows) if r['w'] == '76' and r['level'] == '7' and rows[i - 1]['w'] == '256']
    if len(final) < 2: raise SystemExit('stage final TTT1 non atteint : pas de portrait du boss')
    i = final[1]
    pal = struct.unpack('<256H', (folder / rows[i - 1]['file']).read_bytes()[:512])
    return ui_art.rgba((folder / rows[i]['file']).read_bytes(), 76, 256, pal)


def hit_effect(key, entry, out, name, work):
    """Effet de coup fort du personnage, releve dans la VRAM de TTT1 une fois le
    combat charge (mode versus), converti en paquet d'effet Tekken 3."""
    import hit_effect as H
    vram = CAPTURES / f'{key}-hit-vram.bin'
    if not vram.exists():
        with tempfile.TemporaryDirectory(dir=WORK) as tmp:
            tmp = Path(tmp)
            env = dict(TTT1_PATH=entry.get('path', ''), **forced_index(entry))
            if entry.get('confirm'): env['TTT1_CONFIRM'] = entry['confirm']
            mame(ROOT / 'tools/ttt1_hit_effect_capture.lua', env, tmp, debug='TTT1_INDEX' in env)
            shutil.copyfile(tmp / 'hit-vram.bin', vram)
            shots = sorted((tmp / 'snap/tektagt').glob('*.png'))
            if shots: shutil.copyfile(shots[-1], CAPTURES / f'{key}-hit.png')
        print(f'VRAM de combat TTT1 -> {vram.name}')
    pack = H.t3_pack(vram.read_bytes())
    (out / f'{name}-TTT1-hiteffect.tim').write_bytes(pack)
    H.preview(pack).save(work / 'coup-fort.png')
    print(f'effet de coup fort : {len(pack) // 576} images 32 x 32 (apercu {(work / "coup-fort.png").relative_to(ROOT)})')
    return dict(frames=len(pack) // 576, bytes=len(pack))


def ui_ttt1(key, entry, out, name, work):
    """Interface reprise de TTT1 : grand portrait de chargement ; cases de grille
    et icones de chargement recadrees dans ce portrait a l'endroit que montre la
    vignette de grille TTT1 (vignette agrandie si le portrait est un autre rendu).
    Sans vignette a lui (case partagee avec un autre : Angel, Alex ; case
    cachee : Tetsujin), cadrage tile_box de la table, sinon tete recadree."""
    import ui_art, ui as U
    thumbs, portrait = ui_art.uploads(capture_ui(key, entry))
    if portrait is None: raise SystemExit('grand portrait TTT1 non releve')
    portrait.save(work / 'ttt1-portrait.png')
    thumb, err = None, -1
    if entry.get('thumbnail_at'):                      # pas de case : la vignette reperee par sa place en VRAM
        thumb, err = ui_art.thumbnail_at(capture_ui(key, entry), *entry['thumbnail_at']), 0
        thumb.save(work / 'ttt1-vignette-grille.png')
    elif entry.get('confirm'):                         # case partagee : la vignette est celle de l'autre
        (work / 'ttt1-vignette-grille.png').unlink(missing_ok=True)
    else:
        try:                                           # vignette de la grille TTT1 -> cases T3
            thumb, err = ui_art.find_thumbnail(thumbs, CAPTURES / 'xiaoyu-select.png', CAPTURES / f'{key}-select.png')
            thumb.save(work / 'ttt1-vignette-grille.png')
        except ValueError:                             # case cachee (Tetsujin) : pas de vignette
            pass
    if entry.get('portrait') == 'final_stage':
        # Au selecteur TTT1 envoie le portrait de la case du curseur (Xiaoyu) :
        # celui du boss vient du chargement du stage final.
        portrait = capture_final_portrait(key)
        portrait.save(work / 'ttt1-portrait.png')
    images, how = ui_art.t3_images(portrait, thumb, entry.get('tile_box'))
    print(f'cases de grille : {how}')
    pack, tims = U.pack(images)
    for (iname, *_), tim in zip(U.SPECS, tims):
        images[iname].save(out / f'{name}-T3-{iname}-source.png')
        (out / f'{name}-T3-{iname}.tim').write_bytes(tim)
    (out / f'{name}-T3-ui.jui').write_bytes(pack)
    print(f'interface : {len(pack)} o, portrait et cases depuis TTT1 (vignette de grille : ecart {err:.0f})')
    return dict(source='ttt1', bytes=len(pack), thumbnail_error=round(err))


def donor_moveset(entry, table, donor_key):
    """Moveset TTT1 d'un donneur : celui d'un invite de la table, ou d'un natif
    de Tekken 3 que TTT1 a aussi (donor_movesets, Unknown)."""
    if donor_key in table and 'moveset' in table[donor_key]: return table[donor_key]['moveset']
    return entry['donor_movesets'][donor_key]


def donor(key, entry, table, donor_key, witness):
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('character')
    ap.add_argument('--ttt1', type=Path, help='ton tektagt.zip non fusionne (World TEG2/VER.C1)')
    ap.add_argument('--mame', type=Path, help='executable MAME 0.289')
    ap.add_argument('--moveset', action='append', metavar='DONNEUR',
                    help='personnage a moveset tire au hasard (Tetsujin) : importer ce moveset donneur '
                         '(repetable ; all = tous les donneurs de la table)')
    a = ap.parse_args()
    table = json.loads(TABLE.read_text())['characters']
    key = a.character.lower()
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
            donor(key, entry, table, d, own if same else witness)
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
    oracle = capture_oracle(key, ram, keys['sound'])

    report = dict(character=key, label=entry['label'], keys=keys)
    report['model'] = model(ram, keys['slot'], out, name, work)   # 0x29EF16, costume compris (Angel 67)
    report['motion'] = motion(ram, witness, out, name, work)
    records = report['motion'].pop('manifest')['records']
    report['moves'] = moves(ram, keys, records, report['model']['limbs'], out, name)
    report['costumes'] = costumes(ram, keys, entry, records, report['model']['limbs'], out, name, work)
    report['voices'] = voices(ram, keys, oracle, out, name)
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
