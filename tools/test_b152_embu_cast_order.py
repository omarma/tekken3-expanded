#!/usr/bin/env python3
"""The TTT cast of Tekken 3's Embus resolves its guests (B152; TIPS § 239).

    python tools/test_b152_embu_cast_order.py OUT --mods <dir> [--build build-rel-lite] [--embus N]
    python tools/test_b152_embu_cast_order.py OUT --log <game.log>      (the boot checks alone, on a log)

Since natives are on their TTT1 models by default (F32 E6, 82a71e17), the first tick's follow_models() no
longer asked for a guest's generation, which built the guest roster: embu_parse() then resolved the casting
("TTT1 Embu: baek plays hwoarang") on an empty roster, every pair "(unknown guest, ignored)", once for the
session, and the attract's guests' turn (B104) was gone. tekken3_guest_id() now builds the roster first.

Runs tools/test_embu_rotation.py (attract alone, new card, tier 0: TTT, guests, v0) into OUT, then reads
OUT/game.log. Checks (exit 1 otherwise):
  - the guest catalogue ("TTT1 characters: N guests in ...") is read before the first casting line;
  - the casting has lines, none "(unknown guest, ignored)";
  - the rotation has the guests' turn, and a guest of the casting is grafted on its native's model during it
    ("TTT1 Embu: P1 Baek on hwoarang's model");
  - the rotation bench itself passed (its embus.txt ends with OK).
--mods: the installed mods (the TTT1 import, TTT Cinematics, TTT Stages), linked, never written. Run through
ressources/slot.py (--kind game).
"""
import argparse, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOGUE = re.compile(r'TTT1 characters: (\d+) guests in ')
CAST = re.compile(r'TTT1 Embu: (\w+) plays (\w+)( \(unknown guest, ignored\))?$')
GRAFT = re.compile(r"TTT1 Embu: P(\d) (.+) on (\w+)'s model at ")
ROTATION = re.compile(r'Cine trigger: Embu rotation, ')


def check_log(text, rotation=True):
    """Problems of the boot (catalogue before casting, casting resolved) and of the guests' Embu."""
    lines = text.splitlines()
    rows, problems = [], []
    cat = next((i for i, l in enumerate(lines) if CATALOGUE.search(l)), None)
    cast = [(i, CAST.search(l)) for i, l in enumerate(lines) if CAST.search(l)]
    rows.append(f'catalogue line {cat + 1 if cat is not None else "missing"}'
                + (f' ({CATALOGUE.search(lines[cat]).group(1)} guests)' if cat is not None else ''))
    rows.append(f'casting: {len(cast)} lines from line {cast[0][0] + 1 if cast else "-"}: '
                + ', '.join(f'{m.group(1)}={m.group(2)}{"?" if m.group(3) else ""}' for _, m in cast))
    if cat is None: problems.append('no guest catalogue read')
    if not cast: problems.append('no casting line')
    if cat is not None and cast and cast[0][0] < cat: problems.append('casting parsed before the guest catalogue')
    ignored = [m.group(1) for _, m in cast if m.group(3)]
    if ignored: problems.append(f'unknown guests ignored: {ignored}')
    # The guests' Embu: from its decision to the next one, a guest of the casting grafted.
    guests = {m.group(1) for _, m in cast if not m.group(3)}
    turns = [i for i, l in enumerate(lines) if ROTATION.search(l)]
    guest_turns = [i for i in turns if re.search(r'rotation, guests ', lines[i])]
    rows.append(f'rotation: {len(turns)} decisions, {len(guest_turns)} for the guests')
    if rotation and not guest_turns: problems.append("no guests' turn in the rotation")
    grafted = []
    for start in guest_turns:
        end = next((i for i in turns if i > start), len(lines))
        for l in lines[start:end]:
            m = GRAFT.search(l)
            if m and m.group(2).lower().replace(' ', '').replace('.', '') in guests: grafted.append(m.group(2) + '/' + m.group(3))
    rows.append(f"guests grafted in the guests' Embu: {grafted or 'none'}")
    if guest_turns and not grafted: problems.append("no guest of the casting grafted in the guests' Embu")
    return rows, problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=Path)
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--mods', type=Path)
    ap.add_argument('--embus', type=int, default=4)
    ap.add_argument('--log', type=Path, help='check this log only, no game')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    rows, problems = [], []
    if a.log: log = a.log
    else:
        if not a.mods: ap.error('--mods or --log')
        r = subprocess.run([sys.executable, str(ROOT / 'tools/test_embu_rotation.py'), str(a.out), '--mods', str(a.mods),
                            '--build', a.build, '--tier', '0', '--embus', str(a.embus)])
        embus = (a.out / 'embus.txt').read_text().splitlines() if (a.out / 'embus.txt').is_file() else []
        rows += ['rotation bench: ' + (embus[-2] if len(embus) > 1 else '-'), 'rotation bench: ' + (embus[-1] if embus else 'no embus.txt')]
        if r.returncode or not embus or embus[-1] != 'OK': problems.append('the rotation bench failed')
        log = a.out / 'game.log'
    more, issues = check_log(log.read_text(errors='replace'), not a.log)
    rows, problems = more + rows, issues + problems
    rows.append('OK' if not problems else 'ECHEC: ' + '; '.join(problems))
    (a.out / 'b152.txt').write_text('\n'.join(rows) + '\n')
    print('\n'.join(rows))
    sys.exit(0 if not problems else 1)


if __name__ == '__main__':
    main()
