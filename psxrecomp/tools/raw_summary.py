import socket, json
s = socket.create_connection(('127.0.0.1', 4370))
s.settimeout(3.0)
s.sendall(json.dumps({'id': 1, 'cmd': 'card_read_summary'}).encode() + b'\n')
buf = b''
while True:
    try:
        chunk = s.recv(65536)
    except socket.timeout:
        break
    if not chunk:
        break
    buf += chunk
    if buf.count(b'\n') > 0 and buf.rstrip().endswith(b'}'):
        break
s.close()
print(repr(buf[:400]))
print('---decoded---')
print(buf.decode(errors='replace')[:1500])
