"""Dump the card-data-writes ring (BIOS RAM destinations of incoming card bytes).

Each entry: (seq, cyc, addr, value, width, mc_state, mc_idx, slot, store_pc, func).
The mc_state values: 8=READ_DATA, 9=READ_CHK, 10=READ_END (or whatever your enum says).
mc_idx is 0..127 — the offset within the 128-byte sector that this byte represents.
"""
import socket, json, sys

count = int(sys.argv[1]) if len(sys.argv) > 1 else 1024
host, port = '127.0.0.1', 4370
s = socket.create_connection((host, port))
s.settimeout(3.0)
s.sendall(json.dumps({'id': 1, 'cmd': 'card_data_writes', 'count': count}).encode() + b'\n')

buf = b''
while True:
    try:
        chunk = s.recv(65536)
    except socket.timeout:
        break
    if not chunk:
        break
    buf += chunk
    depth = 0; in_str = False; esc = False
    for c in buf:
        if esc:
            esc = False; continue
        if c == 0x5C:
            esc = True; continue
        if c == 0x22:
            in_str = not in_str; continue
        if in_str:
            continue
        if c == 0x7B:
            depth += 1
        elif c == 0x7D:
            depth -= 1
    if depth == 0 and buf.strip():
        break
s.close()

obj = json.loads(buf.decode())
print(f"# total_seq={obj['total_seq']} avail={obj['avail']} count={obj['count']}")

# Group consecutive entries by destination buffer base.
entries = obj.get('entries', [])
if not entries:
    print("# no entries")
    sys.exit(0)

# Show summary: dest base inferred from each run of mc_idx 0..127.
i = 0
while i < len(entries):
    run = [entries[i]]
    j = i + 1
    while j < len(entries):
        # consecutive idx OR new run starts at idx 0
        prev = run[-1]
        cur = entries[j]
        if cur['mc_idx'] == prev['mc_idx'] + 1 and cur['slot'] == prev['slot']:
            run.append(cur)
            j += 1
        else:
            break
    base = run[0]
    end = run[-1]
    base_addr = int(base['addr'], 16)
    end_addr = int(end['addr'], 16)
    print(f"slot={base['slot']} idx_range=[{base['mc_idx']}..{end['mc_idx']}] "
          f"addr=0x{base_addr:08X}..0x{end_addr:08X} ({len(run)} bytes) "
          f"first_func={base['func']} first_pc={base['store_pc']} "
          f"first_val={base['value']}")
    i = j
