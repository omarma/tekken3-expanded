#!/usr/bin/env python3
"""Import the TTT1 characters from your own arcade ROM, then rebuild the game.

    python3 tools/ttt1_setup.py [character ...] [--ttt1 tektagt.zip] [--jobs N]
        [--jin-red-lightning] [--tekken3 tekken3.zip] [--no-rebuild]
    python3 tools/ttt1_setup.py --update [--roster DIR]
    python3 tools/ttt1_setup.py --check-donor-reuse [--jobs N]

Without a character, every verified entry of tools/data/ttt1_characters.json
is imported, and with them everything built from those imports:

1. the guests, through tools/ttt1_import.py, read from the ROM without MAME
   (tools/ttt1/rom_ram.py; voices and sounds from C352 registers measured once,
   tools/data): the first one alone (it writes the shared select RAMs), the
   others in parallel;
2. the movesets Tetsujin draws and Unknown switches between (--moveset), one
   process per donor; Unknown's also give Tekken 3's own cast its TTT1 moves,
   and Kuma, Ogre, Gun Jack and True Ogre are read at their own index.
   A donor that is also a guest reuses the guest's moves and only gets its
   sounds, except the pairs of tools/data/ttt1_donor_reuse.json, which
   --check-donor-reuse (for developers, after a full import, whenever
   TTT1_IMPORT_VERSION changes) lists again;
3. Devil Jin (Jin confirmed with both punches): his model and his moves,
   once Jun, Devil and Unknown are imported;
4. with --jin-red-lightning, Jin's red strong-hit effect for the
   tekken3.visual.jin-ttt1-hit-effect mod;
5. with --tekken3, the arcade difficulty levels (tools/difficulty/import.py,
   read from both program ROMs, no MAME either);
6. the Practice move lists from the Tekken wiki (a warning only without a
   network), the COMBO TRAINING packs from tools/data/combos, the catalogue
   the TTT1 Characters mod reads (tools/ttt1_stage_roster.py), and a rebuild
   so it all ships beside the executable.

A full import stamps the catalogue with TTT1_IMPORT_VERSION
(tools/ttt1_import_version.py: increment it whenever the import's output
changes). --update brings an older catalogue up to it with the update steps
listed there when they suffice (launcher/setup_backend.py).

Each import is logged under workspace/ttt1-import/logs. Game data stays under
workspace/ and the build folders.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse, json, os, shutil, subprocess, sys
import ttt1_import_version as V

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'workspace/ttt1-import'
LOGS = WORK / 'logs'
TABLE = json.loads((ROOT / 'tools/data/ttt1_characters.json').read_text())['characters']


def run(args, **kwargs):
    subprocess.run([str(x) for x in args], check=True, **kwargs)


def characters():
    return [k for k, v in TABLE.items() if ('path' in v or 'force_index' in v) and 'asset' in v]


def imported(key):
    return (WORK / key / 'guest' / f'{key.capitalize()}-TTT1-combat.jmv').is_file()


def importer(args, key, *extra):
    command = [sys.executable, ROOT / 'tools/ttt1_import.py', key, *extra]
    if args.ttt1: command += ['--ttt1', args.ttt1]
    return command


def logged(command, log):
    """Run one import with its output in its own log; raise with the log's path."""
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(log, 'w') as f:
        done = subprocess.run([str(x) for x in command], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT)
    if done.returncode:
        raise RuntimeError(f'{Path(str(command[1])).name} {command[2]} failed; see {log.relative_to(ROOT)}')


def parallel(jobs, work):
    """work: [(label, command, log)], at most `jobs` at a time."""
    total = len(work)
    def one(item):
        label, command, log = item
        logged(command, log)
        return label
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        for n, label in enumerate(pool.map(one, work), 1):
            print(f'  [{n}/{total}] {label}', flush=True)


def guests(args, wanted):
    first, rest = wanted[0], wanted[1:]
    print(f'Guests: {first} first, alone (it writes the shared select RAMs)...', flush=True)
    logged(importer(args, first), LOGS / f'{first}.log')
    print(f'  [1/{len(wanted)}] {first}', flush=True)
    if rest:
        print(f'Guests: the other {len(rest)}, {args.jobs} at a time...', flush=True)
        parallel(args.jobs, [(k, importer(args, k), LOGS / f'{k}.log') for k in rest])


def natives(args):
    """Kuma, Ogre, Gun Jack and True Ogre on their TTT1 moves: the natives the
    donors of Unknown leave out, captured at their own index (natives section)."""
    keys = list(json.loads((ROOT / 'tools/data/ttt1_characters.json').read_text())['natives'])
    print(f'Natives: {len(keys)} TTT1 movesets, {args.jobs} at a time...', flush=True)
    parallel(args.jobs, [(k, importer(args, k), LOGS / f'native-{k}.log') for k in keys])


def donors(args, wanted):
    """Tetsujin's and Unknown's movesets, one process per donor, then their
    donors.txt written once (parallel runs would each write their own)."""
    sys.path.insert(0, str(ROOT / 'tools'))
    import ttt1_import as I
    for key in [k for k in wanted if TABLE[k].get('donors')]:
        entry, name = TABLE[key], key.capitalize()
        print(f'{name}: {len(entry["donors"])} movesets, {args.jobs} at a time...', flush=True)
        parallel(args.jobs, [(f'{key}@{d}', importer(args, key, '--moveset', d), LOGS / f'{key}@{d}.log')
                             for d in entry['donors']])
        out = WORK / key / 'guest'
        ready = [d for d in entry['donors'] if (out / f'{name}@{d.capitalize()}-TTT1-combat.jmv').is_file()]
        mode = 'switch button\n' if entry.get('donor_switch') == 'button' else ''
        (out / f'{name}-TTT1-donors.txt').write_text(
            mode + ''.join(f'{d.capitalize()} {I.donor_moveset(entry, TABLE, d)}\n' for d in ready))
        missing = sorted(set(entry['donors']) - set(ready))
        if missing: raise RuntimeError(f'{name}: movesets not imported: {", ".join(missing)}')


def check_donor_reuse(args):
    """Convert again every donor moveset that is also a guest, compare it with
    the guest's own files and write the pairs that differ, for this import
    version, to tools/data/ttt1_donor_reuse.json. After a full import."""
    sys.path.insert(0, str(ROOT / 'tools'))
    import ttt1_import as I
    convert = {}
    for key in [k for k in characters() if TABLE[k].get('donors')]:
        name, pairs = key.capitalize(), [d for d in TABLE[key]['donors'] if imported(d)]
        print(f'{name}: converting the {len(pairs)} movesets of guests, {args.jobs} at a time...', flush=True)
        parallel(args.jobs, [(f'{key}@{d}', importer(args, key, '--moveset', d, '--convert'), LOGS / f'{key}@{d}.log')
                             for d in pairs])
        convert[key] = [d for d in pairs if any(
            (WORK / key / 'guest' / f'{name}@{d.capitalize()}-TTT1-{e}').read_bytes() !=
            (WORK / d / 'guest' / f'{d.capitalize()}-TTT1-{e}').read_bytes() for e in I.REUSED)]
        print(f'  {name}: {len(pairs) - len(convert[key])} reusable, converted: {", ".join(convert[key]) or "none"}')
    I.REUSE.write_text(json.dumps(dict(import_version=V.TTT1_IMPORT_VERSION, convert=convert), indent=2) + '\n')
    print(f'{I.REUSE.relative_to(ROOT)} written.', flush=True)


def devil_jin():
    """Jin confirmed with both punches: TTT1 Jin's model with Devil's face (from
    Jun's capture), and TTT1 Jin's moves (Unknown's Jin) with Devil's grafted."""
    if not all(imported(k) for k in ('jun', 'devil', 'unknown')) or \
            not (WORK / 'unknown/guest/Unknown@Jin-TTT1-combat.jmv').is_file():
        print('Devil Jin: skipped (needs Jun, Devil and Unknown with its Jin moveset)', flush=True)
        return
    print('Devil Jin: model and moves...', flush=True)
    logged([sys.executable, ROOT / 'tools/ttt1_devil_jin.py'], LOGS / 'devil-jin.log')
    logged([sys.executable, ROOT / 'tools/ttt1_devil_jin_moves.py'], LOGS / 'devil-jin-moves.log')


def panda_tiger():
    """Panda's and Tiger's portraits and tiles, from TTT1's loading portraits."""
    print('Panda and Tiger portraits...', flush=True)
    logged([sys.executable, ROOT / 'tools/ttt1_panda_tiger.py'], LOGS / 'panda-tiger.log')


def devil_kick():
    """Devil imported again (captures reused): its Kick costume's model."""
    if not imported('devil'):
        print('Devil Kick costume: skipped (Devil not imported)', flush=True)
        return
    print('Devil Kick costume...', flush=True)
    logged([sys.executable, ROOT / 'tools/ttt1_import.py', 'devil'], LOGS / 'devil-kick.log')


def has_work_files():
    """The import's work files are there: the ROM regions and the captures
    (gone once the setup's "free up disk space" deleted workspace/)."""
    return (WORK / 'ttt1/bankedroms.bin').is_file() and (WORK / 'captures').is_dir()


def hands_step(roster, work):
    """Fist pose and per-guest grips (tools/ttt1_retrofit_hands.py; guests.txt's
    fourth column)."""
    import ttt1_retrofit_hands as H
    H.main([WORK if work else roster])     # WORK: the guests' own folders and the roster
    if work: return                        # staged again from the table after the steps
    listed = roster / 'guests.txt'
    lines = [l.split() for l in listed.read_text(encoding='utf-8').splitlines() if l.split()]
    listed.write_text(''.join(' '.join([*(w + ['-', '-'])[:3], TABLE.get(w[0], {}).get('hands', '--')]) + '\n'
                              for w in lines), encoding='utf-8')


UPDATE_STEPS = {'hands': hands_step,
                'devil-jin': lambda roster, work: devil_jin(),
                'panda-tiger': lambda roster, work: panda_tiger(),
                'devil-kick': lambda roster, work: devil_kick()}


def update(roster):
    """The update steps from the roster's stamp to TTT1_IMPORT_VERSION, in
    order, then the new stamp. Steps that need the work files restage the
    roster from them."""
    installed = V.read_stamp(roster)
    steps = V.update_steps(installed)
    if steps is None:
        raise ValueError(f'{roster}: import version {installed} needs a new import to reach {V.TTT1_IMPORT_VERSION}')
    work = has_work_files()
    if not work and any(V.STEPS[s][0] == 'workspace' for s in steps):
        raise ValueError(f'{roster}: the update needs the import work files under {WORK}, which are gone')
    print(f'TTT1 import version {installed} -> {V.TTT1_IMPORT_VERSION}: {len(steps)} update step(s)', flush=True)
    for n, step in enumerate(steps, 1):
        print(f'Update {n}/{len(steps)}: {V.STEPS[step][1]} ({step})', flush=True)
        UPDATE_STEPS[step](roster, work)
    if work and steps and roster.resolve() == (WORK / 'roster').resolve():
        run([sys.executable, ROOT / 'tools/ttt1_stage_roster.py', '--stamp'], cwd=ROOT)
    else:
        V.write_stamp(roster)
    print(f'TTT1 characters at import version {V.TTT1_IMPORT_VERSION}.', flush=True)


def rebuild():
    sys.path.insert(0, str(ROOT / 'psxrecomp/tools'))
    from toolchain_pack import resolve_toolchain_bin, activate_toolchain_bin
    toolchain = resolve_toolchain_bin(ROOT)
    if toolchain: activate_toolchain_bin(toolchain)
    cmake = shutil.which('cmake') or next(
        (str(p) for p in (ROOT / 'toolchain/bin/cmake.exe', ROOT / 'toolchain/bin/cmake') if p.is_file()), None)
    if not cmake:
        raise ValueError('Import succeeded. Put cmake on PATH, then run: '
                         'cmake -S . -B build-release && cmake --build build-release --target psx-runtime')
    build = ROOT / 'build-release'
    # The TTT1 package, the Jin effect and the difficulty levels are staged
    # only if present when CMake configures: configure again after an import.
    configure = [cmake, '-S', ROOT, '-B', build]
    if not (build / 'CMakeCache.txt').is_file():
        configure += ['-DCMAKE_BUILD_TYPE=Release']
        if shutil.which('ninja'): configure += ['-G', 'Ninja']
    run(configure)
    run([cmake, '--build', build, '--target', 'psx-runtime', '-j', str(os.cpu_count() or 8)])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('character', nargs='*', help='keys of tools/data/ttt1_characters.json (default: all)')
    ap.add_argument('--ttt1', type=Path, help='non-merged tektagt.zip, World TEG2/VER.C1')
    ap.add_argument('--jobs', type=int, default=min(os.cpu_count() or 4, 12),
                    help='imports at a time (default: the CPU count, at most 12)')
    ap.add_argument('--jin-red-lightning', action='store_true',
                    help="Jin's red TTT1 strong-hit effect (optional mod)")
    ap.add_argument('--tekken3', type=Path,
                    help='tekken3.zip (Tekken 3 arcade, TET2/VER.E1): the arcade difficulty levels')
    ap.add_argument('--no-rebuild', action='store_true')
    ap.add_argument('--update', action='store_true',
                    help='bring the imported catalogue up to this import version, without a new import')
    ap.add_argument('--check-donor-reuse', action='store_true',
                    help='developers: list again the donors that cannot reuse their guest moves')
    ap.add_argument('--roster', type=Path, default=WORK / 'roster', help='with --update: the catalogue')
    args = ap.parse_args()
    if args.update:
        update(args.roster.resolve())
        return
    if args.check_donor_reuse:
        check_donor_reuse(args)
        return
    if not (ROOT / 'disc/SLUS_004.02').is_file():
        raise ValueError('Run the launcher and Generate & rebuild with your USA Tekken 3 disc first.')
    for module in ('PIL', 'numpy'):
        try: __import__(module)
        except ImportError:
            raise ValueError(f'Missing {module}. Install the importer dependencies: '
                             f'{Path(sys.executable).name} -m pip install --require-hashes --only-binary=:all: -r tools/requirements-import.txt')
    wanted = [k.lower() for k in args.character] or characters()
    unknown = [k for k in wanted if k not in TABLE]
    if unknown: raise ValueError(f'unknown character(s): {", ".join(unknown)}')

    guests(args, wanted)
    donors(args, wanted)
    if not args.character: natives(args)
    devil_jin()
    panda_tiger()
    if args.jin_red_lightning:
        print("Jin's red lightning...", flush=True)
        command = [sys.executable, ROOT / 'tools/ttt1_jin_hit_effect.py']
        if args.ttt1: command += ['--ttt1', args.ttt1]
        logged(command, LOGS / 'jin-red-lightning.log')
    if args.tekken3:
        print('Arcade difficulty levels...', flush=True)
        command = [sys.executable, ROOT / 'tools/difficulty/import.py', '--tekken3', args.tekken3]
        if args.ttt1: command += ['--tektagt', args.ttt1]
        logged(command, LOGS / 'difficulty.log')
    # Practice's COMMAND LIST comes from the Tekken wiki pages kept in the
    # repository (tools/data/wiki): no network needed, the same lists for everyone.
    run([sys.executable, ROOT / 'tools/ttt1/movelist.py', *wanted], cwd=ROOT)
    # COMBO TRAINING: the measured combos (tools/data/combos) become each guest's pack.
    run([sys.executable, ROOT / 'tools/ttt1/combos.py', 'build'], cwd=ROOT)
    # A full import stamps the catalogue with this import version; importing
    # some characters only keeps the stamp the catalogue had.
    run([sys.executable, ROOT / 'tools/ttt1_stage_roster.py', *([] if args.character else ['--stamp'])], cwd=ROOT)
    if not args.no_rebuild: rebuild()
    print('TTT1 characters imported.', flush=True)


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'Import failed: {error}', file=sys.stderr); sys.exit(1)
