#!/usr/bin/env python3
"""A Tekken 3 native's TTT1 arcade models, converted for the native itself (F32).

    python tools/ttt1_native_model.py <native> [--key LP|RP|LK|RK|Start] [--slot N]
        [--out DIR] [--work DIR]

<native> is a key of tools/data/ttt1_native_models.json (jin, paul...). Each
selection button of the native whose slot is not null there goes through the
guests' conversion as it is (tools/ttt1_import.py model():
tools/ttt1/model/convert.py, texpack.py, faces, accessory springs) and is
written as <Name>-Native-TTT1-arcade-P<v + 1>.{3dm,relocs,tim,face,acc} in
--out (default workspace/ttt1-import/native-models/), v the cabinet's variant
of the button (VARIANT). Two buttons on one slot (Mokujin) convert it once.
The runtime draws the native with the model of the button that picked it,
its own moves, sounds and effects kept (src/tekken3_ttt1_mod.c,
native_model_entry). --key converts one button only; --slot replaces its
slot (tests).

Without MAME: the slots' models, textures and face tables are read through a
select-screen RAM rebuilt from the ROM (tools/ttt1/rom_ram.py, written by the
guests' import); --work is the import's work folder (ROM regions in ttt1/,
select RAMs in captures/), this checkout's, else the main checkout's. Game
data never leaves workspace/ (ignored by git).

Prints one JSON line per button (slot, bytes, unplaced rows), then writes
<out>/<native>-report.json. A slot that fails to convert is reported and
skipped (that button keeps the PS1 model); the exit code is 1 only when no
button converted.
"""
import argparse, json, shutil, sys, traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt1'), str(ROOT / 'tools/ttt1/model')]
TABLE = ROOT / 'tools/data/ttt1_native_models.json'
# Cabinet variant of each button (select_apply_costume_button): file P<v + 1>.
VARIANT = {'LP': 0, 'LK': 1, 'RP': 2, 'RK': 3, 'Start': 4}
SUFFIXES = ('3dm', 'relocs', 'tim', 'face', 'acc', 'hilt', 'stick')


def natives():
    return json.loads(TABLE.read_text(encoding='utf-8'))['natives']


def file_name(key):
    """The files' name, as the runtime's table and the TTT1 movesets' (Gunjack)."""
    return key.capitalize()


def default_work():
    """This checkout's import work folder, else the main checkout's (worktrees share it)."""
    own = ROOT / 'workspace/ttt1-import'
    if (own / 'ttt1/bankedroms.bin').is_file(): return own
    main = ROOT.parents[2] / 'workspace/ttt1-import' if ROOT.parent.name == 'worktrees' else own
    return main if (main / 'ttt1/bankedroms.bin').is_file() else own


def convert(native, out, work=None, keys=None, slot=None, log=print):
    """Converts the native's buttons; returns {button: report or {'error': ...}}."""
    import ttt1_import as I
    work = Path(work or default_work()).resolve()
    I.WORK, I.TTT1, I.CAPTURES = work, work / 'ttt1', work / 'captures'
    if not (I.TTT1 / 'bankedroms.bin').is_file():
        raise SystemExit(f'{I.TTT1}: no ROM regions; run tools/ttt1_setup.py once')
    # Any select RAM: what model() reads there (file directory, face and spring
    # tables) is static, by slot, the same in every capture.
    rams = sorted(I.CAPTURES.glob('*-select-ram.bin'))
    if not rams: raise SystemExit(f'{I.CAPTURES}: no select RAM')
    buttons = natives()[native]['buttons']
    name = file_name(native)
    out.mkdir(parents=True, exist_ok=True)
    reports, done = {}, {}                        # done: slot -> variant converted
    for button in (keys or VARIANT):
        s = slot if slot is not None else buttons.get(button)
        v = VARIANT[button]
        base = out / f'{name}-Native-TTT1-arcade-P{v + 1}'
        for e in SUFFIXES: base.with_suffix(f'.{e}').unlink(missing_ok=True)
        if s is None: continue
        if s in done:                              # the same slot on another button
            first = out / f'{name}-Native-TTT1-arcade-P{done[s] + 1}'
            for e in SUFFIXES:
                if first.with_suffix(f'.{e}').is_file(): shutil.copyfile(first.with_suffix(f'.{e}'), base.with_suffix(f'.{e}'))
            reports[button] = dict(slot=s, same_as=[b for b in VARIANT if VARIANT[b] == done[s]][0])
            log(json.dumps(dict(native=native, button=button, **reports[button])))
            continue
        try:
            r = I.model(rams[0], s, out, f'{name}-Native', out / 'work' / f'{native}-{s}', v + 1)
            reports[button] = dict(slot=s, **{k: r[k] for k in ('bytes', 'relocations', 'unplaced_rows', 'texture_mismatches')})
            done[s] = v
        except (Exception, SystemExit) as e:          # entries() stops with SystemExit
            for x in SUFFIXES: base.with_suffix(f'.{x}').unlink(missing_ok=True)
            reports[button] = dict(slot=s, error=str(e) or type(e).__name__)
            log(traceback.format_exc())
        log(json.dumps(dict(native=native, button=button, **reports[button])))
    return reports


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('native', choices=sorted(natives()))
    ap.add_argument('--key', choices=list(VARIANT), help='one selection button only')
    ap.add_argument('--slot', type=int, help="TTT1 model slot instead of the table's (with --key)")
    ap.add_argument('--out', type=Path, default=ROOT / 'workspace/ttt1-import/native-models')
    ap.add_argument('--work', type=Path, default=None, help='import work folder (ttt1/ ROM regions, captures/)')
    a = ap.parse_args(argv)
    if a.slot is not None and not a.key: ap.error('--slot needs --key')
    reports = convert(a.native, a.out, a.work, [a.key] if a.key else None, a.slot)
    if not a.key:
        (a.out / f'{a.native}-report.json').write_text(json.dumps(reports, indent=1) + '\n', encoding='utf-8')
    return 0 if any('error' not in r for r in reports.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
