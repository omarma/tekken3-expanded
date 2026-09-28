"""Press CROSS in recomp via 'press' command (1-frame pulses can be missed)."""
import socket, json, sys, time

def call(d):
    s = socket.create_connection(('127.0.0.1', 4370)); s.settimeout(15.0)
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

# Press CROSS for several frames (BIOS shell wants press-AND-release edge)
print('press CROSS 30 frames:', call({'id':1,'cmd':'press','buttons':0xBFFF,'frames':30}))
time.sleep(2)
print('release:', call({'id':2,'cmd':'press','buttons':0xFFFF,'frames':30}))
time.sleep(2)
print('frame:', call({'id':3,'cmd':'ping'}))
print('shell state:', call({'id':4,'cmd':'read_ram','addr':'0x80066948','len':1}))
print('substate:',    call({'id':5,'cmd':'read_ram','addr':'0x80066940','len':1}))
