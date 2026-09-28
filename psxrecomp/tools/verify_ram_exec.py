"""Cheap verification: does recomp execute the Beetle-identified RAM writer PCs?

Queries:
  1. dirty_ram_stats — block/insn/abort counters + per-PC histogram
  2. dispatch_check on every Beetle writer PC
  3. wtrace_dump filtered to 0x7568..0x756C
  4. wtrace_stats — total writes ever recorded
  5. dispatch_tail — last N dispatched targets (sanity that dispatch is alive)

Drives a CROSS press if --press is given (default: just queries current state).
"""
import socket, json, sys


PCS_OF_INTEREST = [
    0x0000445C,
    0x00004D6C,
    0x00004F0C,
    0x00004F54,
    0x00005DB8,
    0x00005DD0,
    0x00005DD8,
    0x00005EF4,
    0x00005FA8,
    0x00006524,
]


def call(d, timeout=15.0):
    s = socket.create_connection(('127.0.0.1', 4370))
    s.settimeout(timeout)
    s.sendall((json.dumps(d) + '\n').encode())
    buf = b''
    while True:
        try:
            chunk = s.recv(65536)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
        depth = 0; instr = False; esc = False
        for b in buf:
            if esc: esc = False; continue
            if b == 0x5C: esc = True; continue
            if b == 0x22: instr = not instr; continue
            if instr: continue
            if b == 0x7B: depth += 1
            elif b == 0x7D: depth -= 1
        if depth == 0 and buf.strip():
            break
    s.close()
    return json.loads(buf.decode())


def maybe_press():
    if '--press' not in sys.argv:
        return
    print('=== driving CROSS press ===')
    # set_input takes BIOS pad word (active-low). 0xBFFF = CROSS only.
    print(call({'id': 1, 'cmd': 'set_input', 'buttons': '0xBFFF'}))
    # Wait ~4s for shell to react and chain to spin.
    import time; time.sleep(4)
    # Release.
    print(call({'id': 2, 'cmd': 'clear_input'}))
    time.sleep(1)


print('=== ping ===')
print(json.dumps(call({'id': 0, 'cmd': 'ping'})))

maybe_press()

print()
print('=== dirty_ram_stats ===')
r = call({'id': 1, 'cmd': 'dirty_ram_stats'})
print(f"blocks_run = {r['blocks_run']}")
print(f"insns_run  = {r['insns_run']}")
print(f"aborts     = {r['aborts']}")
print(f"dirty_bitmap = {r['dirty_bitmap']}")
print(f"per_pc table size: {len(r.get('per_pc',[]))}")
hit_pcs = set()
for p in sorted(r.get('per_pc', []), key=lambda e: int(e['pc'], 16)):
    pc_int = int(p['pc'], 16)
    hit_pcs.add(pc_int)
    print(f"  pc={p['pc']:>10} hits={p['hits']:>10} insns={p['insns']:>10}")

print()
print('=== Beetle-writer PC dispatch_check ===')
for pc in PCS_OF_INTEREST:
    r = call({'id': 100 + pc, 'cmd': 'dispatch_check', 'addr': f'0x{pc:08X}'})
    in_dri = pc in hit_pcs
    print(f"  PC=0x{pc:08X}  static_dispatch={r.get('found','?')!s:>5}  "
          f"dirty_ram_interp_hit={in_dri}")

print()
print('=== wtrace_stats ===')
print(json.dumps(call({'id': 200, 'cmd': 'wtrace_stats'}), indent=2))

print()
print('=== wtrace ranges ===')
print(json.dumps(call({'id': 201, 'cmd': 'wtrace_ranges'}), indent=2))

print()
print('=== wtrace_dump (full ring, filtered to 0x7568-756C below) ===')
r = call({'id': 202, 'cmd': 'wtrace_dump'})
total = r.get('total_seq', 0)
entries = r.get('entries', [])
print(f"# total writes ever={total} returned={len(entries)}")

gate_writes = [e for e in entries
               if int(e.get('addr', '0x0'), 16) in (0x7568, 0x7569, 0x756A, 0x756B)]
print(f"# writes touching 0x7568..756B: {len(gate_writes)}")
for e in gate_writes[:50]:
    print(f"  seq={e.get('seq'):>6} addr={e.get('addr')} "
          f"old={e.get('old_val'):>10} new={e.get('new_val'):>10} "
          f"width={e.get('width')} ra={e.get('ra')} "
          f"frame={e.get('frame')} func={e.get('func_addr')}")

print()
print('=== dispatch_tail (last 20 dispatched targets — sanity) ===')
r = call({'id': 203, 'cmd': 'dispatch_tail', 'count': '20'})
print(f"# total dispatches={r.get('total')} returned={r.get('count')}")
for a in r.get('addrs', [])[-20:]:
    print(f"  {a}")
