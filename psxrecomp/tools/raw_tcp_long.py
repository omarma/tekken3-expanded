#!/usr/bin/env python3
"""Same as raw_tcp.py but with 30s timeout for large transfers."""
import socket, sys, json

if len(sys.argv) < 3:
    print(__doc__); sys.exit(1)

port = int(sys.argv[1]); cmd = sys.argv[2]
req = {"id": 1, "cmd": cmd}
for kv in sys.argv[3:]:
    k, v = kv.split("=", 1)
    if v.startswith("0x") or v.startswith("0X"):
        pass
    else:
        try: v = int(v)
        except ValueError: pass
    req[k] = v

s = socket.socket(); s.settimeout(30.0)
s.connect(("127.0.0.1", port))
s.sendall((json.dumps(req) + "\n").encode())
data = b""; depth_c = 0; depth_s = 0; in_str = False; esc = False; started = False; done = False
try:
    while not done:
        chunk = s.recv(65536)
        if not chunk: break
        for b in chunk:
            data += bytes([b]); ch = chr(b)
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
            if started and depth_c == 0 and depth_s == 0: done = True; break
except socket.timeout: pass
s.close()
sys.stdout.write(data.decode("utf-8", errors="replace"))
