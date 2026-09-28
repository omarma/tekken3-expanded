"""Check shell card mode and chain progression details."""
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
    return int.from_bytes(bytes.fromhex(hexstr[:8]), 'little')

print(f"frame: {call({'id':0,'cmd':'ping'}).get('frame')}")
print()
print('=== shell card mode flags ===')
for addr, label in [
    (0x80066bc0, '_DAT_80066bc0 (card mode: 6=DELETE, 7=LOAD_DIR)'),
    (0x80066948, '[0x66948] shell state (0x32 = MEMCARD)'),
    (0x80066940, '[0x66940] shell substate'),
    (0x80066944, '[0x66944] shell counter'),
    (0x800666f8, '[0x666f8] one-shot init done flag'),
]:
    print(f'  {label}: {read(addr, 4)}')

print()
print('=== chain progression detail ===')
# These addresses come from FUN_bfc14b00 + chain steps logic
for addr, label in [
    (0x80007550, '[0x7550] chain mode'),
    (0x80007554, '[0x7554] chain step idx'),
    (0x80007264, '[0x7264] slot toggle'),
    (0x800072F0, '[0x72F0] (1 byte/VBLANK?)'),
    (0x80007568, 'gates (4 bytes)'),
    (0x80007560, 'accumulators slot 0..3 (16 bytes)'),
    (0x80007570, '[0x7570..0x7575] (per-slot status?)'),
]:
    n = 16 if 'accumulators' in label else 4
    print(f'  {label}: {read(addr, n)}')

print()
print('=== sector being requested ===')
# After chain step, the sector # to read is probably stored somewhere.
# Common locations: per-slot state struct
for addr, label in [
    (0x80007510, '[0x7510..0x7530] per-slot R state'),
]:
    print(f'  {label}: {read(addr, 32)}')
