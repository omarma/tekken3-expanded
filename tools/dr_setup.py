#!/usr/bin/env python3
"""Dark Resurrection movesets for the natives, read from the player's own ISO.

    python tools/dr_setup.py --iso "C:\\...\\Tekken Dark Resurrection.iso" [--roster DIR] [--force]

Like the TTT1 install without MAME (TIPS sections 61-63): the player's copy of
Tekken: Dark Resurrection (PSP, ULUS10139) is read directly, no PPSSPP, no
BIOS; each file read from it is checked against the SHA-1 of
tools/psp/data/dr_iso_files.json (a different or damaged dump stops here).
Needs the TTT1 import done first: a native's DR pack starts from its TTT1
pack (PSP-DR.md "A3 : conception", decision 1). For each native of
tools/dr_import_version.py NATIVES: the animation fit on its identical moves
(tools/psp/dr_convert.py calibrate), its pack (tools/psp/dr_pack.py), DR's move
cameras on the pack's records (tools/psp/dr_camera.py pack, from
tools/psp/data/dr_camera_<key>.json when the native has one), its line
"<ID> <key> <moveset> dr" in natives.txt. Then the DR characters of
tools/dr_import_version.py CHARACTERS (their <Radical>-DR-* packs, BUILDERS),
after the screen images of all 12 (tools/psp/dr_ui.py: -ui.jui, -name.4bpp,
-label.txt, which alone list nobody),
then their catalogue dr-characters.txt (tools/dr_catalog.py: the complete packs
only, written after every other file), then the stamp dr-import-version.txt.
The catalogue and the stamp are removed first: an import cut short is redone.
Up to date (same stamp): nothing is done unless --force.

Needs numpy and PPSSPP's VFPU tables (assets/vfpu/*.dat of a PPSSPP install, or
PPSSPP_VFPU): DR's pose (tools/psp/dr_pose_a3.py, session B1's code) is computed
to the bit as the PSP does, sines included. The launcher's setup calls it after
the TTT1 import when the player gives the DR ISO (launcher/setup_backend.py).
Nothing from the game is written outside the catalogue and workspace/dr-a3.
"""
import argparse, os, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/psp'), str(ROOT / 'tools/t5'), str(ROOT / 'tools/ttt1')]
import dr_import_version as V
import dr_catalog as C

# Wiki moves the pack leaves out (PSP-DR.md A4: Jin's Lingering Soul Omen and its Soul Rage moves).
LEFT_OUT = {'jin': ('Soul',)}


def place(roster, source, name):
    """A copy of a roster file under a new name; the roster is often hard links (PORTING 22):
    the target is removed first, never written through."""
    target = roster / name
    target.unlink(missing_ok=True)
    shutil.copyfile(roster / source, target)


# Devil Jin (B3): his model v2 (tools/psp/convert_model.py model, version R chosen by the user),
# his voices, laser sound, name, strong-hit lightning and laser images (tools/psp/dr_hitspark.py)
# from the ISO; until
# sub-step 2 lands, his moves stand in from Jin's TTT1 pack.
DEVIL_JIN_STAND_IN = {'Jin-TTT1-combat.jmv': 'combat.jmv', 'Jin-TTT1-tables.jst': 'tables.jst',
                      'Jin-TTT1-idle.poses': 'idle.poses', 'Jin-TTT1-movelist.bin': 'movelist.bin',
                      'Jin-TTT1-combos.bin': 'combos.bin'}


def ttt1_roms(roster):
    """The TTT1 import's ROM folder, beside the catalogue it made (workspace/ttt1-import)."""
    import convert_model
    beside = Path(roster).parent / 'ttt1'
    return beside if (beside / 'bankedroms.bin').is_file() else convert_model.TTT1_FOLDER


def devil_jin(roster):
    import convert_model, dr_sounds, dr_hitspark
    print('deviljin: model', flush=True)
    convert_model.model(roster, perso='deviljin', ttt1=ttt1_roms(roster))
    for source, part in DEVIL_JIN_STAND_IN.items(): place(roster, source, f'DevilJin-DR-{part}')
    print('deviljin: voices, laser and name', flush=True)
    dr_sounds.build('deviljin', 'DevilJin', roster, roster / 'Jin-TTT1-sfx.jus')
    print('deviljin: strong-hit lightning and laser', flush=True)
    dr_hitspark.build('deviljin', 'DevilJin', roster)
    dr_hitspark.build_laser('deviljin', 'DevilJin', roster)


# key -> function(roster) writing that DR character's <Radical>-DR-* pack (tools/dr_catalog.py
# PACK) into the roster; one for each key of V.CHARACTERS.
BUILDERS = {'deviljin': devil_jin}


def vfpu_dir():
    """PPSSPP's assets/vfpu folder: PPSSPP_VFPU, else the usual installs (Windows, macOS, Linux),
    else beside a PPSSPP on the PATH. None when there is none."""
    found = [os.environ.get('PPSSPP_VFPU')]
    for exe in ('PPSSPPWindows64.exe', 'PPSSPPWindows.exe', 'PPSSPPSDL', 'ppsspp'):
        w = shutil.which(exe)
        if w: found.append(str(Path(w).resolve().parent / 'assets/vfpu'))
    for base in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)'),
                 os.environ.get('LOCALAPPDATA') and str(Path(os.environ['LOCALAPPDATA']) / 'Programs')):
        if base: found.append(str(Path(base) / 'PPSSPP/assets/vfpu'))
    found += ['/Applications/PPSSPPSDL.app/Contents/Resources/assets/vfpu', '/usr/share/ppsspp/assets/vfpu',
              '/usr/local/share/ppsspp/assets/vfpu', str(Path.home() / '.local/share/ppsspp/assets/vfpu')]
    return next((Path(f) for f in found if f and (Path(f) / 'vfpu_sin_lut8192.dat').is_file()), None)


def iso_problem(iso):
    """Why this ISO cannot be used for the DR movesets, or None (the launcher asks before starting)."""
    if not Path(iso).is_file(): return 'It is no longer there (moved, renamed or deleted).'
    if vfpu_dir() is None:
        return "PPSSPP was not found on this computer: its VFPU tables (assets/vfpu) are needed to read DR's animations."
    import dr_iso
    try:
        dr_iso.Disc(Path(iso)).raw(dr_iso.COMMON_ANIM)       # checked against the file table's SHA-1
    except (Exception, SystemExit):                          # dr_iso stops with SystemExit on a wrong image
        return 'It is not Tekken: Dark Resurrection USA (ULUS-10139) for PSP, or the image is incomplete or damaged.'
    return None


def natives_line(roster, key):
    path = roster / 'natives.txt'
    lines = path.read_text().splitlines() if path.is_file() else []
    ttt1 = next((l.split() for l in lines if len(l.split()) >= 3 and l.split()[1] == key
                 and (len(l.split()) == 3 or l.split()[3] == 'ttt1')), None)
    if not ttt1: raise SystemExit(f'{key}: no TTT1 moveset in {path} (run the TTT1 import first)')
    line = f'{ttt1[0]} {key} {ttt1[2]} dr'
    lines = [l for l in lines if not (len(l.split()) == 4 and l.split()[1] == key and l.split()[3] == 'dr')] + [line]
    path.write_text('\n'.join(lines) + '\n')


def moveset(roster, key):
    """A DR moveset into the roster, a native's (V.NATIVES) or a DR character's (deviljin, from its
    <Radical>-TTT1-* pack: the easter egg's DevilJin-TTT1 for Devil Jin): the animation fit on its
    identical moves (tools/psp/dr_convert.py calibrate), its pack (tools/psp/dr_pack.py: <Radical>-DR-
    combat.jmv, -tables.jst, -idle.poses, -sfx.jus as its TTT1 base's, -reach.txt, -hands.bin, -air.txt, -airpush.txt), DR's move cameras
    (-camera.txt, from tools/psp/data/dr_camera_<key>.json when there), its COMMAND LIST (-movelist.bin,
    from tools/data/wiki/dr-<key>.wiki). Returns dr_pack's report."""
    import dr_convert, dr_pack, dr_camera
    radical = dr_convert.fighter(key)[2]
    print(f'{key}: fitting the animations on the identical moves', flush=True)
    dr_convert.calibrate(key, pack_dir=roster)
    print(f'{key}: building the pack', flush=True)
    report = dr_pack.build(key, roster, pack_dir=roster)
    tracks = ROOT / f'tools/psp/data/dr_camera_{key}.json'
    if tracks.is_file():
        print(f'{key}: move cameras', flush=True)
        dr_camera.pack(roster / f'{radical}-DR-camera.txt', report, tracks, ROOT / f'fiches/dr-{key}.tsv')
    # Its COMMAND LIST: the Tekken wiki's DR page (tools/data/wiki/dr-<key>.wiki), the links of
    # its commands kept as their text (qcb is a link to the sway there).
    wiki = ROOT / f'tools/data/wiki/dr-{key}.wiki'
    if wiki.is_file():
        sys.path.insert(0, str(ROOT / 'tools/ttt1'))
        import movelist, re
        text = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]*)\]\]', r'\1', wiki.read_text(encoding='utf-8'))
        text = '\n|-'.join(row for row in text.split('\n|-')
                           if not any(re.search(rf'^!.*{w}', row, re.M) for w in LEFT_OUT.get(key, ())))
        data, total, _ = movelist.build(f'dr-{key}', text)
        (roster / f'{radical}-DR-movelist.bin').write_bytes(data)
        print(f'{key}: COMMAND LIST of {data[0]} moves', flush=True)
    # Its COMBO TRAINING (Practice): the wiki's 10 hit combos and strings, their timing measured in
    # game on this pack (tools/ttt1/combos.py probe dr-<key>, results in tools/data/combos/dr-<key>.json).
    measured = ROOT / f'tools/data/combos/dr-{key}.json'
    if measured.is_file():
        import combos
        data, count = combos.pack(f'dr-{key}')
        (roster / f'{radical}-DR-combos.bin').write_bytes(data)
        print(f'{key}: COMBO TRAINING of {count} combos', flush=True)
    return report


def natives(roster):
    """Each native of V.NATIVES: its DR moveset pack and its line in natives.txt."""
    for key in V.NATIVES:
        moveset(roster, key)
        natives_line(roster, key)


def interface(roster):
    """The screen images of every DR character (C3, tools/psp/dr_ui.py), made or not: portrait,
    tiles, name plate and label. A character still needs the rest of its pack to be listed."""
    import dr_ui
    print('Screen images of the DR characters', flush=True)
    keys = dr_ui.write(roster)
    print(f'DR screen images: {", ".join(keys) or "none"}', flush=True)
    return keys


def install(roster):
    """Everything after the ISO check: no catalogue nor stamp while the files are written,
    the natives' movesets, the DR characters' screen images and packs, then the catalogue and
    the stamp."""
    C.remove(roster)
    (roster / V.STAMP).unlink(missing_ok=True)
    natives(roster)
    # The DR characters' screen images only with DR characters to make (none in 1.5.0: Jin's
    # DR moves alone, F34; tools/psp/dr_ui.py stays on the DR line).
    if V.CHARACTERS: interface(roster)
    # One character failing leaves it out, not the others nor the natives' movesets.
    for key in V.CHARACTERS:
        print(f'{key}: building the pack', flush=True)
        try: BUILDERS[key](roster)
        except Exception as error: print(f'{key} left out: {error!r}', flush=True)
    # Last: the catalogue names only complete packs, then the stamp.
    keys = C.write(roster)
    V.write_stamp(roster)
    print(f'DR movesets {", ".join(V.NATIVES) or "none"} written to {roster} (version {V.DR_IMPORT_VERSION})')
    print(f'DR characters: {", ".join(keys) or "none"}')
    gone = C.missing(roster)
    if gone: print(f'DR import partial, missing: {", ".join(gone)}')
    return keys


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--iso', type=Path, required=True)
    ap.add_argument('--roster', type=Path, default=ROOT / 'workspace/ttt1-import/roster')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    roster = a.roster.resolve()
    if not (roster / 'natives.txt').is_file() or not C.ttt1_ready(roster):
        raise SystemExit(f'{roster}: no TTT1 catalogue (run the TTT1 import first)')
    if V.read_stamp(roster) == V.DR_IMPORT_VERSION and not a.force:
        print(f'DR movesets up to date (version {V.DR_IMPORT_VERSION})'); return
    if not a.iso.is_file(): raise SystemExit(f'{a.iso}: no such ISO')
    vfpu = vfpu_dir()
    if vfpu is None: raise SystemExit("PPSSPP's VFPU tables not found (install PPSSPP, or set PPSSPP_VFPU to its assets/vfpu)")
    os.environ['PPSSPP_VFPU'] = str(vfpu)                    # read by tools/psp/dr_pose_a3.py at import
    import dr_iso
    dr_iso.ISO = a.iso.resolve()
    dr_iso.Disc(dr_iso.ISO).raw(dr_iso.COMMON_ANIM)          # checked against the file table's SHA-1
    install(roster)


if __name__ == '__main__':
    main()
