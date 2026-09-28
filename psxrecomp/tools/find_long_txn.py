"""Find long (>=10 bytes) txns. Print byte_seq ranges."""
import sys, json, re
m = re.search(r'\{.*\}', sys.stdin.read(), re.S)
if not m:
    print('parse fail'); sys.exit(1)
j = json.loads(m.group(0))
for e in j.get('entries', []):
    if e.get('bytes', 0) >= 10:
        print(f"txn {e['txn_seq']}: bytes={e['bytes']} ts={e['terminal_state']} "
              f"bs=[{e['start_byte_seq']},{e['end_byte_seq']}]")
