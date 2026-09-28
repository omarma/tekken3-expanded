"""Check whether chain init at FUN_bfc158a8 has ever run."""
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


# Init at FUN_bfc158a8 should write:
#   sw t8, 0x7544(at)  ; t8 = 0x4d6c
#   sw t9, ?(at)       ; t9 = 0x4f90
#   sb t6, 0x7568(at)  ; slot 0 = 0x01
#   sb t7, 0x7569(at)  ; slot 1 = 0x01
#   sb zero, 0x755A    ; abort flag = 0
#   sb zero, 0x7264    ; slot toggle = 0
print('=== chain init evidence ===')
print(f'  0x7540..0x7550 (chain handler ptrs):  {read(0x80007540, 16)}')
print(f'  0x7568..0x7570 (gate bytes):          {read(0x80007568, 8)}')
print(f'  0x7264 (slot toggle):                 {read(0x80007264, 4)}')
print(f'  0x755A (abort flag byte):             {read(0x8000755A, 4)}')
print(f'  0x7258 (SIO MMIO base ptr):           {read(0x80007258, 4)}')
print()

# Function pointer tables that the chain dispatchers (FUN_bfc14cf4 + FUN_bfc15188)
# index into. If init populated them, they should contain RAM addresses (0x80004F54,
# 0x80005EF4, etc. — likely as physical addresses 0x000xxxxx).
print('=== chain step jump tables ===')
print(f'  0x6c70 (jt1 — 10 entries):  {read(0x80006c70, 40)}')
print(f'  0x6c98 (jt2 — 13 entries):  {read(0x80006c98, 52)}')
print(f'  0x6ccc (jt3 — 4 entries):   {read(0x80006ccc, 16)}')
print()

# Has the chain init function ever been dispatched?
print('=== dispatch_check on init/chain entries ===')
for pc, name in [(0x5DA8, 'FUN_bfc158a8 (init)'),
                 (0x5000, 'FUN_bfc14b00 (chain coord)'),
                 (0x51F4, 'FUN_bfc14cf4 (dispatcher 1)'),
                 (0x5688, 'FUN_bfc15188 (dispatcher 2)'),
                 (0x5EF4, '0x02 writer (NEW)'),
                 (0x5FA8, '0x04 writer (NEW)')]:
    r = call({'id': 100, 'cmd': 'dispatch_check', 'addr': f'0x{pc:08X}'})
    print(f"  0x{pc:08X} {name}: in_recent_ring={r.get('found')}")
print()

print(f"frame: {call({'id':0,'cmd':'ping'}).get('frame')}")
