"""Check A0/B0/C0 vector installation and the device vtable."""
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

print('A0 vector at RAM 0x0A0:', read(0x800000A0, 32))
print('B0 vector at RAM 0x0B0:', read(0x800000B0, 32))
print('C0 vector at RAM 0x0C0:', read(0x800000C0, 32))
print()
print('Memcard shell state RAM 0x66948:', read(0x80066948, 4))
print('Vtable at RAM 0x974 (cd, format, ...):', read(0x80000974, 64))
print()
print('A0 table base ptr (likely RAM 0x200):', read(0x80000200, 16))
print('B0 table base ptr (likely RAM 0x208):', read(0x80000208, 16))
print('C0 table base ptr (likely RAM 0x210):', read(0x80000210, 16))
print()
print('RAM-aliased shell trampolines at 0x42960 (NOT relocated):', read(0x80042960, 48))
