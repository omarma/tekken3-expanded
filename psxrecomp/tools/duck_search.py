"""Search DuckStation's RAM for marker addresses via TCP debug server."""
import socket, json, sys

HOST='127.0.0.1'; PORT=4371

def send(cmd):
    s=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect((HOST,PORT))
    s.sendall((json.dumps(cmd)+'\n').encode())
    buf=b''
    while True:
        try: chunk=s.recv(65536)
        except socket.timeout: break
        if not chunk: break
        buf+=chunk
        if b'\n' in buf: break
    s.close()
    line = buf.split(b'\n',1)[0].decode()
    return json.loads(line)

def search(start, length, markers, label_per_marker):
    """Read [start, start+length) bytes; find each marker (hex string LE) in the data."""
    chunk = 8192
    found = {m:[] for m in markers}
    off = 0
    while off < length:
        n = min(chunk, length-off)
        r = send({"cmd":"read_ram", "addr": f"0x{start+off:08X}", "len": n})
        if not r.get('ok'): print('ERR', r); return found
        hex_str = r['hex']
        for m in markers:
            pos=0
            while True:
                i = hex_str.find(m, pos)
                if i<0: break
                byte_off = i//2
                ram_addr = start + off + byte_off
                found[m].append(ram_addr)
                pos = i+1
        off += n
    for m in markers:
        label = label_per_marker.get(m, m)
        for a in found[m]:
            print(f'{label}: RAM phys=0x{a:08X} (KSEG0=0x{0x80000000|a:08X})')
        if not found[m]:
            print(f'{label}: NOT FOUND in [0x{start:08X}..0x{start+length:08X})')
    return found

if __name__=='__main__':
    # Markers are little-endian hex of target addresses
    markers = {
        'bca50580': '0x8005A5BC handler (vblank chain)',
        '40a50580': '0x8005A540 registrar',
        '60a10580': '0x8005A160 init function',
        '24a40580': '0x8005A424 cleanup',
        '80a30580': '0x8005A380 dispatch',
        'fca50580': '0x8005A5FC SetVSync',
    }
    # Search all 2MB of RAM
    search(0x00000000, 0x00200000, list(markers.keys()), markers)
