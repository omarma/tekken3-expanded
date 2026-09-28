import json, socket
s = socket.create_connection(('127.0.0.1', 4370))
s.settimeout(3.0)
s.sendall(b'{"id":1,"cmd":"wtrace_ranges"}\n')
buf = b''
while True:
    try: ch = s.recv(65536)
    except: break
    if not ch: break
    buf += ch
    if b'\n' in buf: break
s.close()
d = json.loads(buf.decode().strip().split('\n')[-1])
for r in d.get('ranges', []):
    print(f"  slot {r['slot']:>2}: {r['lo']}..{r['hi']}")
