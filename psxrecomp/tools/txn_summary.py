"""Summarize card txns: per-txn line + max stats."""
import sys, json, re

txt = sys.stdin.read()
m = re.search(r'\{.*\}', txt, re.S)
if not m:
    print('parse fail'); sys.exit(1)
j = json.loads(m.group(0))
ents = j.get('entries', [])

for e in ents:
    print(f"txn {e.get('txn_seq')}: slot={e.get('slot')} cmd={e.get('cmd')} "
          f"sect={e.get('sector')} bytes={e.get('bytes')} "
          f"ts={e.get('terminal_state')} reason={e.get('end_reason')}")

if ents:
    mb = max(e.get('bytes',0) for e in ents)
    mt = max(e.get('terminal_state',0) for e in ents)
    print(f"\n[max bytes/txn={mb}, max terminal_state={mt}, total_closed={j.get('total_closed')}]")
