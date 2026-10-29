#!/usr/bin/env python3
"""Prepare the TTT Cinematics feature (src/tekken3_cine_hooks.c): the
Tekken Tag Tournament (PS2) endings and Embu, played by the cinematic engine
(src/tekken3_cine.c) in place of the Arcade's ending movies and of one
Tekken 3 Embu in two in the attract.

    python3 tools/ttt_cinematics.py [--catalogue DIR] [--out DIR] [--ttt-disc DISC]

Each cinematic ships in the repository as its declaration
tools/data/ttt_cinematics/<key>.ending.json and its data <key>.json.gz
(tools/ps2/ttt_to_cine.py, docs/CINE-CONVERT.md). From the player's own TTT1
import this writes, into --out (default build-release/mods/ttt-cinematics,
beside the TTT1 catalogue the game reads):

- Jin's model without the Devil and Devil Jin's without wings, the same
  geometry (tools/ttt1_devil_jin.py, from the import's work files; kept once
  made);
- Jin's red TTT1 lightning (tools/ttt1_hitspark.py, made with the TTT1
  characters; its 64 x 64 is read from the catalogue by the TTT Hitspark mod);
- with --ttt-disc (your Tekken Tag Tournament USA PS2 disc, .cue, .bin or
  .iso), the music of TTT's endings, decoded from it; without it, a piece of
  Tekken 3's own music, decoded from the player's disc (disc/);
- <key>.cine, each cinematic for the engine (docs/CINE-FORMAT.md): poses,
  camera, fades, models, effects, arena and actors in one file;
- triggers.txt, the engine's trigger table (src/tekken3_cine_trigger.c):
  one line per cinematic, its event (the declaration's `trigger`: player 1
  finishes the Arcade, the attract's Embu) and its .cine; and version.txt.
- the old way's leftovers of an earlier version removed (cinematics.txt, the
  ending packs <Key>-TTT1-combat.jmv, <key>.cine.txt, <key>.camera.txt:
  TIPS.md sections 57, 69, 130).

Run again after any new TTT1 import: Jin's models come from its work files.
Game data: everything written stays out of the repository.

RULE: a new cinematic, or any change of what this writes, increments
CINEMATICS_VERSION. The setup then runs this step again on its own (seconds,
offline: no new TTT1 import unless a new piece needs the import's work files).
"""
import argparse, gzip, hashlib, json, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/ttt1'))       # glyphs (t3_music)

CINEMATICS_VERSION = 18
STAMP = 'version.txt'
DATA = ROOT / 'tools/data/ttt_cinematics'
WORK = ROOT / 'workspace/ttt1-import'
MODELS = {'JinPlain': ['--plain', '--eyes'], 'DevilJinEnd': ['--wings', 'none', '--eyes']}
EFFECT = 'Jin-TTT1-hiteffect.tim'
# The endings converted by tools/ps2/ttt_to_cine.py: one declaration file
# each (<key>.ending.json: arena, dark, trigger, actors and costumes), the
# whole entry, beside its data. A file per ending, not a line here: the
# sessions converting endings side by side never touch the same lines.
CONVERTED = {p.name[:-len('.ending.json')]: json.loads(p.read_text(encoding='utf-8'))
             for p in sorted(DATA.glob('*.ending.json')) if (DATA / (p.name[:-len('.ending.json')] + '.json.gz')).is_file()}

# The music of TTT's in-engine endings: headerless PS-ADPCM in TEKKEN.BIN,
# stereo interleaved by 1 024-byte blocks, 44 100 Hz, disc sectors 110 777 to
# 111 953 of SLUS-20001 (endings-release: tools/ps2/ttt_music.py).
MUSIC = (110777, 111953, '1c52abba38b4f5ff5d3aa4445dcaab2ae988ee8dca82c619cd1ccc6f5329b082')


# Without TTT's music: Tekken 3's XA stream FALLBACK_XA (a row of the XAS
# table, tools/XAS_TOOL.md) from FALLBACK_FROM seconds on, from the player's
# disc (the user's choice, 2026-10-03).
FALLBACK_XA, FALLBACK_FROM = 44, 73
T3_DISC = ROOT / 'disc'


def read_stamp(folder):
    """The cinematics version a folder was prepared at; 0 without one."""
    try: return int((Path(folder) / STAMP).read_text().split()[0])
    except (OSError, ValueError, IndexError): return 0


def xa_decode(sectors):
    """Raw 2 352-byte XA sectors, 4-bit stereo at 37 800 Hz, into int16 (n, 2)."""
    import numpy as np
    K0, K1 = (0, 60, 115, 98), (0, 0, -52, -55)
    data = np.frombuffer(b''.join(s[24:24 + 18 * 128] for s in sectors), np.uint8).reshape(-1, 128)
    out = np.empty((len(data) * 4, 28, 2), np.int16)      # 4 units a channel a group
    prev = [[0, 0], [0, 0]]
    for g, grp in enumerate(data):
        words = grp[16:].reshape(28, 4)
        for unit in range(8):
            ch, head = unit & 1, int(grp[4 + unit])
            shift, f = head & 15, (head >> 4) & 3
            nib = ((words[:, unit >> 1] >> (4 * (unit & 1))) & 15).astype(np.int32)
            raw = ((np.where(nib >= 8, nib - 16, nib) << 12) >> shift).tolist()
            s1, s2 = prev[ch]; a, b = K0[f], K1[f]
            row = out[g * 4 + (unit >> 1), :, ch]
            for j, v in enumerate(raw):
                v += (s1 * a + s2 * b + 32) >> 6
                v = -32768 if v < -32768 else 32767 if v > 32767 else v
                row[j] = v; s2, s1 = s1, v
            prev[ch] = [s1, s2]
    return out.reshape(-1, 2)


def t3_music(out, row=FALLBACK_XA, seconds=FALLBACK_FROM, name='t3-music.pcm'):
    """Tekken 3's XA stream `row` from `seconds` on, at 44 100 Hz, raw 16-bit stereo PCM."""
    import numpy as np, struct
    exe = (T3_DISC / 'SLUS_004.02').read_bytes()
    start, end, channel = struct.unpack_from('<3I', exe, 0x15578 + 12 * row)
    from glyphs import data_track          # track 1 as disc/'s cue names it
    with data_track().open('rb') as f:
        def sector(n): f.seek((604 + n) * 2352); return f.read(2352)
        pcm = xa_decode([sector(n) for n in range(start + channel, end + channel + 1, 8)])[seconds * 37800:]
    t = np.arange(int(len(pcm) * 44100 / 37800)) * (37800 / 44100)
    pcm = np.stack([np.interp(t, np.arange(len(pcm)), pcm[:, c]) for c in (0, 1)], 1)
    (out / name).write_bytes(pcm.round().astype('<i2').tobytes())


def music_files(e):
    """A cinematic's music file and its Tekken 3 fallback: the endings' piece,
    or a piece of its own (the declaration's "music": the Embu's)."""
    m = e.get('music')
    return (m['file'], m['fallback_file']) if m else ('ending-music.pcm', 't3-music.pcm')


def own_music(e, disc, out):
    """A declaration's own piece ("music": TEKKEN.BIN sectors, their sha256),
    decoded from the TTT disc as the endings' piece is; None on another disc."""
    import numpy as np
    m = e['music']
    path, size, offset = disc_sectors(disc)
    raw = bytearray()
    with path.open('rb') as f:
        for n in range(*m['sectors']):
            f.seek(n * size + offset); raw += f.read(2048)
    if hashlib.sha256(raw).hexdigest() != m['sha256']: return None
    pairs = len(raw) // 2048
    left = b''.join(raw[i * 2048:i * 2048 + 1024] for i in range(pairs))
    right = b''.join(raw[i * 2048 + 1024:(i + 1) * 2048] for i in range(pairs))
    (out / m['file']).write_bytes(np.stack([decode(left), decode(right)], 1).tobytes())
    return out / m['file']


def models(out):
    """Jin's model and Devil Jin's without wings, with their faces (the
    cinematics' eyes), once (they need the import's work files, gone after the
    setup's "free up disk space")."""
    for name, args in MODELS.items():
        if all((out / f'{name}-TTT1-arcade-P1.{ext}').is_file() for ext in ('3dm', 'relocs', 'tim', 'face')): continue
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable, ROOT / 'tools/ttt1_devil_jin.py', *args, '--out', tmp], check=True)
            for ext in ('3dm', 'relocs', 'tim', 'face'):
                shutil.copyfile(Path(tmp) / f'Jin-TTT1-arcade-P1.{ext}', out / f'{name}-TTT1-arcade-P1.{ext}')


def disc_sectors(disc):
    """(bin file, sector size, data offset) of a .cue, .bin (2 352-byte
    sectors) or .iso (2 048)."""
    disc = Path(disc)
    if disc.suffix.lower() == '.cue':
        line = next(l for l in disc.read_text(errors='replace').splitlines() if l.strip().upper().startswith('FILE'))
        disc = disc.parent / line.split('"')[1]
    with disc.open('rb') as f: sync = f.read(12)
    raw = sync == b'\0' + b'\xff' * 10 + b'\0'
    return disc, (2352 if raw else 2048), (24 if raw else 0)


def decode(raw):
    """PS-ADPCM, 16-byte frames of 28 samples, into int16."""
    import numpy as np
    F0, F1 = (0, 60, 115, 98, 122), (0, 0, -52, -55, -60)
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 16)
    shift = (fr[:, 0] & 15).astype(np.int32); shift[shift > 12] = 9
    flt = np.minimum(fr[:, 0] >> 4, 4)
    nib = np.empty((len(fr), 28), np.int32)
    nib[:, 0::2] = fr[:, 2:] & 15; nib[:, 1::2] = fr[:, 2:] >> 4
    s = (np.where(nib >= 8, nib - 16, nib) << 12) >> shift[:, None]
    out = np.empty(len(fr) * 28, np.int16); h1 = h2 = 0; k = 0
    for i in range(len(fr)):
        a, b = F0[flt[i]], F1[flt[i]]
        for v in s[i].tolist():
            v += (h1 * a + h2 * b + 32) >> 6
            v = -32768 if v < -32768 else 32767 if v > 32767 else v
            out[k] = v; k += 1; h2 = h1; h1 = v
    return out


def music_data(disc):
    """The endings' music's sectors on `disc`, None on another disc."""
    path, size, offset = disc_sectors(disc)
    raw = bytearray()
    with path.open('rb') as f:
        for n in range(MUSIC[0], MUSIC[1]):
            f.seek(n * size + offset); raw += f.read(2048)
    return raw if hashlib.sha256(raw).hexdigest() == MUSIC[2] else None


def music_found(disc): return music_data(disc) is not None


def music(disc, out):
    """The endings' music as raw 16-bit stereo PCM (a .cine's `music`)."""
    import numpy as np
    raw = music_data(disc)
    if raw is None:
        raise ValueError(f'{disc}: not Tekken Tag Tournament USA (SLUS-20001) for PS2, the music was not found')
    block, pairs = 1024, len(raw) // 2048
    left = b''.join(raw[i * 2048:i * 2048 + block] for i in range(pairs))
    right = b''.join(raw[i * 2048 + block:(i + 1) * 2048] for i in range(pairs))
    (out / 'ending-music.pcm').write_bytes(np.stack([decode(left), decode(right)], 1).tobytes())


def effect(out):
    # jin/: the old Jin option's; once workspace/ is freed, the copy already in `out` stays.
    for source in (WORK / 'hitspark' / EFFECT, WORK / 'jin' / EFFECT):
        if source.is_file():
            shutil.copyfile(source, out / EFFECT); return
    if not (out / EFFECT).is_file():
        raise ValueError(f"Jin's red lightning is missing: run tools/ttt1_hitspark.py (made with the TTT1 characters)")


def converted_cine(key, e, data, out):
    """A converted ending as a .cine file: its frames are the PS2 script's,
    everything as tools/ps2/ttt_to_cine.py found it (docs/CINE-CONVERT.md)."""
    turn = lambda c: [-c[2], c[1], c[0], -c[5], c[4], c[3]]   # the camera turned as the actors are
    n = data['length']
    lines = ['cine 1', f'name {key}', f'length {n}', f"arena {e['arena']}", f"dark {e['dark']}"]
    lines += [f"actor {i} {a['cast']} {a['costume']}" for i, a in enumerate(data['actors'])]
    lines += [f"swap {i} {w['cast']} {w['costume']} {w['t']}" for i, a in enumerate(data['actors']) for w in a.get('swaps', [])]
    # Model files of an actor's first character, then of each swap's (a
    # segment's first step is the geometry its swap loads), its lightning pack
    # and the strong-hit light; the frames it is not drawn (the Embu's
    # "hide_idle": hide at a span's first frame, show after its last).
    for i, a in enumerate(data['actors']):
        steps = list(a.get('models', [])) + [m for w in a.get('swaps', []) for m in w.get('models', [])]
        lines += [f'model {i} {p} {t}' for p, t in steps]
        if a.get('effect'): lines.append(f"effect {i} {a['effect']}")
        for x, y in a.get('hidden', []):
            lines.append(f'hide {i} {x}')
            if y + 1 < n: lines.append(f'show {i} {y + 1}')
    # A TTT arcade stage drawn instead of the arena, and its storm's lightning.
    if data.get('ttt_stage') is not None:
        lines.append(f"ttt-stage {data['ttt_stage']}" + (f" {data['ttt_courtyard']}" if data.get('ttt_courtyard') else ''))
    lines += [f"storm {s[0]} {s[1]}{' quiet' if s[2:] and s[2] else ''}" for s in data.get('storms', [])]
    lights = {a['light'] for a in data['actors'] if a.get('light')}
    if lights: lines.append(f'light {sorted(lights)[0]}')
    # The script's fades; a level other than the image's is held until the
    # next fade (white until a fade from white, black to the end).
    fades = sorted(data['fades'])
    for k, (a, b, x, y) in enumerate(fades):
        lines.append(f'fade {a} {b} {x} {y}')
        nxt = fades[k + 1][0] if k + 1 < len(fades) else n + 1000
        if y and nxt > b: lines.append(f'fade {b} {nxt} {y} {y}')
    if data.get('music') is not None:
        own, fallback = music_files(e)
        if (out / own).is_file(): lines.append(f"music {own} {data['music']}")
        lines.append(f"music-fallback {fallback} {data['music']}")
    lines.append(f"camera {data['first']} {len(data['camera'])}")
    lines += [' '.join(map(str, turn(c))) for c in data['camera']]
    for i, a in enumerate(data['actors']):
        lines.append(f"poses {i} {data['first']} {len(a['poses'])}")
        lines += [' '.join(map(str, q)) for q in a['poses']]
    for i, a in enumerate(data['actors']):
        # The declaration's "hands": {"pose": P} holds both hands at P instead
        # of the capture's closure (Michelle's clasped hands: the T3 model's
        # half-open fingers went through the other hand, a fist does not).
        held = (e['actors'][i].get('hands') or {}).get('pose') if i < len(e.get('actors', [])) else None
        for h, steps in enumerate(hand_steps(a, data['first'])):
            if held is not None and steps: steps = [[data['first'], held]]
            lines += [f'hand {i} {h} {t} {pose}' for t, pose in steps]
    lines += [f'eyes {i} {t} {closed}' for i, a in enumerate(data['actors']) for t, closed in a.get('eyes', [])]
    lines += [f'spark {t} {i} {bone} {kind}' for t, i, bone, kind in data.get('sparks', [])]
    for blocks, look in ((data.get('sprites', []), data.get('sprite_look')), (data.get('sprays', []), data.get('spray_look'))):
        for block in blocks:
            lines.append(f"sprite {block['first']} {len(block['rows'])} {len(block['rows'][0])} {look['colour']}")
            lines += [' '.join(' '.join(map(str, p)) for p in row) for row in sprite_rows(block['rows'], look)]
    (out / f'{key}.cine').write_text('\n'.join(lines) + '\n', newline='\n')


# The hands. The data keeps every finger of the PS2 (tools/ps2/ttt_to_cine.py,
# fingers); a T3 model has no finger of its own, only a table of poses per
# hand row (13, 17), 4 poses between open and fist (0x80034844, TIPS § 49; the
# TTT1 arcade has 17, the import keeps 4, convert.hand_steps). Their order is
# the model's own (Baek's last one is his most open), so the .cine gives a
# level, 0 open .. 3 fist, and the engine shows the pose of the model's table
# nearest to it, measured on the table itself (src/tekken3_ttt1_mod.c,
# hand_pose). A guest hand without a table (ttt1_characters.json "hands", '-')
# gets nothing; a native's hand without one (Yoshimitsu's sword hand) ignores
# its steps in the engine.
# How closed a hand is: the four fingers past the thumb, each one's straight
# distance from the wrist to its last node over the length of its chain
# (STRETCH_OPEN on an open hand of these captures, STRETCH_FIST in a fist);
# HAND_KEEP: how far past the pose kept the value goes before it changes (no
# flicker).
HAND_POSES = 4
STRETCH_OPEN, STRETCH_FIST, HAND_KEEP = 0.95, 0.43, 0.65
GUESTS = ROOT / 'tools/data/ttt1_characters.json'


def hand_closure(offsets, rotations):
    """0 (open) .. 1 (fist) of one hand at one frame, from its fingers' local
    rotations (w x y z x 10000, in the parent's frame) and offsets."""
    def matrix(q):                     # row-vector rotation (v' = v M) of a w x y z quaternion
        w, x, y, z = (v / 10000 for v in q)
        return [[1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)],
                [2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)],
                [2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)]]
    mul = lambda v, M: [sum(v[k] * M[k][j] for k in range(3)) for j in range(3)]
    dist = lambda v: sum(c * c for c in v) ** 0.5
    stretch = []
    for f in range(1, 5):                                     # past the thumb
        R, p, length = [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [0.0, 0.0, 0.0], 0.0
        for j in range(3):
            n = 3 * f + j
            step = mul(offsets[n], R)
            p = [a + b for a, b in zip(p, step)]; length += dist(step)
            R = [mul(row, R) for row in matrix(rotations[4 * n:4 * n + 4])]
        stretch.append(dist(p) / length if length else 1.0)
    mean = sum(stretch) / len(stretch)
    return min(1.0, max(0.0, (STRETCH_OPEN - mean) / (STRETCH_OPEN - STRETCH_FIST)))


def hand_steps(actor, first):
    """[hand 0 steps, hand 1 steps] of an actor: [frame, pose] each time its
    pose changes. Hand 0 (row 13) is the PS2 wrist 38 on the retarget's side 0.
    After a `swap` the hands are the new character's (its tables, its
    retarget's side), a step given again at the change."""
    if not actor.get('fingers'): return []
    guests = json.loads(GUESTS.read_text(encoding='utf-8'))['characters']
    segments = [dict(t=first, cast=actor['cast'], side=actor.get('side', 0))] + actor.get('swaps', [])
    out = [[], []]
    for n, seg in enumerate(segments):
        end = segments[n + 1]['t'] if n + 1 < len(segments) else None
        tables = guests[seg['cast']].get('hands', '??') if seg['cast'] in guests else '??'
        wrists = ('38', '63') if seg.get('side', 0) == 0 else ('63', '38')
        for h, wrist in enumerate(wrists):
            kept = None
            if tables[h] == '-': continue
            hand = actor['fingers'][wrist]
            for k, q in enumerate(hand['rotations']):
                t = first + k
                if t < seg['t'] or (end is not None and t >= end): continue
                value = (HAND_POSES - 1) * hand_closure(hand['offsets'], q)
                if kept is None or abs(value - kept) > HAND_KEEP:
                    kept = int(round(value))
                    if not out[h] or out[h][-1][1] != kept or t == seg['t']: out[h].append([t, kept])
    return out


def sprite_rows(rows, look):
    """The `sprite` lines: per puff x y z (turned as the camera) radius alpha,
    the alpha ramped in over the first drawn frames and out before the last."""
    n, k = len(rows), len(rows[0])
    out = [[[0, 0, 0, 0, 0] for _ in range(k)] for _ in range(n)]
    for j in range(k):
        drawn = [bool(r[j] and r[j][3]) for r in rows]
        t = 0
        while t < n:
            if not drawn[t]: t += 1; continue
            end = t
            while end + 1 < n and drawn[end + 1]: end += 1
            for u in range(t, end + 1):
                x, y, z = rows[u][j][:3]
                ramp = min(1.0, (u - t + 1) / look['ramp_in'], (end - u + 1) / look['ramp_out'])
                out[u][j] = [-z, y, x, look['radius'], round(look['alpha'] * ramp)]
            t = end + 1
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--catalogue', type=Path, default=ROOT / 'build-release/mods/ttt1', help="the installed TTT1 catalogue")
    ap.add_argument('--out', type=Path, help='default: ttt-cinematics beside the catalogue')
    ap.add_argument('--ttt-disc', type=Path, help='your Tekken Tag Tournament USA PS2 disc: the endings\' music')
    a = ap.parse_args(argv)
    out = a.out or a.catalogue.parent / 'ttt-cinematics'
    out.mkdir(parents=True, exist_ok=True)
    models(out)
    effect(out)
    if a.ttt_disc:
        music(a.ttt_disc, out)
        for key, e in CONVERTED.items():
            if e.get('music') and not own_music(e, a.ttt_disc, out):
                raise ValueError(f'{a.ttt_disc}: {key}\'s music was not found on it')
    # After the music: a .cine names it when it is there.
    for key, e in CONVERTED.items():
        converted_cine(key, e, json.loads(gzip.decompress((DATA / f'{key}.json.gz').read_bytes())), out)
    if not (out / 'ending-music.pcm').is_file() and (read_stamp(out) != CINEMATICS_VERSION or not (out / 't3-music.pcm').is_file()):
        t3_music(out)
    for key, e in CONVERTED.items():
        m = e.get('music')
        if m and not (out / m['file']).is_file() and (read_stamp(out) != CINEMATICS_VERSION or not (out / m['fallback_file']).is_file()):
            t3_music(out, m['fallback_xa'], m['fallback_from'], m['fallback_file'])
    # The old way's leftovers of an earlier version (before 1.3.0): the game
    # reads none of them, a few megabytes of packs.
    for old in ['cinematics.txt', *(f'{k.capitalize()}-TTT1-combat.jmv' for k in ('kazuya', 'devil', 'armorking', 'king'))]:
        (out / old).unlink(missing_ok=True)
    for old in out.glob('*.cine.txt'): old.unlink()
    for old in out.glob('*.camera.txt'): old.unlink()
    table = ['triggers 1', '# event condition... cine=<file> then=<after> (docs/CINE-FORMAT.md)']
    table += [f"{e['trigger']} cine={key}.cine then={e.get('then', 'credits')}" for key, e in CONVERTED.items()]
    (out / 'triggers.txt').write_text('\n'.join(table) + '\n', newline='\n')
    (out / STAMP).write_text(f'{CINEMATICS_VERSION}\n')
    print(f"TTT cinematics ready in {out}{'' if (out / 'ending-music.pcm').is_file() else ' (Tekken 3 music: no TTT PS2 disc given)'}")


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, subprocess.SubprocessError, StopIteration) as error:
        print(f'TTT cinematics failed: {error}', file=sys.stderr); sys.exit(1)
