#!/usr/bin/env python3
"""Stitch DuckStation VRAM into a full screenshot using small tile reads."""
import socket, json, sys
from PIL import Image

port = int(sys.argv[1]) if len(sys.argv) > 1 else 4371
out = sys.argv[2] if len(sys.argv) > 2 else "ds_screenshot.png"
FULL_W, FULL_H = 320, 240
TILE = 32

img = Image.new('RGB', (FULL_W, FULL_H))

for ty in range(0, FULL_H, TILE):
    for tx in range(0, FULL_W, TILE):
        tw = min(TILE, FULL_W - tx)
        th = min(TILE, FULL_H - ty)
        try:
            s = socket.create_connection(('localhost', port), timeout=5)
            cmd = f'{{"cmd":"read_vram","x":{tx},"y":{ty},"w":{tw},"h":{th}}}\n'
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
                continue
            pixels = bytes.fromhex(resp['pixels'])
            rw, rh = resp['w'], resp['h']
            for py in range(rh):
                for px in range(rw):
                    off = (py * rw + px) * 2
                    if off + 1 >= len(pixels):
                        break
                    val = pixels[off] | (pixels[off + 1] << 8)
                    r = (val & 0x1F) << 3
                    g = ((val >> 5) & 0x1F) << 3
                    b = ((val >> 10) & 0x1F) << 3
                    img.putpixel((tx + px, ty + py), (r, g, b))
        except Exception as e:
            print(f'Tile ({tx},{ty}) failed: {e}', file=sys.stderr)

img.save(out)
print(f'Saved {out} ({FULL_W}x{FULL_H})')
