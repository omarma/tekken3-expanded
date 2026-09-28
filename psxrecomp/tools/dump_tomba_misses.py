"""Pull dirty_ram per_pc entries that fall in the Tomba game text range,
suitable for feeding back as TombaRecomp seeds."""
import socket, json, sys

port = int(sys.argv[1]) if len(sys.argv) > 1 else 4470

# Tomba game text: load=0x80010000, text_size=0x00088000 -> phys 0x10000-0x98000
GAME_TEXT_LO = 0x10000
GAME_TEXT_HI = 0x98000

def send_cmd(cmd, **kwargs):
    payload = {'id': 1, 'cmd': cmd}
    payload.update(kwargs)
    s = socket.create_connection(('127.0.0.1', port), timeout=5)
    s.sendall(json.dumps(payload).encode() + b'\n')
    data = b''
    while True:
        chunk = s.recv(65536)
        if not chunk: break
        data += chunk
        try: json.loads(data.decode()); break
        except: pass
    s.close()
    return json.loads(data.decode())

r = send_cmd('dirty_ram_stats')
if not r.get('ok'):
    print('error:', r); sys.exit(1)

game_misses = []
for entry in r.get('per_pc', []):
    pc = int(entry['pc'], 16)
    if GAME_TEXT_LO <= pc < GAME_TEXT_HI:
        game_misses.append((pc, entry['hits'], entry['insns']))

game_misses.sort(key=lambda x: -x[1])

print(f"Tomba game-text dirty_ram misses ({len(game_misses)} unique PCs):")
print(f"{'PC':>12}  {'hits':>8}  {'insns':>12}  virtual")
for pc, hits, insns in game_misses:
    vaddr = 0x80000000 | pc
    print(f"  0x{pc:08X}  {hits:>8}  {insns:>12}  0x{vaddr:08X}")

print(f"\nSeed lines for TombaRecomp seeds/ghidra_funcs.txt:")
for pc, hits, insns in game_misses:
    vaddr = 0x80000000 | pc
    print(f"0x{vaddr:08X}  # dirty_ram miss: {hits} hits, {insns} insns")
