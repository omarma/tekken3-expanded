"""Build a host atlas and exact stock texture guards from the local Nina ARC.

No disc modification. The generated art is repacked with gutters; unchanged
skin-only tiles and effects keep using the guest renderer's original textures.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import numpy as np
from PIL import Image
from tim_tool import scan_tims

STOCK_SHA = 'd62032f1b62ab9261248dd6b31d405c2d801cb54865dfe66e2cad1b78baea0f8'
SELECTED = [0, 1, 3, 4, 5, 6, 8, 9, 10, 11, 14, 16, 17]


def fnv(data):
    value = 14695981039346656037
    for b in data:
        value = ((value ^ b) * 1099511628211) & 0xffffffffffffffff
    return value


def build(source, art, output):
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != STOCK_SHA:
        raise ValueError('Requires the verified US BNS 117 Nina trouser costume')
    tiles = scan_tims(data)
    if len(tiles) != 48:
        raise ValueError('Unexpected texture layout')
    generated = Image.open(art).convert('RGBA')
    if abs(generated.width / generated.height - 2.0) > .01:
        raise ValueError('The authored atlas must have a 6 by 3 square-cell layout')
    output.mkdir(parents=True, exist_ok=True)
    cell, gutter = 256, 16
    stride = cell + 2*gutter
    atlas = Image.new('RGBA', (stride*6, stride*3))
    for i in range(18):
        col, row = i % 6, i // 6
        bounds = (round(col*generated.width/6), round(row*generated.height/3),
                  round((col+1)*generated.width/6), round((row+1)*generated.height/3))
        tile = generated.crop(bounds).resize((cell, cell), Image.Resampling.LANCZOS)
        padded = np.pad(np.array(tile), ((gutter,gutter),(gutter,gutter),(0,0)), mode='edge')
        atlas.paste(Image.fromarray(padded), (col*stride,row*stride))
    atlas.save(output/'nina.png')
    (output/'nina.rgba').write_bytes(b'HDRGBA01'+struct.pack('<2I',*atlas.size)+atlas.tobytes())
    entries, report = [], []
    for player in (0, 1):
        for i in SELECTED:
            t = tiles[i]; q = t.image; c = t.clut
            x, y = 384+q.x, player*256+q.y
            cx, cy = c.x, 504+player*4+c.y
            ph = fnv(data[q.offset+12:q.end_offset])
            ch = fnv(data[c.offset+12:c.end_offset])
            factor = 2 if t.mode == 1 else 4
            sx = (cell-1)/((t.pixel_width-1)*atlas.width)
            sy = (cell-1)/((q.height-1)*atlas.height)
            ox = ((i%6)*stride+gutter+.5)/atlas.width - x*factor*sx
            oy = ((i//6)*stride+gutter+.5)/atlas.height - y*sy
            matrix = (sx,0,ox,0,sy,oy)
            entries.append(struct.pack('<6I2Q6f2I', x,y,q.width_words,q.height,cx,cy,
                                       ph,ch,*matrix,3,t.mode))
            report.append(dict(player=player+1, tile=i, depth=t.mode,
                               rect=[x,y,q.width_words,q.height],clut=[cx,cy]))
    (output/'mapping.bin').write_bytes(b'HDMAP002'+struct.pack('<I',len(entries))+b''.join(entries))
    (output/'pack-report.json').write_text(json.dumps(dict(source_sha256=STOCK_SHA,
        generated_art_sha256=hashlib.sha256(art.read_bytes()).hexdigest(),
        atlas_size=atlas.size, base_texture_bytes=atlas.width*atlas.height*4,
        tiles=report),indent=2)+'\n')
    print(f'Nina White Satin: {len(entries)} guarded tiles, {atlas.width}x{atlas.height} atlas')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--art',type=Path,required=True)
    p.add_argument('--output',type=Path,default=Path('mods/assets/nina-white-satin'))
    a = p.parse_args()
    build(a.source,a.art,a.output)
