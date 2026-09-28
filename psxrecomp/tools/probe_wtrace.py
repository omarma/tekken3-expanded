"""Filtered wtrace dump — only writes to specific address range."""
import socket, json, sys

lo = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x7560
hi = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x7570
host, port = '127.0.0.1', 4370
s = socket.create_connection((host, port))
s.settimeout(5.0)
s.sendall(json.dumps({'id': 1, 'cmd': 'wtrace', 'lo': f'0x{lo:08X}', 'hi': f'0x{hi:08X}'}).encode() + b'\n')
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
text = buf.decode().strip()
# Strip trailing junk
if '\n{' in text:
    text = text.split('\n')[-1]
try:
    obj = json.loads(text)
except Exception as e:
    print('parse fail:', e)
    print(text[:600])
    sys.exit(1)
entries = obj.get('entries', [])
print(f"# wtrace 0x{lo:08X}..0x{hi:08X}  total={obj.get('total','?')}  count_in_range={len(entries)}")
for e in entries[:200]:
    print(f"#{e.get('seq'):>5} addr={e.get('addr')} {e.get('width','?')}B  "
          f"{e.get('old_val','?')}->{e.get('new_val','?')}  "
          f"pc={e.get('ra','?')}/{e.get('store_pc','?')}  func={e.get('func_addr','?')}  frame={e.get('frame','?')}")
