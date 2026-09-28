"""Check chain gate state and B0 dispatcher activity."""
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

print('Card chain state:')
print(f'  [0x74A8] (chain table base):   {read(0x800074A8, 4)}')
print(f'  [0x74AC] (chain handler 0):     {read(0x800074AC, 4)}  (should be 0x000049BC = FUN_bfc144bc)')
print(f'  [0x74B0] (chain handler 1):     {read(0x800074B0, 4)}  (should be 0x00004A4C)')
print(f'  [0x74B4] (chain entry NULL):    {read(0x800074B4, 4)}')
print(f'  [0x74B8] (pad poll gate):       {read(0x800074B8, 4)}  (set by FUN_bfc158a8 chain init)')
print(f'  [0x74BC] (chain coord gate):    {read(0x800074BC, 4)}  (set by FUN_bfc14770 chain enabler -> 1)')
print(f'  [0x74C4] (other card gate):     {read(0x800074C4, 4)}  (set by FUN_bfc15b9c open)')
print(f'  [0x74C8..0x74DC]:               {read(0x800074C8, 24)}')
print()
print('Dispatch_check on the API entry points:')
for pc, name in [
    (0x00005DA8, 'B0:0x4A InitCARD = FUN_bfc158a8'),
    (0x00004C70, 'B0:0x4B StartCARD = FUN_bfc14770'),
    (0x00004CF4, 'B0:0x4C StopCARD = FUN_bfc147F4'),
    (0x0000609C, 'B0:0x?? FUN_bfc15b9c'),
    (0x000049BC, 'FUN_bfc144bc (chain dispatcher tick)'),
    (0x00005000, 'FUN_bfc14b00 (chain coord)'),
    (0x00004B90, 'FUN_bfc14690 (chain installer)'),
    (0x000005E0, 'B0 dispatcher (RAM 0x5E0)'),
    (0x000005C4, 'A0 dispatcher (RAM 0x5C4)'),
]:
    r = call({'id': 100, 'cmd': 'dispatch_check', 'addr': f'0x{pc:08X}'})
    print(f"  0x{pc:08X} {name}: in_recent_ring={r.get('found')}")
