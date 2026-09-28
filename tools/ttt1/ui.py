"""Interface pack of a guest: five indexed TIMs in <Name>-T3-ui.jui.

The images come from TTT1 (ui_art.t3_images): the loading-screen portrait and
the selector / loading tiles. Their geometry is fixed by the runtime
(src/tekken3_ttt1_roster.c, load_ui).
"""
import struct
from PIL import Image

# (name, width, height, width in halfwords)
SPECS = [('portrait',      168, 252, 126),
         ('selector-tall',  44,  68,  32),
         ('selector',       44,  58,  32),
         ('loading-tall',   44,  34,  32),
         ('loading',        44,  29,  32)]


def indexed(image, colors):
    # Reserve zero for transparency. Dither is disabled to retain pixel edges.
    q = image.convert('RGB').quantize(colors=colors - 1, dither=Image.Dither.NONE)
    palette = q.getpalette()
    words = [0]
    for i in range(colors - 1):
        rgb = palette[i * 3:i * 3 + 3]
        v = sum(((c * 31 + 127) // 255) << (j * 5) for j, c in enumerate(rgb))
        words.append(v or 0x8000)
    pixels = bytes(0 if a < 128 else i + 1 for i, a in zip(q.tobytes(), image.getchannel('A').tobytes()))
    return words, pixels

def ps1_tim(image, banded=False):
    image = image.resize((126 if banded else 32, image.height), Image.Resampling.NEAREST)
    if banded:
        palette, pixels = [], bytearray()
        for y in range(0, image.height, 64):
            words, indices = indexed(image.crop((0, y, image.width, min(y + 64, image.height))), 64)
            palette.extend(words)
            pixels.extend(indices)
    else:
        palette, pixels = indexed(image, 256)
    # Destination is overridden by the native portrait uploader. Icons are
    # uploaded explicitly into the experimental roster's reserved VRAM area.
    return (struct.pack('<III4H', 16, 9, 524, 0, 480, 256, 1)
            + struct.pack('<256H', *palette)
            + struct.pack('<I4H', 12 + len(pixels), 0, 0, image.width // 2, image.height)
            + pixels)


def pack(images: dict) -> tuple[bytes, list[bytes]]:
    """(the .jui pack, the five TIMs) from the SPECS images."""
    payloads = [ps1_tim(images[name], name == 'portrait') for name, *_ in SPECS]
    blob = bytearray(struct.pack('<4I', 0x3149554a, 1, len(SPECS), 0) + bytes(len(SPECS) * 8))
    for i, p in enumerate(payloads):
        struct.pack_into('<2I', blob, 16 + i * 8, len(blob), len(p)); blob.extend(p)
    struct.pack_into('<I', blob, 12, len(blob))
    return bytes(blob), payloads
