#!/usr/bin/env python3
"""A TTT1 guest as the CPU's fighter in Arcade, without a player.

    python3 tools/ttt1_arcade_cpu.py <guest> [<guest> ...] [--costume 0|1] [--jobs 3]

Player 1 picks Jin on the stock page of the cabinet selector (private save,
slot 7). Once the game has drawn its ten opponents (0x800AFB18, TIPS.md
section 25), the list is rewritten: stage 2 is the fighter whose arena the
guest takes (tools/data/ttt1_characters.json, "arena"), stage 3 the guest.
Stages are won by emptying player 2's life. The two fights share an arena,
so everything the guest brings shows up as a difference:

- the arena the game chose (0x800ADC84, from byte 10 of the fighter's
  record, by 0x8004F3B0);
- the VRAM zone where player 2's lowest texture tiles move (x 960..1023,
  y 0..255; src/tekken3_ttt1_mod.c), kept for inspection: it holds leftovers
  of earlier screens, so whether a fight reads it is told by the GPU
  commands (tools/ttt1_fight_vram_usage.py), not by its content;
- the HUD palettes (rows 504..511), identical in both fights unless the
  guest's texture band reaches them. Two zones differ between any two
  fighters (control run: Heihachi, then Julia, arena 12) and are left out:
  player 2's fighter palettes (x < 256, rows 508..511) and x 833..895,
  rows 504..507.

Captures and report: workspace/ttt1-arcade-cpu/<guest>/. The arena itself
is for the user to judge on the captures.
"""
import argparse, json, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import ttt1_live
from ttt1_live import Session
from ttt1_stage_roster import T3_IDS

WORK = ROOT / 'workspace/ttt1-arcade-cpu'
LIST, STAGE, ARENA = 0x800AFB18, 0x800AFAAC, 0x800ADC84
STATE, PHASE = 0x800AE204, 0x800AE224
P2_LIFE = 0x800AAAB4 + 0x3F4
MOVED_TILES = (960, 0, 64, 256)                   # x, y, w, h
HUD_PALETTES = [(x, 504, 128, 8) for x in range(0, 1024, 128)]
FIGHTER_OWN = ((0, 508, 256, 4), (833, 504, 63, 4))   # x, y, w, h: differ between any two fighters


def hud_differences(a, b):
    """(x, y) of the HUD palette texels that differ, fighter-own zones left out."""
    out = []
    for r, (x0, y0, w, h) in enumerate(HUD_PALETTES):
        for i in range(w * h):
            o = (r * w * h + i) * 2
            if a[o:o + 2] != b[o:o + 2]:
                x, y = x0 + i % w, y0 + i // w
                if not any(fx <= x < fx + fw and fy <= y < fy + fh for fx, fy, fw, fh in FIGHTER_OWN):
                    out.append((x, y))
    return out


def records(s, cid):
    """Arena and the watched VRAM of the fight on screen."""
    x, y, w, h = MOVED_TILES
    tiles = s.vram(x, y, w, 128) + s.vram(x, y + 128, w, h - 128)
    hud = b''.join(s.vram(*r) for r in HUD_PALETTES)
    return dict(arena=s.value(ARENA, 2), p2=s.actor(1)[2], tiles=tiles, hud=hud)


def run(guest, costume, control=None):
    table = json.loads((ROOT / 'tools/data/ttt1_characters.json').read_text())['characters']
    owner = T3_IDS[table[guest]['arena']]
    out = WORK / (guest if control is None else f'{guest}-control-{control}')
    out.mkdir(parents=True, exist_ok=True)
    s = Session(guest=guest, env={'TEKKEN3_GUEST_P2': guest})
    report = dict(guest=guest, costume=costume, owner=owner)
    try:
        # control: a stock fighter in the guest's place, to tell what differs
        # between any two fighters in the arena from what the guest brings.
        cid = s.cid_p2 if control is None else control
        s.wait(lambda: s.value(STATE) == 9 and s.value(0x80118648) == 21, 'The stock selector grid never appeared', 20)
        for _ in range(23):
            if s.value(0x80118668) == 9: break
            s.press(0xff7f)
        s.press(0x7fff)
        s.wait(lambda: s.value(STATE) == 11, 'Loading screen not reached', 15)
        # Entry: fighter, costume, stage number; stage 1 is already loading.
        for stage, fighter in ((1, owner), (2, cid)):
            s.write(LIST + 4 * stage, fighter, 1); s.write(LIST + 4 * stage + 1, costume, 1)
        report['list'] = s.read(LIST, 40).hex()
        seen, t0 = {}, time.monotonic()
        while 2 not in seen:
            if s.process.poll() is not None: raise RuntimeError('the game exited')
            if time.monotonic() - t0 > 300: raise TimeoutError(f'stopped at stage {s.value(STAGE) + 1}')
            state, phase, stage = s.value(STATE), s.value(PHASE, 2), s.value(STAGE)
            if state == 8 and phase >= 6:
                if stage in (1, 2) and stage not in seen:
                    expected = owner if stage == 1 else cid
                    if s.actor(1)[2] == expected:
                        time.sleep(1.5)
                        s.q(cmd='screenshot', path=str(out / f'stage{stage + 1}.png'))
                        seen[stage] = records(s, expected)
                if stage < 2 and (stage == 0 or stage in seen) and s.value(P2_LIFE) > 0xFFFF:
                    s.write(P2_LIFE + 2, 0, 2)
            elif state not in (8, 9, 11):
                s.press(0xfff7)                  # win screens, continue
            time.sleep(.25)
        native, guest_fight = seen[1], seen[2]
        report.update(
            arena_native=native['arena'], arena_guest=guest_fight['arena'],
            tiles_native_used=any(native['tiles']), tiles_changed=native['tiles'] != guest_fight['tiles'],
            hud_same=not hud_differences(native['hud'], guest_fight['hud']))
        (out / 'tiles-native.bin').write_bytes(native['tiles']); (out / 'tiles-guest.bin').write_bytes(guest_fight['tiles'])
        (out / 'hud-native.bin').write_bytes(native['hud']); (out / 'hud-guest.bin').write_bytes(guest_fight['hud'])
        report['ok'] = report['arena_native'] == report['arena_guest'] and report['hud_same']
        if control is not None: report['control'] = control
    except Exception as e:
        report.update(ok=False, error=f'{type(e).__name__}: {e}')
        try: s.q(cmd='screenshot', path=str(out / 'failure.png'))
        except Exception: pass
    finally:
        s.stop()
    (out / 'report.json').write_text(json.dumps(report, indent=1))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('guests', nargs='+')
    ap.add_argument('--costume', type=int, default=0)
    ap.add_argument('--jobs', type=int, default=1)
    ap.add_argument('--control', type=int, help='stock fighter ID in place of the guest (reference run)')
    a = ap.parse_args()
    if len(a.guests) > 1 and a.jobs > 1:
        # One game per process, at most --jobs at once (3 is the machine's limit).
        pending, running = list(a.guests), []
        while pending or running:
            while pending and len(running) < a.jobs:
                g = pending.pop(0)
                running.append(subprocess.Popen([sys.executable, __file__, g, '--costume', str(a.costume)]))
            running = [p for p in running if p.poll() is None]
            time.sleep(1)
    else:
        for g in a.guests:
            r = run(g, a.costume, a.control)
            print(g, 'OK' if r['ok'] else 'ECHEC', {k: v for k, v in r.items() if k not in ('guest', 'list')}, flush=True)
    for g in a.guests:
        path = WORK / g / 'report.json'
        if len(a.guests) > 1 and path.is_file():
            r = json.loads(path.read_text())
            print(f"{g:10} {'OK' if r['ok'] else 'ECHEC':6} arene {r.get('arena_native')}->{r.get('arena_guest')} "
                  f"tuiles deplacees {'oui' if r.get('tiles_changed') else 'non'} "
                  f"HUD {'identique' if r.get('hud_same') else 'DIFFERENT'} {r.get('error', '')}")


if __name__ == '__main__':
    main()
