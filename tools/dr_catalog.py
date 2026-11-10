"""The DR characters' catalogue, dr-characters.txt, from the packs really there.

    python tools/dr_catalog.py <roster>

The game reads dr-characters.txt in the TTT1 catalogue (docs/DR-ROSTER.md,
TIPS 179): one line a DR character, "<key> <TTT1 moveset> <arena> <hands>
<radical>", in the order of CHARACTERS below, which gives the IDs (41, 42...).
A character is listed only when its <Radical>-DR-* pack is complete (PACK,
and the interface files in the format the game checks, load_ui in
src/tekken3_ttt1_roster.c): the game leaves a character out when its
interface fails, but a missing combat file would only show in a fight.

write() is the last step of the DR import (tools/dr_setup.py), after every
pack file: remove() first, write() at the end, so an import cut short leaves
no catalogue naming half-written packs. Without any complete pack there is no
catalogue at all: no DARK RESURRECTION page, the game as without the ISO.
TTT1 is required (guests.txt with its guests): without it, nothing is written.

Kept free of other imports than tools/dr_import_version.py: the launcher reads it.
"""
import os, struct, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dr_import_version as V

# The 12 DR characters, in the order validated for B3 (docs/DR-ROSTER.md section 5):
# key (records, cinematics, Force routes and tints are kept by key, DR-ROSTER section 13),
# radical of the files, then the catalogue columns: the TTT1 moveset the DR moveset
# starts from, the Tekken 3 fighter whose arena it takes, the grip of its hands; '-'
# until the session that makes the character's pack sets them.
CHARACTERS = (
    ('deviljin', 'DevilJin', '9', '9', 'DD'),     # on Jin's TTT1 moveset and in his arena (B3)
    ('asuka', 'Asuka', '-', '-', '-'),
    ('dragunov', 'Dragunov', '-', '-', '-'),
    ('jack5', 'Jack5', '-', '-', '-'),
    ('marduk', 'Marduk', '-', '-', '-'),
    ('marshall', 'Marshall', '-', '-', '-'),      # Marshall Law: `law` and Law-DR-* are Forest Law's
    ('lili', 'Lili', '-', '-', '-'),
    ('raven', 'Raven', '-', '-', '-'),
    ('steve', 'Steve', '-', '-', '-'),
    ('christie', 'Christie', '-', '-', '-'),
    ('feng', 'Feng', '-', '-', '-'),
    ('jinpachi', 'Jinpachi', '-', '-', '-'),
)
KEYS = tuple(c[0] for c in CHARACTERS)
NAMES = dict(deviljin='Devil Jin', asuka='Asuka', dragunov='Dragunov', jack5='Jack-5', marduk='Marduk',
             marshall='Marshall Law', lili='Lili', raven='Raven', steve='Steve', christie='Christie',
             feng='Feng', jinpachi='Jinpachi')
# A complete pack: the files a TTT1 guest must have (tools/ttt1_stage_roster.py FILES),
# with the DR suffix on both sides (interface and data).
PACK = ('ui.jui', 'name.4bpp', 'label.txt', 'arcade-P1.3dm', 'arcade-P1.relocs', 'arcade-P1.tim',
        'combat.jmv', 'tables.jst', 'idle.poses', 'hiteffect.tim')
# load_ui_pack: the five images' sizes; load_ui: the name bitmap's width.
UI_IMAGES = ((126, 252), (32, 68), (32, 58), (32, 34), (32, 29))
NAME_MAX_HALFWORDS = 19


def ttt1_ready(roster):
    """The TTT1 guests' catalogue is there with at least one guest."""
    p = Path(roster) / 'guests.txt'
    try: return any(l.split() for l in p.read_text(encoding='utf-8').splitlines())
    except OSError: return False


def ui_problem(data):
    """Why a -ui.jui would fail the game's check (load_ui_pack), or None."""
    if len(data) < 56: return 'too short'
    magic, version, count, size = struct.unpack_from('<4I', data)
    if magic != 0x3149554A or version != 1 or count != 5: return 'not a JUI1 pack of 5 images'
    if size != len(data): return f'size {len(data)}, header says {size}'
    for i, (w, h) in enumerate(UI_IMAGES):
        o, n = struct.unpack_from('<2I', data, 16 + i * 8)
        if not (56 <= o <= size and n <= size - o and n == 544 + w * h): return f'image {i}: {n} bytes at {o}'
        if struct.unpack_from('<3I', data, o) != (16, 9, 524) or struct.unpack_from('<2H', data, o + 540) != (w // 2, h):
            return f'image {i}: header'
    return None


def pack_problem(roster, radical):
    """Why <Radical>-DR-* is not a complete pack, or None."""
    roster = Path(roster)
    missing = [s for s in PACK if not (roster / f'{radical}-DR-{s}').is_file()
               or not (roster / f'{radical}-DR-{s}').stat().st_size]
    if missing: return 'missing ' + ', '.join(f'{radical}-DR-{s}' for s in missing)
    ui = ui_problem((roster / f'{radical}-DR-ui.jui').read_bytes())
    if ui: return f'{radical}-DR-ui.jui: {ui}'
    name = (roster / f'{radical}-DR-name.4bpp').stat().st_size
    if name % 32 or name // 32 > NAME_MAX_HALFWORDS: return f'{radical}-DR-name.4bpp: {name} bytes'
    if not (roster / f'{radical}-DR-label.txt').read_text(encoding='utf-8', errors='replace').strip():
        return f'{radical}-DR-label.txt: empty'
    return None


def lines(roster, columns=None):
    """The catalogue's lines for the complete packs, in CHARACTERS order.
    columns: {key: (moveset, arena, hands)} over the table's (test packs)."""
    out = []
    for key, radical, *cols in CHARACTERS:
        if pack_problem(roster, radical) is None:
            out.append(' '.join([key, *((columns or {}).get(key) or cols), radical]))
    return out


def listed(roster):
    """The keys dr-characters.txt lists now."""
    try: text = (Path(roster) / V.CATALOG).read_text(encoding='utf-8')
    except OSError: return []
    return [l.split()[0] for l in text.splitlines() if l.split()]


def remove(roster):
    """No catalogue while packs are written (write() puts it back)."""
    for name in (V.CATALOG, V.CATALOG + '.new'):
        try: (Path(roster) / name).unlink()
        except FileNotFoundError: pass


def write(roster, columns=None):
    """dr-characters.txt for the complete packs, written whole then renamed;
    none without one. Returns the keys listed."""
    roster = Path(roster)
    if not ttt1_ready(roster): raise SystemExit(f'{roster}: no TTT1 guests (guests.txt): the DR characters need them')
    text = lines(roster, columns)
    if not text:
        remove(roster); return []
    new = roster / (V.CATALOG + '.new')
    new.write_text('\n'.join(text) + '\n', encoding='utf-8')
    os.replace(new, roster / V.CATALOG)
    return [l.split()[0] for l in text]


def missing(roster):
    """What this checkout's DR import makes and the roster lacks: natives
    (V.NATIVES) without their DR moveset, characters (V.CHARACTERS) not in the
    catalogue. Names for the player, empty when complete."""
    roster = Path(roster)
    try: natives = [l.split() for l in (roster / 'natives.txt').read_text(encoding='utf-8').splitlines()]
    except OSError: natives = []
    gone = [f'{k.capitalize()} (DR moveset)' for k in V.NATIVES
            if not any(len(f) == 4 and f[1] == k and f[3] == 'dr' for f in natives)
            or not (roster / f'{k.capitalize()}-DR-combat.jmv').is_file()]
    have = listed(roster)
    return gone + [NAMES.get(k, k) for k in V.CHARACTERS if k not in have]


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('roster', type=Path)
    a = ap.parse_args()
    keys = write(a.roster.resolve())
    for key, radical, *_ in CHARACTERS:
        # A pack begun but not complete (none at all is the usual case: not made yet).
        if key not in keys and any(a.roster.glob(f'{radical}-DR-*')): print(f'{key} left out: {pack_problem(a.roster, radical)}')
    print(f'{V.CATALOG}: {", ".join(keys)}' if keys else f'{V.CATALOG}: no complete DR pack, no catalogue')


if __name__ == '__main__':
    main()
