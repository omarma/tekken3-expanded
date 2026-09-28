"""Probe the card txn ring directly via TCP. Server streams partial JSON."""
import socket, json, sys

count = int(sys.argv[1]) if len(sys.argv) > 1 else 16
host, port = '127.0.0.1', 4370
s = socket.create_connection((host, port))
s.settimeout(3.0)
s.sendall(json.dumps({'id': 1, 'cmd': 'card_txn_dump', 'count': count}).encode() + b'\n')

buf = b''
while True:
    try:
        chunk = s.recv(65536)
    except socket.timeout:
        break
    if not chunk:
        break
    buf += chunk
    # check brace balance (account for strings naively)
    depth = 0
    in_str = False
    esc = False
    for c in buf:
        if esc:
            esc = False
            continue
        if c == 0x5C:
            esc = True
            continue
        if c == 0x22:  # "
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == 0x7B:  # {
            depth += 1
        elif c == 0x7D:  # }
            depth -= 1
    if depth == 0 and buf.strip():
        break
s.close()

print(buf.decode(errors='replace'))
