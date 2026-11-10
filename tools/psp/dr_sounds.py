#!/usr/bin/env python3
"""Sons et interface des personnages de Tekken : Dark Resurrection PSP (ULUS10139), lus dans l'ISO.

Carte relevee le 2026-10-25 (etape C1, PSP-DR.md « C1 : paquet sons et interface des nouveaux »,
TIPS.md section 49 decies). Decodeurs ecrits ici (rien repris d'un autre depot), sauf l'ATRAC3plus
des repliques : tools/psp/atrac3plus.py, portage du decodeur de FFmpeg (LGPL, sans ffmpeg chez le joueur).

- Voix de combat : fichier +12 du groupe d'un personnage (tools/psp/dr_iso.py), banque PS-ADPCM
  nue (blocs de 16 o, VAG sans en-tete), 8 a 26 echantillons separes par le drapeau de fin (bit 0
  de l'octet 1) ; le premier bloc est nul. Identique d'un costume a l'autre.
- Cris des coups : liste `voiceclip` du moveset (pointeur +0x2C du coup) : suite de u16 finie par
  0xFFFF ; 0x7000 + n = souffle n de la banque commune 4991 ; 0x20xx non elucide (le jeu tire le cri
  d'attaque lui-meme). Devil Jin : l'echantillon 0 de sa banque est le laser, joue a 16 000 Hz avec le son
  commun 30 (banque 4991) 70 ms apres (son de PPSSPP, 2026-11-01 ; sa prise vers le laser sans ce dernier).
- Repliques : fichier +10 du groupe, conteneur (n, (offset, taille) x n) de TKA3 (0x40 o) + RIFF
  ATRAC3plus mono 44100 Hz.
- Annonceur (noms) : TKPDATA1 1, banque PS-ADPCM commune de 37 echantillons, jouee a 18 002 Hz
  (hauteur 0x688) ; Devil Jin = 1, Dragunov = 34.
- Interface : images NTPP (NUT PSP, CLUT8 / CLUT4 swizzlees) : 12..65 grands portraits 256 x 256,
  2 grille du selecteur (vignettes 64 x 64, noms 128 x 32), 11 ecran VS, 4 et 1258 tournoi. Fichiers
  LZ nus (octet de drapeaux en tete) : dr_iso.Disc.lz.

Sous-commandes :
  voix <perso> <dossier> [--rate n]      banque de voix en WAV (un fichier par echantillon)
  banque <fichier> <dossier> [--rate n]  banque PS-ADPCM d'un fichier TKPDATA1 en WAV
  cris <perso>                           suites voiceclip du moveset et coups qui les jouent
  repliques <perso> <dossier>            .at3 du fichier +10 (ATRAC3plus) et leur WAV (atrac3plus.py)
  images <fichier> <dossier>             images NTPP d'un fichier TKPDATA1 en PNG (Pillow)
  paquet <cle> <dossier> --radical R --sfx BASE.jus   <R>-DR-voices.juv et <R>-DR-sfx.jus (B3, numpy)
  ecoute <cle> <dossier>                 cris a la hauteur du jeu et nom annonce, 44 100 Hz, pour les classer
"""
import argparse, collections, struct, sys, wave
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dr_iso as D
import layout as L

VOICES, LINES = 12, 10                         # place dans le groupe de 16 d'un personnage
ANNOUNCER = 1                                  # TKPDATA1 : noms dits par l'annonceur
RATE = 22050                                   # frequence des banques PS-ADPCM (temoin PPSSPP, TIPS 49 decies)
ANNOUNCER_RATE = 18002                         # hauteur 0x688 de l'annonceur


# ---------------------------------------------------------------- PS-ADPCM
FILTERS = [(0, 0), (60, 0), (115, -52), (98, -55), (122, -60)]

def split(bank):
    """[(debut, fin)] des echantillons d'une banque nue : un echantillon finit sur un bloc dont le
    bit 0 de l'octet de drapeaux vaut 1 ; les blocs nuls entre deux sont sautes."""
    out, start = [], None
    for o in range(0, len(bank) - 15, 16):
        blk = bank[o:o + 16]
        if start is None:
            if blk == bytes(16): continue
            start = o
        if blk[1] & 1: out.append((start, o + 16)); start = None
    if start is not None: out.append((start, len(bank)))
    return out

def decode(adpcm):
    """PS-ADPCM -> PCM s16 (28 echantillons par bloc de 16 o)."""
    s1 = s2 = 0; pcm = []
    for o in range(0, len(adpcm) - 15, 16):
        shift, f = adpcm[o] & 15, min(adpcm[o] >> 4, 4)
        f0, f1 = FILTERS[f]
        for i in range(28):
            n = (adpcm[o + 2 + i // 2] >> (4 * (i & 1))) & 15
            if n >= 8: n -= 16
            v = ((n << 12) >> shift if shift <= 12 else 0) + ((s1 * f0 + s2 * f1 + 32) >> 6)
            v = max(-32768, min(32767, v)); pcm.append(v); s2, s1 = s1, v
    return pcm

def write_wav(path, pcm, rate):
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(struct.pack(f'<{len(pcm)}h', *pcm))

def bank_wavs(bank, out, rate):
    out.mkdir(parents=True, exist_ok=True)
    for i, (a, z) in enumerate(split(bank)):
        pcm = decode(bank[a:z]); write_wav(out / f'{i:02d}.wav', pcm, rate)
        print(f'{i:2d}  {len(pcm) / rate:5.2f} s  {z - a:6d} o')


# ---------------------------------------------------------------- cris des coups
def voiceclips(disc, name):
    """{suite u16: [coups]} depuis la liste voiceclip du moveset relogé."""
    mot = D.moveset_from_iso(disc, name, D.H1, D.ANIMS1, D.COMMON1)
    ram = D.fake_ram(mot, D.H1)
    rd = lambda a, n: ram[a - L.RAM_BASE:a - L.RAM_BASE + n]
    m = L.Moveset(rd)
    out = collections.defaultdict(list)
    for i in range(m.lists['move'][1]):
        a = struct.unpack('<I', rd(m.move(i) + 0x2C, 4))[0]
        if not a: continue
        seq = []
        while len(seq) < 16:
            v = struct.unpack('<H', rd(a, 2))[0]; a += 2
            if v == 0xFFFF: break
            seq.append(v)
        out[tuple(seq)].append(m.move_name(i))
    return out


# ---------------------------------------------------------------- repliques ATRAC3plus
def tka3(container):
    n = struct.unpack_from('<I', container, 0)[0]
    for i in range(n):
        o, size = struct.unpack_from('<II', container, 4 + 8 * i)
        e = container[o:o + size]
        assert e[:4] == b'TKA3', (i, e[:4])
        yield i, e[e.find(b'RIFF'):]


# ---------------------------------------------------------------- images NTPP
def ntpp_images(data):
    """Images de tous les blocs NTPP d'un fichier : dict(w, h, fmt, cf, data, pal)."""
    o = data.find(b'NTPP')
    while o >= 0:
        q = o + 0x10
        while q + 0x20 <= len(data):
            tot, pal, dat, hs = struct.unpack_from('<IIIH', data, q)
            if not tot or q + tot > len(data): break
            w, h = struct.unpack_from('<HH', data, q + 0x14)
            if dat: yield dict(w=w, h=h, fmt=data[q + 0x13], cf=data[q + 0x12],
                               data=data[q + hs:q + hs + dat], pal=data[q + hs + dat:q + hs + dat + pal])
            q += tot
        o = data.find(b'NTPP', o + 4)

def image(t):
    """Image RGBA (Pillow) d'une texture CLUT8 / CLUT4 swizzlee (blocs 16 o x 8 lignes)."""
    from PIL import Image
    import ge_dump
    bpp = {0x85: 8, 0x84: 4}.get(t['fmt'])
    if not bpp: return None
    rb = t['w'] * bpp // 8
    px = ge_dump.unswizzle(t['data'], rb, t['h'])
    cs = 4 if t['cf'] == 3 else 2
    pal = [ge_dump.color(struct.unpack_from('<I' if cs == 4 else '<H', t['pal'], i * cs)[0], t['cf'])
           for i in range(len(t['pal']) // cs)]
    im = Image.new('RGBA', (t['w'], t['h'])); put = im.load()
    for y in range(t['h']):
        for x in range(t['w']):
            i = px[y * rb + x] if bpp == 8 else (px[y * rb + x // 2] >> (4 * (x & 1))) & 15
            put[x, y] = pal[i] if i < len(pal) else (255, 0, 255, 255)
    return im

def file_data(disc, n):
    """Contenu utile : enveloppe FF AC F4 31, ou LZ nu quand le clair ne commence pas par un NTPP."""
    raw = disc.raw(n)
    if raw[:4] == b'\xff\xac\xf4\x31' or raw[:4] == b'NTPP': return D.plain(raw)
    try: d = D.unlz(raw)[0]
    except IndexError: return raw
    return d if b'NTPP' in d else raw


# ---------------------------------------------------------------- paquet des invites (B3)
# Cris d'un nouveau personnage DR au format des invites TTT1 (tools/ttt1/voices.py) : la banque +12
# jouee a la hauteur SAS du personnage (table data/dr_voices.json, temoin PPSSPP de C1 ; Devil Jin
# 0x741), reechantillonnee a 44 100 Hz, rangee par categorie dans <Radical>-DR-voices.juv ('JUV1',
# rang categorie << 16 | rang ; 2 attaque, 3 coup recu, 4 K.O., 5 victoire, aucune vide). Le laser
# (un echantillon de la banque a sa frequence, laser()) et le nom de l'annonceur (fichier 1, 18 002 Hz) vont aux entrees 1024
# et 1025 de <Radical>-DR-sfx.jus, les autres entrees reprises de la .jus du moveset de base.
TABLE = HERE / 'data/dr_voices.json'
OUT_RATE = 44100
JUV = 0x3156554a                                 # 'JUV1' ; la marque de la .jus est reprise de la base
CATEGORIES = {'attack': 2, 'damage': 3, 'ko': 4, 'victory': 5}


def table(key):
    import json
    t = json.loads(TABLE.read_text(encoding='utf-8'))
    if key not in t: raise SystemExit(f'{key} absent de {TABLE}')
    return t[key]


def resample(pcm, rate):
    """PCM s16 a `rate` -> 44 100 Hz, lineaire, en octets."""
    import numpy as np
    x = np.asarray(pcm, dtype=np.float64)
    n = int(round(len(x) * OUT_RATE / rate))
    y = np.interp(np.arange(n) * (rate / OUT_RATE), np.arange(len(x)), x)
    return np.clip(np.round(y), -32768, 32767).astype('<i2').tobytes()


def samples(disc, t):
    """Les echantillons de la banque +12, joues a la hauteur du personnage : [PCM 44 100 Hz]."""
    bank = disc.file(D.group_of(t['dr']) + VOICES)
    rate = RATE * t['pitch'] / 0x800
    return [resample(decode(bank[a:z]), rate) for a, z in split(bank)]


def announcer(disc, t):
    bank = disc.file(ANNOUNCER)
    a, z = split(bank)[t['announcer']]
    return resample(decode(bank[a:z]), ANNOUNCER_RATE)


def juv(clips, t):
    """<Radical>-DR-voices.juv : les echantillons de la table par categorie, dans son ordre."""
    for c in CATEGORIES:
        if not t['voices'][c]: raise SystemExit(f'{t["dr"]} : categorie {c} vide')
    slots = [(n, CATEGORIES[c], r) for c in CATEGORIES for r, n in enumerate(t['voices'][c])]
    if len(slots) > 32: raise SystemExit(f'{len(slots)} cris, le moteur en garde 32')
    blob = bytearray(32 + 16 * len(slots))
    for i, (n, cat, rank) in enumerate(slots):
        pcm = clips[n]
        struct.pack_into('<4I', blob, 32 + 16 * i, n, len(blob), len(pcm) // 2, cat << 16 | rank)
        blob += pcm
    struct.pack_into('<8I', blob, 0, JUV, 1, len(blob), len(slots), OUT_RATE, 0, 0, 0)
    return bytes(blob)


LINE = 1026                                    # premiere replique dans la .jus (dr_pack LINE_SOUND)
COMMON, COMMON_BANK = 1100, 4991               # son commun n de DR (categorie 1, 0x10nn) : .jus COMMON + n


def common(disc, t):
    """Les sons communs de la table (common : {n: rate, gain}), banque 4991, joues a leur hauteur : {index .jus:
    PCM 44 100 Hz}. Devil Jin : 0x22, le gresillement de sa victoire 4 (0x815A 0x1022 de Dj_Win_D_n, 12 fois),
    retrouve en RAM pendant la pose, 16 000 Hz, au niveau 0,17 dans DR (sans musique, PPSSPP)."""
    import numpy as np
    bank, out = disc.file(COMMON_BANK), {}
    parts = split(bank)
    for n, c in t.get('common', {}).items():
        a, z = parts[int(n)]
        x = np.frombuffer(resample(decode(bank[a:z]), c['rate']), '<i2').astype(np.float64) * c['gain']
        out[COMMON + int(n)] = np.clip(np.round(x), -32768, 32767).astype('<i2').tobytes()
    return out


def laser(disc, t):
    """Le son du laser tel que DR le joue (table : laser) : l'echantillon de la banque +12 a sa propre
    frequence (16 000 Hz pour Devil Jin, pas la hauteur des cris : joue a 0x741 il sortait aigu et court),
    puis le son commun `with` (banque 4991) `at` secondes apres, chacun a son niveau (le pack plein
    echelle saturait au double du mixeur des invites) : PCM 44 100 Hz, None sans laser."""
    import numpy as np
    c = t.get('laser')
    if c is None: return None
    bank = disc.file(D.group_of(t['dr']) + VOICES)
    a, z = split(bank)[c['sample']]
    x = np.frombuffer(resample(decode(bank[a:z]), c['rate']), '<i2').astype(np.float64) * c['gain']
    w = c.get('with')
    if w:
        common = disc.file(COMMON_BANK)
        a, z = split(common)[w['common']]
        y = np.frombuffer(resample(decode(common[a:z]), w['rate']), '<i2').astype(np.float64) * w['gain']
        at = int(round(w['at'] * OUT_RATE))
        x = np.pad(x, (0, max(0, at + len(y) - len(x))))
        x[at:at + len(y)] += y
    return np.clip(np.round(x), -32768, 32767).astype('<i2').tobytes()


def jus(base, laser, name, lines=(), gains=(), extra=None):
    """La .jus de base, le laser en 1024 (mot du pilote des lasers TTT1), le nom en 1025, les repliques
    (PCM 44 100 Hz mono, deja decodees) en 1026 + n, chacune a son niveau (table : line_gains), puis extra
    ({index : PCM}, les sons communs)."""
    sys.path.insert(0, str(HERE.parent / 'ttt1'))
    import sfx as SFX
    magic, _, _, n, rate = struct.unpack_from('<5I', base)
    if rate != OUT_RATE: raise SystemExit(f'.jus de base a {rate} Hz')
    entries = {}
    for i in range(n):
        index, at, frames, driver = struct.unpack_from('<4I', base, 32 + 16 * i)
        entries[index] = (driver, base[at:at + 2 * frames])
    if laser is not None: entries[SFX.LASER] = (SFX.RAW[SFX.LASER][1], laser)
    entries[SFX.NAME] = (entries.get(SFX.NAME, (0, b''))[0], name)
    import numpy as np
    for n, pcm in enumerate(lines):
        g = gains[n] if n < len(gains) else 1.0
        x = np.clip(np.round(np.frombuffer(pcm, '<i2').astype(np.float64) * g), -32768, 32767).astype('<i2')
        entries[LINE + n] = (entries[SFX.NAME][0], x.tobytes())
    for index, pcm in (extra or {}).items(): entries[index] = (entries[SFX.NAME][0], pcm)
    blob = bytearray(32 + 16 * len(entries))
    for i, index in enumerate(sorted(entries)):
        driver, pcm = entries[index]
        struct.pack_into('<4I', blob, 32 + 16 * i, index, len(blob), len(pcm) // 2, driver)
        blob += pcm
    struct.pack_into('<8I', blob, 0, magic, 1, len(blob), len(entries), OUT_RATE, 0, 0, 0)
    return bytes(blob)


def lines(disc, t):
    """Les repliques du fichier +10, decodees (tools/psp/atrac3plus.py) : [PCM 44 100 Hz mono]."""
    import atrac3plus
    out = []
    for i, riff in tka3(disc.file(D.group_of(t['dr']) + LINES)):
        pcm, rate = atrac3plus.decode(riff)
        if rate != OUT_RATE: raise SystemExit(f'{t["dr"]} : replique {i} a {rate} Hz')
        out.append(pcm)
    return out


def build(key, radical, out, base_sfx, iso=None):
    """Ecrit <radical>-DR-voices.juv et <radical>-DR-sfx.jus dans out (le roster installe).
    iso : dr_iso.ISO si absent (tools/dr_setup.py y met celui du joueur)."""
    t = table(key); disc = D.Disc(iso or D.ISO)
    clips = samples(disc, t)
    out = Path(out)
    for name, data in ((f'{radical}-DR-voices.juv', juv(clips, t)),
                       (f'{radical}-DR-sfx.jus', jus(Path(base_sfx).read_bytes(),
                                                     laser(disc, t),
                                                     announcer(disc, t), lines(disc, t),
                                                     t.get('line_gains', ()), common(disc, t)))):
        path = out / name
        path.unlink(missing_ok=True)             # roster en liens durs : jamais ecrire au travers
        path.write_bytes(data)
    return t


# ---------------------------------------------------------------- commandes
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--iso', type=Path, default=D.ISO)
    sp = ap.add_subparsers(dest='cmd', required=True)
    c = sp.add_parser('voix'); c.add_argument('perso'); c.add_argument('out', type=Path)
    c.add_argument('--rate', type=int, default=RATE); c.add_argument('--costume', type=int, default=0)
    c = sp.add_parser('banque'); c.add_argument('n', type=int); c.add_argument('out', type=Path)
    c.add_argument('--rate', type=int, default=RATE)
    c = sp.add_parser('cris'); c.add_argument('perso')
    c = sp.add_parser('repliques'); c.add_argument('perso'); c.add_argument('out', type=Path)
    c = sp.add_parser('images'); c.add_argument('n', type=int); c.add_argument('out', type=Path)
    c = sp.add_parser('paquet'); c.add_argument('cle'); c.add_argument('out', type=Path)
    c.add_argument('--radical', required=True); c.add_argument('--sfx', type=Path, required=True)
    c = sp.add_parser('ecoute'); c.add_argument('cle'); c.add_argument('out', type=Path)
    a = ap.parse_args()
    if a.cmd == 'paquet':
        build(a.cle, a.radical, a.out, a.sfx, a.iso)
        print(f'{a.radical}-DR-voices.juv, {a.radical}-DR-sfx.jus -> {a.out}'); return
    if a.cmd == 'ecoute':
        t = table(a.cle); disc = D.Disc(a.iso); a.out.mkdir(parents=True, exist_ok=True)
        for name, pcm in [(f'{i:02d}.wav', c) for i, c in enumerate(samples(disc, t))] + [('nom.wav', announcer(disc, t))]:
            with wave.open(str(a.out / name), 'wb') as w:
                w.setparams((1, 2, OUT_RATE, 0, 'NONE', 'not compressed')); w.writeframes(pcm)
        return
    disc = D.Disc(a.iso)
    if a.cmd == 'voix':
        bank_wavs(disc.file(D.group_of(a.perso, a.costume) + VOICES), a.out, a.rate)
    elif a.cmd == 'banque':
        bank_wavs(disc.file(a.n), a.out, a.rate)
    elif a.cmd == 'cris':
        for seq, moves in sorted(voiceclips(disc, a.perso).items(), key=lambda kv: -len(kv[1])):
            print(f'{len(moves):4d}  {" ".join(f"{v:04x}" for v in seq):24s} {", ".join(moves[:6])}')
    elif a.cmd == 'repliques':
        import atrac3plus
        a.out.mkdir(parents=True, exist_ok=True)
        for i, riff in tka3(disc.file(D.group_of(a.perso) + LINES)):
            (a.out / f'{i:02d}.at3').write_bytes(riff)
            pcm, rate = atrac3plus.decode(riff)
            write_wav(a.out / f'{i:02d}.wav', struct.unpack(f'<{len(pcm) // 2}h', pcm), rate)
            print(f'{i:2d}  {rate} Hz  {len(riff)} o  {len(pcm) / 2 / rate:.2f} s')
    elif a.cmd == 'images':
        a.out.mkdir(parents=True, exist_ok=True)
        for i, t in enumerate(ntpp_images(file_data(disc, a.n))):
            im = image(t)
            if im: im.save(a.out / f'{a.n}_{i:03d}_{t["w"]}x{t["h"]}.png')

if __name__ == '__main__':
    main()
