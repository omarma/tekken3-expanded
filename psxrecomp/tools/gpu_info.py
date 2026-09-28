#!/usr/bin/env python3
"""Read GPU state from debug server."""
import socket, json, sys

port = int(sys.argv[1]) if len(sys.argv) > 1 else 4370
s = socket.create_connection(('localhost', port), timeout=5)
s.sendall(b'{"cmd":"gpu_state"}\n')
data = b''
while b'\n' not in data:
    data += s.recv(4096)
s.close()
resp = json.loads(data.split(b'\n')[0])
if resp.get('ok'):
    for k, v in sorted(resp.items()):
        if k not in ('ok', 'id'):
            print(f'  {k}: {v}')
else:
    print(f'Error: {resp}')
