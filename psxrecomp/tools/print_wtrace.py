#!/usr/bin/env python3
import json, sys
d = json.load(open(sys.argv[1]))
print(f"total={d['total']} captured={d['count']}")
for e in d['entries']:
    print(f"seq={e['seq']:4}  addr={e['addr']}  old={e['old']}  new={e['new']}  ra={e['ra']}  w={e['w']}")
