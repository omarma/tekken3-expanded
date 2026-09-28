#!/usr/bin/env python3
"""Compare two images and report pixel differences."""
import sys
from PIL import Image

a = Image.open(sys.argv[1])
b = Image.open(sys.argv[2])
diff = 0
for y in range(a.height):
    for x in range(a.width):
        if a.getpixel((x, y)) != b.getpixel((x, y)):
            diff += 1
print(f'Pixels different: {diff} out of {a.width * a.height}')
