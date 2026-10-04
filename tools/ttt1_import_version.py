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

TTT1_IMPORT_VERSION = 2
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
