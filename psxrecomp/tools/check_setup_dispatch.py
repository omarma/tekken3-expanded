"""Check whether R/W/D-setup functions are dispatched in recomp."""
import socket, json

def call(d):
    s = socket.create_connection(('127.0.0.1', 4370)); s.settimeout(15.0)
    s.sendall((json.dumps(d) + '\n').encode())
    buf = b''
    while True:
        try: c = s.recv(65536)
        except socket.timeout: break
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

for pc, label in [
    (0x000059A0, 'R-setup FUN_bfc159A0 (sets gate=0x02)'),
    (0x00005A04, 'W-setup FUN_bfc15A04 (sets gate=0x04)'),
    (0x00005AB8, 'D-setup FUN_bfc15AB8 (sets gate=0x08)'),
    (0x00006524, 'SIO RX byte handler at PC 0x6524'),
    (0x00006414, 'SIO callback area'),
    (0x00006594, 'SIO callback area 2'),
]:
    r = call({'id':1,'cmd':'dispatch_check','addr':f'0x{pc:08X}'})
    print(f"  0x{pc:08X} {label}: in_ring={r.get('found')}")
