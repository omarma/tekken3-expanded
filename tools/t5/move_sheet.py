#!/usr/bin/env python3
"""Balance sheet of a fighter, move by move: Dark Resurrection (PSP) against
the native Tekken 3 moveset and the TTT1 moveset converted for Tekken 3.

    python tools/t5/move_sheet.py paul [--out workspace/dr-a1] [--sdtekken file.tsv]
    python tools/t5/move_sheet.py paul --measured workspace/dr-a1/measure/paul.json

Sources, nothing captured: DR from the ISO (tools/psp/dr_iso.py, the moveset
relocated as the game does, read by tools/t5/t5_moveset.py); Tekken 3 from the
disc image (tools/t5/t3_moveset.py --disc); TTT1 from the converted packs of
tools/ttt1/moves.py (<Name>-TTT1-combat.jmv / -tables.jst of the TTT1 import,
workspace/ttt1-import/roster of the main checkout).

Per move: hit level, damage, first and last active frame, total length, the
frame the attacker acts again, and the frame advantage on block, on hit and on
counter hit, computed from the data:

    advantage = (frame the victim's reaction frees it + frames frozen at the impact)
                - (frame the attacker frees itself - first active frame)

A fighter frees itself at the window start of its move's end entry (DR 0x8000,
Tekken 3 0xC000: from there the default move's own cancels are tried,
fighter_cancel_step of the T3 PS1 decompilation), else at the end of the move.
The reaction is the move the hit condition / HitEntry gives the victim:
standing block (crouching block for a low), standing hit, counter hit. Tekken 3
freezes the victim MoveRec.hitstun frames at the impact (hit_contact_check,
fighter_move_advance), not the attacker. A reaction that does not end in the
standing or crouching stance (knockdown, launch, crumple) gives no number: its
name is kept. Checked on DR against sdtekken.com's frame data (--sdtekken) and
on Tekken 3 / TTT1 against the game (--measured, tools/t5/move_measure.py).

Moves are matched by command: every unconditional cancel reachable from the
stance (hits up to 6 deep, up to 3 movement steps first), one key per allowed
direction, the first entry of a list winning as in the game. Rows group the
keys that lead to the same moves in the three games; the shortest key names
the row. Output in --out: dr-<name>.tsv, t3-<name>.tsv, ttt1-<name>.tsv (one
row per move, all its keys), sheet-<name>.tsv and sheet-<name>.md.
"""
import argparse, csv, json, re, struct, subprocess, sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(HERE.parent / 'psp')]
import t5_moveset as T5
import t3_moveset as T3

# Character names: DR (dr_iso_characters.json), Tekken 3 key, TTT1 pack name.
FIGHTERS = {'paul': ('Paul', 'paul', 'Paul'), 'jin': ('Jin', 'jin', 'Jin'), 'law': ('Marshall Law', 'law', 'Law'),
            'lei': ('Lei', 'lei', 'Lei'), 'king': ('King', 'king', 'King'), 'nina': ('Nina', 'nina', 'Nina'),
            'yoshimitsu': ('Yoshimitsu', 'yoshimitsu', 'Yoshimitsu'), 'hwoarang': ('Hwoarang', 'hwoarang', 'Hwoarang'),
            'xiaoyu': ('Xiaoyu', 'xiaoyu', 'Xiaoyu'), 'eddy': ('Eddy', 'eddy', 'Eddy'), 'julia': ('Julia', 'julia', 'Julia'),
            'bryan': ('Bryan', 'bryan', 'Bryan'), 'heihachi': ('Heihachi', 'heihachi', 'Heihachi'), 'anna': ('Anna', 'anna', 'Anna'),
            # A DR character, no native: Tekken 3's Jin for the T3 column, the easter egg's pack (Jin TTT1 with
            # Devil's moves grafted, tools/ttt1_devil_jin_moves.py) for the TTT1 one and as the DR pack's base.
            'deviljin': ('Devil Jin', 'jin', 'DevilJin')}
LEVELS = {0x10f: 'bas', 0x217: 'milieu', 0x412: 'haut', 0x512: 'haut', 0x41f: 'milieu spécial', 0x31f: 'milieu spécial', 0x607: 'imparable',
          0x707: 'imparable'}
MAX_HITS, MAX_STEPS = 6, 3
# DR keys written another way, per fighter: Jin's crouch dash (f, N, d, d/f in DR, the motion Tekken 3
# has too) is reached by the paths only from Mental Alertness 2 (b+1) then d/f, its moves named
# 'b+1, d/f, 1'... for what is f,N,d,d/f then 1.
# Jin's Complicated Wire is stored N,d/f,N,d/f+2+4 from the walk back; DR takes d, d/b, b+1+3. His Evil Intent
# (Jz_karate01, b, f+2, 1, 2 in the wiki's list, written N,b,N,f+2 in Tekken 3 and TTT1) reads 3+4,N,N+1+2.
# Paul's Push Away (Thrmv_B2_00, f, f+1+2: DR's Command List demo 68) reads 1,N,N+2,N,N+4,N,N+3,N,N+1+2+3 (the
# "chain throw" no pad brought out); Tekken 3 and TTT1 write it N,f,N,f+1+2.
# Devil Jin's sequences read the same way: N,f,d,d/b+1 is the b, f+2 of his Laser Cannon (b, f+2, 1, 2, written
# N,b,N,f+2 in Tekken 3 and TTT1, where Jin has it too); b,d,d/f,f+1+2 (Thrmv_B2_00) his Stonehead, f, f+1+2
# (N,f,N,f+1+2 there: the DR take of f,f+1+2 played it); N,f,d+1 (Thrmv_B2_01) the half circle of the demo 91,
# f, b, d/b, d, d/f, f+1+2 (not yet seen in DR: too long a motion for the bench's wall clock).
RENAME = {'paul': (('1,N,N+2,N,N+4,N,N+3,N,N+1+2+3', 'N,f,N,f+1+2'),),
          'jin': (('b+1, d/f, ', 'f,N,d,d/f, '), ('b, N,d/f,N,d/f+2+4', 'd,d/b,b+1+3'), ('3+4,N,N+1+2', 'N,b,N,f+2')),
          'deviljin': (('N,f,d,d/b+1', 'N,b,N,f+2'), ('b,d,d/f,f+1+2', 'N,f,N,f+1+2'), ('N,f,d+1', 'f,b,d/b,d,d/f,f+1+2'),
                       ('b, N,d/f,N,d/f+2+4', 'd,d/b,b+1+3'))}
# DR moves entered only by a fighter played by a person (condition 151 parameter 0, dr_pack.DR_PLAYED), read
# as unconditional: Jin's u/f+2 (Jz_yokerp) and u+2's jump (sJUMP_00H, then its punch Co_jprp03H), both
# played in DR (2026-10-31). Not every 151 entry: his plain jumps are 151 too, and taking them remapped his
# crouch-dash moves.
PLAYED = {'Jin': ('Jz_yokerp', 'sJUMP_00H')}
# Moveset the Tekken 3 / TTT1 reactions are numbered and read in. None: the attacker's own, which is
# how the game's records are labelled in move_measure.py (the 9 first measures: same numbers as Paul's
# table, the dummy being Jin; Jin's file maps some of them elsewhere, e.g. 2250 to his move 4).
DEFENDER = None


def level_name(v):
    return LEVELS.get(v & 0xffff, f'0x{v & 0xffff:x}')


def expand(text):
    """'d/b|d+3' -> ['d/b+3', 'd+3'] ; 'N+1' -> ['1']."""
    out = []
    head, plus, tail = text.partition('+')
    dirs = head.split('|') if '|' in head or head in T3.NUMPAD.values() else None
    if dirs and plus: out = [d + '+' + tail for d in dirs]
    elif dirs: out = dirs
    else: out = [text]
    return [o[2:] if o.startswith('N+') else o for o in out]


def paths(start, links, is_attack, steps=MAX_STEPS, hits=MAX_HITS):
    """{key: move}: every command path from the stance. links(move) -> [(text, move)] in list order.
    Level by level: a move reached by several keys of one level goes on under its simplest one
    (Paul's jab is 1 and 1+2: its follow-ups are named 1, 4 and not 1+2, 4)."""
    seen, level, visited = {}, [(start, '', 0, 0)], {start}
    while level:
        best = {}
        for mv, path, st, h in level:
            for text, dest in links(mv):
                attack = is_attack(dest)
                if not attack and h: continue
                for k in expand(text):
                    key = (path + ', ' if path else '') + k
                    if key in seen: continue
                    seen[key] = dest
                    nxt = (st, h + 1) if attack else (st + 1, h)
                    if dest in visited or nxt[1] >= hits or nxt[0] >= steps: continue
                    if dest not in best or keyorder(key) < keyorder(best[dest][0]): best[dest] = (key, *nxt)
        visited.update(best)
        level = [(dest, key, st, h) for dest, (key, st, h) in best.items()]
    return {k: v for k, v in seen.items() if is_attack(v)}


def length(step, mv, steps=4):
    """Total length of a move and of the records its end entry chains to, until a stance."""
    t = 0
    for _ in range(steps):
        free, n, nxt, neutral = step(mv)
        t += n
        if neutral or nxt is None: return t
        mv = nxt
    return t


def chain(step, mv, steps=4):
    """(frames until the fighter is free, True when that ends in a stance) from the start of `mv`,
    following the moves its end entry chains to (a Tekken 3 move is often two records: Paul's f+4,
    12 frames, then 34 of recovery). step(mv) -> (free frame, length, next move or None, ends in a
    stance). Switching at the end of a move costs its length."""
    t = 0
    for _ in range(steps):
        free, length, nxt, neutral = step(mv)
        if neutral: return t + free, True
        if nxt is None: return t + length, False
        t += length; mv = nxt
    return t, False


def advantage(free_react, freeze, free_attack, first):
    if free_react is None: return None
    return free_react + freeze - (free_attack - first)


CROUCH = 'crouch'          # a step's "ends in a stance" when that stance is the crouch


def back(step, mv, steps=4):
    """Frames until a move or reaction (and the records it chains to) is back in a stance, None when
    it does not end in one. Ending crouched, it leaves at its end window: the crouch's own cancels
    (down released: stand up, move 65) are open at once (measured: Paul's d+2 leaves 354 at its
    frame 31, the window, not 39, its length). Measured exceptions: the dummy hit by a low (2352)
    plays the reaction to its end."""
    t = 0
    for _ in range(steps):
        free, n, nxt, neutral = step(mv)
        if neutral: return t + (free if neutral == CROUCH else n)
        t += n
        if nxt is None: return None
        mv = nxt
    return None


def neutral_advantage(back_react, freeze, back_attack, first):
    """Advantage when both are back in a stance (what move_measure.py measures)."""
    return None if back_react is None or back_attack is None else back_react + freeze - (back_attack - first)


def reaction(step, mv):
    free, neutral = chain(step, mv)
    return free if neutral else None


# ---------------------------------------------------------------- Dark Resurrection

class DR:
    game = 'DR'
    RX = '<7I6H2IH15H'          # Reactions (Structs_t5.h): pushbacks, directions, vertical push, 15 moves
    BLOCK, CROUCH_BLOCK, HIT, CH = 11, 12, 1, 3

    def __init__(s, name):
        import dr_iso as D
        mot = D.moveset_from_iso(D.Disc(D.ISO), name, D.H1, D.ANIMS1, D.COMMON1)
        s.ram = D.fake_ram(mot, D.H1)
        s.m = m = T5.Moveset(s.ram, 0, T5.DR)
        a = m.lists['move'][0]
        s.raw = [struct.unpack_from(T5.MOVE, s.ram, m.off(a) + i * 76) for i in range(len(m.moves))]
        s.start = m.stance
        s.played_moves = PLAYED.get(name, ())

    def played(s, req, d):
        """An entry into one of PLAYED's moves whose only condition is 151 0 (330 ends the list)."""
        if not req or s.m.moves[d]['name'] not in s.played_moves: return False
        conds = []
        for j in range(8):
            c, p = struct.unpack_from('<HH', s.ram, s.m.off(req) + j * 4)
            if c == 330: break
            if c or p: conds.append((c, p))
        return conds == [(151, 0)]

    def name(s, i): return s.m.moves[i]['name']
    def is_attack(s, i): return bool(s.m.moves[i]['damage'] or s.m.moves[i]['first'])

    def links(s, i):
        out = []
        for cmd, req, d in s.m.cancels(s.m.moves[i]['cancel']):
            if d < len(s.m.moves) and s.m.usable(cmd) and (s.m.unconditional(req) or s.played(req, d)):
                out.append((s.m.label(cmd).replace(' ', ''), d))
        if not out and not s.is_attack(i):
            d = s.prelude_of(i)
            if d is not None: out.append(('-', d))
        return out

    def prelude_of(s, i):
        """The attack a move without a hit plays at its end and nothing else (its list only its 0x8000
        entry): Jin's u+3 is Co_jplk00, 14 frames of take-off, then Jz_spinlk, the Spinning High Kick."""
        cmd, req, mid = struct.unpack_from('<III', s.ram, s.m.off(s.raw[i][5]))
        d = s.m.resolve(mid)
        return d if cmd == 0x8000 and d < len(s.m.moves) and s.is_attack(d) else None

    def neutral(s, i):
        n = s.name(i) if i is not None and i < len(s.m.moves) else ''
        return i == s.m.stance or 'cKAM00' in n or 'sKAM00' in n

    def step(s, i):
        """Its 0x8000 entry: from its window start the default move's cancels are open."""
        length = s.m.moves[i]['anim_len']
        c = s.raw[i][5]
        for k in range(128):
            cmd, req, mid, ext, ds, de, sf, opt = struct.unpack_from('<IIIIHHHH', s.ram, s.m.off(c) + k * 24)
            if cmd == 0x8000:
                dest = s.m.resolve(mid)
                nxt = dest if dest < len(s.m.moves) and not s.is_attack(dest) else None
                return ds or length, length, nxt, CROUCH if s.neutral(dest) and 'cKAM00' in s.name(dest) else s.neutral(dest)
        return length, length, None, False

    def reactions(s, i):
        hc = s.raw[i][10]
        if not hc: return None
        for k in range(32):
            if s.m.unconditional(s.m.u32(hc + k * 12)): break
        v = struct.unpack_from(s.RX, s.ram, s.m.off(s.m.u32(hc + k * 12 + 8)))
        return v[16:]

    def row(s, i):
        mv = s.m.moves[i]
        free, _ = chain(s.step, i)
        r = dict(game='DR', id=i, name=mv['name'], level=level_name(mv['hitlevel']), level_raw=mv['hitlevel'] & 0xffff,
                 damage=mv['damage'], first=mv['first'], last=mv['last'], total=length(s.step, i), back=back(s.step, i), free=free, freeze=0,
                 throw=mv['damage'] >= 16384)
        ids = s.reactions(i)
        if ids and not r['throw'] and mv['first']:
            low = (mv['hitlevel'] & 0xff) == 0x0f
            for label, j in (('block', s.CROUCH_BLOCK if low else s.BLOCK), ('hit', s.HIT), ('ch', s.CH)):
                rx = ids[j]
                if rx >= len(s.m.moves): continue
                r[label + '_rx'] = s.name(rx)
                r[label] = advantage(reaction(s.step, rx), 0, free, mv['first'])
                r[label + '_n'] = neutral_advantage(back(s.step, rx), 0, r['back'], mv['first'])
        return r


# ---------------------------------------------------------------- Tekken 3 (disc)

class Native:
    game = 'T3'
    STANDING_BLOCK, CROUCHING_BLOCK, HIT, CH = 10, 11, 0, 2     # HitEntry: [0] standing, [1] crouching
    NEUTRAL = (3, 40)                                         # standing and crouching stance

    def __init__(s, key, defender=DEFENDER):
        s.m = T3.Moveset(*T3.disc_ram(key))
        # The reactions are the victim's moves, by number in its own table: the measured dummy's.
        s.dm = s.m if defender in (None, key) else T3.Moveset(*T3.disc_ram(defender))
        s.start = s.m.record(3)
        # A record has several move numbers (Paul: 2 = 296, b+2 = 308): it is named by the smallest,
        # as tools/t5/move_measure.py names the records it sees in game.
        s.number, s.dnumber = {}, {}
        for n in range(0xfb7):
            s.number.setdefault(s.m.record(n), n); s.dnumber.setdefault(s.dm.record(n), n)

    def name(s, rec): return f'{s.number.get(rec, 0)}'

    def defender_step(s, rec):
        """native_step on the victim's moveset."""
        f = s.dm.fields(rec)
        e = [x for x in s.dm.entries(f['cancel']) if x[0] == 0xc000]
        if not e: return f['frames'], f['frames'], None, False
        dest = e[0][3]
        r = s.dm.record(dest) if dest < 5000 else None
        nxt = r if r is not None and not s.dm.fields(r)['first'] else None
        return e[0][5] or f['frames'], f['frames'], nxt, CROUCH if dest == 40 else dest in s.NEUTRAL

    def react(s, label, number, r, freeze, free, first):
        """The reaction columns of a row, the victim's move `number`."""
        rec = s.dm.record(number)
        r[label + '_rx'] = str(s.dnumber.get(rec, number))
        r[label] = advantage(reaction(s.defender_step, rec), freeze, free, first)
        r[label + '_n'] = neutral_advantage(back(s.defender_step, rec), freeze, r['back'], first)

    def is_attack(s, rec):
        f = s.m.fields(rec)
        return bool((f['damage'] or f['first']) and f['damage'] < 0xc000)

    def links(s, rec):
        out = []
        for cmd, cond, param, dest, *_ in s.m.cancels(s.m.fields(rec)['cancel']):
            if dest >= 5000 or not s.m.unconditional(cond): continue
            if cmd >= 0xc000 and cmd not in (0xc001, 0xc002) and not s.m.sequence(cmd): continue
            out.append((s.m.text(cmd).replace(' ', ''), s.m.record(dest)))
        return out

    def native_step(s, rec):
        """Its 0xC000 entry: from frame_min the default move's cancels are tried (fighter_cancel_step);
        at the end of the move the fighter switches to that default move."""
        f = s.m.fields(rec)
        e = [x for x in s.m.entries(f['cancel']) if x[0] == 0xc000]
        if not e: return f['frames'], f['frames'], None, False
        dest = e[0][3]
        nxt = s.m.record(dest) if dest < 5000 and not s.is_attack(s.m.record(dest)) else None
        return e[0][5] or f['frames'], f['frames'], nxt, CROUCH if dest == 40 else dest in s.NEUTRAL

    step = native_step

    def row(s, rec):
        f = s.m.fields(rec)
        free, _ = chain(s.step, rec)
        throw = bool(f['damage'] & 0x4000)
        r = dict(game=s.game, id=s.number.get(rec, rec), name=s.name(rec), level=level_name(f['level']),
                 level_raw=f['level'], damage=f['damage'] & 0x3fff, first=f['first'], last=f['last'],
                 total=length(s.step, rec), back=back(s.step, rec), free=free, freeze=f['hitstun'], throw=throw)
        he = s.m.hit_entry(f['reaction'])
        if he and f['first'] and not throw:
            low = (f['level'] & 0xff) == 0x0f
            for label, j in (('block', s.CROUCHING_BLOCK if low else s.STANDING_BLOCK), ('hit', s.HIT), ('ch', s.CH)):
                s.react(label, he[j], r, f['hitstun'], free, f['first'])
        return r


# ---------------------------------------------------------------- TTT1 pack (Tekken 3 runtime)

class TTT1(Native):
    game = 'TTT1'
    BASE_ID = 8192

    def __init__(s, key, pack_dir, name):
        super().__init__(key)              # the defender: reaction moves are the native ones
        b = (pack_dir / f'{name}-TTT1-combat.jmv').read_bytes()
        t = (pack_dir / f'{name}-TTT1-tables.jst').read_bytes()
        magic, ver, size, s.count, s.neutral_index, ro, rc, rb = struct.unpack_from('<8I', b, 0)
        s.pack, s.tables, s.records_at = b, t, rb
        s.rx_rows = struct.unpack_from('<I', t, 12)[0]
        p = ro + rc * 4
        n = struct.unpack_from('<I', b, p)[0]; p += 4
        s.patterns = {}
        for _ in range(n):
            c, l = struct.unpack_from('<HH', b, p)
            s.patterns[c] = struct.unpack_from(f'<{l}H', b, p + 4); p += 4 + 2 * l
        s.alia = {}
        o = 32 + s.rx_rows * 42 + struct.unpack_from('<I', t, 16)[0] + struct.unpack_from('<I', t, 20)[0] * 4
        while o + 8 <= len(t):
            tag, ln = t[o:o + 4], struct.unpack_from('<I', t, o + 4)[0]
            if tag == b'ALIA':
                for k in range(ln // 4):
                    native, target = struct.unpack_from('<HH', t, o + 8 + k * 4)
                    s.alia[native] = target
            o += 8 + ln
        s.start = s.neutral_index

    def rec(s, i): return struct.unpack_from('<14I', s.pack, s.records_at + i * 56)
    def meta(s, i): return struct.unpack_from('<4I', s.pack, 32 + i * 16)
    def byte(s, i, k): return s.pack[s.records_at + i * 56 + k]

    def resolve(s, dest):
        """Pack record index of a destination, or None (a native move)."""
        if s.BASE_ID <= dest < s.BASE_ID + s.count: return dest - s.BASE_ID
        t = s.alia.get(dest)
        if t is not None and s.BASE_ID <= t < s.BASE_ID + s.count: return t - s.BASE_ID
        return None

    def name(s, i): return f'{s.meta(i)[1]:08x}'

    def fields(s, i):
        v = s.rec(i)
        return dict(cancel=v[3], damage=v[5] & 0xffff, frames=v[6] & 0xff, first=s.byte(i, 45),
                    last=s.byte(i, 46), level=v[2] & 0xffff, hitstun=s.byte(i, 0x2c), reaction=v[12] >> 16)

    def is_attack(s, i):
        f = s.fields(i)
        return bool((f['damage'] or f['first']) and f['damage'] < 0xc000)

    def entries(s, i):
        v = s.rec(i)
        return [struct.unpack_from('<4H4B', s.pack, v[3] + k * 12) for k in range(s.meta(i)[3])]

    def text(s, cmd):
        if cmd >= 0xe000:
            words = s.patterns.get(cmd)
            return ','.join(T3.step(w & 15, w >> 8) for w in words[1:-1]) if words else None
        if cmd >= 0xc000: return {0xc001: 'f,f', 0xc002: 'b,b'}.get(cmd)
        return s.m.text(cmd)

    def links(s, i):
        out = []
        for cmd, cond, param, dest, *_ in s.entries(i):
            if cmd == 0xc000 or cond >> 8: continue
            t, d = s.text(cmd), s.resolve(dest)
            if t and d is not None: out.append((t.replace(' ', ''), d))
        return out

    def neutral_dest(s, dest):
        """A native stance, or the pack's own standing / crouching stance (what ALIA maps 3 and 40 to)."""
        return dest in s.NEUTRAL or s.resolve(dest) in {s.neutral_index} | {s.resolve(n) for n in s.NEUTRAL}

    def step(s, i):
        f = s.fields(i)
        e = [x for x in s.entries(i) if x[0] == 0xc000]
        if not e: return f['frames'], f['frames'], None, False
        dest = e[0][3]
        d = s.resolve(dest)
        nxt = d if d is not None and not s.is_attack(d) else None
        return e[0][5] or f['frames'], f['frames'], nxt, CROUCH if s.resolve(dest) == s.resolve(40) or dest == 40 else s.neutral_dest(dest)

    def hit_entry_of(s, i):
        r = s.fields(i)['reaction']
        if r >= s.rx_rows: return None
        return struct.unpack_from('<14H7h', s.tables, 32 + r * 42)

    def row(s, i):
        f = s.fields(i)
        free, _ = chain(s.step, i)
        throw = bool(f['damage'] & 0x4000)
        r = dict(game='TTT1', id=i, name=s.name(i), level=level_name(f['level']), level_raw=f['level'],
                 damage=f['damage'] & 0x3fff, first=f['first'], last=f['last'], total=length(s.step, i), back=back(s.step, i), free=free,
                 freeze=f['hitstun'], throw=throw)
        he = s.hit_entry_of(i)
        if he and f['first'] and not throw:
            low = (f['level'] & 0xff) == 0x0f
            for label, j in (('block', s.CROUCHING_BLOCK if low else s.STANDING_BLOCK), ('hit', s.HIT), ('ch', s.CH)):
                target = he[j]
                d = s.resolve(target) if target >= s.BASE_ID else None
                if d is None:
                    s.react(label, target, r, f['hitstun'], free, f['first']); continue
                # A reaction of the pack: the victim plays it from the pack (the runtime's copy).
                r[label + '_n'] = neutral_advantage(back(s.step, d), f['hitstun'], r['back'], f['first'])
                r[label + '_rx'] = f'p{d}'
                r[label] = advantage(reaction(s.step, d), f['hitstun'], free, f['first'])
        return r


# ---------------------------------------------------------------- the sheet

COLUMNS = ['level', 'damage', 'first', 'last', 'total', 'free', 'freeze', 'block', 'hit', 'ch']


def collect(src):
    keys = paths(src.start, src.links, src.is_attack)
    rows, by_move = {}, defaultdict(list)
    for k, mv in keys.items(): by_move[mv].append(k)
    for mv, ks in by_move.items():
        r = src.row(mv)
        r['keys'] = sorted(ks, key=keyorder)
        rows[mv] = r
    return keys, rows


def keyorder(k):
    return (k.count(','), k.count('+'), len(k), k)


def fmt(v):
    if v is None: return ''
    if isinstance(v, int) and not isinstance(v, bool): return f'{v:+d}' if v and False else str(v)
    return str(v)


def adv(v):
    return '' if v is None else f'{v:+d}'


def cell(r, c):
    if r is None: return ''
    if c == 'damage' and r.get('throw'): return 'prise'
    v = r.get(c)
    if c in ('block', 'hit', 'ch'):
        return adv(v) if v is not None else (('(' + r[c + '_rx'] + ')') if r.get(c + '_rx') else '')
    return '' if v is None else str(v)


def compare(a, b):
    """Fields of b that differ from a (None: b absent)."""
    if a is None or b is None: return None
    return [c for c in ('level', 'damage', 'first', 'block', 'hit', 'ch') if a.get(c) != b.get(c)]


def write_game(path, rows):
    cols = ['keys', 'name', 'id'] + COLUMNS + ['block_rx', 'hit_rx', 'ch_rx']
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, delimiter='\t', lineterminator='\n')
        w.writerow(['notation'] + cols[1:])
        for r in sorted(rows.values(), key=lambda r: keyorder(r['keys'][0])):
            w.writerow([' / '.join(r['keys'][:6])] + [r.get(c, '') if c not in ('block', 'hit', 'ch') else adv(r.get(c)) for c in cols[1:]])


def sheet(name, out, pack_dir, sdtekken=None, measured=None):
    dr_name, key, pack_name = FIGHTERS[name]
    srcs = [DR(dr_name), Native(key), TTT1(key, pack_dir, pack_name)]
    data = []
    for src in srcs:
        keys, rows = collect(src)
        if src is srcs[0] and name in RENAME:
            def renamed(k):
                # At the start of the key or after a step (f, N,f,d+1: Stonehead from the walk).
                for old, new in RENAME[name]:
                    if k.startswith(old): return new + k[len(old):]
                    if f', {old}' in k: return k.replace(f', {old}', f', {new}', 1)
                return k
            keys = {renamed(k): v for k, v in keys.items()}
            for r in rows.values(): r['keys'] = sorted({renamed(k) for k in r['keys']}, key=keyorder)
        data.append((keys, rows))
        write_game(out / f'{src.game.lower()}-{name}.tsv', rows)
        print(f'{src.game}: {len(rows)} attaques, {len(keys)} commandes', file=sys.stderr)
    groups = defaultdict(list)
    for k in set().union(*(d[0] for d in data)):
        groups[tuple(d[0].get(k) for d in data)].append(k)
    lines = []
    for moves, ks in groups.items():
        ks.sort(key=keyorder)
        rows = [data[g][1].get(mv) if mv is not None else None for g, mv in enumerate(moves)]
        lines.append((ks, rows))
    # A move reached by several groups: keep the group whose key is shortest for it, mark the rest.
    lines.sort(key=lambda l: keyorder(l[0][0]))
    first_seen = defaultdict(int)
    out_rows = []
    for ks, rows in lines:
        sig = tuple((r['game'], r['id']) for r in rows if r)
        dup = all(first_seen[x] for x in sig)
        for x in sig: first_seen[x] += 1
        if dup: continue
        dr, t3, tt = rows
        # A command that only repeats another one's move (Tekken 3 b+3 = 3) is an alias there.
        alias = [r is not None and keyorder(r['keys'][0]) < keyorder(ks[0]) for r in rows]
        own = [r if r is not None and not a else None for r, a in zip(rows, alias)]
        ref = own[1] or own[2]
        if own[0] and not ref: status = 'nouveau dans DR'
        elif not own[0] and ref: status = 'absent de DR' if not dr else 'absent de DR (DR : = ' + dr['keys'][0] + ')'
        elif not own[0]: continue
        else:
            diff = compare(ref, own[0])
            same_move = (ref['level'] == own[0]['level'] and abs(ref['first'] - own[0]['first']) <= 3
                         and abs(ref['total'] - own[0]['total']) <= 5)
            status = 'identique' if not diff else ('modifié : ' if same_move else 'remplacé : ') + ', '.join(diff)
        notes = [f"{g} = {r['keys'][0]}" for g, r, a in zip(('DR', 'T3', 'TTT1'), rows, alias) if r is not None and a]
        out_rows.append(dict(command=ks[0], other=ks[1:4], status=status, notes=notes, dr=dr, t3=t3, ttt1=tt,
                             alias=alias))
    out_rows = pair_changed_commands(out_rows)
    if sdtekken: check_sdtekken(out_rows, sdtekken, out / f'sdtekken-{name}.tsv')
    # The stand-up from the crouch (move 65) is free too (its cancels are open), in both games.
    rise = {'t3': {'65'}, 'ttt1': {'65', f'p{srcs[2].resolve(65)}'}}
    if measured: check_measured(out_rows, measured, out / f'measured-{name}.tsv', rise)
    write_sheet(out_rows, out / f'sheet-{name}.tsv', out / f'sheet-{name}.md', name)
    return out_rows


def signature(r):
    return None if r is None or r.get('throw') else (r['level'], r['damage'], r['first'], r['total'])


def last_buttons(r):
    """The buttons of the last step of each of a move's commands ('d, f, 3' -> '3'), steps without
    input ('-') skipped."""
    out = set()
    for k in r['keys'] if r else ():
        for step in reversed([x.strip() for x in k.split(',')]):
            if step in ('', '-', 'N'): continue
            b = step.split('+')
            if b[0] in T3.NUMPAD.values() or '|' in b[0]: b = b[1:]
            if b: out.add('+'.join(b)); break
    return out


def pair_changed_commands(rows):
    """A DR move that is new on its command, and a Tekken 3 / TTT1 move missing from DR on another
    command, with the same level, damage, first active frame and length: the same move, its
    command written another way (Paul's while-standing moves: DR d, f, 3 ; Tekken 3 u, u+3). The
    last buttons stay the same: Jin's 1+2+3 (a jab DR also gives 1+2+3) is not f,f, 2, 1, 2's last
    2, nor 3+4,N,N+1+2 the N,b,N,f+2 of Tekken 3."""
    new = [r for r in rows if r['status'] == 'nouveau dans DR']
    missing = [r for r in rows if r['status'].startswith('absent de DR')]
    out, used = [], set()
    for r in new:
        sig = signature(r['dr'])
        match = next((m for m in missing if id(m) not in used and sig and
                      sig in (signature(m['t3']), signature(m['ttt1'])) and
                      last_buttons(r['dr']) & (last_buttons(m['t3']) | last_buttons(m['ttt1']))), None)
        if not match: continue
        used.add(id(match)); used.add(id(r))
        ref = match['t3'] or match['ttt1']
        diff = compare(ref, r['dr'])
        r.update(status='commande changée' + (' : ' + ', '.join(diff) if diff else ''), t3=match['t3'],
                 ttt1=match['ttt1'], notes=r['notes'] + [f"T3 / TTT1 : {match['command']}"])
    return [r for r in rows if id(r) not in used or r['status'].startswith('commande changée')]


STATUS_ORDER = ('identique', 'modifié', 'commande changée', 'remplacé', 'nouveau dans DR', 'absent de DR')


def write_sheet(rows, tsv, md, name):
    fields = ('level', 'damage', 'first', 'last', 'total', 'free', 'freeze', 'block', 'hit', 'ch')
    head = ['commande', 'autres commandes', 'statut', 'notes']
    for g in ('DR', 'T3', 'TTT1'):
        head += [f'{g} coup'] + [f'{g} {c}' for c in ('niveau', 'dégâts', '1re active', 'dernière active', 'durée', 'libre',
                                                     'gel', 'garde', 'touche', 'contre', 'réaction garde', 'réaction touche',
                                                     'réaction contre')]
    with tsv.open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, delimiter='\t', lineterminator='\n')
        w.writerow(head)
        for r in rows:
            line = [r['command'], ' / '.join(r['other']), r['status'], ' ; '.join(r['notes'])]
            for g in ('dr', 't3', 'ttt1'):
                x = r[g]
                line += [x['name'] if x else ''] + [cell(x, c) for c in fields] + [x.get(c + '_rx', '') if x else '' for c in ('block', 'hit', 'ch')]
            w.writerow(line)
    counts = defaultdict(int)
    for r in rows: counts[r['status'].split(' :')[0].split(' (')[0]] += 1
    md_lines = [f"# Fiche d'équilibrage : {name}", '',
                'Statuts : ' + ', '.join(f'{k} {counts[k]}' for k in STATUS_ORDER if counts[k]), '',
                'Images à 60 par seconde. i = première image active ; garde / touche / contre = avantage calculé '
                "(> 0 : l'attaquant a la main) ; entre"
                ' parenthèses, la réaction quand elle ne rend pas la garde '
                '(mise à terre, envol, effondrement) ; « prise » : projection. Une commande notée « = x » dans un jeu '
                'y fait le même coup que la commande x.', '']
    gaps = []
    for r in rows:
        d, t = r['dr'], r['t3']
        if r.get('alias') and (r['alias'][0] or r['alias'][1]): continue      # T3 plays another command's move there
        if not d or not t or d.get('throw') or t.get('throw') or not r['status'].startswith(('modifié', 'commande changée')): continue
        delta = {c: d[c] - t[c] for c in ('damage', 'first', 'block') if d.get(c) is not None and t.get(c) is not None}
        gaps.append((sum(abs(v) for v in delta.values()), r['command'], delta))
    gaps.sort(key=lambda g: -g[0])
    md_lines += ['## Plus gros écarts DR face à T3', '',
                 'Coups communs (statut modifié ou commande changée), écart DR − T3 : dégâts, 1re image active, '
                 'avantage en garde.', '', '| commande | dégâts | 1re active | garde |', '|---|---|---|---|']
    for _, c, delta in gaps[:12]:
        md_lines.append(f"| `{c}` | " + ' | '.join(f"{delta[k]:+d}" if k in delta else '' for k in ('damage', 'first', 'block')) + ' |')
    md_lines.append('')
    hdr = ('| commande | statut | DR niv. | DR dég. | DR i | DR garde | DR touche | DR contre | T3 niv. | T3 dég. | T3 i | '
           'T3 garde | T3 touche | T3 contre | TTT1 dég. | TTT1 i | TTT1 garde | TTT1 touche | TTT1 contre | notes |')
    for status in STATUS_ORDER:
        part = [r for r in rows if r['status'].startswith(status)]
        if not part: continue
        md_lines += [f'## {status} ({len(part)})', '', hdr, '|' + '---|' * 20]
        for r in part:
            d, t, x = r['dr'], r['t3'], r['ttt1']
            md_lines.append('| ' + ' | '.join([f"`{r['command']}`", r['status'].replace(status, '').lstrip(' :') or '-',
                                               cell(d, 'level'), cell(d, 'damage'), cell(d, 'first'), cell(d, 'block'), cell(d, 'hit'), cell(d, 'ch'),
                                               cell(t, 'level'), cell(t, 'damage'), cell(t, 'first'), cell(t, 'block'), cell(t, 'hit'), cell(t, 'ch'),
                                               cell(x, 'damage'), cell(x, 'first'), cell(x, 'block'), cell(x, 'hit'), cell(x, 'ch'),
                                               ' ; '.join(r['notes'])]) + ' |')
        md_lines.append('')
    md.write_text('\n'.join(md_lines), encoding='utf-8')


def sd_value(v):
    v = v.replace('+-', '+').replace('±', '+').strip()
    m = re.match(r'^([+-]?\d+)', v)
    return int(m.group(1)) if m else v.split()[0] if v else ''


def check_sdtekken(rows, path, out):
    """DR computed against sdtekken.com (input, range, damage, speed, block, hit, ch)."""
    table = {}
    for r in csv.DictReader(path.open(encoding='utf-8'), delimiter='\t'):
        table.setdefault(r['input'].replace(' ', ''), r)
    lines, agree, total = ['commande\tchamp\tcalculé\tsdtekken'], defaultdict(int), defaultdict(int)
    for r in rows:
        d = r['dr']
        if not d: continue
        s = next((table[k] for k in [r['command']] + r['other'] if k in table), None)
        if not s: continue
        for c, sc in (('first', 'speed'), ('damage', 'damage'), ('block', 'block'), ('hit', 'hit'), ('ch', 'ch')):
            ours, theirs = d.get(c), sd_value(s[sc])
            if ours is None or not isinstance(theirs, int): continue
            total[c] += 1; agree[c] += ours == theirs
            if ours != theirs: lines.append(f"{r['command']}\t{c}\t{ours}\t{s[sc]}")
    summary = ', '.join(f'{c} {agree[c]}/{total[c]}' for c in total)
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'sdtekken : égaux {summary} -> {out}', file=sys.stderr)


def timeline(raw, labels, stances, expected, first, last, extra=()):
    """A measured command read again knowing the move expected: None when the game never played it.
    rows: [frame, attacker record, its frame, dummy record, its frame] per game frame. Contact = the
    dummy's record changing while the attacker plays `expected` inside its active frames (GUARD ALL
    raises the guard earlier, at the attacker's first frames). Back = first frame in a stance
    (standing or crouching, both counted free as the sheet does) after the contact."""
    rows = raw['rows']
    lab = lambda p, a: labels[p].get(f'{a:08x}', f'{a:08x}')
    if not any(lab(0, r[1]) == expected for r in rows): return None
    a_rest = set(stances[0]) | set(extra) | {lab(0, raw['rest'][0])}
    d_rest = set(stances[1]) | set(extra) | {lab(1, raw['rest'][1]), lab(1, rows[-1][3])}
    hit = next((i for i in range(1, len(rows)) if rows[i][3] != rows[i - 1][3] and lab(0, rows[i - 1][1]) == expected
                and first - 1 <= rows[i - 1][2] <= last + 1 and lab(1, rows[i][3]) not in d_rest), None)
    out = dict(startup=None)
    if hit is None: return out
    k = hit
    while k + 1 < len(rows) and rows[k + 1][3] == rows[hit][3] and rows[k + 1][4] == rows[hit][4]: k += 1
    out.update(startup=rows[hit - 1][2], reaction=lab(1, rows[hit][3]), freeze=k - hit)
    a_back = next((rows[i][0] for i in range(hit, len(rows)) if lab(0, rows[i][1]) in a_rest), None)
    d_back = next((rows[i][0] for i in range(hit, len(rows)) if lab(1, rows[i][3]) in d_rest), None)
    out['neutral'] = d_back - a_back if a_back is not None and d_back is not None else None
    return out


def check_measured(rows, paths, out, rise=None):
    """Tekken 3 / TTT1 computed against the game (tools/t5/move_measure.py): first active frame,
    the reaction the dummy gets, the freeze, and the advantage once both are back in a stance."""
    lines, agree, total = ['jeu\tcommande\tmode\tchamp\tcalculé\tmesuré'], defaultdict(int), defaultdict(int)
    for path in paths:
        data = json.loads(Path(path).read_text())
        g = 'ttt1' if data.get('ttt1') else 't3'
        for r in rows:
            x, m = r[g], data['moves'].get(r['command'])
            if not x or not m: continue
            x['measured'] = {}
            expected = f"p{x['id']}" if g == 'ttt1' else x['name']
            for mode in ('hit', 'block', 'ch'):
                raw = m.get(mode)
                if not raw or not raw.get('rows'): continue
                got = timeline(raw, data['labels'], data['stances'], expected, x['first'], x['last'], (rise or {}).get(g, ()))
                # Only when the game played the move of the sheet (an input can come out as another
                # move: a string's last press out of its window, a conditional entry at that distance).
                if got is None:
                    total[(g, 'autre coup sorti')] += 1
                    lines.append(f"{g}\t{r['command']}\t{mode}\tcoup sorti\t{expected}\t-"); continue
                if got.get('startup') is None:
                    total[(g, 'sans contact')] += 1; continue
                pairs = [('first', x['first'], got['startup']), ('réaction', x.get(mode + '_rx'), got.get('reaction')),
                         ('gel', x['freeze'], got.get('freeze')), ('retour au neutre', x.get(mode + '_n'), got.get('neutral'))]
                x['measured'][mode] = got.get('neutral')
                for field, ours, theirs in pairs:
                    if ours is None or theirs is None: continue
                    if field == 'réaction' and not re.fullmatch(r'p?\d+', str(theirs)): continue   # an unlabelled address
                    key = (g, field); total[key] += 1
                    same = str(ours) == str(theirs)
                    agree[key] += same
                    if not same: lines.append(f"{g}\t{r['command']}\t{mode}\t{field}\t{ours}\t{theirs}")
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('mesures : ' + ', '.join(f'{g} {c} {agree[(g, c)]}/{total[(g, c)]}' for g, c in sorted(total)), file=sys.stderr)


def main_pack_dir():
    common = subprocess.run(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    for base in (ROOT, (ROOT / common).resolve().parent):
        d = base / 'workspace/ttt1-import/roster'
        if d.is_dir(): return d
    raise SystemExit('workspace/ttt1-import/roster introuvable (import TTT1)')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('fighter', choices=sorted(FIGHTERS))
    ap.add_argument('--out', type=Path, default=ROOT / 'workspace/dr-a1')
    ap.add_argument('--packs', type=Path, help='dossier des packs TTT1 (par défaut workspace/ttt1-import/roster)')
    ap.add_argument('--sdtekken', type=Path, help='table sdtekken.com du personnage (.tsv) pour vérifier DR')
    ap.add_argument('--measured', type=Path, nargs='*', help='mesures en jeu (tools/t5/move_measure.py) pour vérifier T3 / TTT1')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    sheet(a.fighter, a.out, a.packs or main_pack_dir(), a.sdtekken, a.measured)


if __name__ == '__main__':
    main()
