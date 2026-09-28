#!/usr/bin/env python3
"""shot.py <port> <out.png> - screenshot the runtime to a PNG (then Read it to
verify VISUALLY; a frame counter advancing != visually progressing). Dev tooling."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from debug_client import connect, send_cmd

port = int(sys.argv[1]); path = sys.argv[2]
s = connect(port=port, timeout=15)
for cmd in ("screenshot_file", "screenshot"):
    r = send_cmd(s, {"cmd": cmd, "path": path})
    print(cmd, "->", {k: r.get(k) for k in ("ok", "error", "path")})
    if r.get("ok"):
        break
s.close()
