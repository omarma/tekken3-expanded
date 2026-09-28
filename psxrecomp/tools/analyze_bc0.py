#!/usr/bin/env python3
import json, sys
path = sys.argv[1] if len(sys.argv) > 1 else 'bc0_wtrace.json'
with open(path) as f:
    d = json.loads(f.read())
es = d.get('entries', [])
print(f'Total: {len(es)}')
seen = {}
for e in es:
    k = (e['addr'], e['old'], e['new'])
    seen[k] = seen.get(k, 0) + 1
print('\nDistinct transitions:')
for k, n in sorted(seen.items(), key=lambda x: -x[1]):
    print(f'  {k[0]} {k[1]}->{k[2]}: {n}')

print('\nLast 20:')
for e in es[-20:]:
    print(f"  seq={e['seq']} {e['addr']} {e['old']}->{e['new']} ra={e['ra']} func={e['func']} f={e.get('frame','?')}")
