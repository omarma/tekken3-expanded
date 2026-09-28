"""Collect dirty_ram dispatch misses in the game text range and append
new unique addresses to a persistent log file. Run this during gameplay
to build up the seed list over time.

Usage: python3 collect_game_misses.py <port> <game_text_lo> <game_text_hi> <output_file>
Example (Tomba): python3 collect_game_misses.py 4470 0x10000 0x98000 seeds/dirty_ram_misses.txt
"""
import socket, json, sys, os

port      = int(sys.argv[1], 0) if len(sys.argv) > 1 else 4470
lo        = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x10000
hi        = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0x98000
out_file  = sys.argv[4]         if len(sys.argv) > 4 else 'dirty_ram_misses.txt'

def send(cmd, **kw):
    s = socket.create_connection(('127.0.0.1', port), timeout=5)
    s.sendall(json.dumps({'id':1,'cmd':cmd,**kw}).encode() + b'\n')
    d = b''
    while True:
        c = s.recv(65536)
        if not c: break
        d += c
        try: json.loads(d.decode()); break
        except: pass
    s.close()
    return json.loads(d.decode())

# Load existing known addresses
known = set()
if os.path.exists(out_file):
    with open(out_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                try:
                    known.add(int(line.split()[0], 0))
                except:
                    pass

r = send('dirty_ram_stats')
if not r.get('ok'):
    print('error:', r); sys.exit(1)

new_entries = []
for entry in r.get('per_pc', []):
    pc = int(entry['pc'], 16)
    if lo <= pc < hi:
        vaddr = 0x80000000 | pc
        if vaddr not in known:
            new_entries.append((vaddr, entry['hits'], entry['insns']))
            known.add(vaddr)

if new_entries:
    with open(out_file, 'a') as f:
        for vaddr, hits, insns in sorted(new_entries, key=lambda x: -x[1]):
            f.write(f"0x{vaddr:08X}  # dirty_ram miss: {hits} hits, {insns} insns\n")
    print(f"Appended {len(new_entries)} new addresses to {out_file}")
    for vaddr, hits, insns in sorted(new_entries, key=lambda x: -x[1]):
        print(f"  0x{vaddr:08X}  ({hits} hits, {insns} insns)")
else:
    print(f"No new addresses (already have {len(known)} in {out_file})")
