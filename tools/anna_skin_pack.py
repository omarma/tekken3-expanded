"""Pack Jessica-inspired Anna artwork using verified red-gown texture identities.

This only crops, resamples and edge-pads authored artwork. The original guest
textures still control transparency; no disc, mesh or gameplay data is patched.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import numpy as np
from PIL import Image
from tim_tool import scan_tims
from nina_skin_pack import fnv

STOCK_SHA = '7b7a35f6e3364275e684fe94f263a845364e08477acb9ca4b335e68a5e5b26d7'
PARTS = ['closed-eye face', 'skirt panel', 'skirt panel', 'waist',
         'chest and bodice', 'open-eye face', 'upper arm', 'opera glove',
         'back and bodice', 'neck', 'gloved fingers', 'ankle and heel',
         'leg', 'hair', 'fringe', 'glove cuff bow']


def build(source, art, output):
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != STOCK_SHA:
        raise ValueError('Requires verified US BNS 217 Anna red gown')
    tiles = scan_tims(data)
    if len(tiles) != 46:
        raise ValueError('Unexpected texture layout')
    generated = Image.open(art).convert('RGBA')
    if generated.width != generated.height or generated.width < 1024:
        raise ValueError('The authored atlas must have a 4 by 4 square-cell layout, at least 1024 square')
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
        atlas.paste(Image.fromarray(padded), (col*stride, row*stride))
    atlas.save(output/'anna.png')
    (output/'anna.rgba').write_bytes(b'HDRGBA01'+struct.pack('<2I', *atlas.size)+atlas.tobytes())
    entries, report = [], []
    for player in (0, 1):
        for i in range(16):
            t = tiles[i]; q = t.image; c = t.clut
            x, y = 384+q.x, player*256+q.y
            cx, cy = c.x, 504+player*4+c.y
            ph = fnv(data[q.offset+12:q.end_offset]); ch = fnv(data[c.offset+12:c.end_offset])
            factor = 2 if t.mode == 1 else 4
            sx = (cell-1)/((t.pixel_width-1)*atlas.width)
            sy = (cell-1)/((q.height-1)*atlas.height)
            ox = ((i%4)*stride+gutter+.5)/atlas.width-x*factor*sx
            oy = ((i//4)*stride+gutter+.5)/atlas.height-y*sy
            entries.append(struct.pack('<6I2Q6f2I', x,y,q.width_words,q.height,cx,cy,
                                       ph,ch,sx,0,ox,0,sy,oy,3,t.mode))
            report.append(dict(player=player+1, tile=i, part=PARTS[i], atlas_cell=i,
                               depth=t.mode, rect=[x,y,q.width_words,q.height], clut=[cx,cy]))
    (output/'mapping.bin').write_bytes(b'HDMAP002'+struct.pack('<I',len(entries))+b''.join(entries))
    (output/'pack-report.json').write_text(json.dumps(dict(source_sha256=STOCK_SHA,
        generated_art_sha256=hashlib.sha256(art.read_bytes()).hexdigest(),
        atlas_size=atlas.size, base_texture_bytes=atlas.width*atlas.height*4,
        tiles=report), indent=2)+'\n')
    print(f'Anna Jessica Rabbit: {len(entries)} guarded tiles, {atlas.width}x{atlas.height} atlas')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--art', type=Path, required=True)
    p.add_argument('--output', type=Path, default=Path('mods/assets/anna-jessica-rabbit'))
    a = p.parse_args(); build(a.source, a.art, a.output)
