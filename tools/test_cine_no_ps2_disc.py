#!/usr/bin/env python3
"""B95: TTT Cinematics prepared without a TTT PS2 disc, as the setup does.

    python3 tools/test_cine_no_ps2_disc.py [--keep DIR]

Runs tools/ttt_cinematics.py in a fresh interpreter (the setup's command
line, no --ttt-disc, no PYTHONPATH) into a new folder, so the Tekken 3
music fallback runs (t3_music: Tekken 3's XA streams read from disc/, the
only path the setup takes without the PS2 disc; 18cbe315 had left its
`from glyphs import data_track` without tools/ttt1 on the path, and the
setup failed on "The TTT cinematics could not be prepared"). Jin's models
and his red lightning are stand-ins put there first (they come from the
TTT1 import's work files, not what is tested here). Then: exit status 0;
t3-music.pcm and every declaration's fallback file there, 16-bit stereo at
44 100 Hz, not silent; no TTT piece (ending-music.pcm, the Embu's own);
every .cine with music names its fallback and not the missing piece;
triggers.txt, and version.txt at CINEMATICS_VERSION. Needs disc/ (the
setup's: SLUS_004.02 and its cue's data track). The setup's Python
(.setup/venv: numpy). Exit status 1 on any failure.
"""
import argparse, gzip, json, os, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import ttt_cinematics as C


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--keep', type=Path, help='prepare into this new folder and keep it')
    a = ap.parse_args()
    if not (C.T3_DISC / 'SLUS_004.02').is_file():
        sys.exit(f'{C.T3_DISC}: no Tekken 3 disc set up (the setup copies it there)')
    if a.keep and a.keep.exists():
        sys.exit(f'{a.keep}: give a folder that does not exist yet')
    tmp = None if a.keep else tempfile.TemporaryDirectory()
    out = a.keep or Path(tmp.name) / 'ttt-cinematics'
    out.mkdir(parents=True)
    for name in C.MODELS:
        for ext in ('3dm', 'relocs', 'tim', 'face'):
            (out / f'{name}-TTT1-arcade-P1.{ext}').write_bytes(b'stand-in')
    (out / C.EFFECT).write_bytes(b'stand-in')

    env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
    run = subprocess.run([sys.executable, ROOT / 'tools/ttt_cinematics.py', '--catalogue', out.parent / 'ttt1',
                          '--out', out], env=env, capture_output=True, text=True)
    print(run.stdout.strip())
    failures = []
    if run.returncode:
        failures.append(f'tools/ttt_cinematics.py exited {run.returncode}:\n{run.stderr.strip()}')
    else:
        import numpy as np
        pieces = {'t3-music.pcm'} | {e['music']['fallback_file'] for e in C.CONVERTED.values() if e.get('music')}
        for name in sorted(pieces):
            f = out / name
            if not f.is_file(): failures.append(f'{name} missing'); continue
            pcm = np.frombuffer(f.read_bytes(), '<i2')
            seconds = len(pcm) / 2 / 44100
            loud = int(np.abs(pcm).max()) if len(pcm) else 0
            print(f'{name}: {seconds:.1f} s, peak {loud}')
            if len(pcm) % 2 or seconds < 10 or loud < 1000: failures.append(f'{name}: {seconds:.1f} s, peak {loud}')
        own = {'ending-music.pcm'} | {e['music']['file'] for e in C.CONVERTED.values() if e.get('music')}
        failures += [f'{name} there without the TTT disc' for name in sorted(own) if (out / name).exists()]
        for key, e in C.CONVERTED.items():
            data = json.loads(gzip.decompress((C.DATA / f'{key}.json.gz').read_bytes()))
            if data.get('music') is None: continue
            lines = (out / f'{key}.cine').read_text().splitlines()
            fallback = C.music_files(e)[1]
            if not any(l.startswith(f'music-fallback {fallback} ') for l in lines):
                failures.append(f'{key}.cine: no "music-fallback {fallback}"')
            if any(l.startswith('music ') for l in lines):
                failures.append(f'{key}.cine names a TTT piece it does not have')
        if not (out / 'triggers.txt').is_file(): failures.append('triggers.txt missing')
        if C.read_stamp(out) != C.CINEMATICS_VERSION:
            failures.append(f'version.txt {C.read_stamp(out)}, not {C.CINEMATICS_VERSION}')
    if tmp: tmp.cleanup()
    for f in failures: print('FAIL', f)
    print('FAIL' if failures else 'OK: TTT Cinematics prepared without the TTT PS2 disc')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
