"""Compile authored forest PNGs and verified local stage metadata into a host pack.

Requires Pillow and numpy. Never changes or redistributes the input ARC/model.
The mapping stores only texture fingerprints and UV transforms.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import struct
from pathlib import Path
import numpy as np
from PIL import Image
from tim_tool import scan_tims

TEXTURE_SHA = "297577e4021e005c6229ea59b1e35a91b35ea3d28e9b0d3bfbc379b8871256b2"
MODEL_SHA = "8da8367a81d8b1c8c18ecdd8373a5d24d2389e5eb1da8d74e1565a4286589f4d"

def fnv(data: bytes) -> int:
    h = 14695981039346656037
    for b in data:
        h = ((h ^ b) * 1099511628211) & ((1 << 64) - 1)
    return h

def build_mapping(texture_data: bytes, model_data: bytes):
    if hashlib.sha256(texture_data).hexdigest() != TEXTURE_SHA:
        raise ValueError("Requires verified US BNS 038 forest texture ARC")
    if hashlib.sha256(model_data).hexdigest() != MODEL_SHA:
        raise ValueError("Requires verified US BNS 058 forest model")
    tiles = scan_tims(texture_data)
    vram = np.zeros((512,1024), dtype='<u2')
    for tile in tiles:
        for block in (tile.clut, tile.image):
            pixels = np.frombuffer(texture_data, dtype='<u2', offset=block.offset+12,
                                   count=block.width_words*block.height).reshape(block.height,block.width_words)
            vram[block.y:block.y+block.height, block.x:block.x+block.width_words] = pixels
    transforms: dict[int, list[np.ndarray]] = {}
    hits = 0
    for rowid in range(struct.unpack_from('<I', model_data, 8)[0]):
        row = struct.unpack_from('<7I', model_data, 12 + rowid*28)
        vertices = np.array([struct.unpack_from('<4h', model_data, 12+row[0]+j*8)[:3]
                             for j in range(row[1])])
        for j in range(row[3]):
            off = 12 + row[4] + j*20
            q = model_data[off:off+20]
            if q[3] not in (0x24, 0x2c):
                raise ValueError(f"Unsupported primitive at {off}")
            n = 4 if q[3] == 0x2c else 3
            xyz = vertices[list(q[16:16+n])]
            uv = np.array([[q[4], q[5]], [q[8], q[9]], [q[12], q[13]], [q[14], q[15]]], dtype=float)[:n]
            clut, tpage = struct.unpack_from('<H', q, 6)[0], struct.unpack_from('<H', q, 10)[0]
            cx, cy = (clut & 63)*16, clut >> 6
            uv[:,0] += (tpage & 15)*256
            uv[:,1] += (tpage & 16)*16
            matches = [i for i,t in enumerate(tiles) if t.clut.x == cx and t.clut.y == cy
                       and np.all(uv[:,0] >= t.image.x*4) and np.all(uv[:,0] < (t.image.x+t.image.width_words)*4)
                       and np.all(uv[:,1] >= t.image.y) and np.all(uv[:,1] < t.image.y+t.image.height)]
            if not matches:
                raise ValueError(f"No TIM for primitive {off}")
            i = matches[-1]
            if i == 473:  # tiny flat sky texel: retain original solid color
                continue
            if i >= 482:
                # Each stock floor patch spans the same material. Match the
                # actual mesh UV endpoints, including its 1px sampling inset.
                lo, hi = uv.min(axis=0), uv.max(axis=0)
                if np.any(hi == lo): continue
                dst = (uv-lo)/(hi-lo)
            else:
                angles = np.arctan2(xyz[:,0], xyz[:,2])
                if np.ptp(angles) > math.pi:
                    angles = np.where(angles < 0, angles+2*math.pi, angles)
                dst = np.column_stack(((angles+math.pi)/(2*math.pi), (xyz[:,1]+1280)/1280))
            a = np.column_stack((uv, np.ones(n)))
            coeff, _, rank, _ = np.linalg.lstsq(a, dst, rcond=None)
            if rank != 3: continue
            transforms.setdefault(i, []).append(coeff.T)
            hits += 1
    # The repeating fighting plane is submitted separately by the game, so
    # its four final TIMs are not referenced by the backdrop's model stream.
    for i in range(482,486):
        t = tiles[i]
        transforms[i] = [np.array([[1/63,0,-t.image.x*4/63],
                                  [0,1/63,-t.image.y/63]])]
    records = bytearray(); report = []
    for i, matrices in sorted(transforms.items()):
        t = tiles[i]; b = t.image; c = t.clut
        matrix = matrices[0]
        # Reused quads can occur one complete turn apart. Their normalized
        # panorama positions remain equivalent under horizontal GL_REPEAT.
        # TIMs share CLUT slots. Unused palette entries differ between TIMs;
        # the last upload is authoritative for every user of that palette.
        pix = vram[b.y:b.y+b.height,b.x:b.x+b.width_words].tobytes()
        pal = vram[c.y,c.x:c.x+16].tobytes()
        kind = 2 if i >= 482 else 1
        records += struct.pack('<6I2Q6fI', b.x,b.y,b.width_words,b.height,c.x,c.y,
                               fnv(pix),fnv(pal),*matrix.flatten(),kind)
        report.append({'tim':i, 'kind':kind, 'uses':len(matrices)})
    if len(transforms) < 470 or not all(i in transforms for i in range(482,486)):
        raise ValueError(f"Incomplete forest coverage: {len(transforms)} tiles")
    return b'HDMAP001'+struct.pack('<I',len(transforms))+records, report, hits

def compile_image(source: Path, target: Path, crop_bars: bool):
    image = Image.open(source).convert('RGBA')
    original_size = image.size
    box = (0,0,*image.size)
    if crop_bars:
        # Normalize generator letterboxing, without altering the authored art.
        a = np.asarray(image)
        rows = np.where(a[:,:,:3].mean(axis=(1,2)) > 12)[0]
        if not len(rows): raise ValueError('Empty background image')
        box = (0,int(rows[0]),image.width,int(rows[-1])+1)
        image = image.crop(box)
    if max(image.size) > 8192 or image.width*image.height > 16777216:
        raise ValueError('Image exceeds runtime texture budget')
    target.write_bytes(b'HDRGBA01'+struct.pack('<II',*image.size)+image.tobytes())
    return {'source_size':original_size,'crop':box,'size':image.size,'gpu_bytes':image.width*image.height*4}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--textures', type=Path, required=True)
    p.add_argument('--model', type=Path, required=True)
    p.add_argument('--assets', type=Path, default=Path('mods/assets/forest-hd'))
    a=p.parse_args()
    mapping, tiles, hits=build_mapping(a.textures.read_bytes(),a.model.read_bytes())
    a.assets.mkdir(parents=True,exist_ok=True)
    report={'format':'forest-hd-1','texture_bns':38,'model_bns':58,'mapped_primitives':hits,'tiles':tiles}
    report['background']=compile_image(a.assets/'background.png',a.assets/'background.rgba',True)
    report['ground']=compile_image(a.assets/'ground.png',a.assets/'ground.rgba',False)
    (a.assets/'mapping.bin').write_bytes(mapping)
    (a.assets/'pack-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f"Forest HD: {len(tiles)} guarded tiles, {hits} mesh primitives; "
          f"background {report['background']['size']}, ground {report['ground']['size']}")
if __name__ == '__main__': main()
