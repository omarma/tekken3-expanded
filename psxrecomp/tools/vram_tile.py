#!/usr/bin/env python3
"""Read a small VRAM tile and report non-zero pixel count."""
import socket, json, sys
from PIL import Image

port = int(sys.argv[1]) if len(sys.argv) > 1 else 4371
x, y = 0, 0
w, h = 128, 128

s = socket.create_connection(('localhost', port), timeout=5)
cmd = f'{{"cmd":"read_vram","x":{x},"y":{y},"w":{w},"h":{h}}}\n'
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
rw, rh = resp['w'], resp['h']
nz = sum(1 for i in range(0, len(pixels), 2) if pixels[i] | pixels[i+1])
print(f'Tile {rw}x{rh}, {len(pixels)} bytes, {nz} non-black pixels out of {rw*rh}')

# Save as image
img = Image.new('RGB', (rw, rh))
for py in range(rh):
    for px in range(rw):
        off = (py * rw + px) * 2
        if off + 1 >= len(pixels):
            break
        val = pixels[off] | (pixels[off + 1] << 8)
        r = (val & 0x1F) << 3
        g = ((val >> 5) & 0x1F) << 3
        b = ((val >> 10) & 0x1F) << 3
        img.putpixel((px, py), (r, g, b))
img.save('ds_tile.png')
print('Saved ds_tile.png')
