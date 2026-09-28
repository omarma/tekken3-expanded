"""Audit SIO byte trace: show per-byte mc_state, ctrl, slot states."""
import sys, json, re

txt = sys.stdin.read()
m = re.search(r'\{.*\}', txt, re.S)
if not m:
    print('parse fail'); sys.exit(1)
j = json.loads(m.group(0))
ents = j.get('entries', [])

print('seq    tx    rx    mc(pre>post)  dev(pre>post)  ctrl    s0  s1  abrt  ctr  func')
print('-' * 95)
for e in ents:
    print(f"{e['seq']:>6} {e['tx']:>4} {e['rx']:>4}   "
          f"{e['mc_pre']:>2} > {e['mc_post']:<2}        "
          f"{e['dev_pre']:>2} > {e['dev_post']:<2}      "
          f"{e['ctrl']:>6} {e['slot0']:>3} {e['slot1']:>3} {e['abort']:>5} {e['ctr']:>4}  "
          f"{e['func']}")
