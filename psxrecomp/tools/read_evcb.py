#!/usr/bin/env python3
"""Read and decode EvCB table from runtime debug server."""
import json, socket, sys

def send(sock, cmd):
    raw = json.dumps(cmd).encode() + b'\n'
    sock.sendall(raw)
    data = b''
    while b'\n' not in data:
        data += sock.recv(65536)
    return json.loads(data.split(b'\n')[0])

sock = socket.socket()
sock.connect(('127.0.0.1', 4370))

# Read EvCB table in two chunks
r1 = send(sock, {'cmd': 'read_ram', 'addr': 0xE028, 'len': 256})
r2 = send(sock, {'cmd': 'read_ram', 'addr': 0xE028 + 256, 'len': 192})
full = bytes.fromhex(r1['hex'] + r2['hex'])

# Each EvCB is 0x1C=28 bytes, 16 entries
print(f"EvCB table at 0xE028, {len(full)} bytes, 16 entries")
print(f"{'Idx':>3} {'Class':>10} {'Spec':>10} {'Mode':>10} {'Status':>10} {'Func':>10}")
print("-" * 60)
for i in range(16):
    off = i * 28
    entry = full[off:off+28]
    cls = int.from_bytes(entry[0:4], 'little')
    spec = int.from_bytes(entry[4:8], 'little')
    mode = int.from_bytes(entry[8:12], 'little')
    status = int.from_bytes(entry[12:16], 'little')
    func = int.from_bytes(entry[16:20], 'little')
    if cls != 0 or status != 0:
        print(f"{i:3d} 0x{cls:08X} 0x{spec:08X} 0x{mode:08X} 0x{status:08X} 0x{func:08X}")

# Also read key state
print("\n--- Key addresses ---")
for name, addr in [
    ("I_STAT (via read)", 0x6D40),   # Read the pointer first
    ("flags 0x8600-0x860F", 0x8600),
    ("VSync counter", 0x79D9C),
    ("DAT_80066940", 0x66940),
]:
    r = send(sock, {'cmd': 'read_ram', 'addr': addr, 'len': 16})
    print(f"{name}: {r['hex']}")

sock.close()
