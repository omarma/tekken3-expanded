#!/usr/bin/env python3
"""B172 (GH#220): the guests' HD portraits on the loading screen with QUICK SELECT.

    python tools/test_b172_quick_portraits.py OUT --data DIR [--exe build-rel-lite/Tekken_3_Expanded.exe]
        [--quick on|off|both] [--mode practice|arcade|vs] [--warmup] [--restore]
        [--rounds N] [--wide] [--renderer software|opengl]

DIR holds bios/ and mods/ with an import that has the HD files
(mods/ttt1/<Name>-T3-portrait-hd.bin; TIPS section 225). Headless software
renderer x2 (the HD substitutes need a scale above 1; --renderer opengl: a
window at x3), keyboard pads, no SDL joystick (the player's pad stays his),
a new memory card. Through slot.py.

From the modes menu, QUICK SELECT written (0x80097F10), the mode entered:
the VS grid (screen 10) or the selector (screen 9), the Tag page (R2), its
first guest chosen for both players, the loading screen. Check: while it
is up, the upper VRAM half holds each guest's HD portrait copy at
(192 p, 768), where the portrait substitute reads it (hd_portrait_put).

--warmup: first a Practice fight with QUICK SELECT off, then Start and
Start + Select: its stage stays loaded over the copies' rectangles, which
the loading screen could not write (the bug: fails before the fix in
Practice and Arcade with QUICK SELECT on). --restore: QUICK SELECT on, a
fight, the modes menu, the same fight again: the copies are written over
the stage on the loading screen, and the stage (not loaded again) must
have its own upper half back in the second fight.

Exit status 1 if a check fails. Screenshots and upper-half dumps in OUT.
"""
import argparse, os, shutil, socket, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'psxrecomp/tools'))
import debug_client

START, SELECT, CROSS, SQUARE, RIGHT, R2 = 0xfff7, 0xfffe, 0xbfff, 0x7fff, 0xffdf, 0xfdff
STATE, LINE, QUICK_SELECT = 0x800ae204, 0x80097f40, 0x80097f10
VS_BLOCK = 0x800b8d70
LOADING_END = 4      # screen 8 phases that still show the loading screen: 1..3
STATE_TOML = '''format_version = 2

[[package]]
id = "tekken3.enhancement.true-widescreen"

[[feature]]
package_id = "tekken3.enhancement.true-widescreen"
id = "true-widescreen"
enabled = {wide}

[[package]]
id = "tekken3.gameplay.all-characters"

[[feature]]
package_id = "tekken3.gameplay.all-characters"
id = "all-characters"
enabled = true
'''


class Game:
    def __init__(self, out, tag, exe, data, renderer='software', wide=False):
        self.run = out / f'run-{tag}'
        self.wide = wide
        shutil.rmtree(self.run, ignore_errors=True); self.run.mkdir(parents=True)
        shutil.copy2(exe, self.run / exe.name)
        shutil.copytree(data / 'bios', self.run / 'bios')
        (self.run / 'mods').mkdir()
        for e in (data / 'mods').iterdir():
            if e.name != 'state.toml':
                subprocess.run(['cmd', '/c', 'mklink', '/J', str(self.run / 'mods' / e.name), str(e)],
                               check=True, capture_output=True)
        (self.run / 'mods/state.toml').write_text(STATE_TOML.format(wide=str(wide).lower()))
        (self.run / 'settings.toml').write_text(
            f'[video]\nsupersampling={2 if renderer == "software" else 3}\nantialiasing=false\n'
            f'aspect_ratio="{"16:9" if wide else "4:3"}"\n'
            '[controller]\np1_device="keyboard"\np2_device="keyboard"\n')
        (self.run / 'cards').mkdir()
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0)); self.port = s.getsockname()[1]
        env = {k: v for k, v in os.environ.items() if not k.startswith(('TEKKEN3_', 'PSX_'))}
        env.update(SDL_AUDIO_DRIVER='dummy', SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS='0', SDL_XINPUT_ENABLED='0',
                   SDL_JOYSTICK_RAWINPUT='0', SDL_JOYSTICK_HIDAPI='0', SDL_JOYSTICK_WGI='0',
                   SDL_JOYSTICK_DIRECTINPUT='0', SDL_JOYSTICK_GAMEINPUT='0')
        self.log_path = out / f'{tag}.log'
        self.out = self.log_path.open('w')
        self.proc = subprocess.Popen(
            [str(self.run / exe.name), '--game', str(ROOT / 'game.toml'), '--disc', str(ROOT / 'disc/Tekken 3 (USA).cue'),
             '--no-launcher', '--renderer', renderer, *(['--headless'] if renderer == 'software' else []),
             '--debug-port', str(self.port),
             '--memcard-dir', str(self.run / 'cards')],
            cwd=self.run, stdout=self.out, stderr=self.out, env=env)
        end = time.monotonic() + 60
        while True:
            try: socket.create_connection(('127.0.0.1', self.port), .2).close(); break
            except OSError:
                if time.monotonic() > end or self.proc.poll() is not None: raise RuntimeError('no debug port')
                time.sleep(.2)

    def q(self, **r):
        for _ in range(600):
            res = debug_client.query('127.0.0.1', self.port, r)
            if res.get('err') != 'emu busy or frozen': return res
            time.sleep(.1)
        return res
    def value(self, a, n=4): return int.from_bytes(bytes.fromhex(self.q(cmd='read_ram', addr=f'{a:08x}', len=n)['hex']), 'little')
    def write(self, a, v, n=4): self.q(cmd='write_ram', addr=f'{a:08x}', bytes=v.to_bytes(n, 'little').hex())
    def press(self, b): self.q(cmd='press', buttons=b, frames=4); time.sleep(.4)
    def shot(self, p): self.q(cmd='screenshot' if self.wide else 'screenshot_hires', path=str(p))
    def frame(self): return self.q(cmd='frame')['frame']
    def prims(self): return self.q(cmd='high_vram').get('primitives', 0)
    def per_frame(self, seconds=1.5):
        f0, n0 = self.frame(), self.prims(); time.sleep(seconds); f1, n1 = self.frame(), self.prims()
        return (n1 - n0) / max(1, f1 - f0)
    def wait(self, pred, what, seconds=60, step=None):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if pred(): return
            if step: step()
            time.sleep(.1)
        raise AssertionError(what)
    def close(self):
        if self.proc.poll() is None: self.proc.kill()
        self.proc.wait(); self.out.close()
        for e in (self.run / 'mods').iterdir():
            if e.is_dir() and e.name != 'state.toml':
                try: os.rmdir(e)
                except OSError: pass


LINES = {'arcade': 0, 'vs': 1, 'practice': 8}


MODE_SELECT, DOWN, FIGHTERS = 0x800b8b60 + 0x75, 0xffbf, 0x800add5c
SELECTOR_GRID = 0x801296c8
GUEST_ID = 23


def on_tag_page(g):
    """The Tag page is up: on the VS grid its six-column cells start at x 75
    (the stock page's seven at 57; write_grid_page), 32 x 58 sprites in the
    last frame; on the selector its cell 0 holds ID 23 (test_locked_select.py)."""
    if g.value(STATE) == 9:
        return g.value(SELECTOR_GRID + 6, 2) == GUEST_ID
    f = g.frame() - 1
    for e in g.q(cmd='gpu_frame_dump', frame=f, count=8192).get('entries', []):
        w = [int(x, 16) for x in e['w']]
        if int(e['op'], 16) != 0x65 or len(w) < 4: continue
        if w[3] == 0x3a0020 and (w[1] & 0xffff) in range(74, 80): return True        # VS grid
    return False


def loading(g, out, name):
    """Choose on the grid (Cross; Cross again on the MOVESET card, the dummy,
    STAGE SELECT) until the loading screen, then follow it to the round:
    the primitives drawn from the upper half over the loading screen (the
    portraits' strips from the HD copies), and a screenshot of it."""
    def screen(): return g.value(STATE), g.value(0x800ae224, 2)
    end = time.monotonic() + 90
    while screen()[0] in (9, 10):
        if time.monotonic() > end:
            g.shot(out / f'{name}-stuck.png')
            raise AssertionError(f'the loading screen never came (screen {screen()})')
        g.q(cmd='press', buttons=CROSS, frames=3); time.sleep(.25)
    # The count at the last poll on the loading screen: screen 8's phases 1..3
    # draw nothing (the picture is held), the stage comes from phase 4 on.
    start, hd, shot = g.prims(), 0, False
    while time.monotonic() < end:
        st, n = screen(), g.prims()
        if st[0] == 11 or (st[0] == 8 and st[1] <= 3): hd = n - start
        if (st[0] == 11 or (st[0] == 8 and st[1] <= 3)) and not shot:
            time.sleep(.3); g.shot(out / f'{name}.png'); shot = True
            g.q(cmd='high_vram', path=str(out / f'{name}-upper.bin'))
        if st[0] == 8 and st[1] >= 8: break
        time.sleep(.02)
    return hd, g.value(FIGHTERS, 2), g.value(FIGHTERS + 2, 2)


def hd_copies(data, upper, fighters):
    """Per player whose fighter is a guest: whether the upper half (dumped on
    the loading screen) holds that guest's HD portrait copy where the
    portrait substitute reads it, (192 p, 768) (src/tekken3_ttt1_roster.c,
    hd_portrait_put; <Name>-T3-portrait-hd.bin, 168 x 252). None for a
    native fighter or a guest without the file."""
    keys = [l.split()[0] for l in (data / 'mods/ttt1/guests.txt').read_text().splitlines() if l.split()]
    hi = upper.read_bytes()
    res = []
    for p, fid in enumerate(fighters):
        k = fid - GUEST_ID
        if not 0 <= k < len(keys): res.append(None); continue
        files = [f for f in (data / 'mods/ttt1').glob('*-T3-portrait-hd.bin')
                 if f.name.lower().replace('-', '').startswith(keys[k].replace('-', ''))]
        if not files: res.append(None); continue
        px = files[0].read_bytes()
        ok = all(hi[((256 + r) * 1024 + 192 * p) * 2:((256 + r) * 1024 + 192 * p + 168) * 2] == px[r * 336:(r + 1) * 336]
                 for r in range(252))
        res.append(ok)
    return res


def player_select(g):
    """Practice's MODE SELECT (up at the round's start): Down to PLAYER SELECT, Cross."""
    g.wait(lambda: g.value(MODE_SELECT, 1), 'MODE SELECT is not up', 20)
    time.sleep(5)                                   # past the round's PRACTICE MODE title
    for _ in range(3): g.press(DOWN)
    g.shot(g.run.parent / 'mode-select.png')
    for _ in range(5):
        g.press(CROSS)
        try: g.wait(lambda: g.value(STATE) != 8, '', 4); break
        except AssertionError: pass
    g.wait(lambda: g.value(STATE) in (9, 10), f'PLAYER SELECT did not lead to the grid (screen {g.value(STATE)})', 30)
    time.sleep(2)


def to_menu(g):
    """The modes menu (state 4): Start at "Namco presents" (state 3)."""
    def menu():
        if g.value(STATE) == 3:
            g.write(0x80097f26, 1, 1); g.write(0x80097f27, 1, 1); g.press(START)
        return g.value(STATE) == 4
    g.wait(menu, 'modes menu', 240)
    time.sleep(.5)


def enter(g, mode, quick):
    """From the modes menu into `mode`, QUICK SELECT on or off: the grid
    (screen 10) or the selector (screen 9)."""
    g.write(QUICK_SELECT, 1 if quick else 0, 1)
    g.write(LINE, LINES[mode], 1)
    g.wait(lambda: g.value(STATE) in (9, 10), 'the selector or the grid', 60, lambda: (g.press(CROSS), time.sleep(.4)))
    time.sleep(2)


def fight_then_quit(g):
    """Choose (Cross) up to a round, then Start + Select: the modes menu. The
    fight's stage stays loaded (TIPS § 225: the pack is not reloaded)."""
    g.wait(lambda: g.value(STATE) == 8 and g.value(0x800ae224, 2) >= 8, 'the round', 90,
           lambda: (g.q(cmd='press', buttons=CROSS, frames=3), time.sleep(.3)) if g.value(STATE) in (9, 10) else None)
    time.sleep(6)
    for _ in range(10):
        if g.value(STATE) in (3, 4): break
        g.press(START); time.sleep(.5)
        g.q(cmd='press', buttons=START & SELECT, frames=6); time.sleep(1.5)
    to_menu(g)


def scene(out, exe, data, quick, check, mode='practice', rounds=1, renderer='software', wide=False, warmup=False):
    """rounds: loading screens chosen from the same grid (Practice: PLAYER
    SELECT between them). warmup: first a fight with QUICK SELECT off, then
    back to the modes menu (the video's path: its stage stays loaded)."""
    tag = f"{mode}-{'quick-on' if quick else 'quick-off'}{'-after-fight' if warmup else ''}"
    g = Game(out, tag, exe, data, renderer, wide)
    try:
        g.q(cmd='turbo', enabled=1)
        to_menu(g)
        g.q(cmd='turbo', enabled=0)
        if warmup:
            enter(g, 'practice', False)
            fight_then_quit(g)
        enter(g, mode, quick)
        for r in range(1, rounds + 1):
            # The Tag page, the cursor on its first guest (the grid comes back on its own page).
            for _ in range(4):
                if on_tag_page(g): break
                g.press(R2); time.sleep(1.5)
            else:
                raise AssertionError('R2 never opened the Tag page')
            per = g.per_frame()
            g.shot(out / f'{tag}-{r}-grid.png')
            hd, p1, p2 = loading(g, out, f'{tag}-{r}-loading')
            guest = p1 >= GUEST_ID
            print(f'{tag}: loading {r}: fighters {p1} / {p2}, {hd} primitives from the upper half on the loading screen'
                  f' (grid: {per:.1f} a frame)', flush=True)
            copies = hd_copies(data, out / f'{tag}-{r}-loading-upper.bin', (p1, p2))
            print(f'{tag}: loading {r}: HD portrait copies in place (P1, P2): {copies}', flush=True)
            check(all(c is not False for c in copies) and any(c for c in copies),
                  f'{tag}: loading screen {r}: guest portraits from their HD copies ({copies})')
            if r < rounds and mode == 'practice': player_select(g)
            elif r < rounds: break
    finally:
        g.close()


def restore_scene(out, exe, data, check, mode='practice', renderer='software', wide=False):
    """The stage under the copies: QUICK SELECT on, a guest's fight (its stage
    loaded, over (192 p, 768) or not), back to the modes menu, the same
    fighters again: the loading screen writes the copies over that stage
    (state 11) and the same stage, not loaded again, must draw from its own
    upper half again (tekken3_stage_high_vram_disturbed). The upper half
    over the copies' rectangles, two seconds into each round, must match."""
    tag = f'{mode}-restore'
    g = Game(out, tag, exe, data, renderer, wide)
    try:
        g.q(cmd='turbo', enabled=1); to_menu(g); g.q(cmd='turbo', enabled=0)
        dumps, copies = [], []
        for r in (1, 2):
            enter(g, mode, True)
            for _ in range(4):
                if on_tag_page(g): break
                g.press(R2); time.sleep(1.5)
            else:
                raise AssertionError('R2 never opened the Tag page')
            hd, p1, p2 = loading(g, out, f'{tag}-{r}-loading')
            copies.append(hd_copies(data, out / f'{tag}-{r}-loading-upper.bin', (p1, p2)))
            g.wait(lambda: g.value(STATE) == 8 and g.value(0x800ae224, 2) >= 8, 'the round', 60)
            time.sleep(2)
            path = out / f'{tag}-{r}-fight-upper.bin'
            g.q(cmd='high_vram', path=str(path)); g.shot(out / f'{tag}-{r}-fight.png')
            dumps.append(path.read_bytes())
            print(f'{tag}: round {r}: fighters {p1} / {p2}, HD copies on the loading screen {copies[-1]}', flush=True)
            if r == 1:
                for _ in range(10):
                    if g.value(STATE) in (3, 4): break
                    g.press(START); time.sleep(.5)
                    g.q(cmd='press', buttons=START & SELECT, frames=6); time.sleep(1.5)
                to_menu(g)
        rows = range(256, 508)
        diff = sum(dumps[0][(y * 1024) * 2:(y * 1024 + 360) * 2] != dumps[1][(y * 1024) * 2:(y * 1024 + 360) * 2] for y in rows)
        print(f'{tag}: rows of the copy rectangles that differ between the two rounds: {diff} of {len(rows)}', flush=True)
        check(all(c is not False for c in copies[1]) and diff == 0,
              f'{tag}: copies written on the second loading screen ({copies[1]}), the stage upper half the same in both rounds ({diff} rows differ)')
    finally:
        g.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out', type=Path)
    ap.add_argument('--exe', type=Path, default=ROOT / 'build-rel-lite/Tekken_3_Expanded.exe')
    ap.add_argument('--data', type=Path, required=True)
    ap.add_argument('--quick', choices=('on', 'off', 'both'), default='both')
    ap.add_argument('--mode', choices=tuple(LINES), default='practice')
    ap.add_argument('--renderer', choices=('software', 'opengl'), default='software')
    ap.add_argument('--wide', action='store_true', help='16:9 (True Widescreen on)')
    ap.add_argument('--rounds', type=int, default=1)
    ap.add_argument('--warmup', action='store_true', help='a fight with QUICK SELECT off first')
    ap.add_argument('--restore', action='store_true', help='the stage under the copies (restore_scene) instead')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    failed = []
    def check(ok, what):
        print(('ok    ' if ok else 'FAILED ') + what, flush=True)
        if not ok: failed.append(what)
    if a.restore:
        restore_scene(a.out, a.exe.resolve(), a.data, check, a.mode, a.renderer, a.wide)
    else:
      for quick in {'on': [True], 'off': [False], 'both': [False, True]}[a.quick]:
        scene(a.out, a.exe.resolve(), a.data, quick, check, a.mode, a.rounds, a.renderer, a.wide, a.warmup)
    print('OK' if not failed else f'{len(failed)} check(s) failed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
