"""Distribution of (bytes, terminal_state) across all txns."""
import sys, json, re
from collections import Counter

txt = sys.stdin.read()
m = re.search(r'\{.*\}', txt, re.S)
if not m:
    print('parse fail'); sys.exit(1)
j = json.loads(m.group(0))
ents = j.get('entries', [])
c = Counter((e['bytes'], e['terminal_state']) for e in ents)
print(f"total_closed={j.get('total_closed')}, returned={len(ents)}")
for (b, t), n in sorted(c.items()):
    print(f"  bytes={b:>3} ts={t:>2}: {n} txns")
