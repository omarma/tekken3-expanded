#!/usr/bin/env python3
"""B136 (GH#189): a game folder copied somewhere else must still find its
disc and memory cards.

    python ressources/slot.py --kind game --who b136 --prio 2 -- \\
        python tools/test_b136_portable_paths.py OUT [--exe build-rel-lite/Tekken_3_Expanded.exe]
            [--root <game folder>] [--seconds 25]

OUT must not exist. It becomes a copied install: game.toml, disc (a junction
or symlink to --root's disc, read only), saves (copies of --root's cards) and
build-release (the exe, its bios and assets). Its settings.toml and disc.cfg
are those of an install made elsewhere, as when a player sets the game up on
a PC and copies it to a Steam Deck: [disc] path, [memcard] dir, card1 and
card2 point into a folder that does not exist.

Two runs, headless and without the launcher:
  moved   the stale settings: the runtime must say each path was moved into
          OUT (disc, card dir, both cards) and boot the BIOS. Before the fix
          it printed "no disc image selected" and exited (and, with the
          launcher, opened First-run setup).
  control the same paths rewritten into OUT: nothing to move, BIOS booted.
Exit 1 if either fails.
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GHOST = 'C:/Users/b136-ghost/Downloads/tekken3-expanded-1.2.1'
DISC = 'disc/Tekken 3 (USA).cue'


def link_dir(link: Path, target: Path):
    if os.name == 'nt':
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                       check=True, stdout=subprocess.DEVNULL)
    else:
        link.symlink_to(target, target_is_directory=True)


def make_install(out: Path, exe: Path, root: Path):
    out.mkdir(parents=True)
    shutil.copy2(root / 'game.toml', out / 'game.toml')
    link_dir(out / 'disc', root / 'disc')
    (out / 'saves').mkdir()
    for card in ('card1.mcd', 'card2.mcd'):
        if (root / 'saves' / card).exists():
            shutil.copy2(root / 'saves' / card, out / 'saves' / card)
    br = out / 'build-release'
    br.mkdir()
    shutil.copy2(exe, br / exe.name)
    for sub in ('bios', 'assets'):
        if (exe.parent / sub).is_dir():
            shutil.copytree(exe.parent / sub, br / sub)
    return br / exe.name


def write_settings(br: Path, base: str):
    (br / 'settings.toml').write_text(
        f'[disc]\npath = "{base}/{DISC}"\n\n'
        f'[memcard]\ndir     = "{base}/saves"\n'
        f'card1   = "{base}/saves/card1.mcd"\ncard2   = "{base}/saves/card2.mcd"\n'
        'enable1 = true\nenable2 = true\n', encoding='utf-8')
    (br / 'disc.cfg').write_text(f'{base}/{DISC}\n', encoding='utf-8')


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def run(exe: Path, log: Path, seconds: float):
    """Run headless without the launcher from an unrelated cwd; the log."""
    env = dict(os.environ, PSX_NO_LAUNCHER='1')
    with open(log, 'wb') as f:
        p = subprocess.Popen([str(exe), '--headless', '--no-launcher',
                              '--debug-port', str(free_port())],
                             cwd=str(log.parent), env=env, stdout=f, stderr=subprocess.STDOUT)
        t0 = time.time()
        while p.poll() is None and time.time() - t0 < seconds:
            if b'loading BIOS from' in log.read_bytes():
                time.sleep(2)
                break
            time.sleep(0.5)
        if p.poll() is None:
            p.kill()
        p.wait()
    return log.read_text(errors='replace')


def check(name: str, text: str, out: Path, moved: bool):
    ok = True
    booted = 'loading BIOS from' in text
    nodisc = 'no disc image selected' in text
    print(f'{name}: BIOS booted {booted}, "no disc image selected" {nodisc}')
    ok &= booted and not nodisc
    expect = {'[disc] path': out / DISC, '[memcard] dir': out / 'saves',
              '[memcard] card1': out / 'saves/card1.mcd', '[memcard] card2': out / 'saves/card2.mcd'}
    for key, want in expect.items():
        lines = [l for l in text.splitlines() if f'settings.toml {key} ' in l and 'not found' in l]
        if not moved:
            print(f'  {key}: {"moved (unexpected)" if lines else "kept"}')
            ok &= not lines
            continue
        got = lines[0].split('; using ', 1)[-1].strip() if lines else ''
        same = bool(got) and Path(got).resolve() == want.resolve()
        print(f'  {key}: {got or "not moved"}')
        ok &= same
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=Path)
    ap.add_argument('--exe', type=Path, default=ROOT / 'build-rel-lite/Tekken_3_Expanded.exe')
    ap.add_argument('--root', type=Path, default=Path('C:/TekkenProject/Tekken3Recompiled'),
                    help='a game folder with game.toml, disc/ and saves/')
    ap.add_argument('--seconds', type=float, default=25)
    a = ap.parse_args()
    out = a.out.resolve()
    if out.exists():
        sys.exit(f'{out} exists: give a new folder')
    if Path(GHOST).exists():
        sys.exit(f'{GHOST} exists: the stale path must not')
    exe = make_install(out, a.exe.resolve(), a.root.resolve())
    br = exe.parent

    write_settings(br, GHOST)
    ok = check('moved', run(exe, out / 'moved.log', a.seconds), out, True)
    write_settings(br, out.as_posix())
    ok &= check('control', run(exe, out / 'control.log', a.seconds), out, False)
    print('OK' if ok else 'FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
