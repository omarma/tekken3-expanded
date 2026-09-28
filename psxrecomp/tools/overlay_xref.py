#!/usr/bin/env python3
"""Cross-reference overlay code bytes captured by the runtime.

The runtime writes one JSON per distinct overlay body it has ever seen into
`<build>/overlay_captures.json.d/<contenthash>.json` (schema
"psxrecomp overlay capture v2": `load_addr`, `size`, `bytes_b64`, and the set of
`executed_pcs` observed inside that body).  Because the set is content-hashed and
additive across every run, it is an always-on record of every overlay variant the
game has ever mapped -- exactly what is needed before touching an address-guarded
`[widescreen.cull]` site, where a second variant at the same virtual address with
the same opcode but different operands would be silently mispatched.

This tool is game-agnostic: point it at any title's capture directory.

Commands
--------
  index                       summarise the capture set
  word   VA...                every distinct word observed at each VA, with the
                              capture ids and whether the VA was ever executed
  dis    VA [-n N]            disassemble N instructions from VA, one listing per
                              distinct variant
  func   VA [-n N]            disassemble backwards to the enclosing function
                              prologue, then forwards to its return
  scan   --op OP [--imm-min M] [--imm-max M] [--exec-only]
                              every site whose opcode matches, optionally
                              filtered by immediate range
  imm    VALUE                every site anywhere whose immediate equals VALUE
  callers VA                  every jal/j site targeting VA
  cover  VA...                which captures contain each VA (load ranges only)

Examples
--------
  overlay_xref.py -d build/overlay_captures.json.d word 0x80069B84
  overlay_xref.py -d build/overlay_captures.json.d dis 0x80069B6C -n 80
  overlay_xref.py -d build/overlay_captures.json.d scan --op sltiu --imm-min 0x100
  overlay_xref.py -d build/overlay_captures.json.d callers 0x80069B6C
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import struct
import sys
from collections import defaultdict

# ---------------------------------------------------------------------------
# MIPS R3000A disassembler (mirrors tools/disasm_helper.py, widened for cop2)
# ---------------------------------------------------------------------------

REGS = ['zr', 'at', 'v0', 'v1', 'a0', 'a1', 'a2', 'a3',
        't0', 't1', 't2', 't3', 't4', 't5', 't6', 't7',
        's0', 's1', 's2', 's3', 's4', 's5', 's6', 's7',
        't8', 't9', 'k0', 'k1', 'gp', 'sp', 'fp', 'ra']

SPECIAL = {
    0x00: 'sll', 0x02: 'srl', 0x03: 'sra', 0x04: 'sllv', 0x06: 'srlv',
    0x07: 'srav', 0x08: 'jr', 0x09: 'jalr', 0x0c: 'syscall', 0x0d: 'break',
    0x10: 'mfhi', 0x11: 'mthi', 0x12: 'mflo', 0x13: 'mtlo', 0x18: 'mult',
    0x19: 'multu', 0x1a: 'div', 0x1b: 'divu', 0x20: 'add', 0x21: 'addu',
    0x22: 'sub', 0x23: 'subu', 0x24: 'and', 0x25: 'or', 0x26: 'xor',
    0x27: 'nor', 0x2a: 'slt', 0x2b: 'sltu',
}

IMMOPS = {
    4: 'beq', 5: 'bne', 6: 'blez', 7: 'bgtz', 8: 'addi', 9: 'addiu',
    10: 'slti', 11: 'sltiu', 12: 'andi', 13: 'ori', 14: 'xori', 15: 'lui',
    32: 'lb', 33: 'lh', 34: 'lwl', 35: 'lw', 36: 'lbu', 37: 'lhu', 38: 'lwr',
    40: 'sb', 41: 'sh', 42: 'swl', 43: 'sw', 46: 'swr',
    0x32: 'lwc2', 0x3a: 'swc2',
}


def _r(n: int) -> str:
    return REGS[n & 0x1f]


def mnemonic(w: int) -> str:
    """Just the opcode name, for filtering."""
    if w == 0:
        return 'nop'
    op = (w >> 26) & 0x3f
    if op == 0:
        return SPECIAL.get(w & 0x3f, f'spec{w & 0x3f:02x}')
    if op == 1:
        rt = (w >> 16) & 0x1f
        return ('bltz' if (rt & 1) == 0 else 'bgez') + ('al' if rt & 0x10 else '')
    if op == 2:
        return 'j'
    if op == 3:
        return 'jal'
    if op == 0x10:
        return 'cop0'
    if op == 0x12:
        return 'cop2'
    return IMMOPS.get(op, f'op{op:02x}')


def dis(pc: int, w: int) -> str:
    if w == 0:
        return 'nop'
    op = (w >> 26) & 0x3f
    rs = (w >> 21) & 0x1f
    rt = (w >> 16) & 0x1f
    rd = (w >> 11) & 0x1f
    sh = (w >> 6) & 0x1f
    fn = w & 0x3f
    imm = w & 0xffff
    simm = imm - 0x10000 if imm & 0x8000 else imm
    tgt = (w & 0x3ffffff) << 2
    if op == 0:
        n = SPECIAL.get(fn, f'spec{fn:02x}')
        if fn == 0x08:
            return f'jr      ${_r(rs)}'
        if fn == 0x09:
            return f'jalr    ${_r(rd)},${_r(rs)}'
        if fn in (0x0c, 0x0d):
            return n
        if fn in (0x10, 0x12):
            return f'{n:<7} ${_r(rd)}'
        if fn in (0x11, 0x13):
            return f'{n:<7} ${_r(rs)}'
        if fn in (0x18, 0x19, 0x1a, 0x1b):
            return f'{n:<7} ${_r(rs)},${_r(rt)}'
        if fn in (0x00, 0x02, 0x03):
            return f'{n:<7} ${_r(rd)},${_r(rt)},{sh}'
        return f'{n:<7} ${_r(rd)},${_r(rs)},${_r(rt)}'
    if op == 1:
        n = ('bltz' if (rt & 1) == 0 else 'bgez') + ('al' if rt & 0x10 else '')
        return f'{n:<7} ${_r(rs)},0x{(pc + 4 + (simm << 2)) & 0xffffffff:08X}'
    if op in (2, 3):
        n = 'j' if op == 2 else 'jal'
        return f'{n:<7} 0x{(pc & 0xf0000000) | tgt:08X}'
    n = IMMOPS.get(op, f'op{op:02x}')
    if op == 15:
        return f'lui     ${_r(rt)},0x{imm:04X}'
    if op in (4, 5):
        return f'{n:<7} ${_r(rs)},${_r(rt)},0x{(pc + 4 + (simm << 2)) & 0xffffffff:08X}'
    if op in (6, 7):
        return f'{n:<7} ${_r(rs)},0x{(pc + 4 + (simm << 2)) & 0xffffffff:08X}'
    if op in (8, 9, 10, 11):
        return f'{n:<7} ${_r(rt)},${_r(rs)},0x{imm:04X}   # {simm}'
    if op in (12, 13, 14):
        return f'{n:<7} ${_r(rt)},${_r(rs)},0x{imm:04X}'
    if op == 0x10:
        return f'cop0    0x{w & 0x3ffffff:07X}'
    if op == 0x12:
        return f'cop2    0x{w & 0x3ffffff:07X}'
    if op >= 32:
        return f'{n:<7} ${_r(rt)},{simm}(${_r(rs)})'
    return f'raw     0x{w:08X}'


def imm_of(w: int):
    """16-bit immediate field for every i-type opcode that has one, else None.

    Covers the ALU immediates (addi..lui) *and* the load/store displacements --
    a gate's threshold is an ALU immediate, but the struct-field offset that
    identifies which coordinate is being tested is a load displacement, so both
    have to be searchable.
    """
    op = (w >> 26) & 0x3f
    if op in (8, 9, 10, 11, 12, 13, 14, 15):          # addi/addiu/slti/sltiu/andi/ori/xori/lui
        return w & 0xffff
    if 32 <= op <= 46 and op not in (39, 44, 45):     # lb..swr (loads and stores)
        return w & 0xffff
    return None


# ---------------------------------------------------------------------------
# Capture set
# ---------------------------------------------------------------------------

class Capture:
    __slots__ = ('cid', 'lo', 'size', 'data', 'exec_pcs')

    def __init__(self, cid, lo, size, data, exec_pcs):
        self.cid = cid
        self.lo = lo
        self.size = size
        self.data = data
        self.exec_pcs = exec_pcs

    @property
    def hi(self):
        return self.lo + self.size

    def word(self, va):
        off = va - self.lo
        if off < 0 or off + 4 > len(self.data):
            return None
        return struct.unpack_from('<I', self.data, off)[0]


CACHE_VERSION = 2


class CaptureSet:
    def __init__(self, directory, want_exec=True, cache=True):
        self.dir = directory
        self.caps: list[Capture] = []
        files = sorted(glob.glob(os.path.join(directory, '*.json')))
        if not files:
            raise SystemExit(f'no capture JSONs under {directory}')
        cache_path = os.path.join(directory, '.overlay_xref.cache')
        if cache and self._load_cache(cache_path, files):
            self._index_phys()
            return
        self._parse(files, want_exec)
        if cache:
            self._save_cache(cache_path, files)
        self._index_phys()

    # -- cache -------------------------------------------------------------
    def _fingerprint(self, files):
        return (CACHE_VERSION, len(files),
                max((os.path.getmtime(f) for f in files), default=0.0),
                sum(os.path.getsize(f) for f in files))

    def _load_cache(self, path, files):
        if not os.path.exists(path):
            return False
        try:
            import pickle
            with open(path, 'rb') as fh:
                fp, caps = pickle.load(fh)
        except Exception:
            return False
        if fp != self._fingerprint(files):
            return False
        self.caps = [Capture(*t) for t in caps]
        return True

    def _save_cache(self, path, files):
        try:
            import pickle
            payload = (self._fingerprint(files),
                       [(c.cid, c.lo, c.size, c.data, c.exec_pcs)
                        for c in self.caps])
            tmp = path + '.tmp'
            with open(tmp, 'wb') as fh:
                pickle.dump(payload, fh, protocol=4)
            os.replace(tmp, path)
        except Exception as exc:
            print(f'# cache write failed: {exc}', file=sys.stderr)

    def _index_phys(self):
        self._by_phys = defaultdict(list)
        for c in self.caps:
            self._by_phys[c.lo & 0x1fffffff].append(c)

    def _parse(self, files, want_exec):
        for path in files:
            cid = os.path.splitext(os.path.basename(path))[0]
            try:
                entries = json.load(open(path))
            except Exception as exc:                      # corrupt/partial write
                print(f'# skipping {cid}: {exc}', file=sys.stderr)
                continue
            if isinstance(entries, dict):
                entries = [entries]
            for e in entries:
                try:
                    lo = int(e['load_addr'], 16)
                    data = base64.b64decode(e['bytes_b64'])
                except (KeyError, ValueError):
                    continue
                pcs = frozenset()
                if want_exec:
                    acc = set()
                    for p in e.get('executed_pcs', ()):
                        try:
                            acc.add(int(p, 16) & 0x1fffffff)
                        except ValueError:
                            pass
                    pcs = frozenset(acc)
                self.caps.append(Capture(cid, lo, int(e.get('size', len(data))),
                                         data, pcs))

    def covering(self, va):
        phys = va & 0x1fffffff
        out = []
        for c in self.caps:
            off = phys - (c.lo & 0x1fffffff)
            if 0 <= off and off + 4 <= len(c.data):
                out.append(c)
        return out

    def variants(self, va):
        """{word: [captures]} for every capture that covers va."""
        out = defaultdict(list)
        for c in self.covering(va):
            w = struct.unpack_from('<I', c.data,
                                   (va & 0x1fffffff) - (c.lo & 0x1fffffff))[0]
            out[w].append(c)
        return out

    def executed(self, va):
        phys = va & 0x1fffffff
        return [c for c in self.caps if phys in c.exec_pcs]

    def iter_words(self, exec_only=False):
        """Yield (va, word, capture) over every code word in every capture."""
        for c in self.caps:
            n = len(c.data) & ~3
            words = struct.unpack_from(f'<{n // 4}I', c.data, 0)
            seg = c.lo & ~0x1fffffff
            if exec_only:
                for p in sorted(c.exec_pcs):
                    off = p - (c.lo & 0x1fffffff)
                    if 0 <= off and off + 4 <= n:
                        yield seg | p, words[off // 4], c
            else:
                for i, w in enumerate(words):
                    yield c.lo + i * 4, w, c


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_index(cs, args):
    print(f'captures      : {len(cs.caps)}')
    lows = sorted({c.lo for c in cs.caps})
    print(f'distinct bases: {len(lows)}')
    exec_total = sum(len(c.exec_pcs) for c in cs.caps)
    print(f'executed pcs  : {exec_total} (non-unique across captures)')
    print()
    print(f'{"base":<12}{"variants":>9}{"size":>9}{"execd":>8}')
    for lo in lows:
        group = [c for c in cs.caps if c.lo == lo]
        sizes = sorted({c.size for c in group})
        nex = sum(1 for c in group if c.exec_pcs)
        sz = sizes[0] if len(sizes) == 1 else f'{sizes[0]}..{sizes[-1]}'
        print(f'0x{lo:08X}{len(group):>9}{str(sz):>9}{nex:>8}')


def _fmt_caps(caps, limit=6):
    ids = [c.cid[:8] for c in caps]
    if len(ids) > limit:
        return ', '.join(ids[:limit]) + f', +{len(ids) - limit} more'
    return ', '.join(ids)


def cmd_word(cs, args):
    for va in args.vas:
        vs = cs.variants(va)
        ex = cs.executed(va)
        print(f'=== 0x{va:08X} ===')
        if not vs:
            print('  NOT COVERED by any capture')
            continue
        print(f'  covered by {sum(len(v) for v in vs.values())} capture(s), '
              f'{len(vs)} distinct word(s), executed in {len(ex)} capture(s)')
        phys = va & 0x1fffffff
        for w, caps in sorted(vs.items(), key=lambda kv: -len(kv[1])):
            nex = sum(1 for c in caps if phys in c.exec_pcs)
            print(f'  0x{w:08X}  n={len(caps):<4} exec={nex:<4} {dis(va, w)}')
            print(f'             {_fmt_caps(caps)}')
        print()


def cmd_cover(cs, args):
    for va in args.vas:
        caps = cs.covering(va)
        print(f'0x{va:08X}: {len(caps)} capture(s)')
        bases = defaultdict(int)
        for c in caps:
            bases[(c.lo, c.size)] += 1
        for (lo, size), n in sorted(bases.items()):
            print(f'  base 0x{lo:08X} size {size:<8} x{n}')


def _listing(cs, va, n, variant_words=None):
    """Print one listing per distinct byte-sequence covering [va, va+4n)."""
    caps = cs.covering(va)
    if not caps:
        print(f'0x{va:08X}: NOT COVERED')
        return
    groups = defaultdict(list)
    for c in caps:
        off = (va & 0x1fffffff) - (c.lo & 0x1fffffff)
        blob = c.data[off:off + 4 * n]
        groups[blob].append(c)
    for blob, gcaps in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f'--- variant: {len(gcaps)} capture(s) '
              f'[{_fmt_caps(gcaps, 4)}] base 0x{gcaps[0].lo:08X} ---')
        execd = set()
        for c in gcaps:
            execd |= c.exec_pcs
        cnt = len(blob) // 4
        words = struct.unpack_from(f'<{cnt}I', blob, 0)
        for i, w in enumerate(words):
            pc = va + i * 4
            mark = 'x' if (pc & 0x1fffffff) in execd else ' '
            print(f' {mark} 0x{pc:08X}: {w:08X}  {dis(pc, w)}')
        print()


def cmd_dis(cs, args):
    for va in args.vas:
        print(f'=== dis 0x{va:08X} n={args.n} ===')
        _listing(cs, va, args.n)


def cmd_func(cs, args):
    """Walk back to a plausible prologue, then forward past the return."""
    for va in args.vas:
        caps = cs.covering(va)
        if not caps:
            print(f'0x{va:08X}: NOT COVERED')
            continue
        c = max(caps, key=lambda x: len(x.exec_pcs))
        base = c.lo
        off = (va & 0x1fffffff) - (base & 0x1fffffff)
        words = struct.unpack_from(f'<{len(c.data) // 4}I', c.data, 0)
        i = off // 4
        # backwards: first `addiu $sp,$sp,-N` (0x27BD****, negative imm)
        start = i
        for j in range(i, max(0, i - args.back), -1):
            w = words[j]
            if (w & 0xffff0000) == 0x27bd0000 and (w & 0x8000):
                start = j
                break
        else:
            start = max(0, i - args.back)
        # forwards: first `jr $ra` plus its delay slot
        end = min(len(words) - 1, i + args.n)
        for j in range(i, min(len(words), i + args.n * 4)):
            if words[j] == 0x03e00008:
                end = j + 1
                break
        print(f'=== func containing 0x{va:08X} -> '
              f'0x{base + start * 4:08X}..0x{base + end * 4:08X} ===')
        _listing(cs, base + start * 4, end - start + 1)


def cmd_scan(cs, args):
    want = set(args.op)
    lo = args.imm_min
    hi = args.imm_max
    seen = defaultdict(lambda: defaultdict(int))
    for va, w, c in cs.iter_words(exec_only=args.exec_only):
        if mnemonic(w) not in want:
            continue
        im = imm_of(w)
        if lo is not None and (im is None or im < lo):
            continue
        if hi is not None and (im is None or im > hi):
            continue
        seen[va][w] += 1
    print(f'{len(seen)} matching site(s)')
    for va in sorted(seen):
        for w, n in sorted(seen[va].items(), key=lambda kv: -kv[1]):
            print(f'0x{va:08X}  {w:08X}  n={n:<5} {dis(va, w)}')


def cmd_imm(cs, args):
    target = args.value
    seen = defaultdict(lambda: defaultdict(int))
    for va, w, c in cs.iter_words(exec_only=args.exec_only):
        if imm_of(w) == target:
            seen[va][w] += 1
    print(f'{len(seen)} site(s) with immediate 0x{target:04X}')
    for va in sorted(seen):
        for w, n in sorted(seen[va].items(), key=lambda kv: -kv[1]):
            print(f'0x{va:08X}  {w:08X}  n={n:<5} {dis(va, w)}')


def cmd_window(cs, args):
    """Find the centered-unsigned-window idiom.

    A PS1 visibility/activation gate is almost always written as

        subu   rT, rRef, rObj        # signed coordinate delta
        addiu  rT, rT, BIAS          # recentre it                  <- bias site
        andi   rT, rT, 0xFFFF        # truncate back to 16-bit (optional)
        sltiu  rD, rT, SPAN          # one unsigned compare == |delta| < SPAN/2
                                     #                               <- range site

    which is exactly what `[widescreen.cull] bias_sites` / `range_sites` widen
    (FUN_80069b6c is the canonical instance).  Instructions between the bias and
    the compare are allowed only when they *carry* the value -- a same-register
    `andi`/`addiu`/`sll`/`sra`/`or` -- so a genuine redefinition still breaks the
    pair.  This reports every such pair in the capture set so a candidate gate
    can be found without knowing the function up front, and so no second variant
    at the same address is missed.
    """
    def carries(v, dst):
        """True if v keeps dst live as a transform of itself."""
        op = (v >> 26) & 0x3f
        if op in (8, 9, 12, 13, 14):                      # addi/addiu/andi/ori/xori
            return ((v >> 16) & 0x1f) == dst and ((v >> 21) & 0x1f) == dst
        if op == 0 and (v & 0x3f) in (0x00, 0x02, 0x03):  # sll/srl/sra
            return ((v >> 11) & 0x1f) == dst and ((v >> 16) & 0x1f) == dst
        if op == 0 and (v & 0x3f) in (0x21, 0x25):        # addu/or (reg move-ish)
            return ((v >> 11) & 0x1f) == dst and dst in (((v >> 21) & 0x1f),
                                                         ((v >> 16) & 0x1f))
        return False

    def writes(v, dst):
        op = (v >> 26) & 0x3f
        if op == 0:
            fn = v & 0x3f
            if fn in (0x08, 0x0c, 0x0d):
                return False
            if fn in (0x11, 0x13, 0x18, 0x19, 0x1a, 0x1b):
                return False
            return ((v >> 11) & 0x1f) == dst
        if op in (2, 3, 4, 5, 6, 7, 0x10, 0x12):
            return False
        if op in (40, 41, 42, 43, 46):                    # stores
            return False
        return ((v >> 16) & 0x1f) == dst

    cmp_ops = {11: 'sltiu'} if not args.signed else {10: 'slti', 11: 'sltiu'}
    pairs = defaultdict(lambda: defaultdict(int))
    for c in cs.caps:
        n = len(c.data) & ~3
        cnt = n // 4
        words = struct.unpack_from(f'<{cnt}I', c.data, 0)
        base = c.lo
        for i, w in enumerate(words):
            if (w >> 26) & 0x3f != 9:                     # addiu = bias
                continue
            bias = w & 0xffff
            if not (args.bias_min <= bias <= args.bias_max):
                continue
            dst = (w >> 16) & 0x1f
            if dst == 0:
                continue
            for j in range(i + 1, min(cnt, i + 1 + args.gap + 1)):
                v = words[j]
                op = (v >> 26) & 0x3f
                if op in cmp_ops and ((v >> 21) & 0x1f) == dst:
                    span = v & 0xffff
                    if args.span_min <= span <= args.span_max:
                        pairs[(base + i * 4, base + j * 4)][(w, v)] += 1
                    break
                if carries(v, dst):
                    continue
                if writes(v, dst):
                    break
    print(f'{len(pairs)} addiu/sltiu window pair(s) '
          f'bias 0x{args.bias_min:X}..0x{args.bias_max:X} '
          f'span 0x{args.span_min:X}..0x{args.span_max:X} gap<={args.gap}')
    print()
    for (ba, sa) in sorted(pairs):
        variants = pairs[(ba, sa)]
        tot = sum(variants.values())
        execd = sum(1 for c in cs.caps
                    if (ba & 0x1fffffff) in c.exec_pcs
                    or (sa & 0x1fffffff) in c.exec_pcs)
        print(f'0x{ba:08X} -> 0x{sa:08X}  captures={tot:<5} execd={execd:<5} '
              f'variants={len(variants)}')
        for (w, v), n in sorted(variants.items(), key=lambda kv: -kv[1]):
            print(f'    n={n:<5} bias {w:08X} {dis(ba, w)}')
            print(f'    {"":<7} span {v:08X} {dis(sa, v)}')


def cmd_ramimage(cs, args):
    """Composite the capture set into a flat guest-RAM image for Ghidra.

    Overlay code only exists in RAM at runtime, so a static EXE import cannot see
    it -- every interesting gate in a heavily-overlaid title lives outside the
    boot EXE's text range.  The capture set *is* an observed record of that RAM,
    so flattening it produces an image a decompiler can chew on.

    Where several overlays mapped different bodies to the same address the winner
    is the variant seen executing in the most captures (ties broken by capture
    count).  Every such address is reported in the conflict manifest so an
    analysis built on this image can never silently assume it saw the only
    version -- use `word <VA>` to inspect the alternatives.
    """
    lo, hi = args.base, args.base + args.size
    seg = args.base & 0xe0000000

    # Tally every observation first, then elect -- electing while accumulating
    # makes the counts depend on capture order, which is how a "winner" can end
    # up undercounted and silently wrong.
    single = {}          # idx -> [word, exec_captures, captures]   (one variant so far)
    multi = {}           # idx -> {word: [exec_captures, captures]} (>1 variant seen)
    for c in cs.caps:
        seg_lo = c.lo & 0x1fffffff
        n = len(c.data) & ~3
        words = struct.unpack_from(f'<{n // 4}I', c.data, 0)
        for k, w in enumerate(words):
            phys = seg_lo + k * 4
            va = seg | phys
            if va < lo or va + 4 > hi:
                continue
            idx = va - lo
            e = 1 if phys in c.exec_pcs else 0
            d = multi.get(idx)
            if d is not None:
                slot = d.setdefault(w, [0, 0])
                slot[0] += e
                slot[1] += 1
                continue
            cur = single.get(idx)
            if cur is None:
                single[idx] = [w, e, 1]
            elif cur[0] == w:
                cur[1] += e
                cur[2] += 1
            else:
                multi[idx] = {cur[0]: [cur[1], cur[2]], w: [e, 1]}
                del single[idx]

    image = bytearray(args.size)
    for idx, (w, _e, _n) in single.items():
        struct.pack_into('<I', image, idx, w)
    conflicts = {}
    for idx, d in multi.items():
        win = max(d.items(), key=lambda kv: (kv[1][0], kv[1][1]))[0]
        struct.pack_into('<I', image, idx, win)
        conflicts[lo + idx] = d

    covered = len(single) + len(multi)
    with open(args.out, 'wb') as fh:
        fh.write(image)
    print(f'wrote {args.out}  base=0x{args.base:08X} size=0x{args.size:X}')
    print(f'covered words: {covered} / {args.size // 4} '
          f'({100.0 * covered * 4 / args.size:.1f}% of the image)')
    print(f'conflicting addresses: {len(conflicts)}')
    if args.manifest:
        with open(args.manifest, 'w') as fh:
            fh.write('# addresses where overlays disagree; winner listed first\n')
            fh.write('# VA  word  exec_captures  captures  disasm\n')
            for va in sorted(conflicts):
                ranked = sorted(conflicts[va].items(),
                                key=lambda kv: (-kv[1][0], -kv[1][1]))
                for w, (we, wc) in ((k, tuple(v)) for k, v in ranked):
                    fh.write(f'0x{va:08X}  {w:08X}  {we:<6} {wc:<6} '
                             f'{dis(va, w)}\n')
                fh.write('\n')
        print(f'wrote conflict manifest {args.manifest}')


def cmd_callers(cs, args):
    for va in args.vas:
        tgt = (va >> 2) & 0x3ffffff
        hits = defaultdict(lambda: defaultdict(int))
        for site, w, c in cs.iter_words(exec_only=args.exec_only):
            op = (w >> 26) & 0x3f
            if op in (2, 3) and (w & 0x3ffffff) == tgt:
                hits[site][w] += 1
        print(f'=== callers of 0x{va:08X}: {len(hits)} site(s) ===')
        for site in sorted(hits):
            for w, n in hits[site].items():
                print(f'0x{site:08X}  {w:08X}  n={n:<5} {dis(site, w)}')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-d', '--dir', required=True,
                    help='overlay_captures.json.d directory')
    ap.add_argument('--no-cache', action='store_true',
                    help='re-parse the JSONs instead of using .overlay_xref.cache')
    sub = ap.add_subparsers(dest='cmd', required=True)

    def va_list(p):
        p.add_argument('vas', nargs='+', type=lambda s: int(s, 16))

    sub.add_parser('index').set_defaults(fn=cmd_index)
    p = sub.add_parser('word'); va_list(p); p.set_defaults(fn=cmd_word)
    p = sub.add_parser('cover'); va_list(p); p.set_defaults(fn=cmd_cover)
    p = sub.add_parser('dis'); va_list(p)
    p.add_argument('-n', type=int, default=32); p.set_defaults(fn=cmd_dis)
    p = sub.add_parser('func'); va_list(p)
    p.add_argument('-n', type=int, default=160)
    p.add_argument('--back', type=int, default=400); p.set_defaults(fn=cmd_func)
    p = sub.add_parser('scan')
    p.add_argument('--op', nargs='+', required=True)
    p.add_argument('--imm-min', type=lambda s: int(s, 0))
    p.add_argument('--imm-max', type=lambda s: int(s, 0))
    p.add_argument('--exec-only', action='store_true'); p.set_defaults(fn=cmd_scan)
    p = sub.add_parser('imm')
    p.add_argument('value', type=lambda s: int(s, 0))
    p.add_argument('--exec-only', action='store_true'); p.set_defaults(fn=cmd_imm)
    p = sub.add_parser('window')
    p.add_argument('--bias-min', type=lambda s: int(s, 0), default=0x10)
    p.add_argument('--bias-max', type=lambda s: int(s, 0), default=0x7fff)
    p.add_argument('--span-min', type=lambda s: int(s, 0), default=0x20)
    p.add_argument('--span-max', type=lambda s: int(s, 0), default=0x7fff)
    p.add_argument('--gap', type=int, default=4,
                   help='max instructions between the addiu and the sltiu')
    p.add_argument('--signed', action='store_true',
                   help='also accept a signed slti as the compare')
    p.set_defaults(fn=cmd_window)
    p = sub.add_parser('ramimage')
    p.add_argument('out', help='output flat RAM image path')
    p.add_argument('--base', type=lambda s: int(s, 0), default=0x80000000)
    p.add_argument('--size', type=lambda s: int(s, 0), default=0x200000)
    p.add_argument('--manifest', help='write a conflicting-address report here')
    p.set_defaults(fn=cmd_ramimage)
    p = sub.add_parser('callers'); va_list(p)
    p.add_argument('--exec-only', action='store_true'); p.set_defaults(fn=cmd_callers)

    args = ap.parse_args()
    cs = CaptureSet(args.dir, cache=not args.no_cache)
    args.fn(cs, args)


if __name__ == '__main__':
    main()
