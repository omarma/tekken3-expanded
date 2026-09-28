#!/usr/bin/env python3
"""COMBO TRAINING de Practice pour les invites TTT1.

Tekken 3 range les combos d'entrainement dans l'overlay de Practice : table
par personnage en 0x800B25F8 (8 octets : premier combo, nombre ; 20
personnages, indexee par la cle de coups acteur +0x16), combos de 12 octets
(entrees, liste attendue, nombre d'entrees, taille de la liste). Une entree =
4 octets : boutons (1 = bouton 2, 2 = bouton 4, 4 = bouton 3, 8 = bouton 1),
directions (1 haut, 2 avant, 4 bas, 8 arriere ; le jeu retourne avant /
arriere selon le cote), duree en images. La demonstration (PLAY = SELECT)
rejoue ces entrees ; l'entrainement compare les coups joues (numero de coup,
acteur +0xA0, journalise a chaque attaque) a la liste attendue : un
demi-mot = nombre de coups, puis les numeros.

TTT1 n'a pas ce mode. Les combos viennent du wiki Tekken (sections « 10 hit
combo » / « String Hits » et chaines de la liste des coups, pages relevees
par movelist.py) ; les delais et les coups attendus sont mesures en jeu :

  python3 tools/ttt1/combos.py probe <cle> [...]   # en jeu (build-opt-dbg), via slot.py
  python3 tools/ttt1/combos.py build [<cle> ...]   # paquets <Nom>-TTT1-combos.bin
  python3 tools/ttt1/combos.py list <cle>          # candidats lus sur le wiki

probe ecrit tools/data/combos/<cle>.json (suivi par git) ; build, sans cle,
ecrit le paquet de chaque invite releve et recopie ceux des donneurs de
Tetsujin et d'Unknown (tools/ttt1_setup.py l'appelle). Paquet (petit-boutiste) :
u16 nombre de combos, puis par combo u16 entrees, u16 coups, entrees
(4 octets chacune), coups (u16 : indice dans le graphe de l'invite ; le
runtime ajoute la base du joueur, 8192 ou 8192 + 4096).
"""
import json, re, struct, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'workspace/ttt1-import'
SRC = ROOT / 'tools/data/wiki'                 # texte des pages du wiki, dans le depot
# Resultats mesures (suivis par git, rien de la ROM : notations et noms du
# wiki, delais, indices de coups) ; les essais en jeu restent sous workspace/.
OUT = ROOT / 'tools/data/combos'
RUN = WORK / 'combos/run'
sys.path.insert(0, str(Path(__file__).resolve().parent))
from movelist import PAGES, rows, MOTIONS

MAX_COMBOS = 7                      # comme les natifs (2 a 7)
MAX_INPUTS = 50                     # tampon de l'overlay (0x800B8C10)
MAX_MOVES = 48                      # 50 demi-mots, compte compris, journal a la suite
BASE_ID = 8192
IDLE = 3                            # numero de coup de la garde au repos
MAX_TRIALS = 30                     # recherche de secours (combo hors du graphe)
PRESS, GAP = 4, 12                  # images par appui, delai de depart entre deux appuis

# Pages dont l'invite partage les coups dans TTT1 (movelist.PAGES) ; Devil a
# aussi les chaines de Kazuya. Tetsujin copie un personnage au hasard.
BORROW = {'devil': ['kazuya'], 'angel': ['kazuya']}

DIRS = {'u': 1, 'f': 2, 'd': 4, 'b': 8, 'u/f': 3, 'd/f': 6, 'd/b': 12, 'u/b': 9}
BUTTON = {1: 8, 2: 1, 3: 4, 4: 2}   # bouton Tekken -> bit de l'entree du jeu


def parse(command):
    """Suite d'etapes (directions, boutons, prefixe) d'une commande du wiki,
    ou None. Prefixe : 'tap' (direction seule), 'N', 'WS' (en se relevant)."""
    c = re.sub(r'\([^)]*\)', ' ', command).replace('~', ',').strip().rstrip(',')
    for k, v in MOTIONS.items(): c = re.sub(rf'\b{k}\b', v, c, flags=re.I)
    steps = []
    for part in re.split(r'\s*,\s*', c):
        part = part.strip()
        if not part: return None
        kind = None
        m = re.match(r'^(WS|FC)\s*\+?\s*', part)
        if m: kind, part = m.group(1), part[m.end():]
        if part == 'N': steps.append((0, 0, 'N')); continue
        m = re.fullmatch(r'(?:([udbfUDBF](?:/[bfBF])?)(?:\+|$))?((?:[1-4]\+)*[1-4])?', part)
        if not m or not (m.group(1) or m.group(2)): return None
        d = DIRS.get(m.group(1).lower()) if m.group(1) else 0
        if m.group(1) and d is None: return None
        b = 0
        for x in (m.group(2) or '').split('+'):
            if x: b |= BUTTON[int(x)]
        steps.append((d, b, kind or ('tap' if not b else None)))
    return steps


def pack_prefix(key):
    """(dossier guest, prefixe) d'une cle : 'kazuya' -> Kazuya-TTT1, 'unknown@paul'
    -> Unknown@Paul-TTT1 (le moveset d'un donneur, Tetsujin / Unknown)."""
    guest, _, donor = key.partition('@')
    name = guest.capitalize() + ('@' + donor.capitalize() if donor else '')
    return WORK / guest / 'guest', f'{name}-TTT1'


def candidates(key):
    """(nom, commande, coups annonces) : combos du wiki puis chaines de coups."""
    page = key.partition('@')[2] or key          # un donneur a la page de son personnage
    pages = [page] + BORROW.get(page, [])
    tens, strings, seen = [], [], set()
    for page in pages:
        f = SRC / f'{page}.wiki'
        if not f.is_file(): continue
        text = f.read_text()
        for title, cmd in re.findall(r'\[\[([^|\]]*Hit Combo[^|\]]*)\|([^\]]+)\]\]', text):
            steps = parse(cmd)
            if steps and cmd not in seen:
                seen.add(cmd); tens.append((re.sub(r'\s*\(.*\)', '', title), cmd, steps))
        for section, name, raw in rows(text):
            if 'hrow' in section or 'ombo' in section and 'Hit' in name: continue
            cmd = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]*)\]\]', r'\1', raw)
            steps = parse(cmd)
            if not steps or cmd in seen: continue
            presses = sum(1 for s in steps if s[1])
            if presses >= 3 and sum(1 for s in steps if s[1] and not s[0]) >= 2:
                seen.add(cmd); strings.append((re.sub(r'\s*\(.*?\)', '', name), cmd, steps))
    strings.sort(key=lambda c: -sum(1 for s in c[2] if s[1]))
    # Variantes de commande prises sur la page du coup (combos.py wiki) : la
    # movelist note parfois une autre version que TTT (Lee : Shaolin Spin
    # Kicks 4, 3, 4 ; Armor King : Stagger Kick d+3+4, 4, 4).
    extra = OUT / 'wiki.json'
    if extra.is_file():
        for e in json.loads(extra.read_text()).get(key.partition('@')[2] or key, []):
            steps = parse(e['command'])
            flat = lambda c: re.sub(r'\s+', '', c)
            same = [c for c in strings if flat(c[1]) == flat(e['command'])]
            if same:                                   # deja dans la movelist : en tete
                strings.remove(same[0]); strings.insert(0, same[0]); continue
            if steps and flat(e['command']) not in {flat(x) for x in seen}:
                seen.add(e['command'])
                # en tete des chaines : la sonde ne prend que les premieres
                (tens.append if e['ten'] else lambda c: strings.insert(0, c))((e['name'], e['command'], steps))
    return tens, strings


class Graph:
    """Listes d'annulation du paquet de combat de l'invite (<Nom>-TTT1-combat.jmv,
    ecrit par moves.py). Entree : commande du moteur (bits 0..3 = boutons 1..4,
    bit 4 = l'un d'eux, bits 5..13 = directions permises, pave numerique 1..9),
    condition, parametre, destination (8192 + i), transition, puis trois
    images : debut et fin de l'acceptation de l'appui, et image ou le coup
    suivant demarre (mesure en jeu : Armor King 170 -> 171, acceptation 1..14,
    depart a l'image 8 ; chez Kazuya fin et depart sont egaux)."""
    def __init__(self, key):
        folder, prefix = pack_prefix(key)
        d = (folder / f'{prefix}-combat.jmv').read_bytes()
        n = struct.unpack_from('<8I', d)[3]
        self.links = []
        for i in range(n):
            rp, count = struct.unpack_from('<4I', d, 32 + i * 16)[2:]
            cp = struct.unpack_from('<14I', d, rp)[3]
            self.links.append([struct.unpack_from('<4H4B', d, cp + k * 12) for k in range(count)])

    def options(self, move, buttons, direction=0, held=0):
        """Suites possibles depuis `move` par ces boutons (bits du moteur) et
        cette direction (entree du jeu, 0 = neutre) : (coup, debut, fin,
        depart, direction a tenir). Si la notation ne donne pas de direction
        et que la suite en exige une, on prend celle qui est tenue (`held`),
        sinon la premiere permise. Un meme bouton peut mener a plusieurs coups
        selon l'image (Michelle 171 : 216 tot, 228 a partir de l'image 8)."""
        pad, out = NUMPAD[direction], []
        # Un lien de transition 2 sur le meme bouton garde un appui precoce
        # (images 1..7 du direct de Bruce) et passe par un coup de liaison
        # vers la suite, qui ne prend plus d'appui neuf a partir de son image
        # de depart (mesure : Bruce 1, 2 -> 240 puis 248 ; appui a l'image 8 :
        # rien). Ce n'est pas une branche : il donne l'image ou appuyer.
        early = {}
        for cmd, cond, param, dest, tr, ws, lo, hi in self.links[move]:
            if tr == 2 and cmd < 0xc000 and not cond: early[cmd] = min(early.get(cmd, 99), ws)
        # Sans lien ordinaire sur ce bouton, le lien de transition 2 est la suite
        # elle-meme (Michelle 283 : 1 -> 284, appui tot seulement).
        normal = {cmd for cmd, cond, param, dest, tr, *_ in self.links[move] if tr != 2 and cmd < 0xc000 and not cond}
        for cmd, cond, param, dest, tr, ws, lo, hi in self.links[move]:
            if cmd >= 0xc000 or cond or dest < BASE_ID or (tr == 2 and cmd in normal): continue
            ws = min(ws, early.get(cmd, ws))
            if cmd & 0x10: match = cmd & 15 and cmd & 15 & buttons == buttons and bin(buttons).count('1') == 1
            else: match = cmd & 15 == buttons
            if not match: continue
            allowed = cmd >> 5 & 0x1ff
            if not allowed or allowed >> (pad - 1) & 1: out.append((dest - BASE_ID, ws, lo, hi, direction))
            elif direction == 0:
                keep = NUMPAD.get(held)
                pick = keep if keep and allowed >> (keep - 1) & 1 else next(k for k in range(1, 10) if allowed >> (k - 1) & 1)
                out.append((dest - BASE_ID, ws, lo, hi, GAME_DIR[pick]))
        return out

    def auto(self, move):
        """Suites sans appui (commande 0x10 seule : aucun bouton, aucune
        direction) : (coup, image de depart). Jun 278 -> 236 d'elle-meme."""
        return [(dest - BASE_ID, hi) for cmd, cond, param, dest, tr, ws, lo, hi in self.links[move]
                if cmd == 0x10 and not cond and dest >= BASE_ID]


# Boutons de l'entree du jeu -> bits d'une commande du moteur (1, 2, 4, 8 = boutons 1..4).
ENGINE = {8: 1, 1: 2, 4: 4, 2: 8}
# Directions de l'entree du jeu (1 haut, 2 avant, 4 bas, 8 arriere) -> pave numerique.
NUMPAD = {0: 5, 1: 8, 2: 6, 4: 2, 8: 4, 3: 9, 6: 3, 12: 1, 9: 7}
GAME_DIR = {v: k for k, v in NUMPAD.items()}


def engine_buttons(b): return sum(v for k, v in ENGINE.items() if b & k)


def chain(graph, first, steps):
    """([(coup, debut, fin, depart, auto)], etapes) d'une suite complete d'apres
    le graphe, depuis le coup du 1er appui (toutes les branches sont essayees,
    y compris par les suites sans appui, marquees auto) ; les etapes recoivent
    la direction que le graphe exige. None si aucune branche ne mene au bout
    (ou prefixe WS / FC apres le 1er appui)."""
    idx = [i for i, st in enumerate(steps) if st[1]]
    if any(steps[i][2] for i in idx[1:]): return None
    def walk(k, move, held, hops=0):
        if k == len(idx): return [], {}
        d, b, kind = steps[idx[k]]
        for dest, ws, lo, hi, used in graph.options(move, engine_buttons(b), d, held):
            rest = walk(k + 1, dest, used)
            if rest is not None:
                return [(dest, ws, lo, hi, False)] + rest[0], {idx[k]: used, **rest[1]}
        if hops < 3:
            for dest, hi in graph.auto(move):
                rest = walk(k, dest, held, hops + 1)
                if rest is not None:
                    return [(dest, 0, 0, hi, True)] + rest[0], rest[1]
        return None
    r = walk(1, first, steps[idx[0]][0]) if idx else None
    if r is None: return None
    out = list(steps)
    for i, used in r[1].items(): out[i] = (used, out[i][1], out[i][2])
    return r[0], out


def alternatives(graph, steps):
    """Pour un combo ecarte : depuis la garde (coup 0), chaque direction de
    depart avec laquelle les memes boutons donnent une suite complete, avec
    ses coups. Un nom change ou une notation du wiki differente de TTT1
    (Stone Fists, devenu Slap U Silly) se voit ainsi."""
    presses = [s for s in steps if s[1]]
    if not presses: return []
    found = []
    for cmd, cond, param, dest, *_ in graph.links[0]:
        if cmd >= 0xc000 or cmd & 0x10 or cmd & 15 != engine_buttons(presses[0][1]) or cond or dest < BASE_ID:
            continue
        allowed = cmd >> 5 & 0x1ff
        pads = [k for k in range(1, 10) if allowed >> (k - 1) & 1] or [5]
        r = chain(graph, dest - BASE_ID, steps)
        if r: found.append((pads, [dest - BASE_ID] + [m for m, *_ in r[0]]))
    return found


def timeline(steps, gaps):
    """Entrees du jeu (boutons, directions, images) ; gaps[k] = attente apres
    le k-ieme appui de bouton."""
    out, k = [(0, 0, 0)], 0
    for d, b, kind in steps:
        if kind == 'N': out.append((0, 0, 2)); continue
        if kind == 'tap': out += [(0, d, 2), (0, 0, 2)]; continue
        if kind in ('WS', 'FC'): out += [(0, 4, 12)] + ([(0, 0, 1)] if kind == 'WS' else [])
        # La direction seule d'abord, 3 images : une seule ne suffit pas toujours au depart.
        if d and kind not in ('WS', 'FC'): out.append((0, d, 3 if k == 0 else 1))
        out.append((b, {'WS': 0, 'FC': d or 4}.get(kind, d), PRESS))
        out.append((0, 0, gaps[k] if k < len(gaps) else GAP)); k += 1
    return out


def presses(steps): return sum(1 for s in steps if s[1])


# ---------------------------------------------------------------- en jeu
# Practice sans joueur : sauvegarde d'etat 8 (selecteur Practice) de
# workspace/fixtures/ps1-saves, Jin valide pour les deux joueurs, puis le
# choix du joueur 1 devient l'invite (la grille Practice n'a pas de case
# invitee), et MODE SELECT -> 1P FREESTYLE.
STATE, ACTOR = 0x800ae204, [0x800a9228, 0x800a9228 + 0x188c]
CURSOR, CHOICE = 0x80098106, [(0x80118688, 0x80118690), (0x80118704, 0x8011870c)]
JIN, GUEST_ID = 9, 23
NONE = 0xffff
U, R, D, L = 4, 5, 6, 7
PAD = {1: 15, 2: 12, 3: 14, 4: 13}          # carre, triangle, croix, rond
def held(*bits):
    m = NONE
    for b in bits: m &= ~(1 << b)
    return m


class Game:
    def __init__(self, exe, guest, work, port=None, player=0):
        import os, shutil, socket, subprocess
        sys.path.insert(0, str(ROOT / 'psxrecomp/tools'))
        import debug_client
        self.client, self.work, self.p = debug_client, work, None
        if port: self.port = port; return
        work.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ROOT / 'workspace/fixtures/ps1-saves', work / 'saves', dirs_exist_ok=True)
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0)); self.port = s.getsockname()[1]
        env = dict(os.environ, SDL_AUDIO_DRIVER='dummy', TEKKEN3_TTT1_ROSTER='1',
                   TEKKEN3_GUEST_NATIVE='1', TEKKEN3_GUEST_UNVERIFIED='1')
        for k in ('TEKKEN3_TTT1_ASSETS', 'TEKKEN3_JUN_ASSETS', 'TEKKEN3_GUEST', 'TEKKEN3_GUEST_P2'): env.pop(k, None)
        if guest:
            env['TEKKEN3_GUEST'], _, donor = guest.partition('@')
            if player: env['TEKKEN3_GUEST_P2'] = env['TEKKEN3_GUEST']
            if donor: env['TEKKEN3_TETSUJIN_MOVESET'] = donor   # Tetsujin au round, Unknown au combat
        self.p = subprocess.Popen([str(exe), '--game', str(ROOT / 'game.toml'), '--disc', str(ROOT / 'disc/Tekken 3 (USA).cue'),
                                   '--no-launcher', '--renderer', 'software', '--headless', '--debug-port', str(self.port),
                                   '--memcard-dir', str(work / 'saves')], cwd=ROOT, env=env,
                                  stdout=(work / 'game.log').open('w'), stderr=subprocess.STDOUT)
        end = time.monotonic() + 60
        while time.monotonic() < end:
            try:
                with socket.create_connection(('127.0.0.1', self.port), .2): return
            except OSError: time.sleep(.2)
        raise RuntimeError('serveur de debogage injoignable')
    def close(self):
        if self.p and self.p.poll() is None: self.p.terminate(); self.p.wait(timeout=15)
    def q(self, r): return self.client.query('127.0.0.1', self.port, r)
    def rd(self, a, n): return bytes.fromhex(self.q(dict(cmd='read_ram', addr=f'{a:08x}', len=n))['hex'])
    def u8(self, a): return self.rd(a, 1)[0]
    def u16(self, a): return int.from_bytes(self.rd(a, 2), 'little')
    def u32(self, a): return int.from_bytes(self.rd(a, 4), 'little')
    def w8(self, a, v): self.q(dict(cmd='write_ram', addr=f'{a:08x}', val=f'{v & 255:x}'))
    def w32(self, a, v):
        for k in range(4): self.w8(a + k, (v & 0xffffffff) >> 8 * k)
    def frame(self): return self.q(dict(cmd='frame'))['frame']
    def wait_frames(self, n):
        end = self.frame() + n
        while self.frame() < end: time.sleep(.05)
    def route(self, steps):
        self.q(dict(cmd='input_route_clear'))
        for n, b in steps: self.q(dict(cmd='input_route_append', frames=int(n), buttons=int(b)))
        self.q(dict(cmd='input_route_start'))
        while self.q(dict(cmd='input_route_status')).get('active'): time.sleep(.05)
    def tap(self, mask, frames=4): self.route([(frames, mask), (8, NONE)])
    def shot(self, name): self.q(dict(cmd='screenshot_file', path=str(self.work / name)))


def start(exe, guest, work, combo=False, choice=None, player=0):
    g = Game(exe, guest, work, player=player)
    try:
        g.q(dict(cmd='turbo', enabled=1))
        g.q(dict(cmd='savestate', op='load', slot=8))
        end = time.monotonic() + 60
        while g.u32(STATE) != 9:
            if time.monotonic() > end: raise RuntimeError('selecteur Practice non atteint')
            time.sleep(.3)
        g.wait_frames(30)
        for p in (0, 1):
            for move in [held(L)] + [held(R)] * 11 + [held(D)] + [held(R)] * 11:
                if g.u8(CURSOR + p) == JIN: break
                g.tap(move); g.wait_frames(6)
            g.tap(held(PAD[3])); g.wait_frames(30)
        if guest or choice is not None:
            for a in CHOICE[player]: g.w8(a, GUEST_ID if choice is None else choice)
        end = time.monotonic() + 240
        while not (g.u32(STATE) == 8 and g.u16(ACTOR[1] + 0x3f6) > 0):
            if time.monotonic() > end: raise RuntimeError('combat non charge')
            time.sleep(.5)
        g.wait_frames(120)
        g.q(dict(cmd='turbo', enabled=0))
        if combo:                                    # MODE SELECT -> COMBO TRAINING
            g.wait_frames(60)
            for move in (held(D), held(D)): g.tap(move); g.wait_frames(10)
            g.tap(held(PAD[3])); g.wait_frames(90)
            return g
        for attempt in range(8):                     # un appui pendant la banniere est perdu
            g.tap(held(PAD[3])); g.wait_frames(60)
            before = g.u32(ACTOR[0] + 0x54)
            g.route([(4, held(PAD[1])), (6, NONE)])
            if g.u32(ACTOR[0] + 0x54) != before: break
            g.wait_frames(30)
        else:
            raise RuntimeError('1P FREESTYLE non atteint')
        g.wait_frames(60)
        return g
    except Exception:
        g.close(); raise


def place(g, distance=700):
    """Joueur 1 au repos, a `distance` du mannequin, du cote des x plus petits
    (le mannequin est remis en place par le jeu a chaque image : on ne deplace
    que J1, x aussi copie en +0x410, +0xF68)."""
    x1, _, z1 = struct.unpack('<3i', g.rd(ACTOR[0], 12))
    x2, _, z2 = struct.unpack('<3i', g.rd(ACTOR[1], 12))
    x = x2 - distance                    # toujours du meme cote : la manette en depend
    for off in (0, 0x410, 0xf68): g.w32(ACTOR[0] + off, x)
    g.w32(ACTOR[0] + 8, z2)
    g.wait_frames(40)
    # Garde debout avant l'essai : apres une suite accroupie ou de dos, une
    # direction envoyee trop tot n'est pas prise (Stone Fists donnait un direct).
    end = g.frame() + 120
    while g.u16(ACTOR[0] + 0xa0) != IDLE and g.frame() < end: g.wait_frames(4)
    g.wait_frames(10)


def pad(b, d, facing_right):
    bits = [PAD[t] for t, m in BUTTON.items() if b & m]
    if d & 1: bits.append(U)
    if d & 4: bits.append(D)
    fwd, back = (R, L) if facing_right else (L, R)
    if d & 2: bits.append(fwd)
    if d & 8: bits.append(back)
    return held(*bits)


class Probe:
    """Joue une frise d'entrees au joueur 1 et releve, image par image, les
    coups que l'entrainement journalise : quand le compteur d'image du coup
    (acteur +0x58) atteint l'octet +0x2D de son enregistrement (non nul),
    le jeu note le numero de coup (acteur +0xA0) ; voir 0x800B7EF0."""
    def __init__(self, g, native=False):
        self.g, self.actor, self.hit = g, ACTOR[0], {}
        self.base = 0 if native else BASE_ID
        g.q(dict(cmd='turbo', enabled=1))          # la frise est comptee en images
        g.q(dict(cmd='set_snapshot', slot=0, addr=f'{self.actor + 0x40:08x}'))
        g.q(dict(cmd='set_snapshot', slot=1, addr=f'{self.actor + 0x400:08x}'))

    def forward_is_right(self):
        """La droite de la manette est-elle l'avant ? Le moteur le dit : 3 images
        a droite, puis lecture des directions de l'acteur (+0x402, codage des
        commandes : pave n -> bit n + 4 ; 0x200 neutre, 0x400 avant, 0x100
        arriere, mesure). La
        position ne suffit pas : apres une suite qui le retourne, le combattant
        peut etre de dos (Kunimitsu apres Crouching Spin Kicks)."""
        g = self.g
        g.q(dict(cmd='input_route_clear'))
        g.q(dict(cmd='input_route_append', frames=3, buttons=int(held(R))))
        g.q(dict(cmd='input_route_append', frames=20, buttons=NONE))
        f0 = g.frame()
        g.q(dict(cmd='input_route_start'))
        while g.q(dict(cmd='input_route_status')).get('active'): time.sleep(.05)
        for f in range(f0, g.frame()):
            try:
                r = bytes.fromhex(g.q(dict(cmd='read_frame_ram', frame=f, addr=f'{self.actor + 0x402:08x}', len=2))['hex'])
            except Exception:
                continue
            bits = int.from_bytes(r, 'little')
            if bits & 1 << 10: return True
            if bits & 1 << 8: return False
        raise RuntimeError('sens de la manette illisible (acteur +0x402)')

    def logged_at(self, record):
        if record not in self.hit: self.hit[record] = self.g.u8(record + 0x2d)
        return self.hit[record]

    trials, seconds = 0, 0.0

    def play(self, tl):
        """[{frame, move}] des coups journalises, image relative au depart."""
        t0 = time.monotonic()
        try: return self._play(tl)
        finally: Probe.trials += 1; Probe.seconds += time.monotonic() - t0

    def _play(self, tl):
        g = self.g
        place(g)
        right = self.forward_is_right()
        self.side = right
        g.q(dict(cmd='input_route_clear'))
        for b, d, n in tl:
            if n: g.q(dict(cmd='input_route_append', frames=int(n), buttons=int(pad(b, d, right))))
        g.q(dict(cmd='input_route_append', frames=90, buttons=NONE))
        f0 = g.frame()
        g.q(dict(cmd='input_route_start'))
        while g.q(dict(cmd='input_route_status')).get('active'): time.sleep(.05)
        f1 = g.frame()
        out, last, self.idle, self.changes, prev = [], None, [], [], None
        for f in range(f0, f1):
            try:
                r = bytes.fromhex(g.q(dict(cmd='read_frame_ram', frame=f, addr=f'{self.actor + 0x54:08x}',
                                           len=0x4e))['hex'])
            except Exception:
                continue
            record, counter = struct.unpack_from('<Ih', r, 0)[0], struct.unpack_from('<h', r, 4)[0]
            move = struct.unpack_from('<H', r, 0x4c)[0]
            if move == IDLE: self.idle.append(f - f0)
            if move != prev: self.changes.append((f - f0, move)); prev = move
            now = None
            if move >= self.base and 0x80000000 <= record < 0xa0000000:
                at = self.logged_at(record)
                if at and counter == at: now = (record, counter)
            # Un arret sur image (coup porte) peut tenir le compteur : une fois par coup.
            if now and now != last: out.append(dict(frame=f - f0, move=move))
            last = now
        return out


def press_frames(tl):
    """Image de debut de chaque appui de bouton dans la frise."""
    return [sum(e[2] for e in tl[:i]) for i, e in enumerate(tl) if e[0]]


def chained(p, steps, gaps, k):
    """Images ou sont journalises les coups des appuis 1..k+1, ou None si
    l'un d'eux ne lance pas la suite. Un appui fait en avance est garde par
    le jeu jusqu'a la fin du coup en cours : on lui attribue le premier coup
    journalise apres lui et apres le coup precedent, dans les images qui
    suivent le plus tardif des deux (120 images), sans retour a la garde entre les deux
    (sinon l'appui a relance le coup isole)."""
    tl = timeline(steps, gaps)
    pf = press_frames(tl)
    logs = [m['frame'] for m in p.play(tl)]
    used, last, out = -1, -1, []
    for i in range(k + 1):
        start = max(pf[i], last + 1)
        nxt = next((j for j in range(used + 1, len(logs)) if logs[j] >= start), None)
        if nxt is None or logs[nxt] >= start + 120: return None
        if i and any(last < f < logs[nxt] for f in p.idle): return None
        used, last = nxt, logs[nxt]
        out.append(last)
    return out


def computed(p, graph, steps, log):
    """Frise calculee d'apres le graphe. Un essai mesure le debut du premier
    coup ; chaque appui tombe une image apres le debut d'acceptation du coup
    en cours, le coup suivant est attendu a son image de depart. Puis on se
    recale sur les departs observes en jeu (au plus 4 essais) jusqu'a ce que
    toute la suite se deroule. Rend (delais, coups, etapes) ou None."""
    n = presses(steps)
    tl = timeline(steps, [GAP] * n)
    logs = p.play(tl)
    if not logs: return None
    first = logs[0]['move'] - p.base
    start = next((f for f, m in p.changes if m == first + p.base), None)
    found = chain(graph, first, steps)
    if start is None or found is None:
        log(f'  hors du graphe (premier coup {first})')
        for pads, moves in alternatives(graph, steps):
            log(f'    existe depuis la garde, direction pave {pads} : coups {moves}')
        return None
    links, steps = found
    want = [first] + [m for m, *_ in links]
    pf0 = press_frames(tl)[0]
    seen_starts = {0: start}
    for attempt in range(4):
        presses_at, s = [pf0], seen_starts[0]
        for k, (move, ws, lo, hi, auto) in enumerate(links):
            if auto:                                  # la suite part d'elle-meme
                s = seen_starts.get(k + 1, s + hi); continue
            press = max(s + min(max(ws, 1) + 1, max(lo, 1)), presses_at[-1] + PRESS + 1)
            presses_at.append(press)
            s = seen_starts.get(k + 1, max(s + hi, press + 1))
        gaps = [b - a - PRESS for a, b in zip(presses_at, presses_at[1:])] + [GAP]
        tl = timeline(steps, gaps)
        moves = [m['move'] - p.base for m in p.play(tl)]
        # Departs observes des coups de la suite, dans l'ordre, sans retour a la garde.
        got, j = {}, 0
        for f, m in p.changes:
            if m == IDLE and j: break
            if j < len(want) and m == want[j] + p.base: got[j] = f; j += 1
        if j == len(want):
            log(f'  delais {gaps}, {len(moves)} coups {moves} (calcul, {attempt + 1} essai(s))')
            return gaps, moves, steps
        seen_starts = {**seen_starts, **got}
    log(f'  calcul refuse : attendu {want}, joue {moves}, changements {p.changes}')
    return None


def fit(p, steps, log):
    """Delais apres chaque appui ; rend (delais, coups) ou None.

    Chaque appui est cale sur l'image ou le coup precedent est journalise
    (le debut de sa fenetre d'enchainement en est proche) : decalages
    croissants, le premier qui enchaine, affine a 2 images pres, plus deux
    images de marge si elles enchainent encore. Trop tard, l'appui lancerait
    le coup isole."""
    n = presses(steps)
    gaps = [GAP] * n
    t0, trials = time.monotonic(), [0]
    def ok(k, gap):
        gaps[k - 1] = gap; trials[0] += 1
        if trials[0] > MAX_TRIALS: return None
        return chained(p, steps, gaps, k)
    logs = chained(p, steps, gaps, 0)
    if not logs:
        log('  premier appui sans coup journalise'); return None
    for k in range(1, n):
        pf = press_frames(timeline(steps, gaps))
        after = lambda o: max(2, logs[k - 1] + o - pf[k - 1] - PRESS)
        tried, found, prev = set(), None, None
        for o in (-30, -20, -12, -6, 0, 6, 12, 20, 30, 45):
            gap = after(o)
            if gap in tried: continue
            tried.add(gap)
            r = ok(k, gap)
            if r: found = (gap, r); break
            prev = gap
        if found is None:
            gaps[k - 1] = GAP
            tl = timeline(steps, gaps)
            log(f'  appui {k + 1} jamais enchaine ; delais {gaps[:k]}, appuis {press_frames(tl)},'
                f' coups {[(m["frame"], m["move"] - p.base) for m in p.play(tl)]},'
                f' garde {p.idle[:1] + [f for a, f in zip(p.idle, p.idle[1:]) if f != a + 1]}')
            return None
        gap, logs = found
        for g in range((prev or 0) + 2, gap, 2):
            if g < 2: continue
            r = ok(k, g)
            if r: gap, logs = g, r; break
        r = ok(k, gap + 2)
        if r: gap, logs = gap + 2, r
        else: gaps[k - 1] = gap
        log(f'  appui {k + 1} : delai {gaps[k - 1]}')
    tl = timeline(steps, gaps)
    moves = [m['move'] - p.base for m in p.play(tl)]
    log(f'  delais {gaps}, {len(moves)} coups {moves} ({trials[0]} essais, {time.monotonic() - t0:.0f} s)')
    return gaps, moves, steps


def probe(key, port=None, only=None, exe=ROOT / 'build-opt-dbg/Tekken_3_Recompiled', command=None, tag=None, dropped=False):
    """<cle> invite, ou 't3:jin' (temoin natif, avec command=...)."""
    OUT.mkdir(parents=True, exist_ok=True)
    native = key.startswith('t3:')
    if native: tens, strings = [(key, command, parse(command))], []
    else: tens, strings = candidates(key)
    result = dict(key=key, combos=[])
    saved = OUT / f'{key}.json'
    keep = set()
    if (only or dropped) and not native and saved.is_file():
        result = json.loads(saved.read_text())       # --only / --dropped : on remplace ces combos-la
        if dropped: keep = {c['command'] for c in result['combos'] if c['moves']}
        result['combos'] = [c for c in result['combos'] if (only and only not in c['name']) or c['command'] in keep]
    guest = None if native else key
    work = RUN / (tag or key.replace(':', '-'))
    g = Game(None, guest, work, port) if port else start(exe, guest, work)
    try:
        p = Probe(g, native)
        graph = None if native else Graph(key)
        log = lambda s: print(s, flush=True)
        for name, cmd, steps in tens + strings[:6]:
            if only and only not in name: continue
            if cmd in keep: continue
            log(f'{key} : {name} [{cmd}]')
            # Le graphe fait foi : hors du graphe, le combo n'existe pas dans le
            # moveset TTT1 (la recherche fit() ne sert qu'aux temoins natifs).
            r = None
            for attempt in range(3 if graph else 1):     # un depart rate (dash, direction) se rejoue
                r = computed(p, graph, steps, log) if graph else fit(p, steps, log)
                if r: break
            how = 'graphe' if r else None
            if not r and graph:
                # Essayes quand meme (demande de l'utilisateur) : d'abord avec la
                # direction de depart sous laquelle le graphe tient la suite (nom
                # ou notation du wiki differents), puis par recherche en jeu.
                for pads, moves in alternatives(graph, steps):
                    first = next(i for i, st in enumerate(steps) if st[1])
                    alt = list(steps); alt[first] = (GAME_DIR[pads[0]], alt[first][1], alt[first][2])
                    log(f'  essai depuis la direction pave {pads[0]}')
                    r = computed(p, graph, alt, log)
                    if r: how = f'depart pave {pads[0]}'; break
                # La recherche en jeu (fit) n'a rien trouve que le graphe n'ait deja
                # dit, a ~7 min par combo : les variantes du wiki (combos.py wiki)
                # la remplacent.
            result['combos'].append(dict(name=name, command=cmd, ten=(name, cmd, steps) in tens,
                                         gaps=r[0] if r else None, moves=r[1] if r else None, how=how,
                                         inputs=timeline(r[2], r[0]) if r else None))
            if not native and not tag: (OUT / f'{key}.json').write_text(json.dumps(result, indent=1))
        g.shot('end.png')
        print(f'{key} : essais {Probe.trials} en {Probe.seconds:.0f} s', flush=True)
    finally:
        g.close()
    return result


def check(key, exe=ROOT / 'build-opt-dbg/Tekken_3_Recompiled', only=None, p2=False):
    """En jeu : COMBO TRAINING s'ouvre-t-il pour l'invite, et la
    demonstration de chaque combo realise-t-elle la liste attendue ?
    (le paquet doit etre dans mods/ttt1 du build)."""
    # --p2 : l'invite en J2 face a Jin, COMBO PLAYER 2 (coups 8192 + 4096 + i).
    work = RUN / f'check-{key}{"-p2" if p2 else ""}'
    player = 1 if p2 else 0
    g = start(exe, key, work, combo=True, player=player)
    actor = ACTOR[player]
    results = []
    try:
        block = g.u32(0x800b8a2c)
        g.w8(block + 0x7b, player)                   # COMBO PLAYER
        g.shot('menu.png')
        g.q(dict(cmd='set_snapshot', slot=0, addr=f'{actor + 0x40:08x}'))
        for c in range(MAX_COMBOS):
            if only and c + 1 not in only: continue
            # Menu COMBO TRAINING : COMBO TYPE (4e ligne) puis OK (1re ligne).
            g.w8(block + 0x7c, c)
            g.tap(held(PAD[3])); g.wait_frames(90)
            g.shot(f'combo{c + 1}.png')
            expected = g.u16(0x800b8ce4)
            if not expected or expected > MAX_MOVES: break
            want = [g.u16(0x800b8ce6 + 2 * i) for i in range(expected)]
            g.wait_frames(60)
            # La demonstration part de l'etat du combattant : attendre la garde
            # (apres Crouching Spin Kicks, Kunimitsu est encore retourne).
            end = g.frame() + 300
            while g.u16(actor + 0xa0) != IDLE and g.frame() < end: g.wait_frames(5)
            g.wait_frames(20)
            f0 = g.frame()
            g.route([(4, held(0)), (6, NONE)])           # PLAY = SELECT
            # Le journal est efface a la fin de la demonstration : le lire pendant.
            got, end = [], g.frame() + 400
            while g.frame() < end:
                r = g.rd(0x800b8ce0, 4 + 100)
                n = min(int.from_bytes(r[:4], 'little'), 50)
                log = [int.from_bytes(r[4 + 2 * i:6 + 2 * i], 'little') for i in range(expected + 1, n)]
                if len(log) > len(got): got = log
                time.sleep(.05)
            changes, prev = [], None
            for f in range(f0, g.frame()):
                try: r = bytes.fromhex(g.q(dict(cmd='read_frame_ram', frame=f, addr=f'{actor + 0xa0:08x}', len=2))['hex'])
                except Exception: continue
                m = int.from_bytes(r, 'little')
                if m != prev: changes.append((f - f0, m - BASE_ID if m >= BASE_ID else -m)); prev = m
            # La demonstration joue-t-elle toute la liste, dans l'ordre ?
            played = [m + BASE_ID for f, m in changes if m >= 0]
            it = iter(played)
            ok = all(any(m == x for x in it) for m in want)
            results.append(dict(combo=c + 1, want=want, played=played, ok=ok))
            print(f'{key} combo {c + 1} : {"OK" if ok else "ECHEC"}, attendu {[m - BASE_ID for m in want]},'
                  f' joue {[m - BASE_ID for m in played]}', flush=True)
            g.tap(held(3)); g.wait_frames(60)            # Start : retour au menu du mode
            g.shot(f'combo{c + 1}-menu.png')
    finally:
        g.close()
    return results


# ---------------------------------------------------------------- paquet
def chosen(key):
    r = json.loads((OUT / f'{key}.json').read_text())
    ok, seen = [], set()
    for c in r['combos']:
        # Deux notations du wiki peuvent mener a la meme suite (Lee : Laser Edge
        # Machine Gun Kick et Laser Edge Kick Combo) : un seul combo.
        if c['moves'] and len(c['moves']) >= 2 and tuple(c['moves']) not in seen:
            seen.add(tuple(c['moves'])); ok.append(c)
    tens = [c for c in ok if c['ten']]
    short = sorted((c for c in ok if not c['ten']), key=lambda c: len(c['moves']))
    return (short[:max(2, MAX_COMBOS - len(tens))] + tens)[:MAX_COMBOS]


def pack(key):
    out = []
    for c in chosen(key):
        tl = [tuple(e) for e in c['inputs']]
        moves = c['moves'][:MAX_MOVES]
        if len(tl) > MAX_INPUTS: continue
        out.append(struct.pack('<HH', len(tl), len(moves)) +
                   b''.join(struct.pack('<BBH', b, d, n) for b, d, n in tl) +
                   b''.join(struct.pack('<H', m) for m in moves))
    return struct.pack('<H', len(out)) + b''.join(out), len(out)


def donors(guest, quiet=False):
    """Combos des movesets que `guest` peut prendre (Tetsujin, Unknown) : un
    paquet de donneur identique a celui d'un invite deja releve en reprend le
    paquet de combos ; rend les cles encore a sonder."""
    import hashlib
    md5 = lambda f: hashlib.md5(f.read_bytes()).hexdigest()
    folder, prefix = pack_prefix(guest)
    name = prefix[:-5]
    own = {}
    for d in WORK.iterdir():
        f = d / 'guest' / f'{d.name.capitalize()}-TTT1-combat.jmv'
        if f.is_file() and (d / 'guest' / f'{d.name.capitalize()}-TTT1-combos.bin').is_file():
            own[md5(f)] = d / 'guest' / f'{d.name.capitalize()}-TTT1-combos.bin'
    todo = []
    for f in [folder / f'{prefix}-combat.jmv'] + sorted(folder.glob(f'{name}@*-TTT1-combat.jmv')):
        if not f.is_file(): continue
        src = own.get(md5(f))
        out = f.with_name(f.name.replace('-combat.jmv', '-combos.bin'))
        if src and src != out:
            out.write_bytes(src.read_bytes())
            if not quiet: print(f'{out.name:34s} <- {src.name}')
        elif not src and not out.is_file():
            donor = f.name.split('@')[1].split('-')[0].lower() if '@' in f.name else None
            todo.append(f'{guest}@{donor}' if donor else guest)
    if todo and not quiet: print('a sonder :', ' '.join(todo))
    return todo


def main():
    if len(sys.argv) < 2: sys.exit(__doc__)
    cmd, keys = sys.argv[1], sys.argv[2:]
    if cmd == 'list':
        for key in keys:
            tens, strings = candidates(key)
            for name, c, steps in tens: print(f'10 {name:28s} {c}')
            for name, c, steps in strings: print(f'   {name:28s} {c}')
    elif cmd == 'bench':
        # bench <n> : n jeux sondent Kazuya en meme temps ; debit total en essais / min.
        n = int(keys[0])
        import subprocess
        t0 = time.monotonic()
        kids = [subprocess.Popen([sys.executable, '-u', __file__, 'probe', 'kazuya', f'--tag=bench{i}'],
                                 stdout=subprocess.PIPE, text=True) for i in range(n)]
        outs = [k.communicate()[0] for k in kids]
        wall = time.monotonic() - t0
        trials = sum(int(re.search(r'essais (\d+)', o).group(1)) for o in outs if re.search(r'essais (\d+)', o))
        play = [float(re.search(r'en (\d+) s', o).group(1)) for o in outs if re.search(r'en (\d+) s', o)]
        print(f'{n} jeux : {trials} essais en {wall:.0f} s (demarrages compris), essais seuls {play} s,'
              f' {60 * trials / max(play or [wall]):.1f} essais / min', flush=True)
    elif cmd == 'probe' and any(k.startswith('--jobs=') for k in keys):
        # Un jeu par invite, au plus n a la fois (le tout dans une seule place de slot.py).
        n = next(int(k[7:]) for k in keys if k.startswith('--jobs='))
        rest = [k for k in keys if not k.startswith('--jobs=')]
        todo = [k for k in rest if not k.startswith('--')]
        opts = [k for k in rest if k.startswith('--')]
        import subprocess
        running = []
        while todo or running:
            while todo and len(running) < n:
                key = todo.pop(0)
                running.append((key, subprocess.Popen([sys.executable, '-u', __file__, 'probe', key] + opts)))
            time.sleep(2)
            running = [(k, p) for k, p in running if p.poll() is None]
    elif cmd == 'probe':
        port = next((int(k[7:]) for k in keys if k.startswith('--port=')), None)
        exe = next((Path(k[6:]) for k in keys if k.startswith('--exe=')), ROOT / 'build-opt-dbg/Tekken_3_Recompiled')
        only = next((k[7:] for k in keys if k.startswith('--only=')), None)
        command = next((k[6:] for k in keys if k.startswith('--cmd=')), None)
        tag = next((k[6:] for k in keys if k.startswith('--tag=')), None)
        for key in [k for k in keys if not k.startswith('--')]: probe(key, port, only, exe, command, tag, '--dropped' in keys)
    elif cmd == 'trace':
        # trace <cle> "<commande>" <delai,delai,...> [...] : chaque changement de coup
        key, commands = keys[0], keys[1].split(';')
        g = start(ROOT / 'build-opt-dbg/Tekken_3_Recompiled', key, RUN / f'trace-{key}')
        try:
            p = Probe(g)
            for command, spec in [(c, sp) for c in commands for sp in keys[2:]]:
                gaps = [int(x) for x in spec.split(',')]
                tl = timeline(parse(command), gaps)
                print(command, flush=True)
                logs = p.play(tl)
                print('delais', gaps, 'appuis', press_frames(tl), 'droite = avant', p.side, flush=True)
                print('  changements', p.changes, flush=True)
                print('  journal', [(m['frame'], m['move'] - p.base) for m in logs], flush=True)
        finally:
            g.close()
    elif cmd == 'check':
        only = next(([int(x) for x in k[7:].split(',')] for k in keys if k.startswith('--only=')), None)
        for key in [k for k in keys if not k.startswith('--')]: check(key, only=only, p2='--p2' in keys)
    elif cmd == 'build':
        everything = not keys
        for key in keys or sorted(p.stem for p in OUT.glob('*.json') if p.stem != 'wiki'):
            folder, prefix = pack_prefix(key)
            if not folder.is_dir() or not (OUT / f'{key}.json').is_file(): print(f'{key} : ignore'); continue
            data, n = pack(key)
            (folder / f'{prefix}-combos.bin').write_bytes(data)
            print(f'{key:16s} {n} combos, {len(data)} octets')
        if everything:                               # Tetsujin, Unknown : leurs donneurs
            for guest in sorted({p.parent.parent.name for p in WORK.glob('*/guest/*@*-TTT1-combat.jmv')}):
                donors(guest, quiet=True)
    elif cmd == 'wiki':
        # wiki <cle> ... : pour chaque combo ecarte, la page du coup sur le wiki
        # dit-elle qu'il existe dans TTT pour ce personnage, et sous quelles
        # commandes ? Les variantes sont ajoutees aux candidats (wiki.json).
        import subprocess, urllib.parse
        def page(title):
            q = dict(action='parse', page=title, prop='wikitext', format='json', redirects=1)
            out = subprocess.run(['curl', '-s', '-A', 'Mozilla/5.0', 'https://tekken.fandom.com/api.php?' +
                                  urllib.parse.urlencode(q)], capture_output=True).stdout
            try: return json.loads(out)['parse']['wikitext']['*']
            except Exception: return None
        found = json.loads((OUT / 'wiki.json').read_text()) if (OUT / 'wiki.json').is_file() else {}
        for key in keys:
            r = json.loads((OUT / f'{key}.json').read_text())
            text = (SRC / f'{key}.wiki').read_text()
            name = PAGES.get(key, key.capitalize()).split()[0]
            for c in [c for c in r['combos'] if not c['moves']]:
                target = None
                m = re.search(r'\[\[([^|\]]+)\|\s*' + re.escape(c['command'].strip()) + r'\s*\]\]', text)
                if m: target = m.group(1)
                else:
                    for m in re.finditer(r'\[\[([^|\]]+)(?:\|([^\]]*))?\]\]', text):
                        if (m.group(2) or m.group(1)).strip() == c['name'].strip(): target = m.group(1); break
                w = page(target) if target else None
                if not w: print(f'{key:10s} {c["name"]:34s} page introuvable'); continue
                captions = [g.strip() for g in re.findall(r'\|\s*(TTT[^|\n<]*)', w) if not g.startswith('TTT2')]
                in_ttt = any(g == 'TTT' or name.lower() in g.lower() for g in captions)
                m = re.search(r'\|\s*Command\s*=\s*(.*)', w)
                variants = []
                for v in re.split(r'<br\s*/?>', m.group(1) if m else ''):
                    note = ' '.join(re.findall(r'\(([^)]*)\)', v))
                    v = re.sub(r"\(.*?\)|''", '', v).strip().strip(',')
                    if v and (not note or 'TTT' in note or 'onward' in note or 'TK3' in note):
                        variants.append(v)
                print(f'{key:10s} {c["name"]:34s} TTT : {"oui" if in_ttt else "non"} {captions} ; variantes {variants}')
                if in_ttt:
                    for v in variants:
                        if v != c['command'] and parse(v):
                            found.setdefault(key, []).append(dict(name=c['name'], command=v, ten=c['ten'], page=target))
        (OUT / 'wiki.json').write_text(json.dumps(found, indent=1))
    elif cmd == 'donors':
        # donors <invite> : combos de chaque moveset qu'il peut prendre. Un paquet
        # de donneur identique au paquet d'un invite deja releve en reprend les
        # combos ; les autres (personnages de Tekken 3 pour Unknown) sont a
        # sonder : probe <invite>@<donneur>.
        for guest in keys: donors(guest)
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
