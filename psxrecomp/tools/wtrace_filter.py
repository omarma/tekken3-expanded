import json, socket, sys

def send(cmd, **kw):
    req = {"id":1,"cmd":cmd, **kw}
    s = socket.socket(); s.settimeout(20.0); s.connect(("127.0.0.1", 4370))
    s.sendall((json.dumps(req)+"\n").encode())
    buf=b""; dc=ds=0; ins=esc=st=False
    while True:
        c = s.recv(65536)
        if not c: break
        for b in c:
            buf += bytes([b]); ch = chr(b)
            if ins:
                if esc: esc=False
                elif ch == "\\": esc=True
                elif ch == '"': ins=False
                continue
            if ch == '"': ins=True
            elif ch == "{": dc+=1; st=True
            elif ch == "}": dc-=1
            elif ch == "[": ds+=1
            elif ch == "]": ds-=1
            if st and dc==0 and ds==0:
                s.close(); return json.loads(buf.decode().strip())
    s.close()
    return json.loads(buf.decode().strip())

d = send("wtrace_dump")
print("keys:", list(d.keys())[:10])
ents = d.get("entries", [])
print(f"total wtrace entries: {len(ents)}")

def in_range(e, lo, hi):
    a = int(e.get("addr","0"), 16) & 0xFFFFFFFF
    p = a & 0xFFFF
    return lo <= p <= hi

hits_72F0 = [e for e in ents if in_range(e, 0x72F0, 0x72F3)]
print(f"writes to [0x72F0..0x72F3]: {len(hits_72F0)}")
for h in hits_72F0[:8]:
    print(" ", h)

hits_755A = [e for e in ents if in_range(e, 0x755A, 0x755C)]
print(f"writes to [0x755A..0x755C]: {len(hits_755A)}")
for h in hits_755A[:8]:
    print(" ", h)

hits_75C0 = [e for e in ents if in_range(e, 0x75C0, 0x75C3)]
print(f"writes to [0x75C0..0x75C3]: {len(hits_75C0)}")
for h in hits_75C0[:8]:
    print(" ", h)

hits_7568 = [e for e in ents if in_range(e, 0x7568, 0x7570)]
print(f"writes to [0x7568..0x7570]: {len(hits_7568)}")
for h in hits_7568[:8]:
    print(" ", h)
