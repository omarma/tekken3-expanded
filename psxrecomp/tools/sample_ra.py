#!/usr/bin/env python3
"""Sample $ra + EPC over N seconds to profile hot code regions."""
import socket, json, sys, time, collections

HOST, PORT = "127.0.0.1", 4370
DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0

s = socket.socket()
s.connect((HOST, PORT))
s.settimeout(2.0)
buf = b""
ra_hist = collections.Counter()
epc_hist = collections.Counter()
n_samples = 0
t_end = time.time() + DURATION

def read_line():
    global buf
    while b"\n" not in buf:
        chunk = s.recv(16384)
        if not chunk: return None
        buf += chunk
    line, _, buf = buf.partition(b"\n")
    return line.decode()

while time.time() < t_end:
    s.sendall(b'{"cmd":"get_registers"}\n')
    line = read_line()
    if not line: break
    d = json.loads(line)
    ra = d['gpr'][31]
    epc = d['cop0_epc']
    ra_hist[ra] += 1
    epc_hist[epc] += 1
    n_samples += 1

s.close()
print(f"samples: {n_samples}")
print(f"--- top 15 $ra ---")
for ra, cnt in ra_hist.most_common(15):
    print(f"  {ra}  {cnt:5}  ({100.0*cnt/n_samples:.1f}%)")
print(f"--- top 15 EPC ---")
for epc, cnt in epc_hist.most_common(15):
    print(f"  {epc}  {cnt:5}  ({100.0*cnt/n_samples:.1f}%)")
