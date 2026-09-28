"""Dump the card-read summary ring (first 32 successful reads, non-evicting)."""
import socket, json, sys

host, port = '127.0.0.1', 4370
s = socket.create_connection((host, port))
s.settimeout(3.0)
s.sendall(json.dumps({'id': 1, 'cmd': 'card_read_summary'}).encode() + b'\n')

buf = b''
while True:
    try:
        chunk = s.recv(65536)
    except socket.timeout:
        break
    if not chunk:
        break
    buf += chunk
    depth = 0; in_str = False; esc = False
    for c in buf:
        if esc:
            esc = False; continue
        if c == 0x5C:
            esc = True; continue
        if c == 0x22:
            in_str = not in_str; continue
        if in_str:
            continue
        if c == 0x7B:
            depth += 1
        elif c == 0x7D:
            depth -= 1
    if depth == 0 and buf.strip():
        break
s.close()

obj = json.loads(buf.decode())
print(f"# count={obj['count']} cap={obj['cap']}")
for e in obj.get('entries', []):
    print(f"#{e['seq']:>2}  cyc={e['cyc']:>14}  slot={e['slot']} cmd={e['cmd']} sec={e['sector']:>5}  "
          f"chk={e['checksum']} idx={e['data_idx']:>3}  func={e['current_func']} pc={e['last_store_pc']}  "
          f"dest={e['dest_ram']}  peek={e['data_peek']}")
