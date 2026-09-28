from PIL import Image
import sys
img = Image.open(sys.argv[1])
out = sys.argv[1].replace('.bmp', '.png')
img.save(out)
print(f'{img.size} mode={img.mode} -> {out}')
