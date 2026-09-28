"""Dump a single card txn's full TX/RX bytes given txn_seq + nearby SIO trace."""
import sys, json, re

txt = sys.stdin.read()
m = re.search(r'\{.*\}', txt, re.S)
if not m:
    print('parse fail'); sys.exit(1)
j = json.loads(m.group(0))
ents = j.get('entries', [])

# Print first txn that has bytes >= 15
for e in ents:
    if e.get('bytes', 0) >= 10:
        print(f"=== txn {e['txn_seq']}: slot={e['slot']} cmd={e['cmd']} "
              f"sect={e['sector']} bytes={e['bytes']} ts={e['terminal_state']} "
              f"reason={e['end_reason']} start_byte_seq={e['start_byte_seq']} "
              f"end_byte_seq={e['end_byte_seq']} ===")
        print(f"  start_func={e['start_func']} end_func={e['end_func']}")
        for i, (tx, rx) in enumerate(zip(e['tx'], e['rx'])):
            print(f"  byte[{i:>2}] tx={tx} rx={rx}")
        print()
