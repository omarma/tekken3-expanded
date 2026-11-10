"""Interface pack of a guest: five indexed TIMs in <Name>-T3-ui.jui.

The images come from TTT1 (ui_art.t3_images): the loading-screen portrait and
the selector / loading tiles. Their geometry is fixed by the runtime
(src/tekken3_ttt1_roster.c, load_ui). Their palettes: palette_of (Lab k-means).
Beside the pack, the HD tile and portrait (write_hd, F28).

The portrait's colours carry the semi-transparency bit (0x8000), as every
colour of a stock portrait does: the selector fades its bands in and out with
semi-transparent strips (t3-ps1 ovl4, sel_panels_draw), which leave a texel
without the bit opaque.
"""
import struct
from PIL import Image

# (name, width, height, width in halfwords)
SPECS = [('portrait',      168, 252, 126),
         ('selector-tall',  44,  68,  32),
         ('selector',       44,  58,  32),
         ('loading-tall',   44,  34,  32),
         ('loading',        44,  29,  32)]


def _lab(rgb):
    """sRGB (n x 3, 0..255) -> CIE Lab (D65)."""
    import numpy as np
    c = rgb / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    xyz = c @ np.array([[0.4124, 0.2126, 0.0193], [0.3576, 0.7152, 0.1192], [0.1805, 0.0722, 0.9505]])
    xyz /= np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], 1)


def palette_of(rgb, colors, iterations=12):
    """At most `colors` RGB colours for the pixels rgb (n x 3) and each pixel's
    one: median cut to start, then k-means on the Lab distance (a band of a
    portrait at 63 colours kept Angel's blue eyes, and Ganryu's, which the
    median cut alone turned to skin)."""
    import numpy as np
    uniq, inverse = np.unique(rgb, axis=0, return_inverse=True)
    if len(uniq) <= colors: return uniq.astype(float), inverse.reshape(-1)
    side = int(np.ceil(np.sqrt(len(rgb))))
    square = np.concatenate([rgb, np.repeat(rgb[:1], side * side - len(rgb), 0)]).reshape(side, side, 3)
    q = Image.fromarray(square.astype(np.uint8)).quantize(colors=colors, method=Image.Quantize.MEDIANCUT,
                                                          dither=Image.Dither.NONE)
    centres = np.array(q.getpalette()[:3 * colors], float).reshape(-1, 3)
    lab = _lab(rgb.astype(float))
    for _ in range(iterations + 1):
        distance = ((lab[:, None, :] - _lab(centres)[None, :, :]) ** 2).sum(2)
        label = distance.argmin(1)
        if _ == iterations: break
        for k in range(len(centres)):
            members = label == k
            # an empty centre takes the pixel served worst
            centres[k] = rgb[members].mean(0) if members.any() else rgb[distance[np.arange(len(rgb)), label].argmax()]
    return centres, label


def rgb15(rgb):
    """0..255 RGB -> 15-bit PS1 colour words (never 0, which is transparent)."""
    v = sum((int(round(c)) * 31 + 127) // 255 << (j * 5) for j, c in enumerate(rgb))
    return v or 0x8000


def indexed(image, colors):
    # Reserve zero for transparency. No dither, to retain pixel edges.
    import numpy as np
    a = np.asarray(image.convert('RGBA'))
    opaque = a[:, :, 3].reshape(-1) >= 128
    rgb = a[:, :, :3].reshape(-1, 3).astype(np.int32)
    words, pixels = [0], np.zeros(len(rgb), np.uint8)
    if opaque.any():
        centres, label = palette_of(rgb[opaque], colors - 1)
        words += [rgb15(c) for c in centres]
        pixels[opaque] = label + 1
    words += [0x8000] * (colors - len(words))
    return words, pixels.tobytes()


def rgb15_bytes(image, stp=False) -> bytes:
    """An RGBA image as 15-bit halfwords, little-endian, row after row; 0
    transparent, black 0x8000, stp: every opaque texel with 0x8000: the HD grid
    tile and portrait the runtime reads (src/tekken3_ttt1_roster.c, hd_file_load)."""
    import numpy as np
    p = np.asarray(image.convert('RGBA'), dtype=np.uint32)
    r, g, b = ((p[:, :, :3] * 31 + 127) // 255).transpose(2, 0, 1)
    v = r | g << 5 | b << 10
    return np.where(p[:, :, 3] < 128, 0, np.where((v == 0) | stp, v | 0x8000, v)).astype('<u2').tobytes()

def ps1_tim(image, banded=False, colors=256):
    image = image.resize((126 if banded else 32, image.height), Image.Resampling.NEAREST)
    if banded:
        palette, pixels = [], bytearray()
        for y in range(0, image.height, 64):
            words, indices = indexed(image.crop((0, y, image.width, min(y + 64, image.height))), 64)
            palette.extend(w | 0x8000 if w else 0 for w in words)   # semi-transparency bit (module doc)
            pixels.extend(indices)
    else:
        palette, pixels = indexed(image, colors)
        palette += [0] * (256 - len(palette))
    # Destination is overridden by the native portrait uploader. Icons are
    # uploaded explicitly into the experimental roster's reserved VRAM area.
    return (struct.pack('<III4H', 16, 9, 524, 0, 480, 256, 1)
            + struct.pack('<256H', *palette)
            + struct.pack('<I4H', 12 + len(pixels), 0, 0, image.width // 2, image.height)
            + pixels)


# Next to <Name>-T3-ui.jui (F28): the HD grid tile (ui_art.hd_tile, 64 x 116)
# and the HD portrait (t3_images' 'portrait', 168 x 252), in rgb15_bytes.
HD_TILE_SUFFIX, HD_PORTRAIT_SUFFIX = 'T3-tile-hd.bin', 'T3-portrait-hd.bin'


def write_hd(images: dict, tile, out, name):
    """<name>-T3-tile-hd.bin (none without a finer tile) and <name>-T3-portrait-hd.bin in out."""
    path = out / f'{name}-{HD_TILE_SUFFIX}'
    if tile is None: path.unlink(missing_ok=True)
    else: path.write_bytes(rgb15_bytes(tile))
    (out / f'{name}-{HD_PORTRAIT_SUFFIX}').write_bytes(rgb15_bytes(images['portrait'], stp=True))


def pack(images: dict, tile_colors=256) -> tuple[bytes, list[bytes]]:
    """(the .jui pack, the five TIMs) from the SPECS images. tile_colors < 256
    leaves the tiles' palette entries past it at zero (Panda and Tiger: their
    tiles take half a palette row, tools/ttt1_panda_tiger.py)."""
    payloads = [ps1_tim(images[name], name == 'portrait', tile_colors) for name, *_ in SPECS]
    blob = bytearray(struct.pack('<4I', 0x3149554a, 1, len(SPECS), 0) + bytes(len(SPECS) * 8))
    for i, p in enumerate(payloads):
        struct.pack_into('<2I', blob, 16 + i * 8, len(blob), len(p)); blob.extend(p)
    struct.pack_into('<I', blob, 12, len(blob))
    return bytes(blob), payloads
