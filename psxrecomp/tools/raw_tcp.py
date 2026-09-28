#!/usr/bin/env python3
"""Send a raw JSON command and dump the raw response bytes.

Usage: python tools/raw_tcp.py <port> <cmd> [k=v ...]
Example: python tools/raw_tcp.py 4370 card_txn_dump
         python tools/raw_tcp.py 4370 read_ram addr=0x80007568 len=16
"""
import socket
import sys
import json

if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)

port = int(sys.argv[1])
cmd = sys.argv[2]
req = {"id": 1, "cmd": cmd}
for kv in sys.argv[3:]:
    k, v = kv.split("=", 1)
    # Keep hex strings as strings (server's read_ram etc. expect "addr":"0x..").
    # Decimal-looking values become ints.
    if v.startswith("0x") or v.startswith("0X"):
        pass  # leave as string
    else:
        try:
            v = int(v)
        except ValueError:
            pass
    req[k] = v

s = socket.socket()
s.settimeout(5.0)
s.connect(("127.0.0.1", port))
s.sendall((json.dumps(req) + "\n").encode())
data = b""
depth_c = 0
depth_s = 0
in_str = False
esc = False
started = False
done = False
try:
    while not done:
        chunk = s.recv(65536)
        if not chunk:
            break
        for b in chunk:
            data += bytes([b])
            ch = chr(b)
            if in_str:
                if esc: esc = False
                elif ch == "\\": esc = True
                elif ch == '"': in_str = False
                continue
            if ch == '"': in_str = True
            elif ch == "{": depth_c += 1; started = True
            elif ch == "}": depth_c -= 1
            elif ch == "[": depth_s += 1
            elif ch == "]": depth_s -= 1
            if started and depth_c == 0 and depth_s == 0:
                done = True
                break
except socket.timeout:
    pass
s.close()
print(f"=== raw bytes (len={len(data)}) ===")
sys.stdout.write(data.decode("utf-8", errors="replace"))
print()
print("=== json parse attempt ===")
try:
    obj = json.loads(data.decode().strip())
    print("OK keys:", list(obj.keys()) if isinstance(obj, dict) else type(obj))
except Exception as e:
    print(f"FAIL: {e}")
    txt = data.decode("utf-8", errors="replace")
    if hasattr(e, "pos"):
        lo, hi = max(0, e.pos - 30), min(len(txt), e.pos + 30)
        print(f"context [{lo}..{hi}]: {txt[lo:hi]!r}")
        print(f"byte at pos {e.pos}: {txt[e.pos]!r}")
