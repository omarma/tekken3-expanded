"""Dump dispatch_tail and summarize."""
import socket, json
from collections import Counter

def call(d):
    s = socket.create_connection(('127.0.0.1', 4370))
    s.settimeout(15.0)
    s.sendall((json.dumps(d) + '\n').encode())
    buf = b''
    while True:
        try: chunk = s.recv(65536)
        except socket.timeout: break
        if not chunk: break
        buf += chunk
        depth = 0; instr = False; esc = False
        for b in buf:
            if esc: esc = False; continue
            if b == 0x5C: esc = True; continue
            if b == 0x22: instr = not instr; continue
            if instr: continue
            if b == 0x7B: depth += 1
            elif b == 0x7D: depth -= 1
        if depth == 0 and buf.strip(): break
    s.close()
    return json.loads(buf.decode())

r = call({'id': 1, 'cmd': 'dispatch_tail', 'count': '4096'})
addrs = r.get('addrs', [])
c = Counter(addrs)
print(f"total ring={r.get('total')} returned={len(addrs)} unique={len(c)}")
print()
print('top 30:')
for a, n in c.most_common(30):
    print(f'  {a}  x{n}')
print()
print('Beetle writer PCs / chain coordinator presence in ring:')
for pc in ['0x00005EF4','0x00005FA8','0x00004F54','0x00005DD0','0x00005DD8',
           '0x00005000','0x000051F4','0x00005688','0x00005DA8',
           '0x00004D6C','0x0000445C','0x00006524']:
    print(f'  {pc}: x{c.get(pc, 0)}')
