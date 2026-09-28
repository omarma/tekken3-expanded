"""Pack generated Xiaoyu garment art and verified local stock fingerprints.

The renderer replaces color only; original transparency, geometry and lighting
remain authoritative. All skin-only, face, hair and effect tiles are untouched.
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

STOCK_SHA = '0ee953f0f6bd7c95d09ca9afc6a79d12f6e5c7e79ae5e503d442d3b6d4667a36'
GARMENT_IDS = [1,7,8,9,10,11,12,13,14,15,16,17,18,20,21,23]
# Tile 17 is an unchanged foot. Hair ties (18) share the blue ribbon material
# from tile 14 so all ribbons use the requested light-blue palette.
SELECTED = [i for i in GARMENT_IDS if i != 17]


def build(source, art, output):
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != STOCK_SHA:
        raise ValueError('Requires verified US BNS 129 Xiaoyu ribbon costume')
    tiles = scan_tims(data)
    if len(tiles) != 54:
        raise ValueError('Unexpected texture layout')
    generated = Image.open(art).convert('RGBA')
    if generated.width != generated.height:
        raise ValueError('The authored atlas must have a 4 by 4 square-cell layout')
    output.mkdir(parents=True,exist_ok=True)
    cell, gutter = 256, 16
    stride = cell+2*gutter
    atlas = Image.new('RGBA',(stride*4,stride*4))
    for j in range(16):
        col,row = j%4,j//4
        bounds = (round(col*generated.width/4),round(row*generated.height/4),
                  round((col+1)*generated.width/4),round((row+1)*generated.height/4))
        tile = generated.crop(bounds).resize((cell,cell),Image.Resampling.LANCZOS)
        padded = np.pad(np.array(tile),((gutter,gutter),(gutter,gutter),(0,0)),mode='edge')
        atlas.paste(Image.fromarray(padded),(col*stride,row*stride))
    atlas.save(output/'xiaoyu.png')
    (output/'xiaoyu.rgba').write_bytes(b'HDRGBA01'+struct.pack('<2I',*atlas.size)+atlas.tobytes())
    entries,report = [],[]
    for player in (0,1):
        for i in SELECTED:
            t=tiles[i];q=t.image;c=t.clut
            x,y=384+q.x,player*256+q.y
            cx,cy=c.x,504+player*4+c.y
            ph=fnv(data[q.offset+12:q.end_offset]);ch=fnv(data[c.offset+12:c.end_offset])
            factor=2 if t.mode==1 else 4
            j=GARMENT_IDS.index(14 if i==18 else i)
            sx=(cell-1)/((t.pixel_width-1)*atlas.width)
            sy=(cell-1)/((q.height-1)*atlas.height)
            ox=((j%4)*stride+gutter+.5)/atlas.width-x*factor*sx
            oy=((j//4)*stride+gutter+.5)/atlas.height-y*sy
            entries.append(struct.pack('<6I2Q6f2I',x,y,q.width_words,q.height,cx,cy,
                                       ph,ch,sx,0,ox,0,sy,oy,3,t.mode))
            report.append(dict(player=player+1,tile=i,atlas_cell=j,depth=t.mode,
                               rect=[x,y,q.width_words,q.height],clut=[cx,cy]))
    (output/'mapping.bin').write_bytes(b'HDMAP002'+struct.pack('<I',len(entries))+b''.join(entries))
    (output/'pack-report.json').write_text(json.dumps(dict(source_sha256=STOCK_SHA,
        generated_art_sha256=hashlib.sha256(art.read_bytes()).hexdigest(),
        atlas_size=atlas.size,base_texture_bytes=atlas.width*atlas.height*4,
        tiles=report),indent=2)+'\n')
    print(f'Xiaoyu Cherry Blossom Ribbon: {len(entries)} guarded tiles, {atlas.width}x{atlas.height} atlas')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--art',type=Path,required=True)
    p.add_argument('--output',type=Path,default=Path('mods/assets/xiaoyu-cherry-blossom'))
    a=p.parse_args();build(a.source,a.art,a.output)
