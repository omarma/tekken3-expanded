#!/usr/bin/env python3
import socket, json, struct, sys

port = int(sys.argv[1])
addr = int(sys.argv[2], 16)
count = int(sys.argv[3]) if len(sys.argv) > 3 else 4

s = socket.create_connection(('localhost', port), timeout=5)
s.sendall(f'{{"cmd":"read_ram","addr":"0x{addr:08X}","len":{count*4}}}\n'.encode())
data = b''
while b'\n' not in data:
    data += s.recv(4096)
s.close()
d = json.loads(data.split(b'\n')[0])
raw = bytes.fromhex(d['hex'])
for i in range(count):
    v = struct.unpack_from('<I', raw, i * 4)[0]
    print(f'  [{i}] 0x{v:08X}')
