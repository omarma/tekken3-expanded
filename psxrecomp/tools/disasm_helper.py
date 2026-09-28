"""Minimal MIPS disassembly helper for PSX BIOS hunts."""
import struct, sys

BASE = 0xBFC00000
REGS = ['zr','at','v0','v1','a0','a1','a2','a3','t0','t1','t2','t3','t4','t5','t6','t7',
        's0','s1','s2','s3','s4','s5','s6','s7','t8','t9','k0','k1','gp','sp','fp','ra']

def r(n): return REGS[n]

def dis(pc, w):
    op=(w>>26)&0x3f; rs=(w>>21)&0x1f; rt=(w>>16)&0x1f; rd=(w>>11)&0x1f; sh=(w>>6)&0x1f; fn=w&0x3f
    imm=w&0xffff; simm=imm-0x10000 if imm&0x8000 else imm
    tgt=(w&0x3ffffff)<<2
    if w==0: return 'nop'
    if op==0:
        fns={0x00:'sll',0x02:'srl',0x03:'sra',0x04:'sllv',0x06:'srlv',0x07:'srav',
             0x08:'jr',0x09:'jalr',0x0c:'syscall',0x0d:'break',0x10:'mfhi',0x11:'mthi',
             0x12:'mflo',0x13:'mtlo',0x18:'mult',0x19:'multu',0x1a:'div',0x1b:'divu',
             0x20:'add',0x21:'addu',0x22:'sub',0x23:'subu',0x24:'and',0x25:'or',0x26:'xor',
             0x27:'nor',0x2a:'slt',0x2b:'sltu'}
        n=fns.get(fn,f'spec{fn:02x}')
        if fn==0x08: return f'jr ${r(rs)}'
        if fn==0x09: return f'jalr ${r(rd)},${r(rs)}'
        if fn in (0x00,0x02,0x03): return f'{n} ${r(rd)},${r(rt)},{sh}'
        return f'{n} ${r(rd)},${r(rs)},${r(rt)}'
    if op==1:
        lnk='al' if (rt&0x10) else ''
        n=('bltz' if (rt&1)==0 else 'bgez')+lnk
        return f'{n} ${r(rs)},0x{pc+4+(simm<<2):08X}'
    if op==2: return f'j 0x{(pc&0xf0000000)|tgt:08X}'
    if op==3: return f'jal 0x{(pc&0xf0000000)|tgt:08X}'
    ops={4:'beq',5:'bne',6:'blez',7:'bgtz',8:'addi',9:'addiu',10:'slti',11:'sltiu',
         12:'andi',13:'ori',14:'xori',15:'lui',32:'lb',33:'lh',34:'lwl',35:'lw',
         36:'lbu',37:'lhu',38:'lwr',40:'sb',41:'sh',42:'swl',43:'sw',46:'swr',
         0x10:'cop0',0x12:'cop2'}
    n=ops.get(op,f'op{op:02x}')
    if op==15: return f'lui ${r(rt)},0x{imm:04X}'
    if op in (4,5): return f'{n} ${r(rs)},${r(rt)},0x{pc+4+(simm<<2):08X}'
    if op in (6,7): return f'{n} ${r(rs)},0x{pc+4+(simm<<2):08X}'
    if op in (8,9,10,11,12,13,14): return f'{n} ${r(rt)},${r(rs)},0x{imm:X}'
    if op>=32: return f'{n} ${r(rt)},{simm}(${r(rs)})'
    return f'raw=0x{w:08X}'

def load_rom(path='bios/SCPH1001.BIN'):
    with open(path,'rb') as f: return f.read()

def dump(rom, pc_start, n):
    for i in range(n):
        pc = pc_start + i*4
        off = pc - BASE
        if off<0 or off+4>len(rom): break
        w = struct.unpack('<I', rom[off:off+4])[0]
        print(f'0x{pc:08X}: {w:08X}  {dis(pc,w)}')

if __name__=='__main__':
    rom = load_rom()
    for arg in sys.argv[1:]:
        if ':' in arg:
            s,n = arg.split(':'); dump(rom, int(s,16), int(n))
        else:
            dump(rom, int(arg,16), 24)
        print()
