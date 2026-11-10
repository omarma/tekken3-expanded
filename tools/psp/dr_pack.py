#!/usr/bin/env python3
"""A native's Dark Resurrection moveset as a pack for the Tekken 3 runtime (<Name>-DR-*).

    python tools/psp/dr_pack.py paul [--moves "d/f+2" "d/f+1" "d+1+2"] [--out DIR]

PSP-DR.md "A3 : conception": the pack starts from the native's TTT1 pack
(<Name>-TTT1-combat.jmv / -tables.jst / -sfx.jus of the TTT1 catalogue: its
graph, movement, reactions and sounds already fit the engine) and each move
of the balance sheet (fiches/dr-<name>.tsv, A1) changes it:

- a move common to both (identical, modified, command changed) keeps its TTT1
  record, numbers of the reference (Tekken 3, else TTT1; A2 rule 15), and
  takes DR's animation retimed onto the record's frames (rule 16);
- a new move gets a record of its own, a copy of the TTT1 move whose DR
  reactions are the same (A2 rule 9), DR's numbers bounded by the Tekken 3
  moves of the same level (rule 15), and the stance's entry for its command;
- the stance plays DR's (decision 2 of the design), its first frame written to
  <Name>-DR-idle.poses too.

Moves not listed keep TTT1's clips and numbers (the first milestone converts
three moves). Writes <Name>-DR-combat.jmv, -tables.jst, -idle.poses, -sfx.jus
and report.json into --out (workspace/dr-a3/roster), nothing into the shared
TTT1 catalogue.
"""
import argparse, csv, json, struct, sys
from collections import Counter, defaultdict
import numpy as np
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / 'tools/t5'), str(ROOT / 'tools/ttt1')]
import dr_convert as X
from pack_edit import Pack

BASE_ID = 8192
WALL = 135                           # DR's wall contact condition: not taken (A2 rule 1)
NEW_PROVENANCE = 0x803f0000          # records the DR moves add (src/tekken3_ttt1_pack.h: below 0x80400000)
JALON = ('d/f+2', 'd/f+1', 'd+1+2')
# DR stances a fighter enters from its stance and Tekken 3 has not (A2 rule 14: a stance record with
# lists of its own, stances()). Jin: Mental Alertness 2 (b+1), Mental Alertness 1 (1+3+4), Power
# Stance (b+1+2); Lingering Soul Omen and its Soul Rage moves are left out (the user's choice,
# 2026-10-26).
# DR input sequences read as another command than the one the game takes: Jin's Complicated Wire is
# stored N,d/f,N,d/f+2+4 (from the walk back), DR takes d, d/b, b+1+3 (the wiki's, filmed in PPSSPP).
# reorder() for these natives (Paul's since 2026-10-31, the user's choice: DR's follow-ups on a hit,
# Demolition Man, come with it; his pack was validated in A3 without it).
REORDER = ('jin', 'deviljin', 'paul')
# What reorder() adds since Paul joined it (Jin's and Devil Jin's packs were validated without it):
# follow-ups on a hit at the frame the record hits, when the sheet's bounds moved it off DR's (Paul's
# d+4 hits on 14, DR's on 15; hit_landed is true on the hit's frame only); the moves past them, which
# only a hit opens (Demolition Man), with DR's reactions; recoveries() ends turning the fighter into a
# record half_turns() turned (Incomplete Somersault landing face down).
LATE_REORDER = ('paul',)
# The reach of a moveset's hits (<Name>-DR-reach.txt, read by src/tekken3_dr_camera.c): each of the
# victim's spheres is that much wider while the fighter's hits are tested. Tekken 3's fist is a bare
# segment, DR's hits land wider: Jin's 1, 2, 4's 2 passed 340 from Paul's chest sphere (radius 300) where
# DR's lands; the user chose a reach for every DR move (2026-10-28), 60 brings 1, 2, 4 to DR's 3 hits.
REACH = {'jin': 60, 'deviljin': 60}
# DR characters whose model has DR's hands (tools/psp/hands.py): their hand poses follow DR's, move by
# move (<Name>-DR-hands.bin, hands()); the user's choice of 2026-10-29 (Devil Jin's stance claw).
HANDS = ('deviljin',)
# Their model's hand poses: the pose table's indices 0 (DR's open T-pose hand) .. HAND_STEPS (DR's guard claw),
# closing evenly (tools/psp/hands.py: TTT1's closures, 0, 0.08 .. 0.95, 1).
HAND_STEPS = 16
# DR's own reactions on a victim in the air (condition 289), for <Name>-DR-air.txt (reactions(), read by
# src/tekken3_dr_camera.c): the spinning lifts only, a move's own (Spinning Demon's 2nd hit sends the
# falling victim up on aDw_ym_y01L, Tekken 3's reaction_air dropped him face up, the user's review of
# 2026-10-31). The juggles' common falls (dwup_hei_xe, Dw_AIR00_Png) stay Tekken 3's (A2 rule 2).
AIR_OWN = {'deviljin': ('aDw_ym_', 'aDw_c_')}
# Attacks pushing a victim in the air by DR's curve (condition 289's), for <Name>-DR-airpush.txt (read by
# src/tekken3_dr_camera.c, applied in reaction_air_arc_setup): Tekken 3's own air push is 160 in all,
# Demolition Man's last hit sent Jin 1860 in DR (he landed 3600 from Paul, 2000 in Tekken 3; the user,
# 2026-10-31).
AIR_PUSH = {'paul': ('Pl_raklpW', 'Pl_raklp')}
# And their reaction in the air DR's whatever it is (Dw_AIR00_Png, not only AIR_OWN's lifts): Tekken 3's own
# fall ended the victim's flight two frames after the hit, the push had no time to act.
AIR_MOVES = AIR_PUSH
# A DR character's lasers: DR move -> beam type of the runtime (src/tekken3_ttt1_combat.c laser_beams):
# 6, 7, 8 and 9 DR's 1+2, u+1+2, the flight's 1+2 and its dive (Cross Infernal Destruction) frame by frame (measured in PPSSPP; the flight's sweeps
# down then up into the sky, which TTT1's Devil Blaster, type 2, did not: the user, 2026-10-30). The
# record's first limb is the pack's laser limb (0x3F), the second the type; the TTT1 move the command
# played (Inferno, Air Inferno) leads to DR's.
LASERS = {'deviljin': {'Dv_beam_00': 6, 'Dv_beam_01': 7, 'Dv_beam_03': 8, 'Dv_beam_05': 9, 'Dv_Beam_n': 10, 'Dv_beam_dw': 11}}
# DR throws that deal their damage in several hits (frame, damage), the victim's life read in PPSSPP
# (probe_dr.py deviljin "demo 92", workspace/dr-b3m/probe-beamn.pkl): Devil Jin's throw into the laser,
# Dv_Beam_n, burns the thrown Jin nine times, 40 in all (Tekken 3 dealt the pack's 5 once as he landed).
# Jin's u/f+1+2 (Jz_front_n, the victim's property 0x803C, his life read in PPSSPP): 2, 2, 2, 2, 4 then 28, 40
# in all (Tekken 3 dealt 40 at once on frame 191); u/b held (Jz_front2_n) ends on 30, 42 (the pack had 30).
THROW_HITS = {'deviljin': {'Dv_Beam_n': ((61, 5), (66, 5), (71, 5), (76, 5), (81, 4), (112, 4), (122, 4), (127, 4), (132, 4))},
              'jin': {'Jz_front_n': ((51, 2), (52, 2), (53, 2), (54, 2), (65, 4), (171, 28)),
                      'Jz_front2_n': ((51, 2), (52, 2), (53, 2), (54, 2), (65, 4), (171, 30))}}
LASER_LIMB = 0x3f
# A DR charge (Devil Jin's Infinite Power, b+1+2): the stance's command leads to its start move, which
# goes on to the charge; there releasing the buttons fires a level by the frame (DR command 0x2000000,
# the runtime's condition BUTTONS_UP on the buttons held, src/tekken3_ttt1_combat.c), the charge's
# last frame the top level, another direction than the one held cancels.
CHARGES = {'deviljin': dict(command='b+1+2', start='Jz_zettai_0', charge='HEIHACHI_TEST', buttons=0x3,
                            levels=('Jz_boost_Lv1', 'Jz_boost_Lv2', 'Jz_boost_Lv3'), cancel='Dv_boost_00E')}
BUTTONS_UP = 84
# DR moves a character plays turned round from the move before: DR's heading (player + 0x20) goes round by
# 180 degrees in the dive (Dv_beam_04 at its frame 65, measured in PPSSPP on Command List demo 13), so
# Cross Infernal Destruction (Dv_beam_05) faces the opponent it flew over; Tekken 3 kept the fighter's
# facing and Devil Jin turned his back to Jin at once, the beam behind him (the user, 2026-10-31). The
# records leading there turn the fighter with the change (kind bit 0x80, as half_turns()).
HEADING_TURNS = {'deviljin': ('Dv_beam_05',)}
# The characters whose redirected entries take DR's window when DR has two moves on the command from the
# same move (hook): Devil Jin's 4~3. Paul's and Jin's packs, validated before, keep TTT1's windows.
TWIN_WINDOWS = ('deviljin',)
# A DR character's round start and end on the engine's aliases (ALIA chunk): 0 and 2 the round 1
# intros (fighter_round_start_move), 0xD67..0xD6A the round win by the button held, 1 to 4, as DR's
# Dj_Direct picks its wins (fighter_win_pose_start), 0xD6C the loser left standing (fighter_start_move)
# and the loop its end goes on to. DR's own animations, whole: one longer than a record (255 frames)
# is played faster to fit (Dj_Win_B 404, Dj_Win_D_n 301).
# Alias 1, the next rounds' start: DR's stance itself (TTT1's 128 frames put him in a guard of their own
# between the win and the fight; the user, 2026-10-30).
CEREMONIES = {'deviljin': {0: 'Dj_Start_A', 1: 'Jz_sKAM00_', 2: 'Dj_Start_A', 0xd67: 'Dj_Win_A', 0xd68: 'Dj_Win_B',
                           0xd69: 'Dj_Win_C', 0xd6a: 'Dj_Win_D_n', 0xd6c: ('Male_Rnd_Lose_01', 'lose01Lp')}}
# The round 1 intros' last frames blended into the stance (ceremonies()): DR cuts to the opponent before
# Dj_Start_A's end, which stands upright, and Tekken 3's 16-frame tail blend snapped Devil Jin into his
# guard as the fight started (the user, 2026-10-30). Its last 75 frames barely move: 48 of them blend.
INTRO_ALIASES, INTRO_SETTLE = (0, 2), 48
# The ceremonies' sounds as DR plays them (ceremony_sounds()), from the move's extra properties: 0x80DD at
# a frame says a line (its value from LINES[name] on: Devil Jin 0xB1..0xB3, his three lines, the
# container +10 of his group), 0x815A a sound in the cries' own coding (0x2002: attack cry 2, voice 3,
# found at that frame in PPSSPP's sound). Each record gets an event script of its own (the TTT1 one
# played TTT1's swings and cries at TTT1's frames, on DR's animations): ids from CEREMONY_SCRIPTS, past
# TTT1's (1682 at most), the engine's 4096 shared by both fighters. A line is the pack's sound
# LINE_SOUND + n (tools/psp/dr_sounds.py; silent while the .jus has none). DR's 0x8019 / 0x801B sounds
# are not in our banks: left out.
LINES = {'deviljin': 0xb1}
# Ceremonies played whole at DR's speed, past a record's 255 frames: the rest on a record of its own the first
# one's end goes to, the round's end held until it is over (src/tekken3_ttt1_sfx.c, a DR character's win pose).
# Devil Jin's win 2 (404 frames) with its whole line (the user, 2026-10-30).
CEREMONY_WHOLE = {'deviljin': ('Dj_Win_B',)}
CEREMONY_SCRIPTS = {'deviljin': 4000}
# F35: event scripts of the DR moves' timed sounds (move_sounds()), past TTT1's and below the ceremonies'.
MOVE_SCRIPTS = {'jin': 3700}
LINE_SOUND, SFX_MARK = 1026, 0x800
# DR's common sounds (0x815A 0x10nn, bank 4991): the pack's sound COMMON_SOUND + n, those dr_voices.json lists
# (Devil Jin's win 4 crackle, 0x22).
COMMON_SOUND = 1100
# The characters whose DR moves light the strong-hit effect on a bone as DR does (move_effects()): 0x8019 at a
# frame, its bone (Devil Jin's electric sparks: his stance's, walk's, Mukurowari...), and 0x801B 0x803, bone 8
# (the high byte: his hand), the charge's glow (Infinite Power's charge, 30 / 40 / 47 / 55; win 2's fist). The
# user, 2026-10-30: "a sort of super charge in his arm".
DR_EFFECTS = ('deviljin',)
# Characters whose DR follow-ups off the sheet are all converted (hidden()): to the strings' ends, from
# every move the pack plays, DR's animation on the TTT1 records they reuse. The user's choice of
# 2026-10-30 (DR's Command List demos: Devil Jin's 10-hit strings, Wind God Step's follow-ups);
# Paul and Jin too since 2026-10-31 (the user: the wiki's moves the sheet lacked: Paul's Demolition Man (its
# just frame), Incomplete Somersault and Down Strike, Jin's WS+3 and Black Out, and all DR's follow-ups off
# the sheet).
DEEP_FOLLOWUPS = ('deviljin', 'paul', 'jin')
# DR's condition 143: the fighter is character <parameter> (26 opens Devil Jin's Mukurowari from the jump and
# Ultimate Tackle from the side step, both played by his Command List demos; 2, 8, 10... open the side
# steps' moves of others). Always true for his own moves, so an entry with nothing else is unconditional.
# Jin is 9 (read at +0x3E in PPSSPP): his u/f+1+2 throw (Thrmv_B2_00) is 143 9 from the jump's take-off, the
# 151 0 moves of move_sheet.PLAYED (u/f+2, u+2) come in through it too. Paul is 0: his side step's 1 and 3
# (Pl_sdhzlp00, Pl_shiranui: SS+1 / SS+3 of the wiki's movelist) are 143 0.
DR_CHARACTER = {'deviljin': 26, 'jin': 9, 'paul': 0}
# DR's condition 151, parameter 0: the fighter played by a person, 1 by the computer (Devil Jin's 1, 1, 2: Jz_lpf
# -> Jz_rp1 on 2 under 151 0, on a hit alone under 151 1; DR's Command List demo plays it as a person).
DR_PLAYED = (151, 0)
# DR's condition 101: the opponent is down; Tekken 3's condition 53, the opponent's move lying (attribute 4,
# cancel_cond_test). Devil Jin's d/f+1+2 goes on to Hellfire Incinerator (Dv_beam_00d -> Dv_beam_dw, its
# Command List entry 59) on a fighter down (on_down(), the characters of DEEP_FOLLOWUPS).
DR_OPPONENT_DOWN, T3_OPPONENT_DOWN = (101, 0), 53
# Devil Jin's Thrmv_B2_01 (the throw into the laser, Dv_Beam_n) is stored N,f,d+1, DR takes the half circle
# f,b,d/b,d,d/f,f+1+2 (its Command List demo 75 and the sheet).
# Paul's Burning Spear (Pl_Fvlbo00) is stored N,f,d,d/b+1 as Devil Jin's Laser Cannon: DR takes b, f+1 (filmed
# 2026-10-31; Tekken 3 played f+1 there).
COMMANDS = {'paul': {'Pl_Fvlbo00': 'N,b,N,f+1', 'Thrmv_B2_00': 'N,f,N,f+1+2'},   # Push Away, stored as a 5-button chain
            'jin': {'Thrmv_B1_L0': 'd,d/b,b+1+3', 'Jz_karate01': 'N,b,N,f+2'},   # Evil Intent, stored 3+4,N,N+1+2
            'deviljin': {'Thrmv_B1_L0': 'd,d/b,b+1+3', 'Thrmv_B2_01': 'f,b,d/b,d,d/f,f+1+2'}}
# A DR character TTT1 does not have: no TTT1 move left in his pack (the user, 2026-10-31: Devil Twister,
# SS+2, played Jin's TTT1 move). An attack still on its TTT1 animation becomes DR's move of that command
# from the same state, or goes (no_ttt1()).
NO_TTT1 = ('deviljin', 'paul', 'jin')
# Back turned: DR's conditions 57 (the back to the opponent), 65 and 66 (turned away on one side or the other:
# Co_R_rp00L / Co_R_lp00R), on the stance's and the jumps' own entries; Tekken 3's 36 (opp_angle_diff
# > 0x4000), 37 and 38 (unk_02E 110..180 / 180..250 degrees: TTT1 puts its L move under 37, its R one under
# 38 and on 1+2 under 36, as DR its 65 / 66 / 57; t3-ps1 cancel_cond_test). back_turned() makes DR's moves,
# no_ttt1() sends TTT1's entries under these conditions to them.
BACK_TURNED = {36: (57, 0), 37: (65, 0), 38: (66, 0)}
BACK_TURNED_DR = ('paul', 'jin')                  # Devil Jin's pack, validated without them, left as it is
# TTT1's throws and what follows them stay (no_ttt1()): DR's tackle mounts (Co_tacF_n, Co_tp_*, Ul_*: a pair
# of moves, attacker and victim, for every punch and escape) are not converted yet, and without TTT1's Paul's
# d/b+1+2 and Jin's running tackle stopped at the grab (2026-10-31).
TTT1_THROWS_KEPT = ('paul', 'jin')
# The side steps: the pack's step (u or d tapped, then N: 15 frames, then its 25-frame end) on DR's whole
# step (sSTEP_01L / R, 40 frames, SS in DR), the side matched by heading (+90 degrees the left one).
# Devil Twister (Dv_meiouken) is N+2 from it in DR, under condition 143 on him.
SIDE_STEPS = {'deviljin': (('8003d06c', '8003d0a0', 'sSTEP_01L'), ('8003d0d4', '8003d108', 'sSTEP_01R')),
              'paul': (('8003d344', '8003d378', 'sSTEP_01L'), ('8003d3ac', '8003d3e0', 'sSTEP_01R'))}
STANCES = {'jin': ('Jz_zettai_0', 'Jz_hadohB00', 'tac02xk'),   # DR's order on b+1+2: Power Stance first
           # Devil Jin's flight (3+4, then Dv_beam_02off: 1+2 Infernal Destruction, the user's choice of 2026-10-29)
           'deviljin': ('Dv_beam_02', 'Dv_beam_02off')}


def validate(p):
    """The runtime's checks on a combat pack (src/tekken3_ttt1_pack.h ttt1_pack_validate), so a
    pack the game would refuse ("rejected invalid combat pack") stops the build. Returns the
    first failure, or None."""
    w = lambda o: struct.unpack_from('<I', p, o)[0]
    h = lambda o: struct.unpack_from('<H', p, o)[0]
    size = len(p)
    if size < 32 or w(0) != 0x314d554a or w(4) != 4 or w(8) != size: return 'header'
    n, r, ro = w(12), w(28), w(20)
    if not n or n > 2048 or w(16) >= n or r != 32 + n * 16 or r + n * 56 > size or ro < r + n * 56 or w(24) != 4 * n:
        return 'record table'
    po = ro + 16 * n; patterns = w(po); po += 4
    for i in range(patterns):
        cmd, words = h(po), h(po + 2); po += 4
        if cmd != 0xe000 + i or not 3 <= words <= 65 or not 1 <= h(po) <= 60 or h(po + (words - 1) * 2): return f'pattern {i}'
        po += words * 2
    if po != size: return 'patterns end'
    target = lambda i: i == 3 or 8192 <= i < 8192 + n
    for i in range(n):
        rp, prov = r + i * 56, w(32 + i * 16 + 4)
        clip, cp, nc = w(rp), w(rp + 12), w(32 + i * 16 + 12)
        if not 0x80010000 <= prov < 0x80400000: return f'record {i}: provenance {prov:#x}'
        if w(32 + i * 16 + 8) != rp or [w(ro + i * 16 + 4 * k) for k in range(4)] != [rp, rp + 12, rp + 28, rp + 32]:
            return f'record {i}: relocations'
        if clip < r + n * 56 or clip > ro - 8 or clip & 3 or (w(clip) & 0xffffff00) != 0x4a554e00 or w(clip + 4) != 57 \
                or not p[clip] or p[clip] * 114 > ro - clip - 8: return f'record {i}: clip'
        if cp < r + n * 56 or cp > ro or cp & 3 or not nc or nc > 4096 or nc * 12 > ro - cp or not target(h(rp + 16)):
            return f'record {i}: cancels'
        for j in range(4):
            if p[rp + 40 + j] >= 24 and not 0x3c <= p[rp + 40 + j] <= 0x3f: return f'record {i}: limb'
        for j in range(nc):
            c = cp + j * 12; cmd = h(c)
            if not target(h(c + 6)) or p[c + 2] or p[c + 3] >= 85 or \
                    (cmd >= 0x8000 and cmd not in (0xc000, 0xc001, 0xc002) and not 0xe000 <= cmd < 0xe000 + patterns):
                return f'record {i}: cancel {j}'
        if h(cp + (nc - 1) * 12) != 0xc000: return f'record {i}: no end entry'
    return None


def num(v):
    try: return int(str(v).replace('+', ''))
    except ValueError: return None


def sheet(name):
    return {r['commande']: r for r in csv.DictReader(open(ROOT / f'fiches/dr-{name}.tsv', encoding='utf-8'), delimiter='\t')}


def bounds_of_new(rows, r):
    """DR's numbers bounded by the Tekken 3 moves of the same level (A2 rule 15): first active
    frame no faster than the fastest, block advantage no better than the best, damage in range."""
    level = r['DR niveau']
    t3 = [x for x in rows.values() if x['T3 niveau'] == level and num(x['T3 1re active'])]
    first, damage, block = num(r['DR 1re active']), num(r['DR dégâts']), num(r['DR garde'])
    out = dict(first=first, damage=damage, block=block, notes=[])
    # No damage, no attack to bound: Jin's Power Stance (Jz_zettai_1, active from frame 1 to 55)
    # came out a 40 damage unblockable at frame 43.
    if t3 and damage:
        fastest = min(num(x['T3 1re active']) for x in t3)
        if first < fastest: out['notes'].append(f'first {first} -> {fastest} (fastest T3 {level})'); out['first'] = fastest
        dmg = [num(x['T3 dégâts']) for x in t3 if num(x['T3 dégâts']) is not None]
        lo, hi = min(dmg), max(dmg)
        if not lo <= damage <= hi:
            out['notes'].append(f'damage {damage} -> {min(max(damage, lo), hi)} (T3 {level} {lo}..{hi})')
            out['damage'] = min(max(damage, lo), hi)
        guards = [num(x['T3 garde']) for x in t3 if num(x['T3 garde']) is not None]
        if block is not None and guards and block > max(guards):
            out['notes'].append(f'block {block:+d} -> {max(guards):+d} (best T3 {level})'); out['block'] = max(guards)
    return out


class Builder:
    def __init__(s, name, pack_dir=None):
        import move_sheet as MS
        # The pack radical: the native's name (Paul-TTT1-* -> Paul-DR-*), or a DR character's (DevilJin-TTT1-*,
        # the easter egg's pack, -> DevilJin-DR-*, the DR family's files of docs/DR-ROSTER.md).
        dr_name, key, s.Name = X.fighter(name)
        s.name = name
        s.rows = sheet(name)
        s.pack_dir = Path(pack_dir) if pack_dir else MS.main_pack_dir()
        s.dr = MS.DR(dr_name)
        s.ttt1 = MS.TTT1(key, s.pack_dir, s.Name)
        s.pack = Pack((s.pack_dir / f'{s.Name}-TTT1-combat.jmv').read_bytes())
        s.ttt1_lists = [tuple(s.pack.cancels(k)) for k in range(len(s.pack.records))]   # as TTT1 wrote them
        s.cv = X.Converter(name)
        s.by_name = {m['name']: m['index'] for m in s.dr.m.moves}
        s.by_addr = {f'{s.ttt1.meta(i)[1]:08x}': i for i in range(s.ttt1.count)}
        s.report = dict(moves={})
        s.dr2rec = {s.dr.m.stance: s.pack.neutral}   # DR move -> pack record playing it
        s.timemap, s._parents, s.whole_done = {}, None, {}
        s.shared = []
        s.throw_sides = []
        s.throw_victims = []          # the victims' records of the throws both games have (throw_ends())
        s.pending = []                               # hidden()'s follow-ups for states()
        s.own = set()                                # DR stances made by stances()
        s.tables = bytearray((s.pack_dir / f'{s.Name}-TTT1-tables.jst').read_bytes())
        s.ttt1_clips = {s.pack.word(k, 0) for k in range(len(s.pack.records))}   # no_ttt1()
        s.step_tails = {}                            # side_steps(): tail record -> (DR move, its first frame)
        ground = Path(__file__).with_name('data') / f'dr_ground_turns_{name}.json'
        s.ground_turns = {k: v for k, v in json.loads(ground.read_text()).items() if not k.startswith('_')} if ground.exists() else {}
        turns = Path(__file__).with_name('data') / f'dr_turns_{name}.json'
        s.turns = {k: v for k, v in json.loads(turns.read_text()).items() if not k.startswith('_')} if turns.exists() else {}

    def dr_bounds(s, mi, anim):
        n = s.cv.ch.frames(anim)
        mv = s.dr.m.moves[mi]
        free = s.dr.step(mi)[0]
        return [0, mv['first'], mv['last'], min(free, n - 1), n - 1]

    def rec_bounds(s, ri):
        b = s.pack.records[ri]
        frames = struct.unpack_from('<I', b, 24)[0] & 0xff
        free = next((e[5] for e in s.pack.cancels(ri) if e[0] == 0xc000 and e[5]), frames)
        return [0, b[45], b[46], min(free, frames - 1), frames - 1]

    def clip(s, mi, dst):
        anim, lacet = s.cv.ch.move(mi)
        src = s.dr_bounds(mi, anim)
        times, stretch = X.retime(src, dst)
        s.timemap[mi] = (src, dst)
        # A segment of one frame or none (DR's single active frame against two) is a hold, not a stretch.
        spans = [b - a for a, b in zip(dst, dst[1:]) if b > a]
        flagged = any((x > 1.5 or x < 1 / 1.5) and span > 1 for x, span in zip(stretch, spans))
        return s.turned(mi, s.cv.poses(anim, lacet, times), times), dict(dr=src, target=dst, stretch=[round(x, 2) for x in stretch], flagged=flagged)

    def turned(s, mi, poses, times):
        """poses turned about the fighter's floor point by DR's own turn of the move (data/dr_turns_<name>.json,
        measured in PPSSPP): DR turns Jin 20 degrees through d+4's sweep (3 a frame, frames 8 to 16), which
        its animation lacks; without it the foot passed Paul's knee by and the sweep missed. A DR turn to
        the left is one to the right in Tekken 3's channels (C turns y over: the measured sign, -1, hit)."""
        curve = s.turns.get(s.dr.m.moves[mi]['name'])
        if not curve: return poses
        out, prev = [], None
        for p, t in zip(poses, times):
            d = -float(np.interp(t, range(len(curve)), curve))
            a = np.radians(d)
            Ry = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
            W = X.ttt1_world(p)
            j = X.ttt1_joints({r: Ry @ W[r] for r in W}, prev); prev = j
            out.append([(X.s16(p[0]) + round(d * 65536 / 360)) & 0xffff, p[1], p[2], *[int(round(v)) & 0xffff for v in j]])
        return out

    def common(s, cmd, r):
        """A move both games have: the TTT1 record, the reference's numbers (Tekken 3, else TTT1),
        DR's animation retimed onto them. Where Tekken 3 frees the attacker at another frame than
        TTT1, the record's end entry and its clip move by as much (the block advantage follows)."""
        mi, ri = s.by_name[r['DR coup']], s.by_addr[r['TTT1 coup']]
        ref = 'T3' if r['T3 coup'] else 'TTT1'
        first, last, dmg = num(r[f'{ref} 1re active']), num(r[f'{ref} dernière active']), num(r[f'{ref} dégâts'])
        rec = s.pack.records[ri]
        if first is not None and ((rec[45], rec[46]) != (first, last) or
                                  (dmg is not None and (struct.unpack_from('<I', rec, 20)[0] & 0x3fff) != dmg)):
            s.pack.set_timing(ri, first, last, dmg if dmg is not None else struct.unpack_from('<I', rec, 20)[0] & 0x3fff)
        dst = s.rec_bounds(ri)
        if first is not None: dst[1:3] = [first, last]
        late = 0
        if ref == 'T3' and num(r['T3 libre']) is not None and num(r['TTT1 libre']) is not None:
            late = num(r['T3 libre']) - num(r['TTT1 libre'])
        if late:
            dst[3] += late; dst[4] += late
            s.set_free(ri, dst[3])
        poses, info = s.clip(mi, dst)
        s.pack.set_clip(ri, poses)
        s.dr2rec[mi] = ri
        s.report['moves'][cmd] = dict(kind=r['statut'], record=ri, reference=ref, free_moved=late, **info)

    def set_free(s, ri, free):
        entries = [list(e) for e in s.pack.cancels(ri)]
        for e in entries:
            if e[0] == 0xc000: e[5] = free
        s.pack.set_cancels(ri, [tuple(e) for e in entries])

    def parents(s, mi):
        """(DR move, its entry to mi: label, window start, end, starting frame), unconditional ones."""
        if s._parents is None:
            s._parents = {}
            m = s.dr.m
            def entries(addr, depth=0):
                # t5_moveset.Moveset.cancels with the windows: shared groups (0x8005) expanded.
                for k in range(512):
                    cmd, req, mid, ext, ds, de, sf, opt = struct.unpack_from('<IIIIHHHH', s.dr.ram, m.off(addr) + k * 24)
                    if cmd == 0x8005 and depth < 4:
                        yield from entries(m.lists['groupCancel'][0] + mid * 24, depth + 1); continue
                    if cmd in (0x8000, 0x8006): return
                    yield cmd, req, m.resolve(mid), ds, de, sf
            s._dests = {}
            # Bits 20..23 are buttons 1..4 held (Jz_Direct's win poses: 0x100000 Win_A ... 0xC00000 Win_E),
            # which t5's label reads as no input: Co_jplp00B -> Jz_guard_00 on 1+2 held (u/b+1+2) became
            # u/b+1's own follow-up, the jump punch left at its frame 1 for Avenger.
            held = lambda cmd: s.name in REORDER and cmd and not cmd & ~0xff00000
            for p in range(len(m.moves)):
                for cmd, req, d, ds, de, sf in entries(s.dr.raw[p][5]):
                    if held(cmd): continue
                    if d < len(m.moves) and m.usable(cmd): s._dests.setdefault(p, []).append((m.label(cmd).replace(' ', ''), d))
                    if d < len(m.moves) and m.usable(cmd) and (m.unconditional(req) or s.own_character(req)):
                        s._parents.setdefault(d, []).append((p, m.label(cmd).replace(' ', ''), ds, de, sf))
        return s._parents.get(mi, [])

    def own_character(s, req):
        """A DR requirement list holding nothing but conditions always true for this fighter played by a
        person: 143 on itself (DR_CHARACTER), 151 parameter 0 (DR_PLAYED)."""
        me = DR_CHARACTER.get(s.name)
        conds = s.dr_conds(req)
        return me is not None and bool(conds) and all(c in ((143, me), DR_PLAYED) for c in conds)

    def own_only(s, p, mi, code):
        """DR enters mi from p on this command only by entries open to this fighter (own_character()), none
        unconditional (Jz_jprk00: u+2+4 under 143 9, u+4 unconditional)."""
        m = s.dr.m
        reqs = [req for cmd, req, d in m.cancels(m.moves[p]['cancel'])
                if d == mi and m.usable(cmd) and s.same_code(m.label(cmd).replace(' ', ''), code)]
        return bool(reqs) and not any(m.unconditional(r) for r in reqs)

    def links(s, p):
        """move_sheet.DR.links, with the entries open to this fighter only (own_character())."""
        out = s.dr.links(p)
        if s.name not in DR_CHARACTER: return out
        m = s.dr.m
        for cmd, req, d in m.cancels(m.moves[p]['cancel']):
            if d < len(m.moves) and m.usable(cmd) and s.own_character(req): out.append((m.label(cmd).replace(' ', ''), d))
        return out

    def same_code(s, label, code):
        try: return s.code_of(label) == code
        except (ValueError, KeyError): return False

    def code_of(s, label):
        # No input: the clip's own follow-up, command 0x0010 in the packs (as TTT1 writes it; 0 made
        # Pl_Tetsuzan -> Pl_TetsuzanA at frame 11 replay Tetsuzan from its start, without the hit).
        if label in ('', '-'): return 0x10
        if ',' in label: return s.sequence(label)
        names = {'d/b': 1, 'd': 2, 'd/f': 3, 'b': 4, 'N': 5, 'f': 6, 'u/b': 7, 'u': 8, 'u/f': 9}
        parts = label.split('+')
        dirs = 0
        # 'b|N|f+2': button 2 with any of these directions, all of them in the mask (taking the
        # last one alone made it f+2).
        if all(x in names for x in parts[0].split('|')):
            for x in parts.pop(0).split('|'): dirs |= 1 << (names[x] - 1)
        return sum(1 << (int(b) - 1) for b in parts) | dirs << 5

    def hook(s, cmd, mi, ri, own_only=False, enter_as=None):
        """Entries into new record ri: from DR's parent move P, into the pack lists that already lead
        to P's other moves (its siblings: the stance's lists for a move from the stance, the
        rising lists for d, f, x...) and P's own record. An entry of the same command there is
        redirected (b+2 did 2 in TTT1); else one is put at the head of the list, DR's window.
        enter_as: a record whose entry in each list gives the transition (a new throw, as 1+3)."""
        done, seen = [], set()
        stance = s.dr.m.stance
        from_stance = {d for _, d in s.dr.links(stance)}
        for p, label, ds, de, sf in s.parents(mi):
            code = s.code_of(COMMANDS.get(s.name, {}).get(s.dr.m.moves[mi]['name'], label))
            # Siblings that say where P is in the pack: its own moves, not those the stance has too
            # (d, f + 1+2's parent links the jab as well: every list leading to the jab got 1+2).
            sib = {s.dr2rec[d] for _, d in s.dr.links(p) if d in s.dr2rec and d != mi and (p == stance or d not in from_stance)}
            lists = set()
            if p in s.dr2rec: lists.add(s.dr2rec[p])
            if p == stance: lists.add(s.pack.neutral)
            targets = {BASE_ID + x for x in sib}
            # A stance of DR's own (stances()) is its record only: its crouch dash sibling put Mental
            # Alertness 2's 1 in every list leading to the crouch dash.
            for k in range(0 if own_only or p in s.own else len(s.pack.records)):
                if k == ri: continue
                # A list stands for P when it leads to most of P's siblings it could (a third at least,
                # two at least), not when one shared follow-up is there.
                hits = {e[3] for e in s.pack.cancels(k) if not e[1] and e[3] in targets}
                if len(hits) >= max(1, min(2, len(targets)), len(targets) // 3): lists.add(k)
            # The TTT1 record one of these goes on into at its end, when DR has no move for it (TTT1's
            # walk back 7 loops in 8, Jz_sWALKB is 7 only): Devil Jin's d, d/b, b+1+3 at the rhythm of
            # DR's demo, b held before the buttons, came out walking back. An input sequence only,
            # whose steps go through these records.
            mapped = set(s.dr2rec.values())
            for k in list(lists):
                if code >= 0xe000 and k < len(s.ttt1_lists):
                    lists |= {e[3] - BASE_ID for e in s.ttt1_lists[k] if e[0] == 0xc000 and e[3] >= BASE_ID
                              and e[3] - BASE_ID not in mapped and e[3] - BASE_ID != ri}
            # DR's window, in the parent's retimed frames when it was retimed.
            tm = s.timemap.get(p)
            w = [int(round(np.interp(x, tm[0], tm[1]))) if tm and x < 255 else x for x in (ds, de, sf)]
            # DR's start 255 on a window to 255 (st2cr_00BRv to Thrmv_B1_L0) is TTT1's 1 there: at 255
            # Tekken 3 entered the throw past its end, the attempt stood up at once.
            if w[2] >= 255 and w[1] >= 255: w[2] = max(w[0], 1)
            # An entry open to this fighter only (143 on itself, 151 0) goes into another DR move's record
            # only when DR's list of that move has it too: Jin's u+2+4 (143 9, the stance's kick) went into
            # the jump's take-off, where DR has 2 to the punch (u, then 2+4: Co_jprp03H in DR, the kick in
            # Tekken 3), and u/f+1+2 into the crouch's, where DR keeps the jump punch.
            rec2dr = {v: k for k, v in s.dr2rec.items()}
            own = s.name in DR_CHARACTER and s.own_only(p, mi, code)
            for k in sorted(lists):
                q = rec2dr.get(k)
                if own and q is not None and q != p and not any(d == mi and s.same_code(l, code) for l, d in s._dests.get(q, ())):
                    continue
                if (k, code) in seen:
                    # A second DR entry of that command to this move, the next frames (Pl_t_slpF's b to
                    # Bodyswy on 14..14, then 15..16, both leaving at 16): one window.
                    entries = [list(e) for e in s.pack.cancels(k)]
                    joined = False
                    for e in entries:
                        if e[0] == code and not e[1] and e[3] == BASE_ID + ri and e[7] == min(w[2], 255) and e[6] + 1 == w[0]:
                            e[6] = min(w[1], 255); joined = True
                    if joined: s.pack.set_cancels(k, [tuple(e) for e in entries])
                    continue
                seen.add((k, code))
                entries = [list(e) for e in s.pack.cancels(k)]
                # The same command there leads to another move: redirected, unless DR goes from P to
                # that move too (by an earlier, conditional entry: Deathfist before Pl_sidrp from the
                # qcf state), then DR's order is kept, the new entry right after it.
                same, kept = [], None
                for i, e in enumerate(entries):
                    if e[0] == code and not e[1]:
                        old = rec2dr.get(e[3] - BASE_ID)
                        # Or when that entry is the list's only way to its move (Deathfist, reached in the
                        # TTT1 graph by 2 from a rising record where DR's 2 is Pl_sidrp): Tekken 3's
                        # command stays its move's (A2 rule 14). b+2 doing 2 is left: 2 still leads there.
                        only = not any(x[3] == e[3] and x[0] != code for x in entries)   # another command, not a twin entry
                        if old is not None and old != mi and (only or any(d == old and s.same_code(l, code) for l, d in s._dests.get(p, ()))):
                            kept = i if kept is None else kept
                        else: same.append(e)
                if same:
                    # DR has another move on the same command from P (Dj_rk00: 3 on frame 1 the flight, 3 on
                    # 1..5 Dv_hasai): the redirected entry takes DR's window, not TTT1's (1..5 took 4~3).
                    # In P's own record only (the lists standing for P keep their windows).
                    twin = s.name in TWIN_WINDOWS and k == s.dr2rec.get(p) and any(d != mi and s.same_code(l, code) for l, d in s._dests.get(p, ())) \
                        and any(d == mi and s.same_code(l, code) for l, d in s._dests.get(p, ()))
                    for e in same:
                        e[3] = BASE_ID + ri
                        if twin and w[1] < e[6]: e[5:8] = [max(w[0], 0), min(w[1], 255), min(w[2], 255)]
                        # DR leaves the parent at a set frame before its hit (pol_sk00 -> pol_sk00G
                        # at 12, its kick at 15): the follow-up's hit replaces the parent's. TTT1's
                        # window (d+4 -> 2: 1..14, start 14) let d+4 hit at 14 and pol_sk00G again
                        # at 15 (3 hits to DR's 2). The entry that goes on with the clip (transition
                        # 2, G plays pol_sk00's animation), not the late one restarting it.
                        first = s.pack.records[k][45]
                        if (k == s.dr2rec.get(p) and first and w[1] == w[2] < first <= e[7] and e[4] & 0x3f == 2
                                and s.same_anim(p, mi)):
                            e[5:8] = [max(w[0], 0), min(w[1], 255), min(w[2], 255)]
                elif kept is not None:
                    e = list(entries[kept]); e[3] = BASE_ID + ri; e[5:8] = [max(w[0], 0), min(w[1], 255), min(w[2], 255)]
                    entries.insert(kept + 1, e)
                else:
                    b0 = next((e[4] for e in entries if not e[1] and e[3] in targets), 12)
                    # A new throw does not take a sibling's 8: walking back took Devil Jin's d, d/b, b+1+3
                    # from the crouch two frames in. It enters as 1+3's attempt from that list then.
                    if enter_as is not None and b0 == 8:
                        b0 = next((e[4] for e in entries if not e[1] and e[3] == BASE_ID + enter_as), b0)
                    # A follow-up without input: DR's window is the parent's frame it leaves at.
                    # One that goes on playing the parent's animation (Pl_Tetsuzan -> Pl_TetsuzanA,
                    # DR at frame 12 after 11) continues the clip, transition 2 (TIPS: Kazuya
                    # 276 -> 277); another starts its own from frame 1 (rakuyo2 in DR), transition 6
                    # as the input entries (2 from d+4 to 895): 2 skipped rakuyo2's first 15 frames,
                    # its hit 14 frames early. Never 33, the paired throw state (TTT1 32,
                    # combat_semantics.transition): Jin was put in Paul's place and facing, playing
                    # the hit reaction as a throw's.
                    # The same holds for a move whose own animation goes on from the parent's pose at
                    # that frame (pol_sjk00FRv -> pol_sjk10F at 16: 5 degrees apart, 80 from its start):
                    # 6 replayed the jump from frame 1 and the 4 never came. An input entry to a move
                    # on the parent's animation continues it too (d/f+1 then b: Pl_t_slpFRv, 12 replayed
                    # the jab from frame 1).
                    if code == 0x10: b0 = 2 if s.continues(p, mi, sf) else 6
                    elif s.same_anim(p, mi): b0 = 2
                    # After the motions and conditional entries (qcf, qcb, f,f... first in a T3 list:
                    # put at the head, b+2 took d, d/b, b+2 and d, f, 2 from them), before the first
                    # plain entry of the same buttons (which would take the command first).
                    # Before the plain entries it is more specific than (Tekken 3 takes an entry whose
                    # buttons are all held: '1' took b+1+4, 2+4 took f+2+4, 2 took d, f, 1+2), unless
                    # DR puts that entry's move first from P too (Deathfist before Pl_sidrp from the
                    # rising state), or DR does not reach that move from P and its buttons are ours
                    # (Tekken 3's command stays its move's, A2 rule 14).
                    mask = lambda c: (c >> 5 & 0x1ff) or 0x1ff
                    order = {}
                    for i, (l, d) in enumerate(s._dests.get(p, ())): order.setdefault(d, i)
                    mine = order.get(mi)
                    at = next((i for i, x in enumerate(entries) if x[0] == 0xc000), len(entries))
                    general = [i for i, x in enumerate(entries) if not x[1] and x[0] < 0x8000 and x[0] & 0xf
                               and not (x[0] & 0xf) & ~(code & 0xf) and mask(x[0]) & mask(code)]
                    if code >= 0xe000:
                        # An input sequence: before the plain commands, which its last step would match
                        # first (d/b+1 before N,f,d,d/b+1), after the other sequences and conditions.
                        general = []
                        at = min(at, next((i for i, x in enumerate(entries) if not x[1] and x[0] < 0x8000), at))
                    if general: at = min(at, general[0])
                    for i in general:
                        x = entries[i]
                        old = rec2dr.get(x[3] - BASE_ID) if x[3] >= BASE_ID else None
                        if old is None or old == mi: continue
                        oi = order.get(old)
                        # Only an entry of the same buttons can stay ahead: DR tells moves apart by their
                        # exact buttons, Tekken 3 lets fewer buttons match (b+1 took b+1+4 when walking back).
                        if x[0] & 0xf != code & 0xf: continue
                        if (oi is not None and mine is not None and oi < mine) or (oi is None and x[0] & 0x1f == code & 0x1f):
                            at = max(at, i + 1)
                    end = min(w[1], 255)
                    if code == 0x10 and k == s.dr2rec.get(p):
                        # Tekken 3 tests the list from the frame after the one a transition 2 enters at:
                        # u/f+3, 4 enters pol_sjk00FRv at 16 (TTT1's entry), so 17 is its first test
                        # and the follow-up's 16..16 never came. The window then runs to that frame.
                        late = [x[7] + 1 for kk in range(len(s.pack.records)) for x in s.pack.cancels(kk)
                                if x[3] == BASE_ID + k and x[4] & 0x3f == 2 and x[0] != 0xc000 and x[7] + 1 > end]
                        if late: end = min(max(late), 255)
                    entries.insert(at, [code, 0, 0, BASE_ID + ri, b0, max(w[0], 0), end, min(w[2], 255)])
                s.pack.set_cancels(k, [tuple(e) for e in entries]); done.append((k, label, 'redirected' if same else 'added'))
        return done

    def like_for(s, r):
        """The TTT1 record of the common move whose DR hit and counter reactions and level are this
        move's (hit first, then counter): its reactions, sounds and properties come with it."""
        best, score = None, -1
        for c, x in s.rows.items():
            if not x['TTT1 coup'] or x['TTT1 coup'] not in s.by_addr or x['statut'].split(' ')[0] not in ('identique', 'modifié'):
                continue
            sc = 4 * (x['DR réaction touche'] == r['DR réaction touche']) + 2 * (x['DR réaction contre'] == r['DR réaction contre']) \
                + (x['DR niveau'] == r['DR niveau'])
            if sc > score: best, score = c, sc
        return best

    def preludes(s, mi):
        """DR moves without a hit that play nothing but move mi at their end (move_sheet.DR.prelude_of:
        Co_jplk00, Jin's take-off for u+3)."""
        if not hasattr(s, '_preludes'):
            s._preludes = defaultdict(list)
            for p in range(len(s.dr.m.moves)):
                if not s.dr.is_attack(p):
                    d = s.dr.prelude_of(p)
                    # Or its one follow-up, an attack without input (Dv_beam_04ex: the flight's dive, then
                    # Dv_beam_05 from its frame 31).
                    if d is None and s.name in DEEP_FOLLOWUPS: d = s.lead_of(p)
                    if d is not None and s.dr.links(p) == [('-', d)]: s._preludes[d].append(p)
        return s._preludes.get(mi, [])

    def lead_of(s, p):
        """The attack move p (without a hit) goes on to without input, its only follow-up; None else."""
        ls = s.dr.links(p)
        return ls[0][1] if len(ls) == 1 and ls[0][0] == '-' and s.dr.is_attack(ls[0][1]) else None

    def prelude(s, p, ri):
        """A record on prelude p's animation whole (copied from the neutral), ending into record ri at its
        last frame, entered as DR enters p (u+3 from the stance, the walks, the runs; 3 from a jump).
        Or at DR's frame, when DR goes on before its end: Jin's WS+3 is Co_s_tlk00 then Co_s_tlk01 from
        frame 5 (the user, 2026-10-31: Tekken 3 played Co_s_tlk00's 64 frames, a kick past the victim)."""
        k = s.pack.add_record(s.pack.neutral, NEW_PROVENANCE + 4 * (len(s.pack.records) - s.ttt1.count))
        anim, lacet = s.cv.ch.move(p)
        n = min(s.cv.ch.frames(anim), 255)
        # DR's frame, one frame of DR's (5..5; not a window: Devil Jin's flight goes on to its dive within
        # 1..90): the clip ends there, Tekken 3 taking the end entry at the clip's end only.
        d = next((x for x, r in s.dr2rec.items() if r == ri), None)
        w = next(((ds, de, sf) for q, l, ds, de, sf in s.parents(d) if q == p and l in ('', '-')), None) if d is not None else None
        start = n
        if w and 0 < w[0] == w[1] < n - 1: n, start = w[0] + 1, min(w[2], 255) or w[0]
        s.pack.set_clip(k, s.cv.poses(anim, lacet, list(range(n))))
        s.pack.set_cancels(k, [(0xc000, 0, 0, BASE_ID + ri, 6, n, 255, start)])
        s.dr2rec[p] = k
        hooks = s.hook(s.dr.m.moves[p]['name'], p, k)
        if not hooks: del s.dr2rec[p]
        return hooks

    def feint(s, d):
        """A DR move without a hit, entered on a press, that waits for another press to go on to an
        attack: Jin's 10 hit combo, f+2, 3, 3, 3 is Jz_10comb4 (no hit), the next 2 within 1..30 its
        Jz_10comb4_3; without a record for it the pack stopped at f+2, 3, 3 (COMBO TRAINING, 2026-11-08).
        A record on its animation whole (copied from the neutral, as prelude()), ending where DR ends it
        (the stance), entered as DR enters it; hidden() then adds its follow-ups. Returns the record or None."""
        k = s.pack.add_record(s.pack.neutral, NEW_PROVENANCE + 4 * (len(s.pack.records) - s.ttt1.count))
        anim, lacet = s.cv.ch.move(d)
        n = min(s.cv.ch.frames(anim), 255)
        w = s.dr_end(d)[1]
        if w and w < n - 1: n = w + 1
        s.pack.set_clip(k, s.cv.poses(anim, lacet, list(range(n))))
        w = min(w or n, n)
        rest = s.dr_rest(d)
        end = BASE_ID + s.dr2rec[rest] if rest in s.dr2rec else 3
        s.pack.set_cancels(k, [(0xc000, 0, 0, end, 6, w, 255, w)])
        s.dr2rec[d] = k
        if not s.hook(s.dr.m.moves[d]['name'], d, k, own_only=True):
            del s.dr2rec[d]; return None
        return k

    def wrong_ends(s):
        """The attacks whose record ends into another record than the one of the move DR plays at
        their end, when that move has one: [(command or DR name, record, goes to, DR's)]. A record
        copied from another move kept that move's end (Devil Jin's d+4 played 1+4's follow-through)."""
        cmd_of = {v['record']: c for c, v in s.report['moves'].items() if isinstance(v, dict) and 'record' in v}
        out = []
        for mi, k in sorted(s.dr2rec.items()):
            if not s.dr.is_attack(mi): continue
            want = s.dr2rec.get(s.dr_end(mi)[0])
            # 3: Tekken 3's own stance, the neutral record's move.
            ends = [s.pack.neutral if e[3] == 3 else e[3] - BASE_ID for e in s.pack.cancels(k) if e[0] == 0xc000]
            if want is None or not ends or ends[0] == want: continue
            out.append((cmd_of.get(k, s.dr.m.moves[mi]['name']), k, ends[0], want))
        return out

    def new(s, cmd, r, own_only=False):
        mi = s.by_name[r['DR coup']]
        like_cmd = s.like_for(r)
        like = s.by_addr[s.rows[like_cmd]['TTT1 coup']]
        # A take-off before the move (Co_jplk00, 14 frames): Tekken 3's bounds are on the whole startup.
        pre = [p for p in s.preludes(mi) if p not in s.dr2rec]
        # Or the one movement() put on a record already (Devil Jin's f+3, 14 frames before the kick).
        lead = max((s.cv.ch.frames(s.cv.ch.move(p)[0]) for p in pre or [p for p in s.preludes(mi) if p not in s.own]), default=0)
        if lead and num(r['DR 1re active']):
            b = bounds_of_new(s.rows, dict(r, **{'DR 1re active': str(num(r['DR 1re active']) + lead)}))
            b['first'] -= lead
        else: b = bounds_of_new(s.rows, r)
        anim, _ = s.cv.ch.move(mi)
        src = s.dr_bounds(mi, anim)
        shift = b['first'] - src[1]
        free = src[3] + shift
        if b['block'] is not None:
            # The block advantage aimed at (DR's, bounded) with the block reaction the copied record
            # gives: advantage = reaction's term - (free - first), the term read from that move's TTT1
            # numbers in the sheet (move_sheet.advantage).
            lr = s.rows[like_cmd]
            term = num(lr['TTT1 garde']) + num(lr['TTT1 libre']) - num(lr['TTT1 1re active'])
            free = b['first'] + term - b['block']
            # A sheet advantage read through crouched states (Jin's crouching jab: -190) would hold
            # the attacker for 220 frames: DR's own free frame then.
            if free > src[4] + shift + 30: free = src[3] + shift
            # Nor free before its hit ends: Hellfire Cannon's +24 on block (u+1+2, active to 35) gave
            # 13, and Tekken 3 cut the laser there.
            if free <= src[2] + shift: free = src[3] + shift
        dst = [0, b['first'], src[2] + shift, free, free + src[4] - src[3]]
        # Its provenance: an address in TTT1's RAM range (ttt1_pack_validate), at the top, that no
        # TTT1 record has.
        ri = s.pack.add_record(like, NEW_PROVENANCE + 4 * (len(s.pack.records) - s.ttt1.count))
        s.pack.set_timing(ri, b['first'], dst[2], b['damage'])
        level = s.dr.m.moves[mi]['hitlevel'] & 0xffff
        s.pack.set_level(ri, level)                  # T5's coding, as the record's (pack_edit.set_level)
        s.pack.records[ri][40:44] = bytes(s.limbs(mi))
        poses, info = s.clip(mi, dst)
        s.pack.set_clip(ri, poses)
        end = [e for e in s.pack.cancels(like) if e[0] == 0xc000][:1]
        if not end: raise SystemExit(f'{cmd}: {like_cmd}\'s record has no end entry')
        e = list(end[0]); e[5] = dst[3]
        # Its own end as in DR (Devil Jin's d+4 into the crouch, cKAM__00_), not the copied move's
        # (1+4's Jz_mama01a, which played 1+4's follow-through after it).
        back = s.dr2rec.get(s.dr_end(mi)[0])
        if back is not None and not (back == s.pack.neutral and e[3] == 3): e[3] = BASE_ID + back
        s.pack.set_cancels(ri, [tuple(e)])
        s.dr2rec[mi] = ri
        beam = LASERS.get(s.name, {}).get(r['DR coup'])
        if beam:
            s.pack.records[ri][40:44] = bytes((LASER_LIMB, beam, 0, 0))
            old = s.by_addr.get(r['TTT1 coup']) if r.get('TTT1 coup') else None
            if old is not None and old != ri:
                for k in range(len(s.pack.records)):
                    es = s.pack.cancels(k)
                    new = [(*e[:3], BASE_ID + ri, *e[4:]) if e[0] != 0xc000 and e[3] == BASE_ID + old else e for e in es]
                    if new != es: s.pack.set_cancels(k, new)
        hooks = s.hook(cmd, mi, ri, own_only)
        for p in pre: hooks += s.prelude(p, ri)
        # A take-off movement() already put on a record (Devil Jin's f+3, Dj_lk00F, on 281, the take-off of
        # TTT1's f+3, a move DR lacks): that record now ends into this one.
        if not hooks:
            for p in s.preludes(mi):
                k = s.dr2rec.get(p)
                if k is None or p in s.own: continue
                n = struct.unpack_from('<I', s.pack.records[k], 24)[0] & 0xff
                s.pack.set_cancels(k, [(0xc000, 0, 0, BASE_ID + ri, 6, n, 255, n) if e[0] == 0xc000 else e for e in s.pack.cancels(k)])
                hooks.append((k, 0xc000, 'end'))
        if not hooks: raise SystemExit(f'{cmd}: no list leads to it (no DR parent mapped)')
        s.report['moves'][cmd] = dict(kind=r['statut'], record=ri, like=like_cmd, level=f'{level:#x}', bounds=b,
                                      entries=len(hooks), entries_added=sum(h[2] == 'added' for h in hooks), **info)

    def hidden(s):
        """DR moves the sheet does not list (one command, one move), reached from a move converted:
        the late press of a just frame (f,f+2 then 1 on frames 1..14: Pl_harp01Err, the same move as
        Pl_harp01, then Pl_hazlp01 without input at frame 18; on 15..17 Pl_hazlpJST, the sheet's).
        A move with its parent's animation is a copy of the parent's record, any other a new move with
        the row the sheet would have given it. Returns [(DR move, record)]."""
        import move_sheet as MS
        ch = s.cv.ch
        anim_id = lambda i: ch.D.u32(ch.mot, ch.D.HDR + ch.D.u32(ch.mot, 0x1E0) + 76 * i + 8)
        attacks = {s.by_name[r['DR coup']] for r in s.rows.values() if r['DR coup'] in s.by_name}
        deep = s.name in DEEP_FOLLOWUPS
        def lead_in(d):
            a = s.dr.prelude_of(d)
            if a is None: a = s.lead_of(d)
            return a if a is not None and a not in s.dr2rec and s.dr.links(d) == [('-', a)] else None
        # Every DR move the pack plays leads on (the run's, the crouch's, Wind God Step's follow-ups).
        if deep: attacks |= set(s.dr2rec)
        done, reused = [], []
        for _ in range(16 if deep else 4):
            found = False
            for p, ri in list(s.dr2rec.items()):
                for label, d in (s.links(p) if deep else s.dr.links(p)):
                    # A move without a hit playing d at its end (Jz_10A_on04, then Jz_10A_onE4): its end.
                    at_end = deep and label == '-' and s.dr.prelude_of(p) == d
                    if d in s.dr2rec or p not in attacks or not (at_end or any(q == p for q, *_ in s.parents(d))): continue
                    mv = s.dr.m.moves[d]
                    if mv['damage'] >= 16384: continue             # throws: new_throw's
                    # The pack has it already: the record the parent's list gives for that command
                    # (the 10-hit strings' last hits, past the sheet's depth).
                    try: code = 0xc000 if at_end else s.code_of(label)
                    except (ValueError, KeyError): continue
                    have = [e[3] - BASE_ID for e in s.pack.cancels(ri) if e[0] == code and not e[1] and e[3] >= BASE_ID]
                    have = [x for x in have if x not in s.dr2rec.values() and x != s.pack.neutral]
                    # Only a record hitting when DR's move does (Decapitating Sword, active at 20, took
                    # TTT1's back jump, no hit: he hopped back and swung at nothing): else a new one.
                    if deep and mv['first']: have = [x for x in have if abs(s.pack.records[x][45] - mv['first']) <= 2]
                    # Nor, for a take-off without a hit, a TTT1 record that hits (Jz_bodylp00, Corpse Thrust's
                    # start on d+1, kept TTT1's crouching jab; Dv_jprk00F, Wraith Kick's, TTT1's u/f+4).
                    elif deep: have = [x for x in have if not s.pack.word(x, 5) & 0xffff]
                    if have:
                        s.dr2rec[d] = have[0]; done.append((mv['name'], have[0])); attacks.add(d); found = True
                        # DR's animation on the TTT1 record, retimed onto its frames (as common(): the
                        # 10-hit strings' last hits kept TTT1's clips; Paul's f,f+3, 4, d+4, pol_ki02L, too).
                        if (deep or s.name in NO_TTT1) and mv['first']:
                            poses, _ = s.clip(d, s.rec_bounds(have[0]))
                            s.pack.set_clip(have[0], poses)
                            reused.append((d, have[0]))
                        continue
                    if anim_id(d) == anim_id(p) and mv['first'] == s.dr.m.moves[p]['first']:
                        rj = s.pack.add_record(ri, NEW_PROVENANCE + 4 * (len(s.pack.records) - s.ttt1.count))
                        s.pack.set_cancels(rj, [e for e in s.pack.cancels(ri) if e[0] == 0xc000][:1])
                        s.dr2rec[d] = rj
                        if p in s.timemap: s.timemap[d] = s.timemap[p]
                        if not s.hook(mv['name'], d, rj, own_only=True): del s.dr2rec[d]; continue
                    elif deep and not mv['first'] and not mv['damage'] and label not in ('', '-')                             and s.dr.is_attack(p) and s.dr.links(d)                             and all(s.dr.is_attack(x) for _, x in s.dr.links(d)):
                        # A move without a hit that waits for a press (feint()): Jin's 10 hit combo.
                        if s.feint(d) is None: continue
                    elif mv['first'] or (deep and lead_in(d) is not None):
                        # A take-off without a hit (Dv_beam_04ex, the flight's dive before Dv_beam_05): the
                        # attack it plays, new() making the take-off's record and its entries.
                        a = d if mv['first'] else lead_in(d)
                        x = s.dr.row(a)
                        r = {'DR coup': s.dr.m.moves[a]['name'], 'DR niveau': x['level'], 'DR 1re active': str(x['first']),
                             'DR dégâts': str(x['damage']), 'DR garde': '' if x.get('block') is None else str(x['block']),
                             'DR réaction touche': x.get('hit_rx', ''), 'DR réaction contre': x.get('ch_rx', ''),
                             'statut': 'suite DR hors fiche'}
                        try: s.new(r['DR coup'], r, own_only=True)
                        except (SystemExit, KeyError, ValueError): continue
                        if d not in s.dr2rec: continue
                        if a != d: done.append((r['DR coup'], s.dr2rec[a])); attacks.add(a)
                    elif label in ('', '-') and not s.continues(p, d, next((sf for q, l, ds, de, sf in s.parents(d) if q == p), 0)):
                        # Made last (states()): the records after it keep their numbers.
                        if (p, d) not in s.pending: s.pending.append((p, d))
                        continue
                    else: continue
                    done.append((mv['name'], s.dr2rec[d])); attacks.add(d); found = True
            if not found: break
        s.deep_added = {k for _, k in done} if deep else set()
        # Nor TTT1's follow-ups without input that DR's move has not, once every follow-up has its record
        # (Decapitating Sword on TTT1's back jump punch went on to Co_jprp03B; Jz_10A_ma05 -> maE5 stays).
        for d, k in reused:
            mine = {BASE_ID + s.dr2rec[x] for l, x in s.dr.links(d) if l in ('', '-') and x in s.dr2rec}
            taken = {BASE_ID + r for r in s.dr2rec.values()}
            es = s.pack.cancels(k)
            keep = [e for e in es if e[0] != 0x10 or e[3] in mine or e[3] not in taken]
            if keep != es: s.pack.set_cancels(k, keep)
        return done

    def on_down(s):
        """DR's follow-ups without input on a fighter down (DR_OPPONENT_DOWN alone) from the attacks the pack
        plays: the move made as hidden() makes one, its entry under Tekken 3's condition (T3_OPPONENT_DOWN).
        Returns [(DR move, record)]."""
        if s.name not in DEEP_FOLLOWUPS: return []
        m, done = s.dr.m, []
        for p, k in list(s.dr2rec.items()):
            if not s.dr.is_attack(p): continue
            c = s.dr.raw[p][5]
            for i in range(64):
                cmd, req, mid, ext, ds, de, sf, _ = struct.unpack_from('<IIIIHHHH', s.dr.ram, m.off(c) + i * 24)
                if cmd in (0x8000, 0x8006): break
                d = m.resolve(mid)
                if cmd or s.dr_conds(req) != [DR_OPPONENT_DOWN] or d >= len(m.moves) or d in s.dr2rec or not s.dr.is_attack(d):
                    continue
                s.parents(d)
                s._parents.setdefault(d, []).append((p, '-', ds, de, sf))
                x = s.dr.row(d)
                r = {'DR coup': m.moves[d]['name'], 'DR niveau': x['level'], 'DR 1re active': str(x['first']),
                     'DR dégâts': str(x['damage']), 'DR garde': '' if x.get('block') is None else str(x['block']),
                     'DR réaction touche': x.get('hit_rx', ''), 'DR réaction contre': x.get('ch_rx', ''),
                     'statut': 'suite DR sur adversaire au sol'}
                try: s.new(r['DR coup'], r, own_only=True)
                except (SystemExit, KeyError, ValueError): continue
                ri = s.dr2rec.get(d)
                if ri is None: continue
                # Turning to him on the way (transition 14, rot_mode 2): DR's beam goes along the heading, at the
                # fighter down; Tekken 3's knockdown left Devil Jin 32 degrees off and the beam passed him by.
                s.pack.set_cancels(k, [(e[0], T3_OPPONENT_DOWN << 8, e[2], e[3], 14, *e[5:]) if e[0] == 0x10 and not e[1]
                                       and e[3] == BASE_ID + ri else e for e in s.pack.cancels(k)])
                done.append((m.moves[d]['name'], ri))
        return done

    def back_turned(s):
        """DR's attacks with the back turned (BACK_TURNED: entered under one of these conditions alone, from
        the stance or the jumps it takes off into), made as hidden() makes a move off the sheet, without
        entries: no_ttt1() gives them TTT1's. Not from a fighter down, where DR's 65 / 66 open the rising
        kicks (Co_AokilkL0 from dwDWN_01U). Returns [(DR move, record)]."""
        if s.name not in NO_TTT1 or s.name not in BACK_TURNED_DR: return []
        m, done, want = s.dr.m, [], {c for c in BACK_TURNED.values()}
        st = m.stance
        jumps = {d for cmd, req, d in m.cancels(m.moves[st]['cancel'])
                 if d < len(m.moves) and m.label(cmd).replace(' ', '') in ('u', 'u/f', 'u/b')}
        for p in [st, *sorted(jumps)]:
            for cmd, req, d in m.cancels(m.moves[p]['cancel']):
                if d >= len(m.moves) or d in s.dr2rec or not m.usable(cmd) or not req: continue
                c = s.dr_conds(req)
                mv = m.moves[d]
                if len(c) != 1 or c[0] not in want or not mv['damage'] or mv['damage'] >= 16384: continue
                x = s.dr.row(d)
                r = {'DR coup': mv['name'], 'DR niveau': x['level'], 'DR 1re active': str(x['first']),
                     'DR dégâts': str(x['damage']), 'DR garde': '' if x.get('block') is None else str(x['block']),
                     'DR réaction touche': x.get('hit_rx', ''), 'DR réaction contre': x.get('ch_rx', ''),
                     'statut': 'suite DR dos tourné'}
                try: s.new(r['DR coup'], r, own_only=True)
                except SystemExit:
                    # No list leads to it yet: no_ttt1()'s entries will.
                    if d not in s.dr2rec: continue
                    s.report['moves'][r['DR coup']] = dict(kind=r['statut'], record=s.dr2rec[d])
                except (KeyError, ValueError): continue
                if d in s.dr2rec: done.append((mv['name'], s.dr2rec[d]))
        return done

    def states(s):
        """The follow-ups hidden() left for state(): [(DR move, record)]."""
        done = []
        for p, d in s.pending:
            if d not in s.dr2rec and s.state(p, d): done.append((s.dr.m.moves[d]['name'], s.dr2rec[d]))
        return done

    def state(s, p, d):
        """A DR follow-up without a hit that starts a motion of its own (Bodyswy, the sway back that
        Pl_t_slpFRv, d/f+1 then b, goes on to at 16; nothing played it, the jab went back to the
        stance): a record on DR's animation whole, copied from the pack record playing the DR move
        whose entries are most like its own (Pl_sway00B: the same three sway attacks). Its list: those
        moves at DR's windows (b|N+1 from 15...), then the stance's from the frame DR goes on to the
        move continuing the animation (Bodyswy2 at 20, its list the stance's), through the end entry.
        Returns the record, None when no pack record is like it."""
        m = s.dr.m
        s.parents(d)
        dests = lambda x: {y for _, y in s._dests.get(x, ())}
        later = [(x, ds) for x in range(len(m.moves)) for q, l, ds, de, sf in s.parents(x)
                 if q == d and x != d and l in ('', '-') and s.same_anim(d, x)]
        mine = dests(d)
        # Ties go to a move ending as d does (Pl_st2cr01B shares the sway attacks and ends crouched).
        tmpl = max(s.pairs, key=lambda k: (len(mine & dests(s.pairs[k])), s.dr_end(s.pairs[k])[0] == s.dr_end(d)[0]), default=None)
        if tmpl is None or not mine & dests(s.pairs[tmpl]): return None
        rj = s.pack.add_record(tmpl, NEW_PROVENANCE + 4 * (len(s.pack.records) - s.ttt1.count))
        anim, lacet = s.cv.ch.move(d)
        n = min(s.cv.ch.frames(anim), 255)
        s.pack.set_clip(rj, s.cv.poses(anim, lacet, list(range(n))))
        rec2dr = {v: k for k, v in s.dr2rec.items()}
        free = min([ds for _, ds in later] + [s.dr.step(d)[0], n - 1])
        entries = []
        for e in s.pack.cancels(tmpl):
            e = list(e)
            if e[0] == 0xc000:
                e[5:8] = [free, 255, free]
            elif e[1] or e[3] < BASE_ID: continue
            else:
                x = rec2dr.get(e[3] - BASE_ID)
                win = next(((ds, de, sf) for q, l, ds, de, sf in s.parents(x) if q == d), None) if x is not None else None
                if win is None: continue
                e[5:8] = [min(v, 255) for v in win]
            entries.append(tuple(e))
        s.pack.set_cancels(rj, entries)
        s.dr2rec[d] = rj
        for x, _ in later: s.dr2rec.setdefault(x, rj)
        if not s.hook(m.moves[d]['name'], d, rj, own_only=True):
            del s.dr2rec[d]; return None
        # Its motion starts over (transition 6), whatever the siblings' entries do: Pl_t_slpF's b took
        # Pl_t_slpFRv's continuing 2 and Bodyswy played from the jab's frame 17.
        for q, *_ in s.parents(d):
            k = s.dr2rec.get(q)
            if k is None or k == rj: continue
            entries = s.pack.cancels(k)
            if any(e[3] == BASE_ID + rj and e[4] & 0x3f == 2 for e in entries):
                s.pack.set_cancels(k, [(*e[:4], (e[4] & ~0x3f) | 6, *e[5:]) if e[3] == BASE_ID + rj and e[4] & 0x3f == 2 else e
                                       for e in entries])
        return rj

    def absent(s, cmd, r):
        """A move DR does not have: the entries that lead to its record go, unless a DR move
        plays that record too."""
        ri = s.by_addr.get(r['TTT1 coup'])
        if ri is None or ri in s.dr2rec.values() or ri == s.pack.neutral: return 0
        gone = 0
        for k in range(len(s.pack.records)):
            entries = s.pack.cancels(k)
            keep = [e for e in entries if e[0] == 0xc000 or e[3] != BASE_ID + ri]
            if len(keep) != len(entries): s.pack.set_cancels(k, keep); gone += len(entries) - len(keep)
        s.report['moves'][cmd] = dict(kind='absent', record=ri, entries_removed=gone)
        return gone

    def limbs(s, mi):
        """The move's hitting limbs: DR's move word +0x50 holds four game bones (dr_pose OS_JOINT
        numbering), each the TTT1 bone of the row its joint is (Paul's jab 0x0C -> 10, 2 0x08 -> 6,
        3 0x14 -> 17, 4 0x10 -> 14, as the TTT1 records have them). A copied record's limbs were
        another move's: Tetsuzan hit with d+1, 2's fist instead of the shoulder and missed up close.
        An end bone (bytes 0, 2) that is no joint of the skeleton (Pl_TetsuzanA's 114: a node of
        DR's, Tekken 3 has none) left the pair without an end, no capsule and no hit: the move then
        takes the limbs of the move whose animation it goes on playing (Pl_Tetsuzan's, from its
        frame 11), else the pair's start bone, swept."""
        word = s.dr.raw[mi][20]
        bone = s.dr_bone
        raw = [word >> 8 * k & 0xff for k in range(4)]
        out = [bone(x) for x in raw]
        lost = [k for k in (0, 2) if raw[k] and not out[k] and out[k + 1]]
        if lost:
            for p, label, *_ in s.parents(mi):
                if label in ('', '-') and p != mi and s.same_anim(p, mi):
                    return s.limbs(p)
            for k in lost: out[k], out[k + 1] = out[k + 1], 0
        return out

    def dr_bone(s, os_):
        """The TTT1 bone of the row a DR game bone (dr_pose OS_JOINT numbering) is, 0 for none."""
        joint_row = {j: r for r, j in s.cv.rj.items()}
        joint_row.update({29: joint_row[16], 30: joint_row[19]})
        j = s.cv.ch.P.OS_JOINT[os_] if os_ < len(s.cv.ch.P.OS_JOINT) else None
        return X.ROW_BONE[joint_row[j]] if os_ and j in joint_row else 0

    def same_anim(s, a, b):
        """DR moves a and b play the same animation (its slice: length and header)."""
        key = lambda m: (lambda x: (len(x), bytes(x[:0xB2])))(s.cv.ch.move(m)[0])
        return key(a) == key(b)

    def continues(s, a, b, frame):
        """DR move b, which a leaves for at a's frame `frame`, goes on with a's motion at the same frame
        number rather than from its own start: its pose there is nearer a's (mean row angle).
        pol_sjk00FRv -> pol_sjk10F at 16: 5 degrees against 80 from its start; pol_sk00G -> rakuyo2
        at 15: 96 against 9 (rakuyo2 starts over, as DR plays it)."""
        if s.same_anim(a, b): return True
        if not 1 < frame < 255: return False
        def pose(m, f):
            anim, lacet = s.cv.ch.move(m)
            return s.cv.frame(anim, min(f, s.cv.ch.frames(anim) - 1), lacet)[0]
        A = pose(a, frame)
        apart = lambda B: np.mean([X.angle(A[r].T @ B[r]) for r in A])
        return apart(pose(b, frame)) < apart(pose(b, 0))

    def sequence(s, label):
        """An input sequence of the pack (0xE000 + n, after the relocations): a frame budget (1..60:
        20 for four steps as N,f,N,f+1+2 has, 59 beyond, as the 1+2,2,2... strings), then one word a
        step, buttons << 8 | keypad direction (5 neutral), ended by 0 (tools/t5/t3_moveset.step)."""
        names = {'d/b': 1, 'd': 2, 'd/f': 3, 'b': 4, 'N': 5, 'f': 6, 'u/b': 7, 'u': 8, 'u/f': 9}
        steps = []
        for token in label.split(','):
            parts = token.split('+')
            d = names[parts.pop(0)] if parts[0] in names else 5
            steps.append(sum(1 << (int(b) - 1) for b in parts) << 8 | d)
        words = [20 if len(steps) <= 4 else 59] + steps + [0]
        n = struct.unpack_from('<I', s.pack.tail, 0)[0]
        p, existing = 4, {}
        for i in range(n):
            c, k = struct.unpack_from('<HH', s.pack.tail, p)
            existing[struct.unpack_from(f'<{k}H', s.pack.tail, p + 4)] = c; p += 4 + 2 * k
        if tuple(words) in existing: return existing[tuple(words)]
        s.pack.tail = struct.pack('<I', n + 1) + s.pack.tail[4:] + struct.pack(f'<HH{len(words)}H', 0xe000 + n, len(words), *words)
        return 0xe000 + n

    @staticmethod
    def command(cmd):
        """Tekken 3 command code of a direction + buttons input (t3_moveset.Moveset.text, inverted)."""
        names = {'d/b': 1, 'd': 2, 'd/f': 3, 'b': 4, 'N': 5, 'f': 6, 'u/b': 7, 'u': 8, 'u/f': 9}
        parts = cmd.split('+')
        dirs = 0
        if parts[0] in names: dirs = 1 << (names[parts.pop(0)] - 1)
        buttons = sum(1 << (int(p) - 1) for p in parts)
        return buttons | dirs << 5

    def pack_root(s, k, poses):
        """poses with the root heading and distance of pack record k's own clip (TTT1's), DR's height and
        rows kept; a loop longer than it (the stance: DR 70 frames, TTT1 54) goes round it. The stance,
        walks and steps move as the pack's (A2 rule 13): DR's stance holds the hips 39 off the floor point
        at 66 degrees, which Tekken 3 takes into the fighter's position at each move start (Paul 32 to the
        side every move), and its walk forward went 7 degrees off (Jin 9 degrees off after the bench's
        walk: u+3, 4 passed him by)."""
        off = s.pack.word(k, 0) - s.pack.data_at
        n = struct.unpack_from('<I', s.pack.data, off)[0] & 0xff
        root = [struct.unpack_from('<3H', s.pack.data, off + 8 + i * 114) for i in range(n)]
        return [[root[i % n][0], p[1], root[i % n][2], *p[3:]] for i, p in enumerate(poses)] if n else poses

    def stance(s):
        """The neutral on DR's stance, with DR's look at the opponent (data/dr_regard_<name>.json,
        tools/psp/dr_regard.py): DR turns bones to the opponent every frame (Devil Jin's neck and head,
        36 and 19 degrees), Tekken 3 does not, and his head stayed down as the animation has it."""
        mi = s.dr.m.stance
        anim, lacet = s.cv.ch.move(mi)
        n = s.cv.ch.frames(anim)
        regard = HERE / 'data' / f'dr_regard_{s.name}.json'
        turns = {int(k): np.array(v['turn']) for k, v in json.loads(regard.read_text())['bones'].items()} if regard.exists() else {}
        world, cache = s.cv.ch.world, s.cv.cache
        if turns:
            P, parent = s.cv.ch.P, s.cv.ch.parent
            def looking(a, f, l=True):
                W, r0, r1 = world(a, f, l)
                W = dict(W)
                for k, T in sorted(turns.items()):
                    j = P.OS_JOINT[k]
                    if j is None: continue
                    D4 = np.eye(4); D4[:3, :3] = T
                    G = W[j] @ D4 @ np.linalg.inv(W[j])
                    below = {j}
                    for c in range(len(W)):
                        x = c
                        while x >= 0 and x not in below: x = parent[x]
                        if x >= 0: below.add(c)
                    for c in below: W[c] = G @ W[c]
                return W, r0, r1
            s.cv.ch.world, s.cv.cache = looking, {}
        try: poses = s.pack_root(s.pack.neutral, s.cv.poses(anim, lacet, list(range(n))))
        finally: s.cv.ch.world, s.cv.cache = world, cache
        s.pack.set_clip(s.pack.neutral, poses)
        s.report['stance'] = dict(dr_move=s.dr.m.moves[mi]['name'], frames=n)
        return poses

    def whole(s, k, mi):
        """Record k plays DR move mi's animation whole, at DR's length: a throw's two sides must stay
        frame for frame together (H_armscr_n 140 / H_armscr_y 140 against TTT1's 140 / 130)."""
        if k in s.whole_done: return s.whole_done[k] == mi       # shared by several throws: the first
        anim, lacet = s.cv.ch.move(mi)
        n = s.cv.ch.frames(anim)
        if n > 255: return False
        s.pack.set_clip(k, s.cv.poses(anim, lacet, list(range(n))))
        s.whole_done[k] = mi
        return True

    def throw(s, cmd, r):
        """A throw both games have (same structure, A2 rule 12): the attempt (retimed like any common
        move), then for each side its condition picks (4 / 5 / 3 / 2, parameter 1536, the same in
        both), the attacker's record and the victim's (the attacker's HitEntry standing hit, DR's
        reaction 1), and on the victim's record its escape (TTT1 condition 58 / 59 / 60, window
        1-10; DR its own condition, the same window)."""
        mi, ri = s.by_name[r['DR coup']], s.by_addr[r['TTT1 coup']]
        poses, info = s.clip(mi, s.rec_bounds(ri))
        s.pack.set_clip(ri, poses)
        s.dr2rec[mi] = ri
        m, t, done = s.dr.m, s.ttt1, []
        def dr_conditional(p):
            out = []
            c = s.dr.raw[p][5]
            for k in range(64):
                cmd_, req, mid, *_ = struct.unpack_from('<IIIIHHHH', s.dr.ram, m.off(c) + k * 24)
                if cmd_ in (0x8000, 0x8006): break
                first = struct.unpack_from('<HH', s.dr.ram, m.off(req))
                d = m.resolve(mid)
                if d < len(m.moves): out.append((first[0], d))
            return out
        sides = s.dr_sides(mi)
        entries, made = [], []
        for e in s.pack.cancels(ri):
            entries.append(e)
            if e[0] == 0xc000: continue
            k, cond = (e[3] - BASE_ID if e[3] >= BASE_ID else None), e[1] >> 8
            # The side without input first: DR puts a held direction's variant ahead of it (2+4 from
            # the front: Pl_8kyo9 with back held, asagao without), which plain 2+4 played every time.
            dm = next((d for c_, c, d in sides if c == cond and not c_), next((d for c_, c, d in sides if c == cond), None))
            if k is None or dm is None: continue
            entries[-1:] = s.variants(e, k, sides, made) + [e]
            if s.whole(k, dm): done.append((k, m.moves[dm]['name']))
            else: s.shared.append((ri, e[1], k, dm))     # a side TTT1 shares and DR does not (2+4's back)
            he = t.hit_entry_of(k)
            rx = s.dr.reactions(dm)
            if he and rx and he[0] >= BASE_ID and rx[1] < len(m.moves):
                v = he[0] - BASE_ID
                if s.whole(v, rx[1]): done.append((v, m.moves[rx[1]]['name'])); s.throw_victims.append(v)
                # The escape, from the victim's record.
                esc_dr = [d for c, d in dr_conditional(rx[1]) if c not in (0, 330, WALL)]
                esc_pk = [x[3] - BASE_ID for x in s.pack.cancels(v) if x[0] != 0xc000 and 58 <= x[1] >> 8 <= 60 and x[3] >= BASE_ID]
                for kk, dd in zip(esc_pk, esc_dr):
                    if s.whole(kk, dd): done.append((kk, m.moves[dd]['name']))
        s.pack.set_cancels(ri, entries)
        s.report['moves'][cmd] = dict(kind=r['statut'] or 'prise', record=ri, throw_records=done, variants=made, **info)

    def dr_sides(s, mi):
        """A DR throw attempt's sides: [(input, condition, DR move)], in DR's order; input 0 is none,
        else a direction held when the grab is tested (DR's command coding: 0x10 b, 0x40 f)."""
        m, out = s.dr.m, []
        c = s.dr.raw[mi][5]
        for k in range(64):
            cmd_, req, mid, *_ = struct.unpack_from('<IIIIHHHH', s.dr.ram, m.off(c) + k * 24)
            if cmd_ in (0x8000, 0x8006): break
            cond = struct.unpack_from('<H', s.dr.ram, m.off(req))[0]
            if m.resolve(mid) < len(m.moves): out.append((cmd_, cond, m.resolve(mid)))
        return out

    def throw_damages(s):
        playing = s.whole_done.keys()
        return [struct.unpack_from('<I', s.pack.records[k], 20)[0] & 0x3fff for k in playing
                if 0 < struct.unpack_from('<I', s.pack.records[k], 20)[0] & 0x3fff < 0x4000] or [30, 50]

    def side_record(s, side, dm, made):
        """A record for DR side move dm, copied from the pack's side record `side`, with its victim
        and a reaction row naming it. Damage: DR's, within the range of the pack's throws (A2 rule 12)."""
        m, t = s.dr.m, s.ttt1
        damages = s.throw_damages()
        k = s.pack.add_record(side, NEW_PROVENANCE + 4 * (len(s.pack.records) - s.ttt1.count))
        s.whole(k, dm)
        dmg = min(max(m.moves[dm]['damage'], min(damages)), max(damages))
        word = struct.unpack_from('<I', s.pack.records[k], 20)[0]
        struct.pack_into('<I', s.pack.records[k], 20, (word & 0xffffc000) | dmg)
        he, rx = t.hit_entry_of(side), s.dr.reactions(dm)
        if he and rx and he[0] >= BASE_ID and rx[1] < len(m.moves):
            v = s.pack.add_record(he[0] - BASE_ID, NEW_PROVENANCE + 4 * (len(s.pack.records) - s.ttt1.count))
            s.whole(v, rx[1])
            row = struct.unpack_from('<I', s.pack.records[side], 48)[0] >> 16
            new_row = s.add_reaction_row(row, BASE_ID + v)
            word = struct.unpack_from('<I', s.pack.records[k], 48)[0]
            struct.pack_into('<I', s.pack.records[k], 48, (word & 0xffff) | new_row << 16)
            made.append((k, m.moves[dm]['name'], v, m.moves[rx[1]]['name'], dmg))
            if s.name in REORDER: s.throw_sides.append((k, v, dmg))      # throw_props(), after reactions()
        return k

    def props_of(s, k):
        off, out = s.pack.word(k, 8), []
        if off < s.pack.data_at: return out
        o = off - s.pack.data_at
        while True:
            f, v = struct.unpack_from('<HH', s.pack.data, o); o += 4
            if not f: return out
            out.append((f, v >> 8, v & 0xff))

    def throw_ends(s):
        """The victims of the throws both games have end on the record playing DR's next move, as
        throw_props() does for the new ones: hp_y (Devil Jin's f, f+1+2) lies down at its end, and TTT1's
        next record (868) threw Jin's legs up a second time before he lay on dwDWN_00U."""
        paired = {s.by_name[nm]: int(r) for r, nm in s.report.get('reactions', {}).get('paired', {}).items()}
        out = []
        for v in s.throw_victims:
            nx = s.dr_next(s.whole_done[v])
            if nx is None or nx not in paired: continue
            es = s.pack.cancels(v)
            new = [(*e[:3], BASE_ID + paired[nx], *e[4:]) if e[0] == 0xc000 else e for e in es]
            if new != es:
                s.pack.set_cancels(v, new)
                out.append((v, s.dr.m.moves[nx]['name'], paired[nx]))
        s.report['throw_ends'] = out
        return out

    def lying_turn(s, v, c, land, turn):
        """Record v's clip c turned on the floor by `turn` degrees, little by little from frame land
        to its end (Tekken 3's get-up then finds the victim on the line). Returns the new clip."""
        out, prev = [], None
        for i, p in enumerate(c):
            a = np.radians(turn * min(max(i - land, 0) / max(len(c) - 1 - land, 1), 1.0))
            Ry = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
            W = X.ttt1_world(p)
            j = X.ttt1_joints({r: Ry @ W[r] for r in W}, prev); prev = j
            out.append([*p[:3], *[int(round(x)) & 0xffff for x in j]])
        s.pack.set_clip(v, out)
        return out

    def reaction_ground_turns(s):
        """The reactions DR leaves lying across the line (data/dr_ground_turns_<name>.json, by the DR
        reaction's name): Demon's Tail's sweep (sDm_ASI20RD) left Jin 43 degrees off, and Tekken 3's
        get-up turned him at once. Turned on the floor from the landing, as the throws' victims.
        Returns [(record, DR reaction, degrees)]."""
        out = []
        for r, nm in s.report.get('reactions', {}).get('paired', {}).items():
            turn = s.ground_turns.get(nm)
            if not turn: continue
            k = int(r); c = s.clip_of(s.pack, k)
            if not c: continue
            h = [X.s16(p[1]) for p in c]
            top = max(range(len(h)), key=lambda i: h[i])
            land = next((i for i in range(top, len(h)) if h[i] < 300), len(h) - 1) + 1
            s.lying_turn(k, c, land, turn)
            out.append((k, nm, turn))
        return out

    def throw_props(s, k, v, dmg):
        """A new throw side's effects at DR's moment (copied from 1+3's, Jin's stomp: sparks on his foot,
        joint 14, at 27 and 63, damage 10 then 20). DR deals its damage once and lights the victim as he
        lands (d,d/b,b+1+3: 35, Paul down at frame 69): the attacker's damage there (kind 11), the
        victim's spark on his hips (kind 8, joint 0) and dust (kind 4) the same frame, his camera
        cues (kind 2) kept. A victim DR leaves lying across the line to his attacker turns on the floor
        from his landing (data/dr_ground_turns_<name>.json): Tekken 3's get-up turned him at once."""
        c = s.clip_of(s.pack, v)
        h = [X.s16(p[1]) for p in c]
        top = max(range(len(h)), key=lambda i: h[i])
        land = next((i for i in range(top, len(h)) if h[i] < 300), len(h) - 1) + 1
        dm_k = s.dr.m.moves[s.whole_done[k]]['name'] if k in s.whole_done else None
        hits = THROW_HITS.get(s.name, {}).get(dm_k, ((land, dmg),))
        s.pack.set_props(k, [(f, 11, d) for f, d in hits])
        beam = LASERS.get(s.name, {}).get(dm_k)
        if beam: s.pack.records[k][40:44] = bytes((LASER_LIMB, beam, 0, 0))
        # The victim's end on the record playing DR's next move (Jz_front_y lies face down, dwDWN_00D,
        # 89): 1+3's side went to 77, face up, and Paul rolled over on the floor.
        dm = s.whole_done.get(v)
        nx = s.dr_next(dm) if dm is not None else None
        paired = {s.by_name[nm]: int(r) for r, nm in s.report.get('reactions', {}).get('paired', {}).items()}
        if nx is not None and nx in paired:
            s.pack.set_cancels(v, [(*e[:3], BASE_ID + paired[nx], *e[4:]) if e[0] == 0xc000 else e for e in s.pack.cancels(v)])
        turn = s.ground_turns.get(s.dr.m.moves[s.whole_done[v]]['name']) if v in s.whole_done else None
        if turn: c = s.lying_turn(v, c, land, turn)
        # Then into the first pose of the record his end goes to, over the same frames: DR's lying pose
        # has the chest a quarter turn from the legs against 77's (u/f+1+2: hips 3 degrees apart, chest
        # 93), and the upper body turned at once as 77 started (Tekken 3's tail blend does not run there).
        end = next((e[3] for e in s.pack.cancels(v) if e[0] == 0xc000), None)
        nxt = s.clip_of(s.pack, end - BASE_ID) if end is not None and end >= BASE_ID else None
        if nxt:
            T = X.ttt1_world(nxt[0])
            L = X.ttt1_world(c[-1])
            R = L[0] @ T[0].T
            y = np.arctan2(R[0, 2] - R[2, 0], R[0, 0] + R[2, 2])
            Ry = np.array([[np.cos(y), 0, np.sin(y)], [0, 1, 0], [-np.sin(y), 0, np.cos(y)]])
            T = {r: Ry @ T[r] for r in T}
            out, prev = [], None
            for i, p in enumerate(c):
                u = min(max(i - land, 0) / max(len(c) - 1 - land, 1), 1.0)
                W = X.ttt1_world(p)
                j = X.ttt1_joints({r: X.slerp_matrix(W[r], T[r], u) for r in W}, prev); prev = j
                out.append([*p[:3], *[int(round(x)) & 0xffff for x in j]])
            s.pack.set_clip(v, out)
        keep = [p for p in s.props_of(v) if p[1] == 2]
        sparks = [(f, 8, 0) for f, _ in hits] if dm_k in THROW_HITS.get(s.name, {}) else [(land, 8, 0)]
        s.pack.set_props(v, sorted(keep + sparks + [(land, 4, 0)]))

    def variants(s, e, side, sides, made):
        """Entries for DR's held-direction variants of entry e's side, to put ahead of it: the same
        condition and window, the direction as the command, each to the record playing that DR move
        or a new one copied from `side`."""
        m, out = s.dr.m, []
        playing = {dm: k for k, dm in s.whole_done.items()}
        for c_, c, dm in sides:
            if c != e[1] >> 8 or not c_: continue
            try: code = s.code_of(m.label(c_))
            except (ValueError, KeyError): continue
            k = playing.get(dm)
            if k is None: k = s.side_record(side, dm, made)
            out.append((code, *e[1:3], BASE_ID + k, *e[4:]))
        return out

    def add_reaction_row(s, like_row, standing):
        """A reaction row (tables.jst, 42 bytes) copied from like_row with its standing-hit move
        changed (a throw's victim); appended after the rows, the counts and size moved."""
        t = s.tables
        nr = struct.unpack_from('<I', t, 12)[0]
        row = bytearray(t[32 + like_row * 42:32 + like_row * 42 + 42])
        struct.pack_into('<H', row, 0, standing)
        t[32 + nr * 42:32 + nr * 42] = row
        struct.pack_into('<I', t, 12, nr + 1)
        struct.pack_into('<I', t, 8, len(t))
        return nr

    def dr_entries(s, mi):
        """(conditions, reactions address) of the DR move mi's hit entries, up to the unconditional one."""
        m, ram = s.dr.m, s.dr.ram
        hc = s.dr.raw[mi][10]
        if not hc: return
        for k in range(32):
            req, conds = m.u32(hc + k * 12), []
            for j in range(16):
                c, p = struct.unpack_from('<HH', ram, m.off(req) + j * 4)
                if c == 330: break
                conds.append((c, p))
            yield conds, m.u32(hc + k * 12 + 8)
            if not conds: return

    def dr_hit(s, mi):
        """DR's reactions of move mi: the 15 moves of its unconditional hit entry, and (distance, 15
        moves) of its condition 34 entry (the clean hit up close: parameter = distance, damage x 1.5),
        else None. Condition 289 (victim in the air) is left to Tekken 3 (A2 rule 2)."""
        m, ram, alt = s.dr.m, s.dr.ram, None
        for conds, rx in s.dr_entries(mi):
            moves = struct.unpack_from('<15H', ram, m.off(rx) + 50)
            if not conds: return moves, alt
            if conds[0][0] == 34 and alt is None: alt = (conds[0][1], moves)
        return None, alt

    def dr_pushes(s, mi, clean=False):
        """The push curves of the DR move mi's unconditional hit entry (of its condition 34 entry when
        clean) as Tekken 3's row has them: hit, counter, down, guard. DR's 7 pushbacks (frames, step,
        8 more steps: Tekken 3's curve, reaction_push_table) are standing, back, left, right, counter,
        down, guard; the 79 moves both games have share them, number for number, 0 / 4 / 5 / 6.
        With them the directions the row pushes along: angle and angle_special (HitEntry +0x1C, +0x24),
        DR's 6 directions (+28: standing, back, left, right, counter, down) 0 and 5, their words as they
        are (78 of the 79 shared moves; b+2's -80 sends Jin away to the side as in DR, measured)."""
        m, ram = s.dr.m, s.dr.ram
        for conds, rx in s.dr_entries(mi):
            if (conds and conds[0][0] == 34) if clean else not conds:
                curves = []
                for k in (0, 4, 5, 6):
                    n, step, count, ext = struct.unpack_from('<hhII', ram, m.off(m.u32(rx + 4 * k)))
                    more = list(struct.unpack_from(f'<{count}h', ram, m.off(ext))) if count and ext else []
                    curves.append((n, step, *(more + [0] * 8)[:8]))
                directions = struct.unpack_from('<6H', ram, m.off(rx) + 28)
                return curves, (directions[0], directions[5])
        return None

    def air_pushes(s):
        """AIR_PUSH's attacks: {record: push table index} of their DR hit entry's condition 289 curve
        (frames, velocity, eight steps, as dr_pushes reads them)."""
        m, ram, out = s.dr.m, s.dr.ram, {}
        for nm in AIR_PUSH.get(s.name, ()):
            mi = s.by_name.get(nm)
            ri = s.dr2rec.get(mi)
            if ri is None: continue
            for conds, rx in s.dr_entries(mi):
                if not conds or conds[0] != (289, 0): continue
                n, step, count, ext = struct.unpack_from('<hhII', ram, m.off(m.u32(rx)))
                more = list(struct.unpack_from(f'<{count}h', ram, m.off(ext))) if count and ext else []
                out[ri] = s.push_of((n, step, *(more + [0] * 8)[:8]))
                break
        s.report['air_pushes'] = out
        return out

    def push_of(s, curve):
        """The pack's push table index (halfwords) of curve (10 halfwords): an existing one when the
        same, else a new one at its end (the clean-hit table moves along). A curve is never read across
        the end of the native table (0x58C bytes): install_tables puts the other guest's after it."""
        t = s.tables
        nr, np_ = struct.unpack_from('<2I', t, 12)
        at, data, native = 32 + nr * 42, struct.pack('<10h', *curve), 0xce8 - 0x75c
        for i in range(0, np_ - 19, 2):
            if i < native < i + 20: continue
            if t[at + i:at + i + 20] == data: return i // 2
        t[at + np_:at + np_] = data
        struct.pack_into('<I', t, 16, np_ + 20)
        struct.pack_into('<I', t, 8, len(t))
        return np_ // 2

    def dr_end(s, mi):
        """(move, window start) of the DR move mi's end entry (0x8000)."""
        m = s.dr.m
        c = s.dr.raw[mi][5]
        for k in range(256):
            cmd, req, mid, ext, ds = struct.unpack_from('<IIIIH', s.dr.ram, m.off(c) + k * 24)
            if cmd == 0x8000: return m.resolve(mid), ds
        return None, None

    def dr_next(s, mi):
        """The DR move mi goes on to at its end, None at a stance: standing or crouched (the victim's
        own, 'sKAM' / 'cKAM'). Lying (dwKAM) goes on: its record is the pack's too."""
        m = s.dr.m
        d = s.dr_end(mi)[0]
        if d is None or d >= len(m.moves) or d == m.stance: return None
        name = m.moves[d]['name']
        return None if 'sKAM' in name or 'cKAM' in name else d

    def dr_rest(s, mi):
        """How a DR reaction ends: the move it goes on to, else 'c' crouched or 's' standing."""
        d = s.dr_next(mi)
        if d is not None: return d
        e = s.dr_end(mi)[0]
        return 'c' if e is not None and e < len(s.dr.m.moves) and 'cKAM' in s.dr.m.moves[e]['name'] else 's'

    def pack_next(s, k):
        """The pack record k goes on to at its end (0xC000 entry), None at a stance or a native move."""
        e = [x for x in s.pack.cancels(k) if x[0] == 0xc000]
        if not e: return None
        d = s.ttt1.resolve(e[0][3])
        if d is None or d == s.pack.neutral or d == s.ttt1.resolve(40): return None
        return d

    def reaction_clip(s, k, mi, done):
        """Pack record k plays DR reaction mi, its DR animation retimed onto k's length (the frame the
        victim is free and the record's end stay: Tekken 3's advantages, the user's choice of
        2026-10-26); then the move each goes on to, side by side (sDm_PNG00_ 45 / dwDWN_00U 60 /
        dwDWN_01U 20 are TTT1's p642 / p88 / p93, the same lengths)."""
        while k is not None and mi is not None and k not in done and k not in s.whole_done:
            anim, lacet = s.cv.ch.move(mi)
            n, frames = s.cv.ch.frames(anim), s.pack.word(k, 6) & 0xff
            if not frames: break
            times = [i * (n - 1) / max(frames - 1, 1) for i in range(frames)]
            s.pack.set_clip(k, s.cv.poses(anim, lacet, times))
            done[k] = mi
            k, mi = s.pack_next(k), s.dr_next(mi)

    def row_of(s, like_row, targets, pushes=None):
        """A reaction row naming targets (14 moves) and pushes (hit, counter, down, guard curves and
        the angle, angle_special they go along: dr_pushes), the rest of like_row's: an existing row of
        the pack's when one is the same, else a new one."""
        t = s.tables
        row = bytearray(t[32 + like_row * 42:32 + like_row * 42 + 42])
        struct.pack_into('<14H', row, 0, *targets)
        curves, angles = pushes or ((), ())
        for k, curve in zip((15, 17, 19, 20), curves):
            struct.pack_into('<H', row, 2 * k, s.push_of(curve))
        for k, angle in zip((14, 18), angles):
            struct.pack_into('<H', row, 2 * k, angle)
        nr = struct.unpack_from('<I', t, 12)[0]
        for i in range(633, nr):
            if t[32 + i * 42:32 + i * 42 + 42] == row: return i
        t[32 + nr * 42:32 + nr * 42] = row
        struct.pack_into('<I', t, 12, nr + 1)
        struct.pack_into('<I', t, 8, len(t))
        return nr

    def counter_of(s, row, distance):
        """An entry (row, distance) of the clean-hit table (reaction_alt_table: the hit is clean
        below that distance; 0 never), an existing one when the same."""
        t = s.tables
        nr, np_, nc = struct.unpack_from('<3I', t, 12)
        at = 32 + nr * 42 + np_
        for i in range(nc):
            if struct.unpack_from('<HH', t, at + i * 4) == (row, distance): return i
        t[at + nc * 4:at + nc * 4] = struct.pack('<HH', row, distance)
        struct.pack_into('<I', t, 20, nc + 1)
        struct.pack_into('<I', t, 8, len(t))
        return nc

    @staticmethod
    def clip_of(pack, k):
        """Record k's poses (57 channels each), None without a clip of its own."""
        off = pack.word(k, 0)
        if off < pack.data_at: return None
        head = struct.unpack_from('<I', pack.data, off - pack.data_at)[0]
        if head & 0xffffff00 != 0x4a554e00: return None
        return [struct.unpack_from('<57H', pack.data, off - pack.data_at + 8 + 114 * i) for i in range(head & 0xff)]

    def aliased(s):
        """Pack records an engine alias names (tables ALIA chunk): a fighter there plays its own."""
        t = s.tables
        nr, np_, nc = struct.unpack_from('<3I', t, 12)
        at, out = 32 + nr * 42 + np_ + nc * 4, set()
        while at + 8 <= len(t):
            typ, n = struct.unpack_from('<II', t, at); at += 8
            if typ == 0x41494c41:
                out |= {struct.unpack_from('<H', t, at + i + 2)[0] - BASE_ID for i in range(0, n, 4)}
            at += n
        return out

    def half_turns(s, done):
        """DR lies face down with the head towards the attacker (dwKAM_00D...), Tekken 3 and TTT1 the
        other way, the fighter turned (hips: a half-turn about the vertical axis). On a record an engine
        alias names, the victim plays its own ground state: Paul fell from Jin's 4 (sDm_kaiten) head
        first towards Jin, then turned at once on his own 0xA8. Those records keep TTT1's way (DR's
        clip turned), and a DR reaction ending turned from the record it goes on to turns the fighter
        with it (kind bit 0x80: the engine's rot -= 0x8000 at the change, fighter_cancel_step), as
        TTT1's own do (139, 142). Returns the records turned and the transitions given the bit."""
        orig = Pack((s.pack_dir / f'{s.Name}-TTT1-combat.jmv').read_bytes())
        D = np.diag([-1.0, 1.0, -1.0])
        hips = lambda p: X.rotation([X.s16(c) for c in p[3:6]])
        turned = lambda A, B: X.angle(D @ A @ B.T) < 30
        aliased, made = s.aliased(), []
        for k in sorted(done):
            if k >= s.ttt1.count or k not in aliased: continue
            new, old = s.clip_of(s.pack, k), s.clip_of(orig, k)
            if not new or not old or not turned(hips(new[0]), hips(old[0])): continue
            out, prev = [], None
            for p in new:
                e = X.euler(D @ hips(p))
                e = e if prev is None else X.nearest(e, prev)
                prev = e
                out.append([(p[0] + 0x8000) & 0xffff, p[1], p[2], *[int(round(v)) & 0xffff for v in e], *p[6:]])
            s.pack.set_clip(k, out)
            made.append(k)
        return dict(records=made, transitions=s.turn_ends(set(done) | set(s.whole_done)))   # the throws' victims lie down too

    def turn_ends(s, records):
        """half_turns()'s turn at the change: the ends of these records into a record that starts turned
        from where they end take kind bit 0x80. Returns [(record, record turned into)]."""
        D = np.diag([-1.0, 1.0, -1.0])
        hips = lambda p: X.rotation([X.s16(c) for c in p[3:6]])
        turned = lambda A, B: X.angle(D @ A @ B.T) < 30
        bits = []
        for k in sorted(records):
            clip, entries, mine = s.clip_of(s.pack, k), [list(e) for e in s.pack.cancels(k)], len(bits)
            for e in entries:
                if e[0] != 0xc000 or not BASE_ID <= e[3] < BASE_ID + len(s.pack.records): continue
                nxt = s.clip_of(s.pack, e[3] - BASE_ID)
                if not clip or not nxt: continue
                if turned(hips(clip[-1]), hips(nxt[0])) and not e[4] & 0x80:
                    # Its window past the record's length: within it the engine looks ahead into the next
                    # record's list and takes that entry's byte, not this one's (fighter_cancel_step), and
                    # Paul did not turn after b+1, 4 (sDm_ASI20RD then his own 0x99, at once his get-up).
                    e[4] |= 0x80; e[5] = 255; bits.append((k, e[3] - BASE_ID))
            if len(bits) > mine: s.pack.set_cancels(k, [tuple(e) for e in entries])
        return bits

    def heading_turns(s):
        """The records ending into a HEADING_TURNS move turn the fighter round with the change (kind bit
        0x80, the engine's rot -= 0x8000; the window past the record's length, as half_turns()).
        Returns [(record, record turned into)]."""
        out = []
        for nm in HEADING_TURNS[s.name]:
            d = s.dr2rec.get(s.by_name.get(nm))
            if d is None: continue
            for k in range(len(s.pack.records)):
                es = [list(e) for e in s.pack.cancels(k)]
                hit = [e for e in es if e[0] == 0xc000 and e[3] == BASE_ID + d and not e[4] & 0x80]
                for e in hit: e[4] |= 0x80; e[5] = 255; out.append((k, d))
                if hit: s.pack.set_cancels(k, [tuple(e) for e in es])
        s.report['heading_turns'] = out
        return out

    def reactions(s):
        """DR's reactions on the victim (A2 rule 9, all of them converted: the TTT1 ones the pack had
        were TTT1's animations, none DR's, the user's verdict of 2026-10-25). In DR the victim plays
        the move of the attacker's moveset its slot names (15 slots: 1..14 are the 14 moves of a
        Tekken 3 reaction row, one for one); in Tekken 3 it plays the attacker's pack records the
        row names. Each pack reaction record paired with a DR reaction (the one most of the moves
        both games have put in the same slot) plays DR's animation; a DR reaction paired with none
        gets a copy of the record its slot has. Every attack then names DR's reactions through its
        row, and DR's clean hit (condition 34) through the clean-hit table, its distance x 0.96 (the
        root's scale, dr_convert). The row pushes the victim as DR does: DR's animations carry their
        root, a TTT1 row's curve on top sent the victim of f,f, f+2 out of the 1's reach (the
        knockdown's 2550 against DR's 0)."""
        m = s.dr.m
        attacks = {}
        for mi, ri in s.dr2rec.items():
            if ri in attacks.values() or ri in s.whole_done: continue
            mv = m.moves[mi]
            if not mv['first'] or mv['damage'] >= 16384: continue
            if (s.pack.word(ri, 12) >> 16) < 633: continue
            base, alt = s.dr_hit(mi)
            if base: attacks[mi] = ri
        valid = lambda x: x < len(m.moves) and m.moves[x]['name'] not in ('motOrigin',) and not m.moves[x]['name'].startswith('_')
        row = lambda r: struct.unpack_from('<14H', s.tables, 32 + r * 42)
        votes = defaultdict(Counter)
        for mi, ri in attacks.items():
            if ri >= s.ttt1.count: continue                # a new move's row is its model's, not DR's
            base = s.dr_hit(mi)[0]
            for k, t in enumerate(row(s.pack.word(ri, 12) >> 16)):
                if t >= BASE_ID and valid(base[k + 1]): votes[t - BASE_ID][base[k + 1]] += 1
        owner = {}
        for k, c in sorted(votes.items(), key=lambda x: -max(x[1].values())):
            name = c.most_common(1)[0][0]
            owner.setdefault(name, k)
        done, cloned = {}, {}
        for x, k in owner.items(): s.reaction_clip(k, x, done)

        def record(x, template):
            """A DR reaction no TTT1 record has (Paul's own dw_Kzup_00, sDw_HRup00...): a record of
            its own at DR's length, ending as DR's does (DR's window; the record of the move DR goes
            on to, or a stance), copied from a paired reaction that ends the same way (its cancels:
            ukemi, stand-up), else from the slot's record."""
            if x in owner: return owner[x]
            if x in cloned: return cloned[x]
            chained = next((k for k, y in done.items() if y == x), None)   # paired through a chain (p88 dwDWN_00U)
            if chained is not None: return chained
            rest = s.dr_rest(x)
            like = [k for y, k in owner.items() if s.dr_rest(y) == rest]
            near = [k for y, k in owner.items() if s.dr_rest(y) == rest and m.moves[y]['name'][:6] == m.moves[x]['name'][:6]]
            tmpl = (near or like or [template])[0]
            k = s.pack.add_record(tmpl, NEW_PROVENANCE + 4 * (len(s.pack.records) - s.ttt1.count))
            cloned[x] = k
            anim, lacet = s.cv.ch.move(x)
            n = min(s.cv.ch.frames(anim), 255)
            s.pack.set_clip(k, s.cv.poses(anim, lacet, list(range(n))))
            done[k] = x
            nxt = s.dr_next(x)
            dest = BASE_ID + record(nxt, s.pack_next(tmpl) or tmpl) if nxt is not None else None
            window = s.dr_end(x)[1]
            # DR's end at 0 is the animation's end (dm_kaityuu, 85 frames, its victim lying until then):
            # the copied record's window (30) took the victim to its own ground state mid-fall (Jin's b+4).
            if not window and s.name in REORDER: window = n
            entries = [list(e) for e in s.pack.cancels(k)]
            for e in entries:
                if e[0] == 0xc000:
                    if dest is not None: e[3] = dest
                    if window: e[5] = min(window, 255)
            s.pack.set_cancels(k, [tuple(e) for e in entries])
            return k

        def react(mi, ri):
            """DR's reactions and pushes on attack mi's record ri; True when its row changed."""
            base, alt = s.dr_hit(mi)
            word = s.pack.word(ri, 12)
            old = word >> 16
            def targets(moves, like):
                return [BASE_ID + record(moves[k + 1], t - BASE_ID) if t >= BASE_ID and valid(moves[k + 1]) else t
                        for k, t in enumerate(row(like))]
            new = s.row_of(old, targets(base, old), s.dr_pushes(mi))
            if alt:
                a = s.row_of(old, targets(alt[1], old), s.dr_pushes(mi, clean=True))
                ctr = s.counter_of(a, round(alt[0] * 0.96))
            else:
                ctr = s.counter_of(new, 0)
            ch = new != old or s.pack.word(ri, 13) != ctr
            s.pack.set_word(ri, 12, (word & 0xffff) | new << 16)
            s.pack.set_word(ri, 13, ctr)
            return ch
        changed = sum(react(mi, ri) for mi, ri in attacks.items())
        # For the attacks made later (reorder(): the moves past an on-hit record, LATE_REORDER).
        s.react = lambda mi, ri: ri not in s.whole_done and m.moves[mi]['first'] and m.moves[mi]['damage'] < 16384             and (s.pack.word(ri, 12) >> 16) >= 633 and s.dr_hit(mi)[0] and (react(mi, ri), air(mi, ri))[0]
        s.air = {}
        def air(mi, ri):
            for conds, rx in s.dr_entries(mi):
                if not conds or conds[0][0] != 289: continue
                x = struct.unpack_from('<15H', s.dr.ram, m.off(rx) + 50)[1]
                if not valid(x) or not (m.moves[x]['name'].startswith(AIR_OWN.get(s.name, ()))
                                        or m.moves[mi]['name'] in AIR_MOVES.get(s.name, ())): continue
                first = row(s.pack.word(ri, 12) >> 16)[0]
                if first >= BASE_ID: s.air[ri] = record(x, first - BASE_ID)
        for mi, ri in sorted(s.dr2rec.items()) if s.name in AIR_OWN or s.name in AIR_MOVES else (): air(mi, ri)
        if s.name in REORDER: s.report['half_turns'] = s.half_turns(done)
        s.report['reactions'] = dict(attacks=len(attacks), records=len(done), cloned={m.moves[x]['name']: k for x, k in cloned.items()},
                                     paired={k: m.moves[x]['name'] for k, x in sorted(done.items())}, moves_changed=changed,
                                     air={ri: m.moves[done[k]]['name'] for ri, k in s.air.items()})
        return s.report['reactions']

    @staticmethod
    def lying(pose):
        """'up' or 'down' for a pose lying on its back or face down (the hips' front axis vertical),
        else None: standing, kneeling, on the side."""
        W = X.ttt1_world(pose)[0]
        if -W[1, 1] > 0.6: return None                # head up: standing
        front = -W[1, 2]
        return 'up' if front > 0.5 else 'down' if front < -0.5 else None

    def dr_deaths(s, mi):
        """DR's knocked-out ends of move mi: [(death move, window start, end, frame)], its entries without
        input on condition 110 alone (the fighter's life at 0; ym_y01 -> dDm_death00 from 40, going at
        50, the fall's last frame; dwDWN_00U at once)."""
        m, c, out = s.dr.m, s.dr.raw[mi][5], []
        for i in range(128):
            cmd, req, mid, ext, ds, de, sf, _ = struct.unpack_from('<IIIIHHHH', s.dr.ram, m.off(c) + i * 24)
            if cmd in (0x8000, 0x8006): break
            if not cmd and s.dr_conds(req) == [(110, 0)]: out.append((m.resolve(mid), ds, de, sf))
        return out

    def deaths(s):
        """DR's deaths on the knocked-out victim (the user's review of 2026-11-07, J5). DR goes from a
        reaction, at its knocked-out entry (dr_deaths(): condition 110), to dDm_death00 lying on the back
        or dDm_death00D face down (70 frames), then their 60-frame loops (..E). The pack kept TTT1's: its
        reactions' entries 0x10 on condition 61 (life 0) to 814 (70 frames) then 815 (60, looping),
        TTT1's writhing, with TTT1's windows (22..30 on the launches: the victim still in the air, at
        once on the floor, curled up), and no death face down (J3: 89, the victim's own ground state).
        The knocked-out record lying on the back the pack's entries go to plays dDm_death00 and its loop
        (reaction_clip, 814 / 815); a copy of the pair plays each other DR death (dDm_death00D). Each
        reaction record playing a DR reaction takes DR's knocked-out entry: its death's record, DR's
        window (retimed as the record's clip), the fighter turned with the change (kind bit 0x80) when
        the head lies the other way, as turn_ends(); a DR reaction without one going on to a move whose
        death comes at once (dwDWN_00U), at the reaction's last frame. A record with neither keeps its entry,
        sent to the death lying as its clip ends when it lay the other way (Jin's 4, 1177: face down,
        to 814 on the back at frame 40). Returns dict(records={DR death: record}, entries=[(record, old
        target, new target, frame)])."""
        m, n0 = s.dr.m, len(s.pack.records)
        D = np.diag([-1.0, 1.0, -1.0])
        hips = lambda p: X.rotation([X.s16(c) for c in p[3:6]])
        turned = lambda A, B: X.angle(D @ A @ B.T) < 30
        rx = s.report.get('reactions', {})
        playing = {int(k): s.by_name[nm] for k, nm in rx.get('paired', {}).items()}
        playing.update({k: s.by_name[nm] for nm, k in rx.get('cloned', {}).items()})
        ko_of = lambda k: [e for e in s.pack.cancels(k) if e[0] == 0x10 and e[1] >> 8 == 61 and BASE_ID <= e[3] < BASE_ID + n0]
        aliased = s.aliased()
        # The pack's knocked-out record lying on the back: the target most of its entries name.
        votes = Counter(e[3] - BASE_ID for k in range(n0) for e in ko_of(k))
        up = next((t for t, _ in votes.most_common() if t not in aliased and s.clip_of(s.pack, t)
                   and s.lying(s.clip_of(s.pack, t)[0]) == 'up' and s.pack_next(t) is not None), None)
        wanted = sorted({d for x in set(playing.values()) for d, *_ in s.dr_deaths(x)})
        if up is None or not wanted: return dict(records={}, entries=[])
        loop = s.pack_next(up)
        records, done = {}, {}
        def lies(d):
            anim, lacet = s.cv.ch.move(d)
            return s.lying(s.cv.poses(anim, lacet, [s.cv.ch.frames(anim) - 1])[0])
        for d in sorted(wanted, key=lambda d: lies(d) != 'up'):
            if lies(d) == 'up' and up not in records.values(): k = up
            else:
                k = s.pack.add_record(up, NEW_PROVENANCE + 4 * (len(s.pack.records) - s.ttt1.count))
                k2 = s.pack.add_record(loop, NEW_PROVENANCE + 4 * (len(s.pack.records) - s.ttt1.count))
                s.pack.set_cancels(k, [(*e[:3], BASE_ID + k2, *e[4:]) if e[3] == BASE_ID + loop else e for e in s.pack.cancels(up)])
                s.pack.set_cancels(k2, [(*e[:3], BASE_ID + k2, *e[4:]) if e[3] == BASE_ID + loop else e for e in s.pack.cancels(loop)])
                struct.pack_into('<H', s.pack.records[k], 16, BASE_ID + k2)       # tails(): the end's record
                struct.pack_into('<H', s.pack.records[k2], 16, BASE_ID + k2)
            s.reaction_clip(k, d, done)
            records[d] = k
        entries = []
        for k in range(n0):
            ko = ko_of(k)
            clip = s.clip_of(s.pack, k) if ko else None
            if not clip or k in aliased: continue
            x = playing.get(k)
            dr = [t for t in (s.dr_deaths(x) if x is not None else []) if t[0] in records]
            # None on the reaction, one at once on the move it goes on to (sDm_PNGL0_ -> dwDWN_00U, its
            # death from frame 1): DR's death comes as the reaction ends, its last frame here.
            nx = s.dr_next(x) if x is not None and not dr else None
            last = (len(clip) - 1) * (s.cv.ch.frames(s.cv.ch.move(x)[0]) - 1) // max(len(clip) - 1, 1) if nx is not None else 0
            if nx is not None: dr = [(d, last, 255, last) for d, ds, de, sf in s.dr_deaths(nx) if ds <= 1 and d in records]
            es, made = [list(e) for e in s.pack.cancels(k)], []
            for e in es:
                if tuple(e) not in ko: continue
                if dr:
                    d, ds, de, sf = dr[0]
                    anim, _ = s.cv.ch.move(x)
                    f = (len(clip) - 1) / max(s.cv.ch.frames(anim) - 1, 1)
                    at = lambda v: min(int(round(v * f)), len(clip) - 1, 255)
                    dest, e[5], e[6], e[7] = records[d], at(ds), 255 if de >= 255 else at(de), at(sf)
                else:
                    end = s.lying(clip[-1])
                    if not end or s.lying(s.clip_of(s.pack, e[3] - BASE_ID)[0]) in (None, end): continue
                    dest = next((r for d, r in records.items() if lies(d) == end), None)
                    if dest is None: continue
                    h = [X.s16(p[1]) for p in clip]
                    down = next(i for i in range(len(clip)) if all(s.lying(p) == end and abs(y - h[-1]) <= 40
                                                                   for p, y in zip(clip[i:], h[i:])))
                    e[5] = e[7] = min(down, 255)
                frame = min(e[7], len(clip) - 1)
                made.append((k, e[3] - BASE_ID, dest, e[7]))
                e[3] = BASE_ID + dest
                e[4] = e[4] & 0x7f | (0x80 if turned(hips(clip[frame]), hips(s.clip_of(s.pack, dest)[0])) else 0)
            if made: s.pack.set_cancels(k, [tuple(e) for e in es]); entries += made
        s.report['deaths'] = dict(records={m.moves[d]['name']: k for d, k in records.items()}, entries=entries)
        return s.report['deaths']

    def dr_ukemi(s, mi):
        """DR's ukemi on move mi: (first frame of its input window, frame it goes), from its entries to
        the recoveries on the floor (Co_Ukem*, Co_Uker*, Co_newUk*, Co_DUkm*: ym_y01 32..41 going at 41,
        the fall touching the floor at 37), else None."""
        m, c, out = s.dr.m, s.dr.raw[mi][5], []
        for i in range(128):
            cmd, req, mid, ext, ds, de, sf, _ = struct.unpack_from('<IIIIHHHH', s.dr.ram, m.off(c) + i * 24)
            if cmd in (0x8000, 0x8006): break
            t = m.resolve(mid)
            if t < len(m.moves) and m.moves[t]['name'].startswith(('Co_Ukem', 'Co_Uker', 'Co_newUk', 'Co_DUkm')):
                out.append((ds, sf))
        return (min(d for d, _ in out), min(f for _, f in out)) if out else None

    def ukemi(s):
        """The ukemi at DR's frame on the reactions playing DR's animations (the user's arcade test of
        2026-11-07, J6). Their records kept TTT1's ukemi entries (kind 0x1C on a button, and the entries
        going at the same frame: 0x930 / 0x2490 kind 0xB), timed for TTT1's shorter falls: ym_y01 (1222,
        f,N,d,d/f+2's launch) took them at 13..22 while DR's fall touches the floor at 37, and the CPU, which
        takes them, went from the air to its roll on the floor at once, turning (a fast spin, then standing
        early). Each such group moves by as much as DR's ukemi is later (or sooner): its going frame on
        DR's (dr_ukemi(), retimed as the record's clip), each window by the same frames. A DR reaction
        without an ukemi of its own loses TTT1's (sDm_PNGL0_, 1199: the crumple on a knee, left at 13..22
        while kneeling; DR's victim falls, then rises from the floor). Returns [(record, old frame, new
        frame or None when removed)]."""
        rx = s.report.get('reactions', {})
        playing = {int(k): s.by_name[nm] for k, nm in rx.get('paired', {}).items()}
        playing.update({k: s.by_name[nm] for nm, k in rx.get('cloned', {}).items()})
        aliased, out = s.aliased(), []
        for k, x in sorted(playing.items()):
            clip = s.clip_of(s.pack, k)
            u = s.dr_ukemi(x)
            if k in aliased or not clip: continue
            es = [list(e) for e in s.pack.cancels(k)]
            go = {e[7] for e in es if e[4] == 0x1c and e[0] not in (0x10, 0xc000)}
            if len(go) != 1: continue
            t = go.pop()
            group = lambda e: e[0] not in (0x10, 0xc000) and e[4] in (0x1c, 0xb) and e[7] == t
            if u is None:
                s.pack.set_cancels(k, [tuple(e) for e in es if not group(e)])
                out.append((k, t, None))
                continue
            f = (len(clip) - 1) / max(s.cv.ch.frames(s.cv.ch.move(x)[0]) - 1, 1)
            d = min(int(round(u[1] * f)), len(clip) - 1) - t
            if not d: continue
            for e in es:
                if not group(e): continue
                e[5] = max(e[5] + d, 0)
                if e[6] < 255: e[6] = min(e[6] + d, 255)
                e[7] += d
            s.pack.set_cancels(k, [tuple(e) for e in es])
            out.append((k, t, t + d))
        s.report['ukemi'] = out
        return out

    def hands(s):
        """DR's hand poses on the pack's records, for <Name>-DR-hands.bin (HANDS: a DR character, whose
        model has DR's hands). DR sets them by a move's properties (move + 0x30): 0x814A both hands,
        0x814C hand 0 (player + 0x844), 0x814B hand 1 (+ 0x858), the pose being value >> 8 in the hand
        table (moveset + 0x248, animation 0); 0x814D puts the defaults back (poses 2 and 1, fists).
        tools/psp/dr_garde.py _proprietes_mains. Devil Jin's stance asks for pose 19, a half-closed claw
        (Jin's: the defaults); his jab none, the hands staying as they were. Each pose becomes the
        model's pose of the same closure, 0 open .. HAND_STEPS, by how bent its fingers are against the
        stance's: the model's most closed hand is DR's guard claw (persos/<name>.json poing_iso "garde",
        tools/psp/hands.py), not a punch's fist. Levels 0..3 against the punch put the claw at 2, which
        the engine took as the model's pose 2 of 16, nearly open: Devil Jin's stance showed straight
        fingers and a straight wrist (the user, 2026-11-01).
        Returns {record: [(frame, hand 0, hand 1)]}, 255 for a hand left as it is; DR's frames retimed
        as the record's clip was."""
        import dr_iso as D
        sys.path.insert(0, str(X.B1))
        import dr_pose as P
        mot = s.cv.ch.mot
        table = P.hand_table(mot[D.HDR + D.u32(mot, 0x248):])
        bend = [sum(2 * np.degrees(np.arccos(min(1.0, abs(q[3])))) for q in pose) for pose in table]
        m, a = s.dr.m, s.dr.m.lists['move'][0]
        def props(d):
            p = m.u32(a + d * 76 + 0x30)
            for i in range(64) if p else ():
                x, v = struct.unpack_from('<II', s.dr.ram, m.off(p + 8 * i))
                if not x and not v: return
                yield x >> 16, x & 0xffff, v
        # The model's most closed hand is the stance's (the guard claw, pose 19 for Devil Jin); a punch's
        # fist, more bent, is that hand too. Without a stance pose, the table's most bent.
        guard = next((v >> 8 for kind, f, v in props(m.stance) if kind == 0x814a and v >> 8 < len(bend)), None)
        fist = bend[guard] if guard is not None and bend[guard] > 0 else max(bend)
        level = lambda k: min(HAND_STEPS, round(HAND_STEPS * bend[k] / fist)) if k < len(bend) else HAND_STEPS
        out = {}
        for d, k in [*s.dr2rec.items(), *getattr(s, 'ceremony', {}).items()]:
            p = m.u32(a + d * 76 + 0x30)
            events = []
            for i in range(64) if p else ():
                x, v = struct.unpack_from('<II', s.dr.ram, m.off(p + 8 * i))
                if not x and not v: break
                kind, f = x >> 16, x & 0xffff
                if kind not in (0x814a, 0x814b, 0x814c, 0x814d) or f >= 0x4000: continue
                tm = s.timemap.get(d)
                f = int(round(np.interp(f, tm[0], tm[1]))) if tm else f
                pose = v >> 8
                h0, h1 = {0x814a: (level(pose), level(pose)), 0x814c: (level(pose), 255),
                          0x814b: (255, level(pose)), 0x814d: (level(2), level(1))}[kind]
                events.append((min(f, 255), h0, h1))
            if events: out[k] = sorted(events)
        s.report['hands'] = {str(k): v for k, v in sorted(out.items())}
        return out

    def hands_file(s, hands):
        """JHD1: magic, version 2 (hands as the model's pose indices, 0..HAND_STEPS; version 1 had levels
        0..3), record count n, n offsets (0: no change on that record), then at each offset a u16 count and
        count x (frame, hand 0, hand 1, 0) bytes; src/tekken3_dr_camera.c reads it."""
        n = len(s.pack.records)
        head = bytearray(struct.pack('<4sII', b'JHD1', 2, n)) + bytes(4 * n)
        body = bytearray()
        for k, ev in sorted(hands.items()):
            struct.pack_into('<I', head, 12 + 4 * k, len(head) + len(body))
            body += struct.pack('<H', len(ev)) + b''.join(struct.pack('<4B', f, a, b, 0) for f, a, b in ev)
        return bytes(head + body)

    def string_turns(s):
        """A string's next hit entered with transition 14 (rot_mode 2: the attacker turns to the victim up
        to 14 degrees a frame until the hit) enters with 15 (rot_mode 1: a steady turn to the heading
        until the hit). DR's reactions slide the victim sideways (sDm_KAO17L), and the attacker's root, a
        lever turning with him, swung him round it: Devil Jin's b+2, 4, 4, 4 went 60 degrees round Jin
        on the second kick (DR 10), the third took Jin on the side and threw him down (sDm_ASI10LL
        for DR's sDm_ASI00LG). Not 16 (a dash's start: dash_state, the root no longer moves the
        fighter): b+2, 3's kick stayed where b+2 hit and missed Jin. Returns the entries changed."""
        att = {v['record'] for v in s.report['moves'].values() if isinstance(v, dict) and 'record' in v}
        out = []
        for k in sorted(att):
            entries = s.pack.cancels(k)
            new = [(*e[:4], 15, *e[5:]) if e[0] != 0xc000 and e[0] & 0xf and not e[1] and e[4] == 14
                   and e[3] - BASE_ID in att else e for e in entries]
            if new != entries:
                s.pack.set_cancels(k, new)
                out += [(k, e[3] - BASE_ID) for e, x in zip(entries, new) if e != x]
        s.report['string_turns'] = out
        return out

    def alias_records(s):
        """{engine alias: pack record} from the tables' ALIA chunk (see aliased)."""
        t = s.tables
        nr, np_, nc = struct.unpack_from('<3I', t, 12)
        at, out = 32 + nr * 42 + np_ + nc * 4, {}
        while at + 8 <= len(t):
            typ, n = struct.unpack_from('<II', t, at); at += 8
            if typ == 0x41494c41:
                for i in range(0, n, 4):
                    alias, rec = struct.unpack_from('<HH', t, at + i)
                    if rec >= BASE_ID: out[alias] = rec - BASE_ID
            at += n
        return out

    def ceremonies(s):
        """The round start and end of a DR character (CEREMONIES): each record an alias names plays
        the DR animation whole, at DR's length (faster past 255 frames), its end entry moved to it (an
        end window at 0, the animation's end, stays). A pair (move, loop): the loop on the record the
        first one's end goes to. Returns [(alias, DR move, records)]."""
        names = CEREMONIES.get(s.name, {})
        if not names: return []
        alias, out = s.alias_records(), []
        s.ceremony, s.ceremony_records, s.ceremony_rest = {}, {}, {}
        def play(k, name, settle=0):
            mi = s.by_name[name]
            anim, lacet = s.cv.ch.move(mi)
            n = s.cv.ch.frames(anim)
            # Longer than a record (255 frames): played faster to fit (the user, 2026-10-29), not cut; or
            # whole on two records (CEREMONY_WHOLE).
            whole = n > 255 and name in CEREMONY_WHOLE.get(s.name, ())
            m_ = n if whole else min(n, 255)
            poses = s.cv.poses(anim, lacet, [i * (n - 1) / max(m_ - 1, 1) for i in range(m_)])
            # The stance itself (alias 1): the neutral's clip, DR's look at the opponent in it (stance()).
            if mi == s.dr.m.stance: poses = s.clip_of(s.pack, s.pack.neutral)
            if settle: poses = s.settled(poses, s.clip_of(s.pack, s.pack.neutral)[0], settle)
            e = next((list(e) for e in s.pack.cancels(k) if e[0] == 0xc000), [0xc000, 0, 0, 3, 6, 0, 0, 0])
            recs = [k]
            if whole:
                rest = s.pack.add_record(k, NEW_PROVENANCE + 4 * (len(s.pack.records) - s.ttt1.count))
                s.pack.set_clip(k, poses[:255]); s.pack.set_clip(rest, poses[255:])
                s.pack.set_cancels(k, [(0xc000, 0, 0, BASE_ID + rest, 6, 0, 0, 0)])
                # Its move_no (tails()): Tekken 3 blends the last 16 frames to the record the end goes to.
                struct.pack_into('<H', s.pack.records[k], 16, BASE_ID + rest)
                if e[5]: e[5] = e[7] = n - 255
                s.pack.set_cancels(rest, [tuple(e)])
                s.ceremony_rest[k] = rest; recs.append(rest)
            else:
                s.pack.set_clip(k, poses)
                if e[5]: e[5] = e[7] = m_
                s.pack.set_cancels(k, [tuple(e)])
            s.ceremony.setdefault(mi, k)              # its hands (hands()); not an attack of the moveset
            s.ceremony_records[k] = mi                # its sounds (ceremony_sounds())
            return recs
        for a, name in names.items():
            k = alias.get(a)
            if k is None: continue
            if isinstance(name, tuple):
                first, loop = name
                recs = play(k, first)
                nxt = next((e[3] - BASE_ID for e in s.pack.cancels(recs[-1]) if e[0] == 0xc000 and e[3] >= BASE_ID), None)
                if nxt is not None: recs += play(nxt, loop)
                out.append((hex(a), name, recs))
            else: out.append((hex(a), name, play(k, name, INTRO_SETTLE if a in INTRO_ALIASES else 0)))
        s.report['ceremonies'] = out
        return out

    def ceremony_sounds(s):
        """Each ceremony record's sounds list on an event script of its own, DR's sounds at DR's frames
        (LINES, CEREMONY_SCRIPTS); a line stops on the record's last frame (category 0, the same sound:
        Tekken 3 goes on to the next round there, and win B's line, 5.2 s, outlasted its pose played
        faster). DR's 0x8019 at a frame is no sound but Devil Jin's sparks on a bone (his stance's,
        his walk's, win D's hand 16 times): the record's timed property 6 there, the fighter's
        strong-hit effect lit at that bone (0x800458C8, as Yoshimitsu's win poses light his sword).
        Returns [(record, script, [(frame, event)])]."""
        if s.name not in CEREMONY_SCRIPTS or not getattr(s, 'ceremony', None): return []
        m, out, scripts = s.dr.m, [], {}
        for mi, k in sorted(s.ceremony.items(), key=lambda x: x[1]):
            n = s.cv.ch.frames(s.cv.ch.move(mi)[0])
            m_ = n if k in s.ceremony_rest else min(n, 255)
            at, events, props = s.dr.raw[mi][16], [], []
            while at:
                w, v = struct.unpack_from('<II', s.dr.ram, m.off(at)); at += 8
                if not w and not v: break
                prop, f = w >> 16, w & 0xffff
                if f & 0x8000: continue                          # whole-move properties, no frame
                f = min(max(1, round(f * (m_ - 1) / max(n - 1, 1))), m_ - 1)
                if prop == 0x80dd and s.name in LINES:
                    line = SFX_MARK | (LINE_SOUND + v - LINES[s.name])
                    events += [(f, 0x1000 | line), (m_ - 1, line)]
                elif prop == 0x815a and v >> 12 == 1 and str(v & 0xfff) in s.common_sounds():
                    snd = SFX_MARK | (COMMON_SOUND + (v & 0xfff))
                    events += [(f, 0x1000 | snd), (m_ - 1, snd)]
                elif prop == 0x8019 and s.dr_bone(v):
                    props.append((f, 6, s.dr_bone(v)))
                elif prop == 0x801b and s.dr_bone(v >> 8):
                    props.append((f, 6, s.dr_bone(v >> 8)))
                elif prop == 0x815a and 2 <= v >> 12 <= 5:
                    events.append((f, v))
            # A sound once at its last start's place in the order, then each stop once, on the last frame
            # (a start there would follow its stop). A whole ceremony on two records: each its frames.
            stops = sorted({e for f, e in events if not e >> 12})
            starts = sorted({(f, e) for f, e in events if e >> 12 and f < m_ - 1})
            for kk in [x for x, y in s.ceremony_records.items() if y == mi]:
                parts = [(kk, 0, 255), (s.ceremony_rest[kk], 255, m_)] if kk in s.ceremony_rest else [(kk, 0, m_)]
                for i, (r, a, z) in enumerate(parts):
                    ev = [(f - a, e) for f, e in starts if a <= f < z]
                    if i == len(parts) - 1: ev += [(z - a - 1, e) for e in stops]
                    sid = CEREMONY_SCRIPTS[s.name] + len(scripts)
                    scripts[sid] = [max(f, 1) | 1 << 12 | e << 16 for f, e in ev] + [0]
                    s.set_sounds(r, [0x8000 | sid])
                    pr = sorted((f - a, kd, b) for f, kd, b in props if a <= f < z)
                    if pr: s.pack.set_props(r, [(max(f, 1), kd, b) for f, kd, b in pr])
                    out.append((r, sid, ev))
        s.add_event_scripts(scripts)
        s.report['ceremony_sounds'] = out
        return out

    def dr_effects(s, mi):
        """DR move mi's effects on a bone: [(DR frame, TTT1 bone)] (DR_EFFECTS)."""
        m, at, out = s.dr.m, s.dr.raw[mi][16], []
        while at:
            w, v = struct.unpack_from('<II', s.dr.ram, m.off(at)); at += 8
            if not w and not v: break
            prop, f = w >> 16, w & 0xffff
            if f & 0x8000: continue
            bone = s.dr_bone(v) if prop == 0x8019 else s.dr_bone(v >> 8) if prop == 0x801b else 0
            if bone: out.append((f, bone))
        return out

    def move_effects(s):
        """The records playing a DR move get its effects (dr_effects) as timed properties 6 (the strong-hit
        effect lit at the bone, 0x800458C8), at the record's frame for DR's (the move's retiming, timemap).
        The ceremonies have theirs (ceremony_sounds()). Returns {record: [(frame, 6, bone)]}."""
        if s.name not in DR_EFFECTS: return {}
        done, skip = {}, set(getattr(s, 'ceremony_records', {})) | set(getattr(s, 'ceremony_rest', {}).values())
        for mi, ri in sorted(s.dr2rec.items(), key=lambda x: x[1]):
            if ri in skip or ri == s.pack.neutral or ri in done: continue
            fx = s.dr_effects(mi)
            if not fx: continue
            n = struct.unpack_from('<I', s.pack.records[ri], 24)[0] & 0xff
            src, dst = s.timemap.get(mi, ([0, 1], [0, 1]))
            at = lambda f: f if mi not in s.timemap else float(np.interp(f, src, dst))
            new = [(min(max(1, round(at(f))), max(n - 1, 1)), 6, b) for f, b in fx]
            old = s.props_of(ri)
            s.pack.set_props(ri, sorted(set(old) | set(new)))
            done[ri] = new
        s.report['move_effects'] = {str(k): v for k, v in done.items()}
        return done

    def voiceclip(s, mi):
        """DR move mi's sounds list (+0x2C, `voiceclip`): u16s ended by 0xFFFF."""
        at, out = s.dr.raw[mi][15], []
        while at and len(out) < 16:
            v = struct.unpack_from('<H', s.dr.ram, s.dr.m.off(at))[0]; at += 2
            if v == 0xffff: break
            out.append(v)
        return out

    def sounds_of(s, k):
        """Record k's sounds list (word 7)."""
        off, out = s.pack.word(k, 7), []
        if off < s.pack.data_at: return out
        o = off - s.pack.data_at
        while len(out) < 8:
            v = struct.unpack_from('<H', s.pack.data, o)[0]; o += 2
            if v == 0xffff: break
            out.append(v)
        return out

    def event_scripts(s):
        """The tables' event scripts: {id: [entries]} (EVNT chunk, add_event_scripts)."""
        t = s.tables
        nr, np_, nc = struct.unpack_from('<3I', t, 12)
        at = 32 + nr * 42 + np_ + nc * 4
        while at + 8 <= len(t):
            typ, n = struct.unpack_from('<II', t, at)
            if typ == 0x544e5645:
                out, o = {}, at + 8
                while o < at + 8 + n:
                    i, k = struct.unpack_from('<II', t, o)
                    out[i] = list(struct.unpack_from(f'<{k}I', t, o + 8)); o += 8 + 4 * k
                return out
            at += 8 + n
        return {}

    def move_sounds(s):
        """F35: the sounds of the records playing a DR move (dr2rec, the throws' sides of whole_done) as
        DR plays them, from tools/psp/data/dr_sounds_<name>.json (tools/psp/dr_move_sounds.py; none:
        TTT1's lists stay). A record's list (word 7, three entries at most: T3 reads three,
        ko_voice_choose, and pack_edit.compact keeps three):
        - the cry: DR's (0x20nn of the move's voiceclip: attack cry n, image 1), else on an attack
          DR's own draw (DR_DRAW, src/tekken3_ttt1_voices.c); on the script, image 1, when there is one;
        - the impact on a hit: DR's sound for that move (measured, `moves`), else `rules` (punch or
          kick, DR's damage), a marked category-7 sound of the pack's .jus;
        - DR's timed sounds (0x815A at a frame) on an event script of its own, at the record's frame
          for DR's (timemap), with the opponent's cries of the TTT1 script it replaces (a throw's
          victim speaks with its own voice);
        - the swing: DR's, a marked category-6 entry, last (T3 skips category 6; tekken3_ttt1_sfx.c
          plays it for its 0x604A).
        Returns {record: list}."""
        import dr_move_sounds as MS
        t = MS.table(s.name)
        if not t: return {}
        m, idx, rules = s.dr.m, MS.sounds(t), t['rules']
        mark = lambda cat, name: cat << 12 | MS.MARK | idx[name]
        skip = set(getattr(s, 'ceremony_records', {})) | set(getattr(s, 'ceremony_rest', {}).values()) | {s.pack.neutral}
        recs = {ri: mi for mi, ri in s.dr2rec.items()}
        recs.update(s.whole_done)
        old_scripts, scripts, out, left = s.event_scripts(), {}, {}, Counter()
        for ri, mi in sorted(recs.items()):
            if ri in skip: continue
            mv, name = m.moves[mi], m.moves[mi]['name']
            vc, own, attack = s.voiceclip(mi), t['moves'].get(name, {}), mv['first'] > 0
            kick = s.limbs(mi)[0] >= 12 if attack else False
            new, cry = [], None
            forced = [v for v in vc if v >> 12 == 2]
            if forced: cry = forced[0]
            elif attack: cry = MS.DR_DRAW
            if attack and mv['damage'] < 16384:
                imp = own.get('impact')
                if imp is None:
                    imp = next(n for top, n in rules['impact']['kick' if kick else 'punch'] if mv['damage'] <= top)
                if imp: new.append(mark(7, imp))
            # Timed sounds: DR's, then the TTT1 script's cries of the opponent.
            n = struct.unpack_from('<I', s.pack.records[ri], 24)[0] & 0xff
            src, dst = s.timemap.get(mi, ([0, 1], [0, 1]))
            at = lambda f: f if mi not in s.timemap else float(np.interp(f, src, dst))
            ev, a = [], s.dr.raw[mi][16]
            while a:
                w, v = struct.unpack_from('<II', s.dr.ram, m.off(a)); a += 8
                if not w and not v: break
                prop, f = w >> 16, w & 0xffff
                if prop != 0x815a or f & 0x8000: continue
                fr = min(max(1, round(at(f))), max(n - 1, 1))
                code = v >> 12
                timed = t['timed'].get(f'{v:#06x}') or (f'c{v & 0xfff}' if code in (1, 6, 7) else None)
                if code in (2, 3): ev.append(fr | 1 << 12 | v << 16)
                elif timed in idx: ev.append(fr | 1 << 12 | mark(7, timed) << 16)
                else: left[f'{v:#06x}'] += 1
            # The other fighter's cries of TTT1's script: on a throw's victim side (DR's *_y, the record
            # the victim plays) its own (kind 1), elsewhere the opponent's (kind 2).
            # A record with no attack, no DR sound and no throw script keeps TTT1's list (steps,
            # reactions); a throw side's TTT1 script goes (its sounds and Jin's cries are DR's now).
            old = [x for x in s.sounds_of(ri) if x >> 12 == 8]
            if not attack and not ev and not (ri in s.whole_done and old): continue
            other = 1 if name.endswith('_y') else 2
            for e in old:
                ev += [x for x in old_scripts.get(e & 0xfff, []) if x and (x >> 12 & 15) == other and 2 <= x >> 28 <= 5]
            if ev:
                # Three entries at most (T3 reads three, pack_edit.compact keeps three): the cry goes on
                # the script, at image 1.
                if cry is not None: ev.append(1 | 1 << 12 | cry << 16)
                sid = MOVE_SCRIPTS[s.name] + len(scripts)
                scripts[sid] = sorted(ev, key=lambda x: x & 0xfff) + [0]
                new.append(0x8000 | sid)
            elif cry is not None: new.insert(0, cry)
            if attack:
                sw = own.get('swing') or rules['swing']['kick' if kick else 'punch']
                new.append(mark(6, sw))
            s.set_sounds(ri, new)
            out[ri] = new
        s.add_event_scripts(scripts)
        s.report['move_sounds'] = dict(records={str(k): [hex(x) for x in v] for k, v in out.items()},
                                       scripts=len(scripts), left=dict(left))
        return out

    def common_sounds(s):
        """The DR common sounds the character's sound pack has (data/dr_voices.json common)."""
        t = json.loads((HERE / 'data' / 'dr_voices.json').read_text(encoding='utf-8'))
        return t.get(s.name, {}).get('common', {})

    def set_sounds(s, k, sounds):
        """Record k's sounds list (word 7: u16s ended by 0xFFFF), a list of its own in the pack's data."""
        blob = struct.pack(f'<{len(sounds) + 1}H', *sounds, 0xffff)
        s.pack.set_word(k, 7, s.pack.add_data(blob + b'\0' * (-len(blob) % 4)))

    def add_event_scripts(s, scripts):
        """Event scripts appended to the tables' EVNT chunk ({id: [entries ending with 0]})."""
        t = s.tables
        nr, np_, nc = struct.unpack_from('<3I', t, 12)
        at = 32 + nr * 42 + np_ + nc * 4
        while at + 8 <= len(t):
            typ, n = struct.unpack_from('<II', t, at)
            if typ == 0x544e5645:
                add = b''.join(struct.pack('<II', i, len(e)) + struct.pack(f'<{len(e)}I', *e) for i, e in sorted(scripts.items()))
                t[at + 8 + n:at + 8 + n] = add
                struct.pack_into('<I', t, at + 4, n + len(add))
                struct.pack_into('<I', t, 8, len(t))             # the header's size (load_tables)
                return
            at += 8 + n
        raise SystemExit('tables: no EVNT chunk')

    @staticmethod
    def settled(poses, to, frames):
        """poses whose last frames blend into pose `to` (smoothstep, the last one is `to`): the root's
        turn, height and offset in a line, each row's world rotation by slerp."""
        frames = min(frames, len(poses) - 1)
        T, out, prev = X.ttt1_world(to), list(poses[:len(poses) - frames]), None
        for i in range(len(poses) - frames, len(poses)):
            p = poses[i]
            u = (i - (len(poses) - frames - 1)) / frames
            t = u * u * (3 - 2 * u)
            W = X.ttt1_world(p)
            j = X.ttt1_joints({r: X.slerp_matrix(W[r], T[r], t) for r in W}, prev); prev = j
            root = [int(round(X.s16(a) + t * X.s16(X.s16(b) - X.s16(a)))) & 0xffff for a, b in zip(p[:3], to[:3])]
            out.append([*root, *[int(round(v)) & 0xffff for v in j]])
        return out

    def own_record(s, mi, like=None):
        """A record of the pack playing DR move mi's animation whole (copied from the neutral, or like),
        ending into the stance at its last frame; returns it."""
        k = s.pack.add_record(s.pack.neutral if like is None else like, NEW_PROVENANCE + 4 * (len(s.pack.records) - s.ttt1.count))
        anim, lacet = s.cv.ch.move(mi)
        n = min(s.cv.ch.frames(anim), 255)
        s.pack.set_clip(k, s.cv.poses(anim, lacet, list(range(n))))
        s.pack.set_cancels(k, [(0xc000, 0, 0, 3, 6, n, 255, n)])
        return k

    def charge_start(s):
        """CHARGES, before the new moves: the start and the charge as records of their own (the charge in
        dr2rec, so the first level, a move of the sheet, finds its parent), the stance's command to the
        start, the start's end to the charge. Returns (start, charge) or None."""
        c = CHARGES.get(s.name)
        if not c: return None
        z, h = (s.own_record(s.by_name[c[x]]) for x in ('start', 'charge'))
        n = struct.unpack_from('<I', s.pack.records[z], 24)[0] & 0xff
        s.pack.set_cancels(z, [(0xc000, 0, 0, BASE_ID + h, 6, n, 255, n)])
        s.dr2rec[s.by_name[c['start']]] = z
        s.dr2rec[s.by_name[c['charge']]] = h
        s.hook(c['command'], s.by_name[c['start']], z)
        s.report['charge'] = dict(start=z, charge=h)
        return z, h

    def charge_levels(s):
        """CHARGES, after the new moves: each level a record (the first the sheet's; the others copied
        from it, DR's animation, timing, damage and level), the cancel a record of its own, and the
        charge's list as DR's: the cancel on another direction than the one held, each level on the
        buttons released in its window, the top level at DR's last frame, the stance at the end."""
        c = CHARGES.get(s.name)
        if not c or 'charge' not in s.report: return []
        h, m = s.report['charge']['charge'], s.dr.m
        # The sheet's row of the first level (its parent, the release, is no command to the moves' hook):
        # the levels copy the attack the row is like (its reactions, sounds and hit data).
        cmd, row = next(((k, r) for k, r in s.rows.items() if r['DR coup'] == c['levels'][0]), (None, None))
        like = s.by_addr[s.rows[s.like_for(row)]['TTT1 coup']] if row else None
        lv = []
        for name in c['levels']:
            mi = s.by_name[name]
            k = s.dr2rec.get(mi)
            if k is None:
                k = s.own_record(mi, like)
                mv = m.moves[mi]
                s.pack.set_timing(k, mv['first'], mv['last'], mv['damage'] & 0xffff)
                s.pack.set_level(k, mv['hitlevel'] & 0xffff)
                s.pack.records[k][40:44] = bytes(s.limbs(mi))
                s.dr2rec[mi] = k
            lv.append(k)
        cancel = s.own_record(s.by_name[c['cancel']])
        entries = []
        for dc, req, mid, ext, ds, de, sf, opt in (struct.unpack_from('<IIIIHHHH', s.dr.ram, m.off(s.dr.raw[s.by_name[c['charge']]][5]) + i * 24) for i in range(32)):
            if dc in (0x8000, 0x8006): break
            d = m.resolve(mid); d = d[0] if isinstance(d, tuple) else d
            name = m.moves[d]['name'] if d < len(m.moves) else None
            if name == c['cancel']: entries.append((s.code_of(m.label(dc).replace(' ', '')), 0, 0, BASE_ID + cancel, 6, ds, min(de, 255), 1))
            elif name in c['levels'] and dc == 0x2000000:
                entries.append((0x10, BUTTONS_UP << 8, c['buttons'], BASE_ID + lv[c['levels'].index(name)], 6, ds, min(de, 255), 1))
            elif name in c['levels']: entries.append((0x10, 0, 0, BASE_ID + lv[c['levels'].index(name)], 6, ds, min(de, 255), 1))
        n = struct.unpack_from('<I', s.pack.records[h], 24)[0] & 0xff
        entries.append((0xc000, 0, 0, 3, 6, n, 255, n))
        s.pack.set_cancels(h, entries)
        s.report['charge'].update(levels=lv, cancel=cancel, entries=len(entries))
        if cmd: s.report['moves'][cmd] = dict(kind=row['statut'], record=lv[0], like=s.like_for(row), charge=True)
        return lv

    def sparks(s):
        """DR's strong-hit effect on each attack record, in its byte 47 (MoveRec +0x2F, a pad, 0 in
        every TTT1 pack): 0x80 DR's rule, 0x01 lit on a hit, 0x02 lit on a clean hit. DR lights it
        when the damage of the hit entry is 21 or more (the condition 34 entry, clean hit, has its
        own: d, d/b, b+2 20 / 30), whatever part of the body is hit; Tekken 3 when max(base, base x
        the hit sphere's 90..140 %) is (hit_impact 0x80076C28), which lit f+4 (20 x 120 %) and left
        f+2, 3 dark (20 x 90 %). The runtime takes the record's answer instead (the user's choice,
        2026-10-26: damage, hence balance, unchanged). Throws keep Tekken 3's."""
        m, ram = s.dr.m, s.dr.ram
        lit = {}
        for mi, ri in s.dr2rec.items():
            mv = m.moves[mi]
            if not mv['first'] or mv['damage'] >= 16384: continue
            hc, hit, clean = s.dr.raw[mi][10], None, None
            for k, (conds, _) in enumerate(s.dr_entries(mi)):
                damage = m.u32(hc + k * 12 + 4)
                if not conds: hit = damage
                elif conds[0][0] == 34 and clean is None: clean = damage
            if hit is None: continue
            flags = 0x80 | int(hit >= 21) | int((clean if clean is not None else hit) >= 21) << 1
            s.pack.records[ri][47] = flags
            lit[ri] = flags
        s.report['sparks'] = {str(ri): f'{f:#04x}' for ri, f in sorted(lit.items())}
        return lit

    def new_throw(s, cmd, r):
        """A throw DR has and the TTT1 pack not (b+1+4, f+1+3, f+2+4): an attempt copied from 1+3's,
        DR's attempt animation, the first frame bounded by T3's throws; each side leads to the
        record already playing DR's move for it (1+3 and 2+4 share most sides with them), or to a
        new one copied from 1+3's same side, with its victim and a reaction row naming it. Damage of
        a new side: DR's, within the range of the pack's throws (A2 rule 12)."""
        m, t = s.dr.m, s.ttt1
        mi = s.by_name[r['DR coup']]
        like = s.by_addr[s.rows['1+3']['TTT1 coup']]
        t3 = [num(x['T3 1re active']) for x in s.rows.values() if x['T3 dégâts'] == 'prise' and num(x['T3 1re active'])]
        first = max(m.moves[mi]['first'], min(t3)) if t3 else m.moves[mi]['first']
        ri = s.pack.add_record(like, NEW_PROVENANCE + 4 * (len(s.pack.records) - s.ttt1.count))
        anim, _ = s.cv.ch.move(mi)
        src = s.dr_bounds(mi, anim)
        shift = first - src[1]
        last = first + src[2] - src[1]
        dst = [0, first, last, src[3] + shift, src[4] + shift]
        poses, info = s.clip(mi, dst)
        s.pack.set_clip(ri, poses)
        rec = s.pack.records[ri]; rec[45], rec[46] = first, last
        # DR's grabbing limbs: 1+3's left hand stayed back in f+2+4, a right-hand grab (550 short).
        rec[40:44] = bytes(s.limbs(mi))
        sides = s.dr_sides(mi)
        plain = {}
        for c_, c, dm in sides:
            if not c_: plain.setdefault(c, dm)
        entries, made = [], []
        for e in s.pack.cancels(like):
            e = list(e)
            if e[0] != 0xc000:
                dm = plain.get(e[1] >> 8)
                if dm is None: continue
                # The grab is tested on the attempt's own active frames: 1+3's window (12..14) never
                # opened on b+1+4's frame 11, closed before f+2+4's 15.
                e[5:8] = [first, last, first]
                side = e[3] - BASE_ID
                k = next((k for k, d in s.whole_done.items() if d == dm), None)
                if k is None: k = s.side_record(side, dm, made)
                entries += s.variants(e, side, sides, made)
                e[3] = BASE_ID + k
            entries.append(tuple(e))
        s.pack.set_cancels(ri, entries)
        s.dr2rec[mi] = ri
        hooks = s.hook(cmd, mi, ri, enter_as=like)
        s.report['moves'][cmd] = dict(kind=r['statut'], record=ri, first=first, sides_made=made, entries=len(hooks),
                                      entries_added=sum(h[2] == 'added' for h in hooks), **info)

    def parries(s):
        """DR's parries (condition 298 in a cancel list) onto Tekken 3's (A2 rule 11). The parameter
        of 298 is the parried attack's limb, a game bone (8 / 12 / 16 / 20: right hand, left hand,
        right foot, left foot), as T3's condition 0x49 takes it in TTT1 bones (6 / 10 / 14 / 17):
        same mapping as the hitting limbs. The pack's parry state (paired with DR's by movement())
        keeps its 0x49 entries, each reversal record on DR's animation (and its victim's, as a
        throw's); TTT1's reversals of given opponent moves (0x4A, 0x4B), which DR lacks, go."""
        m, done = s.dr.m, []
        joint_row = {j: r for r, j in s.cv.rj.items()}
        joint_row.update({29: joint_row[16], 30: joint_row[19]})
        bone_of = lambda os_: X.ROW_BONE.get(joint_row.get(s.cv.ch.P.OS_JOINT[os_]), None) if os_ < len(s.cv.ch.P.OS_JOINT) else None
        for k, p in s.pairs.items():
            reversals = {}
            c = s.dr.raw[p][5]
            for i in range(64):
                cmd, req, mid, *_ = struct.unpack_from('<IIIIHHHH', s.dr.ram, m.off(c) + i * 24)
                if cmd in (0x8000, 0x8006): break
                for j in range(6):
                    a, b = struct.unpack_from('<HH', s.dr.ram, m.off(req) + j * 4)
                    if a == 330: break
                    if a == 298 and m.resolve(mid) < len(m.moves): reversals[bone_of(b)] = m.resolve(mid)
            if not reversals: continue
            # The reversals can be on the attempt's window, a record of its own the attempt goes on to
            # without input: Jin TTT1's b+1+3 (553, one frame, then 554), which Devil Jin's pack has.
            rev = lambda r: any(e[1] >> 8 == 0x49 for e in s.pack.cancels(r))
            window = [] if rev(k) else [e[3] - BASE_ID for e in s.pack.cancels(k)
                                        if e[0] == 0x10 and e[3] >= BASE_ID and rev(e[3] - BASE_ID)]
            for kk in window or [k]: s.reversals(kk, reversals, done)
            # The window goes on with the attempt's animation (transition 2): DR's, as the attempt has it
            # (Dv_5atemi_L on 553, TTT1's parry on 554 from its second frame).
            c = s.clip_of(s.pack, k)
            for kk in window:
                if c and len(s.clip_of(s.pack, kk) or ()) == len(c): s.pack.set_clip(kk, c)
        s.report['parries'] = done
        return done

    def reversals(s, k, reversals, done):
        """Record k's 0x49 reversals onto DR's (parries()), its 0x4A / 0x4B ones gone."""
        m, t = s.dr.m, s.ttt1
        entries = []
        for e in s.pack.cancels(k):
            cond = e[1] >> 8
            if cond in (0x4a, 0x4b): continue
            if cond == 0x49 and e[3] >= BASE_ID and e[2] in reversals:
                v, dm = e[3] - BASE_ID, reversals[e[2]]
                if s.whole(v, dm): done.append((v, m.moves[dm]['name']))
                he, rx = t.hit_entry_of(v), s.dr.reactions(dm)
                if he and rx and he[0] >= BASE_ID and rx[1] < len(m.moves) and s.whole(he[0] - BASE_ID, rx[1]):
                    done.append((he[0] - BASE_ID, m.moves[rx[1]]['name']))
            entries.append(e)
        s.pack.set_cancels(k, entries)

    def recoveries(s):
        """DR's ends of an attack without a hit, which DR goes on to without input and the pack has no
        record for (Jz_narucom_02 -> Jz_narucom_02E at 15, Jz_autocom_3 -> Jz_narucom_03E at 33): a
        record on their animation whole (copied from the neutral, as prelude()), ending at the stance
        at DR's end, or lying on the record playing DR's lying move (Bmt_hasai -> Bmt_hasai_suka at 40,
        then dwDWN_01U: Tekken 3 played the kick's last frames, Jin rising from the floor). Without it
        Tekken 3 played the attack's 95 frames out, its further strikes too (1, 3 and 1+2+3 showed more
        hits than DR). reorder() then adds the follow-up entry."""
        m, made = s.dr.m, []
        s.parents(m.stance)                              # fills _dests
        playing = {s.by_name[nm]: int(k) for k, nm in s.report.get('reactions', {}).get('paired', {}).items()}
        playing.update(s.dr2rec)
        for p, k in list(s.dr2rec.items()):
            if not s.dr.is_attack(p): continue
            for d in {d for l, d in s._dests.get(p, []) if l in ('', '-')}:
                if d in s.dr2rec or s.dr.is_attack(d) or d == m.stance: continue
                rest = s.dr_rest(d)
                if rest != 's' and rest not in playing: continue
                if not any(q == p and l in ('', '-') for q, l, *_ in s.parents(d)): continue
                r = s.pack.add_record(s.pack.neutral, NEW_PROVENANCE + 4 * (len(s.pack.records) - s.ttt1.count))
                anim, lacet = s.cv.ch.move(d)
                n = min(s.cv.ch.frames(anim), 255)
                # Up to DR's end: the frames after it are none DR shows (Bmt_hasai_suka leaves at 58 of 68,
                # its last 10 had Jin floating above the floor before he lay on 82).
                w = s.dr_end(d)[1]
                if w and w < n - 1: n = w + 1
                s.pack.set_clip(r, s.cv.poses(anim, lacet, list(range(n))))
                w = min(w or n, n)
                s.pack.set_cancels(r, [(0xc000, 0, 0, 3 if rest == 's' else BASE_ID + playing[rest], 6, w, 255, w)])
                s.dr2rec[d] = r
                made.append((m.moves[d]['name'], r))
        s.report['recoveries'] = made
        # An attack DR ends lying (Bmt_hasai, 4, 3: Jin's flip kick, then dwDWN_01U): its record's end
        # went to the stance, Jin up in the air at once. To the record playing DR's lying move instead.
        playing.update(s.dr2rec)
        for p, k in list(s.dr2rec.items()):
            nxt = s.dr_next(p)
            if not s.dr.is_attack(p) or nxt is None or nxt not in playing: continue
            entries = [list(e) for e in s.pack.cancels(k)]
            if not any(e[0] == 0xc000 and e[3] == 3 for e in entries): continue
            for e in entries:
                if e[0] == 0xc000 and e[3] == 3: e[3] = BASE_ID + playing[nxt]
            # DR going on there in the same animation (Power Stance: Jz_zettai_1 -> Jz_zettai_2 at 55 of
            # one 80-frame animation, then Jz_zettai_E at 60, the stance at 67): an entry without input
            # at DR's frame, the animation going on (transition 2); the 0xC000 end only plays at the
            # record's last frame, where the next record started the animation over, Jin taking the
            # stance twice (the user's review of 2026-11-07, J4).
            at = s.dr_goes_on(p, nxt)
            if at is not None and at < (s.pack.word(k, 6) & 0xff):
                entries.insert(next(j for j, e in enumerate(entries) if e[0] == 0xc000),
                               [0x10, 0, 0, BASE_ID + playing[nxt], 2, at, 255, at])
            made.append((m.moves[p]['name'], k, m.moves[nxt]['name'], playing[nxt]))
            s.pack.set_cancels(k, [tuple(e) for e in entries])
        return made

    def dr_goes_on(s, p, d):
        """The frame DR goes from move p to move d without input or condition when d goes on in p's
        animation (continues()), else None."""
        m = s.dr.m
        c = s.dr.raw[p][5]
        for i in range(64):
            cmd, req, mid, ext, ds, de, sf, _ = struct.unpack_from('<IIIIHHHH', s.dr.ram, m.off(c) + i * 24)
            if cmd in (0x8000, 0x8006): return None
            if cmd or s.dr_conds(req) or m.resolve(mid) != d: continue
            return ds if ds and s.continues(p, d, ds) else None
        return None

    def dr_props(s, mi):
        """DR move mi's extra properties: (id, parameter, value) (dr_camera.camera_values' list, move +0x30)."""
        m = s.dr.m
        a, _ = m.lists['move']
        p, out = m.u32(a + mi * 76 + 0x30), []
        for k in range(64) if p else ():
            x, val = struct.unpack_from('<II', s.dr.ram, m.off(p + 8 * k))
            if not x and not val: break
            out.append((x >> 16, x & 0xffff, val))
        return out

    def supercharges(s):
        """DR's charge onto Tekken 3's Supercharge flag (record word 9 bit 16, which only the pack's
        1+2+3+4 has: leaving the move gives the fighter 120 frames, his fists glow through them,
        fighter_active_limbs_update 0x440). DR lights the fists with its hand effects (properties
        0x814b / 0x814c) from the charge's first frame (Jz_mk2zan, the d+1+2 follow-ups), then holds
        the state (0x8067, 150 frames) in the move after (Jz_mk2zan2): both get it, the glow from the
        charge's start (on the second alone it came late). whiff_charges() for b+1+2."""
        out, m = [], s.dr.m
        lit = lambda mi: any(x in (0x814b, 0x814c) and p == 1 for x, p, _ in s.dr_props(mi))
        for mi, k in list(s.dr2rec.items()):
            props = {x for x, *_ in s.dr_props(mi)}
            if 0x8067 not in props: continue
            if 0x80e9 in props: out += s.whiff_charge(mi); continue
            starts = [q for q, l, *_ in s.parents(mi) if l in ('', '-') and q in s.dr2rec and lit(q)]
            if not starts: continue
            for q in [mi] + starts:
                r = s.dr2rec[q]
                if not s.pack.word(r, 9) & 0x10000:
                    s.pack.set_word(r, 9, s.pack.word(r, 9) | 0x10000)
                    out.append((m.moves[q]['name'], r))
        s.report['supercharges'] = out
        return out

    def whiff_charge(s, mi):
        """A DR move holding the charge (0x8067) with property 0x80e9 besides (b+1+2, Power Stance:
        Jz_zettai_1, DR's only one) charges only when it touches nothing: at contact it pushes the
        opponent back (a guard reaction, sGrd_ToroD) and the body's red flare goes out; from afar it
        stays (the user's review of 2026-11-07, J4: the fists never lit). The wiki's Power Stance: after
        the animation Jin has ki for about two seconds, unless he touched the opponent before its end.
        Tekken 3 arms the Supercharge (word 9 bit 16, 120 frames) when a record starts and ends it only
        when either fighter is hit (got_hit), which a guard push is not; its condition 1 (hit_landed)
        holds on the contact frame, guard included. The charge comes at the motion's peak, as in
        Tekken 5 (the user, 2026-11-07: at the end it lit once Jin was back in his guard): DR's cry on
        the move (property 0x815a, Jz_zettai_1's frame 21). A contact before it goes on (transition 2,
        the animation going on) to a copy of the record arming nothing; untouched by then, to a copy
        arming the charge (word 9 bit 16) and pushing no more. An opponent coming into contact after the
        peak is not pushed and the charge stays on, where DR would push him and take it off (Tekken 3
        has no way to end it there; close up the push comes at the first active frame).
        Returns [(DR move, record arming)]."""
        m, k = s.dr.m, s.dr2rec[mi]
        first, last = m.moves[mi]['first'], m.moves[mi]['last']
        cries = [f for x, f, _ in s.dr_props(mi) if x == 0x815a and first < f <= last]
        if not last or not cries: return []
        peak = cries[0]
        own = s.pack.cancels(k)
        new = lambda like: s.pack.add_record(like, NEW_PROVENANCE + 4 * (len(s.pack.records) - s.ttt1.count))
        quiet, charged, rest = new(k), new(k), new(k)
        # Tekken 3 arms the charge when the fighter leaves a record with the flag (fighter_move_advance:
        # the move left's flags; measured: +0x122 = 119 as the next record starts), so the flagged copy
        # lasts one frame, then the rest of the move.
        s.pack.set_word(charged, 9, s.pack.word(charged, 9) | 0x10000)
        # No striking limb after the peak: Tekken 3 lights both fists during the charge only on a move
        # without one (fighter_active_limbs_update 0x440), else just the striking limbs within the active
        # frames (none of them a fist here: nothing lit until the stance). The push then ends there.
        for r in (charged, rest): s.pack.records[r][40:44] = bytes(4)
        s.pack.set_cancels(quiet, own)
        s.pack.set_cancels(rest, own)
        s.pack.set_cancels(charged, [(0x10, 0, 0, BASE_ID + rest, 2, peak + 1, peak + 1, peak + 1)] + list(own))
        s.pack.set_cancels(k, [(0x10, 1 << 8, 0, BASE_ID + quiet, 2, min(first, 255), min(peak - 1, 255), min(first, 255)),
                               (0x10, 0, 0, BASE_ID + charged, 2, peak, peak, peak)] + list(own))
        return [(m.moves[mi]['name'], charged)]

    def end_turns(s):
        """Record word +0x12 (MoveInfo.cancel_rot, added to the fighter's facing when the record ends:
        fighter_move_advance's throw_cancel) for the records playing a DR animation whole (the throws'
        sides): the turn about the vertical from the hips of the record's last pose to those of the
        first pose of the record its end goes to, which every TTT1 throw side has (823 90, 824 -90,
        840 90...). The sides kept TTT1's values on DR's animations: d,d/b,b+1+3 ended with Jin's back
        to Paul (90 for -115, 19 degrees off him as in PPSSPP), u/f+1+2 with Paul turning 90 degrees
        on the floor. An end half_turns() gave the bit 0x80 turns the fighter half round already: the
        record's turn is what is left (Devil Jin's f,f+1+2: hp_y's -180 and the bit, Jin lay with his
        back to Devil Jin and turned round at once as he got up)."""
        out = []
        for k, mi in s.whole_done.items():
            end = next((e for e in s.pack.cancels(k) if e[0] == 0xc000), None)
            if end is None: continue
            nxt = s.pack.neutral if end[3] < BASE_ID else end[3] - BASE_ID
            a, b = s.clip_of(s.pack, k), s.clip_of(s.pack, nxt)
            if not a or not b: continue
            R = X.ttt1_world(a[-1])[0] @ X.ttt1_world(b[0])[0].T
            d = float(np.degrees(np.arctan2(R[0, 2] - R[2, 0], R[0, 0] + R[2, 2])))
            if end[4] & 0x80: d = (d + 360) % 360 - 180
            v = max(-32767, min(32767, int(round(d * 65536 / 360))))
            old = struct.unpack_from('<h', s.pack.records[k], 18)[0]
            if abs(((v - old + 32768) & 0xffff) - 32768) > 182:          # a degree apart
                struct.pack_into('<h', s.pack.records[k], 18, v)
                out.append((k, s.dr.m.moves[mi]['name'], round(old * 360 / 65536), round(d)))
        s.report['end_turns'] = out
        return out

    def landings(s):
        """Record bytes 27 and 26 (MoveInfo.hold_frame, air_end) of the reactions playing a DR animation
        that goes up in the air: the frame its victim reaches the floor, the air window (air_start..
        air_end) ending a frame after it. Tekken 3 lands an airborne victim there and raises the dust
        at his place; TTT1's are DR's (sDw_UP_00_ 47 / 48, sDw_KAO00_ 37 / 38). The clones kept their
        model's (18 / 20): f+1+2's sDm_Uk_PNG_ landed at 20 of 45, the dust left behind Paul still
        flying, DR's body down at 32."""
        rx = s.report.get('reactions', {})
        recs = {int(k) for k in rx.get('paired', {})} | set(rx.get('cloned', {}).values())
        out = []
        for k in sorted(recs):
            hold = s.pack.records[k][27]
            c = s.clip_of(s.pack, k)
            if not hold or not c: continue
            h = [X.s16(p[1]) for p in c]
            top = max(range(len(h)), key=lambda i: h[i])
            if h[top] < 1150: continue                       # not up in the air (falls, ground hits)
            ground = next((i for i in range(top, len(h)) if h[i] < 350), None)
            rec = s.pack.records[k]
            if ground is None or (abs(ground - hold) <= 2 and (not rec[25] or abs(rec[26] - ground - 1) <= 2)): continue
            rec[27] = ground
            if rec[25]: rec[26] = ground + 1             # the air window ends a frame after (TTT1's 48 / 47)
            out.append((k, hold, ground))
        s.report['landings'] = out
        return out

    def air_windows(s):
        """Record bytes 22 (push per frame), 25 / 26 (air window) and 27 (frame held) of the records the
        pack made by copying another one, for the moves DR plays on the ground: 0, as DR's move has them
        (T5 move fields 9, 12, 13, 14 of t5_moveset.MOVE, the same numbers as TTT1's: Co_jplp00 9 / 34 / 33,
        push -9848 forward on u/f). A copy kept its model's: Jin's new moves copied u+1, a jump, and b+4,
        f+4, d/f+4... were airborne from frame 9 to 34 (Tekken 3 put him in the air, pushed him as the jump,
        landed him at 34, and its CPU walked under them as under a jump instead of guarding: C4, PSP-DR.md).
        The moves DR plays in the air keep what the pack gave them (their jumps and Devil Jin's flight were
        validated so; DR's numbers differ on some, report 'air_windows_dr': to judge in the game before
        taking them). Returns [(record, DR move, before)] of the records cleared."""
        own = defaultdict(set)
        for mi, ri in s.dr2rec.items():
            if ri >= s.ttt1.count: own[ri].add(mi)
        rx = s.report.get('reactions', {})
        reacting = {int(k) for k in rx.get('paired', {})} | set(rx.get('cloned', {}).values())
        out, airborne = [], []
        for ri, mis in sorted(own.items()):
            if ri in reacting: continue
            rec = s.pack.records[ri]
            before = (struct.unpack_from('<h', rec, 22)[0], rec[25], rec[26], rec[27])
            dr = {tuple(s.dr.raw[mi][i] for i in (9, 12, 13, 14)) for mi in mis}
            name = s.dr.m.moves[min(mis)]['name']
            if any(d[1] for d in dr):
                if before not in dr: airborne.append((ri, name, list(before), [list(d) for d in sorted(dr)]))
                continue
            if before == (0, 0, 0, 0): continue
            struct.pack_into('<h', rec, 22, 0); rec[25] = rec[26] = rec[27] = 0
            out.append((ri, name, before))
        s.report['air_windows'] = [(ri, n, list(b)) for ri, n, b in out]
        s.report['air_windows_dr'] = airborne
        return out

    def window_order(s):
        """DR's order where the same press opens two entries in turn (Wind God Step: d|d/f+4 ->
        Jz_m_k004 on frames 5..19, before 4 -> kz_syark00 on 1..255; the pack's 4 came first and
        d/f+4 played kz_syark00): an entry DR reads first goes before a later one its press would
        also take, when their windows meet. reorder() takes the first DR entry of an input whatever
        its window (Jz_m_k00 on 1..4). Only for the follow-ups hidden() added off the sheet: the moves
        the user validated keep their lists. Returns the entries moved."""
        m, moved = s.dr.m, 0
        rec2dr = {v: k for k, v in s.dr2rec.items()}
        dirs_of = lambda c: {k + 1 for k in range(9) if (c >> 5 & 0x1ff) >> k & 1} or set(range(1, 10))
        def entries(addr, depth=0):
            for k in range(512):
                cmd, req, mid, ext, ds, de, sf, opt = struct.unpack_from('<IIIIHHHH', s.dr.ram, m.off(addr) + k * 24)
                if cmd == 0x8005 and depth < 4:
                    yield from entries(m.lists['groupCancel'][0] + mid * 24, depth + 1); continue
                if cmd in (0x8000, 0x8006): return
                yield cmd, req, m.resolve(mid), ds, de
        for k in range(len(s.pack.records)):
            p = rec2dr.get(k)
            if p is None: continue
            dr = []
            for c, req, d, ds, de in entries(s.dr.raw[p][5]):
                if d >= len(m.moves) or d not in s.dr2rec or not m.usable(c) or not (m.unconditional(req) or s.own_character(req)): continue
                try: code = s.code_of(m.label(c).replace(' ', ''))
                except (ValueError, KeyError): continue
                if code >= 0x8000 or code == 0x10 or not code & 0xf: continue
                dr.append((code, s.dr2rec[d], ds, de))
            for i, (ci, ri, si, ei) in enumerate(dr):
                for cj, rj, sj, ej in dr[i + 1:]:
                    if ri not in s.deep_added or rj == ri or cj & 0xf & ~(ci & 0xf) or not dirs_of(ci) & dirs_of(cj) or ej < si or sj > ei: continue
                    es = list(s.pack.cancels(k))
                    a = next((n for n, e in enumerate(es) if e[0] == ci and not e[1] and e[3] == BASE_ID + ri), None)
                    b = next((n for n, e in enumerate(es) if e[0] == cj and not e[1] and e[3] == BASE_ID + rj), None)
                    if a is None or b is None or a < b: continue
                    es.insert(b, es.pop(a)); s.pack.set_cancels(k, es); moved += 1
        return moved

    def starts(s):
        """Entries kept from TTT1 that go on with the animation (transition 2) to a record playing a DR move
        DR starts over (its own first pose against the leaving move's pose: Jz_lp00 -> Jz_lprpF at 10,
        2 degrees, against 69 going on): transition 6 instead, at DR's frame (the leaving move's frame
        the switch comes at, Tekken 3's count as DR's). 1, 2 took the jab's record into Jz_lprpF at 9,
        before the jab's frame 10, and played lprpF from 10: the jab never hit, the 2 hit late; 1, 2, 4's
        4 came 13 frames early, Paul out of reach."""
        rec2dr = {}
        for d, r in s.dr2rec.items(): rec2dr.setdefault(r, d)
        rec2dr[s.pack.neutral] = s.dr.m.stance
        out, restarted = [], []
        for k in range(len(s.pack.records)):
            p = rec2dr.get(k)
            # Strings only: the jumps' attacks go on with the jump (TTT1's, its airborne motion with them).
            if p is None or not s.dr.is_attack(p): continue
            entries, changed = [list(e) for e in s.pack.cancels(k)], False
            for e in entries:
                if e[0] == 0xc000 or e[4] & 0x3f != 2 or e[3] < BASE_ID: continue
                d = rec2dr.get(e[3] - BASE_ID)
                link = next((x for x in s.parents(d) if x[0] == p), None) if d is not None else None
                if not link or s.continues(p, d, link[4]): continue
                if e[7] > 1: restarted.append((e[3] - BASE_ID, e[7]))
                e[4], e[7] = (e[4] & 0xc0) | 6, min(link[4], 255)
                changed = True
                out.append((k, e[3] - BASE_ID, s.dr.m.moves[d]['name'], e[7]))
            if changed: s.pack.set_cancels(k, [tuple(e) for e in entries])
        # The windows of a record now started from its frame 1 that reorder() moved for its going on from
        # a later frame go back to DR's (Jz_lprpF's 3 into Jz_lprpFE, 1..9, moved to 9..17 for the 2's
        # start at 9: 1, 2, 3's 3 came too late).
        for r, was in restarted:
            p = rec2dr.get(r)
            entries, changed = [list(e) for e in s.pack.cancels(r)], False
            for e in entries:
                d = rec2dr.get(e[3] - BASE_ID) if e[0] != 0xc000 and e[3] >= BASE_ID else None
                link = next((x for x in s.parents(d) if x[0] == p), None) if d is not None and p is not None else None
                if link and (e[5], e[6]) == (min(link[2] + was - 1, 255), min(link[3] + was - 1, 255)):
                    e[5], e[6] = link[2], link[3]; changed = True
            if changed: s.pack.set_cancels(r, [tuple(e) for e in entries])
        s.report['starts'] = out
        return out

    def hit_limbs(s):
        """A common move's record hitting with another limb than DR's move does: DR's limbs (limbs()). 1, 2's
        record (169) is TTT1's jab half of 1, 2 (left hand), its DR move Jz_lprpF the right straight: its
        capsule followed the left fist pulled back and the 2 never hit."""
        out = []
        for mi, k in s.dr2rec.items():
            if not s.dr.is_attack(mi): continue
            d = s.limbs(mi)
            if d[0] and s.pack.records[k][40] != d[0]:
                s.pack.records[k][40:44] = bytes(d)
                out.append((k, s.dr.m.moves[mi]['name'], d))
        s.report['hit_limbs'] = out
        return out

    def tails(s):
        """Record word +0x10 (MoveInfo.move_no) set to the record its end goes to, as every TTT1 record has
        it. Tekken 3 blends a move's last 16 frames towards frame 0 of that record (anim_blend_update mode 3,
        fighter_anim_tail_frames): records ending lying kept the neutral's (3), and Jin rose to his standing
        hips height on the floor before lying on 82 (4, 3: Bmt_hasai_suka, from 133 to 965)."""
        out = []
        for k in range(len(s.pack.records)):
            end = next((e[3] for e in s.pack.cancels(k) if e[0] == 0xc000), None)
            if end is None or struct.unpack_from('<H', s.pack.records[k], 16)[0] == end: continue
            struct.pack_into('<H', s.pack.records[k], 16, end)
            out.append((k, end - BASE_ID if end >= BASE_ID else end))
        s.report['tails'] = out
        return out

    def dr_conds(s, req):
        """The (condition, parameter) pairs of a DR entry's requirement list (330 ends it; an empty pair is
        skipped: Jz_m_k20_D's lists to Jz_mk2_dou open with one before their 42, read as no condition)."""
        m, out = s.dr.m, []
        if not req: return out
        for j in range(8):
            a, b = struct.unpack_from('<HH', s.dr.ram, m.off(req) + j * 4)
            if a == 330: break
            if a or b: out.append((a, b))
        return out

    def on_hit(s):
        """DR's follow-ups on a hit (condition 42 alone, no input): f+4 goes on to Jz_hiza_up02 when it
        hits, f+4, d+1+2 (Jz_hiza_up01) to the charge Jz_mk2zan, then Jz_mk2zan2; d/f+3, d+1+2 and
        b+2, 3, d+1+2 the same way. Tekken 3 has the condition (cancel_cond_test 1: hit_landed), no TTT1
        pack uses it; without it Jin stood back after the hit. DR's moves there without a hit of their
        own get a record on their animation whole (copied from the neutral, ending at the stance at DR's
        end), and the moves they lead to as well; reorder() then gives their inputs and follow-ups."""
        m, made, added = s.dr.m, [], []
        playing = {s.by_name[nm]: int(k) for k, nm in s.report.get('reactions', {}).get('paired', {}).items()}
        def make(d, depth=0):
            if d in s.dr2rec: return s.dr2rec[d]
            if depth > 3 or s.dr.is_attack(d) or d == m.stance or d >= len(m.moves): return None
            anim, lacet = s.cv.ch.move(d)
            n = min(s.cv.ch.frames(anim), 255)
            w = s.dr_end(d)[1]
            if w and w < n - 1: n = w + 1
            r = s.pack.add_record(s.pack.neutral, NEW_PROVENANCE + 4 * (len(s.pack.records) - s.ttt1.count))
            s.pack.set_clip(r, s.cv.poses(anim, lacet, list(range(n))))
            w = min(w or n, n)
            # Ending as DR's: lying on the record playing DR's next move (Bmt_hasaiE2 -> dwDWN_01U, 82).
            nx = s.dr_next(d)
            end = BASE_ID + playing[nx] if nx is not None and nx in playing else 3
            s.pack.set_cancels(r, [(0xc000, 0, 0, end, 6, w, 255, w)])
            s.dr2rec[d] = r
            made.append((m.moves[d]['name'], r))
            for _, t in s.dr.links(d): make(t, depth + 1)
            return r
        for p, k in list(s.dr2rec.items()):
            if not s.dr.is_attack(p): continue
            c = s.dr.raw[p][5]
            for i in range(64):
                cmd, req, mid, ext, ds, de, sf, _ = struct.unpack_from('<IIIIHHHH', s.dr.ram, m.off(c) + i * 24)
                if cmd in (0x8000, 0x8006): break
                conds = s.dr_conds(req)
                # 42 alone, or with one of DR's state tests (0x8000 and up: Jz_mk2_dou -> Bmt_hasaiE2 on
                # (42) (33115, 28683), its victim lying): Tekken 3 has no such test, the hit is enough.
                if cmd or not conds or conds[0] != (42, 0) or any(c < 0x8000 for c, _ in conds[1:]) or len(conds) > 2: continue
                d = m.resolve(mid)
                # Back to the stance on a hit in one of DR's states (jz_c20E, Jz_zan_tuki...): not that.
                if d == m.stance and len(conds) > 1: continue
                r = make(d)
                if r is None: continue
                entries = [list(e) for e in s.pack.cancels(k)]
                if any(e[1] >> 8 == 1 and e[3] == BASE_ID + r for e in entries): continue
                # Before the follow-ups without input its window meets: the engine takes the first that
                # holds, and Mukurowari's TTT1 0x10 entries (its hit follow-up, the landing kz_ho_11) took
                # the hit before DR's kz_ho_10_2. Not with a DR state test besides (Jz_shoryu34 ->
                # Jz_shoryuH on 0x8001 too, which DR's Command List demo hits without): those stay last.
                at = next((j for j, e in enumerate(entries) if e[0] == 0xc000 or
                           (len(conds) == 1 and e[0] == 0x10 and e[5] <= min(de, 255) and e[6] >= min(ds, 255))), len(entries))
                # A window opening on DR's hit frame, on the record's (LATE_REORDER): Tekken 3 reads hit_landed
                # on the frame the record hits only, and the sheet's bounds put Paul's d+4 a frame before
                # DR's (14, DR 15..15 -> pol_sk00H: never taken).
                lag = s.pack.records[k][45] - m.moves[p]['first']
                if s.name in LATE_REORDER and ds == m.moves[p]['first'] and lag and abs(lag) <= 2: ds, de, sf = ds + lag, de + lag, sf + lag
                entries.insert(at, [0x10, 1 << 8, 0, BASE_ID + r, 2 if s.continues(p, d, sf) else 6,
                                    min(ds, 255), min(de, 255), min(sf, 255)])
                s.pack.set_cancels(k, [tuple(e) for e in entries])
                added.append((m.moves[p]['name'], k, m.moves[d]['name'], r))
        s.report['on_hit'] = dict(records=made, entries=added)
        return added

    def reorder(s, passes=12):
        """Entries put in DR's order where Tekken 3 would take another move for the same input. Both games
        take the first unconditional entry whose buttons are all held (command_match; DR's stance has
        d/b+4 -> Jz_t_srk02 before d/b+3+4 -> Co_t_slk00, and d/b+3+4 plays Jz_t_srk02 in PPSSPP), so the
        pack's lists must keep DR's order where it matters (Jin's walk back: b+3 -> Jz_uchi_LK before the
        3; his stance: u/f+1+2 -> the throw before the jump punch); a direction alone takes the input in
        Tekken 3 and not in DR (d+1 is DR's Corpse Thrust). For each pack list
        playing a DR move (or standing for the stance), each of that move's DR entries is pressed as DR
        reads it: when the move Tekken 3 would start is not DR's, the entry leading to DR's record goes
        just before the one taking it (windows overlapping). Returns the entries moved."""
        m, moved = s.dr.m, 0
        s.on_hit()
        # The moves after DR's on-hit records (Demolition Man: pol_sk00H, 2 -> rakuyo2JST, 1+2 ->
        # Pl_raklpW), off the sheet since only a hit opens them: hidden() again.
        if s.name in LATE_REORDER:
            for n, ri in s.hidden():
                # Their reactions and pushes as DR's (reactions() ran before them: Pl_raklpW kept the copied
                # move's row, Demolition Man's last hit sent the victim half as far as DR's).
                s.report.setdefault('after_hits', []).append((n, ri, bool(s.react(s.by_name[n], ri))))
        s.recoveries()
        # Their ends into a lying record half_turns() turned turn the fighter too (Incomplete Somersault:
        # Pl_smrk00C into dwKAM_00D, Paul swung round on the floor at the change).
        if s.name in LATE_REORDER:
            s.report['recovery_turns'] = s.turn_ends({k for _, k, *_ in s.report.get('recoveries', [])})
        # A common move's start that DR plays without a hit (Jin's Corpse Thrust: DR d+1 is Jz_bodylp00,
        # then without input Jz_bodylp01; TTT1 d/b+1 then 270): the record whose follow-up without input
        # leads to the common move's, when there is one, plays that DR start. DR's own command then
        # comes with the entries below (d/b+1 is DR's crouching jab).
        for d, ri in list(s.dr2rec.items()):
            for p, label, *_ in s.parents(d):
                if label not in ('', '-') or p in s.dr2rec or s.dr.is_attack(p): continue
                ks = [k for k in range(len(s.pack.records)) if k != ri
                      and any(e[0] == 0x10 and not e[1] and e[3] == BASE_ID + ri for e in s.pack.cancels(k))]
                if len(ks) != 1 or ks[0] in s.dr2rec.values(): continue
                k = ks[0]
                s.dr2rec[p] = k
                # DR's animation whole, and DR's frame for the follow-up.
                if s.whole(k, p):
                    w = next((x[2:] for x in s.parents(d) if x[0] == p), None)
                    if w:
                        s.pack.set_cancels(k, [(*e[:5], *[min(v, 255) for v in w]) if e[0] == 0x10 and e[3] == BASE_ID + ri else e
                                               for e in s.pack.cancels(k)])
        rec2dr = {v: k for k, v in s.dr2rec.items()}
        rec2dr[s.pack.neutral] = m.stance
        dirs_of = lambda c: [k + 1 for k in range(9) if (c >> 5 & 0x1ff) >> k & 1] or list(range(1, 10))
        t3_takes = lambda e, d, b: (not e[1] and e[0] < 0x8000 and e[0] != 0x10 and e[0] & 0xf and not e[0] & 0xf & ~b
                                    and d in dirs_of(e[0]))
        # An entry of a direction alone takes the input too (the stance's d, to the crouch, took d+1:
        # DR's Corpse Thrust, which DR gives since its d has no button).
        steals = lambda e, d, b: t3_takes(e, d, b) or (not e[1] and e[0] < 0x8000 and e[0] != 0x10 and not e[0] & 0xf
                                                     and e[0] >> 5 & 0x1ff and d in dirs_of(e[0]))
        starts = defaultdict(set)                      # frame each record is entered at (transition 2 goes on)
        for kk in range(len(s.pack.records)):
            for e in s.pack.cancels(kk):
                if e[3] >= BASE_ID and e[0] != 0xc000: starts[e[3] - BASE_ID].add(e[7] if e[4] & 0x3f == 2 else 1)
        for k in range(len(s.pack.records)):
            p = rec2dr.get(k)
            if p is None: continue
            dr = []
            for c, req, d in m.cancels(s.dr.raw[p][5]):
                # DR's entries for this fighter only too (Devil Jin's walk back: b+1+3 -> Dv_5atemi_L,
                # condition 143 26, before the 1+3 throw; Tekken 3 took the throw).
                if d >= len(m.moves) or not m.usable(c) or not (m.unconditional(req) or s.own_character(req)): continue
                try: code = s.code_of(m.label(c).replace(' ', ''))
                except (ValueError, KeyError): continue
                if code >= 0x8000 or code == 0x10 or not code & 0xf: continue
                dr.append((code, d))
            for _ in range(passes):
                entries = [list(e) for e in s.pack.cancels(k)]
                changed = False
                for code, _ in dr:
                    b = code & 0xf
                    for dirn in dirs_of(code):
                        # Each DR entry's input (d/b+3+4 too), and the move DR gives for it: the first
                        # entry it holds (d/b+4 -> Jz_t_srk02, before d/b+3+4 -> Co_t_slk00).
                        d = next(x for c2, x in dr if not c2 & 0xf & ~b and dirn in dirs_of(c2))
                        r = s.dr2rec.get(d)
                        if r is None: continue
                        # The most precise of its entries for the input (f+3+4 rather than f+3: moving the
                        # f+3 one for f+3+4 put Jz_lk00F back before Jz_mikazuki every pass).
                        own = [i for i, e in enumerate(entries) if e[3] == BASE_ID + r and t3_takes(e, dirn, b)]
                        mine = max(own, key=lambda i: (bin(entries[i][0] & 0xf).count('1'), -i)) if own else None
                        if mine is None:
                            # No entry to DR's move in this list (Jin's walk forward: f+3 is Jz_mikazuki
                            # in DR, the pack's walk took f+3 to Jz_lk00F): one at DR's window, before the
                            # entry taking the input.
                            w = next(((ds, de, sf) for q, l, ds, de, sf in s.parents(d) if q == p), None)
                            thief = next((i for i, e in enumerate(entries) if steals(e, dirn, b)), None)
                            if thief is None:     # nothing takes it: before the end entry
                                thief = next((i for i, e in enumerate(entries) if e[0] == 0xc000), len(entries))
                            if w is None: continue
                            entries.insert(thief, [code, 0, 0, BASE_ID + r, 6, min(w[0], 255), min(w[1], 255), min(w[2], 255)])
                            moved += 1; changed = True; continue
                        thief = next((i for i, e in enumerate(entries[:mine]) if steals(e, dirn, b) and e[3] != BASE_ID + r
                                      and e[5] <= entries[mine][6] and entries[mine][5] <= e[6]), None)
                        if thief is None: continue
                        entries.insert(thief, entries.pop(mine)); moved += 1; changed = True
                if not changed: break
                s.pack.set_cancels(k, [tuple(e) for e in entries])
            entries = [list(e) for e in s.pack.cancels(k)]
            # TTT1's follow-ups without input to a record no DR move plays (1, 2 went on to TTT1's 171
            # at frame 10, before DR's 3 could come): DR's move has none of them. A parry's catch window
            # stays (TTT1's b+1+3: 553 a frame, then 554 with the reversals, condition 0x49; Devil Jin's
            # Dv_5atemi_L on 553 lost it and caught nothing).
            playing = set(s.dr2rec.values()) | {s.pack.neutral}
            catches = lambda r: any(x[1] >> 8 in (0x49, 0x4a, 0x4b) for x in s.pack.cancels(r))
            kept = [e for e in entries if not (e[0] == 0x10 and not e[1] and e[3] >= BASE_ID and e[3] - BASE_ID not in playing
                                               and not catches(e[3] - BASE_ID))]
            moved += len(entries) - len(kept); entries = kept
            # DR's follow-ups without input to a move the pack plays, missing here (Jz_c20 -> jz_c20E:
            # d+3+4's new record had only its end entry).
            for q, d in [(q, d) for d in s.dr2rec for q, l, *_ in s.parents(d) if q == p and l in ('', '-')]:
                r = s.dr2rec[d]
                if r == k or any(e[3] == BASE_ID + r for e in entries): continue
                ds, de, sf = next(x[2:] for x in s.parents(d) if x[0] == p and x[1] in ('', '-'))
                at = next((i for i, e in enumerate(entries) if e[0] == 0xc000), len(entries))
                entries.insert(at, [0x10, 0, 0, BASE_ID + r, 2 if s.continues(p, d, sf) else 6, min(ds, 255), min(de, 255), min(sf, 255)])
                moved += 1
            # DR counts a list's windows from the move's entry, Tekken 3 in the animation's frames, which
            # a record entered going on with the animation starts further on (Jz_lprpF at 9 after the
            # jab: its 3 on 1..9 never came). A window closed before that start moves by as much.
            # The start of the entries from DR's parents' records (the jab's 2 into Jz_lprpF at 9).
            from_dr = {e[7] if e[4] & 0x3f == 2 else 1 for q, *_ in s.parents(p) if q in s.dr2rec
                       for e in s.pack.cancels(s.dr2rec[q]) if e[3] == BASE_ID + k and e[0] != 0xc000}
            start = min(from_dr or starts.get(k, {1}))
            if start > 1:
                for e in entries:
                    if e[0] != 0xc000 and e[3] >= BASE_ID and e[3] - BASE_ID in s.dr2rec.values() and e[6] <= start:
                        e[5], e[6] = min(e[5] + start - 1, 255), min(e[6] + start - 1, 255); moved += 1
            s.pack.set_cancels(k, [tuple(e) for e in entries])
        s.report['reordered'] = moved
        return moved

    def stances(s):
        """STANCES: a record for each, on DR's animation whole, copied from the neutral; its list DR's
        entries to the moves the pack plays already (Mental Alertness 2: f the dash, d/f the crouch dash)
        at DR's windows, its end at DR's free frame back to the stance; then the entries into it from
        the stance's lists (hook). The moves from it come with new(), into its own list only."""
        done = []
        s.parents(0)
        for name in STANCES.get(s.name, ()):
            d = s.by_name.get(name)
            if d is None or d in s.dr2rec: continue
            k = s.pack.add_record(s.pack.neutral, NEW_PROVENANCE + 4 * (len(s.pack.records) - s.ttt1.count))
            anim, lacet = s.cv.ch.move(d)
            n = min(s.cv.ch.frames(anim), 255)
            s.pack.set_clip(k, s.cv.poses(anim, lacet, list(range(n))))
            free = min(s.dr.step(d)[0], n - 1)
            entries = []
            for x, rec in list(s.dr2rec.items()):
                for p, label, ds, de, sf in s._parents.get(x, ()):
                    if p != d: continue
                    try: code = s.code_of(label)
                    except (ValueError, KeyError): continue
                    entries.append((code, 0, 0, BASE_ID + rec, 2 if code == 0x10 and s.continues(d, x, sf) else 6,
                                    min(ds, 255), min(de, 255), min(sf, 255)))
            entries.append((0xc000, 0, 0, 3, 6, free, 255, free))
            s.pack.set_cancels(k, entries)
            s.dr2rec[d] = k
            s.own.add(d)
            hooks = s.hook(name, d, k)
            if not hooks:
                del s.dr2rec[d]; s.own.discard(d); continue
            done.append((k, name, n, len(hooks)))
        s.report['stances'] = done
        return done

    def deflects(s):
        """DR's parry that deflects without a counter (Jin's b+1+3 / b+2+4: AteN_move_0, then on a high
        or mid attack of a given limb, conditions 313 / 314 with the limb as 298's, a block move
        sBL_h* / sBL_m*, no damage) onto the TTT1 parry the same command starts (546, its window 547 of
        reversals 0x49 / 0x4A / 0x4B): the attempt and its window on DR's animation, the reversals
        replaced by Tekken 3's high / mid parries with a limb (0x46 / 0x47, cancel_on_hit_cond_test),
        each to a record on DR's block move, back to the stance at DR's frame (A2 rule 11). DR's parries
        of given opponent moves (317) go, as 0x4A / 0x4B did."""
        m, done = s.dr.m, []
        joint_row = {j: r for r, j in s.cv.rj.items()}
        joint_row.update({29: joint_row[16], 30: joint_row[19]})
        bone_of = lambda os_: X.ROW_BONE.get(joint_row.get(s.cv.ch.P.OS_JOINT[os_]), None) if os_ < len(s.cv.ch.P.OS_JOINT) else None

        def dr_list(p):
            c = s.dr.raw[p][5]
            for i in range(64):
                cmd, req, mid, ext, ds, de, sf, opt = struct.unpack_from('<IIIIHHHH', s.dr.ram, m.off(c) + i * 24)
                conds = []
                for j in range(6):
                    a, b = struct.unpack_from('<HH', s.dr.ram, m.off(req) + j * 4)
                    if a == 330: break
                    conds.append((a, b))
                yield cmd, conds, m.resolve(mid), ds, de, sf
                if cmd in (0x8000, 0x8006): return

        attempts = {}
        for c, req, d in m.cancels(s.dr.raw[m.stance][5]):
            if d < len(m.moves) and m.usable(c) and not m.unconditional(req) and d not in attempts.values() \
                    and any(cond in (313, 314) for _, conds, *_ in dr_list(d) for cond, _ in conds):
                attempts[m.label(c).replace(' ', '')] = d
        for label, d in attempts.items():
            code = s.code_of(label)
            k = next((e[3] - BASE_ID for e in s.pack.cancels(s.pack.neutral) if e[0] == code and not e[1] and e[3] >= BASE_ID), None)
            if k is None: continue
            window = next((e[3] - BASE_ID for e in s.pack.cancels(k) if e[0] == 0x10 and e[3] >= BASE_ID), None)
            if window is None: continue
            after = next((e[3] - BASE_ID for e in s.pack.cancels(window) if e[0] == 0x10 and not e[1] and e[3] >= BASE_ID), None)
            if d not in s.dr2rec:
                s.whole(k, d)
                s.whole_done.pop(window, None); s.whole(window, d)
                s.dr2rec[d] = k
            entries, blocks, dr_after = [], {}, None
            for cmd, conds, x, ds, de, sf in dr_list(d):
                if cmd == 0 and conds and conds[0][0] in (313, 314) and x < len(m.moves):
                    bone = bone_of(conds[0][1])
                    if bone is None: continue
                    if x not in blocks:
                        r = next((rr for rr, nm in done if nm == m.moves[x]['name']), None)
                        if r is None:
                            r = s.pack.add_record(after if after is not None else window,
                                                  NEW_PROVENANCE + 4 * (len(s.pack.records) - s.ttt1.count))
                            anim, lacet = s.cv.ch.move(x)
                            n = min(s.cv.ch.frames(anim), 255)
                            s.pack.set_clip(r, s.cv.poses(anim, lacet, list(range(n))))
                            back = min(s.dr_end(x)[1] or n - 1, 255)
                            s.pack.set_cancels(r, [(0xc000, 0, 0, 3, 6, back, 255, back)])
                            done.append((r, m.moves[x]['name']))
                        blocks[x] = r
                    level = 0x46 if conds[0][0] == 313 else 0x47
                    e = (0x10, level << 8, bone, BASE_ID + blocks[x], 6, min(ds, 255), min(de, 255), min(sf, 255))
                    if e not in entries: entries.append(e)
                elif cmd == 0 and not conds and x < len(m.moves) and dr_after is None:
                    dr_after = (x, ds)
            if not entries: continue
            if any(e[1] >> 8 in (0x46, 0x47) for e in s.pack.cancels(window)): continue    # b+2+4: same window
            out = []
            for e in s.pack.cancels(window):
                if e[1] >> 8 in (0x49, 0x4a, 0x4b): continue
                if e[0] == 0x10 and not e[1] and after is not None and e[3] == BASE_ID + after and dr_after:
                    s.whole(after, dr_after[0]); s.dr2rec.setdefault(dr_after[0], after)
                    e = (*e[:5], dr_after[1], dr_after[1], dr_after[1])
                out.append(e)
            s.pack.set_cancels(window, entries + out)
        s.report['deflects'] = done
        return done

    def movement(s, limit=400):
        """Stance, walks, dashes, crouch, jumps... with DR's animations (decision 2 of the design):
        the two graphs walked together from the stance, through the entries without a hit, a pack
        record paired with the DR move its same command leads to (T3 text = DR label, at most two
        frames apart in length: T5 kept T3's lengths, 20 / 20 for the walk, 30 / 30 for the dash).
        Retimed on the record's length; the mechanics stay the pack's (A2 rule 13)."""
        m, t = s.dr.m, s.ttt1
        def dr_edges(p):
            seen = []
            for c, req, d in m.cancels(s.dr.raw[p][5]):
                if d < len(m.moves) and m.usable(c) and not s.dr.is_attack(d):
                    seen.append((m.label(c).replace(' ', ''), d, m.unconditional(req)))
            return seen
        def pack_edges(k):
            out = []
            for e in s.pack.cancels(k):
                if e[0] == 0xc000: continue
                d = t.resolve(e[3]) if e[3] >= BASE_ID else None
                tx = t.text(e[0])
                if d is not None and tx and d < t.count and not t.is_attack(d): out.append((tx.replace(' ', ''), d, not e[1]))
            # The end entry: where the record goes on its own (dash -> its end, crouch -> crouch stance).
            for e in s.pack.cancels(k):
                if e[0] == 0xc000 and e[3] >= BASE_ID and t.resolve(e[3]) is not None: out.append(('<end>', t.resolve(e[3]), True))
            return out
        def dr_end(p):
            c = s.dr.raw[p][5]
            for k in range(256):
                cmd, req, mid, *_ = struct.unpack_from('<IIIIHHHH', s.dr.ram, m.off(c) + k * 24)
                if cmd == 0x8000:
                    d = m.resolve(mid); return [('<end>', d, True)] if d < len(m.moves) else []
                if cmd == 0x8005: return []
            return []
        frames = lambda k: struct.unpack_from('<I', s.pack.records[k], 24)[0] & 0xff
        pairs, todo = {s.pack.neutral: m.stance}, [(s.pack.neutral, m.stance)]
        # The crouch, a loop like the stance: Tekken 3's alias 40, DR's alias 2, DR's own length.
        crouch = t.resolve(t.alia.get(40, 40))
        if crouch is not None and crouch != s.pack.neutral:
            anim, lacet = s.cv.ch.move(m.aliases[2])
            s.pack.set_clip(crouch, s.pack_root(crouch, s.cv.poses(anim, lacet, list(range(s.cv.ch.frames(anim))))))
            pairs[crouch] = m.aliases[2]; todo.append((crouch, m.aliases[2]))
        while todo and len(pairs) < limit:
            k, p = todo.pop(0)
            de = dr_edges(p) + dr_end(p)
            for label, kk, plain in pack_edges(k):
                if kk in pairs or kk in s.dr2rec.values(): continue
                fk = frames(kk)
                # An unconditional entry with an unconditional one (the walk, not the turn that
                # DR puts first under its condition), then the closest length.
                cand = sorted(((u != plain, abs(m.moves[d]['anim_len'] - fk), i, d) for i, (l, d, u) in enumerate(de)
                               if l == label and d not in pairs.values() and abs(m.moves[d]['anim_len'] - fk) <= 2))
                cand = [c[-1] for c in cand]
                if not cand: continue
                pairs[kk] = cand[0]; todo.append((kk, cand[0]))
        done = []
        for k, p in pairs.items():
            if k in (s.pack.neutral, crouch): continue
            anim, lacet = s.cv.ch.move(p)
            n, fk = s.cv.ch.frames(anim), frames(k)
            times = [i * (n - 1) / max(fk - 1, 1) for i in range(fk)]
            s.pack.set_clip(k, s.pack_root(k, s.cv.poses(anim, lacet, times)))
            done.append((k, m.moves[p]['name'], fk, n))
        s.report['movement'] = done
        s.pairs = pairs
        return done

    def side_steps(s):
        """The pack's side steps on DR's (SIDE_STEPS): the step's record and its end's together on DR's
        animation, the root the pack's. DR's step then leads on (hidden(): Devil Twister on N+2)."""
        frames = lambda k: struct.unpack_from('<I', s.pack.records[k], 24)[0] & 0xff
        done = []
        for head, tail, name in SIDE_STEPS.get(s.name, ()):
            k, kt, p = s.by_addr[head], s.by_addr[tail], s.by_name[name]
            anim, lacet = s.cv.ch.move(p)
            n, fk, ft = s.cv.ch.frames(anim), frames(k), frames(kt)
            poses = s.cv.poses(anim, lacet, [i * (n - 1) / max(fk + ft - 1, 1) for i in range(fk + ft)])
            s.pack.set_clip(k, s.pack_root(k, poses[:fk]))
            s.pack.set_clip(kt, s.pack_root(kt, poses[fk:]))
            s.dr2rec[p] = k; s.pairs[k] = p; s.step_tails[kt] = (p, fk)
            done.append((k, kt, name))
        s.report['side_steps'] = done
        return done

    def step_moves(s):
        """The attacks DR's side step leads to that the pack lacks (Paul's SS+1 / SS+3, 143 on him), for a
        fighter whose follow-ups hidden() does not take that deep: made with their entries from the step.
        Returns [(DR move, record)]."""
        if s.name in DEEP_FOLLOWUPS: return []
        m, done = s.dr.m, []
        for *_, name in SIDE_STEPS.get(s.name, ()):
            for label, d in s.links(s.by_name[name]):
                mv = m.moves[d]
                if d in s.dr2rec or not mv['damage'] or mv['damage'] >= 16384: continue
                x = s.dr.row(d)
                r = {'DR coup': mv['name'], 'DR niveau': x['level'], 'DR 1re active': str(x['first']),
                     'DR dégâts': str(x['damage']), 'DR garde': '' if x.get('block') is None else str(x['block']),
                     'DR réaction touche': x.get('hit_rx', ''), 'DR réaction contre': x.get('ch_rx', ''),
                     'statut': 'suite DR du pas de côté'}
                try: s.new(r['DR coup'], r, own_only=True)
                except (SystemExit, KeyError, ValueError): continue
                if d in s.dr2rec: done.append((mv['name'], s.dr2rec[d]))
        return done

    def no_ttt1(s):
        """No TTT1 attack left (NO_TTT1): an entry the fighter can take to a record hitting on its TTT1
        animation leads to DR's move of that command from the DR move its list plays (the parents()
        entries, unconditional), or goes; an end entry goes to the stance. A side step's end first gets
        its step's DR entries (Devil Twister on all of DR's 40 frames). Returns (redirected, removed)."""
        # A record a DR move plays is DR's (a new throw's attempt keeps the TTT1 grab it was copied from).
        mine = set(s.dr2rec.values())
        kept = set()
        if s.name in TTT1_THROWS_KEPT:
            # Every TTT1 record after a throw (TTT1's, or DR's tackle on TTT1's mount), up to the moves DR plays.
            after = lambda k: [e[3] - BASE_ID for e in s.pack.cancels(k) if BASE_ID <= e[3] < BASE_ID + len(s.pack.records)]
            throws = [k for k in range(len(s.pack.records)) if s.pack.word(k, 5) & 0xffff >= 16384]
            todo = [x for k in throws for x in ([k] if k not in mine else after(k))]
            while todo:
                k = todo.pop()
                if k in kept or k in mine or k == s.pack.neutral: continue
                kept.add(k)
                todo += after(k)
        ttt1 = lambda k: k not in mine and k not in kept and s.pack.word(k, 5) & 0xffff and s.pack.word(k, 0) in s.ttt1_clips
        rec2dr = {}
        for d, k in s.dr2rec.items(): rec2dr.setdefault(k, d)
        for k, d in s.pairs.items(): rec2dr.setdefault(k, d)
        for kt, (p, off) in s.step_tails.items():
            rec2dr[kt] = p
            head = s.dr2rec[p]
            entries = [list(e) for e in s.pack.cancels(kt)]
            have = {(e[0], e[1]) for e in entries}
            for e in s.pack.cancels(head):
                if e[0] == 0xc000 or e[1] or e[3] < BASE_ID or ttt1(e[3] - BASE_ID) or (e[0], e[1]) in have: continue
                at = next((i for i, x in enumerate(entries) if not x[1] and x[0] < 0x8000 and x[0] & 0xf == e[0] & 0xf),
                          next(i for i, x in enumerate(entries) if x[0] == 0xc000))
                x = list(e); x[5] = max(e[5] - off, 1); x[6] = e[6] if e[6] >= 255 else max(e[6] - off, 1)
                entries.insert(at, x); have.add((e[0], e[1]))
            s.pack.set_cancels(kt, [tuple(e) for e in entries])
        # DR's entries from each move, in DR's order: (its code, record).
        order = {}
        for q, dests in s._dests.items():
            for i, (l, d) in enumerate(dests): order.setdefault((q, d), i)
        by_parent = defaultdict(list)
        for d, ri in s.dr2rec.items():
            for q, label, *_ in s.parents(d):
                try: by_parent[q].append((order.get((q, d), 999), s.code_of(label), ri))
                except (ValueError, KeyError): pass
        for q in by_parent: by_parent[q].sort(key=lambda x: x[0])
        # DR's back-turned entries (BACK_TURNED) from each move: {(move, DR condition): [(code, record)]},
        # the stance's for a list no DR move stands for.
        back = defaultdict(list)
        for q in range(len(s.dr.m.moves)):
            for cmd, req, d in s.dr.m.cancels(s.dr.m.moves[q]['cancel']):
                if d not in s.dr2rec or not s.dr.m.usable(cmd) or not req: continue
                c = s.dr_conds(req)
                if len(c) != 1 or c[0] not in BACK_TURNED.values(): continue
                try: code = s.code_of(s.dr.m.label(cmd).replace(' ', ''))
                except (ValueError, KeyError): continue
                if (code, s.dr2rec[d]) not in back[(q, c[0])]: back[(q, c[0])].append((code, s.dr2rec[d]))
        dirs = lambda c: (c >> 5 & 0x1ff) or 0x1ff
        def back_codes(p, code, cond):
            """DR's back-turned moves for this command and condition from p (or the stance), split as dr_codes."""
            dc = BACK_TURNED[cond]
            got = back.get((p, dc)) or back.get((s.dr.m.stance, dc), [])
            out, left = [], dirs(code)
            for c, ri in got:
                if c >= 0x8000 or c & 0xf != code & 0xf or not dirs(c) & left: continue
                both = dirs(c) & left; left &= ~both
                out.append(((code & 0x1f) | (0 if both == 0x1ff and not code >> 5 else both << 5), ri))
            return out
        def dr_codes(p, code):
            """DR's moves for this command from p: a pack entry over several directions (d/b|d|d/f+2) is
            DR's move of each, on the directions both have."""
            if code >= 0x8000: return [(code, ri) for _, c, ri in by_parent.get(p, ()) if c == code]
            out, left = [], dirs(code)
            for _, c, ri in by_parent.get(p, ()):
                if c >= 0x8000 or c & 0x1f != code & 0x1f or not dirs(c) & left or ttt1(ri): continue
                both = dirs(c) & left; left &= ~both
                out.append(((code & 0x1f) | (0 if both == 0x1ff and not code >> 5 else both << 5), ri))
            return out
        redirected = removed = 0
        while True:
            seen, todo = {s.pack.neutral}, [s.pack.neutral]
            while todo:
                k = todo.pop()
                for e in s.pack.cancels(k):
                    t = e[3] - BASE_ID
                    if e[3] >= BASE_ID and t < len(s.pack.records) and t not in seen: seen.add(t); todo.append(t)
            changed = False
            for k in sorted(seen):
                out, touched = [], False
                for e in s.pack.cancels(k):
                    t = e[3] - BASE_ID
                    if e[3] < BASE_ID or t >= len(s.pack.records) or not ttt1(t):
                        out.append(e); continue
                    touched = True
                    if e[0] == 0xc000:
                        out.append((*e[:3], 3, *e[4:])); redirected += 1; continue
                    to = dr_codes(rec2dr.get(k), e[0]) if not e[1] else                         back_codes(rec2dr.get(k), e[0], e[1] >> 8) if s.name in BACK_TURNED_DR and e[1] >> 8 in BACK_TURNED                         and not e[1] & 0xff else []
                    for c, ri in to:
                        if not any(x[0] == c and not x[1] and x[3] == BASE_ID + ri for x in out):
                            out.append((c, *e[1:3], BASE_ID + ri, *e[4:])); redirected += 1
                    if not to: removed += 1
                if touched: s.pack.set_cancels(k, out); changed = True
            if not changed: break
        s.report['no_ttt1'] = dict(redirected=redirected, removed=removed)
        return redirected, removed

    def write(s, out, poses_idle):
        out.mkdir(parents=True, exist_ok=True)
        pushes = s.air_pushes()                         # into the tables before they are written
        data = s.pack.build()
        if len(data) > 16 * 1024 * 1024:
            # Past load_combat's bound: the old blobs set_cancels / set_clip left behind go (Jin, 2026-10-31).
            s.pack.compact(); data = s.pack.build()
        fault = validate(data)
        if fault: raise SystemExit(f'the runtime would refuse the pack: {fault}')
        wrong = s.wrong_ends()
        if wrong: raise SystemExit('attacks ending into another move than DR\'s (command, record, goes to, DR\'s): '
                                   + ', '.join(map(str, wrong)))
        (out / f'{s.Name}-DR-combat.jmv').write_bytes(data)
        (out / f'{s.Name}-DR-idle.poses').write_bytes(b''.join(struct.pack('<57H', *p) for p in poses_idle))
        (out / f'{s.Name}-DR-tables.jst').write_bytes(bytes(s.tables))
        if s.name in REACH: (out / f'{s.Name}-DR-reach.txt').write_text(f'{REACH[s.name]}\n')
        if s.name in HANDS: (out / f'{s.Name}-DR-hands.bin').write_bytes(s.hands_file(s.hands()))
        if pushes: (out / f'{s.Name}-DR-airpush.txt').write_text(''.join(f'{a} {c}\n' for a, c in sorted(pushes.items())))
        if s.air: (out / f'{s.Name}-DR-air.txt').write_text(''.join(f'{a} {r}\n' for a, r in sorted(s.air.items())))
        import dr_move_sounds as MS
        if MS.table(s.name):
            # F35: DR's cries (-voices.juv) and DR's swings, impacts and timed sounds added to TTT1's .jus.
            MS.build(s.name, out, s.pack_dir / f'{s.Name}-TTT1-sfx.jus')
        else:
            for tail in ('sfx.jus',):
                (out / f'{s.Name}-DR-{tail}').write_bytes((s.pack_dir / f'{s.Name}-TTT1-{tail}').read_bytes())
        # The pack record playing each DR move: the bench compares the moves both games played.
        s.report['dr2rec'] = {s.dr.m.moves[d]['name']: k for d, k in sorted(s.dr2rec.items())}
        (out / 'report.json').write_text(json.dumps(s.report, indent=1))


def build(name, out, moves=None, pack_dir=None):
    """<Name>-DR-* into out, from the TTT1 catalogue pack_dir (default: the main checkout's)."""
    b = Builder(name, pack_dir)
    idle = b.stance()
    kind = lambda r: r['statut'].split(' ')[0]
    # DR's move decides when DR has one: Devil Jin's d/f+1+2 (Hades Hammer, 21) is d+1+2 in Tekken 3 and
    # TTT1, a throw there.
    throw = lambda r: r['DR dégâts'] == 'prise' if r['DR coup'] else 'prise' in (r['T3 dégâts'], r['TTT1 dégâts'])
    chosen = [c for c in (moves or b.rows) if c in b.rows]
    common = [c for c in chosen if kind(b.rows[c]) in ('identique', 'modifié', 'commande') and not throw(b.rows[c])]
    new = sorted((c for c in chosen if kind(b.rows[c]) in ('nouveau', 'remplacé') and not throw(b.rows[c])), key=lambda c: c.count(', '))
    gone = [c for c in chosen if kind(b.rows[c]) == 'absent']
    left = []
    # A throw both games have; a new one goes to new_throw() even when the sheet's TTT1 column names the
    # move another command gives there (Jin's u/f+1+2 is u/f+1 in TTT1), and a throw DR lacks is absent.
    own_ttt1 = lambda r: r['TTT1 coup'] and 'TTT1 = ' not in r['notes']
    throws = [c for c in chosen if throw(b.rows[c]) and b.rows[c]['DR coup'] and own_ttt1(b.rows[c]) and kind(b.rows[c]) != 'absent']
    for cmd in common + new:
        if cmd == (new or [None])[0]:
            # The throws both games have, before the new moves: their attempts are then moves kept,
            # which a new move's entries do not take (Tetsuzan's d/b|d|d/f+1+2 took d/b+1+2).
            for tc in throws:
                b.throw(tc, b.rows[tc])
                print(f'{tc}: throw, records ' + ', '.join(f'{k}={n}' for k, n in b.report['moves'][tc]['throw_records']) + f', variants {b.report["moves"][tc]["variants"]}')
            # Movement first: a new move then also gets its entries in the walk, crouch... lists DR
            # puts it in (b+3 pressed while walking back played f+3 when only the stance had it).
            moves = b.movement()
            print(f'movement: {len(moves)} records on DR animations: ' + ', '.join(f'{k}={n}' for k, n, *_ in moves))
            for k, kt, n in b.side_steps(): print(f'side step: records {k} and {kt} on {n}')
            for k, p in b.pairs.items(): b.dr2rec.setdefault(p, k)
            st = b.stances()
            ch = b.charge_start()
            if ch: print(f'charge: start {ch[0]}, charge {ch[1]}')
            if st: print('stances: ' + ', '.join(f'{k}={n} ({f} frames, {h} entries)' for k, n, f, h in st))
        try:
            (b.common if cmd in common else b.new)(cmd, b.rows[cmd])
        except (SystemExit, KeyError, ValueError, StopIteration) as e:
            left.append((cmd, str(e))); continue
        m = b.report['moves'][cmd]
        print(f'{cmd}: {m["kind"]}, record {m["record"]}, DR {m["dr"]} -> {m["target"]}, stretch {m["stretch"]}'
              + (' (FLAGGED)' if m['flagged'] else '') + (f', bounds {m["bounds"]["notes"]}' if m.get('bounds', {}).get('notes') else '')
              + (f', {m["entries"]} entries ({m["entries_added"]} added)' if 'entries' in m else ''))
    if not new:
        for cmd in throws:
            b.throw(cmd, b.rows[cmd])
            print(f'{cmd}: throw, records ' + ', '.join(f'{k}={n}' for k, n in b.report['moves'][cmd]['throw_records']))
    for n, ri in b.hidden(): print(f'{n}: DR follow-up off the sheet, record {ri}')
    for n, ri in b.on_down(): print(f'{n}: DR follow-up on a fighter down, record {ri}')
    for n, ri in b.back_turned(): print(f'{n}: DR attack with the back turned, record {ri}')
    for n, ri in b.step_moves(): print(f'{n}: DR attack from the side step, record {ri}')
    lv = b.charge_levels()
    if lv: left = [(c, why) for c, why in left if c not in b.report['moves']]   # the first level, made there
    if lv: print(f'charge levels: records {lv}, {b.report["charge"]}')
    new_throws = [c for c in chosen if throw(b.rows[c]) and b.rows[c]['DR coup'] and not own_ttt1(b.rows[c]) and kind(b.rows[c]) != 'absent']
    for cmd in list(new_throws):
        try:
            b.new_throw(cmd, b.rows[cmd])
        except (SystemExit, KeyError, ValueError) as e:
            left.append((cmd, str(e))); new_throws.remove(cmd); continue
        mm = b.report['moves'][cmd]
        print(f'{cmd}: new throw, record {mm["record"]}, i{mm["first"]}, sides made {mm["sides_made"]}, {mm["entries"]} entries')
    throws += new_throws
    for ri, cond, k, dm in b.shared:
        # Now that the new throws made a record for DR's own side, the shared one is left.
        mine = next((kk for kk, d in b.whole_done.items() if d == dm), None)
        if mine is None: print(f'shared side kept: record {k} for {b.dr.m.moves[dm]["name"]}'); continue
        # The side without input only (0x10): a held-direction variant to that record stays (usiro).
        b.pack.set_cancels(ri, [(e[0], e[1], e[2], BASE_ID + mine, *e[4:]) if e[0] == 0x10 and e[1] == cond and e[3] == BASE_ID + k else e
                                for e in b.pack.cancels(ri)])
        print(f'shared side: record {ri} now leads to {mine} ({b.dr.m.moves[dm]["name"]}) instead of {k}')
    removed = sum(b.absent(c, b.rows[c]) for c in gone)
    if not new:
        moves = b.movement()
        print(f'movement: {len(moves)} records on DR animations: ' + ', '.join(f'{k}={n}' for k, n, *_ in moves))
        for k, kt, n in b.side_steps(): print(f'side step: records {k} and {kt} on {n}')
    print('parries: ' + ', '.join(f'{k}={n}' for k, n in b.parries()))
    df = b.deflects()
    if df: print('deflecting parries: ' + ', '.join(f'{k}={n}' for k, n in df))
    print(f'absent from DR: {len(gone)} moves, {removed} entries removed')
    rx = b.reactions()
    for k, v, dmg in b.throw_sides: b.throw_props(k, v, dmg)
    if name in DEEP_FOLLOWUPS: print(f"reactions turned on the floor: {b.reaction_ground_turns()}")
    if name in REORDER: print(f"throws' victims on DR's next move: {b.throw_ends()}")
    print(f"reactions: {rx['attacks']} attacks on DR's reactions, {rx['records']} records on DR animations "
          f"({len(rx['cloned'])} added), {rx['moves_changed']} moves with new rows")
    if 'half_turns' in b.report:
        h = b.report['half_turns']
        print(f"half-turns: ground records turned to Tekken 3's way {h['records']}, ends turning the fighter {h['transitions']}")
    for n, ri in b.states(): print(f'{n}: DR follow-up of its own motion, record {ri}')
    if name in REORDER: print(f"DR's order on {b.reorder()} entries Tekken 3 read as another move")
    if name in DEEP_FOLLOWUPS: print(f"DR's order within the windows: {b.window_order()} entries moved")
    if b.report.get('on_hit'): print(f"DR's follow-ups on a hit: {b.report['on_hit']}")
    if b.report.get('after_hits'): print(f"moves past them (record, DR's reactions): {b.report['after_hits']}")
    if b.report.get('recoveries'): print(f"DR's ends without a hit, and ends lying: {b.report['recoveries']}")
    if b.report.get('recovery_turns'): print(f"  turning the fighter into the lying record: {b.report['recovery_turns']}")
    if name in REORDER: print(f"DR's moves started over, not gone on with: {b.starts()}")
    if name in REORDER: print(f"hitting with DR's limb: {b.hit_limbs()}")
    if name in REORDER: print(f"tails blended towards the end's record: {b.tails()}")
    aw = b.air_windows()
    print(f"copied records on the ground in DR, model's air window cleared: {len(aw)}; "
          f"airborne in DR with other numbers, left: {len(b.report['air_windows_dr'])}")
    if name in REORDER: print(f"airborne reactions landing at DR's frame: {b.landings()}")
    if name in REORDER: print(f"DR's charges lighting the fists: {b.supercharges()}")
    if name in REORDER: print(f"DR's turns at the end of the whole animations: {b.end_turns()}")
    print(f"string follow-ups turning steadily to the victim: {len(b.string_turns())}")
    cer = b.ceremonies()
    if cer: print("round start and end on DR's animations: " + ', '.join(f'{a} {n} {r}' for a, n, r in cer))
    snd = b.ceremony_sounds()
    if snd: print("their sounds as DR's: " + ', '.join(f'{k} script {i} {[(f, hex(e)) for f, e in ev]}' for k, i, ev in snd))
    ms = b.move_sounds()
    if ms: print(f"DR's move sounds on {len(ms)} records, {b.report['move_sounds']['scripts']} timed scripts; "
                 f"left: {b.report['move_sounds']['left']}")
    fx = b.move_effects()
    if fx: print(f"DR's sparks and charge glow on {len(fx)} records: " + ', '.join(f'{k} {len(v)}' for k, v in fx.items()))
    lit = b.sparks()
    print(f"strong-hit effect: {len(lit)} attacks on DR's rule, {sum(f & 1 for f in lit.values())} lit on a hit, "
          f"{sum(f >> 1 & 1 for f in lit.values())} on a clean hit")
    if name in HEADING_TURNS: print(f"turned round with DR's heading: {b.heading_turns()}")
    if name in NO_TTT1: print("TTT1's attacks: %d entries to DR's move, %d removed" % b.no_ttt1())
    dt = b.deaths()
    print(f"DR's deaths on the knocked-out victim: records {dt['records']}, {len(dt['entries'])} entries: {dt['entries']}")
    uk = b.ukemi()
    print(f"ukemi at DR's frame: {len(uk)} reactions (record, TTT1's frame, DR's): {uk}")
    b.report['left'] = left
    for c, why in b.report['left']: print(f'not converted: {c}: {why}')
    b.write(out, idle)
    print(f'-> {out}')
    return b.report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('name', choices=('paul', 'jin', 'deviljin'))
    ap.add_argument('--moves', nargs='*', help='commands of the sheet (default: all of them)')
    ap.add_argument('--out', type=Path, default=X.WORK / 'roster')
    a = ap.parse_args()
    build(a.name, a.out, a.moves)


if __name__ == '__main__':
    main()
