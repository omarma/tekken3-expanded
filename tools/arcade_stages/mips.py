"""TTT Stages S4: a small R3000 interpreter for leaf routines of TTT's
program, run on the program's own bytes (no copy of its code here).

Used for libmath's csqrt / csin (CORDIC, 0x8018F260 / 0x8018EEAC), which the
stage 11 floor lights call at the stage load (0x8011F1B4): ported by hand
they missed the game by one 5-bit step on 42 words of 7680 (TIPS section
110); run as they are, they give the game's numbers. Integer instructions
only, with the load delay slot and the branch delay slot of the R3000; a
call returns when it comes back to the return address it was given. Any
instruction outside the subset stops the run (ValueError).
"""
from __future__ import annotations

import struct

RETURN = 0xFFFFFFF0          # the fake return address of a call
STACK = 0x803FFF00           # stack pointer of a call (a scratch area of RAM)


def s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >> 31 else v


class Machine:
    def __init__(self, program: bytes, base: int):
        self.base = base
        self.ram = bytearray(0x400000)          # 4 MiB main RAM (System 12), KSEG0 0x80000000
        self.ram[base - 0x80000000:base - 0x80000000 + len(program)] = program
        self.pristine = bytes(self.ram)

    def _addr(self, a):
        a &= 0x1FFFFFFF
        if a >= len(self.ram):
            raise ValueError(f'address 0x{a:08X} out of RAM')
        return a

    def load(self, a, n, signed=False):
        a = self._addr(a)
        v = int.from_bytes(self.ram[a:a + n], 'little', signed=signed)
        return v & 0xFFFFFFFF

    def store(self, a, v, n):
        a = self._addr(a)
        self.ram[a:a + n] = (v & ((1 << 8 * n) - 1)).to_bytes(n, 'little')

    def call(self, pc: int, *args, limit=200000):
        """Run the routine at pc with a0.. = args; returns v0 (signed)."""
        self.ram[:] = self.pristine
        r = [0] * 32
        for i, a in enumerate(args):
            r[4 + i] = a & 0xFFFFFFFF
        r[29] = STACK
        r[31] = RETURN
        hi = lo = lzcs = 0
        pending = None                  # (register, value): the load delay slot
        delay_to = None                 # branch target after the delay slot
        for _ in range(limit):
            if pc == RETURN:
                if pending:
                    r[pending[0]] = pending[1]
                return s32(r[2])
            w = self.load(pc, 4)
            op, rs, rt, rd = w >> 26, w >> 21 & 31, w >> 16 & 31, w >> 11 & 31
            sa, fn, imm = w >> 6 & 31, w & 63, w & 0xFFFF
            simm = imm - 0x10000 if imm & 0x8000 else imm
            new_pending = None
            next_pc = pc + 4
            branch = None
            S, T = r[rs], r[rt]
            def wr(i, v):
                if i:
                    r[i] = v & 0xFFFFFFFF
            if op == 0:
                if fn == 0x00: wr(rd, T << sa)
                elif fn == 0x02: wr(rd, T >> sa)
                elif fn == 0x03: wr(rd, s32(T) >> sa)
                elif fn == 0x04: wr(rd, T << (S & 31))
                elif fn == 0x06: wr(rd, T >> (S & 31))
                elif fn == 0x07: wr(rd, s32(T) >> (S & 31))
                elif fn == 0x08: branch = S
                elif fn == 0x09: wr(rd, pc + 8); branch = S
                elif fn == 0x10: wr(rd, hi)
                elif fn == 0x12: wr(rd, lo)
                elif fn == 0x18:
                    p = s32(S) * s32(T); lo, hi = p & 0xFFFFFFFF, (p >> 32) & 0xFFFFFFFF
                elif fn == 0x19:
                    p = S * T; lo, hi = p & 0xFFFFFFFF, (p >> 32) & 0xFFFFFFFF
                elif fn == 0x1A:
                    if s32(T):
                        q = int(s32(S) / s32(T)); lo, hi = q & 0xFFFFFFFF, (s32(S) - q * s32(T)) & 0xFFFFFFFF
                elif fn == 0x1B:
                    if T:
                        lo, hi = S // T, S % T
                elif fn in (0x20, 0x21): wr(rd, S + T)
                elif fn in (0x22, 0x23): wr(rd, S - T)
                elif fn == 0x24: wr(rd, S & T)
                elif fn == 0x25: wr(rd, S | T)
                elif fn == 0x26: wr(rd, S ^ T)
                elif fn == 0x27: wr(rd, ~(S | T))
                elif fn == 0x2A: wr(rd, int(s32(S) < s32(T)))
                elif fn == 0x2B: wr(rd, int(S < T))
                else:
                    raise ValueError(f'0x{pc:08X}: special 0x{fn:02X}')
            elif op == 1:
                if rt in (0, 0x10): branch = pc + 4 + (simm << 2) if s32(S) < 0 else None
                elif rt in (1, 0x11): branch = pc + 4 + (simm << 2) if s32(S) >= 0 else None
                else:
                    raise ValueError(f'0x{pc:08X}: regimm {rt}')
                if rt & 0x10:
                    wr(31, pc + 8)
                if branch is None:
                    branch = next_pc + 4        # not taken: still a delay slot
            elif op in (2, 3):
                if op == 3:
                    wr(31, pc + 8)
                branch = (pc & 0xF0000000) | (w & 0x3FFFFFF) << 2
            elif op in (4, 5, 6, 7):
                taken = {4: S == T, 5: S != T, 6: s32(S) <= 0, 7: s32(S) > 0}[op]
                branch = pc + 4 + (simm << 2) if taken else next_pc + 4
            elif op in (8, 9): wr(rt, S + simm)
            elif op == 0x0A: wr(rt, int(s32(S) < simm))
            elif op == 0x0B: wr(rt, int(S < (simm & 0xFFFFFFFF)))
            elif op == 0x0C: wr(rt, S & imm)
            elif op == 0x0D: wr(rt, S | imm)
            elif op == 0x0E: wr(rt, S ^ imm)
            elif op == 0x0F: wr(rt, imm << 16)
            elif op in (0x20, 0x21, 0x23, 0x24, 0x25):
                n = {0x20: 1, 0x24: 1, 0x21: 2, 0x25: 2, 0x23: 4}[op]
                v = self.load(S + simm, n, signed=op in (0x20, 0x21))
                if rt:
                    new_pending = (rt, v)
            elif op in (0x28, 0x29, 0x2B):
                self.store(S + simm, T, {0x28: 1, 0x29: 2, 0x2B: 4}[op])
            elif op == 0x12 and rs == 4 and rd == 30:   # mtc2 LZCS (0x80190770, csqrt's leading bits)
                lzcs = T
            elif op == 0x12 and rs == 0 and rd == 31:   # mfc2 LZCR: leading bits equal to the sign bit
                v, k = lzcs, 0
                sign = v >> 31 & 1
                while k < 32 and (v >> (31 - k) & 1) == sign:
                    k += 1
                new_pending = (rt, k) if rt else None
            elif op == 0x10 and rs in (0, 4):           # mfc0 / mtc0: not in these routines' paths
                raise ValueError(f'0x{pc:08X}: cop0')
            else:
                raise ValueError(f'0x{pc:08X}: opcode 0x{op:02X}')
            if pending and (new_pending is None or pending[0] != new_pending[0]):
                r[pending[0]] = pending[1]
            pending = new_pending
            if delay_to is not None:
                pc, delay_to = delay_to, None
                if branch is not None:
                    raise ValueError(f'0x{pc:08X}: a branch in a delay slot')
                continue
            if branch is not None:
                delay_to = branch
            pc = next_pc
        raise ValueError(f'call to 0x{pc:08X}: no return after {limit} instructions')
