#!/usr/bin/env python3
"""B88: a build without the TTT1 characters (-DTEKKEN3_TTT1_CHARACTERS=OFF) links.

    python tools/test_ttt1_off_link.py

The mod's sources are the src/*.c the `if(TEKKEN3_TTT1_CHARACTERS)` block of CMakeLists.txt
compiles. Every function or variable they define that the always-built code names (the other
src/ files, psxrecomp/runtime) must have an answer in src/tekken3_ttt1_off.c, which the block's
else() compiles: otherwise the OFF build stops at the link (ld.lld: undefined symbol), as it did
with tekken3_cine_scene_turbo (main.cpp, F09). Reads the sources only, builds nothing; the real
check is an OFF build (TIPS § 160).
"""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OFF = 'tekken3_ttt1_off.c'
KEYWORDS = {'if', 'for', 'while', 'switch', 'return', 'sizeof'}
FUNC = re.compile(r'^(?!static\b)[A-Za-z_][\w \t\*]*?[\s\*]([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{', re.M)
VAR = re.compile(r'^(?!static\b|extern\b|typedef\b|return\b)(?:const\s+)?[A-Za-z_]\w*[\s\*]+([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*[=;]', re.M)


def defined(text):
    names = {m.group(1) for m in FUNC.finditer(text)} | {m.group(1) for m in VAR.finditer(text)}
    return {n for n in names if n not in KEYWORDS and not n.startswith('__wrap_')}


def main():
    cm = (ROOT / 'CMakeLists.txt').read_text(encoding='utf-8')
    start = cm.index('if(TEKKEN3_TTT1_CHARACTERS)')
    m = re.compile(r'^(else|endif)\(\)', re.M).search(cm, start)
    block, tail = cm[start:m.start()], cm[m.start():cm.index('\nendif()', m.start())]
    mod = sorted(set(re.findall(r'src/(\w+\.c)', block)))
    errors = []
    if 'src/' + OFF not in tail:
        errors.append(f'the else() of if(TEKKEN3_TTT1_CHARACTERS) does not compile src/{OFF}')
    syms = {}
    for name in mod:
        for s in defined((ROOT / 'src' / name).read_text(encoding='utf-8', errors='replace')):
            syms.setdefault(s, name)
    others = [p for p in (ROOT / 'src').glob('*.c*') if p.name not in mod and p.name != OFF]
    others += [p for p in (ROOT / 'psxrecomp' / 'runtime').rglob('*')
               if p.suffix in ('.c', '.cpp', '.h', '.hpp', '.mm') and 'third_party' not in p.parts]
    used = {}
    for p in others:
        text = p.read_text(encoding='utf-8', errors='replace')
        for s in syms:
            if re.search(r'\b' + re.escape(s) + r'\b', text):
                used.setdefault(s, []).append(p.relative_to(ROOT).as_posix())
    answered = defined((ROOT / 'src' / OFF).read_text(encoding='utf-8'))
    for s in sorted(used):
        status = 'ok' if s in answered else 'MISSING'
        print(f'{status:7} {s} ({syms[s]}) named by {", ".join(used[s])}')
        if s not in answered:
            errors.append(f'{s} ({syms[s]}) has no answer in src/{OFF}')
    print(f'{len(mod)} sources of the mod, {len(syms)} symbols, {len(used)} named outside it')
    for e in errors:
        print('FAIL', e)
    print('FAIL' if errors else 'PASS')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
