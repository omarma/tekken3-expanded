"""Dump recomp wtrace, filtered to a range."""
import socket, json, sys

def call(d):
    s = socket.create_connection(('127.0.0.1', 4370)); s.settimeout(60.0)
    s.sendall((json.dumps(d) + '\n').encode())
    buf = b''
    while True:
        try: c = s.recv(65536)
        except (socket.timeout, ConnectionResetError): break
        if not c: break
        buf += c
        depth=0; ins=False; esc=False
        for b in buf:
            if esc: esc=False; continue
            if b==0x5C: esc=True; continue
            if b==0x22: ins=not ins; continue
            if ins: continue
            if b==0x7B: depth+=1
            elif b==0x7D: depth-=1
        if depth==0 and buf.strip(): break
    s.close()
    return json.loads(buf.decode())

lo = sys.argv[1] if len(sys.argv) > 1 else '0x80080000'
hi = sys.argv[2] if len(sys.argv) > 2 else '0x80088000'
r = call({'id':1,'cmd':'wtrace_dump','addr_lo':lo,'addr_hi':hi})
total = r.get('total','?')
avail = r.get('available','?')
entries = r.get('entries', [])
print(f"total={total} avail={avail} returned={len(entries)}")
for e in entries[:200]:
    addr = e.get('addr', '?')
    old  = e.get('old',  '?')
    new  = e.get('new',  e.get('val', e.get('value', '?')))
    pc   = e.get('pc', '?')
    ra   = e.get('ra', '?')
    fn   = e.get('func', '?')
    w    = e.get('w', e.get('size', '?'))
    fr   = e.get('frame', '?')
    print(f'  fr={fr:>6} {addr}: {old}->{new} (w{w}) pc={pc} ra={ra} fn={fn}')
