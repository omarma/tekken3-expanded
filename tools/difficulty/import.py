#!/usr/bin/env python3
"""Arcade CPU difficulty levels for the Tekken 3 PS1 build.

The PS1 game picks its CPU's behaviour from a table in SLUS_004.02 at
0x800231AC: 3 difficulties x 10 stages of 110-byte blocks (reaction delays,
action probabilities out of 4096...), read by 0x80061488. The arcade boards
keep the same blocks in RAM, from the user's own ROMs:

  Tekken 3 (tekken3, TET2/VER.E1)  0x801FFE04: 2 modes x 5 levels x 10 stages x 120 bytes
  Tekken Tag (tektagt, TEG2/VER.C1) 0x8019602C: 2 modes x 9 levels x 8 stages x 128 bytes

Their first 57 halfwords are the PS1 block with its first four fields widened
to halfwords (the rest is a pointer and, for TTT1, fields of its own). This
tool reads both tables under MAME during the attract mode, checks them against
the PS1 table (PS1 MEDIUM must equal arcade MEDIUM and PS1 HARD arcade ULTRA
HARD, block for block) and writes workspace/difficulty/levels.bin, which the
runtime plugin src/tekken3_difficulty_mod.c copies over the PS1 table.

  python3 tools/difficulty/import.py [--tekken3 tekken3.zip] [--tektagt tektagt.zip] [--mame mame]

Nothing from either game is written outside workspace/.
"""
import argparse, hashlib, json, os, shutil, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'workspace/difficulty'
SOURCE = WORK / 'source.json'
NATIVE_EXE_SHA = 'fbda8b68e5799dbef4af39a161783bc670c15b0aa0e87dce65e210717da19b8c'

PS1_TABLE, PS1_BLOCK, STAGES = 0x800231AC, 110, 10
ARCADE = {
    'tekken3': dict(addr=0x801FFE04, block=120, levels=5, stages=10, modes=2),
    'tektagt': dict(addr=0x8019602C, block=128, levels=9, stages=8, modes=2),
}
# (key, menu label, source, level, mode). The ps1-* rows are the game's own
# table, kept only so the plugin can check the table in RAM before writing it.
# The others are the levels beyond the PS1 HARD, in the Options menu order,
# easiest first. Over the ten stages, each one reacts faster (sum of the
# reaction delays, fields 5 to 8: PS1 HARD 510, then 488, 401, 212) and acts
# more (sum of the action probabilities, fields 10 to 55: 335 136, then
# 342 101, 362 466, 385 624) than the one before; the TTT1 SUPER HARD reacts
# a little slower than the T3 ULTRA HARD in the last three stages only. EX
# SUPER HARD is the most aggressive (445 385) but reacts slowest (645); it is
# the board's top level and played hardest, so it comes last. The labels keep the
# boards' names, with the board they come from; they fit the menu's value
# column when the row is named LEVEL. The boards' levels the PS1 menu already
# has (MEDIUM, and ULTRA HARD as its HARD) or that sit below the PS1 HARD
# (Tekken 3's HARD and VERY HARD) are left out.
LEVELS = [
    ('ps1-easy',      'EASY',                        'ps1',     0, 0),
    ('ps1-medium',    'MEDIUM',                      'ps1',     1, 0),
    ('ps1-hard',      'HARD',                        'ps1',     2, 0),
    ('hard-plus',     'ULTRA HARD (T3 ARCADE)',      'tekken3', 4, 1),
    ('super-hard',    'SUPER HARD (TTT1 ARCADE)',    'tektagt', 7, 0),
    ('ultra-hard-1',  'ULTRA HARD1 (TTT1 ARCADE)',   'tektagt', 5, 0),
    ('ex-super-hard', 'EX SUPER HARD (TTT1 ARCADE)', 'tektagt', 8, 0),
]


def to_ps1(block):
    """Arcade block -> PS1 layout: four byte fields, then 53 halfwords."""
    h = struct.unpack_from('<57H', block)
    if any(x > 255 for x in h[:4]):
        raise ValueError(f'first fields do not fit a byte: {h[:4]}')
    return bytes(h[:4]) + struct.pack('<53H', *h[4:])


def choose(prompt, pattern):
    try:
        import tkinter, tkinter.filedialog
        tkinter.Tk().withdraw()
        p = tkinter.filedialog.askopenfilename(title=prompt, filetypes=[(pattern, pattern)])
    except Exception:
        p = input(f'{prompt} : ').strip()
    if not p: raise SystemExit('annule')
    return Path(p)


def mame_dump(mame, game, roms, addr, length):
    with tempfile.TemporaryDirectory(dir=WORK) as tmp:
        tmp = Path(tmp)
        for d in ('nvram', 'cfg', 'snap'): (tmp / d).mkdir()
        env = dict(os.environ, DUMP_ADDR=f'{addr:x}', DUMP_LEN=str(length), DUMP_OUT='dump.bin')
        if sys.platform == 'darwin':
            # Sans fenetre ni vol du focus (MAME sous SDL3 en ouvre une malgre -video none).
            env.update(SDL_MAC_BACKGROUND_APP='1', SDL_VIDEO_DRIVER='dummy')
        subprocess.run([str(mame), game, '-rompath', str(roms), '-video', 'none', '-sound', 'none',
                        '-nothrottle', '-skip_gameinfo', '-autoboot_script', str(ROOT / 'tools/difficulty/dump_ram.lua'),
                        '-autoboot_delay', '0', '-nvram_directory', 'nvram', '-cfg_directory', 'cfg',
                        '-snapshot_directory', 'snap', '-seconds_to_run', '120'],
                       cwd=tmp, env=env, check=True, timeout=600,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        data = (tmp / 'dump.bin').read_bytes()
    if len(data) != length: raise SystemExit(f'{game} : releve incomplet ({len(data)} octets)')
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--tekken3', type=Path, help='tekken3.zip (Tekken 3 arcade, non fusionne)')
    ap.add_argument('--tektagt', type=Path, help='tektagt.zip (Tekken Tag Tournament arcade)')
    ap.add_argument('--mame', type=Path, help='executable MAME 0.289')
    args = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    exe = (ROOT / 'disc/SLUS_004.02').read_bytes()
    if hashlib.sha256(exe).hexdigest() != NATIVE_EXE_SHA:
        raise SystemExit('disc/SLUS_004.02 n est pas l executable Tekken 3 USA attendu')
    known = json.loads(SOURCE.read_text()) if SOURCE.exists() else {}
    ttt1 = ROOT / 'workspace/ttt1-import/source.json'
    ttt1 = json.loads(ttt1.read_text()) if ttt1.exists() else {}
    zips = {}
    for game, arg, label in (('tekken3', args.tekken3, 'Ton tekken3.zip (Tekken 3 arcade)'),
                             ('tektagt', args.tektagt, 'Ton tektagt.zip (Tekken Tag arcade)')):
        z = arg or (Path(known[game]) if known.get(game) else None)
        if game == 'tektagt' and not z and ttt1.get('ttt1'): z = Path(ttt1['ttt1'])
        if not z or not z.is_file(): z = choose(label, '*.zip')
        zips[game] = z.resolve()
    mame = args.mame or (Path(known['mame']) if known.get('mame') else None) or \
        (Path(ttt1['mame']) if ttt1.get('mame') else None) or shutil.which('mame')
    if not mame: mame = choose('Executable MAME 0.289', '*')
    SOURCE.write_text(json.dumps(dict(tekken3=str(zips['tekken3']), tektagt=str(zips['tektagt']), mame=str(mame)), indent=2) + '\n')
    roms = WORK / 'roms'; roms.mkdir(exist_ok=True)
    for game, z in zips.items():
        link = roms / f'{game}.zip'
        if link.is_symlink() or link.exists(): link.unlink()
        # Windows refuse les liens symboliques sans admin ni mode developpeur.
        try: link.symlink_to(z)
        except OSError:
            try: os.link(z, link)
            except OSError: shutil.copy2(z, link)

    ps1 = {(d, s): exe[0x800 + PS1_TABLE - 0x80010000 + d * STAGES * PS1_BLOCK + s * PS1_BLOCK:][:PS1_BLOCK]
           for d in range(3) for s in range(STAGES)}
    arcade = {}
    for game, t in ARCADE.items():
        size = t['modes'] * t['levels'] * t['stages'] * t['block']
        print(f'{game} : releve de la table IA sous MAME...', flush=True)
        raw = mame_dump(mame, game, roms, t['addr'], size)
        for m in range(t['modes']):
            for d in range(t['levels']):
                for s in range(t['stages']):
                    o = ((m * t['levels'] + d) * t['stages'] + s) * t['block']
                    arcade[game, m, d, s] = to_ps1(raw[o:o + t['block']])
    # The addresses are right only if the arcade T3 table reproduces the PS1
    # one where the two are known to agree.
    for s in range(STAGES):
        if arcade['tekken3', 0, 1, s] != ps1[1, s] or arcade['tekken3', 0, 4, s] != ps1[2, s]:
            raise SystemExit(f'table arcade T3 inattendue au stage {s + 1} : ROM ou version differente')
    for key, (m, d, s) in {'tektagt': (0, 0, 0)}.items():
        h = struct.unpack_from('<4B', arcade[key, m, d, s])
        if not all(1 <= x <= 10 for x in h):
            raise SystemExit('table arcade TTT inattendue : ROM ou version differente')

    out = bytearray(b'T3DF' + struct.pack('<III', 1, len(LEVELS), PS1_BLOCK))
    report = []
    for key, label, src, d, m in LEVELS:
        blocks = []
        for s in range(STAGES):
            if src == 'ps1': blocks.append(ps1[d, s])
            else:
                n = ARCADE[src]['stages']
                blocks.append(arcade[src, m, d, round(s * (n - 1) / (STAGES - 1))])
        out += key.encode().ljust(24, b'\0') + label.encode()[:63].ljust(64, b'\0') + b''.join(blocks)
        react = [sum(b[4 + 2 * k] | b[5 + 2 * k] << 8 for k in range(1, 5)) / 4 for b in blocks]
        report.append(dict(key=key, label=label, source=src, level=d, mode=m,
                           reaction_first=react[0], reaction_last=react[-1]))
    (WORK / 'levels.bin').write_bytes(bytes(out))
    (WORK / 'report.json').write_text(json.dumps(report, indent=1) + '\n')
    print(f'{len(LEVELS)} niveaux -> {(WORK / "levels.bin").relative_to(ROOT)}')
    for r in report: print(f'  {r["key"]:14} {r["label"]}')


if __name__ == '__main__':
    main()
