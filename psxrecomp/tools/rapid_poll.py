#!/usr/bin/env python3
"""Rapidly poll a RAM address and report unique values seen."""
import socket, json, struct, sys, time

port = int(sys.argv[1])
addr = int(sys.argv[2], 16)
duration = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0
label = sys.argv[4] if len(sys.argv) > 4 else "value"

seen = {}
reads = 0
start = time.time()

while time.time() - start < duration:
    try:
        s = socket.create_connection(('localhost', port), timeout=1)
        cmd = f'{{"cmd":"read_ram","addr":"0x{addr:08X}","len":4}}\n'
        s.sendall(cmd.encode())
        data = b''
        while b'\n' not in data:
            data += s.recv(4096)
        s.close()
        resp = json.loads(data.split(b'\n')[0])
        if resp.get('ok'):
            raw = bytes.fromhex(resp['hex'])
            val = struct.unpack_from('<I', raw, 0)[0]
            seen[val] = seen.get(val, 0) + 1
            reads += 1
    except:
        pass

elapsed = time.time() - start
print(f'{label} at 0x{addr:08X}: {reads} reads in {elapsed:.1f}s')
for val, count in sorted(seen.items()):
    print(f'  0x{val:08X} ({val:5d}): seen {count} times ({100*count/reads:.1f}%)')
