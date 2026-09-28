"""Press CROSS in recomp to advance from MEMCARD selector into per-card view.
Mirrors Beetle's press_into_card_view.py."""
import socket, json, sys, time

def call(d):
    s = socket.create_connection(('127.0.0.1', 4370)); s.settimeout(60.0)
    s.sendall((json.dumps(d) + '\n').encode())
    buf = b''
    while True:
        try: c = s.recv(65536)
        except socket.timeout: break
        if not c: break
        buf += c
        depth = 0; in_str = False; esc = False
        for b in buf:
            if esc: esc = False; continue
            if b == 0x5C: esc = True; continue
            if b == 0x22: in_str = not in_str; continue
            if in_str: continue
            if b == 0x7B: depth += 1
            elif b == 0x7D: depth -= 1
        if depth == 0 and buf.strip(): break
    s.close()
    return json.loads(buf.decode())

frames = int(sys.argv[1]) if len(sys.argv) > 1 else 240
print('initial substate:', call({'id':1,'cmd':'read_ram','addr':'0x80066940','len':4}))
print('initial state:',    call({'id':2,'cmd':'read_ram','addr':'0x80066948','len':4}))

print(f'press CROSS {frames}f:', call({'id':3,'cmd':'press','buttons':0xBFFF,'frames':frames}))
time.sleep(2)
print('release:',  call({'id':4,'cmd':'press','buttons':0xFFFF,'frames':30}))
time.sleep(1)

print('post substate:', call({'id':5,'cmd':'read_ram','addr':'0x80066940','len':4}))
print('post state:',    call({'id':6,'cmd':'read_ram','addr':'0x80066948','len':4}))
print('frame:',         call({'id':7,'cmd':'ping'}))
