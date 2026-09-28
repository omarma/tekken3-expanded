"""Probe A0/B0/C0 kernel vector tables and the RAM trampoline chain."""
import socket, json, time, struct

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

def dump(data, base, label=''):
    print(f'--- {label} 0x{base:08X}..+0x{len(data):X} ---', flush=True)
    for i in range(0, len(data), 16):
        words = [int.from_bytes(data[i+j:i+j+4],'little') for j in range(0, min(16,len(data)-i), 4)]
        print(f'  0x{base+i:08X}: ' + ' '.join(f'{w:08X}' for w in words), flush=True)

send({"cmd":"pause"})
time.sleep(0.3)

# A0/B0/C0 trampolines at RAM 0xA0, 0xB0, 0xC0
for name, addr in [('A0',0xA0),('B0',0xB0),('C0',0xC0)]:
    d = read_ram(addr, 16)
    if d: dump(d, 0x80000000|addr, f'{name} vector trampoline')

# Now, each A0/B0/C0 dispatcher loads a function pointer from a table. The table
# base is computed internally. Let me scan a wider window around common locations
# where the A0/B0/C0 pointer tables might live.

# Based on standard PS1 layout, tables are often at 0x80000200..0x80000400 or in
# the kernel RAM 0x8000_0500+. Let's dump that.
d = read_ram(0x00000000, 0x200)
if d: dump(d, 0x80000000, 'RAM 0x80000000..0x200 (vectors)')

# Search kernel RAM 0x80000500..0x80009000 for the handler address 0x8005A5BC
# AND the registrar address 0x8005A540 AND SetVSync 0x8005A5FC
print('\n--- Searching kernel RAM 0x80000500..0x80009000 for shell kernel ptrs ---', flush=True)
d = read_ram(0x00000500, 0x8B00)
if d:
    targets = {
        bytes.fromhex('bca50580'): '0x8005A5BC handler',
        bytes.fromhex('40a50580'): '0x8005A540 registrar',
        bytes.fromhex('60a10580'): '0x8005A160 init',
        bytes.fromhex('fca50580'): '0x8005A5FC SetVSync',
        bytes.fromhex('24a40580'): '0x8005A424 cleanup',
        bytes.fromhex('80a30580'): '0x8005A380 chain-install',
    }
    for m,label in targets.items():
        pos=0
        while True:
            i=d.find(m,pos)
            if i<0: break
            a = 0x80000000 | (0x500 + i)
            print(f'  {label}: at 0x{a:08X}', flush=True)
            pos = i+1

send({"cmd":"continue"})
print('RESUMED', flush=True)
