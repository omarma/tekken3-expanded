#!/usr/bin/env python3
"""Prepare the TTT Cinematics feature (src/tekken3_embu_scenes.c): the
Tekken Tag Tournament (PS2) endings of Kazuya and Armor King, played by the
Tekken 3 engine in place of their Arcade ending movies.

    python3 tools/ttt_cinematics.py [--catalogue DIR] [--out DIR] [--ttt-disc DISC]

Each ending's poses and camera ship in the repository
(tools/data/ttt_cinematics/<key>.json.gz: {about, p1, p2: {guest, poses},
camera}, the retarget files of branch endings-release, where the capture and
retargeting tools live; ENDINGS below holds every other setting of an
ending, explicit, never taken from the fight). From the player's own TTT1
import this writes, into --out (default build-release/mods/ttt-cinematics,
beside the TTT1 catalogue the game reads):

- each participant's combat pack with the ending's clips added: Kazuya's and
  Devil's, Armor King's and King's (a native: his TTT1 pack, played on his
  own model) (TEKKEN3_ENDING_PACKS: the game uses them in place of the
  catalogue's);
- Jin's model without the Devil and Devil Jin's without wings, the same
  geometry (tools/ttt1_devil_jin.py, from the import's work files; kept once
  made);
- Jin's red TTT1 lightning (tools/ttt1_jin_hit_effect.py, the setup's Jin
  option);
- with --ttt-disc (your Tekken Tag Tournament USA PS2 disc, .cue, .bin or
  .iso), the music of TTT's endings, decoded from it; without it, a piece of
  Tekken 3's own music, decoded from the player's disc (disc/);
- cinematics.txt, the feature's settings: the shared lines, then a section
  "[ending <key>]" per ending with its own TEKKEN3_* lines, selected by the
  game when that character finishes the Arcade; and version.txt.

Run again after any new TTT1 import: the packs come from the catalogue's.
Game data: everything written stays out of the repository.

RULE: a new cinematic, or any change of what this writes, increments
CINEMATICS_VERSION. The setup then runs this step again on its own (seconds,
offline: no new TTT1 import unless a new piece needs the import's work files).
"""
import argparse, gzip, hashlib, json, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/ttt1'))
from pack_edit import Pack

CINEMATICS_VERSION = 3
STAMP = 'version.txt'
DATA = ROOT / 'tools/data/ttt_cinematics'
WORK = ROOT / 'workspace/ttt1-import'
START = 14              # the ending's first frame in the cutscene (black before)
CHUNK = 240             # frames a clip (its length is one byte)
HOLD = 130              # frames the last pose is held
SLOT_BASE, SLOT_STRIDE = 8192, 4096
FADE_IN, FADE_OUT = 40, 90
MODELS = {'JinPlain': ['--plain'], 'DevilJinEnd': ['--wings', 'none']}
EFFECT = 'Jin-TTT1-hiteffect.tim'
# The endings, each with every setting of its own (the user's rule: explicit
# per ending, never taken from the fight): the T3 arena it plays in and its
# dark look (True Ogre's) or not (tools/ps2/ttt_endings.json on
# endings-release); p2_aura: player 2's lightning aura (timed property 6)
# over capture frames, one entry every `step` frames on the next T3 bone;
# p2_models: player 2 drawn with other model files from a capture frame on;
# effects: the lightning pack of both players and the strong-hit light.
ENDINGS = {
    'kazuya': dict(arena=6, dark=0,                                   # Ogre's temple, lit
                   p2_aura=(832, 1023, [2, 13, 6, 17, 3, 10, 16, 5, 14, 7, 12, 8, 15, 4], 2),
                   p2_models='JinPlain@0,DevilJinEnd@832',             # Jin, then Devil Jin from his transformation
                   effects=True),
    'armorking': dict(arena=11, dark=0),                              # King's stage, King on his own model
}

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


def t3_music(out):
    """Tekken 3's XA stream FALLBACK_XA from FALLBACK_FROM s, at 44 100 Hz, raw 16-bit stereo PCM."""
    import numpy as np, struct
    exe = (T3_DISC / 'SLUS_004.02').read_bytes()
    start, end, channel = struct.unpack_from('<3I', exe, 0x15578 + 12 * FALLBACK_XA)
    from glyphs import data_track          # track 1 as disc/'s cue names it
    with data_track().open('rb') as f:
        def sector(n): f.seek((604 + n) * 2352); return f.read(2352)
        pcm = xa_decode([sector(n) for n in range(start + channel, end + channel + 1, 8)])[FALLBACK_FROM * 37800:]
    t = np.arange(int(len(pcm) * 44100 / 37800)) * (37800 / 44100)
    pcm = np.stack([np.interp(t, np.arange(len(pcm)), pcm[:, c]) for c in (0, 1)], 1)
    (out / 't3-music.pcm').write_bytes(pcm.round().astype('<i2').tobytes())


def clips(poses, key, player, catalogue, out, aura=None):
    """Script records playing `poses` on `player` from frame 0; the guest's
    pack gets the clips, copies of its neutral record, written to `out`."""
    name = key.capitalize()
    pack = Pack((catalogue / f'{name}-TTT1-combat.jmv').read_bytes())
    base = SLOT_BASE + player * SLOT_STRIDE
    # The first pose held until the ending starts, then clips of CHUNK frames.
    i = pack.add_record(pack.neutral, 0x803F0000 + 0xFFF0)
    pack.set_clip(i, [poses[0]] * START)
    recs, f = [[0, 2 + player, base + i, 0, START - 1]], START
    for k in range(0, len(poses), CHUNK):
        chunk = poses[k:k + CHUNK]
        i = pack.add_record(pack.neutral, 0x803F0000 + k)
        pack.set_clip(i, chunk)
        if aura:
            first, last, bones, step = aura
            lit = [(n - k + 1, 6, bones[n // step % len(bones)])
                   for n in range(max(first, k), min(last, k + len(chunk) - 1) + 1, step)]
            if lit: pack.set_props(i, lit)
        recs.append([f, 2 + player, base + i, 0, len(chunk) - 1]); f += len(chunk)
    # The last pose held by a clip of its own (a record at its end frame goes
    # on to its next move, the stance at the origin).
    i = pack.add_record(pack.neutral, 0x803F0000 + len(poses))
    pack.set_clip(i, [poses[-1]] * HOLD)
    recs.append([f, 2 + player, base + i, 0, HOLD - 1])
    (out / f'{name}-TTT1-combat.jmv').write_bytes(pack.build())
    return recs, f


def models(out):
    """Jin's model and Devil Jin's without wings, once (they need the import's
    work files, gone after the setup's "free up disk space")."""
    for name, args in MODELS.items():
        if all((out / f'{name}-TTT1-arcade-P1.{ext}').is_file() for ext in ('3dm', 'relocs', 'tim')): continue
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable, ROOT / 'tools/ttt1_devil_jin.py', *args, '--out', tmp], check=True)
            for ext in ('3dm', 'relocs', 'tim'):
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
    """The endings' music as raw 16-bit stereo PCM (TEKKEN3_EMBU_MUSIC)."""
    import numpy as np
    raw = music_data(disc)
    if raw is None:
        raise ValueError(f'{disc}: not Tekken Tag Tournament USA (SLUS-20001) for PS2, the music was not found')
    block, pairs = 1024, len(raw) // 2048
    left = b''.join(raw[i * 2048:i * 2048 + block] for i in range(pairs))
    right = b''.join(raw[i * 2048 + block:(i + 1) * 2048] for i in range(pairs))
    (out / 'ending-music.pcm').write_bytes(np.stack([decode(left), decode(right)], 1).tobytes())


def effect(out):
    for source in (WORK / 'jin' / EFFECT, ROOT / 'build-release/mods/jin-ttt1-hit-effect' / EFFECT):
        if source.is_file():
            shutil.copyfile(source, out / EFFECT); return
    if not (out / EFFECT).is_file():
        raise ValueError(f"Jin's red lightning is missing: run tools/ttt1_jin_hit_effect.py (the setup's Jin option)")


def fade_spans(levels, offset, tol=6):
    """TEKKEN3_EMBU_FADE spans for per-frame levels (a captured ending's own
    fades): straight pieces within `tol` of every frame, frames at 0 left
    out (the switch off). As ttt_ending_pack.py's on endings-release."""
    spans, i, n = [], 0, len(levels)
    while i < n:
        if levels[i] == 0: i += 1; continue
        j = i
        while j + 1 < n and levels[j + 1] != 0:
            k = j + 1
            if not all(abs(levels[i] + (levels[k] - levels[i]) * (m - i) / (k - i) - levels[m]) <= tol for m in range(i, k + 1)): break
            j = k
        spans.append(f'{offset + i}-{offset + j}:{levels[i]}:{levels[j]}')
        i = j + 1
    return spans


def ending(key, e, catalogue, out):
    """One ending's packs, script and camera files; its cinematics.txt section."""
    data = json.loads(gzip.decompress((DATA / f'{key}.json.gz').read_bytes()))
    script, end = clips(data['p1']['poses'], data['p1']['guest'], 0, catalogue, out)
    recs, end2 = clips(data['p2']['poses'], data['p2']['guest'], 1, catalogue, out, e.get('p2_aura'))
    script = sorted(script + recs, key=lambda r: (r[0], r[1])); end = max(end, end2)
    # Ended by a -1 record once the fade to black, over the held last pose, is done.
    (out / f'{key}.cine.txt').write_text(''.join(' '.join(map(str, r)) + '\n' for r in script + [[end + FADE_OUT + 10, -1, 0, 0, 0]]))
    # The camera turned as the actors are, (x, z) -> (-z, x); the first shot
    # held before the ending starts, the last one after it.
    cams = data['camera']
    turn = lambda c: [-c[2], c[1], c[0], -c[5], c[4], c[3]]
    track = [cams[0]] * START + cams
    track += [cams[-1]] * max(0, end + 1000 - len(track))
    (out / f'{key}.camera.txt').write_text('0\n' + '\n'.join(' '.join(map(str, turn(c))) for c in track) + '\n')
    # Model files under the catalogue (mods/ttt1): ours are beside it. Every
    # key written, empty when the ending has none: a selection replaces the
    # previous ending's lines.
    steps = [m.split('@') for m in e.get('p2_models', '').split(',') if m]
    # The fades: the PS2 cutscene's own when captured (black before it, then
    # black after it if it ended so), else in over FADE_IN, out over FADE_OUT.
    if data.get('fade'):
        lv = data['fade']
        spans = [f'0-{START - 1}:-256:-256'] + fade_spans(lv, START)
        spans += ([f'{START + len(lv)}-{end + 1000}:-256:-256'] if lv[-1] <= -200 else
                  [f'{end}-{end + FADE_OUT}:0:-256', f'{end + FADE_OUT}-{end + 1000}:-256:-256'])
        fade = ';'.join(spans)
    else:
        fade = (f'0-{START}:-256:-256;{START}-{START + FADE_IN}:-256:0;'
                f'{end}-{end + FADE_OUT}:0:-256;{end + FADE_OUT}-{end + 1000}:-256:-256')
    return {
        'TEKKEN3_ENDING': f"{data['p1']['guest']}:{data['p2']['guest']}:{e['arena']}:{e['dark']}",
        'TEKKEN3_FIGHT_CINE': f'$DIR/{key}.cine.txt@ending',
        'TEKKEN3_EMBU_CAMERA_TRACK': f'$DIR/{key}.camera.txt',
        'TEKKEN3_EMBU_MODEL_P2': ','.join(f'../ttt-cinematics/{m}-TTT1@{START + int(f)}' for m, f in steps),
        'TEKKEN3_EMBU_EFFECT_P1': f'$DIR/{EFFECT}' if e.get('effects') else '',
        'TEKKEN3_EMBU_EFFECT_P2': f'$DIR/{EFFECT}' if e.get('effects') else '',
        'TEKKEN3_EMBU_EFFECT_LIGHT': 'ff2020' if e.get('effects') else '',
        'TEKKEN3_EMBU_FADE': fade,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--catalogue', type=Path, default=ROOT / 'build-release/mods/ttt1', help="the installed TTT1 catalogue")
    ap.add_argument('--out', type=Path, help='default: ttt-cinematics beside the catalogue')
    ap.add_argument('--ttt-disc', type=Path, help='your Tekken Tag Tournament USA PS2 disc: the endings\' music')
    a = ap.parse_args(argv)
    out = a.out or a.catalogue.parent / 'ttt-cinematics'
    out.mkdir(parents=True, exist_ok=True)
    sections = {key: ending(key, e, a.catalogue, out) for key, e in ENDINGS.items()}
    models(out)
    effect(out)
    if a.ttt_disc: music(a.ttt_disc, out)
    settings = {'TEKKEN3_ENDING_PACKS': '$DIR'}
    if (out / 'ending-music.pcm').is_file(): settings['TEKKEN3_EMBU_MUSIC'] = f'$DIR/ending-music.pcm@{START}'
    else:
        if read_stamp(out) != CINEMATICS_VERSION or not (out / 't3-music.pcm').is_file(): t3_music(out)
        settings['TEKKEN3_EMBU_MUSIC'] = f'$DIR/t3-music.pcm@{START}'
    text = ''.join(f'{k}={v}\n' for k, v in settings.items())
    for key, lines in sections.items():
        text += f'[ending {key}]\n' + ''.join(f'{k}={v}\n' for k, v in lines.items())
    (out / 'cinematics.txt').write_text(text)
    (out / STAMP).write_text(f'{CINEMATICS_VERSION}\n')
    print(f"TTT cinematics ready in {out}{'' if (out / 'ending-music.pcm').is_file() else ' (Tekken 3 music: no TTT PS2 disc given)'}")


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, subprocess.SubprocessError, StopIteration) as error:
        print(f'TTT cinematics failed: {error}', file=sys.stderr); sys.exit(1)
