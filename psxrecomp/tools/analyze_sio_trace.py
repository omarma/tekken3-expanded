#!/usr/bin/env python3
"""Analyze sio_trace for abort patterns and state distribution."""
import json
import sys
from collections import Counter

path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/sio_trace_full.json'
with open(path) as f:
    data = json.load(f)

MC_NAMES = {
    0:'IDLE', 1:'CMD', 2:'ID1', 3:'ID2', 4:'ADDR_MSB', 5:'ADDR_LSB',
    6:'R_ACK1', 7:'R_ACK2', 8:'R_DATA', 9:'R_CHK', 10:'R_END',
}

# Count aborts by mc_state at abort
abort_states = Counter()
abort_funcs = Counter()
card_entries = 0
for e in data['entries']:
    tx = int(e['tx'], 16) if isinstance(e['tx'], str) else e['tx']
    if e['abort']:
        state_name = MC_NAMES.get(e['mc_pre'], str(e['mc_pre']))
        abort_states[state_name] += 1
        abort_funcs[e['func']] += 1
    if e['dev_post'] == 2 or e['dev_pre'] == 2:
        card_entries += 1

print(f"Total entries: {data['count']}, Card-related: {card_entries}")
print(f"\nAbort by mc_state at abort time:")
for state, count in abort_states.most_common():
    print(f"  {state}: {count}")

print(f"\nAbort by calling function:")
for func, count in abort_funcs.most_common():
    print(f"  {func}: {count}")

# Find entries past ADDR_MSB
past = [e for e in data['entries'] if e['mc_post'] > 4]
print(f"\nEntries reaching past ADDR_MSB (state >4): {len(past)}")
for e in past[:10]:
    tx = int(e['tx'], 16) if isinstance(e['tx'], str) else e['tx']
    rx = int(e['rx'], 16) if isinstance(e['rx'], str) else e['rx']
    pre = MC_NAMES.get(e['mc_pre'], str(e['mc_pre']))
    post = MC_NAMES.get(e['mc_post'], str(e['mc_post']))
    print(f"  seq={e['seq']} tx=0x{tx:02X} rx=0x{rx:02X} mc:{pre}->{post} func={e['func']}")

# Show a complete card transaction attempt (first one in buffer)
print(f"\n--- First complete card transaction in buffer ---")
in_card = False
for e in data['entries']:
    tx = int(e['tx'], 16) if isinstance(e['tx'], str) else e['tx']
    rx = int(e['rx'], 16) if isinstance(e['rx'], str) else e['rx']
    if tx == 0x81 and e['dev_post'] == 2:
        in_card = True
    if in_card:
        pre = MC_NAMES.get(e['mc_pre'], str(e['mc_pre']))
        post = MC_NAMES.get(e['mc_post'], str(e['mc_post']))
        flag = " *ABORT*" if e['abort'] else ""
        print(f"  seq={e['seq']} tx=0x{tx:02X} rx=0x{rx:02X} mc:{pre:>10}->{post:<10} func={e['func']}{flag}")
        if e['abort'] or (e['mc_post'] == 0 and e['mc_pre'] != 0):
            in_card = False
            break
