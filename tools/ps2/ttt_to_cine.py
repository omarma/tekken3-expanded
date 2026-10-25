#!/usr/bin/env python3
"""A Tekken Tag Tournament (PS2) ending, from its capture to the cinematic
engine: one tool for every ending (docs/CINE-CONVERT.md).

    venv-import python tools/ps2/ttt_to_cine.py KEY [--capture CAPTURE.jsonl] [--elf SLUS_200.01]
        [--redo] [--check] [--out DIR]

KEY names the ending's declaration, tools/data/ttt_cinematics/KEY.ending.json
(written by hand, in git: the script scene, the T3 arena, the trigger, each
actor's cast, costume, TTT1 skeleton and retarget options, the elements
knowingly left out). From the capture (tools/ps2/ttt_capture.py, format 2),
the scene's script (tools/ps2/ttt_script.py, read in the game's executable)
and the retargets (tools/ps2/ttt_retarget.py, run here) this writes
tools/data/ttt_cinematics/KEY.json.gz, the data that ships (poses, camera,
fades, music start: no disc data), then tools/ttt_cinematics.py makes the
.cine from it at the player's setup. With --out DIR, also the .cine itself
into DIR (a test, e.g. build-rel-lite/mods/ttt-cinematics).

Everything on screen comes from the script or the capture, nothing by hand:
- the frames are the script's (cine frame = script frame "t"), the length
  the script's;
- the poses: each actor's retarget, by script frame (a frame the capture
  missed holds the one before it, more than MAX_GAP in a row is an error);
- the camera: actor 0's retarget (eye, target);
- the fingers: every finger node's rotation, every frame (fingers), whole:
  what each model shows of them is ttt_cinematics.py's (hand_steps);
- the eyes: the PS2 eyelids (nodes 25 and 26, under the head) closed or
  open, every frame (eyes: blinks, unconscious actors), as `eyes` steps;
- the fades: the script's (cmd 19, 20 black, 5, 6 white), checked against
  the captured fade quads (ttt_cine_report.py);
- the music: the frame of the capture's first music packet, which must be
  the endings' piece (MUSIC_PACKET; ttt_cinematics.py's music and its
  Tekken 3 fallback, XA 44);
- the cast: the script's actor list and the capture's fighters must agree
  with the declaration;
- the character changes (cmd 0 / 1 after frame 0, the capture's "relink"):
  each one an entry of its actor's "swaps" in the declaration (cast, costume,
  skeleton, idle, model, retarget, as an actor's own), in the script's order;
  the actor is retargeted again on that skeleton (a retarget a segment, all in
  actor 0's frame of reference) and its poses change from the relink's frame,
  the first one the capture shows with the new skeleton: `swap` in the .cine.

- the sparks (cmd 10): the strong-hit effect of actor a on actor c's T3
  bone (NODE_BONE: the PS2 node's nearest T3 bone), as a T3 timed property;
  their engine tasks (SPARK_TASK) are T3's own effect then;
- the sprites at a node (cmd 18): the puffs the command spawns (SPRITE_TASKS),
  each one's captured position frame by frame while it is drawn, in the
  retarget's frame like the camera; their look (radius, alpha ramps) is
  SPRITE_LOOK, measured on the PS2 (TIPS § 103), their colour the declaration's
  "sprite_colour" (additive).

What the engine cannot play yet is never dropped silently: character
changes not declared (cmd 0 / 1 after frame 0, "relink"), Devil textures
(cmd 12), sprites between two nodes (17), props (25), coloured fades (21),
screen filters (22, 23, 24, 29, 30, 32), per-character states (15, 16,
28), flags (26, 31), figurants ("statics"), engine tasks other than the
fades and the stage's own (alive from the first frame to the last), voices,
other music. Each one is listed in workspace/ttt-ps2/KEY/convert.md and the
tool fails, unless the declaration's "ignore" names it ({"cmd": N, "t": T,
"why": ...} or {"task": "0x...", "why": ...}; the tasks born within two frames
of a left-out command go with it): then it is listed as left out.
--check stops after that report (no retarget, nothing written).
"""
import argparse, gzip, json, math, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import ttt_script, ttt_cine_report

DATA = ROOT / 'tools/data/ttt_cinematics'
WORK = ROOT / 'workspace/ttt-ps2'
IMPORT = ROOT / 'workspace/ttt1-import'
# The capture session's worktree (wip/ttt-capture-full): its captures and
# executable, read only, when this worktree has none of its own.
CAPTURE_TREE = ROOT.parent / 'Tekken3Recompiled-capture/workspace/ttt-ps2'
MUSIC_PACKET = '45804007'        # sound queue 0x40, piece 7: the endings' music, every ending's
MAX_GAP = 4
FADE_TASK = '0x3ac538'           # the black / white fades of cmd 5, 6, 19, 20
UNSUPPORTED = {                  # script command -> what it is (ttt_script.ENDING_COMMANDS)
    0: 'character change of actor 0 not in its declaration\'s "swaps"',
    1: 'character change of actor 1 not in its declaration\'s "swaps"',
    12: 'Devil textures (`devil`, reserved)',
    21: 'coloured fade (task 0x3AC728)', 25: 'held prop (scene model on a hand)',
    15: 'screen task 0x3AC4C0', 16: 'Devil / Angel state', 28: 'True Ogre / Devil state (wings)',
    22: 'screen filter 0x3AC818', 23: 'screen filter (memory / dream)', 24: 'screen filter 0x3ACA18',
    29: 'screen task 0x3AA420', 30: 'screen task 0x3AD140', 32: 'screen task 0x3AA378',
    26: 'flag gp-28292', 31: 'flag 0x34CAE0',
}
PLAYED = {2, 3, 4, 27, 5, 6, 19, 20, 10, 17, 18}   # motions and camera (in the capture), fades, sparks, sprites (below)
# The Embu's script has commands of its own (ttt_script.py): 11 a white flash
# held (a fade, ttt_cine_report.script_fades), 13 the music (its packet, the
# declaration's "music_packet").
EMBU_PLAYED = {11, 13}
def embu(scene): return scene['scene'] == 'embu'
SPARK_TASK = '0x346b60'          # cmd 10's hit effect: T3 draws its own (the `spark` property)
DEVIL_SPARK_TASK = '0x347398'    # cmd 10 of a Devil (Kazuya's ending, Jin): his lightning, T3's own effect too
SPRITE_TASKS = {'0x3a0668'}      # cmd 18 (kind 3) puffs: position float x y z at +0x20, drawn while +0x74 != 0
SPRAY_TASKS = {'0x3a0570'}       # cmd 17 (kind 2) sparks: the anchor float x y z at +0x20 plus the spark's own offset at +0x80, drawn while +0x74 != 0
EXPECTED_TASKS = {10: {SPARK_TASK, DEVIL_SPARK_TASK}, 17: SPRAY_TASKS, 18: SPRITE_TASKS}
# PS2 node -> T3 bone (actor + 0x908 + 68 · bone; 0 the pelvis, 6 / 10 the hands):
# 79 is the legs' root, at the hips. A node not here stops the conversion.
# Measured on Baek's ending (both actors, frames 119 and 300: the T3 bones
# read in the game against the PS2 nodes through the retarget's frame, 5 to
# 65 units apart): 2 the head, 3 / 7 the collarbones, 4-6 / 8-10 shoulder,
# elbow, hand, 12-14 / 15-17 hip, knee, ankle. Node 4, mid chest, has no T3
# bone: the collarbone 7, the nearest mostly (Kazuya's ending's lightning).
NODE_BONE = {0: 0, 1: 0, 79: 0, 4: 7, 5: 2, 6: 2, 31: 4, 32: 4, 33: 4, 34: 5, 38: 6,
             56: 8, 57: 8, 58: 8, 59: 9, 62: 9, 63: 10, 81: 12, 84: 13, 87: 14, 90: 15, 93: 16, 95: 16, 96: 17}
# TTT's kind 3 puff, measured on the PS2 (Kunimitsu's ending, one puff alone
# against none, TIPS § 103): about 500 units of radius, a soft disc, drawn
# while flying (landed: gone); alpha ramps so that none pops.
SPRITE_LOOK = dict(radius=500, alpha=256, ramp_in=4, ramp_out=8)
# cmd 17's spray (Armor King's ending, 45 sparks a command): tiny blue
# points on the PS2 (~6 px of its 640 at ~3 000 units): radius 40, no ramp in.
SPRAY_LOOK = dict(radius=40, alpha=256, ramp_in=1, ramp_out=6)


def first_file(*paths):
    for p in paths:
        if p and Path(p).is_file(): return Path(p)
    return None


def load_capture(path):
    """Header, frames by script frame (the last 'done' line and 'relink'
    lines apart), relinks. The Embu's lines while its player counts down to
    the scene (embu_state 2: the clock goes 19 .. 0) are not the scene's."""
    lines = path.read_text().splitlines()
    head, by_t, relinks, done = json.loads(lines[0]), {}, [], None
    for line in lines[1:]:
        d = json.loads(line)
        if 'relink' in d: relinks.append(d)
        elif d.get('done'): done = d
        elif d.get('actors') and 't' in d and d.get('embu_state', 3) == 3: by_t.setdefault(d['t'], d)
    return head, by_t, relinks, done


def relink_t(r):
    return r.get('t', r.get('relink'))


def changes(e, scene, relinks):
    """The declared character changes: {actor: [[frame, swap entry, script event], ...]},
    the frame the relink's (the first the capture shows with the new skeleton,
    0 to 2 frames after the script's command), or, when the new character's
    skeleton has the same nodes (no relink line: the Embu's Jin -> Paul at
    1574), the frame after the command's, as the relinks of Angel and Lee are;
    entries without their command are left to check(). An entry with its own
    "t" is a change no cmd 0 / 1 makes (the Embu's Jin turning Devil Jin at
    2079, cmd 12: another character, the Devil guest): at that frame, its
    event None."""
    out, used = {}, set()
    for ev in sorted((ev for ev in scene['events'] if ev['cmd'] in (0, 1) and ev['t'] > 0), key=lambda ev: ev['t']):
        i = ev['cmd']
        swaps = [w for w in e['actors'][i].get('swaps', []) if 't' not in w] if i < len(e['actors']) else []
        k = len([v for v in out.get(i, []) if v[2] is not None])
        r = next((r for r in relinks if id(r) not in used and 0 <= relink_t(r) - ev['t'] <= 2), None)
        if k >= len(swaps): continue
        if r is not None: used.add(id(r))
        out.setdefault(i, []).append([relink_t(r) if r is not None else ev['t'] + 1, swaps[k], ev])
    for i, a in enumerate(e['actors']):
        for w in a.get('swaps', []):
            if 't' in w: out.setdefault(i, []).append([w['t'], w, None])
        if i in out: out[i].sort(key=lambda v: v[0])
    return out


def check(key, e, scene, head, by_t, relinks, capture_name):
    """What the scene holds that the engine cannot play: (problems, left out
    on purpose, notes), each a report line."""
    problems, left_out, notes = [], [], []
    ignore = e.get('ignore', [])
    def ignored(**k):
        # An entry matches by the keys it gives: {"cmd": 7} every cmd 7, {"cmd": 12, "t": 2079} that one.
        return next((i for i in ignore if all(k.get(a) == b for a, b in i.items() if a != 'why')), None)
    def problem(text, also=None, **k):
        i = ignored(**k) or (also and ignored(**also))
        (left_out if i else problems).append(text + (f" — left out: {i['why']}" if i else ''))

    # The cast: the script's list entries at frame 0 against the declaration.
    entries = {a['entry']: a for a in scene['actors']}
    cast = {}
    for ev in scene['events']:
        if ev['cmd'] in (0, 1) and ev['t'] == 0: cast[ev['cmd']] = entries.get(ev['a'])
    for i, a in enumerate(e['actors']):
        s = cast.get(i)
        if not s: problems.append(f'actor {i}: no cast at frame 0 in the script'); continue
        notes.append(f"actor {i}: script {s['key']} (TTT costume {s['costume']}) -> .cine {a['cast']} costume {a['costume']}"
                     + (f" ({a['why']})" if a.get('why') else ''))
        if s['key'] != a['cast'] and not a.get('cast_of'):
            problems.append(f"actor {i}: the script casts {s['key']}, the declaration {a['cast']} (give \"cast_of\" to mean it)")
    if len(e['actors']) != len(cast):
        problems.append(f"{len(cast)} actors in the script, {len(e['actors'])} declared")

    # The character changes: each script command after frame 0 a declared
    # swap and a relink of the capture, in order.
    found = changes(e, scene, relinks)
    matched = {id(ev) for v in found.values() for _, _, ev in v}
    relink_ts = {relink_t(r) for r in relinks}
    seen_relinks = {t for v in found.values() for t, _, _ in v}
    for i, v in found.items():
        for t, w, ev in v:
            if ev is None:
                notes.append(f"actor {i} at {t} (the declaration's own frame): `swap` {w['cast']} costume {w['costume']}"
                             + (f" ({w['why']})" if w.get('why') else ''))
                continue
            s = entries.get(ev['a'])
            notes.append(f"actor {i} at {t} (script {ev['t']}{'' if t in relink_ts else ', no relink: the frame after'}): "
                         f"script {s and s['key']} (TTT costume {s and s['costume']}) "
                         f"-> `swap` {w['cast']} costume {w['costume']}" + (f" ({w['why']})" if w.get('why') else ''))
            if s and s['key'] != w['cast'] and not w.get('cast_of'):
                problems.append(f"actor {i} at {t}: the script casts {s['key']}, the declaration {w['cast']} (give \"cast_of\" to mean it)")
    for i, a in enumerate(e['actors']):
        if len(a.get('swaps', [])) > len(found.get(i, [])):
            problems.append(f"actor {i}: {len(a['swaps'])} swaps declared, {len(found.get(i, []))} character changes in the script and the capture")

    # Script commands.
    for ev in scene['events']:
        c, t = ev['cmd'], ev['t']
        if c in (0, 1) and (t == 0 or id(ev) in matched): continue
        if c == 10 and e.get('spark_bones') != 't3' and ev['b'] not in NODE_BONE:
            problems.append(f"script {t}: cmd 10 on PS2 node {ev['b']}: no T3 bone for it (NODE_BONE)")
        if c in PLAYED or (embu(scene) and c in EMBU_PLAYED) or (c == 7 and e.get('ttt_stage')): continue
        problem(f"script {t}: cmd {c} ({UNSUPPORTED.get(c, 'unknown command')}) a={ev['a']} b={ev['b']} c={ev['c']}", cmd=c, t=t)

    # Capture: skeletons, figurants, tasks, voices, music.
    for r in (r for r in relinks if relink_t(r) not in seen_relinks):
        problem(f"capture {r.get('t', r.get('relink'))}: skeleton change ({r.get('nodes')} nodes)", relink=r.get('t', r.get('relink')))
    ts = sorted(by_t)
    statics = [t for t in ts if by_t[t].get('statics')]
    if statics: problem(f'capture: figurants at {statics[:10]}{" …" if len(statics) > 10 else ""}', figurants=True)
    alive, life = {}, []
    for t in ts:
        d = by_t[t]
        if 'tasks' not in d: continue
        now = {a: f for a, f in d['tasks']}
        for a, f in list(alive.items()):
            if a not in now or now[a] != f[0]: life.append((f[0], f[1], t - 1)); del alive[a]
        for a, f in now.items():
            if a not in alive: alive[a] = (f, t)
    life += [(f, t0, None) for f, t0 in alive.values()]
    stage_tasks, bursts = {}, {}
    for kind, t0, t1 in life:
        if kind == FADE_TASK: continue
        if t0 <= ts[0] and t1 is None: stage_tasks[kind] = stage_tasks.get(kind, 0) + 1; continue
        bursts[kind, t0, t1] = bursts.get((kind, t0, t1), 0) + 1
    # One line per kind and cause: a burst born just after a script command is
    # most likely that command's; bursts without one (a stage's ambience
    # spawned all along: Baek's and Wang's 0x3A0850) are grouped.
    groups = {}
    for (kind, t0, t1), count in sorted(bursts.items(), key=lambda kv: kv[0][1]):
        cause = next((ev for ev in scene['events'] if 0 <= t0 - ev['t'] <= 2 and (ev['cmd'] not in PLAYED or ev['cmd'] in EXPECTED_TASKS)), None)
        g = groups.setdefault((kind, cause and (cause['t'], cause['cmd'])), [0, 0, t0, t1])
        g[0] += count; g[1] += 1; g[3] = None if t1 is None or g[3] is None else max(g[3], t1)
    for (kind, cause), (count, n, t0, t1) in groups.items():
        if cause and kind in EXPECTED_TASKS.get(cause[1], ()):
            notes.append(f"capture {t0}-{t1 if t1 is not None else 'end'}: engine task {kind} ×{count} of script {cause[0]} cmd {cause[1]}: "
                         + ("T3's own hit effect (`spark`)" if cause[1] == 10 else 'its puffs (`sprite`)'))
            continue
        problem(f"capture {t0}-{t1 if t1 is not None else 'end'}: engine task {kind} ×{count}"
                + (f' in {n} bursts' if n > 1 else '')
                + (f" (after script {cause[0]} cmd {cause[1]})" if cause else ' (no script command)'), task=kind,
                also=dict(t=cause[0], cmd=cause[1]) if cause else None)
    if stage_tasks:
        notes.append('the stage\'s own tasks (alive all along; the T3 arena brings its own): '
                     + ', '.join(f'{k} ×{n}' for k, n in sorted(stage_tasks.items())))
    voices = [t for i, t in enumerate(ts[1:], 1) if by_t[t].get('voices') and by_t[ts[i - 1]].get('voices')
              and any(a[:3] != b[:3] and b[1] for a, b in zip(by_t[ts[i - 1]]['voices'], by_t[t]['voices']))]
    if voices: problem(f'capture: sounds started at {voices[:10]}', voices=True)
    music = [(t, by_t[t]['music']) for t in ts if 'music' in by_t[t]]
    if not music: problems.append('capture: no music packet')
    packet = e.get('music_packet', MUSIC_PACKET)
    for t, m in music:
        if m != packet: problem(f'capture {t}: music packet {m}, not the piece {packet}', music=m)

    # Frames the capture missed.
    missing = [t for t in range(ts[0], ts[-1] + 1) if t not in by_t]
    run = longest = 0
    for t in range(ts[0], ts[-1] + 1):
        run = run + 1 if t not in by_t else 0; longest = max(longest, run)
    if longest > MAX_GAP: problems.append(f'capture {capture_name}: {longest} script frames missed in a row (more than {MAX_GAP})')
    notes.append(f"capture {capture_name}: script frames {ts[0]}..{ts[-1]} of 0..{scene['length'] - 1}, "
                 f"{len(missing)} missed inside" + (f' (first {missing[:8]})' if missing else '')
                 + (f', frames 0..{ts[0] - 1} hold the first pose' if ts[0] else ''))
    if ts[-1] < scene['length'] - 1:
        notes.append(f"frames {ts[-1] + 1}..{scene['length'] - 1} hold the last pose")
    return problems, left_out, notes


def fades(scene, by_t):
    """The script's fades as (from, to, a, b), and the report lines that
    check them against the captured quads."""
    out = [tuple(f) for f in ttt_cine_report.script_fades(scene)]
    ts = sorted(by_t)
    for t in ts: by_t[t].setdefault('fade', [0, 0, 0])
    whites = [(by_t[t]['fade'][1] >> 24) & 0xFF for t in ts]
    levels = []
    for k, t in enumerate(ts):
        f = by_t[t]['fade']
        moving = any(whites[j] != whites[k] for j in (k - 1, k + 1) if 0 <= j < len(ts))
        black = (f[0] >> 24) & 0xFF
        levels.append(2 * whites[k] if moving and f[2] and whites[k] > 2 else (-2 * black if black > 2 else 0))
    seen = ttt_cine_report.spans(levels, ts)
    lines, problems = [], []
    for a, b, x, y in out:
        hit = [m for m in seen if m[0] <= b + 3 and m[1] >= a - 3]
        lines.append(f"fade {a}-{b} {x} -> {y}: captured {', '.join(f'{m[0]}-{m[1]} (peak {m[2]})' for m in hit) or 'NOT SEEN'}")
        if not hit and a > ts[0]: problems.append(f'script fade {a}-{b} not seen in the capture')
    for m in seen:
        if not any(m[0] <= b + 3 and m[1] >= a - 3 for a, b, _, _ in out):
            problems.append(f'captured fade {m[0]}-{m[1]} (peak {m[2]}) without a script command')
    return out, lines, problems


def retarget(key, e, capture, redo):
    """Each actor's retargets (ttt_retarget.py), kept in workspace/ttt-ps2/KEY/:
    [actor][segment], segment 0 its own character, then one a swap (on that
    character's skeleton, over the whole capture: only its frames are kept)."""
    folder = WORK / key; folder.mkdir(parents=True, exist_ok=True)
    outs = []
    for i, a in enumerate(e['actors']):
        outs.append([])
        for k, w in enumerate([a] + a.get('swaps', [])):
            out = folder / (f"{w['cast']}-{i}-ttt1.json" if not k else f"{w['cast']}-{i}-s{k}-ttt1.json")
            log_name = f'retarget-{i}.log' if not k else f'retarget-{i}-s{k}.log'
            outs[i].append(out)
            if out.is_file() and not redo and out.stat().st_mtime > capture.stat().st_mtime: continue
            skel = w.get('skeleton', w['cast'])
            args = [sys.executable, str(HERE / 'ttt_retarget.py'), str(capture), str(i), skel, str(out)]
            if w.get('idle'): args += ['--idle', str(IMPORT / w['idle'])]
            if w.get('model'): args += ['--model', str(IMPORT / w['model'])]
            opts = [str(outs[0][0]) if v == '{actor0}' else v for v in w.get('retarget', [])]
            # --view's file, as the declaration's "camera", is under workspace/ttt-ps2/.
            args += [str(WORK / v) if k and opts[k - 1] == '--view' else v for k, v in enumerate(opts)]
            print('retarget:', ' '.join(args[2:]), flush=True)
            with (folder / log_name).open('w') as log:
                subprocess.run(args, check=True, stdout=log, stderr=subprocess.STDOUT)
            print((folder / log_name).read_text().strip().splitlines()[-1], flush=True)
    return [[json.loads(p.read_text()) for p in o] for o in outs]


def storms(scene, e):
    """The declaration's "ttt_stage": {"stage": n, "types": {a: type}}: the
    script's storm (cmd 7, effect a of TTT's stage 4, the Embu's) as the TTT
    arcade stage's lightning of that type (`storm`), a kept as the type by
    default (0-2 lit clouds, 3-5 a bolt seen: the PS2's look alike). Of
    commands closer than STORM_GAP frames the strongest only: a second one
    cut the first's flash short (the Embu: 4 then 0 two frames after at 120,
    1 then 6 at 440)."""
    s = e.get('ttt_stage')
    if not s: return []
    types = {int(k): v for k, v in s.get('types', {}).items()}
    evs = [[ev['t'], types.get(ev['a'], ev['a'])] for ev in scene['events'] if ev['cmd'] == 7]
    quiet = int(bool(s.get('quiet')))      # without the thunder (the PS2's Embu has none)
    return [[t, k, quiet] for t, k in evs if not any(abs(u - t) < STORM_GAP and (j > k or (j == k and u < t)) for u, j in evs)]


STORM_GAP = 30


def sparks(scene, e):
    """cmd 10 as [frame, actor, T3 bone, kind]: kind = the actor whose effect it is.
    The Embu's (the declaration's "spark_bones": "t3"): actor a's own hit point b,
    numbered as Tekken 3's bones. Its kind is the other actor's: an actor's spark
    on its own body showed the other one's effect with its own kind (measured in
    the engine: Paul's punch with Hwoarang's cyan light, Jin's lightning as
    Paul's orange blaze; crossed, each one's own)."""
    if e.get('spark_bones') == 't3':
        return [[ev['t'], ev['a'] & 1, ev['b'], 1 - (ev['a'] & 1)] for ev in scene['events'] if ev['cmd'] == 10]
    return [[ev['t'], ev['c'] & 1, NODE_BONE[ev['b']], ev['a'] & 1] for ev in scene['events'] if ev['cmd'] == 10]


def sprites(scene, by_t, calib, cmd=18, tasks=SPRITE_TASKS, offset=None, every=1):
    """Each cmd 18's puffs: one block {first, rows: [[x, y, z, alive] per puff]},
    positions through the retarget's calibration (to_t3 of ttt_retarget.py).
    cmd 17's sprays the same way, each spark at its anchor plus `offset`'s
    vector (SPRAY_TASKS), one spark in `every` kept: the engine draws 64
    puffs a frame, 32 a block (Armor King's four sprays at 936-942: 180)."""
    import numpy as np, struct
    C, scale, origin = np.array(calib['C']), calib['scale'], np.array(calib['origin'])
    ts = sorted(by_t); out = []; seen = set()      # tasks claimed by an earlier command, or left out
    for ev in (ev for ev in scene['events'] if ev['cmd'] == cmd):
        mine, rows, first = [], [], None
        for t in ts:
            if t < ev['t']: continue
            td = {a: bytes.fromhex(v) for a, v in by_t[t].get('task_data', {}).items()}
            live = {a for a, b in td.items() if f'0x{struct.unpack_from("<I", b, 8)[0]:x}' in tasks}
            if t <= ev['t'] + 2:
                new = sorted(a for a in live if a not in seen); seen.update(new); mine += new[::every]
            if not mine: continue
            if not live & set(mine) and t > ev['t'] + 2: break
            first = t if first is None else first
            row = []
            for a in mine:
                b = td.get(a)
                if b is None or a not in live: row.append(None); continue
                p = np.array(struct.unpack_from('<3f', b, 0x20))
                if offset: p = p + np.array(struct.unpack_from('<3f', b, offset))
                drawn = struct.unpack_from('<f', b, 0x74)[0] != 0
                q = scale * (C @ (p - origin))
                row.append([round(v) for v in q] + [int(drawn)])
            while rows and len(rows) + first < t: rows.append(rows[-1])          # a missed frame holds the one before
            rows.append(row)
        if mine: out.append(dict(cmd_t=ev['t'], first=first, rows=rows))
    return out


# The hands, kept whole: each PS2 hand has five fingers of three nodes after
# its wrist (38 and 63, tools/ps2/ttt_retarget.py), the thumb first, each
# node's parent the one before it (the first one's the wrist). The data keeps,
# for every frame, each finger node's rotation in its parent's frame (a unit
# quaternion w x y z, x 10000) and, once, its offset from the parent (the
# median: the bones do not stretch), the opening and closing of every finger
# as the PS2 plays it. What a model can show of it (a few poses from open to
# fist, no finger of its own) is ttt_cinematics.py's, per model (hand_steps).
WRISTS = (38, 63)
FINGER_NODES = 15


def quaternion(R):
    """w x y z of a rotation matrix (column vectors)."""
    import numpy as np
    w = np.sqrt(max(0.0, 1 + R[0, 0] + R[1, 1] + R[2, 2])) / 2
    x = np.copysign(np.sqrt(max(0.0, 1 + R[0, 0] - R[1, 1] - R[2, 2])) / 2, R[2, 1] - R[1, 2])
    y = np.copysign(np.sqrt(max(0.0, 1 - R[0, 0] + R[1, 1] - R[2, 2])) / 2, R[0, 2] - R[2, 0])
    z = np.copysign(np.sqrt(max(0.0, 1 - R[0, 0] - R[1, 1] + R[2, 2])) / 2, R[1, 0] - R[0, 1])
    q = np.array([w, x, y, z]); return q / np.linalg.norm(q)


def fingers(head, by_t, actor, frames, relinks=()):
    """{wrist: {offsets: [[x, y, z] per node], rotations: [[w x y z per node] per frame]}}
    of a PS2 actor, by script frame over `frames` (a missed frame holds the one before,
    the frames before the first captured one take it, and so do the frames it is not
    drawn: the Embu's actors before their first clip). An actor without a skeleton at
    the start (the Embu's) takes its first relink's."""
    import numpy as np
    parents = head['parents'][actor] or next((r['parents'][actor] for r in relinks if r['parents'][actor]), [])
    out = {}
    for wrist in WRISTS:
        nodes = list(range(wrist + 1, wrist + 1 + FINGER_NODES))
        if len(parents) <= nodes[-1] or any(parents[n] != (wrist if (n - wrist - 1) % 3 == 0 else n - 1) for n in nodes):
            raise SystemExit(f'actor {actor}: nodes {nodes[0]}..{nodes[-1]} are not five fingers on wrist {wrist}')
        rows, offsets, last = [], [], None
        for t in frames:
            d = by_t.get(t)
            if d and d['actors'][actor]:
                m = d['actors'][actor]
                world = lambda k: np.array(m[k], float).reshape(4, 4)   # row vectors: v' = v M
                row = []
                for n in nodes:
                    local = world(n) @ np.linalg.inv(world(parents[n]))
                    u, _, vt = np.linalg.svd(local[:3, :3].T)            # column vectors, orthonormal
                    row += [round(float(v) * 10000) for v in quaternion(u @ vt)]
                    offsets.append(local[3, :3])
                last = row
            rows.append(last)
        first = next(r for r in rows if r)
        rows = [r or first for r in rows]
        median = np.median(np.array(offsets).reshape(-1, FINGER_NODES, 3), axis=0)
        out[str(wrist)] = dict(offsets=[[round(float(v), 3) for v in o] for o in median], rotations=rows)
    return out


def spliced(rs, starts, field, frames):
    """An actor's `field` by script frame over `frames`, from the retarget of
    the segment each frame is in (segment k from starts[k - 1] on)."""
    runs = [by_frame(r, field, frames) for r in rs]
    return [runs[sum(t >= s for s in starts)][n] for n, t in enumerate(frames)]


# The eyes. TTT's eyelids are nodes 25 and 26 (children of the head, 6): their
# rotation in the head's frame, measured in Angel's ending (2026-10-21): Angel
# open ~117 degrees (the two lids' mean), closed in a blink ~142, Devil and
# Kazuya unconscious ~141-148, Kazuya waking 134 then 127. Closed above
# EYES_SHUT, open below EYES_OPEN, unchanged between (no flicker).
EYELIDS, EYES_SHUT, EYES_OPEN = (25, 26), 135.0, 131.0


def eyes(head, by_t, relinks, actor, frames):
    """[[frame, closed], ...] each time the actor's eyes change, over `frames`
    (a frame the capture missed keeps the state before); [] without eyelids."""
    import numpy as np
    changes = sorted((relink_t(r), r['parents']) for r in relinks)
    out, state = [], None
    for t in frames:
        d = by_t.get(t)
        if not d or not d['actors'][actor]: continue      # not drawn (the Embu's hidden actors)
        parents = head['parents']
        for at, q in changes:
            if at <= t: parents = q
        p, m = parents[actor], d['actors'][actor]
        if len(p) <= max(EYELIDS) or any(p[n] != 6 for n in EYELIDS): continue
        world = lambda k: np.array(m[k], float).reshape(4, 4)
        mean = 0.0
        for n in EYELIDS:
            local = world(n) @ np.linalg.inv(world(p[n]))
            R = local[:3, :3] / np.linalg.norm(local[:3, :3], axis=0)
            mean += np.degrees(np.arccos(max(-1.0, min(1.0, (np.trace(R) - 1) / 2)))) / len(EYELIDS)
        closed = 1 if mean > EYES_SHUT else 0 if mean < EYES_OPEN else state
        if closed is None: closed = int(mean > (EYES_SHUT + EYES_OPEN) / 2)
        if closed != state: out.append([t, closed]); state = closed
    return out


def nudged(poses, nudges, frames):
    """The declaration's "nudge" of an actor: [{"from": A, "to": B, "offset": [x, y, z]}, ...],
    its root moved by the offset (TTT1 units, the retarget's frame: y down) over
    script frames A..B-1, the rest untouched. For a contact the TTT1 proportions
    lose (a T3 head bigger than the PS2's under a hand): put A and B on camera cuts."""
    import math
    K = 2 * math.pi / 65536
    s16 = lambda v: ((int(v) + 32768) % 65536) - 32768
    out = [list(q) for q in poses]
    for n in nudges:
        dx, dy, dz = n['offset']
        for k, t in enumerate(frames):
            if not n['from'] <= t < n['to']: continue
            a, h, d = s16(out[k][0]) * K, s16(out[k][1]), s16(out[k][2])
            x, y, z = math.sin(a) * d + dx, -h + dy, math.cos(a) * d + dz
            out[k][:3] = [int(round(math.atan2(x, z) / K)) & 0xffff, int(round(-y)) & 0xffff, int(round(math.hypot(x, z))) & 0xffff]
    return out


def by_frame(r, field, frames):
    """r[field] by script frame over `frames`, gaps holding the frame before,
    the frames before the first one taking it (the Embu's actor 0 before its
    first clip, hidden)."""
    have = dict(zip(r['frames'], r[field]))
    out, last = [], None
    for t in frames:
        last = have.get(t, last)
        out.append(last)
    first = next((v for v in out if v is not None), None)
    return [first if v is None else v for v in out]


def hidden_spans(scene, actor):
    """The declaration's "hide_idle": the script frames the actor plays no clip
    (cmd 2 / 3: for c - b frames), as [first, last] spans: the PS2's Embu draws
    an actor only then. A command shows from the frame after its own, as its
    camera (cmd 4), the relinks and the poses do in the capture: the clip at
    script 2016 is on screen from 2017, with Xiaoyu's skeleton and her shot's
    camera. Taken from 2016 it showed actor 0 one frame early, still Jun in her
    last pose, the eye moved onto her in Paul's shot."""
    plays = sorted((ev['t'] + 1, ev['t'] + 1 + ev['c'] - ev['b']) for ev in scene['events'] if ev['cmd'] == 2 + actor)
    out, t = [], 0
    for a, b in plays:
        if a > t: out.append([t, a - 1])
        t = max(t, b + 1)
    if t < scene['length']: out.append([t, scene['length'] - 1])
    return out


def camera_track(e, by_t, frames, calib, hidden):
    """The declaration's "camera": every frame's own view-projection ({"view":
    file under workspace/ttt-ps2/, "focal": Tekken 3's in PS2 pixels}), in the
    retarget's frame, the eye moved along its axis for the shot's focal as
    ttt_retarget.py --focal does, at the hips of the actor shown (actor 0 first),
    not moved when nobody is (the Embu's opening storm: moved for its wide 574 px it
    left Tekken 3's arena, a black screen). "min_height": the eye (and the target with
    it) raised to that height above the floor at least: the Embu's eye goes down to
    151 under it (Eddy's shots), unseen with a PS1 floor (culled from below), a
    floor of tiles across the sky with Arcade Stages' (400 higher: right)."""
    import numpy as np
    import ttt_retarget as RT
    views = json.loads((WORK / e['camera']['view']).read_text())
    F = float(e['camera']['focal'])
    C, scale, origin = np.array(calib['C']), calib['scale'], np.array(calib['origin'])
    out = []
    for t in frames:
        V = np.array(views[str(t)]).reshape(4, 4)
        A = V[:3][:, [0, 1, 3]].T; b = -V[3, [0, 1, 3]]
        eye, fwd = np.linalg.solve(A, b), RT.unit(V[:3, 3])
        d = by_t.get(t)
        shown = [a for a in (0, 1) if d and d['actors'][a] and not any(x <= t <= y for x, y in hidden[a])]
        if shown:
            subject = np.array(d['actors'][shown[0]][1][12:15], float)
            step = float((subject - eye) @ fwd) * (1 - F / RT.focal(V))
            # "min_gap": moved in, the eye stays that far before the nearest node
            # of an actor shown (the Embu's 1 944 px close-up of Jin at 489-504
            # put it 92 from his face: clipped, no face), never behind the PS2's.
            gap = e['camera'].get('min_gap')
            if gap and step > 0:
                nodes = np.array([m[12:15] for a in shown for m in d['actors'][a][:98]], float)
                near = float(((nodes - eye) @ fwd).min()) - step
                if near < gap: step = max(0.0, step - (gap - near))
            eye = eye + fwd * step
        c = [round(float(v)) for v in (*(scale * (C @ (eye - origin))), *(scale * (C @ (eye + 2000 * fwd - origin))))]
        low = c[1] + e['camera'].get('min_height', -10 ** 9)     # Tekken 3's y is -height
        if low > 0: c[1] -= low; c[4] -= low
        out.append(c)
    # "empty_reach": [near, far]: while nobody is shown, the eye's distance from
    # the stage's centre squeezed beyond `near` so that the farthest one is
    # `far`, the target moved with it. The Embu's opening crane starts 17 600
    # away: past ~6 000 Tekken 3 draws no stage round hidden actors, and the
    # temple sprang out of nowhere mid-move (the user).
    if e['camera'].get('empty_reach'):
        near, far = e['camera']['empty_reach']
        empty = [k for k, t in enumerate(frames) if not any(
            by_t.get(t) and by_t[t]['actors'][a] and not any(x <= t <= y for x, y in hidden[a]) for a in (0, 1))]
        reach = lambda c: math.hypot(c[0], c[2])
        top = max((reach(out[k]) for k in empty), default=0)
        for k in empty:
            r = reach(out[k])
            if r <= near or top <= far: continue
            s = (near + (r - near) * (far - near) / (top - near)) / r
            dx, dz = out[k][0] * (s - 1), out[k][2] * (s - 1)
            out[k] = [round(out[k][0] + dx), out[k][1], round(out[k][2] + dz), round(out[k][3] + dx), out[k][4], round(out[k][5] + dz)]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('key')
    ap.add_argument('--capture', type=Path, help='default: workspace/ttt-ps2/full/KEY.jsonl here, else in the capture worktree')
    ap.add_argument('--elf', type=Path, help='SLUS_200.01; default: workspace/ttt-ps2/ here, else in the capture worktree')
    ap.add_argument('--redo', action='store_true', help='retarget again even if the retargets are newer than the capture')
    ap.add_argument('--check', action='store_true', help='the report only')
    ap.add_argument('--out', type=Path, help='also write KEY.cine there (a test)')
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8')
    key = a.key
    e = json.loads((DATA / f'{key}.ending.json').read_text(encoding='utf-8'))
    capture = first_file(a.capture, WORK / f'full/{key}.jsonl', CAPTURE_TREE / f'full/{key}.jsonl')
    elf = first_file(a.elf, WORK / 'SLUS_200.01', CAPTURE_TREE / 'SLUS_200.01')
    if not capture: raise SystemExit(f'{key}: no capture (workspace/ttt-ps2/full/{key}.jsonl, here or in {CAPTURE_TREE})')
    if not elf: raise SystemExit('no SLUS_200.01 (workspace/ttt-ps2/, copied from the TTT disc)')
    scene = ttt_script.find(ttt_script.scenes(ttt_script.Elf(elf)), e['scene'])
    head, by_t, relinks, _ = load_capture(capture)
    if head.get('version') != 2: raise SystemExit(f'{capture}: capture format {head.get("version")}, 2 needed (ttt_capture.py)')

    problems, left_out, notes = check(key, e, scene, head, by_t, relinks, capture.name)
    fade_list, fade_lines, fade_problems = fades(scene, by_t)
    problems += fade_problems
    music = next((t for t in sorted(by_t) if by_t[t].get('music') == e.get('music_packet', MUSIC_PACKET)), None)
    report = [f"# {key}: scene {scene['scene']} ({scene['key']}), {scene['length']} frames, TTT stage {scene['stage']} -> T3 arena {e['arena']}", '',
              '## Not convertible yet' + ('' if problems else ': nothing'), ''] + [f'- {p}' for p in problems]
    report += ['', '## Left out on purpose (the declaration\'s "ignore")' + ('' if left_out else ': nothing'), ''] + [f'- {p}' for p in left_out]
    report += ['', '## Converted', ''] + [f'- {n}' for n in notes] + [f'- {l}' for l in fade_lines]
    piece = 'its own piece' if e.get('music') else "the endings' piece"
    report += [f'- music: {piece} from frame {music}' if music is not None else '- music: none']
    (WORK / key).mkdir(parents=True, exist_ok=True)
    (WORK / key / 'convert.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
    print('\n'.join(report))
    if problems:
        raise SystemExit(f'\n{key}: {len(problems)} element(s) the engine cannot play yet (above, and in {WORK / key / "convert.md"}): '
                         'convert them in the engine first, or name them in the declaration\'s "ignore" with why')
    if a.check: return

    segments = retarget(key, e, capture, a.redo)
    rs = [r[0] for r in segments]
    found = changes(e, scene, relinks)
    first, last = min(by_t), max(by_t)
    frames = list(range(first, last + 1))
    hidden = [hidden_spans(scene, i) if e.get('hide_idle') else [] for i in range(len(e['actors']))]
    fits = [max(r['fit_deg']) for s in segments for r in s if r.get('fit_deg')]
    data = dict(
        about=f"{e['about']} Data of tools/ps2/ttt_to_cine.py from capture {capture.name} and the scene's script "
              f"(retargets: {'; '.join(' '.join(x.get('retarget', [])) or 'stance' for x in e['actors'])}). "
              'Poses on the TTT1 arcade skeletons (57 channels), camera eye and target, both in the retarget\'s frame; '
              'frames are the script\'s.',
        version=3, key=key, length=scene['length'], first=first,
        actors=[dict(cast=x['cast'], costume=x['costume'],
                     poses=nudged(spliced(segments[i], [t for t, _, _ in found.get(i, [])], 'poses', frames), x.get('nudge', []), frames),
                     side=r['calibration'].get('side', 0), fingers=fingers(head, by_t, i, frames, relinks),
                     eyes=eyes(head, by_t, relinks, i, frames),
                     swaps=[dict(t=t, cast=w['cast'], costume=w['costume'], side=s['calibration'].get('side', 0),
                                 models=w.get('models', []))
                            for (t, w, _), s in zip(found.get(i, []), segments[i][1:])],
                     hidden=hidden[i], models=x.get('models', []), effect=x.get('effect'), light=x.get('light'))
                for i, (x, r) in enumerate(zip(e['actors'], rs))],
        camera=camera_track(e, by_t, frames, rs[0]['calibration'], hidden) if e.get('camera') else by_frame(rs[0], 'camera', frames),
        fades=[list(f) for f in fade_list], music=music,
        sparks=sparks(scene, e), sprites=sprites(scene, by_t, rs[0]['calibration']),
        sprays=sprites(scene, by_t, rs[0]['calibration'], 17, SPRAY_TASKS, 0x80, 3),
        spray_look=dict(SPRAY_LOOK, radius=round(SPRAY_LOOK['radius'] * rs[0]['calibration']['scale']),
                        colour=e.get('spray_colour', 'ffffff')),
        ttt_stage=(e.get('ttt_stage') or {}).get('stage'), ttt_courtyard=(e.get('ttt_stage') or {}).get('courtyard'),
        storms=storms(scene, e),
        sprite_look=dict(SPRITE_LOOK, radius=round(SPRITE_LOOK['radius'] * rs[0]['calibration']['scale']),
                         colour=e.get('sprite_colour', 'ffffff')))
    (DATA / f'{key}.json.gz').write_bytes(gzip.compress(json.dumps(data, separators=(',', ':')).encode(), 9, mtime=0))
    print(f"{DATA / f'{key}.json.gz'}: {len(frames)} frames from {first}, worst retarget segment {max(fits):.1f} degrees")
    if a.out:
        sys.path.insert(0, str(ROOT / 'tools'))
        import ttt_cinematics
        a.out.mkdir(parents=True, exist_ok=True)
        ttt_cinematics.converted_cine(key, e, data, a.out)
        print(a.out / f'{key}.cine')


if __name__ == '__main__':
    main()
