#!/usr/bin/env python3
import json, sys
path = sys.argv[1] if len(sys.argv) > 1 else 'sio_trace.json'
with open(path) as f:
    d = json.loads(f.read())
es = d.get('entries', [])
print(f'Total entries: {len(es)}')
print()
print(f'idx | seq    | frame | tx   rx   ctrl  mc state | in_exc ctr')
for i, e in enumerate(es[-50:]):
    print(f"{i:3d} | seq={e.get('seq','?')} f={e.get('frame','?')} tx={e.get('tx','?')} rx={e.get('rx','?')} ctrl={e.get('ctrl','?')} mc={e.get('mc','?')} ie={e.get('in_exc','?')} ctr={e.get('ctr','?')}")
