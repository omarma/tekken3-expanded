#!/usr/bin/env python3
"""Devil Jin's moves: TTT1 Jin's moveset with Devil's moves grafted on.

    python3 tools/ttt1_devil_jin_moves.py

TTT1 keeps every character's move records in RAM; a selector capture only
changes the alias table and the keys the rules test. So Jin's capture holds
Devil's records too, and tools/ttt1/moves.py converts them with Devil's
alias table and keys (graft=...). GRAFTS below lists, move by move, the
Devil records added and the Jin record that leads into them.

Sources (tools/ttt1_import.py): Jin's moveset is Unknown's Jin donor
capture (captures/unknown@jin-select-ram.bin, moveset 9), Devil's own
capture (captures/devil-select-ram.bin, moveset 27). Output, next to the
easter-egg model in workspace/ttt1-import/devil-jin/guest:
DevilJin-TTT1-combat.jmv, -tables.jst, -idle.poses (Jin's), -sfx.jus.
"""
import json, shutil, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt1'), str(ROOT / 'tools/ttt1/model')]
WORK = ROOT / 'workspace/ttt1-import'
OUT = WORK / 'devil-jin/guest'
KEYS, ALIASES = 0x29ef00, 0x2a7350
PREFIX = 'DevilJin-TTT1'

# name: (Devil records added, [(Jin record, Devil record whose entries into
# them are copied onto the Jin record, and whether its links back to its own
# slot come too)]). Addresses in TTT1 RAM. Without links, every Devil record
# leading into the move lends its entry to the Jin record in the same alias
# slot (auto_links).
GRAFTS = {
    # f,N,d,d/f+1 then u/f on hit. Devil's Dragon Uppercut 80049ABC carries
    # the link; Jin's own 80049A88 (same alias slot 0x9B, with its ,3 and ,4)
    # gets it, with the early-press buffer back to itself.
    "Heaven's Door": ([0x8006b260], [(0x80049a88, 0x80049abc, True)]),
    # 1+2 (input sequence), from the stance and the walks: laser type 1.
    'Inferno': ([0x8006b5d4], None),
    # u (or u/f, u/b)+1+2: the laser upwards, only against an airborne foe.
    'Air Inferno': ([0x8006b6d8], None),
    # 3+4 (input sequence): flies and fires down ahead (laser type 2); 3+4
    # again within 45 frames turns over (8006B670) into Reverse Devil
    # Blaster (8006B6A4, type 3), which the graft follows by itself.
    'Devil Blaster': ([0x8006b63c], None),
}


def auto_links(root, devil_pack, devil_aliases, jin_aliases, jin_records):
    """(Jin record, Devil record) for each Devil record with an entry into
    `root`: the same record when Jin has it, else Jin's in the same slot."""
    d = devil_pack
    n = struct.unpack_from('<8I', d)[3]
    meta = [struct.unpack_from('<4I', d, 32 + i * 16) for i in range(n)]
    target = next(8192 + i for i, m in enumerate(meta) if m[1] == root)
    links = set()
    for m in meta:
        cp = struct.unpack_from('<14I', d, m[2])[3]
        if not any(struct.unpack_from('<4H', d, cp + k * 12)[3] == target for k in range(m[3])):
            continue
        donor = m[1]
        hosts = {donor} if donor in jin_records else \
            {jin_aliases[k] for k, a in enumerate(devil_aliases) if a == donor and jin_aliases[k] in jin_records}
        if not hosts: raise SystemExit(f'{root:08x}: no Jin record for Devil record {donor:08x}')
        links |= {(h, donor) for h in hosts}
    return sorted(links)


def main():
    import moves as M, convert
    from fmt import load
    jin = (WORK / 'captures/unknown@jin-select-ram.bin').read_bytes()
    devil = (WORK / 'captures/devil-select-ram.bin').read_bytes()
    jin_moveset, jin_body = struct.unpack_from('<2H', jin, KEYS + 0x10)
    devil_moveset, devil_body = struct.unpack_from('<2H', devil, KEYS + 0x10)
    assert (jin_moveset, devil_moveset) == (9, 27), (jin_moveset, devil_moveset)
    records = json.loads((WORK / 'unknown/@jin/motion/manifest.json').read_text())['records']
    bank = (WORK / 'ttt1/bankedroms.bin').read_bytes()
    # Same accessory bones as the Unknown@Jin pack this one extends.
    limbs = convert.limb_map(load(WORK / 'unknown/ttt1.3dm'))
    devil_aliases = struct.unpack_from('<5515I', devil, ALIASES)
    jin_aliases = struct.unpack_from('<5515I', jin, ALIASES)
    # Jin's records as converted without graft (the Unknown@Jin pack).
    plain = (WORK / 'unknown/guest/Unknown@Jin-TTT1-combat.jmv').read_bytes()
    jin_records = {struct.unpack_from('<4I', plain, 32 + i * 16)[1] for i in range(struct.unpack_from('<8I', plain)[3])}
    devil_pack = (WORK / 'devil/guest/Devil-TTT1-combat.jmv').read_bytes()
    links = []
    for name, (roots, explicit) in GRAFTS.items():
        found = explicit or [l for r in roots for l in auto_links(r, devil_pack, devil_aliases, jin_aliases, jin_records)]
        print(f'{name}: entries on {len(found)} Jin records')
        links += found
    graft = dict(aliases=devil_aliases, moveset=devil_moveset, body=devil_body,
                 roots=[a for roots, _ in GRAFTS.values() for a in roots], links=links)
    combat, tables, report = M.convert(jin, bank, records, jin_moveset, jin_body, limbs, graft=graft)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f'{PREFIX}-combat.jmv').write_bytes(combat)
    (OUT / f'{PREFIX}-tables.jst').write_bytes(tables)
    shutil.copyfile(WORK / 'unknown/guest/Unknown@Jin-TTT1-idle.poses', OUT / f'{PREFIX}-idle.poses')
    # Move sounds, grafted moves' included (laser...), replayed from the
    # measured table (tools/ttt1/sfx.py), without MAME.
    import ttt1_import
    capture = WORK / 'captures/unknown@jin-select-ram.bin'
    jin_sound = struct.unpack_from('<3H', jin, KEYS + 0x10)[2]
    ttt1_import.sounds(capture, report['sound_indexes'], jin_sound, OUT, PREFIX.removesuffix('-TTT1'))
    print(f'{PREFIX}: {report["records"]} records, {report["grafted_records"]} from Devil '
          f'({", ".join(GRAFTS)}) -> {OUT}')


if __name__ == '__main__':
    main()
