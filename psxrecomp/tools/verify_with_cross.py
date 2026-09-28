"""Arm wtrace on 0x7568..0x756C, press CROSS, re-query everything."""
import socket, json, time


def call(d, timeout=15.0):
    s = socket.create_connection(('127.0.0.1', 4370))
    s.settimeout(timeout)
    s.sendall((json.dumps(d) + '\n').encode())
    buf = b''
    while True:
        try: chunk = s.recv(65536)
        except socket.timeout: break
        if not chunk: break
        buf += chunk
        depth = 0; instr = False; esc = False
        for b in buf:
            if esc: esc = False; continue
            if b == 0x5C: esc = True; continue
            if b == 0x22: instr = not instr; continue
            if instr: continue
            if b == 0x7B: depth += 1
            elif b == 0x7D: depth -= 1
        if depth == 0 and buf.strip(): break
    s.close()
    return json.loads(buf.decode())


PCS = [0x0000445C, 0x00004D6C, 0x00004F0C, 0x00004F54,
       0x00005DB8, 0x00005DD0, 0x00005DD8, 0x00005EF4, 0x00005FA8, 0x00006524]


def take_dispatch_baseline():
    """Snapshot dispatch_check status for every PC of interest."""
    out = {}
    for pc in PCS:
        r = call({'id': 100 + pc, 'cmd': 'dispatch_check', 'addr': f'0x{pc:08X}'})
        out[pc] = (r.get('found'), r.get('total'))
    return out


print('=== arm wtrace on 0x7568..0x756C ===')
print(call({'id': 1, 'cmd': 'wtrace_add', 'lo': '0x7568', 'hi': '0x756C'}))

print()
print('=== reset wtrace + dirty_ram counters (so post-CROSS counters are clean) ===')
print(call({'id': 2, 'cmd': 'wtrace_clear'}))

print()
print('=== baseline dispatch_check + dirty_ram_stats (pre-CROSS) ===')
pre_disp = take_dispatch_baseline()
pre_dri = call({'id': 3, 'cmd': 'dirty_ram_stats'})
print(f"PRE: blocks_run={pre_dri['blocks_run']} insns_run={pre_dri['insns_run']} "
      f"aborts={pre_dri['aborts']} dispatch_total={pre_disp[PCS[0]][1]}")
print(f"PRE per_pc: {[(p['pc'],p['hits']) for p in pre_dri.get('per_pc',[])]}")

print()
print('=== press CROSS for ~6 seconds ===')
print(call({'id': 4, 'cmd': 'set_input', 'buttons': '0xBFFF'}))
time.sleep(6)
print('=== release ===')
print(call({'id': 5, 'cmd': 'clear_input'}))
time.sleep(2)

print()
print('=== POST-CROSS dispatch_check ===')
post_disp = take_dispatch_baseline()
total_delta = post_disp[PCS[0]][1] - pre_disp[PCS[0]][1]
print(f"# dispatches during press window: {total_delta}")
print(f"# (dispatch_check 'found' searches the ring; True = hit somewhere in trace)")
for pc in PCS:
    print(f"  PC=0x{pc:08X}  found={post_disp[pc][0]!s:>5}  pre_found={pre_disp[pc][0]!s:>5}")

print()
print('=== POST-CROSS dirty_ram_stats ===')
post_dri = call({'id': 6, 'cmd': 'dirty_ram_stats'})
print(f"POST: blocks_run={post_dri['blocks_run']} insns_run={post_dri['insns_run']} "
      f"aborts={post_dri['aborts']}")
delta_blocks = post_dri['blocks_run'] - pre_dri['blocks_run']
delta_insns = post_dri['insns_run'] - pre_dri['insns_run']
delta_aborts = post_dri['aborts'] - pre_dri['aborts']
print(f"DELTA: blocks=+{delta_blocks} insns=+{delta_insns} aborts=+{delta_aborts}")
print('POST per_pc histogram:')
for p in sorted(post_dri.get('per_pc', []), key=lambda e: int(e['pc'], 16)):
    print(f"  pc={p['pc']:>10} hits={p['hits']:>10} insns={p['insns']:>10}")

# Check whether any of the Beetle writer PCs landed in the histogram
hit_pcs = {int(p['pc'], 16) for p in post_dri.get('per_pc', [])}
print()
print('=== Beetle writer PC ∈ dirty_ram_interp histogram? ===')
for pc in PCS:
    print(f"  0x{pc:08X}: {'YES' if pc in hit_pcs else 'no'}")

print()
print('=== POST-CROSS wtrace_dump (full ring, filtered to 0x7568..756B) ===')
r = call({'id': 7, 'cmd': 'wtrace_dump'})
total = r.get('total_seq', 0)
entries = r.get('entries', [])
gate_writes = [e for e in entries
               if int(e.get('addr', '0x0'), 16) in (0x7568, 0x7569, 0x756A, 0x756B)]
print(f"# total writes ever={total} returned={len(entries)} gate_hits={len(gate_writes)}")
for e in gate_writes[:30]:
    print(f"  seq={e.get('seq'):>5} addr={e.get('addr')} "
          f"old={e.get('old_val'):>10}->new={e.get('new_val'):>10} "
          f"width={e.get('width')} ra={e.get('ra')} pc={e.get('store_pc','?')} "
          f"frame={e.get('frame')}")
