"""Dump A0/B0/C0 dispatchers and shell trampoline RAM contents."""
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
    return r.get('hex', '')

print('A0 dispatcher at RAM 0x5C4 (=ROM BFC100C4):')
print(' ', read(0x800005C4, 64))
print()
print('B0 dispatcher at RAM 0x5E0 (=ROM BFC100E0):')
print(' ', read(0x800005E0, 64))
print()
print('A0 table at RAM 0x874 (full first 0x100 = 64 entries):')
for off in range(0, 0x100, 16):
    print(f'  +{off:04X}:', read(0x80000874 + off, 16))
print()
print('B0 table at RAM 0x?? -- check via B0 dispatcher')
print()
print('Shell pad-state region [0x80079CB4..]:')
print(' ', read(0x80079CB4, 32))
print()
print('Card state structure 0x74C4..:')
print(' ', read(0x800074C4, 16))
