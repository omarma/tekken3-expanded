"""Dump C0 table at RAM 0x674."""
import socket, json

def call(d):
    s = socket.create_connection(('127.0.0.1', 4370)); s.settimeout(15.0)
    s.sendall((json.dumps(d) + '\n').encode())
    buf = b''
    while True:
        try: c = s.recv(65536)
        except socket.timeout: break
        if not c: break
        buf += c
        if buf.count(b'{') == buf.count(b'}') and buf.strip(): break
    s.close()
    return json.loads(buf.decode())

def read(addr, n):
    r = call({'id': 1, 'cmd': 'read_ram', 'addr': f'0x{addr:08X}', 'len': n})
    return bytes.fromhex(r.get('hex', ''))

c0 = read(0x80000674, 0x100)
print(f'C0 table @ RAM 0x674 ({len(c0)} bytes):')
for i in range(0, len(c0), 4):
    val = int.from_bytes(c0[i:i+4], 'little')
    note = ''
    if val == 0x00005DA8: note = ' <-- FUN_bfc158a8 (chain init)'
    if val == 0x00004C70: note = ' <-- FUN_bfc14770 (chain enabler)'
    if val == 0x0000609C: note = ' <-- FUN_bfc15b9c'
    if val == 0x00004B90: note = ' <-- FUN_bfc14690 (chain installer B0:13)'
    if val == 0xBFC0C2E8: note = ' <-- FUN_bfc0c2e8 (BootInitMemcards!!)'
    if val == 0x000005C4: note = ' <-- A0 dispatcher'
    if val == 0x000005E0: note = ' <-- B0 dispatcher'
    if val:
        print(f'  C0[0x{i//4:02X}] (off+0x{i:03X}): 0x{val:08X}{note}')
