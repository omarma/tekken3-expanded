#!/usr/bin/env python3
"""Embu TTT's casting plays only the guests' Embu, T3's variants 0, 1, 2 left alone (GH#134, B104,
src/tekken3_ttt1_mod.c embu_tick, src/tekken3_cine_trigger.c).

    python tools/test_embu_variant_cast.py OUT --mods <dir> [--build build-rel-lite] [--embus 4] [--window]

Boots a private copy of a debug-server build (rel-lite: headless, software, x1; tools/test_guest_records_card.py's
Game, its mods linked from the build then --mods, one with the TTT1 catalogue) on a new memory card in OUT/saves,
"Unlock All Characters" and TTT Cinematics off (no TTT Embu in the rotation), the Embu TTT casting at the
launcher's defaults. Once the boot has read the card, the roster (0x80097EF0) and the tier (0x80097F1F) of a save
with every character: the rotation is guests (variant 0 with the casting), variants 2, 0, 1. No input: the attract
alone (the Embu from the modes menu is not the natural one, TIPS § 28).

For each Embu (state 6): the rotation's turn ("Cine trigger: Embu rotation, ..." in the log), its variant and the
"TTT1 Embu: ... on ...'s model" grafts the log shows during it, plus the natives the two actors play (+0x14 >> 2).
Checks (exit 1 otherwise): every turn seen, grafts in the guests' Embu, none in variants 0, 1, 2. OUT/embus.txt,
OUT/game.log, OUT/states.txt. With PSX_FILM set (the local film patch), each Embu's first film frame is noted. Run
through ressources/slot.py (--kind game).
"""
import argparse, os, shutil, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_guest_records_card as gr

SCREEN, PHASE = gr.SCREEN, gr.PHASE
ROSTER, TIER, VARIANT, ACTOR, STRIDE = 0x80097ef0, 0x80097f1f, 0x80097f20, 0x800a9228, 0x188c
KEYS = ['paul', 'law', 'lei', 'king', 'yoshimitsu', 'nina', 'hwoarang', 'xiaoyu', 'eddy', 'jin', 'julia', 'kuma',
        'bryan', 'heihachi', 'ogre', 'mokujin', 'gunjack', 'gon', 'anna', 'drb']
STATE = '\n'.join(f'[[package]]\nid = "{p}"\n\n[[feature]]\npackage_id = "{p}"\nid = "{f}"\nenabled = false\n'
                  for p, f in (('tekken3.gameplay.all-characters', 'all-characters'),
                               ('tekken3.cinematic.ttt-cinematics', 'ttt-cinematics')))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=Path)
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--mods', type=Path, required=True)
    ap.add_argument('--embus', type=int, default=4)
    ap.add_argument('--window', action='store_true', help='a window instead of --headless (the film patch needs one)')
    a = ap.parse_args()
    a.out = a.out.resolve()
    a.out.mkdir(parents=True, exist_ok=True)
    saves = a.out / 'saves'
    if saves.exists(): shutil.rmtree(saves)
    (saves / 'openbios').mkdir(parents=True)
    mods = a.out / 'mods'
    if mods.exists():
        for entry in mods.iterdir(): gr.Game.unlink(entry)
    else: mods.mkdir()
    for entry in a.mods.iterdir():
        if entry.name == 'state.toml': continue
        if entry.is_dir(): gr.Game.link(entry.resolve(), mods / entry.name)
        else: shutil.copy2(entry, mods / entry.name)
    (mods / 'state.toml').write_text('format_version = 2\n\n' + STATE)
    film = os.environ.get('PSX_FILM')

    if a.window:
        popen = gr.subprocess.Popen
        gr.subprocess.Popen = lambda args, **k: popen([x for x in args if x != '--headless'], **k)
    g = gr.Game(ROOT / a.build, mods, saves)
    rows, embus, trace, t0 = [], [], [], time.monotonic()
    try:
        gr.booted(g)
        g.wait(lambda: g.value(SCREEN, 2) == 3, 'no title after the boot', 120)
        g.write(ROSTER, 0x1fffff); g.write(TIER, 2, 1)
        rows.append(f'tier {g.value(TIER, 1)}, roster {g.value(ROSTER):#x}, variant {g.value(VARIANT, 1)}')
        last, cur, log_at, turn = None, None, 0, None
        end = time.monotonic() + 900 + 400 * a.embus
        while time.monotonic() < end:
            st, ph = g.value(SCREEN, 2), g.value(PHASE, 2)
            if (st, ph) != last:
                trace.append(f'{time.monotonic() - t0:8.2f} state {st:2d} phase {ph:3d} variant {g.value(VARIANT, 1)}')
            log = g.log(); new = log[log_at:log.rfind('\n') + 1]; log_at += len(new)
            for line in new.splitlines():
                if 'Cine trigger: Embu rotation, ' in line: turn = line.split('Embu rotation, ')[1].split(' ')[0]
            if st == 6 and cur is None:
                cur = {'turn': turn, 'variant': g.value(VARIANT, 1), 'grafts': [], 'natives': set(),
                       'film': len(os.listdir(film)) if film else None}
            if cur is not None:
                cur['grafts'] += [l.split('TTT1 Embu: ')[1] for l in new.splitlines() if "'s model at" in l]
                if st == 6:
                    for p in (0, 1):
                        n = g.value(ACTOR + p * STRIDE + 0x14, 2) >> 2
                        cur['natives'].add(f'P{p + 1} {KEYS[n] if n < 20 else n}')
                else:
                    embus.append(cur)
                    rows.append(f'Embu {len(embus)}: {cur["turn"]}, variant {cur["variant"]}' +
                                (f', film from frame {cur["film"]}' if film else '') +
                                f'\n  natives: {", ".join(sorted(cur["natives"]))}' +
                                f'\n  grafts: {"; ".join(cur["grafts"]) or "none"}')
                    cur = None
                    if len(embus) >= a.embus: break
            last = (st, ph)
            time.sleep(.05)
    finally:
        shutil.copy2(g.logfile, a.out / 'game.log')
        (a.out / 'states.txt').write_text('\n'.join(trace) + '\n')
        g.stop()

    problems = []
    if len(embus) < a.embus: problems.append(f'{len(embus)} Embus of {a.embus}')
    for t in ('guests', 'v0', 'v1', 'v2'):
        if not any(e['turn'] == t for e in embus): problems.append(f'no {t}')
    for e in embus:
        if e['turn'] == 'guests' and (e['variant'] != 0 or not e['grafts']):
            problems.append(f'guests: variant {e["variant"]}, {len(e["grafts"])} grafts')
        if e['turn'] != 'guests' and e['grafts']: problems.append(f'{e["turn"]}: guests {e["grafts"]}')
    rows.append('OK' if not problems else 'ECHEC: ' + '; '.join(problems))
    (a.out / 'embus.txt').write_text('\n'.join(rows) + '\n')
    print('\n'.join(rows))
    sys.exit(0 if not problems else 1)


if __name__ == '__main__':
    main()
