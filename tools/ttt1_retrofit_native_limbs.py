#!/usr/bin/env python3
"""Retrofit Ogre's and True Ogre's hit limbs in their TTT1 move packs
(Ogre-, Trueogre-TTT1-combat.jmv), without a new import (B106, GH#152).

The natives play their TTT1 moves on their Tekken 3 model, but the import
renumbered TTT1's accessory limbs after the converted TTT1 model: limb 19 of
their left-arm moves (ws2 and WS f+2 among them) became 20, a slot that is
empty on Ogre's model (the hit and its spark at the arena's centre, on the
floor) and True Ogre's tail on his (the spark at his feet). Ogre's 19 is his
left hand 6, as both TTT1 and Tekken 3 read it (0x80041F4C: limb 0x13 of
character 0xE is joint 6); True Ogre's 19 is the tip of his snake arm, bone
19 of his model. True Ogre's limb 23 (Buffalo Horn, the end of Demon's
Feast), which no part of the converted model carries, became 0, his hips:
it is the tip of his horns, joint 2 moved by (800, 0, 600), a point TTT1 and
Tekken 3 (0x80041F4C, 0x8001DC40, character 0x14) both compute as joint 23.
tools/ttt1_import.py now takes them from the natives' "limbs" of
tools/data/ttt1_characters.json. The records are known by their TTT1 address
(the pack's provenance), the same in both packs.

    python3 tools/ttt1_retrofit_native_limbs.py workspace/ttt1-import/roster
"""
import struct, sys
from pathlib import Path

# TTT1 records with limb 19 (limbs 19, 0, 19, 5), every one of Ogre's moveset.
ARM_RECORDS = (0x80043e84, 0x800489ac, 0x800489e0, 0x80066be4, 0x80066e20, 0x80066e54)
# TTT1 records with limb 23 (True Ogre's own): limbs before and after.
HORN_RECORDS = {0x80047388: ((0, 0, 0, 2), (23, 0, 23, 2)),     # Buffalo Horn
                0x80066b14: ((0, 0, 0, 0), (23, 0, 0, 0))}      # Demon's Feast, its last hit


def arm(bone):
    return {a: ((20, 0, 20, 5), (bone, 0, bone, 5)) for a in ARM_RECORDS}


NATIVE = {'Ogre-TTT1-combat.jmv': arm(6), 'Trueogre-TTT1-combat.jmv': {**arm(19), **HORN_RECORDS}}


def retrofit(data, fixes):
    """Rewrites `data` (a v4 combat pack) in place; number of records changed."""
    done = 0
    for i in range(struct.unpack_from('<I', data, 12)[0]):
        _, provenance, rp, _ = struct.unpack_from('<4I', data, 32 + i * 16)
        old, new = fixes.get(provenance, (None, None))
        if old and data[rp + 40:rp + 44] == bytes(old):
            data[rp + 40:rp + 44] = bytes(new); done += 1
    return done


def main(folders):
    for folder in folders:
        for path in sorted(p for p in Path(folder).rglob('*-TTT1-combat.jmv') if p.name in NATIVE):
            data = bytearray(path.read_bytes())
            if retrofit(data, NATIVE[path.name]):
                path.write_bytes(data)
                print(f'  {path.name}: hit limbs on the Tekken 3 model', flush=True)


if __name__ == '__main__':
    main(sys.argv[1:] or ['workspace/ttt1-import/roster'])
