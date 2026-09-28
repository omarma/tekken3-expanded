#!/usr/bin/env python3
"""devtrace_diff.py — two-process DEVICE-EVENT cycle-timeline diff.

Pulls the always-on device-event ring (devtrace_dump) from psx-runtime (code
under test) and psx-beetle (independent oracle) and compares, per IRQ source
(VBLANK / GPU / CDROM / DMA / TIMER0-2 / SIO / SPU), the GUEST CYCLE at which the
Nth event of that source fired. VBlank is cycle-paced so it should track between
the two; a source that drifts (its Nth event at a very different cycle) is the
device whose completion timing diverges — the producer of an over-fast/over-slow
wait. This is the level below parity_diff (control flow): it names the hardware
event, not the branch.

Both backends emit the IDENTICAL row schema (device_trace.h), so one tool reads
both ports by switching the port number.

Usage:
  python tools/devtrace_diff.py [--native PORT] [--beetle PORT]
        [--cyc-lo C] [--cyc-hi C]   # restrict to a guest-cycle window
        [--drift N]                 # flag first ordinal whose |Δcycle| > N (default 2_000_000)
        [--show K]                  # also print first K events per source per side
"""
import argparse, json, socket, sys

SRC = {0:"vblank",1:"gpu",2:"cdrom",3:"dma",4:"timer0",5:"timer1",6:"timer2",
       7:"sio0",8:"sio1",9:"spu",10:"pio"}

# KNOWN INTENTIONAL divergences from the Beetle oracle — where OUR runtime is
# MORE faithful to real hardware than Beetle, so a native/beetle delta on this
# source is EXPECTED, not a bug. Labeled (not red-flagged) unless --strict.
# See ACCURACY_BURNDOWN.md (Axis 5 — CDROM). Add entries here (never silence a
# real divergence): source-name -> one-line reason.
KNOWN_DIVERGENCES = {
    "cdrom": "SCPH-1001 CD controller version 94/09/19/C0 (psx-spx) vs Beetle's "
             "hardcoded 97/01/10/C2 — version <0x95 keeps the shell CD-init flag "
             "[0xA000DFFC] clear, so Beetle issues a spurious boot ReadTOC we do "
             "not: expect a CDROM event count/timing delta around CD-init. "
             "Also GetID region (SCEA/E/I) + status bit2 ADPBUSY idle=0.",
}

def query(port, cmd, **kw):
    obj = {"cmd": cmd}; obj.update(kw)
    s = socket.create_connection(("127.0.0.1", port), timeout=15)
    try:
        s.sendall((json.dumps(obj) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(1 << 20)
            if not chunk: break
            buf += chunk
        return json.loads(buf.decode(errors="replace").split("\n", 1)[0])
    finally:
        s.close()

def pull(port, cyc_lo, cyc_hi):
    kw = {"count": 1 << 20}
    if cyc_lo is not None: kw["cyc_lo"] = str(cyc_lo)
    if cyc_hi is not None: kw["cyc_hi"] = str(cyc_hi)
    r = query(port, "devtrace_dump", **kw)
    if not r.get("ok"):
        print(f"[port {port}] devtrace_dump failed: {r}", file=sys.stderr); sys.exit(2)
    return r

def by_source(events):
    d = {}
    for e in events:
        d.setdefault(e["srcn"], []).append(e)
    return d

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--native", type=int, default=4490)
    ap.add_argument("--beetle", type=int, default=4382)
    ap.add_argument("--cyc-lo", type=int, default=None)
    ap.add_argument("--cyc-hi", type=int, default=None)
    ap.add_argument("--drift", type=int, default=2_000_000)
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--strict", action="store_true",
                    help="do NOT suppress KNOWN_DIVERGENCES (show them as raw drift)")
    args = ap.parse_args()

    nat = pull(args.native, args.cyc_lo, args.cyc_hi)
    bet = pull(args.beetle, args.cyc_lo, args.cyc_hi)
    ne, be = nat["events"], bet["events"]
    print(f"native(:{args.native}): {len(ne)} events (ring total={nat['total']}, armed={nat['armed']})")
    print(f"beetle(:{args.beetle}): {len(be)} events (ring total={bet['total']}, armed={bet['armed']})")

    ns, bs = by_source(ne), by_source(be)
    sources = sorted(set(ns) | set(bs))
    print(f"\n{'source':<8} {'native#':>8} {'beetle#':>8}  {'first divergent ordinal (cycle delta)':<40}")
    print("-" * 78)
    suppressed = []
    for s in sources:
        n, b = ns.get(s, []), bs.get(s, [])
        name = SRC.get(s, f"src{s}")
        # align by ordinal, find first where the cycle gap exceeds --drift
        flag = ""
        m = min(len(n), len(b))
        for i in range(m):
            dc = n[i]["cycle"] - b[i]["cycle"]
            if abs(dc) > args.drift:
                flag = f"#{i}: native cyc={n[i]['cycle']} beetle cyc={b[i]['cycle']} (delta={dc:+d})"
                break
        if not flag and len(n) != len(b):
            flag = f"count differs ({len(n)} vs {len(b)}) — no big per-ordinal drift in first {m}"
        diverged = bool(flag)
        if not flag:
            flag = "tracks (no drift > threshold)"
        known = KNOWN_DIVERGENCES.get(name)
        if diverged and known and not args.strict:
            flag = f"KNOWN✓ intentional (more faithful) — {flag}"
            suppressed.append(name)
        print(f"{name:<8} {len(n):>8} {len(b):>8}  {flag}")

    if suppressed and not args.strict:
        print("\nKNOWN intentional divergences suppressed (re-run with --strict to"
              " see raw): " + ", ".join(suppressed))
        for nm in suppressed:
            print(f"  {nm}: {KNOWN_DIVERGENCES[nm]}")

    if args.show:
        for s in sources:
            name = SRC.get(s, f"src{s}")
            print(f"\n--- {name} first {args.show} (native | beetle) ---")
            n, b = ns.get(s, []), bs.get(s, [])
            for i in range(min(args.show, max(len(n), len(b)))):
                nc = f"cyc={n[i]['cycle']} f={n[i]['frame']} d={n[i]['detail']}" if i < len(n) else "-"
                bc = f"cyc={b[i]['cycle']} f={b[i]['frame']} d={b[i]['detail']}" if i < len(b) else "-"
                print(f"  #{i:<4} {nc:<34} | {bc}")

if __name__ == "__main__":
    main()
