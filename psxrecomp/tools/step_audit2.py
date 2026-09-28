#!/usr/bin/env python3
"""Deeper SIO trace mining for card-related entries."""
import socket, json, sys

def send(cmd, **kw):
    req = {"id": 1, "cmd": cmd, **kw}
    s = socket.socket(); s.settimeout(15.0); s.connect(("127.0.0.1", 4370))
    s.sendall((json.dumps(req) + "\n").encode())
    buf = b""
    depth_c = depth_s = 0
    in_str = esc = started = False
    while True:
        chunk = s.recv(65536)
        if not chunk: break
        for b in chunk:
            buf += bytes([b]); ch = chr(b)
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
                s.close(); return json.loads(buf.decode().strip())
    s.close()
    return json.loads(buf.decode().strip())


count = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
r = send("sio_trace", count=count)
ents = r.get("entries", [])
print(f"sio_trace total_seq={r.get('total')} returned={len(ents)}")

# Card related: mc_pre or mc_post > 0 OR dev_pre/dev_post == DEV_MEMCARD (=2)
DEV_MEMCARD = 2
DEV_PAD = 1
cards = [e for e in ents if e.get("mc_pre", 0) > 0 or e.get("mc_post", 0) > 0
         or e.get("dev_pre") == DEV_MEMCARD or e.get("dev_post") == DEV_MEMCARD]
print(f"card-related: {len(cards)}")

# Of card-related, how many had irq_cd > 0 (IRQ countdown armed)?
armed = [e for e in cards if e.get("irq_cd", 0) > 0]
print(f"card-related with irq_cd>0 at trace time: {len(armed)}")

# Show first few card-related
if cards:
    print("\nfirst 5 card-related:")
    for e in cards[:5]:
        print(f"  seq={e['seq']} tx={e['tx']} rx={e['rx']} mc_pre={e['mc_pre']} mc_post={e['mc_post']}"
              f" dev_pre={e['dev_pre']} dev_post={e['dev_post']} ctrl={e['ctrl']} irq_cd={e['irq_cd']}"
              f" abort={e['abort']} in_exc={e['in_exc']}")

# distribution of irq_cd values for card bytes
if cards:
    from collections import Counter
    cdist = Counter(e['irq_cd'] for e in cards)
    print(f"\nirq_cd distribution among card bytes: {dict(cdist)}")
