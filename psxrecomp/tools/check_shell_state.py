"""Read shell flow gates + see if memcard subsystem ran at all."""
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
        if buf.count(b'{') == buf.count(b'}') and buf.strip(): break
    s.close()
    return json.loads(buf.decode())


def read(addr, n):
    r = call({'id': 1, 'cmd': 'read_ram', 'addr': f'0x{addr:08X}', 'len': n})
    return r.get('hex', '')


def hex_words(hexstr, n):
    """Split hex string into n LE 32-bit words."""
    out = []
    for i in range(n):
        b = hexstr[i*8:(i+1)*8]
        if len(b) < 8: break
        # LE
        word = int(b[6:8] + b[4:6] + b[2:4] + b[0:2], 16)
        out.append(word)
    return out


print('=== shell state machine 0x80066940 ===')
hx = read(0x80066940, 32)
print(f'  raw = {hx}')
print(f'  words = {[hex(w) for w in hex_words(hx, 8)]}')

print()
print('=== shell flow gate 0x80066bc0 ===')
hx = read(0x80066bc0, 32)
print(f'  raw = {hx}')
print(f'  words = {[hex(w) for w in hex_words(hx, 8)]}')

print()
print('=== card chain state 0x80007510..0x80007570 ===')
hx = read(0x80007510, 0x60)
print(f'  raw = {hx}')

print()
print('=== card slots gates 0x80007568..0x80007570 ===')
hx = read(0x80007568, 8)
print(f'  raw = {hx}  (slot0..3 gate bytes + xor accums)')

print()
print('=== xor accumulators 0x80007560..0x80007568 ===')
hx = read(0x80007560, 8)
print(f'  raw = {hx}  (slot0/slot1 xor accums)')

print()
print('=== ping ===')
print(call({'id': 0, 'cmd': 'ping'}))
