#!/usr/bin/env python3
import json, sys
path = sys.argv[1] if len(sys.argv) > 1 else 'evcb_writes.json'
with open(path) as f:
    d = json.loads(f.read())
entries = d.get('entries', [])
print(f"Total entries: {len(entries)}")
seen = {}
for e in entries:
    k = (e['addr'], e['old'], e['new'])
    seen[k] = seen.get(k, 0) + 1
print('\nDistinct transitions:')
for k, n in sorted(seen.items(), key=lambda x: -x[1]):
    print(f"  {k[0]} {k[1]}->{k[2]}: {n}")

# Status field offsets are +4: 0xE0F0, 0xE10C, 0xE128, 0xE144
status_addrs = ('0x0000e0f0', '0x0000e10c', '0x0000e128', '0x0000e144')
print('\nStatus field writes (the firing/ack transitions):')
for e in entries:
    if e['addr'].lower() in status_addrs:
        print(f"  seq={e['seq']} {e['addr']} {e['old']}->{e['new']} ra={e['ra']} func={e['func']} f={e.get('frame','?')}")
