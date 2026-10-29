#!/usr/bin/env python3
"""The Embu's guests keep their own strong-hit effects (GH#29 again in 1.4.0, B115).

    python tools/test_embu_guest_sparks.py OUT [--build build-dbg] [--hitspark on|off] [--cast default|none]
        [--after-guest]

Build: PSX_DEBUG_TOOLS=ON (the debug server's high_vram), its mods/ with the TTT1 catalogue at import version 10 or
later. tools/test_hit_effect_64.py's game (headless, software, x1), TTT Cinematics off so that the Embu is Tekken 3's
(variant 0 on a new card), the Embu TTT casting at the launcher's defaults (Kunimitsu plays Yoshimitsu, Kazuya Jin)
or none (--cast none: the natives themselves). Start at the title, then no input: the Embu (state 6) comes from the
modes menu (TIPS § 28).

Each strong-hit effect the Embu plays (a sprite of 0x800A3408 alive, palette row 503, pack at x 368 for player 1,
496 for player 2) is noted with, a few frames in: the native whose part the actor plays (+0x14 >> 2); its effect
entry's header (0x800A35C8 + 16 * player -> 6 bytes at 0x80027950 + ID * 6: images, then the light's RGB); whose
32 x 32 pack lies at x 368 / 496 (its images and the palette of row 503, against every <Name>-TTT1-hiteffect.tim of
the catalogue); with TTT Hitspark, whose 64 x 64 lies in the player's cells of the upper half (its images and its
palette at (560, 896 + 32 * player), against every *-hiteffect64.hfx). Packs alike are named together ("Angel|Devil|
Kazuya": TTT1's lightning is theirs); one with the most images and the palette alike, else "?".
Checks (exit 1 otherwise): at least one effect for each side; a guest's part (the log's "TTT1 Embu: Pn <Guest> on
<native>'s model") shows the guest's 32 x 32, 64 x 64 and the header of its pack's length; a native's part, the
native's own 64 x 64 (its 32 x 32 is the disc's, not in the catalogue: noted only). OUT/effects.txt, OUT/game.log.
"""
import argparse, os, shutil, struct, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/arcade_stages'), str(ROOT / 'psxrecomp/tools')]
import test_hit_effect_64 as H
from high_vram_check import set_feature

SCREEN = 0x800ae204
ACTOR, STRIDE = 0x800a9228, 0x188c
FX_SPRITES, EFFECT_ROWS, HEADERS = 0x800a3408, 0x800a35c8, 0x80027950
START = 0xfff7
CINEMATICS = ('tekken3.cinematic.ttt-cinematics', 'ttt-cinematics')
KEYS = ['paul', 'law', 'lei', 'king', 'yoshimitsu', 'nina', 'hwoarang', 'xiaoyu', 'eddy', 'jin', 'julia', 'kuma',
        'bryan', 'heihachi', 'ogre', 'mokujin', 'gunjack', 'gon', 'anna', 'drb']


def cell(p, k):
    """Image k's cell of player p in the upper half (src/tekken3_ttt1_combat.c hfx_cell)."""
    if k >= 30: return (672 if p else 576) + 16 * (k - 30), 896
    if p: return 544 + 16 * k, 832
    if k == 29: return 544, 896
    return (544 + 16 * k if k < 2 else 592 + 16 * (k - 2)), 768


def catalogue(ttt1):
    """{name: its 32 x 32 images} and {name: its 64 x 64 images} from the catalogue, and each 32 x 32 pack's length."""
    small, big, frames = {}, {}, {}
    for f in ttt1.glob('*-hiteffect.tim'):
        b = f.read_bytes()
        if len(b) < 576 or len(b) % 576: continue
        name = f.name.split('-')[0]
        small[name] = [b[20:52]] + [b[k * 576 + 64:(k + 1) * 576] for k in range(len(b) // 576)]   # palette, images
        frames[name.lower()] = len(b) // 576
    for f in ttt1.glob('*-hiteffect64.hfx'):
        try: n, pals, images = H.hfx(f)
        except AssertionError: continue
        big[f.name.split('-')[0]] = [pals[0]] + images
    return small, big, frames


def whose(candidates, images):
    """The candidate whose palette and images match the most of those read (palette first: the Mishima share their
    images, Jin's red lightning is their images in red)."""
    score = {name: (own[0] == images[0]) * 100 + sum(k < len(own) and own[k] == im for k, im in enumerate(images[1:], 1))
             for name, own in candidates.items()}
    best = max(score.values(), default=0)
    names = sorted(n for n, v in score.items() if v == best)
    return names[0] if best and len(names) == 1 else '?' if not best else '|'.join(names)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=Path)
    ap.add_argument('--build', default='build-dbg')
    ap.add_argument('--hitspark', choices=('on', 'off'), default='on')
    ap.add_argument('--cast', choices=('default', 'none'), default='default')
    ap.add_argument('--after-guest', action='store_true',
                    help="the state a fight with a guest leaves (TTT1 characters' control byte at 1, as                     tekken3_ttt1_select(1)), written at the modes menu")
    a = ap.parse_args()
    out = a.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    build = (ROOT / a.build).resolve()
    small, big, frames = catalogue(build / 'mods/ttt1')

    # A view of the build whose state.toml has TTT Cinematics off (H.Game copies the files of <build>/mods).
    view = H.WORK / f'view-{os.getpid()}'
    shutil.rmtree(view, ignore_errors=True); (view / 'mods').mkdir(parents=True)
    for p in (build / 'mods').iterdir():
        if p.is_file(): shutil.copy2(p, view / 'mods' / p.name)
        elif p.name == 'ttt1':
            (view / 'mods/ttt1').mkdir()
            for f in p.iterdir(): os.link(f, view / 'mods/ttt1' / f.name)
        else: subprocess.run(['cmd', '/c', 'mklink', '/J', str(view / 'mods' / p.name), str(p)], check=True, capture_output=True)
    set_feature(view / 'mods/state.toml', False, CINEMATICS)
    exe = next(p for p in (build / 'Tekken_3_Expanded.exe', build / 'Tekken_3_Expanded') if p.exists())
    os.link(exe, view / exe.name)
    subprocess.run(['cmd', '/c', 'mklink', '/J', str(view / 'bios'), str(build / 'bios')], check=True, capture_output=True)

    env = [('TEKKEN3_EMBU_CAST', 'none=none')] if a.cast == 'none' else []
    g = H.Game(view, f'b115-{a.hitspark}-{a.cast}', env=env, hitspark=a.hitspark == 'on')
    rows, effects, failures = [], [], []
    try:
        g.wait(lambda: g.value(SCREEN) >= 2, 'the game did not boot', 120)
        def menu():
            if g.value(SCREEN) == 3: g.press(START)
            return g.value(SCREEN) == 4
        g.wait(menu, 'the modes menu never came', 240)
        if a.after_guest:
            control = int(g.log().split('TTT1 characters: control=')[1][:8], 16)
            g.write(control, bytes([1])); g.write(control + 12, bytes([2]))
            rows.append(f'control byte {control:08X} at 1 (after a fight with a guest)')
        g.wait(lambda: g.value(SCREEN) == 6, 'no Embu after the modes menu', 120)
        rows.append(f'Embu from frame {g.frame()}, variant {g.value(0x80097f20, 1)}')
        seen, hi_path = {}, out / 'high-vram.bin'
        while g.value(SCREEN) == 6:
            fx = g.read(FX_SPRITES, 192)
            for i in range(3):
                life, = struct.unpack_from('<h', fx, 64 * i + 2)
                base, = struct.unpack_from('<H', fx, 64 * i + 0x14)
                clut_y, = struct.unpack_from('<H', fx, 64 * i + 0x22)
                key = (i, base)
                if life <= 0 or clut_y != 503 or base not in (368, 496):
                    seen.pop(key, None); continue
                if key in seen: continue
                seen[key] = life
                p = base == 496
                g.frames(3)
                native = g.value(ACTOR + p * STRIDE + 0x14, 2) >> 2
                header = g.value(EFFECT_ROWS + 16 * p)
                hb = g.read(header, 6)
                images, rgb = struct.unpack_from('<H', hb)[0], tuple(hb[2:5])
                # The 32 x 32 pack: frame k at x base + 8 (k % 2), y 32 (k / 2), 8 x 32 halfwords.
                peek = ''.join(g.q(cmd='vram_peek', x=base, y=y, w=16, h=128)['hex'] for y in range(0, 512, 128))   # 128 rows at most
                px = [int(peek[4 * k:4 * k + 4], 16) for k in range(16 * 480)]
                read32 = [b''.join(struct.pack('<H', px[(32 * (k // 2) + r) * 16 + 8 * (k % 2) + c]) for r in range(32) for c in range(8))
                          for k in range(30)]
                pal = g.q(cmd='vram_peek', x=16 * p, y=503, w=16, h=1)['hex']
                read32 = [b''.join(struct.pack('<H', int(pal[4 * k:4 * k + 4], 16)) for k in range(16))] + read32
                pack32 = whose(small, read32)
                pack64 = '-'
                if a.hitspark == 'on':
                    g.q(cmd='high_vram', path=hi_path.as_posix()); hi = hi_path.read_bytes()   # slashes: no escapes in its JSON
                    at = 2 * ((896 + 32 * p - 512) * 1024 + 560)
                    read64 = [hi[at:at + 32]]                                     # palette 0 (560, 896 + 32 p)
                    for k in range(30):
                        x, y = cell(p, k)
                        read64.append(b''.join(hi[2 * ((y - 512 + r) * 1024 + x):2 * ((y - 512 + r) * 1024 + x + 16)] for r in range(64)))
                    pack64 = whose(big, read64)
                effects.append({'frame': g.frame(), 'player': p + 1, 'native': KEYS[native] if native < 20 else native,
                                'header': (header - HEADERS) // 6 if header >= HEADERS else hex(header),
                                'images': images, 'rgb': rgb, 'pack32': pack32, 'pack64': pack64})
        log = g.log()
    finally:
        g.stop()
        for p in view.iterdir():
            if p.is_dir(): subprocess.run(['cmd', '/c', 'rmdir', str(p)], capture_output=True)
        shutil.rmtree(view, ignore_errors=True)
    (out / 'game.log').write_text(log)

    # Who plays each part, from the log: "TTT1 Embu: P2 Kunimitsu on yoshimitsu's model at ...".
    cast = {}
    for line in log.splitlines():
        if "'s model at" in line and 'TTT1 Embu: P' in line:
            words = line.split('TTT1 Embu: ')[1].split()
            cast[(int(words[0][1]), words[-4].split("'")[0])] = ' '.join(words[1:-5])
    rows.append('cast: ' + ', '.join(f'P{p} {n}={g_}' for (p, n), g_ in sorted(cast.items())))
    for e in effects:
        guest = cast.get((e['player'], e['native']))
        want = guest or e['native'].capitalize()
        bad = []
        # A name among those whose packs are the same (Kazuya, Angel and Devil share TTT1's lightning).
        if guest and want.lower() not in e['pack32'].lower().split('|'): bad.append(f"32 x 32 of {e['pack32']}")
        if a.hitspark == 'on' and want.lower() not in e['pack64'].lower().split('|'): bad.append(f"64 x 64 of {e['pack64']}")
        if guest and e['images'] != frames.get(want.lower()): bad.append(f"header of {e['images']} images")
        rows.append(f"frame {e['frame']} P{e['player']} {e['native']}{' (' + guest + ')' if guest else ''}: header {e['header']} "
                    f"({e['images']} images, light {e['rgb']}), 32 x 32 {e['pack32']}, 64 x 64 {e['pack64']}"
                    + (' -- FAIL: ' + ', '.join(bad) if bad else ''))
        if bad: failures.append(rows[-1])
    for p in (1, 2):
        if not any(e['player'] == p for e in effects): failures.append(f'no effect for player {p}')
    (out / 'effects.txt').write_text('\n'.join(rows) + '\n')
    print('\n'.join(rows))
    if failures:
        print('FAILED:\n  ' + '\n  '.join(failures)); sys.exit(1)
    print('all checks passed')


if __name__ == '__main__':
    main()
