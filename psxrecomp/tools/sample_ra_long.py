#!/usr/bin/env python3
"""Sample $ra and also sp+20 (saved ra on stack) to trace the full chain."""
import socket, json, sys, time, collections

HOST, PORT = "127.0.0.1", 4370
DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0

s = socket.socket()
s.connect((HOST, PORT))
s.settimeout(3.0)
buf = b""

def read_line():
    global buf
    while b"\n" not in buf:
        chunk = s.recv(16384)
        if not chunk: return None
        buf += chunk
    line, _, buf = buf.partition(b"\n")
    return line.decode()

def send(cmd):
    s.sendall(cmd.encode() + b"\n")
    return json.loads(read_line())

ra_hist = collections.Counter()
stack0_hist = collections.Counter()
n = 0
t_end = time.time() + DURATION

while time.time() < t_end:
    r = send('{"cmd":"get_registers"}')
    ra = r['gpr'][31]
    sp = r['gpr'][29]
    ra_hist[ra] += 1
    # Read saved $ra at sp+20 (common store-location)
    sp_int = int(sp, 16)
    sp20 = f"0x{(sp_int + 20) & 0xFFFFFFFF:08X}"
    r2 = send(f'{{"cmd":"read_ram","addr":"{sp20}","len":4}}')
    if r2.get('ok'):
        hex4 = r2['hex']
        # little-endian 4 bytes
        saved_ra = int.from_bytes(bytes.fromhex(hex4), 'little')
        stack0_hist[f"0x{saved_ra:08X}"] += 1
    n += 1

s.close()
print(f"samples: {n}")
print("--- $ra (register) ---")
for v, c in ra_hist.most_common(15):
    print(f"  {v}  {c:5}")
print("--- saved $ra at sp+20 (outer frame) ---")
for v, c in stack0_hist.most_common(15):
    print(f"  {v}  {c:5}")
