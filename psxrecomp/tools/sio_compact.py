"""Compact SIO trace dump."""
import socket, json, sys

def call(d):
    s = socket.create_connection(('127.0.0.1', 4370)); s.settimeout(15.0)
    s.sendall((json.dumps(d) + '\n').encode())
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
    return json.loads(buf.decode())

count = int(sys.argv[1]) if len(sys.argv) > 1 else 200
r = call({'id': 1, 'cmd': 'sio_trace', 'count': str(count)})
print(f"total={r['total']} returned={r['count']}")
for e in r['entries']:
    abort = '!' if e.get('abort') else ' '
    print(f"  seq={e['seq']:>6} tx={e['tx']} rx={e['rx']} ctrl={e['ctrl']} fn={e['func']} {abort} dev0/1={e.get('slot0','?')}/{e.get('slot1','?')}")
