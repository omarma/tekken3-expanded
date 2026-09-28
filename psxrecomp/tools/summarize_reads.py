"""Summarize card_read_summary output."""
import socket, json

s = socket.create_connection(('127.0.0.1', 4370)); s.settimeout(15.0)
s.sendall((json.dumps({'id':1,'cmd':'card_read_summary'}) + '\n').encode())
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
r = json.loads(buf.decode())
print(f"count={r['count']}/{r['cap']}")
for e in r['entries']:
    print(f"  slot={e['slot']} sec={e['sector']:>4d} cmd={e['cmd']} "
          f"chk={e['checksum']} dest={e['dest_ram']} peek={e['data_peek'][:32]}")
