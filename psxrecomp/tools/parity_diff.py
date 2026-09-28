#!/usr/bin/env python3
"""parity_diff.py — generic two-process control-flow first-divergence finder.

Pulls the `parity_dump` ring from psx-runtime (code under test) and psx-beetle
(independent oracle), aligns the two thread-scoped control-flow streams by
LOGICAL SEQUENCE (not frame), and reports the FIRST point where they diverge —
plus the watched state-word deltas at that point. This is the instrument that
replaces "somewhere upstream" guessing (recomp-template PRINCIPLES.md: "find the
first divergence, not the final visible bug").

Both sides emit the IDENTICAL row schema (parity_trace.h), so the diff is a plain
sequence match on the (kind, pc, target) tuple. Each side is typically armed from
boot and frozen on its own trigger (native: the wedge target; beetle: the
expected-but-missing producer), so the common prefix aligns and the tail reveals
the missing/extra/reordered behavior.

Usage:
  python tools/parity_diff.py [--native PORT] [--beetle PORT] [--key kind,pc,target]
                              [--context N] [--count N]
"""
import argparse, json, socket, sys, difflib

def query(port, cmd, **kw):
    obj = {"cmd": cmd}; obj.update(kw)
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
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

def rows(port, count):
    r = query(port, "parity_dump", count=count)
    if not r.get("ok"):
        print(f"[port {port}] parity_dump failed: {r}", file=sys.stderr); sys.exit(2)
    return r

def norm(v):
    """Normalize an address-ish field to physical (mask KSEG bits) so virtual
    (0x80..) on one side matches physical (0x00..) on the other."""
    try:
        n = int(v, 16) if isinstance(v, str) and v.startswith("0x") else int(v)
        return f"0x{n & 0x1FFFFFFF:08X}"
    except (ValueError, TypeError):
        return v

def keytuple(e, fields):
    return tuple(norm(e.get(f, "")) if f in ("pc", "target", "ra") else e.get(f, "")
                 for f in fields)

def fmt(e):
    w = e.get("w", [])
    return (f"seq={e['seq']:>5} f={e['frame']:>5} {e['kind']:<12} "
            f"cur={e['cur_tcb']} pc={e['pc']} tgt={e['target']} "
            f"epc={e['epc']} st={e['state']} ra={e['ra']} sp={e['sp']} "
            f"flag={w[1] if len(w)>1 else '?'} struct={w[2] if len(w)>2 else '?'}")

def prov(e):
    """Per-watch-slot value + LAST-WRITER provenance (pc/cycle/frame/tcb).
    This is the 'who produced the divergent gate input' view."""
    w   = e.get("w", []);     wpc = e.get("wwpc", [])
    wcy = e.get("wwcy", []);  wf  = e.get("wwf", []); wt = e.get("wwt", [])
    lines = []
    for i in range(len(w)):
        if w[i] == "0x00000000" and (i >= len(wpc) or wpc[i] == "0x00000000"):
            continue  # unconfigured / never-touched slot
        p  = wpc[i] if i < len(wpc) else "?"
        cy = wcy[i] if i < len(wcy) else "?"
        fr = wf[i]  if i < len(wf)  else "?"
        tc = wt[i]  if i < len(wt)  else "?"
        lines.append(f"    w[{i}]={w[i]}  <- writer pc={p} cyc={cy} f={fr} tcb={tc}")
    return "\n".join(lines)

def compare_prov(n, b):
    """Side-by-side watch provenance for the two diverging rows. Flags slots whose
    VALUE differs (mask KSEG) — that slot + its writer name the early producer."""
    w_n, w_b = n.get("w", []), b.get("w", [])
    pc_n, pc_b = n.get("wwpc", []), b.get("wwpc", [])
    cy_n, cy_b = n.get("wwcy", []), b.get("wwcy", [])
    f_n, f_b   = n.get("wwf", []),  b.get("wwf", [])
    out = []
    for i in range(min(len(w_n), len(w_b))):
        if w_n[i] == "0x00000000" and w_b[i] == "0x00000000":
            continue
        diff = norm(w_n[i]) != norm(w_b[i])
        flag = "  <-- VALUE DIFFERS" if diff else ""
        out.append(f"  slot {i}:{flag}")
        out.append(f"    NATIVE w={w_n[i]} writer pc={pc_n[i] if i<len(pc_n) else '?'} "
                   f"cyc={cy_n[i] if i<len(cy_n) else '?'} f={f_n[i] if i<len(f_n) else '?'}")
        out.append(f"    BEETLE w={w_b[i]} writer pc={pc_b[i] if i<len(pc_b) else '?'} "
                   f"cyc={cy_b[i] if i<len(cy_b) else '?'} f={f_b[i] if i<len(f_b) else '?'}")
    return "\n".join(out) if out else "  (no configured watch slots)"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--native", type=int, default=4490)
    ap.add_argument("--beetle", type=int, default=4382)
    ap.add_argument("--count", type=int, default=16384)
    ap.add_argument("--key", default="kind,pc,target",
                    help="comma fields forming the per-row alignment key")
    ap.add_argument("--context", type=int, default=12)
    args = ap.parse_args()
    fields = args.key.split(",")

    nat = rows(args.native, args.count)
    bet = rows(args.beetle, args.count)
    ne, be = nat["entries"], bet["entries"]
    print(f"native(:{args.native}): {len(ne)} rows total={nat['total']} "
          f"armed={nat['armed']} frozen={nat['frozen']}")
    print(f"beetle(:{args.beetle}): {len(be)} rows total={bet['total']} "
          f"armed={bet['armed']} frozen={bet['frozen']}")
    if not ne or not be:
        print("\nOne side has no rows — arm both from boot and reach the window.")
        return

    nk = [keytuple(e, fields) for e in ne]
    bk = [keytuple(e, fields) for e in be]
    sm = difflib.SequenceMatcher(a=nk, b=bk, autojunk=False)
    blocks = sm.get_matching_blocks()

    # First divergence = end of the first matching block that does not extend
    # to the end of both streams.
    first = None
    for blk in blocks:
        end_a, end_b = blk.a + blk.size, blk.b + blk.size
        if blk.size and (end_a < len(nk) or end_b < len(bk)):
            first = (end_a, end_b); break
    if first is None:
        print("\nNo divergence in the compared window (streams match to the end).")
        return
    ia, ib = first
    C = args.context
    print(f"\n===== FIRST DIVERGENCE (native idx {ia}, beetle idx {ib}) =====")
    print("--- last common rows (native) ---")
    for e in ne[max(0, ia - C):ia]:
        print("  ", fmt(e))
    print(f"--- NATIVE diverges here (idx {ia}+) ---")
    for e in ne[ia:ia + C]:
        print("  N", fmt(e))
    print(f"--- ORACLE/BEETLE path here (idx {ib}+) ---")
    for e in be[ib:ib + C]:
        print("  B", fmt(e))
    # Provenance at the divergence: which gate-input value differs, and who wrote
    # it on each side. This is the 'name the early producer' payoff.
    if ia < len(ne) and ib < len(be):
        print("\n----- WATCH PROVENANCE @ divergence (native idx %d vs beetle idx %d) -----" % (ia, ib))
        print(compare_prov(ne[ia], be[ib]))

if __name__ == "__main__":
    main()
