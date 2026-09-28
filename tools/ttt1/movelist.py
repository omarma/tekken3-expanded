#!/usr/bin/env python3
"""Liste des coups (COMMAND LIST de Practice) des invites TTT1.

TTT1 arcade n'a pas de liste des coups : on la reprend du wiki Tekken
(Fandom, pages « <Nom>/Tekken Tag Tournament Movelist ») et on l'ecrit au
format de la liste de Tekken 3, que le runtime pose dans le tampon du joueur.

  python3 tools/ttt1/movelist.py [--fetch] [<cle> ...]

--fetch telecharge d'abord le texte wiki des pages (API MediaWiki, par curl)
dans workspace/ttt1-import/movelists/<cle>.wiki. Sortie :
workspace/ttt1-import/<cle>/guest/<Nom>-TTT1-movelist.bin, puis
tools/ttt1_stage_roster.py la recopie avec l'invite.

Format T3 (tampon de 0x1A0 octets par joueur, J1 en 0x800A3628) : un octet
= nombre d'entrees, puis pour chaque entree « nom\\0 commande\\0 ». Le nom
est en ASCII (au-dela de ~29 caracteres il passe sur deux lignes). Dans la
commande : 0x80..0x87 directions bas-arriere, bas, bas-avant, arriere, avant,
haut-arriere, haut, haut-avant ; +8 = direction maintenue ; 0x90 = neutre ;
0x91 + masque = boutons (1 = bit 0, 2 = bit 1, 3 = bit 2, 4 = bit 3) ; du
texte ASCII s'affiche tel quel avant les icones.
"""
import json, re, subprocess, sys, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'workspace/ttt1-import'
SRC = WORK / 'movelists'
BUFFER = 0x1A0                       # octets par joueur, compte compris
NAME_MAX = 29                        # une ligne
ICONS_MAX = 9                        # largeur d'une ligne de commande
TEXT_MAX = 14

# Page du wiki par invite. Dans TTT1, Angel a les coups de Devil et Alex ceux
# de Roger ; Tetsujin copie un personnage au hasard et n'a pas de liste.
PAGES = {'kazuya': 'Kazuya Mishima', 'kunimitsu': 'Kunimitsu', 'michelle': 'Michelle Chang',
         'baek': 'Baek Doo San', 'armorking': 'Armor King', 'bruce': 'Bruce Irvin',
         'jack2': 'Jack-2', 'lee': 'Lee Chaolan', 'ganryu': 'Ganryu', 'pjack': 'Prototype Jack',
         'devil': 'Devil Kazuya', 'angel': 'Devil Kazuya', 'roger': 'Roger', 'alex': 'Roger',
         'jun': 'Jun Kazama', 'wang': 'Wang Jinrei',
         'unknown': 'Jun Kazama',     # her moveset at the start of a fight is Jun's
         # Movesets of Tekken 3 fighters that Unknown can take (donors only).
         'paul': 'Paul Phoenix', 'law': 'Forest Law', 'lei': 'Lei Wulong', 'king': 'King II',
         'yoshimitsu': 'Yoshimitsu', 'nina': 'Nina Williams', 'hwoarang': 'Hwoarang',
         'xiaoyu': 'Ling Xiaoyu', 'eddy': 'Eddy Gordo', 'jin': 'Jin Kazama', 'julia': 'Julia Chang',
         'bryan': 'Bryan Fury', 'heihachi': 'Heihachi Mishima', 'anna': 'Anna Williams'}
DONOR_ONLY = {'paul', 'law', 'lei', 'king', 'yoshimitsu', 'nina', 'hwoarang', 'xiaoyu', 'eddy',
              'jin', 'julia', 'bryan', 'heihachi', 'anna'}

DIRS = {'d/b': 0, 'd': 1, 'd/f': 2, 'b': 3, 'f': 4, 'u/b': 5, 'u': 6, 'u/f': 7}
MOTIONS = {'qcf': 'd, d/f, f', 'qcb': 'd, d/b, b', 'hcf': 'b, d/b, d, d/f, f', 'hcb': 'f, d/f, d, d/b, b'}
PREFIX = [(r'^FC[,+]?\s*', 'Crouching '), (r'^WS[,+]?\s*', 'Rising '), (r'^SS[LR]?[,+]?\s*', 'Sidestep '),
          (r'^(Back to (the )?opponent|BT)[,+]?\s*', 'Back to foe '), (r'^On the back[,+]?\s*', 'Face up ')]


def fetch(key):
    p = dict(action='parse', page=f'{PAGES[key]}/Tekken Tag Tournament Movelist', prop='wikitext',
             format='json', redirects=1)
    out = subprocess.run(['curl', '-s', '-A', 'Mozilla/5.0',
                          'https://tekken.fandom.com/api.php?' + urllib.parse.urlencode(p)],
                         capture_output=True, check=True).stdout
    SRC.mkdir(parents=True, exist_ok=True)
    (SRC / f'{key}.wiki').write_text(json.loads(out)['parse']['wikitext']['*'])


def rows(text):
    """(section, nom, commande) des tableaux wiki, dans l'ordre de la page."""
    section = ''
    for block in re.split(r'^\|-\s*$', text, flags=re.M):
        # Les lignes d'un bloc precedent le titre de section qui le termine.
        cells = [c.strip() for c in re.findall(r'^[!|](?![}\-+])(?!\s*style)(.*)$', block, re.M)]
        name = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]*)\]\]', r'\1', cells[0]).strip() if cells else ''
        if len(cells) >= 2 and name and cells[1]: yield section, name, cells[1]
        for s in re.findall(r'^==+\s*(.*?)\s*==+', block, re.M): section = s


def buttons(spec):
    mask = 0
    for b in spec.split('+'):
        if b not in '1234' or not b: return None
        mask |= 1 << (int(b) - 1)
    return 0x91 + mask if mask != 15 else 0xA0


def command(raw):
    """Octets T3 de la commande, ou None si la notation n'est pas comprise."""
    c = re.sub(r'\([^)]*\)', ' ', raw).replace('[', ' ').replace(']', ' ')
    c = c.replace('~', ',').replace('...', '').strip().rstrip(',')
    c = re.sub(r'\s*\+\s*', '+', c)
    text = ''
    for pat, word in PREFIX:
        m = re.match(pat, c)
        if m: text, c = word, c[m.end():]; break
    m = re.match(r'^During ([A-Za-z\' ]+?)[, ]+(?=[A-Za-z/]*[+,\d]|[dbfuDBFUN](?:/[bfBF])?\b)', c)
    if m:
        text = f'During {m.group(1)} '
        if len(text) > TEXT_MAX: return None
        c = c[m.end():]
    for k, v in MOTIONS.items(): c = re.sub(rf'\b{k}\b', v, c, flags=re.I)
    out = []
    for step in re.split(r'[,\s]+', c.strip()):
        if not step: continue
        m = re.fullmatch(r'(?:([dubfDUBF](?:/[bfBF])?|N)(?:\+|$))?([1-4](?:\+[1-4])*)?', step)
        if not m or not (m.group(1) or m.group(2)): return None
        d, b = m.group(1), m.group(2)
        if d == 'N': out.append(0x90)
        elif d:
            if d.lower() not in DIRS: return None
            out.append(0x80 + DIRS[d.lower()] + (8 if d.isupper() or d[0].isupper() else 0))
        if b:
            code = buttons(b)
            if code is None: return None
            out.append(code)
    if not out or len(out) > ICONS_MAX: return None
    return text.encode('ascii') + bytes(out)


def build(key):
    text = (SRC / f'{key}.wiki').read_text()
    attacks, throws, skipped = [], [], []
    for section, name, raw in rows(text):
        cmd = command(raw)
        if cmd is None: skipped.append((name, raw)); continue
        throw = 'hrow' in section
        if not throw and len(cmd) == 1 and 0x91 <= cmd[0] < 0xA0: continue   # bouton seul
        name = re.sub(r'\s*\(.*?\)', '', name)
        if len(name) > NAME_MAX: name = name[:NAME_MAX].rstrip()
        entry = name.encode('ascii', 'replace') + b'\0' + cmd + b'\0'
        (throws if throw else attacks).append(entry)
    # Comme la liste d'origine : les coups marquants (direction, commande
    # speciale) d'abord, puis les enchainements de boutons, et au plus trois
    # projections a la fin ; chaque groupe garde l'ordre du wiki.
    def special(e):
        cmd = e[e.index(0) + 1:-1]
        return any(c < 0x91 for c in cmd)
    budget, picked = BUFFER - 1, set()
    order = [e for e in attacks if special(e)] + [e for e in attacks if not special(e)]
    for e in throws[:3] + order:
        if len(e) <= budget: picked.add(id(e)); budget -= len(e)
    chosen = [e for e in attacks if id(e) in picked] + [e for e in throws[:3] if id(e) in picked]
    return bytes([len(chosen)]) + b''.join(chosen), len(attacks) + len(throws), skipped


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    keys = args or [k for k in PAGES if k not in DONOR_ONLY]
    table = json.loads((ROOT / 'tools/data/ttt1_characters.json').read_text())['characters']
    for key in keys:
        # A guest whose moveset changes (Unknown): one list per donor,
        # <Name>@<Donor>-TTT1-movelist.bin, shown with that donor's moves.
        for donor in table.get(key, {}).get('donors', []) if key in args else []:
            if donor not in PAGES: continue
            try:
                if '--fetch' in sys.argv or not (SRC / f'{donor}.wiki').is_file(): fetch(donor)
                data, total, skipped = build(donor)
            except (KeyError, ValueError) as e:
                print(f'{key}@{donor} : pas de liste ({e!r})'); continue
            guest = WORK / key / 'guest'
            if guest.is_dir():
                (guest / f'{key.capitalize()}@{donor.capitalize()}-TTT1-movelist.bin').write_bytes(data)
                print(f'{key}@{donor:10s} {data[0]:2d} entrees sur {total} lisibles')
        if key not in PAGES: continue
        if '--fetch' in sys.argv or not (SRC / f'{key}.wiki').is_file(): fetch(key)
        data, total, skipped = build(key)
        guest = WORK / key / 'guest'
        if not guest.is_dir(): print(f'{key} : pas importe, ignore'); continue
        (guest / f'{key.capitalize()}-TTT1-movelist.bin').write_bytes(data)
        print(f'{key:10s} {data[0]:2d} entrees sur {total} lisibles, {len(data)} octets,'
              f' {len(skipped)} notations ignorees')


if __name__ == '__main__':
    main()
