#!/usr/bin/env python3
"""Analyze shell card SM state transitions from wtrace dump."""
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else 'wtrace_dump.json'
with open(path) as f:
    data = json.loads(f.read().strip())
entries = data.get('entries', [])
print(f'Total entries returned: {len(entries)}')

sm_addrs = ('0x00009f20','0x00009f24','0x00009f28','0x00009f2c')
sm = [e for e in entries if e['addr'].lower() in sm_addrs]
print(f'SM state writes: {len(sm)}')

seen = {}
for e in sm:
    k = (e['addr'], e['old'], e['new'])
    seen[k] = seen.get(k, 0) + 1
print('\nDistinct transitions:')
for k, n in sorted(seen.items(), key=lambda x: -x[1]):
    print(f'  {k[0]} {k[1]}->{k[2]}: {n}')

print('\nLast 20 SM transitions:')
for e in sm[-20:]:
    print(f"  seq={e['seq']:5} {e['addr']} {e['old']}->{e['new']} ra={e['ra']} func={e['func']} f={e.get('frame','?')}")

# Look for transitions to 4 (directory load)
to_4 = [e for e in sm if e['new'] == '0x00000004']
print(f"\nTransitions to state 4: {len(to_4)}")

# Also check 0x66940 transitions (screen state)
screen = [e for e in entries if e['addr'].lower() == '0x00066940']
print(f"\nScreen state writes: {len(screen)}")
for e in screen[-10:]:
    print(f"  seq={e['seq']:5} {e['old']}->{e['new']} ra={e['ra']} func={e['func']} f={e.get('frame','?')}")
