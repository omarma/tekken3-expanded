"""Version of what the Dark Resurrection import produces (tools/dr_setup.py), apart from the TTT1 import's.

RULE: any change to the DR import that changes its output files (the animation
converter, the pack builder, a moveset or a character added, the catalogue)
increments DR_IMPORT_VERSION. A change of the DR import does not ask for a new
TTT1 import, nor the other way round (tools/ttt1_import_version.py,
docs/DR-ROSTER.md section 5).

tools/dr_setup.py writes the stamp (dr-import-version.txt) into the TTT1
catalogue last, after its <Name>-DR-* files and dr-characters.txt; a catalogue
with an older stamp, or none, is imported again.

Kept free of other imports, like tools/ttt1_import_version.py.
"""
from pathlib import Path

DR_IMPORT_VERSION = 21             # 2: <Name>-DR-camera.txt (DR's move cameras)
                                   # 3: DR's strong-hit effect on each attack record (byte 47)
                                   # 4: <Name>-DR-movelist.bin (COMMAND LIST from the Tekken wiki's DR page)
                                   # 5: dr-characters.txt, the DR characters' catalogue (C2 S5, tools/dr_catalog.py);
                                   #    on wip/dr/a4-jin, Jin's DR moveset (A4)
                                   # 6: <Radical>-DR-ui.jui, -name.4bpp, -label.txt of the 12 DR characters (C3, tools/psp/dr_ui.py);
                                   #    on wip/dr/a4-jin, A4's review of Jin's moves and <Name>-DR-reach.txt
                                   # 7: the two lines merged in B3 (wip/dr/b3-devil-jin): the higher + 1
                                   # 8: the DR portraits without their red glow (C3 bis, dr_ui.without_halo)
                                   # 9: the DR portraits sharpened after the bust's enlargement (C3 bis, dr_ui.sharpen)
                                   # 10: five DR selector tiles framed again (C3 bis, "tile" in tools/psp/data/dr_ui.json)
                                   # 11: four more tiles framed again; Marshall Law's plate and label LAW (C3 bis)
                                   # 12: the DR portraits stored 1.30 times narrower, as T3's 368 x 480 mode widens them (dr_ui.PORTRAIT_SQUEEZE)
                                   # 13: copied records of DR ground moves lose their model's push, air window and frame held (dr_pack.air_windows, C4)
                                   # 14: C4 merged under Devil Jin for a Jin test build (test/dr-jin-c4): the higher + 1
                                   # 15: a reaction's knocked-out end lying the other way from DR's fall taken out (dr_pack.ko_lying, J3)
                                   # 16: b+1+2 (Power Stance) charges from afar at its peak; DR's moves going on in one animation go on (J4)
                                   # 17: DR's deaths on the knocked-out victim, at DR's frame (dr_pack.deaths, J5; replaces ko_lying)
                                   # 18: the ukemi at DR's frame on DR's reactions, none where DR has none (dr_pack.ukemi, J6)
                                   # 19: DR's throw cameras drawn among their variants (DRCAM 2, dr_camera.py variants, J7)
                                   # 20: <Name>-DR-combos.bin, COMBO TRAINING's 10 hit combos; Jin's 10 hit combo whole (dr_pack feint, J9)
                                   #     In dev since 1.5.0 (F34): Jin's alone, experimental (NATIVES below);
                                   #     the DR line's next change takes the higher + 1 at its merge
                                   # 21: DR's cries, swings, impacts and timed sounds on the DR moves
                                   #     (<Name>-DR-voices.juv, -sfx.jus; tools/psp/dr_move_sounds.py, F35, dev only)
STAMP = 'dr-import-version.txt'
CATALOG = 'dr-characters.txt'
# The natives that have a DR moveset, in the order they were done (PSP-DR.md A3, A4, A5).
# In dev (1.5.0, F34): Jin alone, experimental; Paul's (A3) waits on the DR line for its turn.
NATIVES = ('jin',)
# The DR characters the import makes from the ISO (keys of tools/dr_catalog.py
# CHARACTERS), in the order they were done: B3 adds deviljin.
CHARACTERS = ()


def read_stamp(roster):
    """The DR import version of a roster; 0 without a readable stamp."""
    try: return int((Path(roster) / STAMP).read_text(encoding='utf-8').split()[0])
    except (OSError, ValueError, IndexError): return 0


def write_stamp(roster, version=DR_IMPORT_VERSION):
    (Path(roster) / STAMP).write_text(f'{version}\n', encoding='utf-8')
