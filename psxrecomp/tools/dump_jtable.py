#!/usr/bin/env python3
"""Dump a jump table from PSX RAM via debug server."""
import socket, json, struct, sys

port = int(sys.argv[1]) if len(sys.argv) > 1 else 4370
addr = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x8005AD0C
count = int(sys.argv[3]) if len(sys.argv) > 3 else 24
base_state = int(sys.argv[4]) if len(sys.argv) > 4 else 2

s = socket.create_connection(('localhost', port), timeout=5)
cmd = f'{{"cmd":"read_ram","addr":"0x{addr:08X}","len":{count*4}}}\n'
s.sendall(cmd.encode())
data = b''
while b'\n' not in data:
    data += s.recv(65536)
s.close()

resp = json.loads(data.split(b'\n')[0])
raw = bytes.fromhex(resp['hex'])
for i in range(count):
    val = struct.unpack_from('<I', raw, i * 4)[0]
    state = base_state + i
    print(f'  state {state:2d} (idx {i:2d}): 0x{val:08X}')
