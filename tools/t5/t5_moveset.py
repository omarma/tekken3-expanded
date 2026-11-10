#!/usr/bin/env python3
"""Tekken 5 (PS2, NTSC-U SLUS-21059) moveset of a fighter, read from a PCSX2
savestate: no Windows tool, no process hook.

    python3 tools/t5/t5_moveset.py <state.p2s | ram.bin | --live> [--player 1|2] [--out file.tsv]

A savestate (.p2s) is a zip whose eeMemory.bin is the 32 MiB main RAM
(zstd-compressed members: Python 3.14's zipfile reads them). The layout
below was read from the public TKMovesets2 sources (Kiloutre, GPL-3;
Structs_t5.h, game_addresses.ini) and checked on the data; this reader is
our own. Player 1 at 0x3A8AD0, players 0x8D0 apart, moveset pointer at
+0x50. Moveset: name strings at +8.. (character, creator, date), alias
table (36 words) at +0x18 + 144, then the table of (address, count) lists at
+0x180: move is the 12th. A move is 76 bytes: name, animation name,
animation, vulnerability, hit level, cancel list, ..., hit conditions (+0x20,
12-byte entries, damage at +4 of the first unconditional one), animation length (+0x24), first / last active frame
(+0x44 / +0x46). A cancel is 24 bytes: command (direction low 16 bits, one
bit each: 2 d/b, 4 d, 8 d/f, 0x10 b, 0x20 N, 0x40 f, 0x80 u/b, 0x100 u,
0x200 u/f; buttons 1..4 in bits 16..19), requirement list (4-byte
condition / parameter pairs, 321 ends it), destination (0x8000 + n: alias
n), window start / end, starting frame. 0x8005 opens a shared group
(entries until 0x8006), 0x8000 is the recovery, 0x8013.. input sequences
(window, count, inputs). 0x8001 / 0x8002 are f,f / b,b, 0x8003 / 0x8004
the side steps.

Also reads Tekken: Dark Resurrection (PSP, ULUS10139), which keeps these
records little-endian with PSP addresses (layout and proofs: tools/psp/layout.py,
TIPS.md section 49 bis): 37 aliases per header table (current ones at +0xAC),
list table at +0x188, requirement lists ended by 330. Source: a 24 MiB RAM
dump from 0x08800000 (ram.bin), or --live: the running PPSSPP, paused for the
read through its debugger (--save-ram keeps the dump).

Output: one line per attack reachable from the stance through unconditional
entries (the first per command wins), through movement states, then strings:
notation, name, first and last active frame, animation length, damage, hit
level.
"""
import argparse, importlib.util, struct, sys, zipfile
from pathlib import Path

PSP_TOOLS = Path(__file__).resolve().parents[1] / 'psp'


def psp_module(name):
    """A module of tools/psp, loaded without putting that folder on sys.path (its names would shadow ours)."""
    spec = importlib.util.spec_from_file_location(f'psp_{name}', PSP_TOOLS / f'{name}.py')
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


DRL = psp_module('layout')

LISTS = DRL.LISTS


class Game:
    """Where a fighter's moveset is, per game; ram holds RAM from address `base`, addresses masked by `mask`."""
    def __init__(s, **kw): s.__dict__.update(kw)


PS2 = Game(name='T5 PS2', p1=0x3a8ad0, psize=0x8d0, motbin=0x50, table=0x180, alias=0x18 + 144, n_alias=36,
           req_end=321, base=0, mask=0x1ffffff, ram_size=32 << 20)
DR = Game(name='DR PSP', p1=DRL.P1, psize=DRL.PSIZE, motbin=DRL.MOTBIN, table=DRL.TABLE, alias=DRL.ALIAS,
          n_alias=DRL.N_ALIAS, req_end=DRL.REQ_END, base=DRL.RAM_BASE, mask=0xffffffff, ram_size=24 << 20)
assert DRL.MOVE_SIZE == 76 and DRL.CANCEL_SIZE == 24 and DRL.REQ_SIZE == 4 and DRL.INPUT_SEQ_BASE == 0x8013

MOVE = '<IIIIII HHhh I hHHH IIII iI HH hH'          # 76 bytes
DIRS = {0x2: 'd/b', 0x4: 'd', 0x8: 'd/f', 0x10: 'b', 0x20: 'N', 0x40: 'f', 0x80: 'u/b', 0x100: 'u', 0x200: 'u/f'}
SPECIAL = {0x8001: 'f,f', 0x8002: 'b,b', 0x8003: 'SS', 0x8004: 'SS'}


def ram_of(state):
    """The 32 MiB RAM of a savestate. Its members are zstd-compressed, which
    zipfile reads from Python 3.14 on; a copy is kept in workspace/t5/ram/ for
    older Pythons (the numpy one of tools/t5/t5_convert.py)."""
    state = Path(state)
    cache = Path(__file__).resolve().parents[2] / 'workspace/t5/ram' / (state.stem + '.bin')
    try:
        with zipfile.ZipFile(state) as z: ram = z.read('eeMemory.bin')
    except NotImplementedError:
        if cache.is_file(): return cache.read_bytes()
        raise SystemExit(f'{state.name}: read it once with Python 3.14 (zstd), e.g. tools/t5/t5_capture.py')
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not cache.is_file() or cache.read_bytes() != ram: cache.write_bytes(ram)
    return ram


def live_ram(save=None):
    """DR's 24 MiB of user RAM, read from the running PPSSPP while its CPU is paused (one coherent frame)."""
    p = psp_module('ppsspp').PPSSPP()
    print(p.title(), file=sys.stderr)
    p.pause()
    try:
        ram = b''.join(p.read(DR.base + o, 0x10000) for o in range(0, DR.ram_size, 0x10000))
    finally:
        p.resume(); p.close()
    if save: Path(save).parent.mkdir(parents=True, exist_ok=True); Path(save).write_bytes(ram)
    return ram


def source(path):
    """(ram, game): PCSX2 savestate, or a raw RAM dump told apart by its size."""
    if path.suffix.lower() == '.p2s': return ram_of(path), PS2
    ram = path.read_bytes()
    game = next((g for g in (PS2, DR) if len(ram) == g.ram_size), None)
    if not game: raise SystemExit(f'{path.name}: {len(ram)} bytes, neither a T5 PS2 (32 MiB) nor a DR PSP (24 MiB) RAM')
    return ram, game


class Moveset:
    def __init__(s, ram, player=0, game=PS2):
        s.ram, s.g = ram, game
        s.mb = s.u32(game.p1 + player * game.psize + game.motbin)
        # Character name: ASCII ('[DEVIL JIN]') or Shift-JIS ('[ポール]' for Paul, both versions).
        s.name = s.cstr(s.u32(s.mb + 8)).encode('latin1').decode('shift_jis', 'replace')
        s.lists = {n: (s.u32(s.mb + game.table + i * 8), s.u32(s.mb + game.table + i * 8 + 4)) for i, n in enumerate(LISTS)}
        s.aliases = [s.u32(s.mb + game.alias + i * 4) for i in range(game.n_alias)]
        a, c = s.lists['move']
        s.moves = []
        for i in range(c):
            f = struct.unpack_from(MOVE, ram, s.off(a) + i * 76)
            s.moves.append(dict(index=i, name=s.cstr(f[0]), hitlevel=f[4], cancel=f[5], anim_len=f[11],
                                first=f[21], last=f[22], damage=s.hit_damage(f[10]) if f[10] else 0))
        # The standing stance: the move alias 1 names.
        s.stance = s.aliases[1]

    def off(s, a): return (a & s.g.mask) - s.g.base
    def u32(s, a): return struct.unpack_from('<I', s.ram, s.off(a))[0]
    def cstr(s, a, n=64):
        a = s.off(a); e = s.ram.find(b'\0', a, a + n); return s.ram[a:e].decode('latin1')
    def resolve(s, m): return s.aliases[m - 0x8000] if 0x8000 <= m < 0x8000 + len(s.aliases) else m

    def cancels(s, addr):
        """(command, requirement list, move), shared groups expanded."""
        for k in range(512):
            cmd, req, mid, ext, ds, de, sf, opt = struct.unpack_from('<IIIIHHHH', s.ram, s.off(addr) + k * 24)
            if cmd == 0x8005:
                yield from s.cancels(s.lists['groupCancel'][0] + mid * 24); continue
            if cmd in (0x8000, 0x8006): return
            yield cmd, req, s.resolve(mid)

    def hit_damage(s, hc):
        """Damage of the default hit condition (12-byte entries: requirement list, damage, reactions):
        the first entry whose requirements are empty, the one Practice shows. Entries before it are
        conditional, e.g. condition 32 (DR 34), parameter 950: 1.5 x the damage (Paul's
        Pl_hadoh03 49 / 33 on PS2)."""
        for k in range(32):
            if s.unconditional(s.u32(hc + k * 12)): return s.u32(hc + k * 12 + 4)
        return s.u32(hc + 4)

    def unconditional(s, req):
        for j in range(16):
            c, p = struct.unpack_from('<HH', s.ram, s.off(req) + j * 4)
            if c == s.g.req_end: return True
            if c: return False
        return False

    @staticmethod
    def one(cmd):
        d, b = cmd & 0xffff, (cmd >> 16) & 0xff
        parts = [n for bit, n in DIRS.items() if d & bit] if d and d < 0x8000 else []
        btn = '+'.join(str(k + 1) for k in range(4) if b >> k & 1)
        text = '|'.join(parts)
        return (text + '+' + btn if text and btn else text or btn) or '-'

    def label(s, cmd):
        low = cmd & 0xffff
        if not cmd >> 16 and low in SPECIAL: return SPECIAL[low]
        if not cmd >> 16 and 0x8013 <= low <= 0x81ff:
            a, c = s.lists['inputSequence']
            i = low - 0x8013
            if 0 <= i < c:
                win, _, n, ia = struct.unpack_from('<BbHI', s.ram, s.off(a) + i * 8)
                return ','.join(s.one(s.u32(ia + j * 4)) for j in range(n))
        return s.one(cmd)

    def usable(s, cmd):
        low = cmd & 0xffff
        return bool(cmd >> 16) or low < 0x8000 or low in SPECIAL or 0x8013 <= low <= 0x81ff

    def walk(s, moves_deep=6, steps_deep=4):
        """{move index: notation}."""
        seen, queue, visited = {}, [(s.stance, '', 0, 0)], {s.stance}
        while queue:
            m, path, steps, hits = queue.pop(0)
            used = set()
            for cmd, req, d in s.cancels(s.moves[m]['cancel']):
                if d >= len(s.moves) or cmd in used or not s.usable(cmd) or not s.unconditional(req): continue
                used.add(cmd)
                mv = s.moves[d]
                note = (path + ', ' if path else '') + s.label(cmd)
                if mv['damage'] or mv['first']:
                    seen.setdefault(d, note)
                    if hits + 1 < moves_deep and d not in visited:
                        visited.add(d); queue.append((d, note, steps, hits + 1))
                elif not hits and steps + 1 < steps_deep and d not in visited:
                    visited.add(d); queue.append((d, note, steps + 1, hits))
        return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('state', type=Path, nargs='?', help='PCSX2 savestate (.p2s), or a T5 PS2 / DR PSP RAM dump')
    ap.add_argument('--live', action='store_true', help='DR: read the running PPSSPP (debugger)')
    ap.add_argument('--save-ram', type=Path, help='with --live: keep the RAM dump there')
    ap.add_argument('--player', type=int, default=1)
    ap.add_argument('--out', type=Path)
    a = ap.parse_args()
    if a.live == bool(a.state): ap.error('give a savestate / RAM dump, or --live')
    ram, game = (live_ram(a.save_ram), DR) if a.live else source(a.state)
    m = Moveset(ram, a.player - 1, game)
    lines = ['notation\tname\tfirst\tlast\tanim\tdamage\thitlevel']
    for d, note in m.walk().items():
        v = m.moves[d]
        lines.append(f"{note}\t{v['name']}\t{v['first']}\t{v['last']}\t{v['anim_len']}\t{v['damage']}\t{v['hitlevel']:08x}")
    text = '\n'.join(lines) + '\n'
    if a.out: a.out.parent.mkdir(parents=True, exist_ok=True); a.out.write_bytes(text.encode())
    else: sys.stdout.buffer.write(text.encode())
    print(f'{game.name}, {m.name}: {len(m.moves)} moves, {len(lines) - 1} reachable attacks', file=sys.stderr)


if __name__ == '__main__':
    main()
