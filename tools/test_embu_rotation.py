#!/usr/bin/env python3
"""The Embus' rotation with the TTT Embu second (src/tekken3_cine_trigger.c, `attract rotation=2`).

    python tools/test_embu_rotation.py OUT --mods <dir> [--build build-rel-lite] [--tier 0|1|2]
                                       [--embus N] [--hold l2|l1|r1|l1r1] [--off ttt-stages|ttt-cinematics]
                                       [--saves <dir>] [--card-save] [--variant V] [--visible] [--env K=V]

Boots a private copy of a debug-server build (rel-lite: headless, software, x1; tools/test_guest_records_card.py's
Game, its mods linked from the build then --mods) on the memory card folder --saves (OUT/saves by default, created
empty: a new card), "Unlock All Characters" off. No input: the attract alone. The save's tier (0x80097F1F) is
written once the boot has read the card, with a roster (0x80097EF0) that gives it (0: 11 characters, 1: 15,
2: 21, Dr. B's bit 19 in); without --tier the card's is kept. Each Embu is noted from the trigger's decision in
the game's log ("Embu rotation, ...embu.cine" or "the game's variant N"; headless, the TTT Embu's state 6 lasts
less than a poll), and each TTT one must then be played; without the table (--off ttt-cinematics), from state 6
entered and the variant (0x80097F20). --hold: that button held from the first demo fight until the next Embu
is chosen (T3's L1 / R1 / L1 + R1, our L2): that Embu is noted "held". --off: that feature off (state.toml).
--card-save: OPTION MODE > MEMORY CARD > CARD SAVE after the last Embu (the card and <card>-embu-rotation.txt
written). OUT/states.txt: every state and phase seen.

Checks (exit 1 otherwise): the natural Embus follow the rotation of the tier, [v0 TTT] / [v0 TTT v1] /
[v0 TTT v1 v2], from any place; with --off, no TTT and T3's own rotation, [v0] / [v0 v1] / [v0 v1 v2]; with
--hold l2 the held one is TTT, and the next natural one T3's v(1 if the tier allows it, else 0). OUT/embus.txt,
OUT/game.log. Run through ressources/slot.py (--kind game).
"""
import argparse, re, shutil, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_guest_records_card as gr

SCREEN, PHASE, MODE = gr.SCREEN, gr.PHASE, gr.MODE
ROSTER, TIER, VARIANT, CYCLE, PAD = 0x80097ef0, 0x80097f1f, 0x80097f20, 0x80097f3e, 0x800add68
ROSTERS = {0: 0x7ff, 1: 0x7fff, 2: 0x1fffff}
# Pad 1 as the debug server takes it (active low, the SIO order), and as the game reads it (0x800ADD68).
HOLD = {'l2': (0xfeff, 1), 'r2': (0xfdff, 2), 'l1': (0xfbff, 4), 'r1': (0xf7ff, 8), 'l1r1': (0xf3ff, 12)}
CYCLES = {0: ['v0', 'TTT'], 1: ['v0', 'TTT', 'v1'], 2: ['v0', 'TTT', 'v1', 'v2']}


def state_toml(off):
    lines = ['format_version = 2', '']
    features = [('tekken3.gameplay.all-characters', 'all-characters')]
    if off == 'ttt-stages': features.append(('tekken3.character.ttt1', 'ttt-stages'))
    if off == 'ttt-cinematics': features.append(('tekken3.cinematic.ttt-cinematics', 'ttt-cinematics'))
    for package, feature in features:
        lines += ['[[package]]', f'id = "{package}"', '', '[[feature]]', f'package_id = "{package}"',
                  f'id = "{feature}"', 'enabled = false', '']
    return '\n'.join(lines)


def follows(seen, cycle):
    """`seen` is a stretch of the endless repetition of `cycle`."""
    if not seen: return False
    return any(all(seen[k] == cycle[(s + k) % len(cycle)] for k in range(len(seen))) for s in range(len(cycle)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=Path)
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--mods', type=Path, required=True)
    ap.add_argument('--tier', type=int, choices=(0, 1, 2))
    ap.add_argument('--embus', type=int, default=5)
    ap.add_argument('--hold', choices=sorted(HOLD))
    ap.add_argument('--off', choices=('ttt-stages', 'ttt-cinematics'))
    ap.add_argument('--saves', type=Path)
    ap.add_argument('--card-save', action='store_true')
    ap.add_argument('--variant', type=int, choices=(0, 1, 2), help='written with --tier (where the rotation starts)')
    ap.add_argument('--visible', action='store_true', help='a window at 60 frames a second (a film), not headless')
    ap.add_argument('--env', action='append', default=[], metavar='KEY=VALUE')
    a = ap.parse_args()
    a.out = a.out.resolve()
    a.out.mkdir(parents=True, exist_ok=True)
    saves = (a.saves or a.out / 'saves').resolve()
    (saves / 'openbios').mkdir(parents=True, exist_ok=True)
    # The overlay: --mods, then our state.toml over it (never written into --mods).
    mods = a.out / 'mods'
    if mods.exists():
        for entry in mods.iterdir(): gr.Game.unlink(entry)
    else: mods.mkdir()
    for entry in a.mods.iterdir():
        if entry.name == 'state.toml': continue
        if entry.is_dir(): gr.Game.link(entry.resolve(), mods / entry.name)
        else: shutil.copy2(entry, mods / entry.name)
    (mods / 'state.toml').write_text(state_toml(a.off))

    g = gr.Game(ROOT / a.build, mods, saves, a.visible, dict(kv.split('=', 1) for kv in a.env))
    rows, embus, held, problems, trace, t0 = [], [], None, [], [], time.monotonic()
    try:
        gr.booted(g)
        g.wait(lambda: g.value(SCREEN, 2) == 3, 'no title after the boot', 120)
        if a.tier is not None:
            g.write(ROSTER, ROSTERS[a.tier]); g.write(TIER, a.tier, 1)
            if a.variant is not None: g.write(VARIANT, a.variant, 1)
        tier = g.value(TIER, 1)
        rows.append(f'tier {tier}, roster {g.value(ROSTER):#x}, variant {g.value(VARIANT, 1)}')
        last, hold_state, log_at = None, 'wait' if a.hold else None, 0
        end = time.monotonic() + 600 + 240 * a.embus
        while len(embus) < a.embus and time.monotonic() < end:
            st, ph = g.value(SCREEN, 2), g.value(PHASE, 2)
            if (st, ph) != last: trace.append(f'{time.monotonic() - t0:8.2f} state {st:2d} phase {ph:3d} cycle {g.value(CYCLE, 1)} variant {g.value(VARIANT, 1)}')
            if hold_state == 'wait' and st == 8 and g.value(MODE, 1) == 6 and ph >= 8:
                g.q(cmd='set_input', buttons=f'{HOLD[a.hold][0]:04x}'); hold_state = 'held'
                rows.append(f'hold {a.hold} in the demo fight (phase {ph})')
            # Each Embu: the trigger's decision in the log (headless, the TTT Embu's state 6 lasts less than a
            # poll), or, without the table (TTT Cinematics off), state 6 entered (T3's Embu stays in it).
            found = []
            if a.off == 'ttt-cinematics':
                if st == 6 and (last is None or last[0] != 6): found.append((f'v{g.value(VARIANT, 1)}', 'state 6'))
            else:
                log = g.log(); new = log[log_at:log.rfind('\n') + 1]; log_at += len(new)
                for line in new.splitlines():
                    if 'Cine trigger: Embu rotation, ' not in line: continue
                    m = re.search(r"the game's variant (\d+)", line)
                    found.append((f'v{m.group(1)}' if m else 'TTT', line.split('Cine trigger: ')[1]))
            for kind, why in found:
                # Held from the demo fight until the way back to the title has chosen (the next Embu).
                if hold_state == 'held':
                    rows.append(f'  pad 0x800ADD68 = {g.value(PAD, 2):#06x} at the choice (wanted {HOLD[a.hold][1]})')
                    g.q(cmd='clear_input'); hold_state = 'done'; held = len(embus)
                embus.append(kind)
                rows.append(f'Embu {len(embus)}: {kind}{" (held)" if held == len(embus) - 1 else ""}, '
                            f'tier {g.value(TIER, 1)}: {why}')
            last = (st, ph)
            time.sleep(.05)
        # The TTT Embus decided were played (the last one included).
        played = lambda: g.log().count('Cine trigger: attract, Embu variant')
        try: g.wait(lambda: played() >= embus.count('TTT'), '', 120)
        except AssertionError: pass
        if played() != embus.count('TTT'): problems.append(f'{embus.count("TTT")} TTT Embus decided, {played()} played')
        if a.card_save:
            gr.card_save(g)
            rows.append(f'CARD SAVE: variant {g.value(VARIANT, 1)}')
    finally:
        if 'Cine trigger: Embu rotation' not in g.log(): rows.append('(no "Embu rotation" line in the log)')
        shutil.copy2(g.logfile, a.out / 'game.log')
        (a.out / 'states.txt').write_text('\n'.join(trace) + '\n')
        g.stop()
    files = sorted(p.name for p in saves.iterdir() if p.is_file())
    rotation = saves / 'card1-embu-rotation.txt'
    rows.append(f'saves: {files}' + (f'; card1-embu-rotation.txt: {rotation.read_text().strip()}' if rotation.is_file() else ''))

    if len(embus) < a.embus: problems.append(f'{len(embus)} Embus of {a.embus}')
    natural = embus[held + 1:] if held is not None else embus
    cycle = [k for k in CYCLES[tier] if k != 'TTT'] if a.off else CYCLES[tier]
    if natural and not follows(natural, cycle): problems.append(f'natural Embus {natural}, not the rotation {cycle}')
    if a.hold == 'l2' and held is not None:
        if embus[held] != ('v0' if a.off else 'TTT') and not a.off: problems.append(f'L2 gave {embus[held]}')
        if held + 1 < len(embus) and not a.off and embus[held + 1] != ('v1' if tier else 'v0'):
            problems.append(f'after L2: {embus[held + 1]}')
    if a.hold in ('l1', 'r1', 'l1r1') and held is not None and tier:
        want = {'l1': 'v1', 'r1': 'v0', 'l1r1': 'v2' if tier >= 2 else None}[a.hold]
        if want and embus[held] != want: problems.append(f'{a.hold} gave {embus[held]}, not {want}')
    if a.hold and held is None: problems.append('the held return never came to an Embu')
    rows.append('sequence: ' + ' '.join(embus))
    rows.append('OK' if not problems else 'ECHEC: ' + '; '.join(problems))
    (a.out / 'embus.txt').write_text('\n'.join(r for r in rows if r) + '\n')
    print('\n'.join(r for r in rows if r))
    sys.exit(0 if not problems else 1)


if __name__ == '__main__':
    main()
