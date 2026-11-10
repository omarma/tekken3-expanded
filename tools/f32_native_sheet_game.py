#!/usr/bin/env python3
"""F32 E2: one sheet per native from the game's HQ captures, for the user to judge.

    python tools/f32_native_sheet_game.py [--work workspace/f32-native-models] [--out DIR]

Reads the captures of tools/test_f32_native_models.py --sweep ... --hq (TTT1
models) and --sweep ... --hq --off (PS1 models): <tag>-<native>-<button>-stance.png
and -3-b.png. One row per selection button of the native that has a TTT1 slot
(tools/data/ttt1_native_models.json): the PS1 model of the same costume (stance),
then the TTT1 model (stance, then kick 3). Each image is cropped to the fighters.
Captures missing for a button leave its cells grey, with the reason when the
sweep's JSON gives one. Writes <out>/F32-E2-<native>.png (game data: workspace/).
"""
import argparse, json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
TABLE = json.loads((ROOT / 'tools/data/ttt1_native_models.json').read_text(encoding='utf-8'))['natives']
ORDER = ('LP', 'RP', 'LK', 'RK', 'Start')
COSTUME = {'LP': 'LP', 'RP': 'LP', 'LK': 'LK', 'RK': 'LK', 'Start': 'Start'}   # the PS1 capture of that costume
CROP = (0.08, 0.16, 0.92, 0.98)                                            # left, top, right, bottom (fractions)
CELL = (480, 400)


def font(n):
    for f in ('arial.ttf', 'DejaVuSans.ttf'):
        try: return ImageFont.truetype(f, n)
        except OSError: pass
    return ImageFont.load_default()


def cell(path):
    if not path or not path.is_file(): return None
    im = Image.open(path).convert('RGB'); w, h = im.size
    im = im.crop((int(CROP[0] * w), int(CROP[1] * h), int(CROP[2] * w), int(CROP[3] * h)))
    im.thumbnail(CELL, Image.LANCZOS)
    return im


def find(work, tags, native, button, shot):
    for tag in tags:
        p = work / f'{tag}-{native}-{button}-{shot}.png'
        if p.is_file(): return p
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--work', type=Path, default=ROOT / 'workspace/f32-native-models')
    ap.add_argument('--out', type=Path, default=None)
    ap.add_argument('--note', action='append', default=[], metavar='native:BUTTON=text', help='a remark under a row')
    a = ap.parse_args()
    out = a.out or a.work
    out.mkdir(parents=True, exist_ok=True)
    notes = {}
    for n in a.note:
        k, _, t = n.partition('='); notes[k] = t
    errors = {}
    for j in a.work.glob('sweep-*-hq*.json'):
        for k, r in json.loads(j.read_text(encoding='utf-8')).items():
            if r.get('error'): errors.setdefault(k, r['error'])
    ttt, ps1 = ['sweep-ttt1-hq', *[f'sweep-ttt1-hq-{i}' for i in range(1, 9)]], \
               ['sweep-ps1-hq', *[f'sweep-ps1-hq-{i}' for i in range(1, 9)]]
    f1, f2 = font(28), font(20)
    for native, entry in TABLE.items():
        rows = [b for b in ORDER if entry['buttons'][b] is not None]
        pad, head, label = 10, 50, 150
        W = label + 3 * (CELL[0] + pad) + pad
        H = head + len(rows) * (CELL[1] + 34 + pad) + pad
        sheet = Image.new('RGB', (W, H), (30, 32, 36)); d = ImageDraw.Draw(sheet)
        d.text((pad, 10), f'{native.capitalize()} — PS1 (même costume) | TTT1 garde | TTT1 coup 3', font=f1, fill=(240, 240, 240))
        for i, b in enumerate(rows):
            y = head + i * (CELL[1] + 34 + pad)
            d.text((pad, y + 10), b, font=f1, fill=(255, 210, 90))
            d.text((pad, y + 50), f"empl. {entry['buttons'][b]}", font=f2, fill=(200, 200, 200))
            images = [cell(find(a.work, ps1, native, COSTUME[b], 'stance')),
                      cell(find(a.work, ttt, native, b, 'stance')), cell(find(a.work, ttt, native, b, '3-b'))]
            for c, im in enumerate(images):
                x = label + c * (CELL[0] + pad)
                d.rectangle([x, y, x + CELL[0] - 1, y + CELL[1] - 1], fill=(58, 62, 70))
                if im: sheet.paste(im, (x + (CELL[0] - im.width) // 2, y + (CELL[1] - im.height) // 2))
                elif c: d.text((x + 10, y + 10), errors.get(f'{native}-{b}', 'pas de capture')[:60], font=f2, fill=(255, 120, 120))
            if f'{native}:{b}' in notes:
                d.text((label, y + CELL[1] + 4), notes[f'{native}:{b}'], font=f2, fill=(255, 160, 120))
        sheet.save(out / f'F32-E2-{native}.png')
        print(out / f'F32-E2-{native}.png')


if __name__ == '__main__':
    main()
