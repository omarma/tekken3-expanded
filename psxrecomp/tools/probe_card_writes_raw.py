"""Dump card-data-writes ring entry-by-entry."""
import socket, json, sys

count = int(sys.argv[1]) if len(sys.argv) > 1 else 200
host, port = '127.0.0.1', 4370
s = socket.create_connection((host, port))
s.settimeout(3.0)
s.sendall(json.dumps({'id': 1, 'cmd': 'card_data_writes', 'count': count}).encode() + b'\n')
buf = b''
while True:
    try: chunk = s.recv(65536)
    except socket.timeout: break
    if not chunk: break
    buf += chunk
    depth = 0; in_str = False; esc = False
    for c in buf:
        if esc: esc = False; continue
        if c == 0x5C: esc = True; continue
        if c == 0x22: in_str = not in_str; continue
        if in_str: continue
        if c == 0x7B: depth += 1
        elif c == 0x7D: depth -= 1
    if depth == 0 and buf.strip(): break
s.close()
obj = json.loads(buf.decode())
print(f"# total_seq={obj['total_seq']} avail={obj['avail']} count={obj['count']}")
for e in obj.get('entries', []):
    val_lo = int(e['value'], 16) & 0xFF
    print(f"#{e['seq']:>4} cyc={e['cyc']:>14} slot={e['slot']} idx={e['mc_idx']:>3} "
          f"st={e['mc_state']:>2} addr={e['addr']} val=0x{val_lo:02X} w={e['width']} "
          f"pc={e['store_pc']} func={e['func']}")
