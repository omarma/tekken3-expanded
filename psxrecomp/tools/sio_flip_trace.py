#!/usr/bin/env python3
"""Pull the always-on sio_trace ring and isolate pad CONFIG handshakes + type
flips, to find the byte our config SM emits that trips libpad's disconnect.

Usage: python sio_flip_trace.py [PORT] [COUNT]
"""
import socket, json, sys

port  = int(sys.argv[1]) if len(sys.argv) > 1 else 4470
count = int(sys.argv[2]) if len(sys.argv) > 2 else 16000

def fetch(port, count):
    s = socket.create_connection(("127.0.0.1", port), 5)
    s.sendall((json.dumps({"cmd": "sio_trace", "count": count}) + "\n").encode())
    buf = b""
    while True:
        chunk = s.recv(1 << 20)
        if not chunk:
            break
        buf += chunk
        if buf.endswith(b"\n"):
            try:
                return json.loads(buf.decode())
            except Exception:
                continue
    return json.loads(buf.decode())

resp = fetch(port, count)
ents = resp.get("entries", [])
print(f"port={port} total_seq={resp.get('total')} fetched={len(ents)}")

def b(x):
    return int(x, 16) if isinstance(x, str) else int(x)

CFG = {0x43, 0x44, 0x45, 0x46, 0x47, 0x4C, 0x4D, 0x4F}

# Reconstruct pad transactions from the byte stream.
# A pad transaction begins at tx==0x01 with dev going to PAD(1).
txns = []
cur = None
for e in ents:
    tx = b(e["tx"]); rx = b(e["rx"])
    dev_pre = e.get("dev_pre"); dev_post = e.get("dev_post")
    if tx == 0x01:
        # close previous
        if cur: txns.append(cur)
        cur = {"seq": e["seq"], "tx": [tx], "rx": [rx], "func": e.get("func")}
        continue
    if cur is not None:
        # continue only while this looks like the same pad txn (PAD device)
        if dev_pre == 1 or dev_post == 1:
            cur["tx"].append(tx); cur["rx"].append(rx)
        else:
            txns.append(cur); cur = None
if cur: txns.append(cur)

# Classify: command = 2nd tx byte; id = 2nd rx byte (controller id).
def cmd_of(t):  return t["tx"][1] if len(t["tx"]) > 1 else None
def id_of(t):   return t["rx"][1] if len(t["rx"]) > 1 else None

# Histogram to confirm parsing + see which poll IDs/commands actually occur.
from collections import Counter
hcmd = Counter(); hid = Counter()
for t in txns:
    hcmd[cmd_of(t)] += 1
    if cmd_of(t) == 0x42: hid[id_of(t)] += 1
print(f"\ntxns reconstructed: {len(txns)}")
print("cmd histogram: " + ", ".join(f"{(('%02X'%k) if k is not None else 'None')}:{v}" for k,v in sorted(hcmd.items(), key=lambda x:-x[1])))
print("poll(0x42) ID histogram: " + ", ".join(f"{(('%02X'%k) if k is not None else 'None')}:{v}" for k,v in sorted(hid.items(), key=lambda x:-x[1])))

# Find poll (0x42) transactions and detect ID flips between consecutive polls.
print("\n=== TYPE FLIPS (consecutive 0x42 poll ID changes) + nearby CONFIG handshakes ===")
last_poll_id = None
flip_idx = []
for i, t in enumerate(txns):
    c = cmd_of(t)
    if c == 0x42:
        pid = id_of(t)
        if last_poll_id is not None and pid != last_poll_id:
            flip_idx.append(i)
        last_poll_id = pid

print(f"detected {len(flip_idx)} poll-ID flips")

def fmt(t):
    cmd = cmd_of(t)
    tlist = " ".join(f"{x:02X}" for x in t["tx"])
    rlist = " ".join(f"{x:02X}" for x in t["rx"])
    tag = ""
    if cmd in CFG: tag = "  <CONFIG>"
    if cmd == 0x42 and id_of(t) is not None: tag = f"  <POLL id={id_of(t):02X} len={len(t['rx'])}>"
    # flag the disconnect-class anomalies
    if 0xFF in t["rx"][1:3]: tag += "  !!buf0/ID=FF!!"
    return f"  seq={t['seq']:>9} cmd={cmd:02X} func={t['func']}  TX[{tlist}]  RX[{rlist}]{tag}"

# Print a window around each flip (a few txns before/after).
W = 6
shown = set()
for fi in flip_idx:
    lo = max(0, fi - W); hi = min(len(txns), fi + W + 1)
    print(f"\n--- flip at txn #{fi} (window {lo}..{hi-1}) ---")
    for j in range(lo, hi):
        marker = ">>" if j == fi else "  "
        print(marker + fmt(txns[j]))

# Also: every CONFIG transaction in the capture + its response (the smoking gun).
print("\n=== ALL CONFIG transactions in capture (cmd in 43/44/45/46/47/4C/4D/4F) ===")
for t in txns:
    if cmd_of(t) in CFG:
        print(fmt(t))
