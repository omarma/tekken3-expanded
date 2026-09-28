"""Dump CORRECT A0/B0/C0 tables from DuckStation."""
import socket, json, time
HOST='127.0.0.1'; PORT=4371

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

def read_ram(addr, length):
    r = send({"cmd":"read_ram","addr":f"0x{addr:08X}","len":length})
    if not r or not r.get('ok'): return None
    return bytes.fromhex(r['hex'])

TARGETS = {
    0x8005A5BC:'handler', 0x8005A540:'registrar', 0x8005A160:'init_42160',
    0x8005A5FC:'SetVSync', 0x8005A380:'chain-install', 0x8005A424:'cleanup',
    0x80059C80:'VSync(41C80)', 0x80059FC0:'InitRCnt(41FC0)', 0x80059DA4:'spin(41DA4)',
    0x8005A600:'42600', 0x8005A640:'42640', 0x8005A70C:'4270C',
    0x8005A090:'42090', 0x8005A910:'42910', 0x8005A980:'42980', 0x8005AC00:'42C00',
    0x80059C7C:'41C7C', 0x80059F88:'41F88', 0x8005AE2C:'42E2C',
}

def dump(name, base, length):
    d = read_ram(base, length)
    if not d: print(f'{name}: read failed'); return
    print(f'\n=== {name} @ 0x{0x80000000|base:08X} ({length} bytes, {length//4} entries) ===')
    nonzero = []
    for i in range(0, len(d), 4):
        if i+4>len(d): break
        w=int.from_bytes(d[i:i+4],'little')
        if w==0: continue
        annot = TARGETS.get(w, '')
        # Try fuzzy match for shell kernel functions
        if not annot and 0x8005A000 <= w < 0x8005B000:
            # RAM alias of 0xBFC42xxx
            rom = w - 0x8005A000 + 0xBFC42000
            annot = f'shell_kern 0x{rom:08X}'
        elif not annot and 0x80059000 <= w < 0x8005A000:
            rom = w - 0x80059000 + 0xBFC41000
            annot = f'shell_kern 0x{rom:08X}'
        elif not annot and 0xBFC00000 <= w < 0xBFC80000:
            annot = f'ROM_direct'
        nonzero.append((i, w, annot))
    print(f'  {len(nonzero)} non-zero entries:')
    for i,w,annot in nonzero:
        idx = i // 4
        print(f'  [{idx:3d}] +0x{i:03X}: 0x{w:08X}' + (f'  {annot}' if annot else ''))

send({"cmd":"pause"}); time.sleep(0.3)
dump('A0 TABLE', 0x00000200, 0x100)   # A0:0..63 entries (probably enough)
dump('B0 TABLE', 0x00000874, 0x100)
dump('C0 TABLE', 0x00000674, 0x100)
send({"cmd":"continue"})
