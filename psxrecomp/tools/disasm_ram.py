"""Fetch 4KB at target RAM via TCP debug server and disassemble."""
import sys, socket, json, time, struct

HOST='127.0.0.1'
PORT = int(sys.argv[1]) if len(sys.argv)>1 else 4370
addr = int(sys.argv[2],16) if len(sys.argv)>2 else 0x00000C80
length = int(sys.argv[3]) if len(sys.argv)>3 else 512

def send(cmd, timeout=3.0):
    s=socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(timeout); s.connect((HOST,PORT))
    s.sendall((json.dumps(cmd)+'\n').encode()); buf=b''
    deadline=time.time()+timeout
    while time.time()<deadline:
        try: chunk=s.recv(65536)
        except socket.timeout: break
        if not chunk: break
        buf+=chunk
        if b'\n' in buf: break
    s.close()
    line=buf.split(b'\n',1)[0].decode()
    if not line: return None
    try: return json.loads(line)
    except: return line

r = send({"cmd":"read_ram","addr":f"0x{addr:08X}","len":length})
if not r or not r.get('ok'):
    print('read failed', r); sys.exit(1)

data = bytes.fromhex(r['hex'])
base = 0x80000000 | addr
names=['zr','at','v0','v1','a0','a1','a2','a3','t0','t1','t2','t3','t4','t5','t6','t7',
       's0','s1','s2','s3','s4','s5','s6','s7','t8','t9','k0','k1','gp','sp','fp','ra']
def R(n): return '$'+names[n]

for i in range(0, len(data), 4):
    if i+4>len(data): break
    w = struct.unpack('<I', data[i:i+4])[0]
    pc = base+i
    op=(w>>26)&0x3f
    rs=(w>>21)&0x1f; rt=(w>>16)&0x1f; rd=(w>>11)&0x1f; sh=(w>>6)&0x1f
    imm=w&0xffff; simm=imm-0x10000 if imm&0x8000 else imm
    s = f'0x{pc:08X}: {w:08X}  '
    if w==0: s += 'nop'
    elif op==0:
        fn=w&0x3f
        fnames={0x00:'sll',0x02:'srl',0x03:'sra',0x04:'sllv',0x06:'srlv',0x07:'srav',
                0x08:'jr',0x09:'jalr',0x0c:'syscall',0x0d:'break',0x10:'mfhi',0x12:'mflo',
                0x18:'mult',0x19:'multu',0x1a:'div',0x1b:'divu',0x20:'add',0x21:'addu',
                0x22:'sub',0x23:'subu',0x24:'and',0x25:'or',0x26:'xor',0x27:'nor',
                0x2a:'slt',0x2b:'sltu'}
        n=fnames.get(fn, f'spec{fn:02x}')
        if fn==8: s += f'jr {R(rs)}'
        elif fn==9: s += f'jalr {R(rd)},{R(rs)}'
        elif fn in (0x00,0x02,0x03): s += f'{n} {R(rd)},{R(rt)},{sh}'
        elif fn==0x0c: s += f'syscall 0x{(w>>6)&0xfffff:X}'
        else: s += f'{n} {R(rd)},{R(rs)},{R(rt)}'
    elif op==1:
        t=(rt&1); lnk='al' if (rt&0x10) else ''
        n=('bltz' if t==0 else 'bgez')+lnk
        s += f'{n} {R(rs)},0x{pc+4+(simm<<2):08X}'
    elif op==2: s += f'j 0x{(pc&0xf0000000)|((w&0x3ffffff)<<2):08X}'
    elif op==3: s += f'jal 0x{(pc&0xf0000000)|((w&0x3ffffff)<<2):08X}'
    elif op==0x10:
        sub=(w>>21)&0x1f
        if sub==0: s += f'mfc0 {R(rt)},$cop0[{rd}]'
        elif sub==4: s += f'mtc0 {R(rt)},$cop0[{rd}]'
        elif sub==0x10 and (w&0x3f)==0x10: s += 'rfe'
        else: s += f'cop0 sub={sub}'
    elif op==0x0f: s += f'lui {R(rt)},0x{imm:04X}'
    elif op==0x09: s += f'addiu {R(rt)},{R(rs)},{simm}'
    elif op==0x08: s += f'addi {R(rt)},{R(rs)},{simm}'
    elif op==0x0a: s += f'slti {R(rt)},{R(rs)},{simm}'
    elif op==0x0b: s += f'sltiu {R(rt)},{R(rs)},{simm}'
    elif op==0x0c: s += f'andi {R(rt)},{R(rs)},0x{imm:X}'
    elif op==0x0d: s += f'ori {R(rt)},{R(rs)},0x{imm:X}'
    elif op==4: s += f'beq {R(rs)},{R(rt)},0x{pc+4+(simm<<2):08X}'
    elif op==5: s += f'bne {R(rs)},{R(rt)},0x{pc+4+(simm<<2):08X}'
    elif op==6: s += f'blez {R(rs)},0x{pc+4+(simm<<2):08X}'
    elif op==7: s += f'bgtz {R(rs)},0x{pc+4+(simm<<2):08X}'
    elif op==0x20: s += f'lb {R(rt)},{simm}({R(rs)})'
    elif op==0x21: s += f'lh {R(rt)},{simm}({R(rs)})'
    elif op==0x23: s += f'lw {R(rt)},{simm}({R(rs)})'
    elif op==0x24: s += f'lbu {R(rt)},{simm}({R(rs)})'
    elif op==0x25: s += f'lhu {R(rt)},{simm}({R(rs)})'
    elif op==0x28: s += f'sb {R(rt)},{simm}({R(rs)})'
    elif op==0x29: s += f'sh {R(rt)},{simm}({R(rs)})'
    elif op==0x2b: s += f'sw {R(rt)},{simm}({R(rs)})'
    else: s += f'op{op:02x}'
    print(s)
