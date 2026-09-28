"""Dump runtime A0/B0/C0 tables from DuckStation and search for VSync/registrar/init in each."""
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
    # Chunked
    out = b''
    off = 0
    while off < length:
        n = min(4096, length-off)
        r = send({"cmd":"read_ram","addr":f"0x{addr+off:08X}","len":n})
        if not r or not r.get('ok'): return None
        out += bytes.fromhex(r['hex'])
        off += n
    return out

TARGETS = {
    0x8005A5BC: 'handler',
    0x8005A540: 'registrar',
    0x8005A160: 'init_1FC42160',
    0x8005A5FC: 'SetVSync/CRCNT',
    0x8005A380: 'chain-install',
    0x8005A424: 'cleanup',
    0x80059C80: 'VSync(1FC41C80)',
    0x80059FC0: 'InitRCnt(1FC41FC0)',
    0x80059DA4: 'VSync-spin(1FC41DA4)',
    0x8005A600: '0xBFC42600',
    0x8005A640: '0xBFC42640',
    0x8005A70C: '0xBFC4270C',
    0x8005A090: 'jal-target(1FC42090)',
    0x8005A910: 'jal-target(1FC42910)',
    0x8005A980: 'jal-target(1FC42980)',
    0x8005AC00: 'jal-target(1FC42C00)',
}

def table_dump(name, base, length):
    d = read_ram(base, length)
    if not d: print(f'{name}: read failed'); return
    print(f'\n=== {name} @ 0x{base|0x80000000:08X} ({length} bytes) ===')
    for i in range(0, len(d), 4):
        if i+4 > len(d): break
        w = int.from_bytes(d[i:i+4],'little')
        annot = TARGETS.get(w, '')
        if not annot and w != 0 and (w & 0xFFFFFFF0) in {t & 0xFFFFFFF0 for t in TARGETS}:
            for t,n in TARGETS.items():
                if (w & 0xFFFFFFF0) == (t & 0xFFFFFFF0):
                    annot = f'{n}+{w-t:+d}'
                    break
        print(f'  +0x{i:03X}: 0x{w:08X}' + (f'  <-- {annot}' if annot else ''))

send({"cmd":"pause"})
time.sleep(0.3)

# A0 table = {ptr=0x00008648, size=0x2C0 = 704 bytes = 176 entries}
table_dump('A0 TABLE', 0x00008648, 0x2C0)
# B0 table = {ptr=0x00006EE0, size=0x320 = 800 bytes = 200 entries}
table_dump('B0 TABLE', 0x00006EE0, 0x320)

send({"cmd":"continue"})
