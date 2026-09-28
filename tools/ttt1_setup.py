#!/usr/bin/env python3
"""Import the TTT1 characters from your own arcade ROM, then rebuild the game.

    python3 tools/ttt1_setup.py [character ...] [--ttt1 tektagt.zip] [--mame mame]
        [--jobs N] [--jin-red-lightning] [--tekken3 tekken3.zip] [--no-rebuild]

Without a character, every verified entry of tools/data/ttt1_characters.json
is imported, and with them everything built from those imports:

1. the guests, through tools/ttt1_import.py: the first one alone (it fills the
   shared captures and the sound oracle, about 40 minutes the first time),
   the others in parallel, one MAME each;
2. the movesets Tetsujin draws and Unknown switches between (--moveset), one
   process per donor; Unknown's also give Tekken 3's own cast its TTT1 moves;
3. Devil Jin (Jin confirmed with both punches): his model and his moves,
   once Jun, Devil and Unknown are imported;
4. with --jin-red-lightning, Jin's red strong-hit effect for the
   tekken3.visual.jin-ttt1-hit-effect mod;
5. with --tekken3, the arcade difficulty levels (tools/difficulty/import.py);
6. the Practice move lists from the Tekken wiki (a warning only without a
   network), the COMBO TRAINING packs from tools/data/combos, the catalogue
   the TTT1 Characters mod reads (tools/ttt1_stage_roster.py), and a rebuild
   so it all ships beside the executable.

Each import is logged under workspace/ttt1-import/logs. Game data stays under
workspace/ and the build folders.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse, json, os, shutil, subprocess, sys

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
    if args.mame: command += ['--mame', args.mame]
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
    print(f'Guests: {first} first, alone (it fills the shared captures and sound oracle)...', flush=True)
    logged(importer(args, first), LOGS / f'{first}.log')
    print(f'  [1/{len(wanted)}] {first}', flush=True)
    if rest:
        print(f'Guests: the other {len(rest)}, {args.jobs} at a time...', flush=True)
        parallel(args.jobs, [(k, importer(args, k), LOGS / f'{k}.log') for k in rest])


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
    ap.add_argument('--mame', type=Path, help='MAME 0.289 executable')
    ap.add_argument('--jobs', type=int, default=min(os.cpu_count() or 4, 12),
                    help='imports at a time, one MAME each (default: the CPU count, at most 12)')
    ap.add_argument('--jin-red-lightning', action='store_true',
                    help="Jin's red TTT1 strong-hit effect (optional mod)")
    ap.add_argument('--tekken3', type=Path,
                    help='tekken3.zip (Tekken 3 arcade, TET2/VER.E1): the arcade difficulty levels')
    ap.add_argument('--no-rebuild', action='store_true')
    args = ap.parse_args()
    if not (ROOT / 'disc/SLUS_004.02').is_file():
        raise ValueError('Run the launcher and Generate & rebuild with your USA Tekken 3 disc first.')
    for module in ('PIL', 'numpy'):
        try: __import__(module)
        except ImportError:
            raise ValueError(f'Missing {module}. Install the importer dependencies: '
                             f'{Path(sys.executable).name} -m pip install -r tools/requirements-import.txt')
    wanted = [k.lower() for k in args.character] or characters()
    unknown = [k for k in wanted if k not in TABLE]
    if unknown: raise ValueError(f'unknown character(s): {", ".join(unknown)}')

    guests(args, wanted)
    donors(args, wanted)
    devil_jin()
    if args.jin_red_lightning:
        print("Jin's red lightning...", flush=True)
        command = [sys.executable, ROOT / 'tools/ttt1_jin_hit_effect.py']
        if args.ttt1: command += ['--ttt1', args.ttt1]
        if args.mame: command += ['--mame', args.mame]
        logged(command, LOGS / 'jin-red-lightning.log')
    if args.tekken3:
        print('Arcade difficulty levels...', flush=True)
        command = [sys.executable, ROOT / 'tools/difficulty/import.py', '--tekken3', args.tekken3]
        if args.ttt1: command += ['--tektagt', args.ttt1]
        if args.mame: command += ['--mame', args.mame]
        logged(command, LOGS / 'difficulty.log')
    # Practice's COMMAND LIST comes from the Tekken wiki (text kept out of git):
    # fetch it now; without a network the guests show Jin's list until it runs.
    try:
        run([sys.executable, ROOT / 'tools/ttt1/movelist.py', '--fetch', *wanted], cwd=ROOT)
    except (OSError, subprocess.SubprocessError) as error:
        print(f'Warning: could not fetch the move lists from the Tekken wiki ({error}); '
              'run python3 tools/ttt1/movelist.py --fetch later.', file=sys.stderr, flush=True)
    # COMBO TRAINING: the measured combos (tools/data/combos) become each guest's pack.
    run([sys.executable, ROOT / 'tools/ttt1/combos.py', 'build'], cwd=ROOT)
    run([sys.executable, ROOT / 'tools/ttt1_stage_roster.py'], cwd=ROOT)
    if not args.no_rebuild: rebuild()
    print('TTT1 characters imported.', flush=True)


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'Import failed: {error}', file=sys.stderr); sys.exit(1)
