"""Check current state: gate writes, interp histogram, recent dispatch."""
import socket, json
from collections import Counter

def call(d):
    s = socket.create_connection(('127.0.0.1', 4370)); s.settimeout(15.0)
    s.sendall((json.dumps(d) + '\n').encode())
    buf = b''
    while True:
        try: c = s.recv(65536)
        except socket.timeout: break
        if not c: break
        buf += c
        if buf.count(b'{') == buf.count(b'}') and buf.strip(): break
    s.close()
    return json.loads(buf.decode())


print('=== ping ===')
print(call({'id': 0, 'cmd': 'ping'}))
print()

print('=== gate writes (wtrace) ===')
r = call({'id': 1, 'cmd': 'wtrace_dump'})
entries = r.get('entries', [])
gate = [e for e in entries if int(e.get('addr', '0x0'), 16) in (0x7568, 0x7569, 0x756A, 0x756B)]
print(f'total wtrace entries={len(entries)} gate hits={len(gate)}')
for e in gate[:30]:
    print(f"  seq={e.get('seq')} addr={e.get('addr')} new={e.get('new_val')} "
          f"ra={e.get('ra')} func={e.get('func_addr')} frame={e.get('frame')}")
print()

print('=== dirty_ram_stats (post-CROSS interp histogram) ===')
r = call({'id': 2, 'cmd': 'dirty_ram_stats'})
print(f"blocks_run={r['blocks_run']} insns_run={r['insns_run']} "
      f"aborts={r['aborts']} dirty_bitmap={r['dirty_bitmap']}")
for p in sorted(r.get('per_pc', []), key=lambda e: int(e['pc'], 16)):
    print(f"  pc={p['pc']:>10} hits={p['hits']:>10} insns={p['insns']:>10}")
print()

print('=== shell state machine ([0x80066940..0x80066954) ===')
r = call({'id': 3, 'cmd': 'read_ram', 'addr': '0x80066940', 'len': 20})
print(r)
print()

print('=== FUN_bfc14b00 chain-coord dispatch_check ===')
for pc in [0x4D6C, 0x5000, 0x51F4, 0x5688, 0x5DA8, 0x5EF4, 0x5FA8, 0x4F54]:
    r = call({'id': 100, 'cmd': 'dispatch_check', 'addr': f'0x{pc:08X}'})
    print(f"  PC=0x{pc:08X}: found={r.get('found')}  total={r.get('total')}")
