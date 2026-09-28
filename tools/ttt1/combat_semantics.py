"""System 12 -> SLUS-00402 combat data translations.

These are field translations, not a nearest-move/template selection. Addresses
refer to the TTT1 RAM captured at the selector and the Tekken 3 executable,
as used by moves.py.
"""
import struct


def flags(value):
    # Native flags start at bit 8. TTT added a nine-direction posture flag at
    # bit 8 and a flag at bit 21; its translation/root flags moved to 19/20/22.
    low = (value & 0xff) | ((value & 0x7fe00) >> 1)
    return (low << 8) | ((value & 0x180000) << 9) | ((value & 0x400000) << 8)


def properties(ram, pointer):
    """Yield timed property rows, including damage during paired animations.

    Dispatches: TTT 800FBE88; PS1 800458C8. Unsupported tag operations are
    returned separately so the export audit does not hide them.
    """
    out, omitted = [], []
    if not pointer:
        return out, omitted
    for i in range(256):
        frame, op = struct.unpack_from('<HH', ram, (pointer & 0x3fffff)+i*4)
        if not frame:
            return out, omitted
        kind, arg = op >> 8, op & 255
        if kind==5:continue  # The original dispatch entry is a no-op.
        translated = {1:1, 2:2, 3:3, 4:4, 10:6, 11:7, 12:8,
                      13:9, 14:10, 24:11, 25:12, 26:13}.get(kind)
        if 0x1b <= kind < 0x4b:
            group, action = divmod(kind-0x1b, 16)
            if action < 8:
                translated = 0xe+group*16+action
        if kind==0x26:
            translated=0x40  # Jun facial expression, handled by her texture adapter.
        if translated is None:
            omitted.append((frame, kind, arg))
        else:
            out.append((frame, translated << 8 | arg))
    raise ValueError('Unterminated timed property list')


def sound_events(ram, pointer):
    """The two sound dispatchers share their three-halfword event format.

    Category 8 addresses a separate animation-event table, not a sound. It
    must be relocated by the event-table port and is reported independently.
    """
    out, animation_events = [], []
    if pointer:
        for i in range(3):
            event = struct.unpack_from('<H', ram, (pointer & 0x3fffff)+i*2)[0]
            if event == 0xffff:
                break
            if event >> 12 == 8:
                animation_events.append(event & 0xfff)
                out.append(0x8000 | (1024+(event&0xfff) if event&0xfff else 0))
            else:
                # A record's list is played on hit (T3 80040EA0 / 80041038,
                # TTT1 80114274). T3 applies TTT1's own rules to it, with the
                # same numbers: left unmarked, but its sound goes in the pack
                # (the runtime swaps T3's sample for TTT1's).
                if not 2 <= event >> 12 <= 5 and event >> 12 < 8 and event & 0xfff:
                    SFX_INDEXES.add(event & 0xfff)
                out.append(event)
    return out, animation_events


# TTT1 sounds other than voices. 80113C78 plays table[event & 0xfff]
# (80194CA8, 220 entries); the category only picks the driver channel. T3
# reads the same numbers as its own sounds, so the conversion sets bit 0x800
# of the index in event scripts, which no T3 event carries: the runtime plays
# these from the guest's pack (tools/ttt1/sfx.py, src/tekken3_ttt1_sfx.c).
# Voices (2..5) keep their category routing.
SFX_MARK = 0x800
# Played by the engine itself, not by a move, in TTT1 and in T3 alike (same
# rules, same numbers, different samples): the attack swing (TTT1 80114F78,
# one frame before the active window: 0x6049 or 0x604a), the impact picked by
# limb and damage (8011499C: 0x7041..0x7048, 0x7064, 0x7065, 0x7067, 0x7072),
# guarding (0x704d, 0x704e) and footsteps (0x104f, 0x1053, 0x1054). Every
# pack carries them; the runtime plays TTT1's sample for a guest's moves.
ENGINE_SOUNDS = tuple(range(0x41, 0x49)) + (0x49, 0x4a, 0x4d, 0x4e, 0x4f, 0x53, 0x54, 0x64, 0x65, 0x67, 0x72)
# The lasers' sound, asked for outside the table (tools/ttt1/sfx.py RAW).
LASER_SOUND = 1024
SFX_INDEXES = set()


def mark_sound(event):
    if 2 <= event >> 12 <= 5 or event >> 12 >= 8 or not event & 0xfff:
        return event
    if event & 0xfff >= SFX_MARK:
        raise ValueError(f'TTT1 sound event {event:#06x} beyond the sound table')
    SFX_INDEXES.add(event & 0xfff)
    return event | SFX_MARK


# False (tools/ttt1_import.py): an event script with an unknown entry is cut there.
STRICT_EVENTS=False   # True: an event script ending on an unknown entry stops the conversion
TRUNCATED_EVENTS={}


def event_script(ram, index):
    start=struct.unpack_from('<H',ram,0x1622c+index*2)[0]
    out=[]
    previous=0
    for k in range(256):
        frame,kind,value=struct.unpack_from('<BBH',ram,0x1213c+(start+k)*4)
        if not frame:return out+[0]
        if kind>3 or frame<previous:
            # Generic TTT1 import: keep the script up to the unknown entry (counted).
            if STRICT_EVENTS:raise ValueError('Invalid timed sound script')
            TRUNCATED_EVENTS[index]=k;return out+[0]
        # Kinds 1 and 2 sound an event for the fighter or for its opponent.
        if kind in (1, 2):value=mark_sound(value)
        out.append(frame | kind<<12 | value<<16);previous=frame
    raise ValueError('Unterminated timed sound script')


def reaction(ram, index):
    """Seven angle/pushback fields, followed by fourteen reaction aliases."""
    p = 0x19ff88 + index*56
    return struct.unpack_from('<7I14H', ram, p)


def transition(kind):
    # The PS1 inserts a reserved state before the paired throw states. Later
    # TTT tag states have no counterpart in a solo fight.
    value = kind & 127
    if value <= 30:
        return value | ((kind >> 8) & 0xc0)
    if value in (31,32):
        return 33 | ((kind >> 8) & 0xc0)
    if 33 <= value <= 35:
        # Source-only facing transitions, implemented by the combat adapter.
        return value+12 | ((kind >> 8) & 0xc0)
    if 36 <= value <= 46:
        return value-2 | ((kind >> 8) & 0xc0)
    return None


def native_aliases():
    """Engine entry points, compared in the two resolved alias tables.

    These are semantic alias ranges (walk, guard, getup, win), not animation
    similarity matches. Character attacks enter through the source graph.
    """
    result = {0:4, 1:5, 2:6, 3:56, 6:59, 21:61, 22:62,
              24:63, 26:64, 27:65, 28:65, 29:67,
              0x87:0xb9, 0x88:0xbe, 0xd58:0x1268,
              0xd61:0x128a, 0xd62:0x128d, 0xd63:0x128e,
              0xd64:0x128f, 0xd65:0x1290, 0xd66:0x1291,
              0xd6c:0x129c, 0xd6d:0x129d}
    for start,end,delta in (
        (30,33,38),(36,40,38),(44,49,38),(51,54,38),(56,70,38),
        (0x7f,0x86,0x36),(0x89,0xa6,0x36),(0xa7,0xc8,0x38),
        (0xd1,0xed,0x30),(0xf4,0x106,0x2e),(0x108,0x114,0x2f),
        (0x11b,0x122,0x2f),(0xd06,0xd56,0x511),
        (0xd59,0xd60,0x511),(0xd67,0xd6a,0x52b)):
        result.update({i:i+delta for i in range(start,end+1)})
    return result


def group_at(ram, offset, limit=128):
    """Clips of the contact-exception list starting at `offset` in 0xEC558, or None."""
    clips=[]
    while len(clips)<=limit:
        index=struct.unpack_from('<h',ram,0xec558+(offset+len(clips))*2)[0]
        if index<0:return sorted(set(clips)) if clips else None
        clips.append(struct.unpack_from('<I',ram,0x36768+index*52)[0])
    return None


def motion_groups(ram):
    """Original contact-exception groups and their PS1 group identities.

    TTT added an initial empty list and removed PS1's reserved group 15.
    The shared groups end at 46; the later tag-specific lists differ.
    """
    result={}
    offset=0
    for ordinal in range(47):
        start=offset;clips=[]
        while True:
            index=struct.unpack_from('<h',ram,0xec558+offset*2)[0];offset+=1
            if index<0:break
            clips.append(struct.unpack_from('<I',ram,0x36768+index*52)[0])
        if ordinal:
            result[start]=(ordinal-1 if ordinal<=15 else ordinal,sorted(set(clips)))
    return result
