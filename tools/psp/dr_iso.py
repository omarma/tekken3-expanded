#!/usr/bin/env python3
"""Lecture directe de l'ISO de Tekken : Dark Resurrection PSP (ULUS10139), sans PPSSPP.

Carte relevee le 2026-10-13 (TIPS.md section 49 quater, PSP-DR.md « Etude de l'ISO ») :

- ISO 9660 ordinaire ; les donnees sont dans PSP_GAME/USRDIR/TKPDATA1.BIN (5004 fichiers) et
  TKPDATA0.BIN (49 fichiers, videos PSMF). Pas de noms : un fichier est un numero dans sa table.
- Table des fichiers : dans l'EBOOT (chiffre), en RAM a 0x08AFC234, 40 octets par fichier :
  secteur de depart (2048 o, relatif a l'archive), taille (0xFFFFFFFF = absent), SHA-1 du clair,
  0, graine, 0. Elle est recopiee dans data/dr_iso_files.json (sous-commande `table`, depuis une
  RAM temoin) ; l'import du joueur n'a besoin que de l'ISO et de ce fichier.
- Chiffrement (0x08950F6C) : par secteur, mot par mot, w ^= k puis k = k * 5 + 3 ; k repart de la
  graine a chaque secteur. Graine du fichier n de son archive : 0x0A802600 + n * 0x00200201.
- Compression (0x08805CB8) : LZ a octet de drapeaux lu bit 0 d'abord, bit de poids fort = sentinelle
  (0 = fin) ; 1 = litteral, 0 = reference 16 bits grand-boutiste, distance = bits 0-10 (0 -> 0x800),
  longueur = bits 11-15 (0 -> 32). Les fichiers FF AC F4 31 se decompressent en AC F4 31 01 + taille.
- Personnage : groupe de 16 fichiers (un groupe par costume) ; +8 moveset, +9 animations (conteneur
  de 6, le 0 = paquet d'animations du personnage), +11 pieces de personnalisation (PAC, noms), +13
  modele de combat (conteneur : NTPP textures, NDPP maillages et listes GE, MIF, TK5 SPLJNT...).
  Animations communes : fichier 4996. Decodage des animations : tools/psp/dr_anim.py.
- Moveset : en-tete de 0x274 octets (29 entrees de table a +0x188), donnees ensuite ; references
  en indices (indice x taille de l'element de la liste visee) ou en octets depuis la fin de
  l'en-tete. Relogement transcrit de la fonction du jeu 0x08910D18 (`relocate`).

Sous-commandes :
  ls                          fichiers de l'ISO
  table <ram>                 recopie la table des fichiers d'une RAM temoin (.ppst ou ram.bin)
  scan                        groupes de personnages (noms des movesets) -> data/dr_iso_characters.json
  extract <perso> <dossier>   moveset (brut + relogé), animations, modele d'un personnage
  anim <perso> <coup> [--frame n]   pose decodee de l'animation d'un coup
  verify <ram> [--player 1]   moveset relogé depuis l'ISO == moveset de la RAM, a l'octet
  tsv <perso> <sortie>        export t5_moveset.py depuis l'ISO seule
"""
import argparse, hashlib, json, struct, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ISO = Path(r'C:\TekkenProject\discs\Tekken_Dark_Resurrection_USA_PSP-ARTiSAN.iso')
FILES = HERE / 'data/dr_iso_files.json'
CHARS = HERE / 'data/dr_iso_characters.json'
GRID = HERE / 'data/dr_practice_grid.json'
sys.path.insert(0, str(HERE))
import layout as L

SECTOR = 2048
ARCHIVES = ('TKPDATA1.BIN', 'TKPDATA0.BIN')   # ordre des tables dans l'EBOOT
TABLE_RAM = 0x08AFC234                         # table des fichiers (EBOOT), 40 octets par fichier
SEED0, SEED_STEP = 0x0A802600, 0x00200201
COMMON_ANIM = 4996                             # animations communes (TKPDATA1)
GROUP = dict(moveset=8, anims=9, parts=11, model=13)   # place dans le groupe de 16 d'un personnage
MODE = 0x08B7519C                              # mode de jeu (Practice : 0x0D), lu par le relogeur
PRACTICE = 0x0D
NAMES_STRIPPED = 0x08AEAD64                    # chaine mise a la place des noms si l'octet +3 de l'en-tete vaut 1


# ---------------------------------------------------------------- ISO 9660
class Iso:
    """Lecteur ISO 9660 minimal : chemins -> (secteur, taille)."""
    def __init__(s, path=ISO):
        s.f = open(path, 'rb'); s.files = {}
        pvd = s.sector(16)
        if pvd[1:6] != b'CD001': raise SystemExit(f'{path} : pas un ISO 9660')
        s._walk(pvd[156:190], '')

    def sector(s, n, count=1):
        s.f.seek(n * SECTOR); return s.f.read(count * SECTOR)

    def _walk(s, rec, path):
        lba, size = struct.unpack_from('<I', rec, 2)[0], struct.unpack_from('<I', rec, 10)[0]
        d = s.sector(lba, (size + SECTOR - 1) // SECTOR); i = 0
        while i < size:
            n = d[i]
            if not n: i = (i // SECTOR + 1) * SECTOR; continue
            r = d[i:i + n]; name = r[33:33 + r[32]]
            if name not in (b'\0', b'\1'):
                p = f"{path}/{name.decode().split(';')[0]}"
                if r[25] & 2: s._walk(r, p)
                else: s.files[p] = (struct.unpack_from('<I', r, 2)[0], struct.unpack_from('<I', r, 10)[0])
            i += n

    def lba(s, name):
        return next(v for k, v in s.files.items() if k.upper().endswith('/' + name.upper()))


# ---------------------------------------------------------------- chiffrement, compression
def seed(n): return (SEED0 + n * SEED_STEP) & 0xFFFFFFFF

def keystream(k):
    w = []
    for _ in range(SECTOR // 4): w.append(k); k = (k * 5 + 3) & 0xFFFFFFFF
    return int.from_bytes(struct.pack(f'<{SECTOR // 4}I', *w), 'little')

def decrypt(raw, k):
    ks = keystream(k); out = bytearray()
    for o in range(0, len(raw), SECTOR):
        out += (int.from_bytes(raw[o:o + SECTOR], 'little') ^ ks).to_bytes(SECTOR, 'little')
    return bytes(out)

def unlz(src, pos=0):
    """Decompresseur de 0x08805CB8 ; rend (donnees, position apres le 0 final)."""
    out = bytearray(); t = src[pos]; pos += 1
    while t:
        while t >= 2:
            if t & 1: out.append(src[pos]); pos += 1
            else:
                v = src[pos] << 8 | src[pos + 1]; pos += 2
                dist, n = v & 0x7FF or 0x800, v >> 11 & 0x1F or 0x20
                s = len(out) - dist
                for k in range(n): out.append(out[s + k])
            t >>= 1
        t = src[pos]; pos += 1
    return bytes(out), pos

def plain(data):
    """Contenu utile d'un fichier dechiffre : LZ nu (movesets, DD 00 18 01...) ou enveloppe FF AC F4 31."""
    if data[:4] == b'\xff\xac\xf4\x31': return unlz(data)[0]
    return data


# ---------------------------------------------------------------- archives
class Disc:
    def __init__(s, iso=ISO, table=FILES):
        s.iso = Iso(iso)
        s.table = json.loads(Path(table).read_text(encoding='utf-8'))
        s.base = {a: s.iso.lba(a)[0] for a in ARCHIVES}

    def raw(s, n, archive='TKPDATA1.BIN', check=True):
        """Fichier n dechiffre, verifie par le SHA-1 de la table de l'EBOOT. Une cinquantaine de
        fichiers (sons, TKPDATA1 6 a 9) sont en clair : c'est le SHA-1 qui le dit."""
        sec, size, sha = s.table[archive][n]
        if size in (0, 0xFFFFFFFF): return b''
        s.iso.f.seek((s.base[archive] + sec) * SECTOR)
        raw = s.iso.f.read((size + SECTOR - 1) // SECTOR * SECTOR)
        d = decrypt(raw, seed(n))[:size]
        if check and hashlib.sha1(d).hexdigest()[:len(sha)] != sha:
            d = raw[:size]
            if hashlib.sha1(d).hexdigest()[:len(sha)] != sha:
                raise SystemExit(f'{archive} fichier {n} : SHA-1 different (ISO autre que ULUS10139 ?)')
        return d

    def file(s, n, archive='TKPDATA1.BIN'): return plain(s.raw(n, archive))
    def lz(s, n, archive='TKPDATA1.BIN'): return unlz(s.raw(n, archive))[0]


def ram_of(path):
    """24 Mo de RAM utilisateur (0x08800000) : relevé brut ou sauvegarde d'etat PPSSPP (.ppst, zstd)."""
    b = Path(path).read_bytes()
    if Path(path).suffix.lower() != '.ppst': return b
    from compression import zstd                        # Python 3.14
    u = zstd.decompress(b[b.find(b'\x28\xb5\x2f\xfd'):])
    m = u.find(b'Memory\0')                              # section : nom (16 o), 3 mots, taille, donnees
    size = struct.unpack_from('<I', u, m + 0x1C)[0]
    mem = u[m + 0x20:m + 0x20 + size]                    # depuis 0x08000000
    return mem[L.RAM_BASE - 0x08000000:L.RAM_BASE - 0x08000000 + (24 << 20)]


def table_from_ram(ram):
    """Les deux tables de fichiers de l'EBOOT : TKPDATA1 (graines depuis 0), puis TKPDATA0."""
    o = TABLE_RAM - L.RAM_BASE; out = {}
    for a in ARCHIVES:
        rows = []
        while True:
            e = struct.unpack_from('<10I', ram, o)
            if e[8] != seed(len(rows)) or e[7] or e[9]: break
            rows.append([e[0], e[1], ram[o + 8:o + 28].hex()[:12]]); o += 40
        out[a] = rows
    return out


# ---------------------------------------------------------------- moveset
HDR = 0x274                                    # en-tete ; les references en octets partent d'ici
def u32(b, o): return struct.unpack_from('<I', b, o)[0]
def u16(b, o): return struct.unpack_from('<H', b, o)[0]


def container(data, base):
    """Adresses des sous-fichiers d'un conteneur (nombre, puis (offset, taille)) charge a `base` (0x08970968)."""
    n = u32(data, 0)
    return [base + u32(data, 4 + 8 * k) if k < n else 0 for k in range(6)]


def anim_table(pack, off=0):
    """Offsets des animations d'un paquet (u16 0x64, u16 nombre, u16 nombre d'os + types, u32 offsets)."""
    bones = struct.unpack_from('<h', pack, off + 4)[0]
    tab = off + 6 + 2 * bones + (0 if bones & 1 else 2)
    return tab


class Relocator:
    """Transcription de 0x08910D18 : moveset charge a H, animations du personnage (conteneur charge a
    `anims_at`), animations communes chargees a `common_at`. Les paquets sont donnes en octets pour
    lire la duree des animations (u16 en tete de chacune)."""
    def __init__(s, mot, H, anims, anims_at, common, common_at, mode=PRACTICE):
        s.m = bytearray(mot); s.H = H; s.SB = H + HDR; s.mode = mode
        s.anims, s.anims_at, s.common, s.common_at = anims, anims_at, common, common_at

    def g(s, o): return u32(s.m, o)
    def p(s, o, v): struct.pack_into('<I', s.m, o, v & 0xFFFFFFFF)
    def at(s, a): return a - s.H                         # adresse RAM -> offset dans le moveset
    def lst(s, e): return s.g(e), s.g(e + 4)             # (adresse relogee, nombre) d'une entree de table

    def run(s):
        m, g, p, SB = s.m, s.g, s.p, s.SB
        for o in (8, 0xC, 0x10, 0x14): p(o, g(o) + SB)
        for o in range(0x188, 0x270, 8): p(o, g(o) + SB)
        packs = container(s.anims, s.anims_at)
        for k in range(6): p(0x244 + 8 * k, packs[k])
        s.packs = {0x4000: (packs[0], s.anims, packs[0] - s.anims_at),
                   0x8000: (s.common_at, s.common, 0)}
        own = g(0x240)                                   # paquet interne (ni 0x4000 ni 0x8000)
        s.packs[0] = (own, s.m, s.at(own))
        a, c = s.lst(0x1E0)
        for i in range(c):
            mv = s.at(a + 76 * i)
            if m[3]: p(mv, NAMES_STRIPPED); p(mv + 4, NAMES_STRIPPED)
            else: p(mv, g(mv) + SB); p(mv + 4, g(mv + 4) + SB)
            p(mv + 0x20, g(0x198) + 12 * g(mv + 0x20))
            ch = u16(m, 0)
            if ch < 15 or ch == 16: s.anim(mv)
            p(mv + 0x14, g(0x1B0) + 24 * g(mv + 0x14))
            for f, e, sz in ((0x30, 0x1C8, 8), (0x34, 0x1D0, 8), (0x38, 0x1D8, 8), (0x2C, 0x1E8, 2)):
                v = g(mv + f); p(mv + f, 0 if v == 0xFFFFFFFF else g(e) + sz * v)
        for e in (0x1B0, 0x1B8): s.cancels(e)
        s.each(0x198, 12, ((0, 0x190, 4), (8, 0x188, 80)))           # hitCondition
        s.each(0x1F0, 8, ((4, 0x1F8, 4),))                          # inputSequence
        s.each(0x1D0, 8, ((0, 0x190, 4),)); s.each(0x1D8, 8, ((0, 0x190, 4),))
        s.each(0x188, 80, tuple((k * 4, 0x1A0, 12) for k in range(7)))   # reactions -> pushback
        s.each(0x1A0, 12, ((8, 0x1A8, 2),))                         # pushback -> extradata
        a, c = s.lst(0x218)
        for i in range(c):
            for k in range(7): o = s.at(a + 44 * i) + 4 * k; p(o, g(o) + SB)
        s.each(0x208, 20, ((0x10, 0x210, 4),))
        s.each(0x238, 8, ((4, 0x1C8, 8),))
        m[2] = 1; p(0x270, 0)
        return bytes(m)

    def each(s, entry, size, fields):
        a, c = s.lst(entry)
        for i in range(c):
            r = s.at(a + size * i)
            for f, target, sz in fields: s.p(r + f, s.g(target) + sz * s.g(r + f))

    def anim(s, mv):
        v = s.g(mv + 8)
        key = 0x4000 if v & 0x4000 else 0x8000 if v & 0x8000 else 0
        if key: v &= 0x3FFF; s.p(mv + 8, v)
        addr, pack, off = s.packs[key]
        e = u32(pack, anim_table(pack, off) + 4 * v)
        ptr = addr + (e & ~1)
        s.p(mv + 8, ptr)
        struct.pack_into('<H', s.m, mv + 0x24, u16(pack, off + (e & ~1)))

    def conds(s, req):
        out, o = [], s.at(req)
        while True:
            c = u16(s.m, o)
            if c == L.REQ_END: return out
            out.append(c); o += 4

    def cancels(s, entry):
        a, c = s.lst(entry)
        for i in range(c):
            r = s.at(a + 24 * i)
            s.p(r + 4, s.g(0x190) + 4 * s.g(r + 4)); s.p(r + 0xC, s.g(0x1C0) + 4 * s.g(r + 0xC))
            cmd, cs, ext = s.g(r), s.conds(s.g(r + 4)), s.g(s.at(s.g(r + 0xC)))
            arcade = s.mode in (0x20, 0x21, 0x26)
            o = 1 if cmd == 0 else 0
            if any(0x126 <= x < 0x8000 for x in cs): o |= 0x202 if arcade else 2
            if any(0x138 <= x < 0x8000 for x in cs): o |= 4
            if 0x8162 in cs: o |= 8
            if cmd or {0x6A, 0x6B, 0x6C} & set(cs): o |= 0x10
            if ext & 0x3C00 != 0x2400: o |= 0x40
            if ext & 0x3F == 0x10: o |= 0x80
            if arcade and ext & 0x3C00 == 0x1800: o |= 0x100
            struct.pack_into('<H', s.m, r + 0x16, o)


# ---------------------------------------------------------------- personnages
def char_name(mot):
    return mot[HDR + u32(mot, 8):mot.index(b'\0', HDR + u32(mot, 8))].decode('shift_jis', 'replace')


def load_chars():
    return {k: v for k, v in json.loads(CHARS.read_text(encoding='utf-8')).items() if k != '_'}


def group_of(name, costume=0):
    c = load_chars()[name]
    return c['groups'][costume]


def moveset_from_iso(disc, name, H, anims_at, common_at, mode=PRACTICE, costume=0):
    g = group_of(name, costume)
    mot = disc.lz(g + GROUP['moveset'])
    return Relocator(mot, H, disc.raw(g + GROUP['anims']), anims_at, disc.raw(COMMON_ANIM), common_at, mode).run()


def witness(ram, player):
    """Ce que la RAM temoin dit des adresses de chargement : en-tete, conteneur d'animations, communes."""
    rd = lambda a, n: ram[a - L.RAM_BASE:a - L.RAM_BASE + n]
    H = u32(rd(L.P1 + player * L.PSIZE + L.MOTBIN, 4), 0)
    hdr = rd(H, HDR)
    e0 = u32(hdr, 0x244)
    return H, e0, u32(rd(MODE, 4), 0)


# ---------------------------------------------------------------- commandes
def cmd_ls(a):
    for p, (lba, size) in sorted(Iso(a.iso).files.items()): print(f'{lba:8d} {size:11d} {p}')


def cmd_table(a):
    t = table_from_ram(ram_of(a.ram))
    lines = ['{', ' "_": "Tables des fichiers de TKPDATA1.BIN / TKPDATA0.BIN (EBOOT de ULUS10139, RAM 0x08AFC234) : '
             '[secteur dans l archive, taille en octets (4294967295 = absent), debut du SHA-1 du clair]. '
             'Graine du fichier n : 0x0A802600 + n * 0x00200201. tools/psp/dr_iso.py table <ram>.",']
    for k, a_ in enumerate(ARCHIVES):
        rows = ',\n'.join('  ' + json.dumps(r) for r in t[a_])
        lines.append(f' "{a_}": [\n{rows}\n ]' + (',' if k == 0 else ''))
    FILES.write_text('\n'.join(lines) + '\n}\n', encoding='utf-8', newline='\n')
    print({k: len(v) for k, v in t.items()}, '->', FILES)


JP = {'[ポール]': 'Paul', '[ ロウ ]': 'Law', '[ 雷 武龍 ]': 'Lei', '[キング]': 'King', '吉光': 'Yoshimitsu',
      '[ニーナ]': 'Nina', '[花郎]': 'Hwoarang', '凌 暁雨': 'Xiaoyu', '[クリスティ]': 'Christie',
      '[エディ・ゴルドー]': 'Eddy', '風間 仁': 'Jin', '[ ジュリア ]': 'Julia', '[クマ]': 'Kuma', 'ブライアン': 'Bryan',
      '三島 平八': 'Heihachi', '[ 三島 一八 ]': 'Kazuya', '[ 李 超狼 ]': 'Lee', 'ボクサー': 'Steve',
      '[ VALE-TUDO ]': 'Marduk', '[ジャック５]': 'Jack-5', '[ロジャー]': 'Roger Jr.', '[ANNA]': 'Anna',
      '[ 王 椋雷 ]': 'Wang', '[厳竜]': 'Ganryu', '[ 飛鳥 ]': 'Asuka', 'ブルース': 'Bruce', 'BAEK DOO SAN': 'Baek',
      '[DEVIL JIN]': 'Devil Jin', '[黒人忍者]': 'Raven', '[太極拳]': 'Feng', '[アマキン]': 'Armor King',
      '[EMILIE]': 'Lili', '[新キャラ(大佐)]': 'Dragunov', '[鉄拳5ボス]': 'Jinpachi'}


def cmd_scan(a):
    """Groupes de 16 fichiers dont le +8 est un moveset ; nom du moveset -> nom de la grille."""
    d = Disc(a.iso); found = {}
    rows = d.table['TKPDATA1.BIN']
    for n, (sec, size, _) in enumerate(rows):
        if size in (0, 0xFFFFFFFF) or size > 1 << 20: continue
        b = d.raw(n)
        if b[:4] != b'\xdd\x00\x18\x01': continue
        mot = unlz(b)[0]
        if mot[4:8] != b'COM\0' or 'STORY' in char_name(mot) or u32(mot, 0x1E4) < 256: continue
        g = n - GROUP['moveset']                         # +0 : petit moveset de quelques coups (sKAM)
        head = d.raw(g)
        if head[:4] != b'\xdd\x00\x18\x01' or u32(unlz(head)[0], 0x1E4) > 32: continue
        found.setdefault(char_name(mot), []).append(g)
    grid = [k for k in json.loads(GRID.read_text(encoding='utf-8')) if k != '_']
    out = {'_': 'Personnages de Dark Resurrection dans TKPDATA1.BIN : premier fichier de chaque groupe de 16 '
                '(un groupe par costume ; +8 moveset, +9 animations, +11 modele). tools/psp/dr_iso.py scan --write.'}
    for jp, groups in found.items():
        out[JP.get(jp, jp)] = dict(moveset_name=jp, groups=groups)
    for k, v in out.items(): print(k, v)
    print('grille sans moveset :', [k for k in grid if k not in out], file=sys.stderr)
    if a.write: CHARS.write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')


def cmd_verify(a):
    ram = ram_of(a.ram)
    H, e0, mode = witness(ram, a.player - 1)
    d = Disc(a.iso)
    for name, c in load_chars().items():                 # le personnage : celui dont le moveset a ce nom
        g = c['groups'][0]
        mot0 = d.lz(g + GROUP['moveset'])
        if mot0[HDR:HDR + 64] == ram[H - L.RAM_BASE + HDR:H - L.RAM_BASE + HDR + 64]: break
    else: raise SystemExit('moveset de la RAM introuvable dans l ISO')
    anims = d.raw(g + GROUP['anims'])
    anims_at = e0 - u32(anims, 4)
    common = d.raw(COMMON_ANIM)
    # Paquet commun : depuis un coup 0x8000 du fichier, son adresse en RAM moins son offset.
    mv = HDR + u32(mot0, 0x1E0)
    for i in range(u32(mot0, 0x1E4)):
        v = u32(mot0, mv + 76 * i + 8)
        if v & 0x8000:
            ptr = u32(ram, H - L.RAM_BASE + mv + 76 * i + 8)
            common_at = ptr - (u32(common, anim_table(common) + 4 * (v & 0x3FFF)) & ~1); break
    out = Relocator(mot0, H, anims, anims_at, common, common_at, mode).run()
    live = ram[H - L.RAM_BASE:H - L.RAM_BASE + len(out)]
    diff = [i for i in range(0, len(out), 4) if out[i:i + 4] != live[i:i + 4]]
    print(f'{name} (groupe {g}) : moveset {len(out)} o a 0x{H:08X}, animations a 0x{anims_at:08X}, '
          f'communes a 0x{common_at:08X}, mode 0x{mode:X} : {"IDENTIQUE" if not diff else f"{len(diff)} mots differents"}')
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True); a.out.write_bytes(out)
    return not diff


def fake_ram(mot, H):
    """24 Mo de RAM ou seuls le joueur 1 et son moveset existent : de quoi lire t5_moveset.py."""
    ram = bytearray(24 << 20)
    struct.pack_into('<I', ram, L.P1 + L.MOTBIN - L.RAM_BASE, H)
    ram[H - L.RAM_BASE:H - L.RAM_BASE + len(mot)] = mot
    return bytes(ram)


# Adresses de chargement de la sauvegarde Practice Devil Jin (les memes pour tout personnage en J1).
H1, ANIMS1, COMMON1 = 0x09571B80, 0x09657000, 0x08CC1700


def cmd_tsv(a):
    d = Disc(a.iso)
    mot = moveset_from_iso(d, a.perso, H1, ANIMS1, COMMON1, costume=a.costume)
    ram = fake_ram(mot, H1)
    if a.ram_out: a.ram_out.parent.mkdir(parents=True, exist_ok=True); a.ram_out.write_bytes(ram)
    sys.path.insert(0, str(HERE.parent / 't5'))
    import t5_moveset as T
    m = T.Moveset(ram, 0, T.DR)
    lines = ['notation\tname\tfirst\tlast\tanim\tdamage\thitlevel']
    for i, note in m.walk().items():
        v = m.moves[i]
        lines.append(f"{note}\t{v['name']}\t{v['first']}\t{v['last']}\t{v['anim_len']}\t{v['damage']}\t{v['hitlevel']:08x}")
    a.out.parent.mkdir(parents=True, exist_ok=True); a.out.write_bytes(('\n'.join(lines) + '\n').encode())
    print(f'{m.name} : {len(m.moves)} coups, {len(lines) - 1} attaques -> {a.out}', file=sys.stderr)


def cmd_extract(a):
    d = Disc(a.iso); g = group_of(a.perso, a.costume); out = Path(a.dir); out.mkdir(parents=True, exist_ok=True)
    mot = d.lz(g + GROUP['moveset'])
    (out / 'moveset.bin').write_bytes(mot)
    (out / 'moveset_ram.bin').write_bytes(moveset_from_iso(d, a.perso, H1, ANIMS1, COMMON1, costume=a.costume))
    anims = d.raw(g + GROUP['anims'])
    for k in range(u32(anims, 0)):
        o, n = struct.unpack_from('<II', anims, 4 + 8 * k); (out / f'anims_{k}.bin').write_bytes(anims[o:o + n])
    (out / 'common_anims.bin').write_bytes(d.raw(COMMON_ANIM))
    (out / 'parts.pac').write_bytes(d.raw(g + GROUP['parts']))
    body = d.raw(g + GROUP['model'])                     # conteneur : NTPP, NDPP, MIF, TK5 SPLJNT...
    for k in range(u32(body, 0)):
        o, n = struct.unpack_from('<II', body, 4 + 8 * k)
        tag = body[o:o + 4].rstrip(b'\0').decode('latin1') if body[o:o + 4].isalpha() or body[o:o + 3] == b'MIF' else 'bin'
        (out / f'model_{k:02d}_{tag.strip()}.bin').write_bytes(body[o:o + n])
    print(f'{a.perso} groupe {g} -> {out}')


def cmd_anim(a):
    """Pose d'un coup (animation lue et décodée depuis l'ISO) à une image donnée."""
    import dr_anim as A
    d = Disc(a.iso); g = group_of(a.perso, a.costume)
    mot = d.lz(g + GROUP['moveset'])
    mv = HDR + u32(mot, 0x1E0)
    i = next(i for i in range(u32(mot, 0x1E4)) if mot[HDR + u32(mot, mv + 76 * i):].split(b'\0')[0].decode('latin1') == a.coup)
    v = u32(mot, mv + 76 * i + 8)
    if v & 0x8000: pack, n, src = d.raw(COMMON_ANIM), v & 0x3FFF, 'communes'
    else:
        c = d.raw(g + GROUP['anims']); o, size = struct.unpack_from('<II', c, 4)
        pack, n, src = c[o:o + size], v & 0x3FFF, 'personnage'
    anim = pack[A.pack_offsets(pack)[n]:]
    frames = struct.unpack_from('<H', anim, 0)[0]
    print(f'{a.coup} : coup {i}, animation {n} ({src}), {frames} images')
    for b, q in enumerate(A.pose(anim, a.frame)):
        print(f'  os {b:2d} ' + ' '.join(f'{x:10.5f}' for x in q))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--iso', type=Path, default=ISO)
    sp = ap.add_subparsers(dest='cmd', required=True)
    sp.add_parser('ls')
    p = sp.add_parser('table'); p.add_argument('ram')
    p = sp.add_parser('scan'); p.add_argument('--write', action='store_true')
    p = sp.add_parser('verify'); p.add_argument('ram'); p.add_argument('--player', type=int, default=1)
    p.add_argument('--out', type=Path)
    p = sp.add_parser('tsv'); p.add_argument('perso'); p.add_argument('out', type=Path)
    p.add_argument('--costume', type=int, default=0); p.add_argument('--ram-out', type=Path)
    p = sp.add_parser('extract'); p.add_argument('perso'); p.add_argument('dir'); p.add_argument('--costume', type=int, default=0)
    p = sp.add_parser('anim'); p.add_argument('perso'); p.add_argument('coup'); p.add_argument('--frame', type=int, default=1)
    p.add_argument('--costume', type=int, default=0)
    a = ap.parse_args()
    r = globals()['cmd_' + a.cmd](a)
    if r is False: sys.exit(1)


if __name__ == '__main__':
    main()
