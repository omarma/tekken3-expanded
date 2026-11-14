#!/usr/bin/env python3
"""B156 (GH#203): Yoshimitsu's sword glow follows the costume he wears, not the costume slot.

    python tools/test_b156_yoshimitsu_glow.py --assets <TTT1 catalogue> [--build build-rel-lite]
        [--off] [--ps1] [--cases SPEC]

Practice, Yoshimitsu picked with each key (LP, LK, RP, RK) against Paul, then the two
sides on Yoshimitsu (the clash: the game gives player 2 the other costume slot, his model
follows his key). Reads the colours of the glow's quads of each player (sword_glow_prims
0x8009BC88 + 8 * player: two buffers of 10 POLY_GT4, the lit corners' RGB) in the stance
and checks them against the cabinet's glow of the TTT1 costume drawn (TTT1 set_accessory_flags
bit 8, sword_glow_init 0x80102AF0: LP none, LK blue, RP green, RK red). No glow: the quads'
first corners are zeroed and must stay so (the draw writes them every frame). --off: TEKKEN3_B156=0, the "before": the
slot's colour (Tekken 3's: model 8 green, 9 red) is then the one expected. --ps1: every
native on its PS1 model, Tekken 3's colour of the slot expected (unchanged). Captures and the
results in workspace/b156-yoshimitsu-glow/.
"""
import argparse, json, struct, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_f32_native_models as F
T = F.T

WORK = ROOT / 'workspace/b156-yoshimitsu-glow'
PRIMS = 0x8009bc88
YOSHIMITSU, PAUL = 4, 0
# The cabinet's (buffer 0 bright, buffer 1 dim, as Tekken 3 lays them) by TTT1 variant.
CABINET = {0: None, 1: ((0, 0x14, 0xa0), (0, 0x10, 0x50)),
           2: ((0x20, 0x40, 0), (0x10, 0x28, 0)), 3: ((0x60, 0x28, 0), (0x40, 0x20, 0))}
# Tekken 3's (sword_glow_color_table 0x80019F04) by costume slot (model 8, 9).
T3 = {0: ((24, 48, 24), (12, 30, 12)), 1: ((72, 30, 30), (48, 24, 24))}
NAMES = {0: 'none', 1: 'blue', 2: 'green', 3: 'red'}
# P1 key, P2 (fighter, key): the four keys against Paul, then the clashes (the report's:
# player 1 RP, player 2 LP, both in the punch slot, player 2 given the kick slot, model LP).
CASES = [('LP', None), ('LK', None), ('RP', None), ('RK', None),
         ('RP', ('yoshimitsu', 'LP')), ('LP', ('yoshimitsu', 'LP')), ('LK', ('yoshimitsu', 'RK'))]


def colours(g, p):
    """The set of lit corner colours of each buffer of player p's glow quads."""
    out = []
    for b in range(2):
        prim = g.value(PRIMS + p * 8 + b * 4)
        raw = bytes.fromhex(g.q(cmd='read_ram', addr=f'{prim:08x}', len=0x34 * 10)['hex'])
        seen = set()
        for q in range(10):
            for k in range(4):
                o = q * 0x34 + 4 + k * 12
                rgb = tuple(raw[o:o + 3])
                if any(rgb): seen.add(rgb)
        out.append(sorted(seen))
    return out


def drawn(g, p):
    """Whether player p's glow quads are drawn: their first corners zeroed, read 0.5 s later."""
    corners = [g.value(PRIMS + p * 8 + b * 4) + q * 0x34 + 8 for b in range(2) for q in range(10)]
    for a in corners: g.write(a, 0)
    time.sleep(.5)
    return any(g.value(a) for a in corners)


def run(build, assets, off, ps1, cases):
    env = {'TEKKEN3_TTT1_ASSETS': str(assets), 'TEKKEN3_NATIVE_MOVES': '0',
           'TEKKEN3_TTT1_NATIVE_MODELS': '0' if ps1 else 'all'}
    if off: env['TEKKEN3_B156'] = '0'
    tag = 'ps1' if ps1 else 'before' if off else 'after'
    F.WORK = T.WORK = WORK
    results, ok = {}, True
    g = None

    def boot():
        g = F.Game(build, tag, env)
        F.to_practice(g); time.sleep(.5); F.save(g, 5)
        return g

    def one(g, key, other):
        bit, costume, variant = F.BUTTONS[key]
        name = f'P1-{key}' + (f'-vs-P2-{other[1]}' if other else '-vs-paul')
        g.q(cmd='savestate', op='load', slot=5); time.sleep(1.2)
        F.cursor_to(g, YOSHIMITSU)
        T.route(g, [(4, T.pad(bit)), (20, 0xffff)]); time.sleep(2.5)
        F.cursor_to(g, YOSHIMITSU if other else PAUL, 1)
        dbit = F.BUTTONS[other[1]][0] if other else T.SQ
        g.wait(lambda: g.value(T.STATE) != 9, 'dummy not chosen', 30,
               lambda: (g.q(cmd='press', buttons=T.pad(dbit), frames=4), time.sleep(.8),
                        g.press(T.CROSS), time.sleep(.8)))
        g.wait(lambda: g.value(T.STATE) == 8 and g.value(T.PHASE, 2) >= 6, 'round did not start', 120)
        F.close_menus(g); time.sleep(1.5)
        F.shot(g, name, False)
        r = {}
        sides = [(0, key, None)] + ([(1, other[1], key)] if other else [])
        for p, k, k1 in sides:
            ident = T.actor(g, p)
            slot = ident[0] & 3
            v = (F.clash_variant(k1, k)[0] if k1 else F.BUTTONS[k][2])
            got = colours(g, p)
            want = T3[slot] if (off or ps1) else CABINET[v]
            shown = drawn(g, p)
            good = ident[2] == YOSHIMITSU and shown == (want is not None)
            if want: good &= all(got[b] == [want[b]] for b in range(2))
            r[f'P{p + 1}'] = dict(key=k, slot=slot, variant=v, drawn=shown, got=got,
                                  want=[list(w) for w in want] if want else None, colour=NAMES.get(v), ok=good)
        return r

    try:
        g = boot()
        for key, other in cases:
            name = f'P1-{key}' + (f'-vs-P2-{other[1]}' if other else '-vs-paul')
            for attempt in (1, 2):
                try:
                    results[name] = one(g, key, other); break
                except (AssertionError, RuntimeError) as e:
                    results[name] = {'error': str(e)}
                    g.stop(); g = boot()
            r = results[name]
            good = 'error' not in r and all(s['ok'] for s in r.values())
            ok &= good
            print(name, 'OK' if good else 'FAIL', flush=True)
            for p, s in (r.items() if 'error' not in r else []):
                print(f"   {p} key {s['key']} slot {s['slot']} TTT1 variant {s['variant']} ({s['colour']}): "
                      f"drawn {s['drawn']} got {s['got']} want {s['want']}", flush=True)
            if 'error' in r: print('  ', r['error'])
    finally:
        if g: g.stop()
    (WORK / f'{tag}.json').write_text(json.dumps(results, indent=1) + '\n', encoding='utf-8')
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--assets', type=Path, required=True, help='a TTT1 catalogue with Yoshimitsu-Native-TTT1-*')
    ap.add_argument('--off', action='store_true', help='TEKKEN3_B156=0: the slot colour (before)')
    ap.add_argument('--ps1', action='store_true', help='natives on their PS1 models: Tekken 3 colours')
    ap.add_argument('--cases', help='indices into CASES, comma-separated (default all)')
    a = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    cases = CASES if not a.cases else [CASES[int(i)] for i in a.cases.split(',')]
    sys.exit(0 if run((ROOT / a.build).resolve(), a.assets.resolve(), a.off, a.ps1, cases) else 1)


if __name__ == '__main__':
    main()
