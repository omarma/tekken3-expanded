"""Version of what the TTT1 import produces, and how an installed roster catches up.

RULE: any change to the import that changes its output files (a converter fix,
a new piece, a new capture, a retrofit) increments TTT1_IMPORT_VERSION and adds
its entry to UPDATES. Without it, existing installs never get the change: the
setup only imports again when the installed roster is older than this version.

tools/ttt1_setup.py writes the stamp (import-version.txt) into
workspace/ttt1-import/roster once a full import is staged; the build copies the
roster, stamp included, to build-release/mods/ttt1. A roster without a stamp
predates the stamp: version 0.

Kept free of other imports: launcher/setup_backend.py reads it at every start.
"""
from pathlib import Path

TTT1_IMPORT_VERSION = 13
STAMP = 'import-version.txt'

# Update steps (implemented in tools/ttt1_setup.py, update_step): name ->
# (needs, what the setup log and window say). needs 'roster': works on the
# roster alone, so on a copy of build-release/mods/ttt1 once workspace/ is
# deleted; 'workspace': needs the import's work files (the ROM regions and the
# captures under workspace/ttt1-import), then the roster is staged again.
STEPS = {
    'hands': ('roster', "Guests' hand poses"),
    'devil-jin': ('workspace', "Devil Jin's model and moves"),
    'panda-tiger': ('workspace', "Panda's and Tiger's portraits"),
    'devil-kick': ('workspace', "Devil's Kick costume (purple model)"),
    'accessories': ('workspace', "Guests' tails, hair and other swinging pieces"),
    'tarzan-crash': ('workspace', "Event scripts: the Jacks' Tarzan crash, Heihachi's"),
    'jin-omen': ('workspace', "Jin's Omen (moves and Devil mark)"),
    'hand-fists': ('roster', "Guests' fists (Baek, Lee, Armor King, Ganryu)"),
    'mist': ('roster', "The poison mist of Nina's, Anna's and Yoshimitsu's TTT1 moves"),
    'half-welds': ('workspace', "Guests' joints (welds on whole vertices)"),
    'unknown-wolf': ('workspace', "Unknown's wolf spirit and its glow"),
    'hit-effect-64': ('workspace', "Strong-hit effects in 64 x 64 (TTT Hitspark)"),
    'native-limbs': ('roster', "Ogre's and True Ogre's left-arm and horn hits (ws2, WS f+2 sparks)"),
    'unknown-hilt': ('workspace', "The hilt of Unknown's blade (Yoshimitsu's and Kunimitsu's moves)"),
    'hit-effect-64-more': ('workspace', "Throw spark, knockdown smoke and poison mist in 64 x 64 (TTT Hitspark)"),
}

# What brings a roster from version n - 1 to n: its update steps, in order, or
# None when only a new import does (new MAME captures, a converter change that
# needs them). Each step is idempotent.
UPDATES = {
    # 1: the first stamped import. Since v1.1.3: TTT1 movesets of Kuma, Ogre,
    # Gun Jack and True Ogre and Unknown's final-fight spark (new captures),
    # lasers, Jacks haywire, costume faces, Unknown's costume 2 (converter),
    # hands, wings, Panda and Tiger, juggle aliases 0x128B/0x128C (B07),
    # Jack-2's and P.Jack's metallic hit sounds, Lee's thigh welds, Tetsujin's
    # gold model, the whole strong-hit effect with its fade-out (#14).
    # Captures already made are reused.
    1: None,
    # 2: Devil's Kick costume takes the game's own model (253, purple Devil)
    # instead of costume 1's (175), whose UVs missed its texture.
    2: ['devil-kick'],
    # 3: springs of the accessory bones (tails, hair, skirts, coat tails) from
    # the arcade's table, one .acc per costume (F03).
    3: ['accessories'],
    # 4: an event script entry behind the previous one is left out, not the
    # rest of the script (both engines skip it and go on): the Jacks' Tarzan
    # win pose (script 490) ends on its crash, Heihachi's 410 / 411 (B50).
    4: ['tarzan-crash'],
    # 5: Jin's Omen on his TTT1 moves (Force, then 2,2,3): the partner rule
    # kept for his moveset, and the Devil mark for his Tekken 3 face.
    5: ['jin-omen'],
    # 6: the fist is TTT1's 17th hand pose, not the last: Baek, Lee and Ganryu
    # have an 18th, Armor King an 18th and a 19th, an open hand after the
    # progression, and fought with flat hands (convert.hand_steps).
    6: ['hand-fists'],
    # 7: the mist's virtual limb 25 (Nina's Evil Mist, Yoshimitsu's Poison
    # Breath, a shared record of Nina's and Anna's) kept as a marker for T3's
    # own effect limb 25, instead of limb 0 (B65).
    7: ['mist'],
    # 8: a weld on a whole vertex (TTT1 weights 16 and w) became a copy of it in
    # the converter: the joint followed one bone only (Michelle's third costume:
    # her shorts' hem stayed on her hips, B70). The writing row now drops a half
    # of it for the reader, a PS1 8/8 weld, when w >= 5 (convert.half_welds).
    8: ['half-welds'],
    # 9: Unknown's wolf spirit (TTT1 model 114) and its light effects
    # (archive 06), drawn behind her in every fight (F08, GH#42).
    9: ['unknown-wolf'],
    # 10: the strong-hit effect also in TTT1's 64 x 64 (<Name>-TTT1-hiteffect64.hfx),
    # the guests' and Tekken 3's own cast's, drawn from the upper VRAM half by the TTT
    # Hitspark mod; the 32 x 32 pack stays the fallback (F12, GH#112).
    10: ['hit-effect-64'],
    # 11: Ogre's and True Ogre's TTT1 limb 19 (left-arm moves, ws2 and WS f+2
    # among them) read on their Tekken 3 model: Ogre's left hand 6, True Ogre's
    # arm tip 19, not the converted TTT1 model's bone 20 (empty on Ogre: hit and
    # spark at the arena's centre; True Ogre's tail: at his feet). True Ogre's
    # limb 23 (Buffalo Horn, Demon's Feast) stays his horn tip 23, not his hips 0.
    # B106, GH#152.
    11: ['native-limbs'],
    # 12: the hilt of Unknown's glowing blade, which TTT1 draws by code (0x801042B0)
    # on Yoshimitsu's and Kunimitsu's moves: its quads and points from the ROM, its
    # image kept by the texture packer, one .hilt per costume (B107, GH#150).
    12: ['unknown-hilt'],
    # 13: TTT1's throw spark, knockdown smoke and poison mist in 64 x 64 for the
    # TTT Hitspark mod (Throw-, Smoke-, Mist-TTT1-hiteffect64.hfx, F22).
    13: ['hit-effect-64-more'],
}


def read_stamp(folder):
    """The import version of a roster; 0 without a readable stamp."""
    try: return int((Path(folder) / STAMP).read_text(encoding='utf-8').split()[0])
    except (OSError, ValueError, IndexError): return 0


def write_stamp(folder, version=TTT1_IMPORT_VERSION):
    (Path(folder) / STAMP).write_text(f'{version}\n', encoding='utf-8')


def update_steps(installed, current=TTT1_IMPORT_VERSION, updates=None):
    """The steps from `installed` up to `current`, in order and without
    repeats; None when one version on the way needs a new import."""
    updates = UPDATES if updates is None else updates
    steps = []
    for version in range(installed + 1, current + 1):
        more = updates.get(version)
        if more is None: return None
        steps += [s for s in more if s not in steps]
    return steps
