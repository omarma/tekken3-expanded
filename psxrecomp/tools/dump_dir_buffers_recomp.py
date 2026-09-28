"""Dump shell directory buffers via runtime read_ram (different cmd from oracle)."""
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

for addr in [0x800EA868, 0x800EBC88, 0x800E0000, 0x80060000,
             0x80067000, 0x80068000, 0x80069000, 0x80070000,
             0x80080000, 0x80090000, 0x800A0000]:
    r = call({'id':1,'cmd':'read_ram','addr':f'0x{addr:08X}','len':64})
    print(f'  {addr:08X}: {r.get("hex","?")[:128]}')
