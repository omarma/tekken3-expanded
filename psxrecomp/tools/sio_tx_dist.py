#!/usr/bin/env python3
"""Show TX byte distribution in SIO trace."""
import json, sys
from collections import Counter

path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/beetle_sio_full.json'
with open(path) as f:
    data = json.load(f)

txs = Counter()
for e in data['entries']:
    tx = int(e['tx'], 16) if isinstance(e['tx'], str) else e['tx']
    txs[tx] += 1

print(f"Total: {data['total']}, Shown: {data['count']}")
print("TX byte distribution:")
for val, count in txs.most_common():
    print(f"  0x{val:02X}: {count}")
