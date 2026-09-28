#!/usr/bin/env python3
"""measure.py — per-iteration cycle delta for each test-ROM anchor on one backend.

Arms cyc_watch single-anchor on each loop top, dumps, and reports the modal
consecutive-hit delta = one iteration's cycle cost. Run against Beetle (4382,
the oracle) and native (the cost model) and compare.

Usage: python measure.py [--port 4382] [--json cycle_testrom.exe.anchors.json]
"""
import argparse, collections, json, socket, sys, time

def query(port, cmd, host="127.0.0.1", timeout=10.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout); s.connect((host, port))
    try:
        s.sendall((json.dumps(cmd) + "\n").encode())
        buf = bytearray(); depth = 0; instr = False; esc = False; started = False
        while True:
            ch = s.recv(1 << 20)
            if not ch: break
            buf.extend(ch)
            i = 0
            while i < len(buf):
                c = buf[i]
                if instr:
                    if esc: esc = False
                    elif c == 0x5C: esc = True
                    elif c == 0x22: instr = False
                elif c == 0x22: instr = True
                elif c == 0x7B: depth += 1; started = True
                elif c == 0x7D:
                    depth -= 1
                    if started and depth == 0:
                        return json.loads(buf[:i+1].decode())
                i += 1
    finally:
        s.close()
    return json.loads(bytes(buf).decode())

def modal_delta(entries):
    cy = [int(e["cycles"]) for e in entries]
    ds = [cy[i+1]-cy[i] for i in range(len(cy)-1)]
    if not ds: return None, ds
    return collections.Counter(ds).most_common(1)[0][0], ds

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=4382)
    p.add_argument("--json", default="cycle_testrom.exe.anchors.json")
    p.add_argument("--hits", type=int, default=8)
    p.add_argument("--wait", type=float, default=1.5)
    a = p.parse_args()
    meta = json.load(open(a.json))
    anchors = meta["anchors"]
    label = "beetle" if a.port == 4382 else ("native" if a.port == 4500 else f"port{a.port}")
    print(f"=== per-iteration cycle delta on {label} (port {a.port}) ===")
    results = {}
    base = None
    for name, addr in anchors.items():
        query(a.port, {"cmd": "cyc_watch", "pc": addr, "n": a.hits})
        time.sleep(a.wait)
        d = query(a.port, {"cmd": "cyc_watch_dump"})
        md, ds = modal_delta(d.get("entries", []))
        results[name] = md
        if name == "baseline": base = md
        comp = f"  (component = {md - base:+d})" if (base is not None and md is not None and name != "baseline") else ""
        print(f"  {name:12s} {addr}  per-iter={md}{comp}   hits={d.get('hits')}")
    print()
    if base is not None:
        print("Component costs (per-iter minus baseline):")
        for name, md in results.items():
            if name == "baseline" or md is None: continue
            print(f"  {name:12s} {md - base:+d}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
