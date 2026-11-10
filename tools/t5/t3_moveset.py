#!/usr/bin/env python3
"""Tekken 3 native moveset of a fighter, in the same table as
tools/t5/t5_moveset.py, to compare the two games move by move.

    python3 tools/t5/t3_moveset.py --disc paul [--out file.tsv]  # no game run: the disc image alone
    python3 tools/t5/t3_moveset.py --live [--out file.tsv]     # through slot.py: runs the game
    python3 tools/t5/t3_moveset.py --ram workspace/t5/t3-ram.bin [--out file.tsv]

--disc builds the RAM the game would have from the disc image (disc/Tekken
3 (Track 1).bin and disc/SLUS_004.02, tools/bns_tool.py): the executable at
0x80010000, then the fighter's move block (TEKKEN3.BNS entry 280 + key, the
file char_file_queue reads as 0x4A + n) and the shared one (entry 279, 0x49)
relocated as movelist_relocate does (Tekken 3 PS1 decompilation,
t3-ps1/src/combat/8002BFE8.c): offsets made addresses, MoveRec.frames = the
first byte of the animation, damage + the throw damage of its properties
(kind 0xB, move_damage_total), move_table words to record addresses.

--live starts the debug build without a player (tools/test_devil_jin.py
helpers: Practice, plain Jin, the dummy standing), saves the 2 MiB RAM and
player 1's move header next to it (workspace/t5/t3-ram.bin, .json), then
reads them. Only Jin (the stock selector cursor path).

PS1 cancel lists: 12-byte entries (command, condition, parameter,
destination alias, transition, window start, end, starting frame). Command
bits 0..3 = buttons 1..4 (bit 4: any of them), bits 5..13 = the allowed
directions, one per keypad number 1..9; 0xC000 ends a list (recovery),
0xC001 / 0xC002 = f,f / b,b, 0xC00C opens a shared group at 0x80017C78 +
12 * destination with its row count in byte +11 (0xC00D ends it; found at
0x8002DE84). Condition: low byte = whose rule (0 anyone, key + 1 the
fighter), high byte = a state test. The move header (0x800ADC20 + 4 *
player) holds the alias table at +12; a record is 56 bytes (MoveRec of the
decompilation, t3-ps1/d5/t3_types.h): +8 low half = hit level (coded as in
Tekken 5: 0x10F low, 0x217 mid, 0x412 / 0x512 high), +12 cancel list,
+0x14 damage (low half), +24 low byte = frames, +0x2C frames the victim
stays frozen at the impact (hitstun), +45 / +46 first / last active frame,
+0x32 reaction (HitEntry of reaction_alias_table, 0x80010CE8 + 42 * n, or
of reaction_pairs, 0x800174C4 + 2 * n when the top 4 bits are set).
Input sequences 0xC00E.. / 0xC7FF..: input_seq_table_a / _b (0x800954D0,
0x800955CC), each a window then words keypad direction | buttons << 8.
"""
import argparse, json, struct, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'workspace/t5'
GROUPS = 0x80017c78
NUMPAD = {1: 'd/b', 2: 'd', 3: 'd/f', 4: 'b', 5: 'N', 6: 'f', 7: 'u/b', 8: 'u', 9: 'u/f'}
REACTIONS, REACTION_PAIRS = 0x80010ce8, 0x800174c4
SEQ_A, SEQ_B = 0x800954d0, 0x800955cc
# Move keys (actor +0x16), as tools/ttt1/balance.py.
KEYS = {'paul': 0, 'law': 1, 'lei': 2, 'king': 3, 'yoshimitsu': 4, 'nina': 5, 'hwoarang': 6,
        'xiaoyu': 7, 'eddy': 8, 'jin': 9, 'julia': 10, 'kuma': 11, 'bryan': 12, 'heihachi': 13,
        'ogre': 14, 'gunjack': 16, 'anna': 17, 'drb': 18, 'gon': 19}
EXE_BASE, SHARED_AT, OWN_AT = 0x80010000, 0x80140000, 0x80180000


def step(direction, buttons):
    """One step of an input sequence: keypad direction (0: none), buttons bits 0..3 (bit 4: any)."""
    d = NUMPAD.get(direction, '')
    b = ('/' if buttons & 0x10 else '+').join(str(k + 1) for k in range(4) if buttons >> k & 1)
    return (d + '+' + b if d and b else d or b) or 'N'


class Moveset:
    def __init__(s, ram, header, key):
        s.ram, s.key = ram, key
        s.aliases = s.u32(header + 12)

    def u32(s, a): return struct.unpack_from('<I', s.ram, a & 0x1fffff)[0]
    def record(s, alias): return s.u32(s.aliases + alias * 4)
    def fields(s, rec):
        o = rec & 0x1fffff
        v = struct.unpack_from('<14I', s.ram, o)
        return dict(cancel=v[3], damage=v[5] & 0xffff, frames=v[6] & 0xff, first=s.ram[o + 45], last=s.ram[o + 46],
                    level=v[2] & 0xffff, hitstun=s.ram[o + 0x2c], reaction=v[12] >> 16)

    def cancels(s, addr):
        for e in s.entries(addr):
            if e[0] == 0xc000: return
            yield e

    def entries(s, addr):
        """The cancel list, shared groups expanded, its 0xC000 end included."""
        for k in range(256):
            e = struct.unpack_from('<4H4B', s.ram, (addr & 0x1fffff) + k * 12)
            if e[0] == 0xc00c:
                for j in range(e[7]):
                    row = struct.unpack_from('<4H4B', s.ram, ((GROUPS + e[3] * 12) & 0x1fffff) + j * 12)
                    if row[0] == 0xc00d: break
                    yield row
                continue
            yield e
            if e[0] == 0xc000: return

    def recovery(s, rec):
        """First frame the fighter acts again: the window start of the 0xC000 end, where the default
        move's own cancels are tried (fighter_cancel_step); 0 = only at the end of the move."""
        end = [e for e in s.entries(s.fields(rec)['cancel']) if e[0] == 0xc000]
        return end[0][5] if end else 0

    def hit_entry(s, reaction):
        """The 14 reaction moves of a HitEntry (busy0, counter, busy1, busy3, busy2, guard: [crouching,
        standing] each; special_4, special_200) and its 7 push / angle fields."""
        base = REACTION_PAIRS + (reaction & 0xfff) * 2 if reaction & 0xf000 else REACTIONS + reaction * 42
        return struct.unpack_from('<14H7h', s.ram, base & 0x1fffff)

    def text(s, cmd):
        if cmd >= 0xc000:
            seq = s.sequence(cmd)
            if seq: return seq
            return {0xc001: 'f,f', 0xc002: 'b,b'}.get(cmd, f'seq{cmd - 0xc000:x}')
        b, any_, dirs = cmd & 15, cmd & 0x10, (cmd >> 5) & 0x1ff
        d = '|'.join(NUMPAD[k + 1] for k in range(9) if dirs >> k & 1) if dirs and dirs != 0x1ff else ''
        btn = ('/' if any_ else '+').join(str(k + 1) for k in range(4) if b >> k & 1)
        return (d + '+' + btn if d and btn else d or btn) or '-'

    def sequence(s, cmd):
        """Notation of an input sequence (command_match, input_sequence_match), or None."""
        if 0xc00e <= cmd <= 0xc04c: table = SEQ_A + (cmd - 0xc00e) * 4
        elif 0xc7ff <= cmd <= 0xc827: table = SEQ_B + (cmd - 0xc7ff) * 4
        else: return None
        p = s.u32(table)
        if not 0x80000000 <= p < 0x80200000: return None
        words = []
        for k in range(1, 40):
            w = struct.unpack_from('<H', s.ram, (p & 0x1fffff) + k * 2)[0]
            if not w: break
            words.append(w)
        return ','.join(step(w & 15, w >> 8) for w in words) or None

    def unconditional(s, cond):
        # 0x6B: a rule the stock fighters all pass outside Tag (seen on Jin's stance).
        return cond >> 8 == 0 and (cond & 0xff) in (0, s.key + 1, 0x6b)

    def walk(s, start=3, moves_deep=6, steps_deep=4):
        """{alias: (notation, fields)} from the stance (alias 3)."""
        seen, queue, visited = {}, [(s.record(start), '', 0, 0)], set()
        while queue:
            rec, path, steps, hits = queue.pop(0)
            used = set()
            for cmd, cond, param, dest, *_ in s.cancels(s.fields(rec)['cancel']):
                if dest >= 5000 or cmd in used or not s.unconditional(cond): continue
                if cmd >= 0xc000 and cmd not in (0xc001, 0xc002) and not s.sequence(cmd): continue
                used.add(cmd)
                r = s.record(dest); f = s.fields(r)
                note = (path + ', ' if path else '') + s.text(cmd)
                if (f['damage'] or f['first']) and f['damage'] < 0xc000:
                    seen.setdefault(dest, (note, f))
                    if hits + 1 < moves_deep and r not in visited:
                        visited.add(r); queue.append((r, note, steps, hits + 1))
                elif not hits and steps + 1 < steps_deep and r not in visited:
                    visited.add(r); queue.append((r, note, steps + 1, hits))
        return seen


def disc_dir():
    """disc/ of this checkout, else of the main one (a worktree has none)."""
    here = ROOT / 'disc'
    if (here / 'SLUS_004.02').is_file(): return here
    common = subprocess.run(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    main = (ROOT / common).resolve().parent / 'disc'
    if (main / 'SLUS_004.02').is_file(): return main
    raise SystemExit(f'no disc/SLUS_004.02 in {here} or {main}')


def relocate(ram, block, at, shared_at=None):
    """Put a move block (Movelist) at `at` and relocate it as fighter_data_slot_relocate then
    movelist_relocate do; `shared_at`: where the shared block (char_data_ptrs[2]) already is."""
    ram[at & 0x1fffff:(at & 0x1fffff) + len(block)] = block
    o = at & 0x1fffff
    h = list(struct.unpack_from('<14I', ram, o))
    for k in range(1, 14): h[k] = (h[k] + at) & 0xffffffff
    struct.pack_into('<13I', ram, o + 4, *h[1:])
    count = struct.unpack_from('<h', ram, o + 2)[0]
    shared = list(struct.unpack_from('<14I', ram, shared_at & 0x1fffff)) if shared_at else h
    cancels, recs, table, sounds, props, anims = h[1], h[2], h[3], h[4], h[5], h[7]
    for i in range(count):
        e = (recs & 0x1fffff) + i * 56
        a = struct.unpack_from('<I', ram, e)[0]
        a = a + anims if a <= 0x3fffffff else (a + shared[7] + 0xc0000000) & 0xffffffff
        struct.pack_into('<I', ram, e, a)
        ram[e + 0x18] = ram[a & 0x1fffff]
        c = struct.unpack_from('<I', ram, e + 0xc)[0]
        struct.pack_into('<I', ram, e + 0xc, (cancels + c * 12) & 0xffffffff)
        p = struct.unpack_from('<i', ram, e + 0x20)[0]
        if p == -1:
            struct.pack_into('<I', ram, e + 0x20, 0)
        else:
            p = props + p * 4
            struct.pack_into('<I', ram, e + 0x20, p)
            damage = struct.unpack_from('<h', ram, e + 0x14)[0]
            q = p & 0x1fffff
            while struct.unpack_from('<H', ram, q)[0]:
                w = struct.unpack_from('<H', ram, q + 2)[0]
                if w >> 8 == 0xb: damage += w & 0xff        # throw damage (move_damage_total)
                q += 4
            struct.pack_into('<h', ram, e + 0x14, damage)
        snd = struct.unpack_from('<i', ram, e + 0x1c)[0]
        struct.pack_into('<I', ram, e + 0x1c, 0 if snd == -1 else (sounds + snd * 2) & 0xffffffff)
    if shared_at:
        for j in range(0xfb7):
            w = struct.unpack_from('<I', ram, (table & 0x1fffff) + j * 4)[0]
            w = recs + w * 56 if w <= 0x3fffffff else shared[2] + 56 * ((w + 0xc0000000) & 0xffffffff)
            struct.pack_into('<I', ram, (table & 0x1fffff) + j * 4, w & 0xffffffff)
    return at


def disc_ram(name):
    """(2 MiB RAM, move header, key) of a fighter, from the disc image alone."""
    sys.path.insert(0, str(ROOT / 'tools'))
    import bns_tool
    key = KEYS[name]
    disc = disc_dir()
    exe = (disc / 'SLUS_004.02').read_bytes()
    entries, _, _ = bns_tool.load_us_table(disc / 'SLUS_004.02')
    with bns_tool.open_bns_source(disc / 'Tekken 3 (Track 1).bin') as src:
        read = lambda n: src.read_at(entries[n].offset, entries[n].size)
        shared, own = read(279), read(280 + key)
    ram = bytearray(0x200000)
    text = exe[0x800:]
    ram[EXE_BASE & 0x1fffff:(EXE_BASE & 0x1fffff) + len(text)] = text
    relocate(ram, shared, SHARED_AT)
    relocate(ram, own, OWN_AT, SHARED_AT)
    return bytes(ram), OWN_AT, key


def live():
    """RAM of a Practice fight with plain Jin (player 1), no player."""
    sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'psxrecomp/tools')]
    import test_devil_jin as t
    t.PRACTICE = True
    WORK.mkdir(parents=True, exist_ok=True)
    def grab(g):
        time.sleep(2)
        (WORK / 't3-ram.bin').write_bytes(bytes.fromhex(g.q(cmd='read_ram', addr='80000000', len=0x200000)['hex']))
        (WORK / 't3-ram.json').write_text(json.dumps(dict(header=g.value(0x800adc20), key=g.value(t.ACTOR + 0x16, 2))))
    t.case((ROOT / 'build-opt-dbg').resolve(), 't3-moveset', t.SQUARE, then=grab)
    return WORK / 't3-ram.bin'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--disc', choices=sorted(KEYS), help='fighter read from the disc image, no game run')
    ap.add_argument('--live', action='store_true')
    ap.add_argument('--ram', type=Path)
    ap.add_argument('--out', type=Path)
    a = ap.parse_args()
    if a.disc:
        m = Moveset(*disc_ram(a.disc))
    else:
        ram_path = live() if a.live else a.ram
        if not ram_path: raise SystemExit('--disc, --live or --ram')
        info = json.loads(ram_path.with_suffix('.json').read_text())
        m = Moveset(ram_path.read_bytes(), info['header'], info['key'])
    lines = ['notation\talias\tfirst\tlast\tanim\tdamage']
    for d, (note, f) in m.walk().items():
        lines.append(f"{note}\t{d}\t{f['first']}\t{f['last']}\t{f['frames']}\t{f['damage']}")
    text = '\n'.join(lines) + '\n'
    if a.out: a.out.parent.mkdir(parents=True, exist_ok=True); a.out.write_text(text)
    else: sys.stdout.write(text)
    print(f'{len(lines) - 1} reachable attacks', file=sys.stderr)


if __name__ == '__main__':
    main()
