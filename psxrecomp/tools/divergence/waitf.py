#!/usr/bin/env python3
"""waitf.py <port> <target_frame> [timeout_s=180] - retry-connect, poll `frame`
until >= target, print progress. The debug server may abort a persistent socket
between commands under load; this reconnects and keeps polling. Dev tooling."""
import sys, time, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from debug_client import connect, send_cmd

port = int(sys.argv[1]); target = int(sys.argv[2])
deadline = time.time() + (float(sys.argv[3]) if len(sys.argv) > 3 else 180)
s = None
while time.time() < deadline and s is None:
    try:
        s = connect(port=port, timeout=10)
    except OSError:
        time.sleep(0.3)
if not s:
    print("ERR connect"); sys.exit(1)
last = -1
while time.time() < deadline:
    try:
        f = send_cmd(s, {"cmd": "frame"}).get("frame")
    except Exception:
        time.sleep(0.3)
        try: s = connect(port=port, timeout=10)
        except OSError: pass
        continue
    if f != last:
        print("frame", f, flush=True); last = f
    if isinstance(f, int) and f >= target:
        print("REACHED", f); break
    time.sleep(0.5)
s.close()
