#!/usr/bin/env python3
"""B140 (GH#190): Baek's and Wang's KO cry is their real one (TIPS.md section 220).

    python tools/test_b140_ko_cry.py [--build build-rel-lite] [--mods <dir>] [--memcard-dir saves]

The cabinet files Baek's and Wang's real KO cries as their victory voice (Baek
186, Wang 235) and plays an attack-like shout (187) or a damage-like one (234)
at the KO. src/tekken3_ttt1_voices.c plays the victory sample at the KO
instead, Wang's at Tekken 2's pitch (5604 instead of 6319: 73378 frames).

Runs tools/test_ko_echo.py (arcade, each subject KOed as player 1 and as the
CPU, round and match) on Baek, Wang and two witnesses, Jun and Lee, whose KO
cry must not change, and reads the games' logs. Exit status 1 when a KO plays
another sample, when the stretched cry has the wrong length, or when the echo
bench itself fails (a KO cry or an echo cut short). Launch it through slot.py.
"""
import argparse, re, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = {'Baek': 186, 'Wang': 235, 'Jun': 163, 'Lee': 174}
FIXED = {'Baek': (187, 186, 6319, 45163), 'Wang': (234, 235, 5604, 73378)}


def main():
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', default=str(ROOT / 'build-rel-lite'))
    ap.add_argument('--mods')
    ap.add_argument('--memcard-dir', default=str(ROOT / 'saves'))
    a = ap.parse_args()
    logs = Path(tempfile.mkdtemp(prefix='b140-'))
    cmd = [sys.executable, str(ROOT / 'tools/test_ko_echo.py'), '--build', a.build, '--memcard-dir', a.memcard_dir,
           '--only', 'arcade-p1,arcade-p2', '--guests', 'baek,wang,jun,lee', '--logs', str(logs)]
    if a.mods: cmd += ['--mods', a.mods]
    echo = subprocess.run(cmd).returncode

    text = ''.join(p.read_text(errors='replace') for p in sorted(logs.glob('*.log')))
    failures = []
    if echo: failures.append(f'test_ko_echo.py: exit status {echo}')
    for name, sample in EXPECTED.items():
        played = [int(s) for s in re.findall(rf'^{name} voice: P\d command=4[0-9A-F]{{3}} sample=(\d+)', text, re.M)]
        verdict = 'PASS' if played and set(played) == {sample} else 'FAIL'
        print(f'{verdict}  {name}: KO cries {played or "none"}, expected {sample}')
        if verdict == 'FAIL': failures.append(name)
    for name, (old, new, rate, frames) in FIXED.items():
        lines = re.findall(rf'^{name} voices: KO cry {old} -> {new} at {rate} Hz, (\d+) frames \(B140\)', text, re.M)
        verdict = 'PASS' if lines and all(int(n) == frames for n in lines) else 'FAIL'
        print(f'{verdict}  {name}: KO cry {old} -> {new} at {rate} Hz, frames {lines or "none"} (expected {frames})')
        if verdict == 'FAIL': failures.append(f'{name} remap')
    for name in set(EXPECTED) - set(FIXED):
        if re.search(rf'^{name} voices: KO cry .*\(B140\)', text, re.M):
            print(f'FAIL  {name}: remapped, it must not be'); failures.append(f'{name} remapped')
    print(f'logs: {logs}')
    print('B140: ' + ('FAIL ' + ', '.join(failures) if failures else 'PASS'))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
