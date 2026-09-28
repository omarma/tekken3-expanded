#!/usr/bin/env python3
"""Capture DuckStation oracle VRAM as screenshot via debug server."""
import socket, json, sys
from PIL import Image

port = int(sys.argv[1]) if len(sys.argv) > 1 else 4371
out = sys.argv[2] if len(sys.argv) > 2 else "ds_screenshot.png"

s = socket.create_connection(('localhost', port))
cmd = '{"cmd":"read_vram","x":0,"y":0,"w":640,"h":480}\n'
s.sendall(cmd.encode())
data = b''
while True:
    chunk = s.recv(65536)
    if not chunk:
        break
    data += chunk
    if b'\n' in data:
        break
s.close()

resp = json.loads(data.split(b'\n')[0])
if not resp.get('ok'):
    print('Error:', resp)
    sys.exit(1)

pixels = bytes.fromhex(resp['pixels'])
w, h = resp['w'], resp['h']
img = Image.new('RGB', (w, h))
for y in range(h):
    for x in range(w):
        off = (y * w + x) * 2
        if off + 1 >= len(pixels):
            break
        val = pixels[off] | (pixels[off + 1] << 8)
        r = (val & 0x1F) << 3
        g = ((val >> 5) & 0x1F) << 3
        b = ((val >> 10) & 0x1F) << 3
        img.putpixel((x, y), (r, g, b))

img.save(out)
print(f'Saved {out} ({w}x{h})')
