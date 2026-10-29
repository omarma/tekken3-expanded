"""TTT Stages S2: the Tekken Tag Tournament arcade stages for the Arcade Stages
decoder (decode.py, scene.py, pack.py, validate.py, render.py).

TTT's stage code is a sibling of Tekken 3 arcade's: same geometry container,
same GPU packets, same far background, cone and floor lighting. This module
holds what differs, each item with the TTT routine it is read from (TIPS
sections 91, 108 and the S2 section; S1's notes in tools/ttt_stages/notes/).
The program is TTT's main program unpacked at 0x80010000
(tools/ttt1/extract.py); stage n (u16 0x802434E4) is archive 7 + n
(u32 0x80022D98), every file LZ-packed; stage 14 (Unknown) has no archive.

Geometry (loader 0x80150D90, builder 0x801510F0, drawing 0x80153914, emitter
0x801542A4):
- OT slot of a tile: u8 0x80026FF8 + 0x100 * stage (T3: one table for all);
- tiles the builder skips: s16 lists chosen by 0x8015D0AC (first word 1:
  keep only the listed tiles, else skip them; one list without and one with
  True Ogre), SKIP / SKIP_TRUE_OGRE;
- primitives the builder masks: 0x8015D28C, per stage and tile a list of
  primitive indices masked always, then -1, then those masked with True
  Ogre, -1 (MASKS). A masked primitive has its header rewritten 0xFFFFFF0k in
  the geometry in RAM, its packet words reserved and never written, and the
  emitter skips it;
- True Ogre (character 0x14 in a team or fighting, 0x8015D018, read at the
  load): every colour of every packet = the stage's byte of the string at
  0x80022E4C, except stage 6's rewritten FT4;
- stage 6, FT4 0x2D010709 (0x80152000): CLUT 0x182D on texture page
  (0x58, 0x2C0) becomes semi-transparent on page (0x58, 0x2C0) with abr 1, and
  primitives of tiles 0x62..0x65, 0x6A, 0x92..0x95, 0x9A get fixed uv, CLUT
  and pages (the torches the textures animate, STAGE6_FT4);
- OT B: stage 3 tiles 0..0xF, 0x17, 0x18; stage 4 tiles < 0x55; stage 11 the
  same 16 tiles as T3 (0x801512E8);
- matrix: as T3's, row 1 of the camera rotation x 10 >> 4 rounded towards
  minus infinity (T3 towards zero), no x 7 / 10 for stage 3; the fight axis
  starts at u32 0x80022DD4 + 8 n + 4 (0x801534CC);
- emitter: before NCLIP, FT4 0x2C000709 / 0x2D010709 and GT4 0x3D010A0C keep a
  primitive only when one of its three culling vertices has y >= -12 and
  -32 <= x <= 544 (frame 0x80340130); FT4 0x2C000709 is then never culled:
  `mfc2 $t0, MAC0` is followed at once by `lw $t0` (the OT word), which
  cancels it in its delay slot, and `blez $t0` in the lw's delay slot sees
  the old $t0, a scratchpad address (0x801544B8, measured in MAME);
- OT A at main rank 995, B at 1021 (stage 3: A 1021, B 1022), 0x80153738;
- cone 0x80154BC4: the width table s16 0x80027EF8[H - 400] without the
  x 9 / 10, its rays stepped with the 1.12 sine 0x8001B194.
"""
from __future__ import annotations

import dataclasses
import json
import pickle
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/arcade_stages'), str(ROOT / 'tools'), str(ROOT / 'tools/ttt1')]
import decode  # noqa: E402

WORK = ROOT / 'workspace/ttt-stages'
CACHE = WORK / 'cache'
BASE = 0x80010000
NSTAGE = 15
STAGE_ARCHIVES = 0x80022D98      # u32 per stage: archive (7 + n; 14 -> 7, never read)
NO_ARCHIVE = 14                  # Unknown: no tiles, no archive (0x80150D90)


def default_zip() -> Path:
    src = ROOT / 'workspace/ttt1-import/source.json'
    if src.exists():
        p = json.loads(src.read_text(encoding='utf-8')).get('ttt1')
        if p:
            return Path(p)
    return Path('C:/TekkenProject/discs/tektagt.zip')


class Ttt:
    """TTT's program and archive files (LZ-unpacked where the game unpacks
    them), from the user's tektagt.zip. cache=True (development) keeps them
    in workspace/ttt-stages/cache/ttt.pkl (never committed); cache=False (the
    setup) reads the zip as it is."""
    game = 'ttt'

    def __init__(self, zip_path: Path | None = None, cache: bool = True):
        cached = CACHE / 'ttt.pkl'
        if cache and cached.exists():
            self.__dict__.update(pickle.loads(cached.read_bytes()))
            return
        import arcade_model_probe as probe
        import extract as ttt1
        zip_path = zip_path or default_zip()
        sets = json.loads(probe.MANIFEST.read_text(encoding='utf-8'))['sets']
        wanted = [r for r in sets[probe.ttt_set(zip_path)]['regions'] if r['name'] in ('maincpu:rom', 'bankedroms')]
        regions, _ = probe.reconstruct(zip_path, {'regions': wanted})
        rom = ttt1.Rom(regions['bankedroms'], regions['maincpu:rom'])
        self.program = ttt1.unpack_game(regions['maincpu:rom'])
        self.files = {}
        for i, n, a, size in ttt1.archives(self.program, rom):
            data = rom(a, size)
            if i in ttt1.PACKED and data:
                data = ttt1.lz(data, 0)
            self.files.setdefault(i, []).append(data)
        if cache:
            CACHE.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(pickle.dumps(self.__dict__))

    def word(self, a: int, n: int = 1, fmt: str = 'I'):
        v = struct.unpack_from('<%d%s' % (n, fmt), self.program, a - BASE)
        return v if n > 1 else v[0]

    def bytes_at(self, a: int, n: int) -> bytes:
        return self.program[a - BASE:a - BASE + n]

    def archive_files(self, k: int):
        return self.files[k]

    def stage_archive(self, stage: int):
        return None if stage == NO_ARCHIVE else self.word(STAGE_ARCHIVES + 4 * stage)

    def stage(self, stage: int):
        """(geometry bytes or None, [TIMs of files 1.. as 0x801557D4 sends them])."""
        k = self.stage_archive(stage)
        if k is None:
            return None, []
        files = self.files[k]
        return files[0], [t for f in files[1:] for t in file_tims(f)]


def file_tims(f: bytes):
    """0x801557D4: the TIMs of one unpacked file, walked while the word is
    0x10 (all TTT stage files carry a CLUT and end with a word 0)."""
    out, p = [], 0
    while p + 4 <= len(f) and struct.unpack_from('<I', f, p)[0] == 0x10:
        flags = struct.unpack_from('<I', f, p + 4)[0]
        assert flags & 8, 'a TIM without CLUT: 0x801557D4 would loop'
        size, x, y, w, h = struct.unpack_from('<I4H', f, p + 8)
        clut = (x, y, w, h, bytes(f[p + 20:p + 20 + w * h * 2]))
        q = p + 8 + (size & ~3)
        isize, x, y, w, h = struct.unpack_from('<I4H', f, q)
        image = (x, y, w, h, bytes(f[q + 12:q + 12 + w * h * 2]))
        out.append(dict(bpp=(4, 8, 16)[flags & 3], clut=clut, image=image))
        p = q + (isize & ~3)
    return out


def get_tpage(tp, abr, x, y):
    """GetTPage of the System 12 library (0x8018C7EC): bit 11 = y + 512."""
    return (tp << 7 | abr << 5 | (y & 0x100) >> 4 | (x & 0x3FF) >> 6 | (y & 0x200) << 2) & 0xFFFF


def get_clut(x, y):
    return (y << 6 | x >> 4) & 0xFFFF


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
SLOTS = 0x80026FF8               # u8 per tile, 0x100 per stage
FIGHT_AXIS_START = 0x80022DD4    # 8 bytes per stage: u32 n, u32 fight axis at the round start (0x801534CC)
TRUE_OGRE_SHADE = 0x80022E4C     # u8 per stage: every packet colour with True Ogre
SKIP = {2: 0x80024038, 4: 0x8002404C, 6: 0x80024054, 9: 0x8002405C, 12: 0x80024064}
SKIP_TRUE_OGRE = {0: 0x80024070, 1: 0x800240AC, 2: 0x800240D0, 3: 0x80024110, 4: 0x80024168,
                  5: 0x8002419C, 6: 0x800241C8, 7: 0x800241E0, 8: 0x8002424C, 9: 0x80024280,
                  10: 0x800242CC, 13: 0x800242CC, 12: 0x800242FC}
# 0x8015D28C: stage -> {tile: list}, read in its switch statements.
MASKS = {
    0: {0x39: 0x8002436C, 0x47: 0x80024374, 0x48: 0x80024380, 0x49: 0x80024388, 0x57: 0x800243C0,
        0x58: 0x800243F0, 0x59: 0x80024404, 0x66: 0x80024410, 0x67: 0x80024460, 0x68: 0x80024484,
        0x69: 0x80024494, 0x74: 0x800244A4, 0x75: 0x800244AC, 0x76: 0x800244D4, 0x7A: 0x800244EC,
        0x85: 0x80024508, 0x86: 0x80024520, 0x8A: 0x80024528, 0x96: 0x80024530, 0x97: 0x8002453C,
        0x9A: 0x80024544, 0xA7: 0x8002454C, 0xA8: 0x8002455C, 0xAA: 0x80024564, 0xB8: 0x80024580,
        0xB9: 0x8002458C, 0xC8: 0x800245A8, 0xC9: 0x800245B0},
    1: {0x67: 0x800245B8, 0x76: 0x800245C4, 0x77: 0x800245D4, 0x78: 0x800245DC, 0x86: 0x800245F0,
        0x89: 0x80024600},
    2: {0x56: 0x8002462C, 0x5B: 0x80024638, 0x5C: 0x80024648, 0x64: 0x80024660, 0x66: 0x80024668,
        0x6B: 0x80024610, 0x74: 0x80024680, 0x7B: 0x8002461C, 0x84: 0x80024688, 0x94: 0x80024690,
        0x9B: 0x80024698, 0xB6: 0x800246A0, 0xB7: 0x800246A8, 0xB9: 0x800246B0, 0xD8: 0x800246B8},
    3: {0x2B: 0x800246C0, 0x35: 0x800246C8, 0x41: 0x800246D0, 0x42: 0x800246D8, 0x44: 0x800246E0,
        0x45: 0x800246EC, 0x5B: 0x800246F4, 0x61: 0x800246FC, 0x6B: 0x80024708, 0x7B: 0x80024710,
        0x82: 0x80024720, 0x8B: 0x80024728, 0x9A: 0x80024730, 0x9B: 0x80024754, 0xAB: 0x8002476C,
        0xBA: 0x80024774, 0xBB: 0x8002479C, 0xCA: 0x800247AC, 0xD4: 0x800247D0, 0xD5: 0x800247E0,
        0xD7: 0x800247EC, 0xD9: 0x800247F8},
    4: {0x46: 0x80024804, 0x49: 0x8002480C, 0x55: 0x80024814, 0x5A: 0x80024834, 0x65: 0x80024854,
        0x6A: 0x8002486C, 0x95: 0x80024884, 0x9A: 0x8002489C, 0xA5: 0x800248B4, 0xA6: 0x800248BC,
        0xA7: 0x800248C8, 0xA8: 0x800248D4, 0xA9: 0x800248E0, 0xAA: 0x800248EC},
    5: {0x67: 0x800248F4, 0x68: 0x80024918, 0x69: 0x80024944, 0x6A: 0x80024954, 0x75: 0x80024968,
        0x76: 0x80024970, 0x77: 0x8002498C, 0x78: 0x80024994, 0x79: 0x800249A0, 0x7A: 0x800249C0,
        0x86: 0x800249C8, 0x87: 0x800249DC, 0x88: 0x800249F8, 0x89: 0x80024A1C, 0x97: 0x80024A2C,
        0x98: 0x80024A4C, 0xA7: 0x80024A80, 0xA8: 0x80024A8C, 0xB7: 0x80024AA8, 0xB8: 0x80024AC0},
    6: {0x66: 0x80024AD8, 0x67: 0x80024B30, 0x68: 0x80024BB0, 0x69: 0x80024C20, 0x79: 0x80024C88,
        0x7A: 0x80024C9C, 0x89: 0x80024CAC, 0x8A: 0x80024CC4, 0x96: 0x80024CD4, 0x97: 0x80024D2C,
        0x98: 0x80024DA8, 0x99: 0x80024E18},
    7: {0x44: 0x80024E80, 0x45: 0x80024E8C, 0x48: 0x80024E98, 0x49: 0x80024ED8, 0x4A: 0x80024F00,
        0x4B: 0x80024F28, 0x4C: 0x80024F54, 0x4D: 0x80024F84, 0x56: 0x80024FAC, 0x57: 0x80024FDC,
        0x5D: 0x80025010, 0x65: 0x80025018, 0x66: 0x80025028, 0x6D: 0x80025034, 0x74: 0x8002503C,
        0x75: 0x80025060, 0x7D: 0x8002506C, 0x7F: 0x80025074, 0x84: 0x80025080, 0x85: 0x80025088,
        0x8D: 0x800250A4, 0x8F: 0x800250AC, 0x94: 0x800250BC, 0x95: 0x800250C4, 0x9F: 0x800250D8,
        0xA4: 0x800250E8, 0xA5: 0x800250F0, 0xAF: 0x800250FC, 0xB6: 0x8002510C, 0xB7: 0x80025114,
        0xB8: 0x8002511C, 0xB9: 0x80025124, 0xBC: 0x8002512C, 0xCB: 0x80025134},
    8: {0x66: 0x8002513C, 0x67: 0x80025154, 0x68: 0x80025170, 0x69: 0x80025188, 0x76: 0x800251A0,
        0x79: 0x800251B4, 0x86: 0x800251C8, 0x89: 0x800251DC, 0x96: 0x800251F0, 0x97: 0x80025208,
        0x98: 0x80025224, 0x99: 0x8002523C},
    9: {0x2A: 0x800255EC, 0x2B: 0x800255F4, 0x36: 0x800255FC, 0x43: 0x80025630, 0x45: 0x80025638,
        0x46: 0x80025658, 0x47: 0x80025668, 0x48: 0x80025674, 0x53: 0x8002567C, 0x54: 0x80025694,
        0x5A: 0x8002569C, 0x5C: 0x800256A4, 0x5D: 0x800256B0, 0x65: 0x800256B8, 0x73: 0x800256C8,
        0x74: 0x800256FC, 0x7B: 0x8002571C, 0x7C: 0x8002572C, 0x83: 0x80025740, 0x84: 0x8002575C,
        0x8B: 0x80025778, 0x94: 0x80025788, 0xA4: 0x800257C0, 0xA8: 0x800257D8, 0xA9: 0x800257E0,
        0xAB: 0x80025804, 0xB3: 0x8002580C, 0xB4: 0x80025818, 0xB5: 0x80025838, 0xB6: 0x80025850,
        0xB7: 0x80025888, 0xB8: 0x800258A4, 0xB9: 0x800258BC, 0xBA: 0x800258F0, 0xC4: 0x800258F8,
        0xC7: 0x80025904, 0xC8: 0x80025920},
    10: {0x66: 0x80025504, 0x67: 0x80025510, 0x69: 0x80025564, 0x7A: 0x80025588, 0xA6: 0x800255A8,
         0xA7: 0x800255CC},
    12: {0x14: 0x80025254, 0x15: 0x80025268, 0x1A: 0x80025278, 0x1B: 0x8002528C, 0x22: 0x8002529C,
         0x23: 0x800252C0, 0x24: 0x800252C8, 0x2B: 0x800252D4, 0x2C: 0x800252E0, 0x2D: 0x800252E8,
         0x31: 0x80025310, 0x32: 0x8002531C, 0x3D: 0x80025324, 0x41: 0x80025330, 0x42: 0x80025340,
         0x4D: 0x80025350, 0x51: 0x80025368, 0x52: 0x80025370, 0x5D: 0x80025378, 0x62: 0x80025380,
         0x6D: 0x80025388, 0x71: 0x80025390, 0x92: 0x800253A0, 0x9D: 0x800253A8, 0xA1: 0x800253B0,
         0xA2: 0x800253BC, 0xA6: 0x800253C4, 0xAD: 0x800253D0, 0xAE: 0x800253DC, 0xB1: 0x800253E4,
         0xB2: 0x800253F0, 0xBD: 0x80025400, 0xBE: 0x80025414, 0xC1: 0x8002541C, 0xC2: 0x8002542C,
         0xCD: 0x80025434, 0xCE: 0x80025444, 0xD2: 0x8002544C, 0xD3: 0x80025474, 0xD4: 0x8002547C,
         0xD5: 0x8002548C, 0xD6: 0x80025498, 0xDA: 0x800254A0, 0xDB: 0x800254A8, 0xDC: 0x800254B8,
         0xDD: 0x800254C8, 0xE7: 0x800254EC, 0xE8: 0x800254F4, 0xE9: 0x800254FC},
}
MASKS[13] = MASKS[10]            # case 10: case 0xd: in 0x8015D28C
# Headers the builder can mask (marker 0xFFFFFF0k); the others are always built.
MASKABLE = (0x2D010709, 0x3D010A0C, 0xBD010A0C, 0x2C000709, 0xAD010709, 0x25010607, 0x35010809, 0xAC000709)
FRAME_TESTED = (0x2C000709, 0x2D010709, 0x3D010A0C)
NO_NCLIP = (0x2C000709,)         # 0x801544B8: the test sees the old $t0 (load delays), not MAC0


@dataclass
class TttPrim(decode.Prim):
    semi: bool = False           # semi-transparent (stage 6, SetSemiTrans: code bit 1)
    keeps: bool = False          # stage 6's rewritten FT4: no True Ogre colour

    @property
    def code(self):
        return decode.GPU_CODE[self.kind] | (2 if self.semi else 0)


def s16_list(src, a):
    out = []
    while True:
        v = src.word(a + 2 * len(out), 1, 'h')
        if v == -1:
            return out
        out.append(v)


def skipped(src, stage, tile, true_ogre):
    """0x8015D0AC(tile, True Ogre): the builder makes nothing of this tile."""
    a = (SKIP_TRUE_OGRE if true_ogre else SKIP).get(stage)
    if a is None:
        return False
    keep_only = src.word(a, 1, 'h') == 1
    listed = tile in s16_list(src, a + 2)
    return not listed if keep_only else listed


def masked(src, stage, tile, true_ogre):
    """0x8015D28C: {primitive index} masked for this tile."""
    a = MASKS.get(stage, {}).get(tile)
    if a is None:
        return set()
    always = s16_list(src, a)
    out = set(always)
    if true_ogre:
        out |= set(s16_list(src, a + 2 * (len(always) + 1)))
    return out


def layer_b(stage, tile):
    """0x801512E8: tiles of OT B."""
    if stage == 3:
        return tile <= 0xF or tile in (0x17, 0x18)
    if stage == 4:
        return tile < 0x55
    if stage == 11:
        return decode.layer_b(11, tile)
    return False


def true_ogre_shade(src, stage):
    return src.bytes_at(TRUE_OGRE_SHADE, 16)[stage]


# 0x80152000, stage 6: (tiles and primitive indices, page, CLUT, uv x 4, semi-transparent).
_P58 = get_tpage(0, 1, 0x58, 0x2C0)
STAGE6_FT4 = [
    ({0x62: (2, 4), 0x63: (2,), 0x64: (1,), 0x65: (2, 5), 0x9A: (2, 5)},
     get_tpage(0, 0, 0, 0x240), get_clut(0x290, 0x60), ((0, 0x7E), (0x3E, 0x7E), (0, 0x40), (0x3E, 0x40)), False),
    ({0x62: (1, 3), 0x63: (1,), 0x64: (0,), 0x65: (1, 4), 0x9A: (1, 4)},
     get_tpage(0, 0, 0, 0x200), get_clut(0x290, 0x60), ((0x3E, 0), (0, 0), (0x3E, 0x3E), (0, 0x3E)), False),
    ({0x6A: (2, 5), 0x92: (1, 3), 0x93: (2,), 0x94: (2,), 0x95: (2, 5)},
     get_tpage(0, 0, 0, 0x240), get_clut(0x290, 0x60), ((0x3E, 0x7E), (0, 0x7E), (0x3E, 0x40), (0, 0x40)), False),
    ({0x6A: (1, 4), 0x92: (0, 4), 0x93: (1,), 0x94: (1,), 0x95: (1, 4)},
     get_tpage(0, 0, 0, 0x200), get_clut(0x290, 0x60), ((0, 0), (0x3E, 0), (0, 0x3E), (0x3E, 0x3E)), False),
    ({0x62: (0, 5), 0x63: (0,), 0x64: (2,), 0x65: (0, 3), 0x9A: (0, 3)},
     get_tpage(0, 1, 0x90, 0x230), get_clut(0x280, 0x60), ((0x40, 0x4E), (0x40, 0x30), (0x7E, 0x4E), (0x7E, 0x30)), True),
    ({0x6A: (0, 3), 0x92: (2, 5), 0x93: (0,), 0x94: (0,), 0x95: (0, 3)},
     get_tpage(0, 1, 0x90, 0x230), get_clut(0x280, 0x60), ((0x40, 0x30), (0x40, 0x4E), (0x7E, 0x30), (0x7E, 0x4E)), True),
]


def stage6_ft4(prim, tile, k):
    """0x80152000 for stage 6 (FT4 0x2D010709 only): (primitive, rewritten)."""
    hit = False
    if prim.clut == get_clut(0x2D0, 0x60) and prim.tpage & 0x81F == get_tpage(0, 0, 0x58, 0x2C0) & 0x81F:
        prim = dataclasses.replace(prim, tpage=_P58, semi=True)
        hit = True
    for where, tpage, clut, uv, semi in STAGE6_FT4:
        if k in where.get(tile, ()):
            prim = dataclasses.replace(prim, tpage=tpage, clut=clut, uv=uv, semi=prim.semi or semi)
            hit = True
    return prim, hit


def parse_geometry(src, stage, g, true_ogre=False):
    """decode.Geometry of a TTT stage as 0x80150D90 / 0x801510F0 build it:
    tiles with the TTT slots, OT B, skipped tiles; primitives as TttPrim with
    the stage 6 rewrites and the True Ogre colours; tile.masked = the indices
    of the primitives the builder masks (their packets are reserved but
    never written nor drawn)."""
    magic, size, nrows = struct.unpack_from('<3I', g, 0)
    assert magic == 0x41 and nrows == 256, (magic, nrows)
    geo = decode.Geometry(size)
    slots = src.bytes_at(SLOTS + 0x100 * stage, 256)
    shade = true_ogre_shade(src, stage)
    for r in range(nrows):
        row = struct.unpack_from('<7I', g, 12 + 28 * r)
        vo, vn, _, _, po, pn, _ = row
        verts = [struct.unpack_from('<3h', g, 12 + vo + 8 * i) for i in range(vn)]
        prims, p = [], 12 + po
        for k in range(pn):
            prim, n = decode.parse_prim(g, p)
            prim = TttPrim(**{f.name: getattr(prim, f.name) for f in dataclasses.fields(decode.Prim)})
            hit = False
            if stage == 6 and prim.header == 0x2D010709:
                prim, hit = stage6_ft4(prim, r, k)
                prim = dataclasses.replace(prim, keeps=hit)
            if true_ogre and not hit:
                c = (shade,) * 3
                prim = dataclasses.replace(prim, colors=(c,) * max(1, len(prim.colors)))
            prims.append(prim)
            p += n
        t = decode.Tile(r, verts, prims, slot=1 + slots[r], layer_b=layer_b(stage, r),
                        skipped=skipped(src, stage, r, true_ogre), raw_row=row)
        t.masked = {k for k in masked(src, stage, r, true_ogre) if k < len(prims) and prims[k].header in MASKABLE}
        geo.tiles.append(t)
    return geo


def ot_ranks(stage):
    """(OT A rank, OT B rank) in the main OT (0x80153738)."""
    return (1021, 1022) if stage == 3 else (995, 1021)


def in_frame(x, y):
    """0x801542A4's frame test of one vertex (SXY word against the frame
    0xFFE00000, 0x02200000, 0xFFF40000 at 0x80340130)."""
    w = ((y & 0xFFFF) << 16 | (x & 0xFFFF))
    w = w - (1 << 32) if w >> 31 else w
    lo = (x & 0xFFFF) << 16
    lo = lo - (1 << 32) if lo >> 31 else lo
    return w >= -0xC0000 and -0x200000 - lo <= 0 and 0x2200000 - lo >= 0


def geometry_commands(stage, geo, cam, visible, framed=None):
    """{main OT rank: [commands in drawing order]} of the tiles, as
    0x80153914 / 0x801542A4 emit them (scene.geometry_commands with TTT's
    frame test, masks and ranks). framed(x, y): the frame test of one
    vertex (default TTT's in_frame; the PS1 port passes its own)."""
    in_frame_ = framed or in_frame
    import numpy as np
    import gte
    import scene
    emitted = {False: [], True: []}
    for t in geo.tiles:
        if not t.prims or t.skipped or len(t.verts) > 0x100:
            continue
        if not visible(t.index):
            continue
        sx, sy, sz = gte.rtps(cam, np.array(t.verts))
        for k, prim in enumerate(t.prims):
            if k in t.masked:
                continue
            i = prim.idx
            a, b, c = (i[q] for q in prim.cull)
            if prim.header in FRAME_TESTED and not any(in_frame_(int(sx[v]), int(sy[v])) for v in (a, b, c)):
                continue
            if prim.header not in NO_NCLIP and gte.nclip(sx[a], sy[a], sx[b], sy[b], sx[c], sy[c]) <= 0:
                continue
            cmds = [scene.prim_command(prim, [(int(sx[j]), int(sy[j])) for j in i])]
            cmds[0]['code'] = prim.code
            if prim.window:
                cmds = ([dict(kind='window', code=0xE2, value=scene.tex_window(*prim.window) & 0xFFFFFF)] + cmds
                        + [dict(kind='window', code=0xE2, value=0)])
            emitted[t.layer_b].append((t.slot, cmds))
    a_rank, b_rank = ot_ranks(stage)
    out = {}
    for layer, rank in ((True, b_rank), (False, a_rank)):
        seq = []
        for slot in range(15, -1, -1):
            for s_, cmds in reversed(emitted[layer]):
                if s_ == slot:
                    seq += cmds
        out[rank] = seq
    return out


# ---------------------------------------------------------------------------
# Cone (0x80154BC4): scene.tile_visibility's algorithm, other tables
# ---------------------------------------------------------------------------
SINE = 0x8001B194                # s16, 1.12 (4096 = 1), cosine = sine[a + 0x400]
CONE_FOV = 0x80027EF8            # s16 per projection distance H - 400 (u32 0x802434B8)
ROT_TABLE = 0x8023D2F8           # RotMatrix's u32 sine | cosine << 16 (4.12)


def cone_inputs(src, h, special=False):
    """The direction table and the cone width 0x80153914 passes for the
    projection distance h: the table's value as it is (T3: x 9 / 10), x 11 /
    10 when the main state u16 0x8024356A is 2. The rays step with the 1.12
    sine and >> 15: 8 steps where T3 makes one."""
    sine = src.word(SINE, 0x1400, 'h')
    dirs = [(sine[a], sine[a + 0x400]) for a in range(4096)]
    w = src.word(CONE_FOV + 2 * (h - 400), 1, 'h')
    return dirs, scene_tdiv(w * 11, 10) if special else w


def scene_tdiv(a, b):
    import scene
    return scene.tdiv(a, b)


# ---------------------------------------------------------------------------
# VRAM after the stage load (0x800F9894: 0x80150D90, then 0x80156624 ->
# 0x8015C4C0, then the floor 0x8011C204)
# ---------------------------------------------------------------------------
OBJECT_ARCHIVES = {3: 22, 11: 21}            # 0x8015FEF8: file 0 = TIMs (not packed), 1.. = TMD
EFFECTS, EFFECTS_EXTRA = 5, 6
# 0x8015C4C0, files of archive 5 after its file 0 (the effects common to all
# stages, low half, not the stage's), by stage. Stage 4's file 6 holds the
# storm skies (far background entries 15-20); stage 7's file 11 (12, the
# caged Panda's empty CLUT, when 0x8015F6A4 says True Ogre or Panda: her
# models 0x5D / 0x17, Kuma's kick costumes in table 0x8001110C, among the
# team members or fighters, 0x8015CE68; B114) and archive 6 files 0-2
# its animated textures; stage 14's archive 6 files 3-8 its floor and veils.
STAGE_EFFECTS = {3: [(5, 7), (5, 8)], 4: [(5, 6)], 6: [(5, 1), (5, 2), (5, 3)],
                 7: [(5, 11), (6, 0), (6, 1), (6, 2)], 11: [(5, 4), (5, 5)],
                 14: [(6, 3), (6, 4), (6, 5), (6, 6), (6, 7), (6, 8)]}
STAGE_EFFECTS_TRUE_OGRE = {**STAGE_EFFECTS, 7: [(5, 12)]}
# Stage 2: the particles' two CLUTs (LoadClut2 of the CLUTs of archive 5 files
# 9 and 10 at (0x270, 0x40) and (0x270, 0xFF)).
PARTICLE_CLUTS = {2: [((5, 9), (0x270, 0x40)), ((5, 10), (0x270, 0xFF))]}
# Stage 14: 32 CLUTs of 16 colours built from 5-bit RGB triples at 0x80023A10
# (0x30 bytes each), sent to (s16 x, y) at 0x80023990 (0x8015C4C0's end).
STAGE14_CLUTS, STAGE14_CLUT_PLACES, STAGE14_NCLUT = 0x80023A10, 0x80023990, 32


def stage14_cluts(src):
    out = []
    for i in range(STAGE14_NCLUT):
        rgb = src.bytes_at(STAGE14_CLUTS + 0x30 * i, 0x30)
        words = [rgb[3 * k] | rgb[3 * k + 1] << 5 | rgb[3 * k + 2] << 10 for k in range(16)]
        x, y = src.word(STAGE14_CLUT_PLACES + 4 * i, 2, 'h')
        out.append((x, y, words))
    return out


def stage_tims(src, stage, true_ogre=False, common=False):
    """[(source, TIM)] the stage load sends, in the game's order: the
    archive's files 1.., the objects' file 0, the effects' files of this
    stage (common=True: archive 5 file 0 first, as the game does)."""
    _, tims = src.stage(stage)
    out = [(('stage', stage), t) for t in tims]
    if stage in OBJECT_ARCHIVES:
        out += [(('objects', OBJECT_ARCHIVES[stage]), t) for t in file_tims(src.files[OBJECT_ARCHIVES[stage]][0])]
    if common:
        out += [(('effects', 5, 0), t) for t in file_tims(src.files[EFFECTS][0])]
    for k, f in (STAGE_EFFECTS_TRUE_OGRE if true_ogre else STAGE_EFFECTS).get(stage, []):
        out += [(('effects', k, f), t) for t in file_tims(src.files[k][f])]
    return out


def vram(src, stage, true_ogre=False, common=False, height=1024):
    """System 12 VRAM (height x 1024 u16) after the stage load, and the
    rectangles [(kind, x, y, w, h, bpp, source)] in upload order."""
    import numpy as np
    v = np.zeros((height, 1024), np.uint16)
    rects = []
    for source, t in stage_tims(src, stage, true_ogre, common):
        for kind in ('image', 'clut'):
            x, y, w, h, raw = t[kind]
            if kind == 'clut' and stage == 6 and (x, y) == (0x200, 0x15E):
                continue                 # 0x801557D4: not sent on stage 6 (archive 5 file 2 has one)
            v[y:y + h, x:x + w] = np.frombuffer(raw[:w * h * 2], '<u2').reshape(h, w)
            rects.append((kind, x, y, w, h, t['bpp'], source))
    for (k, f), (x, y) in PARTICLE_CLUTS.get(stage, []):
        t = file_tims(src.files[k][f])[0]
        raw = t['clut'][4]
        w = t['clut'][2]
        v[y, x:x + w] = np.frombuffer(raw[:2 * w], '<u2')
        rects.append(('clut', x, y, w, 1, 4, ('particles', k, f)))
    if stage == NO_ARCHIVE:
        for x, y, words in stage14_cluts(src):
            v[y, x:x + 16] = words
            rects.append(('clut', x, y, 16, 1, 4, ('program', STAGE14_CLUTS)))
    return v, rects


# ---------------------------------------------------------------------------
# Far background (0x8011C310 set-up, 0x8011C7CC per frame, main OT rank 1023):
# scene.farbg_commands' algorithm; the rules T3 ties to its stage numbers are
# fields here, so the pack carries them.
# ---------------------------------------------------------------------------
FARBG, FARBG_PITCH, FARBG_COLOURS = 0x8001A2B8, 0x8001A45C, 0x8001A47C
STORM_STAGE, STORM_SKIES = 4, range(15, 21)      # entries 15..20: stage 4's lit skies


@dataclass
class TttFarBg:
    """scene.FarBg's fields plus TTT's rules: mode 0 cells, 1 gradient (stage
    3: G4 from `gradient` to black over 0x60 lines, then the bottom band), 2
    plain (stages 6, 14: the top colour on the whole screen); clamp_top: y
    kept <= 0 (stages 0, 1, 5, 11, 12); min_y: lowest y (stage 11: -0x60 in
    low resolution); cell uv: u = (d * 32) & 0xFF, v = (d & 0x38) * 4."""
    stage: int
    cols: int
    rows: int
    ring: int
    desc: list
    cluts: list
    kinds: list
    yoff: int
    degrees: int
    pitch: int
    cell_rgb: tuple
    top_rgb: tuple
    top_on: int
    bottom_rgb: tuple
    bottom_on: int
    mode: int = 0
    clamp_top: bool = False
    min_y: int | None = None
    gradient: tuple = (0x1F, 0x21, 0x70)

    def tpage(self, d):
        """0x8011C7CC: the T3 page bits of a cell word (GRAPH_TYPE 4)."""
        return (d >> 4 & 0x100) >> 4 | (d >> 8 & 0xF) | (d >> 4 & 0x200) << 2

    @staticmethod
    def uv(d):
        return (d * 32) & 0xFF, ((d & 0x38) * 4) & 0xFF


def farbg_entry(src, entry):
    """(columns, rows, desc pointer, CLUT pointer, kinds pointer, y offset, degrees) of 0x8001A2B8[entry]."""
    return struct.unpack('<hhIIIhH', src.bytes_at(FARBG + 20 * entry, 20))


def parse_farbg(src, stage, hires=False, entry=None):
    """TttFarBg of a stage; entry (15..20 for stage 4) takes the textures and
    CLUTs of a storm sky instead (0x8011D210 swaps those two pointers only)."""
    import scene
    cols, rows, p_desc, p_clut, p_kind, yoff, degrees = farbg_entry(src, stage)
    if entry is not None:
        _, _, p_desc, p_clut, _, _, _ = farbg_entry(src, entry)
    ring = scene.tdiv(0x2D000, degrees) >> 6
    pitch = src.word(FARBG_PITCH + 2 * stage, 1, 'h')
    if not hires:
        yoff, pitch = yoff >> 1, pitch >> 1
    c = src.bytes_at(FARBG_COLOURS + 12 * stage, 12)
    n = rows * cols

    def table(p):
        if not p:
            return [[0] * cols for _ in range(rows)]
        v = src.word(p, n, 'H')
        v = v if isinstance(v, tuple) else (v,)
        return [list(v[r * cols:(r + 1) * cols]) for r in range(rows)]
    kinds = src.bytes_at(p_kind, rows * ring) if p_kind else bytes(rows * ring)
    return TttFarBg(stage, cols, rows, ring, table(p_desc), table(p_clut),
                    [list(kinds[r * ring:(r + 1) * ring]) for r in range(rows)],
                    yoff, degrees, pitch, tuple(c[0:3]), tuple(c[4:7]), c[7], tuple(c[8:11]), c[11],
                    mode=1 if stage == 3 else 2 if stage in (6, 14) else 0,
                    clamp_top=stage in (0, 1, 5, 11, 12),
                    min_y=(-0xC0 if hires else -0x60) if stage == 11 else None)


def farbg_commands(fb, yaw, pitch, hires=False, black=False):
    """0x8011C7CC for camera yaw (minus the fight axis of the previous frame)
    and pitch, in drawing order (rank 1023). black: True Ogre (0x80243790),
    one black TILE."""
    import scene
    H = 0xF0 << int(hires)
    if black:
        return [dict(kind='tile', code=0x60, xy=[(0, 0)], w=0x200, h=H, rgb=[(0, 0, 0)])]
    if fb.mode == 2:
        return [dict(kind='tile', code=0x60, xy=[(0, 0)], w=0x200, h=H, rgb=[fb.top_rgb])]
    linked = []
    a = scene.tdiv(((-yaw) & 0xFFF) << 9, scene.tdiv(fb.degrees << 12, 360))
    scroll = scene.tmod(a, fb.cols << 6)
    col0, kind0 = scene.tdiv(scroll, 64), scene.tdiv(scene.tmod(a, fb.ring << 6), 64)
    y = scene.tdiv(-scene.s12(pitch) * fb.pitch, 256) + fb.yoff
    if fb.mode == 1:
        y = min(y, 0)
        y2 = y + (0xC0 if hires else 0x60)
        g = fb.gradient
        linked.append(dict(kind='g4', code=0x38, xy=[(0, y), (0x200, y), (0, y2), (0x200, y2)],
                           rgb=[g, g, (0, 0, 0), (0, 0, 0)]))
        linked.append(dict(kind='tile', code=0x60, xy=[(0, y2)], w=0x200, h=H * 75 // 100 - y2, rgb=[fb.bottom_rgb]))
        return linked[::-1]
    if fb.clamp_top and y > 0:
        y = 0
    if fb.min_y is not None:
        y = max(y, fb.min_y)
    if y > 0 and fb.top_on:
        linked.append(dict(kind='tile', code=0x60, xy=[(0, 0)], w=0x200, h=y, rgb=[fb.top_rgb]))
    step = 0x40 if hires else 0x20
    for r in range(fb.rows):
        x = scene.tdiv(scroll, 64) * 64 - scroll
        for c in range(9):
            if not (y < -0x40 or y > H):
                kind = fb.kinds[r][scene.tmod(kind0 + c, fb.ring)]
                k = scene.tmod(col0 + c, fb.cols)
                if kind == 0x31:
                    d = fb.desc[r][k]
                    tp, (u, v) = fb.tpage(d), fb.uv(d)
                    clut = fb.cluts[r][k]
                    flip = fb.stage == 5 and r == 3
                    if hires and not flip:
                        linked.append(dict(kind='sprite', code=0x64, xy=[(x, y)], w=0x40, h=0x40, uv=[(u, v)], clut=clut,
                                           rgb=[(0x80, 0x80, 0x80)]))
                        linked.append(dict(kind='tpage', code=0xE1, value=tp))
                    else:
                        h_ = 0x40 if hires else step
                        v0, v1 = (v + 0x3F, v) if flip else (v, v + 0x3F)
                        linked.append(dict(kind='ft4', code=0x2C, xy=[(x, y), (x + 0x40, y), (x, y + h_), (x + 0x40, y + h_)],
                                           uv=[(u, v0), (u + 0x3F, v0), (u, v1), (u + 0x3F, v1)], clut=clut, tpage=tp,
                                           rgb=[(0x80, 0x80, 0x80)]))
                elif kind == 0x74:
                    linked.append(dict(kind='tile', code=0x60, xy=[(x, y)], w=0x40, h=step, rgb=[fb.cell_rgb]))
                elif kind == 0x64:
                    linked.append(dict(kind='tile', code=0x60, xy=[(x, y)], w=0x40, h=step, rgb=[fb.bottom_rgb]))
            x += 0x40
        y += step
    if y < H and fb.bottom_on:
        y = max(y, 0)
        linked.append(dict(kind='tile', code=0x60, xy=[(0, y)], w=0x200, h=H * 75 // 100 - y, rgb=[fb.bottom_rgb]))
    return linked[::-1]


# ---------------------------------------------------------------------------
# Floor (set-up 0x8011C204 / 0x8011D454 at the load, 0x8011FCC4 ->
# 0x8011E10C every frame through the pointer 0x80243758, after the world
# matrix 0x80118BA4): a generated grid of cols x rows cells, one GT4 each (4
# GT3 around the middle of the diagonal 1-2 for at most 11 cells near the
# camera), centred on the fighters' middle moved forward along the camera
# yaw, its texture map wrapping every cols / rows cells; T3's three lights.
# ---------------------------------------------------------------------------
FLOOR_STAGES = 0x8001A244        # 8 bytes per stage: u32 block (0xEA bytes), u32 n + 1
FLOOR_CELLS = 0x80195140         # 12 bytes per cell kind: w0, w1, 0
FLOOR_FOG = 0x8001A530           # 1024 bytes, kind 0 (0x802E5328 = its ramp)
# Corner uv offsets of a cell (w0: bits 30-31 rotation, 25 mirror, 26 flip),
# packet vertices 0..3, as the long switch of 0x8011D454 writes them.
FLOOR_CORNERS = {
    (0, 0, 0): (0x3F00, 0x3F3F, 0, 0x3F), (0, 0, 1): (0, 0x3F, 0x3F00, 0x3F3F),
    (0, 1, 0): (0x3F3F, 0x3F00, 0x3F, 0), (0, 1, 1): (0x3F, 0, 0x3F3F, 0x3F00),
    (1, 0, 0): (0x3F3F, 0x3F, 0x3F00, 0), (1, 0, 1): (0x3F00, 0, 0x3F3F, 0x3F),
    (1, 1, 0): (0x3F, 0x3F3F, 0, 0x3F00), (1, 1, 1): (0, 0x3F00, 0x3F, 0x3F3F),
    (2, 0, 0): (0x3F, 0, 0x3F3F, 0x3F00), (2, 0, 1): (0x3F3F, 0x3F00, 0x3F, 0),
    (2, 1, 0): (0, 0x3F, 0x3F00, 0x3F3F), (2, 1, 1): (0x3F00, 0x3F3F, 0, 0x3F),
    (3, 0, 0): (0, 0x3F00, 0x3F, 0x3F3F), (3, 0, 1): (0x3F, 0x3F3F, 0, 0x3F00),
    (3, 1, 0): (0x3F00, 0, 0x3F3F, 0x3F), (3, 1, 1): (0x3F3F, 0x3F, 0x3F00, 0),
}


@dataclass
class TttFloor:
    stage: int
    kind: int          # 0 fog by depth, 1 a light under each fighter, 2 one light at their middle
    fog: int
    cols: int          # grid cells (14 or 15), the texture map wraps every cols / rows
    rows: int
    size: int          # world units per cell
    cells: list        # 15 x 15 (w0, w1) of the texture map, row-major
    unique: list       # 15 x 15: rank of the cell's w0 & 0x39FFFFFF among the distinct ones
    verts: list        # (cols + 1) x (rows + 1) (x, z), row z then x
    quads: list        # rows x cols u32: four vertex indices (bytes)
    ramp: list         # 1024 kind-0 shades (0x802E5328)
    half: bool = False  # stage 8: kind 2 light halved

    def corners(self, r, c):
        """((u, v) x 4 packet vertices, CLUT, page) of map cell (r, c): 0x8011D454's records."""
        w0, w1 = self.cells[r][c]
        o = FLOOR_CORNERS[(w0 >> 30, w0 >> 25 & 1, w0 >> 26 & 1)]
        base = w0 & 0xFFFF
        uvs = [((base + k) & 0xFF, ((base + k) >> 8) & 0xFF) for k in o]
        return uvs, (w1 >> 16) & 0xFFFF, (w0 >> 16) & 0x39FF

    def middle(self, r, c):
        """0x802ED4D8: uv halfway between corners 1 and 2."""
        (u1, v1), (u2, v2) = self.corners(r, c)[0][1:3]
        return (u1 + u2) >> 1, (v1 + v2) >> 1


def grid(cols, rows, size):
    """0x8017A424: vertices (x, z) and quads (i0 | i1 << 8 | i2 << 16 | i3 << 24)."""
    quads = []
    for r in range(rows):
        for c in range(cols):
            a, b = r * (cols + 1) + c, (r + 1) * (cols + 1) + c
            quads.append(a | (a + 1) << 8 | b << 16 | (b + 1) << 24)
    hz = (rows if rows % 2 == 0 else rows + 1) >> 1
    hx = (cols if cols % 2 == 0 else cols + 1) >> 1
    verts = [((c - hx) * size, (r - hz) * size) for r in range(rows + 1) for c in range(cols + 1)]
    return verts, quads


def parse_floor(src, stage, true_ogre=False):
    """0x8011C204 / 0x8011D454: None when the stage has no floor."""
    p = src.word(FLOOR_STAGES + 8 * (stage % 15))
    kind = src.word(p + 0xE6, 1, 'h')
    if kind == 0 and true_ogre:
        kind = 2
    if not 0 <= kind <= 2:
        return None
    cols, rows = src.bytes_at(p + 0xE1, 2)
    size, _, fog = src.word(p + 0xE4, 3, 'h')
    tex = src.bytes_at(p, 225)
    cells = [[src.word(FLOOR_CELLS + 12 * tex[15 * r + c], 2) for c in range(15)] for r in range(15)]
    seen, unique = [], []
    for r in range(15):
        row = []
        for c in range(15):
            v = cells[r][c][0] & 0x39FFFFFF
            if v not in seen:
                seen.append(v)
            row.append(seen.index(v))
        unique.append(row)
    if len(seen) > 40:
        raise ValueError(f'stage {stage}: {len(seen)} distinct floor cells, the game gives up over 40')
    ramp = []
    for f in src.bytes_at(FLOOR_FOG, 1024):
        v = f * fog
        v = ((v + 0x7F if v < 0 else v) >> 7) + 0x80
        ramp.append(min(max(v, 0), 0xFE))
    verts, quads = grid(cols, rows, size)
    return TttFloor(stage, kind, fog, cols, rows, size, cells, unique, verts, quads, ramp, half=stage == 8)


@dataclass
class TttView:
    """What the floor needs from the frame: the world matrix (0x803A8280,
    0x80118BA4 from the camera), the camera struct 0x802E0790 (pitch, yaw,
    position), the fighters' x, z (+0x53C, +0x544) the floor gets, the ones
    its lights use (the 0x802E6328 copies in state 0x141C), the GTE screen,
    0x80242F08 (the near limit with size / 3)."""
    rot: tuple
    trans: tuple
    pitch: int
    yaw: int
    cam: tuple
    p1: tuple
    p2: tuple
    l1: tuple
    l2: tuple
    h: int = 600
    ofx: int = 256 << 16
    ofy: int = 120 << 16
    hires: bool = False
    third: bool = False


SQRT_TABLE = 0x8023CCC8          # SquareRoot0 (0x8018F38C), 192 s16


def sqrt0(src):
    """SquareRoot0 of TTT's program, as a function."""
    import scene
    table = src.word(SQRT_TABLE, 192, 'h')
    return lambda a: scene.sqrt0(None, a, table)


def i32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >> 31 else v


STAGE11_LIGHTS, STAGE11_COUNTER = 0x802E6348, 0x802437A8   # u32 x 2 per frame (CLUT << 16), u32 0..0xEF


def stage11_lights(table, counter):
    """0x8011E10C, stage 11: the CLUT of map cell (row, column) for the lights
    of rows 0 and 2 (mod 4): table = the 480 u32 0x8011F1B4 fills (CLUT << 16,
    two per frame), counter = u32 0x802437A8 after this frame's increment."""
    def clut(r, c):
        second = (c & 3) == 0 if r % 4 == 0 else c % 4 == 2
        return table[2 * counter + second] >> 16
    return clut


def floor_commands(floor, view, sine, sqrt0, stage11_clut=None, screen=None):
    """0x8011FCC4 / 0x8011E10C: [(rank, command)] in link order. Commands
    carry 'packet' = (pool, index): pool 0 the GT4 (0x802E6AC8 + 0x2DB4 per
    buffer, one per grid cell), pool 1 the GT3 (0x802EC630 + 0x6E0 per
    buffer). sine: the 0x1400 s16 of 0x8001B194; sqrt0: SquareRoot0;
    stage11_clut(map row, column): the CLUT of the stage 11 lights;
    screen(xy): the cell's screen test (default TTT's: a vertex above the
    bottom, one across the 512 columns; the PS1 port passes its own)."""
    import numpy as np
    import gte
    import scene
    if sine[(view.pitch + 0xEF) & 0xFFF] <= 0:
        return []
    t = floor.size
    pos = [(view.p1[0] + view.p2[0]) >> 1, (view.p1[1] + view.p2[1]) >> 1]
    a = t + scene.tdiv(t * (abs(sine[view.pitch & 0xFFF]) << 2), 4096)
    b = view.yaw & 0xFFF
    pos[0] -= scene.tdiv(sine[b] * a, 4096)
    pos[1] += scene.tdiv(sine[b + 0x400] * a, 4096)
    x, z = pos[0] + (t >> 1), pos[1] + (t >> 1)
    ix = scene.tdiv(x, t) - (x < 0)
    iz = scene.tdiv(z, t) - (z < 0)
    col = scene.tmod(ix, floor.cols)
    col += floor.cols if col < 0 else 0
    s0 = scene.tmod(iz, floor.rows)
    s0 += floor.rows if s0 < 0 else 0
    s0 = floor.rows - (s0 + 1)
    cx, cz = ix * t, iz * t
    rot = np.array(view.rot, np.int64)
    off = (cx, 0, cz)
    tr = [(sum(int(rot[i, k]) * off[k] for k in range(3)) >> 12) + view.trans[i] for i in range(3)]
    cam = gte.Camera(rot, np.array(tr, np.int64), view.ofx, view.ofy, view.h)
    sx, sy, sz = gte.rtps(cam, np.array([(vx, 0, vz) for vx, vz in floor.verts], np.int64))
    pa, pb = view.l1, view.l2
    lum = []
    if floor.kind == 0:
        dx = view.cam[0] - ((pa[0] + pb[0]) >> 1)
        dz = view.cam[2] - ((pa[1] + pb[1]) >> 1)
        d = sqrt0(i32(dx * dx + dz * dz))
        for i in range(len(floor.verts)):
            v = max(int(sz[i]) - d, t)
            v = (v * 0x1A36) >> 16
            lum.append(floor.ramp[min(v, 0x3FF)])
    elif floor.kind == 2:
        mx, mz = (pa[0] + pb[0]) >> 1, (pa[1] + pb[1]) >> 1
        for vx, vz in floor.verts:
            d = i32((mx - (cx + vx)) ** 2 + (mz - (cz + vz)) ** 2) or 1
            v = min(scene.tdiv(0x7A120000, d), 0xC0)
            lum.append(v >> 1 if floor.half else v)
    else:
        ax, az, bx, bz = pa[0] - cx, pa[1] - cz, pb[0] - cx, pb[1] - cz
        for vx, vz in floor.verts:
            d1 = i32((ax - vx) ** 2 + (az - vz) ** 2) or 1
            d2 = i32((bx - vx) ** 2 + (bz - vz) ** 2) or 1
            lum.append(min(scene.tdiv(0xF200000, d1) + scene.tdiv(0xF200000, d2), 0xFE))
    fp = 0xF0 << int(view.hires)
    k = (view.pitch + 0xEF) & 0xFFF
    s1 = scene.tdiv(sine[k] << 12, sine[k + 0x400])
    h = scene.tdiv(t, 3) if view.third else t
    v = scene.tdiv(scene.tdiv(h, 2) * sine[k + 0x400], 4096)
    v = scene.tdiv(v * (0x2000 - sine[(view.yaw & 0xFFF) + 0x400]), 4096)
    limit = scene.tdiv(abs(view.cam[1]) << 12, s1) + v
    out, cnt, quad = [], 0, 0
    for _ in range(floor.rows):
        tc = col
        for _ in range(floor.cols):
            w = floor.quads[quad]
            vi = [w >> (8 * q) & 0xFF for q in range(4)]
            packet = quad
            quad += 1
            if all(sz[i] for i in vi):
                xy = [(int(sx[i]), int(sy[i])) for i in vi]
                if (screen(xy) if screen else any(y < fp for _, y in xy) and any((x & 0xFFFF) < 0x200 for x, _ in xy)):
                    uvs, clut, tpage = floor.corners(s0, tc)
                    if stage11_clut is not None and s0 % 4 in (0, 2):
                        clut = stage11_clut(s0, tc)
                    rgb = [(lum[i],) * 3 for i in vi]
                    rank = 1021 - floor.unique[s0][tc]
                    if sz[vi[0]] < limit and cnt < 11:
                        cnt += 1
                        mid = ((xy[1][0] + xy[2][0]) >> 1, (xy[1][1] + xy[2][1]) >> 1)
                        mc = (rgb[1][0] + rgb[2][0]) >> 1
                        for f, (p, q) in enumerate(((0, 1), (1, 3), (3, 2), (2, 0))):
                            out.append((rank, dict(kind='gt3', code=0x34, xy=[mid, xy[p], xy[q]],
                                                   rgb=[(mc,) * 3, rgb[p], rgb[q]],
                                                   uv=[floor.middle(s0, tc), uvs[p], uvs[q]], clut=clut, tpage=tpage,
                                                   packet=(1, 4 * (cnt - 1) + f))))
                    else:
                        out.append((rank, dict(kind='gt4', code=0x3C, xy=xy, rgb=rgb, uv=uvs, clut=clut,
                                               tpage=tpage, packet=(0, packet))))
            tc = 0 if tc + 1 >= floor.cols else tc + 1
        s0 = floor.rows - 1 if s0 - 1 < 0 else s0 - 1
    return out


# ---------------------------------------------------------------------------
# Objects (0x8015FEF8 at the load: archive 22 for stage 3, one model; archive
# 21 for stage 11, three models; file 0 = TIMs, files 1.. = TMD; drawn by
# 0x801600C0 after the tiles: stage 3 always, stage 11 only in the rankings
# (main state 7), never with True Ogre). A model is drawn only when its
# vertex 0 is inside the frame 0x8019C9CC (x -256..768, y >= -180); then, as
# T3, a primitive kept by NCLIP (FT3 / G3 on vertices 0, 1, 2, the quads on
# 0, 1, 3; here a nop sits between mfc2 and lw, so FT4 0x2C000709 is culled
# too, unlike the tiles) goes
# to slot AVSZ of a private OT of 128 (0x80353120 + 0x200 per buffer) linked
# at main rank 1022; slot 0 is lost by that link. Packets prepared once in
# 0x8034FBC0 + 0x1A90 per buffer.
# ---------------------------------------------------------------------------
OBJECTS = {3: (22, 1), 11: (21, 3)}
OBJECT_FRAME = 0x8019C9CC        # 4 words, as 0x80340130 for the tiles


def parse_objects(src, stage):
    if stage not in OBJECTS:
        return []
    archive, n = OBJECTS[stage]
    return [decode.parse_geometry(f).tiles[0] for f in src.files[archive][1:n + 1]]


def object_layout(stage):
    """[(model, main OT rank, private OT size)] in drawing call order
    (0x80160210 for stage 3; 0x80160370 for stage 11: fuselage, rotor)."""
    if stage == 3:
        return [(0, 1022, 128)]
    if stage == 11:
        return [(0, 1022, 128), (1, 1022, 128)]
    return []


def object_frame(src):
    return [i32(w) for w in src.word(OBJECT_FRAME, 3)]


def object_commands(stage, models, cams, frame, framed=None):
    """{main OT rank: [commands in drawing order]}; cams[i]: gte.Camera of
    model i. Commands carry 'packet': word index in the object pool.
    framed(x, y): the frame test of vertex 0 (default TTT's, the frame
    words; the PS1 port passes its own)."""
    import numpy as np
    import gte
    import scene
    base, cursor = [], 0
    for m in models:
        base.append(cursor)
        cursor += sum(scene.decode_words(p) for p in m.prims)
    ots = {}
    for i, rank, size in object_layout(stage):
        if i not in cams:
            continue
        m = models[i]
        sx, sy, sz = gte.rtps(cams[i], np.array(m.verts))
        ot = ots.setdefault(rank, [[] for _ in range(size)])
        w0 = i32((int(sy[0]) & 0xFFFF) << 16 | (int(sx[0]) & 0xFFFF))
        lo = i32((int(sx[0]) & 0xFFFF) << 16)
        if framed is not None:
            if not framed(int(sx[0]), int(sy[0])):
                continue
        elif not (frame[2] - w0 <= 0 and frame[0] - lo <= 0 and frame[1] - lo >= 0):
            continue
        z5 = sz >> 5
        word = base[i]
        for prim in m.prims:
            v = prim.idx
            c = (0, 1, 2) if len(v) == 3 else (0, 1, 3)
            if gte.nclip(*[int(q) for k in c for q in (sx[v[k]], sy[v[k]])]) > 0:
                cmd = scene.prim_command(prim, [(int(sx[j]), int(sy[j])) for j in v])
                cmd['packet'] = word
                zsf = scene.ZSF4 if len(v) == 4 else scene.ZSF3
                slot = min((sum(int(z5[j]) for j in v) * zsf) >> 12, 0xFFFF)
                if slot >= size:
                    raise ValueError(f'object primitive at OT slot {slot}: outside the game\'s table')
                if slot:
                    ot[slot].append(cmd)
            word += scene.decode_words(prim)
    out = {}
    for rank, ot in ots.items():
        seq = []
        for slot in range(len(ot) - 1, -1, -1):
            seq += list(reversed(ot[slot]))
        out[rank] = seq
    return out


# ---------------------------------------------------------------------------
# Animated textures (0x8015EB70, every frame of a fight and of the rankings;
# counters u16 0x80243A98 / 0x80243A9A set to 0xFFFF by 0x8015F638 at each
# round). The copies are MoveImage requests (0x8012F708) the game runs at the
# end of the frame. Stage 3: three 16 x 64 textures every 4 frames from 63
# places (0x80028378); stage 6: a 8 x 64 on even frames (0x800285F8), a
# 16 x 32 on odd ones (0x80028478) and, when 0x800286B8 says so, two 16 x 64
# and a CLUT (0x80028678, 0x80028718); stage 7: a state machine drawing
# rand() (0x8015F20C..0x8015F5AC, the 7 frame sequences 0x80028758..) that
# copies one of 53 textures and its CLUT (0x80028834); stage 14: one CLUT of
# 32 every frame (0x800289DC). Stage 7's runs only when 0x8015F6A4 is false
# (no True Ogre, no Panda: models 0x17 / 0x5D, see STAGE_EFFECTS).
# ---------------------------------------------------------------------------
ANIM_STAGE3, ANIM_STAGE6_EVEN, ANIM_STAGE6_ODD = 0x80028378, 0x800285F8, 0x80028478
ANIM_STAGE6_MORE, ANIM_STAGE6_SWITCH, ANIM_STAGE6_CLUT = 0x80028678, 0x800286B8, 0x80028718
ANIM_STAGE7_SEQUENCES = (0x80028758, 0x8002876C, 0x80028788, 0x800287A4, 0x800287D8, 0x8002880C, 0x80028820)
ANIM_STAGE7_FRAMES, ANIM_STAGE7_NFRAMES = 0x80028834, 53
ANIM_STAGE14 = 0x800289DC
ANIM_STAGES = (3, 6, 7, 14)


class TttAnim:
    """0x8015EB70 for one stage: step() = one frame, returns the copies
    [(source x, y, w, h, destination x, y)] queued that frame. rand: the
    random numbers of stage 7 (the game's rand(), 0..0x7FFF)."""

    def __init__(self, src, stage, rand=None, active=True):
        self.stage, self.rand = stage, rand
        w = lambda a, n, f='H': list(src.word(a, n, f))
        if stage == 3:
            self.places = [tuple(w(ANIM_STAGE3 + 4 * i, 2)) for i in range(64)]
        elif stage == 6:
            self.even = [tuple(w(ANIM_STAGE6_EVEN + 4 * i, 2)) for i in range(32)]
            self.odd = [tuple(w(ANIM_STAGE6_ODD + 4 * i, 2)) for i in range(96)]
            self.switch = src.bytes_at(ANIM_STAGE6_SWITCH, 96)
            n = max(self.switch)
            self.more = [tuple(w(ANIM_STAGE6_MORE + 8 * k, 4)) for k in range(n)]
            self.cluts = [tuple(w(ANIM_STAGE6_CLUT + 8 * k, 2)) for k in range(n)]
        elif stage == 7:
            self.sequences = [w(a, 26, 'h') for a in ANIM_STAGE7_SEQUENCES]
            self.frames = [tuple(w(ANIM_STAGE7_FRAMES + 8 * i, 4)) for i in range(ANIM_STAGE7_NFRAMES)]
        elif stage == 14:
            self.cycle = src.bytes_at(ANIM_STAGE14, 64)
        self.active = active
        self.reset()

    def reset(self):
        """0x8015F638 (each round)."""
        self.a98 = self.a9a = 0xFFFF
        self.state, self.count, self.tick, self.frame = 0, 0, 0, -1

    def seq(self, k, i):
        s = self.sequences[k]
        return s[i] if i < len(s) else -1

    def step(self):
        old = self.a9a
        self.a98 = (self.a98 + 1) & 0xFFFF
        self.a9a = (self.a9a + 1) & 0xFFFF
        s16 = lambda v: ((v & 0xFFFF) ^ 0x8000) - 0x8000
        out = []
        if self.stage == 3:
            if self.a98 & 3:
                return out
            i = self.a98 >> 2 & 0x3F
            if i > 0x3E:
                i, self.a98 = 0, 0
            k = s16(self.a98) >> 2
            for j, (dx, dy) in zip((i, (k + 0x15) & 0x3F, (k + 0x2A) & 0x3F), ((0x10, 0x280), (0x10, 0x2C0), (0x50, 0x300))):
                out.append(self.places[j] + (16, 64, dx, dy))
        elif self.stage == 6:
            if s16(self.a98) >> 1 > 0x5F:
                self.a98 = 0
            if not self.a98 & 1:
                out.append(self.even[((old + 1) * 2 & 0x7C) >> 2] + (8, 64, 0x58, 0x2C0))
            else:
                i = s16(self.a98) >> 1
                out.append(self.odd[i] + (16, 32, 0x90, 0x230))
                b = self.switch[i]
                if b:
                    m = self.more[b - 1]
                    out.append(m[0:2] + (16, 64, 0, 0x240))
                    out.append(m[2:4] + (16, 64, 0, 0x200))
                    out.append(self.cluts[b - 1] + (16, 1, 0x290, 0x60))
        elif self.stage == 14:
            b = self.cycle[self.a98 >> 2 & 0x3F]
            out.append(((b & 0xF) * 16 + 0x200, ((b & 0x10) >> 4) + 0xE0, 16, 1, 0x200, 0x60))
        elif self.stage == 7 and self.active:
            self.stage7()
            if self.frame != -1:
                x, y, cx, cy = self.frames[self.frame]
                out.append((x, y, 16, 64, 0x20, 0x3C0))
                out.append((cx, cy, 16, 1, 0x2C0, 0x62))
                self.frame = -1
        return out

    def stage7(self):
        """0x8015EB70's switch on u16 0x80243A9E (state 0 falls into 1)."""
        r = self.rand
        st = self.state

        def play(k, mask):
            self.tick = (self.tick + 1) & 0xFFFF
            if self.tick & mask:
                return False
            self.frame = self.seq(k, self.tick >> (2 if mask == 3 else 3))
            return self.frame == -1
        if st == 0:
            self.count = r() & 0x1F
            self.state, self.frame = 1, self.seq(0, 0)
        if st in (0, 1):
            self.count = (self.count - 1) & 0xFFFF
            if self.count and not self.count & 0x8000:
                return
            k = r() % 3
            if k == 1:
                self.state, self.frame = 3, self.seq(1, 0)
            elif k == 0:
                self.count, self.state, self.frame = (r() & 3) + 5, 2, self.seq(0, 0)
            else:
                self.state, self.frame = 6, self.seq(5, 0)
            self.tick = 0
        elif st == 2:
            if play(0, 3):
                self.count = (self.count - 1) & 0xFFFF
                if not self.count or self.count & 0x8000:
                    self.count, self.state, self.frame = r() & 0x1F, 1, self.seq(0, 0)
                else:
                    self.tick, self.frame = 0, self.seq(0, 0)
        elif st == 3:
            if play(1, 7):
                self.count, self.state, self.frame = (r() & 0x7F) + 0x78, 4, self.seq(2, 0)
        elif st == 4:
            self.count = (self.count - 1) & 0xFFFF
            if not self.count or self.count & 0x8000:
                self.tick, self.state, self.frame = 0, 5, self.seq(2, 0)
        elif st == 5:
            if play(2, 7):
                self.count, self.tick, self.state, self.frame = (r() & 3) + 5, 0, 2, self.seq(0, 0)
        elif st == 6:
            if play(5, 7):
                self.count, self.tick, self.state, self.frame = (r() & 3) + 1, 0, 7, self.seq(3, 0)
        elif st in (7, 8):
            k = 3 if st == 7 else 4
            if play(k, 7):
                self.count = (self.count - 1) & 0xFFFF
                if not self.count or self.count & 0x8000:
                    if r() & 3 == 0:
                        self.count = (r() & 3) + 1
                        self.state, self.frame = (8, self.seq(4, 0)) if st == 7 else (7, self.seq(3, 0))
                    else:
                        self.state, self.frame = 9, self.seq(6, 0)
                    self.tick = 0
                else:
                    self.tick, self.frame = 0, self.seq(k, 0)
        elif st == 9:
            if play(6, 7):
                self.count, self.tick, self.state, self.frame = (r() & 3) + 5, 0, 2, self.seq(0, 0)


def apply_copies(v, copies):
    """Run MoveImage requests on a VRAM array (each reads before it writes)."""
    for sx, sy, w, h, dx, dy in copies:
        v[dy:dy + h, dx:dx + w] = v[sy:sy + h, sx:sx + w].copy()


# ---------------------------------------------------------------------------
# Stage 4's storm (0x8015C2A8 every frame at the head of the tiles, stage 4
# only; 0x8015BFA0 starts a flash; 0x8015C454 at the stage load). Program
# data: thresholds, flash sequences, light colours; the lit skies are far
# background entries 15..20 (textures: archive 5 file 6).
# ---------------------------------------------------------------------------
STORM_THRESHOLDS = 0x80023818    # s16 every 4 bytes, 5 counters
STORM_SEQUENCES = (0x80023830, 0x80023854, 0x80023878, 0x8002389C, 0x800238A4, 0x800238AC)
STORM_COLOURS = 0x80023800       # 4 bytes per flash type: r, g, b of the light on the fighters (0x8010CE8C)
# 0x8015BFA0's switch: (sound, voice) per flash type 0..4 (types 0-2 skip the
# sound when voice 0x1C is busy, 0x8012568C); type 4 runs into type 5.
STORM_SOUNDS = ((0x121, 0x1C), (0x123, 0x1C), (0x124, 0x1C), (0x122, 0x1D), (0x122, 0x1D))
STORM_FORCED = ((60, 4), (130, 3))   # idle frame -> counter forced to 0x7FFF
STORM_STATE = 0x80243A68         # s16 index in the sequence (-1 idle), s16 type, u32 idle frames
STORM_COUNTERS = 0x80347700      # 5 s16
STORM_POINT = 0x803476F0         # the light's x, y, z


@dataclass
class Storm:
    thresholds: list   # 5 s16
    sequences: list    # 6 lists of s8: 1 lit (sky 15 + type, light), 0 normal sky (4), -1 end
    colours: list      # 6 (r, g, b)
    skies: list        # 6 (desc rows, CLUT rows) of entries 15..20


def parse_storm(src):
    seqs = []
    for a in STORM_SEQUENCES:
        s = []
        for b in src.bytes_at(a, 64):
            s.append(b - 256 if b > 127 else b)
            if s[-1] == -1:
                break
        seqs.append(s)
    skies = []
    for e in STORM_SKIES:
        fb = parse_farbg(src, STORM_STAGE, entry=e)
        skies.append((fb.desc, fb.cluts))
    return Storm([src.word(STORM_THRESHOLDS + 4 * k, 1, 'h') for k in range(5)], seqs,
                 [tuple(src.bytes_at(STORM_COLOURS + 4 * k, 3)) for k in range(6)], skies)


class TttStorm:
    """0x8015C454 / 0x8015C2A8 / 0x8015BFA0 without the light's position and
    the sound mixer: step() -> (far background entry, flash type lit or
    None, (sound, voice) started or None). rand: the game's rand()."""

    def __init__(self, storm, rand):
        self.s, self.rand = storm, rand
        self.index, self.type, self.frames = -1, 0, 0
        self.counters = [rand() & 0x3FF, rand() & 0x3FF, rand() & 0x3FF, rand() & 0x7FF, rand() & 0x7FF]

    def start(self):
        """0x8015BFA0: True when a flash starts this frame."""
        for k in range(5):
            self.counters[k] = ((self.counters[k] + (self.rand() & 0xF) + 0x8000) & 0xFFFF) - 0x8000
        self.frames += 1
        for frame, k in STORM_FORCED:
            if self.frames == frame:
                self.counters[k] = 0x7FFF
                break
        k = next((k for k in range(5) if self.counters[k] > self.s.thresholds[k]), None)
        if k is None:
            return False, None
        self.rand()                                  # the light's angle
        self.rand()                                  # its height
        self.type, self.counters[k] = k, 0
        if k > 2:
            self.counters = [c - (c >> 2) for c in self.counters]
        return True, STORM_SOUNDS[k]

    def step(self):
        sound = None
        if self.index == -1:
            started, sound = self.start()
            if not started:
                return None, None, None             # 0x8015C2A8 returns: the sky stays
        self.index += 1
        seq = self.s.sequences[self.type]
        if self.type == 4 and seq[self.index] == -1:
            self.type, self.index = 5, 0
            seq = self.s.sequences[5]
        v = seq[self.index]
        if v == 1:
            return STORM_SKIES[0] + self.type, self.type, sound
        if v == -1:
            self.index = -1
        elif v != 0:
            return None, None, sound
        return STORM_STAGE, None, sound


# ---------------------------------------------------------------------------
# Stage 11's floor lights (0x8011F1B4, after the floor set-up): 4 runs of 120
# CLUTs of 16 colours at x 16.., y 480..511 (low half), table 0x802E6348
# (two per frame: [2 i] runs 1-2, [2 i + 1] runs 3-4). All copy the CLUT the
# RECT at 0x80242F9C names (stage 11's (736, 96)); colours 14 and 15 pulse
# in runs 1 and 4, stay (1, 5, 4) in 2 and 3. The pulse uses TTT's libmath
# csqrt / csin (CORDIC, 0x8018F260 / 0x8018EEAC), run as they are on the
# program's bytes by mips.Machine (TTT Stages S4): by hand (isqrt, a sine
# x 4095) 42 words of 7680 were a 5-bit step off the game's.
# ---------------------------------------------------------------------------
STAGE11_SOURCE = (736, 96)
CSQRT, CSIN = 0x8018F260, 0x8018EEAC


def stage11_light_cluts(v, src):
    """[(x, y, 16 words)] of the 480 CLUTs, and the 480 u32 of 0x802E6348,
    as 0x8011F1B4 makes them (src: the Ttt whose csqrt / csin run)."""
    import mips
    import scene
    m = mips.Machine(src.program, BASE)
    memo = {}

    def call(pc, a):
        if (pc, a) not in memo:
            memo[pc, a] = m.call(pc, a)
        return memo[pc, a]
    words_in = [int(w) for w in v[STAGE11_SOURCE[1], STAGE11_SOURCE[0]:STAGE11_SOURCE[0] + 16]]
    s0 = call(CSQRT, 0xB43)
    out, table = [], [0] * 480
    x, y = 0x10, 0x1E0
    for run in range(4):
        for i in range(120):
            p = scene.tdiv(call(CSIN, scene.tdiv(i << 12, 120) - 0x400) + 0x1000, 2)
            words = []
            for k, w in enumerate(words_in):
                r, g, b, stp = w & 31, w >> 5 & 31, w >> 10 & 31, w >> 15
                if stp == 0 and k in (14, 15):
                    if run in (0, 3):
                        s = call(CSQRT, r * r + g * g + b * b)
                        c = [(scene.tdiv((s * p * q) >> 12, s0) + a) & 0xFF for q, a in ((4, 1), (16, 5), (14, 4))]
                        c = [1, 1, 1] if c == [0, 0, 0] else [min(q, 31) for q in c]
                    else:
                        c = [1, 5, 4]
                    w = c[0] | c[1] << 5 | c[2] << 10
                words.append(w)
            out.append((x, y, words))
            table[2 * (i + 120 * (run & 1)) + (run >> 1)] = (y << 6 | x >> 4) << 16
            y += 1
            if y > 0x1FF:
                y, x = 0x1E0, x + 0x10
    return out, table


# ---------------------------------------------------------------------------
# Stage 2's particles (effect type 0xF of the effects engine 0x80155D34): 15
# at the round start (0x80156568(1)), then one every 10 frames while fewer
# than 0x50 effects live; born by 0x80159ED0 in front of the camera (yaw
# drawn in the view's width from 0x801554E8, distance 0xA00 + rand & 0x1FFF,
# at the round start y scaled by rand / 0x8000), falling (rand & 0xF, 0x18,
# -(rand & 0xF)) per frame (0x8015B9C0), freed when y > 0. Each one a
# semi-transparent FT4 facing the camera (quad 0x800235BC, 30 units), uv
# 16 x 16 from 0x800235B8 on page (0x3C0, 0) abr 1, CLUT (0x210, 0xFF),
# colour 0x80; drawn when its vertex 0 has SZ >> 5 >= 0x14, at main OT rank
# SZ(vertex 1) >> 5 (0x80154B34). The texture lies in the effects' common
# file (archive 5 file 0, low half): the decoder moves its 16 x 16 to a free
# place of the high half. Stage 14's veils (types 0x12-0x16, 0x8015671C)
# show only while a fighter's byte +0x3DD is set: TTT Stages S4 decoded it
# (0x80169B6C / 0x80169FF8): 1 when the fighter's team is Unknown twice
# (character 0x21, TTT's boss Unknown fighting alone), 0x802FE23A = 1 and the
# main state is not 5. The veils follow that fighter's body parts 1, 13, 16
# (0x802A6304 + 0x50 * part, 0x8015A31C, 0x8015A584, 0x8015A8E8, 0x8015AE94):
# Unknown's aura, not the stage's (in S2's stage 14 dumps the 10 veil effects
# live, hidden: flag 0x40 clear, +0x3DD 0, a Xiaoyu team fighting).
#
# Drawing (0x80155D34 / 0x80154B34, measured on S2's stage 2 dumps: 236
# particles drawn, 236 packets = particle_ttt): the centre is the camera
# rotation (RotMatrix of the camera's angles, row 1 x 10 >> 4 in low
# resolution) of the position minus the camera's (s16), of the previous
# frame's camera (the effects are drawn before the camera moves); the quad's
# corners are added unrotated (rotation (0, 0, 0), row 1 x 10 >> 4), RTPS.
# ---------------------------------------------------------------------------
PARTICLE_STAGE = 2
PARTICLE_QUAD, PARTICLE_UV = 0x800235BC, 0x800235B8
PARTICLE_PAGE, PARTICLE_CLUT = (0x3C0, 0), (0x210, 0xFF)


@dataclass
class Particles:
    quad: list          # 4 (x, y, z) local corners
    tpage: int          # System 12 page of the moved texture (abr 1, 4 bits)
    uv: tuple           # top-left u, v (16 x 16)
    clut: int           # CLUT word (low half; moved up by the pack)
    image: tuple        # (x, y, w, h, words): the moved texture in the high half
    start: int = 15     # particles at the round start
    every: int = 10     # then one every `every` frames
    most: int = 0x50    # while fewer effects than this live
    near: int = 0x14    # drawn when SZ(vertex 0) >> 5 >= near
    distance: tuple = (0xA00, 0x1FFF)   # base, random mask
    fall: tuple = (0xF, 0x18, 0xF)      # x rand mask, y speed, z rand mask (negated)


def particles(src, used):
    """Stage 2's particle data, its texture moved into a free 4 x 16 words
    of the high half (used: bool (512, 1024), True where the stage has a
    texture; updated)."""
    import numpy as np
    u, v = src.bytes_at(PARTICLE_UV, 2)
    px, py = PARTICLE_PAGE
    sx, sy = px + u // 4, py + v                 # 4-bit texels: 4 per VRAM word
    words = None
    for t in file_tims(src.files[EFFECTS][0]):
        x, y, w, h, raw = t['image']
        if x <= sx and sx + 4 <= x + w and y <= sy and sy + 16 <= y + h:
            img = np.frombuffer(raw[:w * h * 2], '<u2').reshape(h, w)
            words = img[sy - y:sy - y + 16, sx - x:sx - x + 4].copy()
    assert words is not None, 'particle texture not in archive 5 file 0'
    for yy in range(511 - 15, -1, -1):
        for xx in range(1024 - 4, -1, -4):
            if xx // 64 != (xx + 3) // 64 or yy // 256 != (yy + 15) // 256:
                continue
            if not used[yy:yy + 16, xx:xx + 4].any():
                used[yy:yy + 16, xx:xx + 4] = True
                ny = yy + 512
                tpage = get_tpage(0, 1, xx & ~63, ny)
                quad = [src.word(PARTICLE_QUAD + 8 * k, 3, 'h') for k in range(4)]
                return Particles(quad, tpage, ((xx & 63) * 4, ny & 255), get_clut(*PARTICLE_CLUT),
                                 (xx, ny, 4, 16, words))
    raise ValueError('no room for the particle texture in the high half')


class TttParticles:
    """0x80155D34's stage 2 part without the drawing: spawn() at a frame
    (round_start: the 15 of the round start) returns the particles born,
    each (x, y, z, vx, vy, vz) given its birth point; step() moves them
    and frees those below y 0 (0x8015B9C0)."""

    def __init__(self, data, rand):
        self.d, self.rand, self.live, self.timer = data, rand, [], 0

    def born(self, x, y, z, round_start):
        r = self.rand
        if round_start:
            y = (y * (r() & 0xFFFF)) >> 15
        vx, vz = r() & self.d.fall[0], -(r() & self.d.fall[2])
        r()
        return [x, y, z, vx, self.d.fall[1], vz]

    def step(self):
        for p in self.live:
            p[0] += p[3]
            p[1] += p[4]
            p[2] += p[5]
        self.live = [p for p in self.live if p[1] <= 0]


def particle_ttt(cam_rot, rel, quad, ofx, ofy, h, hires=False):
    """0x80155D34's FT4 of one particle in TTT: cam_rot = RotMatrix of the
    camera's angles (rows as RotMatrix gives them), rel = position minus the
    camera's (s16 each). Returns ([(x, y)] x 4, SZ of the 4 corners)."""
    import numpy as np
    import gte
    import anim
    s16 = anim.s16
    r = [list(row) for row in cam_rot]
    r[1] = [s16((v * 10 << int(hires)) >> 4) for v in r[1]]
    t = anim.apply_matrix(r, [s16(v) for v in rel])
    ident = np.array([[0x1000, 0, 0], [0, s16((0x1000 * 10 << int(hires)) >> 4), 0], [0, 0, 0x1000]], np.int64)
    sx, sy, sz = gte.rtps(gte.Camera(ident, np.array(t, np.int64), ofx, ofy, h), np.array(quad))
    return [(int(sx[k]), int(sy[k])) for k in range(4)], [int(v) for v in sz]


def row_norms(rot):
    """|row k| of a 4.12 matrix, the PS1 port's scale of a camera-facing quad:
    TTT's rows are (4096, 4096 x 10 / 16, 4096), the PS1 world matrix's its
    own (its screen is 368 x 480)."""
    import math
    return [math.isqrt(sum(int(v) * int(v) for v in row)) for row in rot]


def particle_ps1(world_rot, world_trans, pos, quad, ofx, ofy, h):
    """The PS1 port of a particle's FT4 (src/tekken3_arcade_stages.c): its
    centre through the PS1 world matrix (0x800ADF70: world units, as the
    floor's), the corners added unrotated, each axis scaled by that matrix's
    row norms. Returns ([(x, y)] x 4, [SZ] x 4)."""
    import numpy as np
    import gte
    rot = np.array(world_rot, np.int64)
    c = ((rot @ np.array(pos, np.int64)) >> 12) + np.array(world_trans, np.int64)
    n = row_norms(world_rot)
    out, zs = [], []
    for q in quad:
        p = np.array([c[k] + ((q[k] * n[k]) >> 12) for k in range(3)], np.int64)
        cam = gte.Camera(np.zeros((3, 3), np.int64), p, ofx, ofy, h)
        sx, sy, sz = gte.rtps(cam, np.zeros((1, 3), np.int64))
        out.append((int(sx[0]), int(sy[0])))
        zs.append(int(sz[0]))
    return out, zs


# ---------------------------------------------------------------------------
# Stage 11's light beams at the fighters' feet (0x801631FC at each round, in
# the fights (main state 4) on stage 11; 0x80163554 every frame, from the
# fighters' drawing). Per fighter, body parts 14 and 17 (the ankles, +0xA8C +
# 0x50 * part): when the part is near the floor (y > -0x101), 14 vertices
# (0x8019CDDC) through the world matrix (0x803A8280) times RotMatrixY of one
# angle drawn per round (rand & 0xE00, + 0x800), moved to the part's (x, 0,
# z); 6 semi-transparent GT4 (indices 0x8019CE4C, page (0x1C0, 0x200) abr 1,
# CLUT (0x200, 0x9F)), black at the foot, colours 0x8019CE64 + 16 i scaled by
# an intensity that walks 0..0x100 by random steps, u scrolling by 2 a frame
# (0x8019CEC4), v 0..0x14; main OT rank 5. When the camera lies along the
# beams (|dot| > 0xF80 with their direction) the routine returns at part 14
# and part 17's phase stops. Measured on S2's stage 11 dumps (32 parts drawn,
# 192 GT4: xy, colours, uv = glow_commands).
# ---------------------------------------------------------------------------
GLOW_STAGE = 11
GLOW_VERTS, GLOW_INDEX, GLOW_COLOURS, GLOW_UV = 0x8019CDDC, 0x8019CE4C, 0x8019CE64, 0x8019CEC4
GLOW_PAGE, GLOW_CLUT, GLOW_PARTS = (0x1C0, 0x200), (0x200, 0x9F), (14, 17)


@dataclass
class Glow:
    verts: list         # 14 (x, y, z)
    index: list         # 6 x 4 vertex indices
    colours: list       # 6 x (rgb0, rgb1, rgb2 base, rgb3 base)
    uv: list            # 4 u of the strips' edges
    tpage: int
    clut: int           # low half (moved up by the pack)


def parse_glow(src):
    c = [src.bytes_at(GLOW_COLOURS + 16 * i, 16) for i in range(6)]
    return Glow([src.word(GLOW_VERTS + 8 * i, 3, 'h') for i in range(14)],
                [list(src.bytes_at(GLOW_INDEX + 4 * i, 4)) for i in range(6)],
                [(tuple(q[0:3]), tuple(q[4:7]), tuple(q[8:11]), tuple(q[12:15])) for q in c],
                [src.bytes_at(GLOW_UV, 8)[2 * k] for k in range(4)],
                get_tpage(0, 1, *GLOW_PAGE), get_clut(*GLOW_CLUT))


def glow_commands(glow, rot, trans, ofx, ofy, h, phase, intensity):
    """0x80163554's 6 GT4 of one part: rot, trans = the GTE it sets (world x
    RotMatrixY, translation world x (x, 0, z) + world's); phase 0..0x1F,
    intensity 0..0x100."""
    import numpy as np
    import gte
    sx, sy, sz = gte.rtps(gte.Camera(np.array(rot, np.int64), np.array(trans, np.int64), ofx, ofy, h),
                          np.array(glow.verts))
    c = (-(phase & 0x1F)) & 0xFF
    sc = lambda v: ((v * intensity + (0xFF if v * intensity < 0 else 0)) >> 8) & 0xFF
    out = []
    for i in range(6):
        j = i if i <= 2 else i - 3
        u0, u1 = (c + glow.uv[j] - 0x40) & 0xFF, (c + glow.uv[j + 1] - 0x40) & 0xFF
        col = glow.colours[i]
        out.append(dict(kind='gt4', code=0x3E, xy=[(int(sx[k]), int(sy[k])) for k in glow.index[i]],
                        rgb=[col[0], col[1], tuple(sc(v) for v in col[2]), tuple(sc(v) for v in col[3])],
                        uv=[(u0, 0), (u1, 0), (u0, 0x14), (u1, 0x14)], clut=glow.clut, tpage=glow.tpage))
    return out


# ---------------------------------------------------------------------------
# Stage 3's object (archive 22, one model): 0x8016213C at each round and
# load (position (0, -0x16B, -0x1022) in tile units, yaw 0x555, c = 0x5550,
# k = 0), 0x80162198 every frame of a fight: yaw = c >> 4, c -= 0x40, k +=
# 0x40, past 0x2AA9 k = 0 and c = 0x5550 - k % 0x2AAA: -4 a frame, back near
# 0x555 every 171 frames (measured on S2's stage 3 dumps: 25 frames). Drawn
# with RotMatrix(0, yaw, 0) of the tiles' matrix (0x80160210).
# ---------------------------------------------------------------------------
OBJECT3_POS = (0, -0x16B, -0x1022)


class TttObject3:
    def __init__(self):
        self.reset()

    def reset(self):
        self.yaw, self.c, self.k = 0x555, 0x5550, 0

    def step(self):
        self.yaw = (self.c >> 4) & 0xFFFF
        self.yaw -= 0x10000 if self.yaw & 0x8000 else 0
        self.c -= 0x40
        self.k += 0x40
        if self.k > 0x2AA9:
            self.c = 0x5550 - self.k % 0x2AAA
            self.k = 0


# ---------------------------------------------------------------------------
# The light on the fighters (B76): one 24-byte entry per stage, entry n + 1
# for stage n, read by 0x8010C18C(0x802434E4) at the stage load and by
# 0x8010CCA8 per fighter. Tekken 3's table 0x80096C78 (PS1, 28 bytes) has the
# same fields in its first 24 bytes, read the same way (0x80039960,
# 0x8003A164): u16 +0 the ambient << 4 (SetBackColor), +4 a colour
# (0x8010CE20), +8..+10 the light's b, g, r (colour matrix column 0, and
# halved column 2), u16 +12 / +14 its angles (light matrix row 0), +16 the
# shadows' colour (0x8010CE48), u16 +20 / +22 the shadows' angles
# (0x8010CDF0). T3's last 4 bytes have no TTT field.
# ---------------------------------------------------------------------------
FIGHTER_LIGHT = 0x80194164
FIGHTER_LIGHT_SIZE = 24
FIGHTER_LIGHT_SETUP = 0x8010C18C


def fighter_light(src, stage):
    """Stage's 24 bytes. The table is read back from 0x8010C18C: a0 * 24
    (sll 1, addu, sll 3) plus the table's entry 1 (lui / addiu v0)."""
    w = [src.word(FIGHTER_LIGHT_SETUP + 4 * k) for k in range(1, 6)]
    assert w[:3] == [0x00041840, 0x00641821, 0x000318C0], 'no a0 * 24 in 0x8010C18C'
    assert w[3] >> 16 == 0x3C02 and w[4] >> 16 == 0x2442, 'no lui / addiu v0 in 0x8010C18C'
    lo = w[4] & 0xFFFF
    table = ((w[3] & 0xFFFF) << 16) + lo - (0x10000 if lo & 0x8000 else 0)
    assert table == FIGHTER_LIGHT + FIGHTER_LIGHT_SIZE, hex(table)
    return src.bytes_at(FIGHTER_LIGHT + FIGHTER_LIGHT_SIZE * (stage + 1), FIGHTER_LIGHT_SIZE)


# ---------------------------------------------------------------------------
# One TTT stage, everything decoded (scene.Stage's counterpart)
# ---------------------------------------------------------------------------
class Stage:
    """Everything decoded for one TTT stage (from tektagt.zip, or from a
    pack.py file with Stage.__new__ and the attributes set by pack.load)."""
    game = 'ttt'

    def __init__(self, src, stage, true_ogre=False):
        import numpy as np
        self.stage, self.true_ogre = stage, true_ogre
        g, _ = src.stage(stage)
        self.geo = parse_geometry(src, stage, g, true_ogre) if g is not None else decode.Geometry(0)
        self.vram, self.rects = vram(src, stage, true_ogre)
        self.lights = None
        if stage == 11:
            cluts, self.lights = stage11_light_cluts(self.vram, src)
            for x, y, words in cluts:
                self.vram[y, x:x + 16] = np.array(words, np.uint16)
                self.rects.append(('clut', x, y, 16, 1, 4, ('floor lights', 11)))
        self.glow = parse_glow(src) if stage == GLOW_STAGE else None
        self.particles = None
        if stage == PARTICLE_STAGE:
            used = np.zeros((512, 1024), bool)
            for r in self.rects:
                if r[0] == 'image' and r[2] >= 512:
                    used[r[2] - 512:r[2] - 512 + r[4], r[1]:r[1] + r[3]] = True
            self.particles = particles(src, used)
            x, y, w, h, words = self.particles.image
            self.vram[y:y + h, x:x + w] = words
            self.rects.append(('image', x, y, w, h, 4, ('particles', EFFECTS, 0)))
            cx, cy = PARTICLE_CLUT
            for t in file_tims(src.files[EFFECTS][0]):
                if t['clut'][:2] == (cx, cy):
                    self.vram[cy, cx:cx + 16] = np.frombuffer(t['clut'][4][:32], '<u2')
            self.rects.append(('clut', cx, cy, 16, 1, 4, ('particles', EFFECTS, 0)))
        self.farbg = parse_farbg(src, stage)
        self.floor = parse_floor(src, stage, true_ogre)
        self.objects = parse_objects(src, stage)
        self.object_frame = object_frame(src)
        self.sine = src.word(SINE, 0x1400, 'h')
        self.sqrt_table = src.word(SQRT_TABLE, 192, 'h')
        self.storm = parse_storm(src) if stage == STORM_STAGE else None
        self.anim = TttAnim(src, stage) if stage in ANIM_STAGES else None
        self.axis = src.word(FIGHT_AXIS_START + 8 * stage + 4)
        self.light = fighter_light(src, stage)
        self.shade = true_ogre_shade(src, stage)
        self.rot_table = src.word(ROT_TABLE, 4096) if stage in OBJECTS else None
        # CLUT cells the animations write that no TIM brings (stage 14's floor CLUT)
        self.patches = {6: [(0x290, 0x60)], 7: [(0x2C0, 0x62)], 14: [(0x200, 0x60)]}.get(stage, [])

    def sqrt0(self, a):
        import scene
        return scene.sqrt0(None, a, self.sqrt_table)

    def sky(self, entry):
        """The far background with storm sky `entry` (15..20) or the normal one."""
        if entry is None or entry == STORM_STAGE or self.storm is None:
            return self.farbg
        desc, cluts = self.storm.skies[entry - STORM_SKIES[0]]
        return dataclasses.replace(self.farbg, desc=desc, cluts=cluts)

    def frame(self, cam, view, yaw, visible, objects=None, sky=None, lights=None):
        """All the stage's commands for one frame, in drawing order. cam:
        gte.Camera of the tiles; view: TttView of the floor; yaw: camera yaw
        minus the fight axis of the previous frame; visible(tile): the cone;
        objects: {model: gte.Camera}; sky: storm entry; lights: stage 11's
        light CLUT table and counter (default: this decoder's, counter 0).
        Link order of the game: floor, far background, objects, tiles."""
        ranks = {}

        def link(rank, cmds):
            ranks.setdefault(rank, []).append(cmds)
        if self.floor is not None and view is not None:
            clut = None
            if self.stage == 11:
                table, counter = lights if lights is not None else (self.lights, 0)
                clut = stage11_lights(table, counter)
            for rank, cmd in floor_commands(self.floor, view, self.sine, self.sqrt0, clut):
                link(rank, [cmd])
        pitch, hires = (view.pitch, view.hires) if view is not None else (0, False)
        link(1023, farbg_commands(self.sky(sky), yaw, pitch, hires, self.true_ogre))
        if objects and not self.true_ogre:
            for rank, cmds in object_commands(self.stage, self.objects, objects, self.object_frame).items():
                link(rank, cmds)
        if self.geo.tiles:
            for rank, cmds in geometry_commands(self.stage, self.geo, cam, visible).items():
                link(rank, cmds)
        out = []
        for rank in sorted(ranks, reverse=True):
            for cmds in reversed(ranks[rank]):
                out += cmds
        return out
