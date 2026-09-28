"""Pack 2:3 skin gallery PNGs into the runtime's HDRGBA01 texture format."""
from pathlib import Path
import argparse,struct
from PIL import Image
ap=argparse.ArgumentParser();ap.add_argument('--directory',type=Path,default=Path(__file__).resolve().parents[1]/'mods/assets/outfit-menu');args=ap.parse_args()
for source in sorted(args.directory.glob('*.png')):
    with Image.open(source) as image:
        image=image.convert('RGBA')
        if image.width*3!=image.height*2:
            raise ValueError(f'{source.name}: expected 2:3, got {image.size}')
        if image.width*image.height>16777216:
            raise ValueError(f'{source.name}: image too large')
        source.with_suffix('.rgba').write_bytes(b'HDRGBA01'+struct.pack('<II',*image.size)+image.tobytes())
        print(source.name,image.size)
