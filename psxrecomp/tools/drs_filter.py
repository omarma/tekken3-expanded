import json, socket

def send(cmd, **kw):
    req = {"id":1,"cmd":cmd, **kw}
    s = socket.socket(); s.settimeout(15.0); s.connect(("127.0.0.1", 4370))
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

d = send("dirty_ram_stats")
print(f"blocks_run={d['blocks_run']} insns_run={d['insns_run']} aborts={d['aborts']}")
print("per_pc filtered:")
for e in d.get("per_pc", []):
    pc = int(e["pc"], 16)
    if pc in (0xCF0, 0x641C, 0x6594, 0x6444, 0x6458, 0x6514, 0x650C, 0x48, 0xA0, 0xB0, 0xC0, 0x80):
        print(f"  pc={e['pc']} hits={e['hits']} insns={e['insns']}")
