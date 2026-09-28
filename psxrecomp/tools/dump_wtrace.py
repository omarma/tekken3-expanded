#!/usr/bin/env python3
"""Dump write trace entries for a specific address range."""
import socket, json, sys

port = int(sys.argv[1]) if len(sys.argv) > 1 else 4370
filter_lo = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x79EB0
filter_hi = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x79EC0

def to_int(v):
    if isinstance(v, str):
        return int(v, 16) if v.startswith('0x') else int(v)
    return v

s = socket.create_connection(('localhost', port), timeout=10)
s.sendall(b'{"cmd":"wtrace_dump","start":0,"count":200}\n')
data = b''
while b'\n' not in data:
    chunk = s.recv(65536)
    if not chunk:
        break
    data += chunk
s.close()

resp = json.loads(data.split(b'\n')[0])
if not resp.get('ok'):
    print(f'Error: {resp}')
    sys.exit(1)

entries = resp.get('entries', [])
print(f'Total trace entries: {len(entries)}')
found = 0
for e in entries:
    phys = to_int(e.get('addr', 0))
    if filter_lo <= phys < filter_hi:
        found += 1
        func_val = to_int(e.get('func', 0))
        old_val = to_int(e.get('old', 0))
        new_val = to_int(e.get('new', 0))
        ra_val = to_int(e.get('ra', 0))
        w = to_int(e.get('width', 0))
        frame = e.get('frame', '?')
        print(f'  addr=0x{phys:08X} old=0x{old_val:08X} new=0x{new_val:08X} '
              f'w={w} func=0x{func_val:08X} ra=0x{ra_val:08X} frame={frame}')

if found == 0:
    print(f'No writes to range 0x{filter_lo:08X}-0x{filter_hi:08X}')
    print(f'Sample entries:')
    for e in entries[:5]:
        phys = to_int(e.get('addr', 0))
        new_val = to_int(e.get('new', 0))
        func_val = to_int(e.get('func', 0))
        print(f'  addr=0x{phys:08X} new=0x{new_val:08X} func=0x{func_val:08X}')
