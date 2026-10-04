#!/usr/bin/env python3
"""Arcade CPU difficulty levels for the Tekken 3 PS1 build.

The PS1 game picks its CPU's behaviour from a table in SLUS_004.02 at
0x800231AC: 3 difficulties x 10 stages of 110-byte blocks (reaction delays,
action probabilities out of 4096...), read by 0x80061488. The arcade boards
keep the same blocks in RAM, from the user's own ROMs:

  Tekken 3 (tekken3, TET2/VER.E1)  0x801FFE04: 2 modes x 5 levels x 10 stages x 120 bytes
  Tekken Tag (tektagt, TEG2/VER.C1) 0x8019602C: 2 modes x 9 levels x 8 stages x 128 bytes

Their first 57 halfwords are the PS1 block with its first four fields widened
to halfwords (the rest is a pointer and, for TTT1, fields of its own). Both
tables are static in the game programs, which the boards unpack from their
program ROM at boot (Tekken 3: LZ entry at ROM+0x20238, the TTT LZ of
tools/ttt1/extract.py; TTT: extract.unpack_game). This tool reads them there,
without MAME, checks them against
the PS1 table (PS1 MEDIUM must equal arcade MEDIUM and PS1 HARD arcade ULTRA
HARD, block for block) and writes workspace/difficulty/levels.bin, which the
runtime plugin src/tekken3_difficulty_mod.c copies over the PS1 table.

  python3 tools/difficulty/import.py [--tekken3 tekken3.zip] [--tektagt tektagt.zip]

Nothing from either game is written outside workspace/.
"""
import argparse, hashlib, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'workspace/difficulty'
SOURCE = WORK / 'source.json'
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt1')]
import arcade_model_probe as probe, extract as E  # noqa: E402
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


def program(game, zip_path):
    """The game program as the board unpacks it to 80010000 at boot."""
    regions = [r for r in json.loads(probe.MANIFEST.read_text())['sets'][game]['regions']
               if r['name'] == 'maincpu:rom']
    try: main = probe.reconstruct(zip_path, dict(regions=regions))[0]['maincpu:rom']
    except probe.ProbeError as e: raise SystemExit(f'{zip_path.name} : {e}')
    if game == 'tektagt': return E.unpack_game(main)
    # Boot stub at ROM+0x20270: zero fills at 0x20210, copies at 0x20220,
    # then LZ unpacks at 0x20238 (source, destination), one entry.
    src, dst = struct.unpack_from('<2I', main, 0x20238)
    if dst != 0x80010000: raise SystemExit(f'{zip_path.name} : chargeur inattendu')
    return E.lz(main, src - 0x1FC00000)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--tekken3', type=Path, help='tekken3.zip (Tekken 3 arcade, non fusionne)')
    ap.add_argument('--tektagt', type=Path, help='tektagt.zip (Tekken Tag Tournament arcade)')
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
    SOURCE.write_text(json.dumps(dict(tekken3=str(zips['tekken3']), tektagt=str(zips['tektagt'])), indent=2) + '\n')

    ps1 = {(d, s): exe[0x800 + PS1_TABLE - 0x80010000 + d * STAGES * PS1_BLOCK + s * PS1_BLOCK:][:PS1_BLOCK]
           for d in range(3) for s in range(STAGES)}
    arcade = {}
    for game, t in ARCADE.items():
        size = t['modes'] * t['levels'] * t['stages'] * t['block']
        print(f'{game} : table IA lue dans la ROM...', flush=True)
        raw = program(game, zips[game])[t['addr'] - 0x80010000:][:size]
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
