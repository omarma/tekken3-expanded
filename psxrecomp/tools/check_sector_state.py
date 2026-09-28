"""Snapshot full chain state for sector-progression debugging.

Captures everything the user listed:
- requested sector number / current slot / chain state counter
- [0x7568+slot] gate bytes
- [0x7560+slot*4] checksum accumulators
- [0x72F0] / [0x74BC] / [0x75C0] / [0x755A] state flags
- dispatch presence for chain step handlers
"""
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
        depth = 0; in_str = False; esc = False
        for b in buf:
            if esc: esc = False; continue
            if b == 0x5C: esc = True; continue
            if b == 0x22: in_str = not in_str; continue
            if in_str: continue
            if b == 0x7B: depth += 1
            elif b == 0x7D: depth -= 1
        if depth == 0 and buf.strip(): break
    s.close()
    return json.loads(buf.decode())

def read(addr, n=4):
    r = call({'id': 1, 'cmd': 'read_ram', 'addr': f'0x{addr:08X}', 'len': n})
    return r.get('hex', '?')

def le_word(hexstr):
    if len(hexstr) < 8: return None
    b = bytes.fromhex(hexstr[:8])
    return int.from_bytes(b, 'little')

print(f"frame: {call({'id':0,'cmd':'ping'}).get('frame')}")
print()
print('=== chain state flags ===')
for addr, label in [
    (0x800072F0, '[0x72F0]'),
    (0x800074BC, '[0x74BC] (chain coord gate)'),
    (0x800075C0, '[0x75C0]'),
    (0x8000755A, '[0x755A] (abort flag, byte)'),
    (0x80007264, '[0x7264] (slot toggle, byte)'),
    (0x80007558, '[0x7558] (chain step?)'),
    (0x8000755C, '[0x755C] (chain step?)'),
]:
    print(f'  {label}: {read(addr, 4)}')

print()
print('=== gate bytes [0x7568..0x7570] (4 slots) ===')
gates = read(0x80007568, 8)
for i in range(min(4, len(gates)//2)):
    print(f'  slot {i}: 0x{gates[i*2:i*2+2]}')

print()
print('=== checksum accumulators [0x7560..0x756F] (4 slots * 4 bytes) ===')
acc = read(0x80007560, 16)
for i in range(4):
    if i*8+8 <= len(acc):
        print(f'  slot {i}: 0x{acc[i*8:i*8+8]}')

print()
print('=== chain handler ptrs [0x7540..0x7550] ===')
ptrs = read(0x80007540, 16)
for i in range(4):
    if i*8+8 <= len(ptrs):
        v = le_word(ptrs[i*8:i*8+8])
        print(f'  +{i*4:04X}: 0x{v:08X}')

print()
print('=== dispatch_check on chain step handlers ===')
# jt2 (READ chain) entries from disasm
jt2_entries = [0x000056E8, 0x00005768, 0x0000579C, 0x00005834,
               0x00005870, 0x000058B4, 0x000058E8, 0x00005918,
               0x00005954, 0x00005990, 0x00005A00, 0x00005A58, 0x00005AB0]
for i, pc in enumerate(jt2_entries):
    r = call({'id': 1, 'cmd': 'dispatch_check', 'addr': f'0x{pc:08X}'})
    print(f'  jt2[{i:>2}] 0x{pc:08X}: in_ring={r.get("found")}')

print()
print('=== chain step jump tables (verify intact) ===')
print(f'  jt1@0x6c70: {read(0x80006c70, 8)}...')
print(f'  jt2@0x6c98: {read(0x80006c98, 8)}...')
print(f'  jt3@0x6ccc: {read(0x80006ccc, 8)}...')
