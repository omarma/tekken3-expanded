"""Pack authored polar-bear art with exact guards for Kuma's stock 4bpp tiles."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import numpy as np
from PIL import Image
from tim_tool import scan_tims
from nina_skin_pack import fnv

STOCK_SHA = 'bc2159f986181c6f6c99ad145bf3aaa7d6639e3dcffef11c934d9caa5d8f3921'
SELECTED = [1, 2, 3, 4, 5, 7, 9, 10, 11, 14, 15]


def build(source, art, output):
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != STOCK_SHA:
        raise ValueError('Requires the verified US BNS 161 original Kuma costume')
    tiles = scan_tims(data)
    if len(tiles) != 46 or any(t.mode != 0 for t in tiles[:16]):
        raise ValueError('Unexpected Kuma texture layout')
    generated = Image.open(art).convert('RGBA')
    if generated.width != generated.height or generated.width < 1024:
        raise ValueError('Author a square atlas with 4 by 4 square cells, at least 1024px')
    output.mkdir(parents=True, exist_ok=True)
    cell, gutter = 256, 16
    stride = cell + 2*gutter
    atlas = Image.new('RGBA', (stride*4, stride*4))
    for i in range(16):
        col, row = i % 4, i // 4
        bounds = (round(col*generated.width/4), round(row*generated.height/4),
                  round((col+1)*generated.width/4), round((row+1)*generated.height/4))
        tile = generated.crop(bounds).resize((cell, cell), Image.Resampling.LANCZOS)
        padded = np.pad(np.array(tile), ((gutter,gutter),(gutter,gutter),(0,0)), mode='edge')
        atlas.paste(Image.fromarray(padded), (col*stride,row*stride))
    atlas.save(output/'kuma.png')
    (output/'kuma.rgba').write_bytes(b'HDRGBA01'+struct.pack('<2I',*atlas.size)+atlas.tobytes())
    entries, report = [], []
    for player in (0, 1):
        for i in SELECTED:
            t = tiles[i]; q = t.image; c = t.clut
            x, y = 384+q.x, player*256+q.y
            cx, cy = c.x, 504+player*4+c.y
            ph = fnv(data[q.data_offset:q.end_offset])
            ch = fnv(data[c.data_offset:c.end_offset])
            sx = (cell-1)/((t.pixel_width-1)*atlas.width)
            sy = (cell-1)/((q.height-1)*atlas.height)
            ox = ((i%4)*stride+gutter+.5)/atlas.width - x*4*sx
            oy = ((i//4)*stride+gutter+.5)/atlas.height - y*sy
            entries.append(struct.pack('<6I2Q6f2I', x,y,q.width_words,q.height,cx,cy,
                                       ph,ch,sx,0,ox,0,sy,oy,3,t.mode))
            report.append(dict(player=player+1,tile=i,depth=t.mode,
                               rect=[x,y,q.width_words,q.height],clut=[cx,cy]))
    (output/'mapping.bin').write_bytes(b'HDMAP002'+struct.pack('<I',len(entries))+b''.join(entries))
    (output/'pack-report.json').write_text(json.dumps(dict(source_sha256=STOCK_SHA,
        generated_art_sha256=hashlib.sha256(art.read_bytes()).hexdigest(),
        atlas_size=atlas.size,base_texture_bytes=atlas.width*atlas.height*4,
        preserved_tiles=[0,6,8,12,13],tiles=report),indent=2)+'\n',encoding='utf-8')
    print(f'Kuma Polar Bear: {len(entries)} guarded tiles, {atlas.width}x{atlas.height} atlas')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--art',type=Path,required=True)
    p.add_argument('--output',type=Path,default=Path('mods/assets/kuma-polar-bear'))
    a = p.parse_args()
    build(a.source,a.art,a.output)
