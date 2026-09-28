"""Quick focused queries to DuckStation TCP debug server (port 4371)."""
import socket, json, sys, time

HOST='127.0.0.1'; PORT=4371

def send(cmd, timeout=3.0):
    s=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((HOST,PORT))
    s.sendall((json.dumps(cmd)+'\n').encode())
    buf=b''
    deadline = time.time()+timeout
    while time.time()<deadline:
        try: chunk=s.recv(65536)
        except socket.timeout: break
        if not chunk: break
        buf+=chunk
        if b'\n' in buf: break
    s.close()
    line = buf.split(b'\n',1)[0].decode()
    if not line: return None
    try: return json.loads(line)
    except: return line

def read_ram(addr, length):
    r = send({"cmd":"read_ram","addr":f"0x{addr:08X}","len":length})
    if not r or not r.get('ok'): return None
    return bytes.fromhex(r['hex'])

def search_in(data, base_addr, marker_le, label):
    pos=0
    while True:
        i=data.find(marker_le, pos)
        if i<0: break
        a = base_addr + i
        print(f'  {label}: RAM phys=0x{a:08X} (KSEG=0x{0x80000000|a:08X})', flush=True)
        pos=i+1

if __name__=='__main__':
    print('PING:', send({"cmd":"ping"}), flush=True)

    # Pause execution for stable read
    print('PAUSE:', send({"cmd":"pause"}), flush=True)
    time.sleep(0.5)

    # Read kernel state addresses we already know
    for addr,n,name in [
        (0x00079D9C, 4, 'VSync counter'),
        (0x00079D48, 4, 'init-done flag (chk by 0xBFC42160)'),
        (0x000DFF40, 4, 'user VSync callback slot'),
        (0x00000080, 16, 'exception vector'),
        (0x00000100, 64, 'PCB/TCB/EvCB pointer table'),
    ]:
        d = read_ram(addr, n)
        if d:
            words = ' '.join(f'{int.from_bytes(d[i:i+4],"little"):08X}' for i in range(0,len(d),4))
            print(f'  0x{addr:08X} {name}: {words}', flush=True)

    # Search EvCB for the handler/registrar/init function pointers
    targets = {
        bytes.fromhex('bca50580'): '0x8005A5BC handler',
        bytes.fromhex('40a50580'): '0x8005A540 registrar',
        bytes.fromhex('60a10580'): '0x8005A160 init',
        bytes.fromhex('24a40580'): '0x8005A424 cleanup',
        bytes.fromhex('80a30580'): '0x8005A380 dispatch',
        bytes.fromhex('fca50580'): '0x8005A5FC SetVSync',
    }
    print('\n--- Searching key RAM regions for handler-related addresses ---', flush=True)
    # Search smaller, focused regions: kernel data 0x0000_0000..0x0001_0000, EvCB region 0x0000_E000..0x0000_E200,
    # shell stack 0x000F_0000..0x0010_0000, and shell data 0x000DF000..0x000E0000
    for base, length in [(0x00000000, 0x00010000), (0x000DF000, 0x00001000), (0x000E0000, 0x00010000), (0x000F0000, 0x00010000)]:
        print(f'\nRegion 0x{base:08X}..0x{base+length:08X}:', flush=True)
        # read in 4KB chunks
        chunks = []
        for off in range(0, length, 4096):
            d = read_ram(base+off, min(4096, length-off))
            if d is None:
                print(f'  (read failed at 0x{base+off:08X})', flush=True)
                break
            chunks.append(d)
        if not chunks: continue
        data = b''.join(chunks)
        for marker, label in targets.items():
            search_in(data, base, marker, label)

    # Resume
    print('\nCONTINUE:', send({"cmd":"continue"}), flush=True)
