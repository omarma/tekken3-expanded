"""Filter SIO trace to entries with seq in [smin, smax]. Args: smin smax."""
import sys, json, re

if len(sys.argv) != 3:
    print('usage: trace_range.py SMIN SMAX', file=sys.stderr); sys.exit(1)
smin, smax = int(sys.argv[1]), int(sys.argv[2])

txt = sys.stdin.read()
m = re.search(r'\{.*\}', txt, re.S)
if not m:
    print('parse fail'); sys.exit(1)
j = json.loads(m.group(0))
ents = j.get('entries', [])
hits = [e for e in ents if smin <= e['seq'] <= smax]

print(f'(found {len(hits)} of {len(ents)} entries in [{smin},{smax}], total seq up to {j.get("total")})')
print('seq    tx    rx    mc(pre>post) dev(pre>post) ctrl    s0 s1 abrt ctr  func')
for e in hits:
    print(f"{e['seq']:>6} {e['tx']:>4} {e['rx']:>4}  "
          f"{e['mc_pre']:>2}>{e['mc_post']:<2}        "
          f"{e['dev_pre']:>2}>{e['dev_post']:<2}      "
          f"{e['ctrl']:>6} {e['slot0']:>2} {e['slot1']:>2} "
          f"{e['abort']:>4} {e['ctr']:>4}  {e['func']}")
