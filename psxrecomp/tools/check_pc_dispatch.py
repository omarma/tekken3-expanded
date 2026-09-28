"""Check what fn_entries have happened, filter by addr range. Args: addr_lo addr_hi [max]"""
import socket, json, sys
from collections import Counter

addr_lo = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0
addr_hi = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0xFFFFFFFF
max_count = int(sys.argv[3]) if len(sys.argv) > 3 else 100000

def call(d):
    s = socket.create_connection(("127.0.0.1", 4370), timeout=120)
    s.sendall((json.dumps(d) + "\n").encode())
    buf = b""
    while True:
        c = s.recv(65536)
        if not c: break
        buf += c
        if buf.strip().endswith(b'}'):
            try: json.loads(buf.decode()); break
            except: continue
    s.close()
    return json.loads(buf.decode())

r = call({'id': 1, 'cmd': 'fn_entry_dump',
          'addr_lo': f'0x{addr_lo:08X}', 'addr_hi': f'0x{addr_hi:08X}',
          'max_count': max_count})
entries = r.get('entries', [])
print(f"total fn_entries={r.get('total')} oldest={r.get('oldest')} returned={len(entries)}")
by_func = Counter()
by_func_t1 = {}
for e in entries:
    by_func[e['func']] += 1
    by_func_t1.setdefault(e['func'], Counter())[e['t1']] += 1
for func, n in by_func.most_common(40):
    t1s = by_func_t1[func].most_common(3)
    t1str = ' '.join(f"t1={t} ({c})" for t, c in t1s)
    print(f"  {n:>6}× func={func}  {t1str}")
