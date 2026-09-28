#!/usr/bin/env python3
"""Visionneuse d'animations des invites TTT1 : page HTML autonome (telephone).

    python3 tools/ttt1/anim_viewer.py kazuya devil [-o sortie.html]

Pour chaque personnage importe (tools/ttt1_import.py) :
- le modele PS1 converti, chaque sommet rattache a la ligne qui l'a produit ;
- toutes ses animations TTT1 (57 canaux par image) ;
- le graphe de ses coups dans TTT1, chaque transition exclue classee comme le fait
  tools/ttt1/moves.py, et un verdict tag / pas tag avec un niveau de
  confiance pour les animations qui ne sont atteintes que par ces transitions ;
- les coups conserves avec une perte (os de frappe absent, propriete inconnue).

La page contient des donnees du jeu : elle reste locale, ne pas la publier.
"""
import argparse, base64, collections, json, struct, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt1'), str(ROOT / 'tools/ttt1/model')]
import numpy as np
import anim_model as A
import moves as cjm
import combat_semantics as solo
from motion import decode

SENT = 0x8009374c
CAPTURES = ROOT / 'workspace/ttt1-import/captures'
BANK = ROOT / 'workspace/ttt1-import/ttt1/bankedroms.bin'

# categorie d'exclusion -> (verdict, confiance %, explication)
VERDICT = {
    'tag_input': ('tag', 90, "entree de la touche Tag (bit 0x4000 de la commande)"),
    'partner_transition': ('tag', 85, "condition sur le partenaire ou transition de relais"),
    'partner_recovery': ('tag', 80, "fin d'animation qui demande l'echange de partenaire"),
    'round_controller': ('pas tag', 90, "signal de defaite du round TTT1, remplace par celui de Tekken 3"),
    'unknown_condition': ('inconnu', 30, "condition TTT1 sans equivalent PS1 connu"),
    'special_input': ('pas tag', 55, "commande speciale non convertie"),
    'input_sequence': ('pas tag', 60, "sequence d'entree hors des bornes du convertisseur"),
    'transition_type': ('inconnu', 40, "type de transition non converti"),
}


def classify(cmd, req, kind, conditions):
    """Meme ordre de tests que cancels() de moves.py (hors regles d'autres personnages)."""
    if cmd == 0x8000: return 'continuation'            # fin d'animation : suite de la source
    if cmd < 0x8000 and cmd & 0x4000: return 'tag_input'
    if 0x64 <= req & 255 < 0x85 or 0xa7 <= req & 255 < 0xc9 or kind & 0x3f80 or (req >> 8) & 127 in (88, 89, 90, 91, 92):
        return 'partner_transition'
    if (req >> 8) & 127 == 95: return 'round_controller'
    if conditions.get((req >> 8) & 127) is None: return 'unknown_condition'
    if solo.transition(kind) is None: return 'transition_type'
    if cmd >= 0x800f: return None                       # sequence : jugee plus loin
    if cmd >= 0x8000 and cmd not in (0x8001, 0x8002): return 'special_input'
    return None


BTN = ((0x1, '1'), (0x2, '2'), (0x4, '3'), (0x8, '4'))
def command_text(ram, cmd):
    """Commande TTT1 lisible. Boutons : bits 0..3 = 1..4. Directions : hypothese
    (bits de l'octet haut, pave numerique), affichees en hexadecimal."""
    if cmd == 0x8000: return 'fin d animation'
    if cmd >= 0x800f:
        words = []
        for k in range(16):
            v = struct.unpack_from('<H', ram, 0x772 + cmd * 2 + k * 2)[0]; words.append(v)
            if k and not v: break
        steps = []
        for w in words[1:-1]:
            b = '+'.join(n for bit, n in ((0x100, '1'), (0x200, '2'), (0x400, '3'), (0x800, '4')) if w & bit)
            steps.append((f'dir{w & 0xff}' if w & 0xff != 5 else 'N') + (('+' + b) if b else ''))
        return 'sequence ' + ', '.join(steps) + f' (fenetre {words[0]})'
    b = '+'.join(n for bit, n in BTN if cmd & bit)
    d = (cmd >> 8) & 0x3f                              # 0x4000 : touche Tag
    parts = (['Tag'] if cmd & 0x4000 else []) + ([b] if b else [])
    text = '+'.join(parts) or '-'
    if d: text += f' (direction 0x{d:02x}, hypothese)'
    if cmd & 0xf0: text += f' (bits 0x{cmd & 0xf0:02x})'
    return text


def character_graph(ram, moveset, body, start):
    """Transitions du personnage, avant exclusions, a partir de ses coups convertis
    (et, de proche en proche, des animations qu'elles atteignent)."""
    def own(req):
        c = req & 255
        if c in (0, 0xed): return True
        if c == 0xec: return False
        if 1 <= c < 0x22: return c - 1 == moveset
        if 0x22 <= c < 0x43: return c - 0x22 != moveset
        if 0x85 <= c < 0xa7: return c - 0x85 == body
        if 0xc9 <= c < 0xeb: return c - 0xc9 != body
        return None
    aliases = struct.unpack_from('<5515I', ram, 0x2a7350)
    rec = lambda a: struct.unpack_from('<13I', ram, a & 0x3fffff)
    edges = collections.defaultdict(list)              # destination -> [(source, cmd, req, kind)]
    seen = set()
    pending = list(start)
    while pending:
        a = pending.pop()
        if a in seen: continue
        seen.add(a)
        v = rec(a)
        try: rows = list(cjm.cancel_rows(ram, v[3]))
        except ValueError: rows = []
        for cmd, req, param, nxt, kind, window, end in rows:
            if nxt >= 5515: continue
            dst = aliases[nxt]
            if not (0x80000000 <= dst < 0x80400000) or dst == SENT: continue
            if own(req) is False: continue
            edges[dst].append((a, cmd, req, kind))
            if dst not in seen: pending.append(dst)     # suite de la chaine (animations manquantes)
    return aliases, edges


def export(key):
    name = key.capitalize()
    guest = ROOT / f'workspace/ttt1-import/{key}/guest'
    ram = (CAPTURES / f'{key}-select-ram.bin').read_bytes()
    bank = BANK.read_bytes()
    moveset, body, sound, slot = struct.unpack_from('<4H', ram, 0x29ef10)

    # enregistrements convertis (pack de combat)
    pack = (guest / f'{name}-TTT1-combat.jmv').read_bytes()
    n = struct.unpack_from('<I', pack, 12)[0]
    kept = {struct.unpack_from('<I', pack, 32 + i * 16 + 4)[0] for i in range(n)}
    kept_list = [struct.unpack_from('<I', pack, 32 + i * 16 + 4)[0] for i in range(n)]
    aliases, edges = character_graph(ram, moveset, body, kept_list)
    alias_of = collections.defaultdict(list)
    for i, a in enumerate(aliases): alias_of[a].append(i)
    report = json.loads((ROOT / f'workspace/ttt1-import/{key}/import-report.json').read_text())
    limbs = {int(k): v for k, v in report['model'].get('limbs', {}).items()}

    rec = lambda a: struct.unpack_from('<13I', ram, a & 0x3fffff)
    conditions = cjm.CONDITIONS
    entries = {}

    def entry(a, status):
        v = rec(a); src = v[0]
        e = entries.setdefault(a, dict(address=f'{a:08x}', clip=src, frames=bank[src] if src < len(bank) else 0,
                                       aliases=alias_of[a][:6], status=status, notes=[], incoming=[]))
        return e

    # 1. animations manquantes : atteintes mais non converties
    for dst, inc in edges.items():
        if dst in kept: continue
        reasons = collections.Counter()
        e = entry(dst, 'manquante')
        for a, cmd, req, kind in inc:
            cat = classify(cmd, req, kind, conditions)
            if cat is None and cmd >= 0x800f:
                cat = 'input_sequence'
            if cat is None:
                cat = 'kept_source_missing' if a not in kept else 'transition_type'
            reasons[cat] += 1
            if len(e['incoming']) < 8:
                e['incoming'].append(dict(source=f'{a:08x}', source_kept=a in kept, cmd=command_text(ram, cmd),
                                          cond=(req >> 8) & 127, req=req & 255, reason=cat))
        known = {c: k for c, k in reasons.items() if c in VERDICT}
        if not known:
            e['verdict'], e['confidence'], e['why'] = 'inconnu', 20, "atteinte seulement depuis des coups non convertis"
        else:
            top = max(known, key=lambda c: (VERDICT[c][1] * known[c]))
            verdict, conf, why = VERDICT[top]
            if len({VERDICT[c][0] for c in known}) > 1: conf = max(20, conf - 30); why += ' (entrees de natures mixtes)'
            if min(e['aliases'] or [0]) >= 4900: conf = min(99, conf + 5); why += ' ; alias dans la zone propre au tag (>= 4900)'
            e['verdict'], e['confidence'], e['why'] = verdict, conf, why
        e['reasons'] = dict(reasons)

    # suites d'animation : heritent du verdict de leur source manquante
    for _ in range(8):
        for a, e in entries.items():
            if e['status'] != 'manquante' or set(e.get('reasons', {})) - {'continuation', 'kept_source_missing'}: continue
            srcs = [entries.get(int(x['source'], 16)) for x in e['incoming']]
            srcs = [x for x in srcs if x and x.get('verdict') and x.get('why', '').find('suite de') < 0 or x and x.get('verdict') in ('tag', 'pas tag')]
            if not srcs: continue
            best = max(srcs, key=lambda x: x['confidence'])
            e['verdict'], e['confidence'] = best['verdict'], max(20, best['confidence'] - 5)
            e['why'] = f"suite de l'animation {best['address']} (fin d'animation) : meme verdict"

    # 2. coups conserves avec une perte
    for a in kept_list:
        v = rec(a)
        try: _, omitted = solo.properties(ram, v[8])
        except ValueError: omitted = []
        bad = [x for x in struct.pack('<I', v[10]) if x >= 18 and x not in limbs]
        if omitted or bad:
            e = entry(a, 'gardee avec perte')
            if bad: e['notes'].append(f"frappe sur l'os {bad} porte par aucun maillage : la frappe est sautee (ne touche pas)")
            for f, k, arg in omitted: e['notes'].append(f'propriete temporisee 0x{k:02x} (valeur {arg}) a la trame {f} ecartee')
            for b, (s, cmd, req, kind) in [(b, x) for b, lst in edges.items() for x in lst if b == a][:6]:
                e['incoming'].append(dict(source=f'{s:08x}', source_kept=s in kept, cmd=command_text(ram, cmd),
                                          cond=(req >> 8) & 127, req=req & 255, reason='conservee'))

    # 3. toutes les animations du personnage (navigation libre)
    clips = {}
    for a in list(entries):                            # manquantes et gardees avec perte seulement
        src = rec(a)[0]
        if src in clips or not 0 < src < len(bank) or not bank[src]: continue
        frames = [decode(bank, src, f) for f in range(bank[src])]
        clips[src] = base64.b64encode(np.array(frames, dtype='<u2').tobytes()).decode()

    # modele : sommets (ligne, x, y, z) par ligne, triangles, hierarchie
    m = A.load(guest / f'{name}-TTT1-arcade-P1.3dm')
    B = A.bind(m)
    rows = {}
    for r, (L, tris) in B.items():
        rows[r] = dict(slots=[[s[0], *s[1]] if s else None for s in L], tris=tris)
    rowinfo = {r: dict(pos=list(A.row(m, r)[3:6]), parent=A.row(m, r)[6] & 0xff, rot=list(A.row(m, r)[7:10]))
               for r in range(A.nrows(m))}
    return dict(key=key, label=report['label'], keys=dict(moveset=moveset, body=body, sound=sound, slot=slot),
                rows=rows, rowinfo=rowinfo, entries=list(entries.values()), clips=clips)


def sine_table():
    E = (ROOT / 'disc/SLUS_004.02').read_bytes()
    return base64.b64encode(E[0xe8c4 + 0x800:0xe8c4 + 0x800 + 0x2800]).decode()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('characters', nargs='+')
    ap.add_argument('-o', '--out', type=Path, default=ROOT / 'workspace/ttt1-import/animations.html')
    a = ap.parse_args()
    data = dict(sin=sine_table(), chars=[export(k) for k in a.characters])
    html = (Path(__file__).with_name('anim_viewer.html')).read_text()
    a.out.write_text(html.replace('/*DATA*/null', json.dumps(data, separators=(',', ':'))))
    for c in data['chars']:
        st = collections.Counter(e['status'] for e in c['entries'])
        print(c['label'], dict(st), len(c['clips']), 'animations')
    print('->', a.out, f'{a.out.stat().st_size // 1024} Kio')


if __name__ == '__main__':
    main()
