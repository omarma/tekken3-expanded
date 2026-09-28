#!/usr/bin/env python3
"""Parse wtrace_dump for shell state variable transitions."""
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/shell_state_trace.json'
with open(path) as f:
    data = json.load(f)

entries = data.get('entries', [])
print(f"Total writes to shell state: {len(entries)}")
print()
print(f"{'Frame':>6} {'Old':>6} {'New':>6} {'Func':>12} {'RA':>12} {'Width':>5}")
print("-" * 55)

prev_val = None
for e in entries:
    old_str = e['old']
    new_str = e['new']
    old_val = int(old_str, 16) if isinstance(old_str, str) else old_str
    new_val = int(new_str, 16) if isinstance(new_str, str) else new_str
    # Only show actual state changes
    if new_val != prev_val:
        print(f"{e['frame']:6d} 0x{old_val:04X} 0x{new_val:04X} {e['func']:>12} {e['ra']:>12} {e.get('width', '?'):>5}")
        prev_val = new_val
