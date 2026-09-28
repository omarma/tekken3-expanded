"""Follow-up probe: read IRQ chain blocks, explore 0x800DFEE0 context, disassemble exception entry."""
import socket, json, time

HOST='127.0.0.1'; PORT=4371

def send(cmd, timeout=3.0):
    s=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((HOST,PORT))
    s.sendall((json.dumps(cmd)+'\n').encode())
    buf=b''
    deadline = time.time()+timeout
    while time.time()<deadline:
        try: chunk=s.recv(65536)
        except socket.timeout: break
        if not chunk: break
        buf+=chunk
        if b'\n' in buf: break
    s.close()
    line = buf.split(b'\n',1)[0].decode()
    if not line: return None
    try: return json.loads(line)
    except: return line

def read_ram(addr, length):
    r = send({"cmd":"read_ram","addr":f"0x{addr:08X}","len":length})
    if not r or not r.get('ok'): return None
    return bytes.fromhex(r['hex'])

def dump_words(data, base, annotate=None):
    for i in range(0, len(data), 16):
        words = [int.from_bytes(data[i+j:i+j+4],'little') for j in range(0, min(16,len(data)-i), 4)]
        hexs = ' '.join(f'{w:08X}' for w in words)
        annot = ''
        if annotate:
            for j,w in enumerate(words):
                tag = annotate(base+i+j*4, w)
                if tag: annot += f' [{base+i+j*4:08X}:{tag}]'
        print(f'  0x{base+i:08X}: {hexs}{annot}', flush=True)

# Targets we care about
TARGETS = {
    0x8005A5BC: 'handler',
    0x8005A540: 'registrar',
    0x8005A160: 'init',
    0x8005A424: 'cleanup',
    0x8005A380: 'dispatch-entry',
    0x8005A5FC: 'SetVSync',
    0x8005A600: '0xBFC42600',
    0xBFC42160: 'init-rom',
    0xBFC425BC: 'handler-rom',
}
def annot(addr, val):
    if val in TARGETS: return TARGETS[val]
    for t,name in TARGETS.items():
        if val == t: return name
    # Match uncached alias
    if (val | 0x20000000) in TARGETS: return TARGETS[val|0x20000000]+'(uncached)'
    if (val & ~0x20000000) in TARGETS: return TARGETS[val&~0x20000000]+'(cached)'
    return None

print('PING:', send({"cmd":"ping"}))
print('PAUSE:', send({"cmd":"pause"}))
time.sleep(0.3)

# 1. Dump exception entry at 0x80000C80 (from jr $k0 → 0x00000C80)
print('\n=== Exception handler at 0x80000C80 (32 words) ===', flush=True)
d = read_ram(0x00000C80, 128)
if d: dump_words(d, 0x80000C80, annot)

# 2. Dump IRQ handler chain block at 0xA000E1F4, size 0x300 bytes
print('\n=== Handler chain block 0xA000E1F4..+0x300 ===', flush=True)
d = read_ram(0x0000E1F4, 0x300)
if d: dump_words(d, 0xA000E1F4, annot)

# 3. Dump 0x800DFEE0 context (64 bytes before, 64 after)
print('\n=== Around 0x800DFEE0 (where handler ptr lives) ===', flush=True)
d = read_ram(0x000DFEC0, 256)
if d: dump_words(d, 0x800DFEC0, annot)

# 4. Also check the TCB block at 0xA000E1EC, size 4*TCB (each TCB 0xC0 bytes)
print('\n=== 0xA000E1EC (TCB table, 4×0xC0=0x300 bytes) — overlapping with chain block? ===', flush=True)
d = read_ram(0x0000E1EC, 16)
if d: dump_words(d, 0xA000E1EC, annot)

# 5. Dump 0xA000E004 block, size 0x20
print('\n=== 0xA000E004..+0x20 (DCB?) ===', flush=True)
d = read_ram(0x0000E004, 0x30)
if d: dump_words(d, 0xA000E004, annot)

# 6. Dump 0xA000E028 EvCB
print('\n=== EvCB 0xA000E028..+0x1C0 (first 4 slots only, 28 bytes each) ===', flush=True)
d = read_ram(0x0000E028, 4*28)
if d: dump_words(d, 0xA000E028, annot)

print('\nCONTINUE:', send({"cmd":"continue"}))
