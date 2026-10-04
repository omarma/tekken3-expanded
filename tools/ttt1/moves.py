"""Solo combat of a TTT1 character, converted for the Tekken 3 runtime.

convert() walks the character's move graph in the TTT1 RAM captured at the
selection screen and writes the two packs the runtime reads:
<Name>-TTT1-combat.jmv (records, clips, cancel lists, input sequences) and
<Name>-TTT1-tables.jst (reaction rows, pushback curves, contact groups,
event scripts, opponent-specific rules). Donor motion, input links, hit
damage, attacking bones and active frames are preserved; reactions use the
translated source tables. What has no solo meaning (tag inputs and partner
transitions, the TTT1 round controller, rules of other characters) is left
out and counted; anything else unsupported stops the conversion rather than
being treated as true.
"""
from pathlib import Path
import collections
import hashlib
import json
import struct
from motion import decode
import combat_semantics as solo

ROOT = Path(__file__).resolve().parents[2]
BASE_ID = 8192
NATIVE_EXE_SHA='fbda8b68e5799dbef4af39a161783bc670c15b0aa0e87dce65e210717da19b8c'
# Shared contact tests (2..23), distance, attack class, posture and reaction
# flags. TTT's inserted facing tests shift the later PS1 condition numbers.
CONDITIONS = {i:i for i in range(37)}
CONDITIONS.update({i:i-3 for i in range(40,72) if i!=50})
CONDITIONS.update({70:67,71:68})
CONDITIONS.update({i:i-0x1b for i in range(0x60,0x67)})
CONDITIONS.update({37:76,38:77,39:78})
CONDITIONS.update({i:79+(i-80)%4 for i in range(80,88)})


# Depth of the PS1 input history read by the sequence matcher 8002CA84.
INPUT_HISTORY = 60
# Contact group with no native counterpart (runtime: never matches a stock clip).
NO_NATIVE_GROUP = 0xffff
# Virtual limb 24 of TTT1 lasers -> runtime marker (src/tekken3_ttt1_pack.h TTT1_PACK_LASER_LIMB).
LASER_LIMB = 0x3f
# Unknown (TTT1 body 33): limbs 22 and 23 are points of her glowing blade,
# fixed in her hand bone 10 (runtime limb_position, TTT1_PACK_BLADE_*).
BLADE_BODY, BLADE_LIMBS = 33, {22: 0x3e, 23: 0x3d}
# TTT1 laser clip -> beam type (tools/data/ttt1_lasers.json, measured in MAME).
LASER_TYPES = {int(k, 16): v for k, v in json.loads((ROOT / 'tools/data/ttt1_lasers.json').read_text())['clips'].items()} \
    if (ROOT / 'tools/data/ttt1_lasers.json').exists() else {}
# Left out on purpose and counted in the report. The first five are
# structural (other characters' rules, tag inputs and partners, the TTT1 round
# controller). The others keep the conversion going for a semantics not
# identified yet: timed properties with no PS1 counterpart, an opponent-
# specific hit rule kept as the default row, a hit on a bone no mesh carries,
# an input sequence out of range (its cancel entry is dropped).
ALLOWED_EXCLUSIONS = {'other_character_rule', 'native_round_controller',
                      'solo_excluded_tag_input', 'solo_excluded_partner_transition',
                      'solo_excluded_partner_recovery', 'opponent_hit_rule_default',
                      'hit_limb_without_bone', 'input_sequence_out_of_range',
                      'input_sequence_window_clamped'}


STRUCTURAL = {'other_character_rule', 'native_round_controller', 'solo_excluded_tag_input',
              'solo_excluded_partner_transition', 'solo_excluded_partner_recovery'}


def allowed(kind):
    return kind in ALLOWED_EXCLUSIONS or kind.startswith('timed_property_')


def opponent_requirement(code):
    """Codes 0x43..0x63: the rule holds only against a given opponent.

    Same range as the opponent-specific hit rows (dynamic_hits). It also
    appears in cancel lists (six rules for Kazuya, none for Jun): legitimate
    solo conditions, not tag mechanics.
    """
    return code - 0x43 if 0x43 <= code < 0x64 else None


# Laser reactions (Devil / Angel): the record the defender plays when the
# beam hits (alias E23, shared by everyone) carries rules of other
# characters, the Jacks' (movesets 0x10 Gun Jack, 0x13 Jack-2, 0x14 P.Jack):
# at frame 30 they go haywire (E24..E26, the Windmill Punch, with their Clock
# Up / sliding answers). In the arcade the rule tests the fighter that plays
# the record, the defender: kept as this runtime condition (param = moveset,
# src/tekken3_ttt1_combat.c), its moves resolved with that character's
# alias table, read from its own selector capture.
SELF_MOVESET = 83


def moveset_requirement(code):
    """Codes 0x01..0x21: the rule holds for moveset code - 1."""
    return code - 1 if 1 <= code < 0x22 else None


def character_requirement(code, moveset, body):
    """Whether a rule applies to this character (its keys at 0x29EF00), or
    None when it depends on something else."""
    if code in (0,0xed):return True
    if code==0xec:return False
    if 1<=code<0x22:return code-1==moveset
    if 0x22<=code<0x43:return code-0x22!=moveset
    if 0x85<=code<0xa7:return code-0x85==body
    if 0xc9<=code<0xeb:return code-0xc9!=body
    return None


def cancel_rows(ram,pointer,stack=()):
    if pointer in stack or len(stack)>8:raise ValueError('Recursive cancel list')
    for k in range(1024):
        row=struct.unpack_from('<7H',ram,(pointer&0x3fffff)+k*14)
        if row[0]==0x800e:return
        if row[0]==0x800d:
            yield from cancel_rows(ram,0x801b3740+row[3]*14,stack+(pointer,))
            continue
        yield row
        if row[0]==0x8000:return
    raise ValueError('Unterminated cancel list')


def hit_data(ram,index,requirement):
    """Resolve the character's normal hit row as the arcade's 801012D4 does.

    Record +0x14 indexes ten-byte hit rows at 800EC8BC. Record +0x28
    contains four limb IDs, not damage. Opponent-specific rows are exported
    separately and resolved against the actual opponent by the adapter.
    """
    dynamic=False
    for i in range(128):
        row=struct.unpack_from('<5H',ram,0xec8bc+(index+i)*10)
        req=requirement(row[0])
        if row[0]==0xffff or req is True:return row,dynamic
        if req is None:dynamic=True
    raise ValueError('Unterminated arcade hit-data list')


def hit_rows(ram,index):
    rows=[]
    for k in range(128):
        row=struct.unpack_from('<5H',ram,0xec8bc+(index+k)*10)
        rows.append(row)
        if row[0]==0xffff:return rows
    raise ValueError('Unterminated arcade hit-data list')


def convert(ram, bank, records, moveset, body, limb_map, native_exe=None, graft=None, aliases_of=None):
    """Returns (combat pack, tables pack, report).

    ram: 4 MiB TTT1 RAM with the character highlighted at the selector;
    bank: the verified TTT1 banked ROMs; records: the character's own move
    records (motion.export); moveset, body: its keys at 0x29EF00; limb_map:
    TTT1 accessory bone -> PS1 bone, from the converted model.

    graft: moves of another character added to this one (Devil Jin: Jin with
    Devil's moves). Every character's move records stay resident in TTT1 RAM;
    only the alias table (and the keys the rules test) differ. A dict with
    aliases (the donor's 5515 alias words, from its own selector capture),
    moveset and body (its keys), roots (donor record addresses to add) and
    links ((host record, donor record) pairs: the donor record's cancel
    entries that lead into the grafted records are added to the host
    record, ahead of its own so that the donor's version of an input wins;
    a third item True also copies the donor's links back to its own slot).
    Grafted records are converted with the donor's aliases and keys; a
    record the host already has stays the host's.

    aliases_of: moveset key -> that character's 5515 alias words (or None),
    for the rules of other characters kept on the laser reactions
    (SELF_MOVESET)."""
    if native_exe is None:native_exe=(ROOT/'disc/SLUS_004.02').read_bytes()
    if hashlib.sha256(native_exe).hexdigest()!=NATIVE_EXE_SHA:
        raise ValueError('disc/SLUS_004.02 is not the Tekken 3 USA executable')
    native_exe=native_exe[0x800:]
    host_requirement=lambda code:character_requirement(code,moveset,body)
    requirement=host_requirement
    solo.TRUNCATED_EVENTS.clear()
    solo.SFX_INDEXES.clear()
    aliases = host_aliases = struct.unpack_from('<5515I', ram, 0x2a7350)
    addresses = {x['address'] for x in records}
    # Common locomotion supplies crouching, walking and turning for the donor.
    addresses.update(a for a in aliases[56:344] if a != 0x8009374c)
    native_aliases=solo.native_aliases()
    native_aliases={k:v for k,v in native_aliases.items() if aliases[v]!=0x8009374c}
    addresses.update(aliases[v] for v in native_aliases.values())
    # Follow the character's actual graph, including moves shared with others. A diff of
    # their alias tables alone omits shared recovery and attack destinations.
    def walk(pending, addresses, aliases, requirement, stop=frozenset()):
        while pending:
          v=struct.unpack_from('<13I',ram,pending.pop()&0x3fffff)
          targets=[v[4]&65535]
          for cmd,req,param,nxt,kind,window,end in cancel_rows(ram,v[3]):
              # A rule conditioned on the opponent is still the character's:
              # its destination must join the graph, or cancels() keeps it
              # without being able to resolve it.
              owned=requirement(req&255) is True or opponent_requirement(req&255) is not None
              if cmd==0x8000 or (owned and not (cmd<0x8000 and cmd&0x4000) and
                  (req>>8)&127 in CONDITIONS and solo.transition(kind) is not None and not kind&0x3f80):
                  targets.append(nxt)
          for hit in hit_rows(ram,v[5]&65535):
              for reaction_id in (hit[2],hit[3]):
                  if reaction_id:targets.extend(solo.reaction(ram,reaction_id)[7:])
          for target_alias in targets:
              if 0<=target_alias<len(aliases):
                  address=aliases[target_alias]
                  if address not in addresses and address not in stop:
                      addresses.add(address);pending.append(address)
    walk(list(addresses), addresses, host_aliases, host_requirement)
    grafted=set()
    self_context={}
    self_rules=[0]
    if graft:
        # A donor alias whose slot the host fills with its own move (stance,
        # crouch, walks, recoveries) resolves to the host's: grafted moves
        # come back to the host's stance, not into the donor's whole graph.
        graft_aliases=tuple(h if h in addresses and h!=0x8009374c and d not in graft['roots'] else d
                            for h,d in zip(host_aliases,graft['aliases']))
        graft_requirement=lambda code:character_requirement(code,graft['moveset'],graft['body'])
        roots={a for a in graft['roots'] if a not in addresses}
        grafted|=roots
        # A record the host already has is the host's: the walk stops there.
        walk(list(roots), grafted, graft_aliases, graft_requirement, frozenset(addresses))
        addresses|=grafted
    # The reactions of the host's lasers (limb 24), and the moves of the
    # characters their rules name (SELF_MOVESET), walked as a graft is.
    laser_victims=set()
    for a in list(addresses):
        v=struct.unpack_from('<13I',ram,a&0x3fffff)
        if 24 in struct.pack('<I',v[10]):
            for hit in hit_rows(ram,v[5]&65535):
                for reaction_id in (hit[2],hit[3]):
                    if reaction_id:laser_victims.update(host_aliases[t] for t in solo.reaction(ram,reaction_id)[7:]
                                                        if 0<=t<len(host_aliases))
    laser_victims&=addresses
    self_aliases={}
    for a in sorted(laser_victims):
        for cmd,req,param,nxt,kind,window,end in cancel_rows(ram,struct.unpack_from('<13I',ram,a&0x3fffff)[3]):
            m=moveset_requirement(req&255)
            if cmd==0x8000 or m is None or m==moveset or not aliases_of:continue
            if m not in self_aliases:
                other=aliases_of(m)
                if other is None:continue
                # As for a graft: an alias the host fills (stance, its own
                # reactions when the Windmill Punch hits it) stays the host's;
                # only those it leaves on the empty record take the other's.
                self_aliases[m]=tuple(h if h in addresses and h!=0x8009374c else d for h,d in zip(host_aliases,other))
            other=self_aliases[m]
            if not 0<=nxt<len(other) or other[nxt]==0x8009374c:continue
            self_set=set()
            other_requirement=lambda code,m=m:character_requirement(code,m,None)
            if other[nxt] not in addresses:
                self_set.add(other[nxt])
                walk([other[nxt]],self_set,other,other_requirement,frozenset(addresses))
            for r in self_set:self_context.setdefault(r,(other,other_requirement))
    addresses|=set(self_context)
    def context(address):
        if address in self_context:return self_context[address]
        return (graft_aliases,graft_requirement) if address in grafted else (host_aliases,host_requirement)
    # TTT1 aliases with no Tekken 3 entry, played on a juggled victim by the
    # arcade (solo.JUGGLE_ALIASES). Appended after the others: the number of
    # every other record stays what it was (combos, move lists, batteries).
    extra={aliases[a] for a in solo.JUGGLE_ALIASES if aliases[a]!=0x8009374c}-addresses
    base=set(addresses)
    walk(list(extra),extra,host_aliases,host_requirement,frozenset(base))
    addresses = sorted(base)+sorted(extra-base)
    indices = {a:i for i,a in enumerate(addresses)}
    raw = [struct.unpack_from('<13I', ram, a & 0x3fffff) for a in addresses]
    skipped = collections.Counter()
    # Where each omission lies (record address), for kinds that are not structural.
    omitted_at = collections.defaultdict(list)
    current = [0]
    def lose(kind, detail=None):
        skipped[kind] += 1
        if kind not in STRUCTURAL:omitted_at[kind].append((current[0], detail))
    omitted_conditions = collections.Counter()
    opponent_rules = []
    patterns = {}
    groups=solo.motion_groups(ram)
    event_scripts={}
    rx_ids=sorted({idx for v in raw for row in hit_rows(ram,v[5]&65535) for idx in row[2:4]})
    dynamic_hits=[]
    distance_hits=[]
    # The native reaction table contains 633 records. Preserve stock fighters;
    # append the character's source-derived rows and original pushback curves.
    rx_map={idx:633+i for i,idx in enumerate(rx_ids)}
    rx_blob=bytearray(native_exe[0xce8:0xce8+633*42])
    push_blob=bytearray(native_exe[0x75c:0xce8])
    push_offsets={}
    counter_blob=bytearray(native_exe[0x77dc:0x7c10])
    # Matching condition handlers were compared in the two executables.
    conditions=CONDITIONS

    def input_pattern(cmd):
        if cmd not in patterns:
            start=0x772+cmd*2
            words=[]
            for k in range(65):
                value=struct.unpack_from('<H',ram,start+k*2)[0]
                words.append(value)
                if k and not value:break
            else:raise ValueError('Unterminated input sequence')
            if not words[0] or len(words)<3:
                return None      # the cancel entry is dropped (counted)
            if words[0]>INPUT_HISTORY:
                # T3 keeps 60 input entries (circular, 8002CA84); TTT1 allows
                # longer windows (Armor King's chain throws: 94 and 114). The
                # sequence stays playable within the last 60, and counted.
                words[0]=INPUT_HISTORY;lose('input_sequence_window_clamped',f'{cmd:04x}')
            patterns[cmd]=(0xe000+len(patterns),words)
        return patterns[cmd][0]

    # The record being converted decides the alias table and keys in use.
    aliases, requirement = host_aliases, host_requirement
    def target(alias):
        if alias == 56: return 3
        if 0 <= alias < len(aliases) and aliases[alias] in indices:
            return BASE_ID + indices[aliases[alias]]
        return None

    def required_target(alias):
        resolved=target(alias)
        if resolved is None:
            raise ValueError(f'Unconverted solo animation destination {alias:04x}')
        return resolved

    def cancels(pointer):
        emitted = 0
        for cmd,req,param,nxt,kind,window,end in cancel_rows(ram,pointer):
            dest = target(nxt)
            if cmd == 0x8000:
                # End-of-animation links also carry a transition and facing
                # flags. Forcing type 6 loses the half-turn on back-facing
                # recovery (for example alias C1 -> C2 uses source 800B).
                transition = solo.transition(kind)
                if transition is None or kind & 0x1f80:
                    raise ValueError(f'Unconverted recovery transition {kind:04x}')
                # Source bit 13 requests a partner swap at 800FF424. Solo
                # recovery keeps the actor and the base facing transition.
                if kind & 0x2000:skipped['solo_excluded_partner_recovery']+=1
                yield struct.pack('<4H4B',0xc000,0,0,required_target(nxt),transition,window>>8,end&255,end>>8)
                emitted += 1
                return
            owner=requirement(req&255)
            opponent=opponent_requirement(req&255)
            if owner is None and opponent is not None:
                # The rule is the character's own; it is the opponent it
                # depends on. Kept, with the condition exported apart (DYNC).
                owner=True
            m=moveset_requirement(req&255)
            if owner is False and current[0] in laser_victims and m in self_aliases:
                # Another character's rule on a laser reaction: the defender's.
                other=self_aliases[m]
                dest=BASE_ID+indices[other[nxt]] if 0<=nxt<len(other) and other[nxt] in indices else None
                transition=solo.transition(kind)
                if (req>>8)&127 or cmd>=0x8000 or cmd&0x4000 or dest is None or transition is None or kind&0x3f80:
                    raise ValueError(f'Unconverted laser reaction rule {req:04x} -> {nxt:04x}')
                self_rules[0]+=1
                yield struct.pack('<4H4B',cmd,SELF_MOVESET<<8,m,dest,transition,window>>8,end&255,end>>8)
                emitted += 1
                continue
            if owner is False:
                skipped['other_character_rule']+=1;continue
            if cmd<0x8000 and cmd&0x4000:
                skipped['solo_excluded_tag_input']+=1;continue
            if 0x64<=req&255<0x85 or 0xa7<=req&255<0xc9 or kind&0x3f80 or (req>>8)&127 in (88,89,90,91,92):
                skipped['solo_excluded_partner_transition']+=1;continue
            if (req>>8)&127==95:
                # TTT's round-defeat signal; the PS1 round controller enters
                # native D6C/D6D, mapped to the character's defeat motions.
                skipped['native_round_controller']+=1;continue
            # Bit 7 gates the opponent's tag state (800FE1B8..800FE238).
            # With no tag partner in PS1 combat that gate permits the normal
            # low-seven-bit condition; it is not a new condition number.
            condition=conditions.get((req>>8)&127)
            if owner is None or condition is None:
                omitted_conditions[f'{req:04x}']+=1
                skipped['conditional_requirement'] += 1; continue
            if dest is None:
                skipped['unmapped_destination'] += 1; continue
            transition = solo.transition(kind)
            if transition is None or kind & 0x3f80:
                skipped['transition_type'] += 1; continue
            if cmd in (0x8001,0x8002):cmd+=0x4000
            elif cmd>=0x800f:
                cmd=input_pattern(cmd)
                if cmd is None:lose('input_sequence_out_of_range',f'{nxt:04x}');continue
            elif cmd>=0x8000 or cmd&0x4000:
                skipped['special_input']+=1;continue
            if condition==74:
                param|=0x8000  # Source alias checked by the contact bridge.
            elif condition==75:
                if param not in groups:
                    # TTT-only group (Jack-2 / P. Jack: 52nd list). No native
                    # group matches it; only a guest clip can satisfy it.
                    clips=solo.group_at(ram,param)
                    if clips is None:raise ValueError(f'Unknown contact group {param:x}')
                    groups[param]=(NO_NATIVE_GROUP,clips)
                param|=0x4000
            # Bit 15/14 became bit 7/6 in the PS1 transition byte.
            if opponent is not None:
                opponent_rules.append((i,emitted,opponent))
            yield struct.pack('<4H4B',cmd,condition<<8,param,dest,transition,window>>8,end&255,end>>8)
            emitted += 1

    # Header, metadata records (16 bytes), native records (56 bytes).
    blob = bytearray(32+len(raw)*72)
    relocs=[]
    pose_offsets={}
    def append(data):
        blob.extend(b'\0'*(-len(blob)%4)); offset=len(blob);blob.extend(data);return offset
    for i,v in enumerate(raw):
        source=v[0];current[0]=addresses[i]
        aliases,requirement=context(addresses[i])
        if source not in pose_offsets:
            count=bank[source]
            data=struct.pack('<II',0x4a554e00|count,57)
            data+=b''.join(struct.pack('<57H',*decode(bank,source,f)) for f in range(count))
            pose_offsets[source]=append(data)
        converted=list(cancels(v[3]))
        for host,donor,*own in (graft or {}).get('links',()):
            if host!=addresses[i]:continue
            # The donor record's entries into the grafted moves, with the
            # donor's aliases and keys, ahead of the host's recovery; and its
            # links back to its own slot (the early-press buffer of the
            # follow-up), which the host fills with its own move.
            aliases,requirement=graft_aliases,graft_requirement
            before=len(opponent_rules)
            # Only the entries into the grafted moves are kept: what the
            # donor's others would count (moves not grafted) is not a loss.
            counted=skipped.copy()
            keep={indices[a] for a in grafted}|({i} if own and own[0] else set())
            extra=[e for e in cancels(struct.unpack_from('<13I',ram,donor&0x3fffff)[3])
                   if struct.unpack_from('<H',e)[0]!=0xc000 and
                   struct.unpack_from('<H',e,6)[0]-BASE_ID in keep]
            skipped.clear();skipped.update(counted)
            aliases,requirement=context(addresses[i])
            if not extra:raise ValueError(f'Graft link {donor:08x} -> {host:08x} leads to no grafted move')
            converted[0:0]=extra
            # Opponent-specific rules name their entry by position: the
            # host's move down by the entries put ahead. The donor's would
            # be numbered among entries filtered out: refused.
            host_rows=[r for r in opponent_rules[:before] if r[0]==i]
            opponent_rules[:before]=[r for r in opponent_rules[:before] if r[0]!=i]+[(r[0],r[1]+len(extra),r[2]) for r in host_rows]
            if len(opponent_rules)>before:
                raise ValueError(f'Graft link {donor:08x}: opponent-specific rules not supported')
        # A nested group can end without the parent sentinel.
        if not converted or struct.unpack_from('<H',converted[-1])[0]!=0xc000:
            converted.append(struct.pack('<4H4B',0xc000,0,0,required_target(v[4]&65535),6,0,0,0))
        # Flattened subroutines return at 800e; only the outer list terminates.
        cp=append(b''.join(converted))
        hit,dynamic_hit=hit_data(ram,v[5]&65535,requirement)
        damage=hit[1]
        if hit[4]:distance_hits.append((i,hit[4],rx_map[hit[3]],rx_map[hit[2]]))
        if dynamic_hit:
            variants=hit_rows(ram,v[5]&65535)
            if any(not 0x43<=row[0]<0x64 or row[1:]!=variants[0][1:] for row in variants[:-1]) or any(
                variants[0][k]!=hit[k] for k in (3,4)):
                # Untranslated: keep the default hit row against everyone.
                lose('opponent_hit_rule_default')
            else:
                mask=sum(1<<(row[0]-0x43) for row in variants[:-1])
                # High halfwords: damage + 1 against those opponents / the
                # others, when it differs (Roger, Baek, Bruce: 19 vs 20).
                alt,normal=rx_map[variants[0][2]],rx_map[hit[2]]
                if variants[0][1]!=hit[1]:
                    alt|=(variants[0][1]+1)<<16;normal|=(hit[1]+1)<<16
                dynamic_hits.append((i,mask,alt,normal))
        t=[0]*14
        t[0]=pose_offsets[source];t[1]=v[1];t[2]=v[2];t[3]=cp
        # Both engines add the high halfword to facing at recovery.
        t[4]=(v[4]&0xffff0000)|required_target(v[4]&65535)
        # Only the low halfword becomes damage. The signed high halfword is the
        # horizontal speed of the airborne window (T3 8003F3E8): dropping it
        # turns forward and back jumps into vertical ones.
        t[5]=(v[5]&0xffff0000)|damage
        t[6]=(v[6]&0xffffff00)|bank[source]
        sounds,animation_events=solo.sound_events(ram,v[7])
        for event in animation_events:
            if event:event_scripts[1024+event]=solo.event_script(ram,event)
        t[7]=append(struct.pack(f'<{len(sounds)+1}H',*sounds,0xffff))
        props,omitted_props=solo.properties(ram,v[8])
        t[8]=append(b''.join(struct.pack('<HH',*p) for p in props)+b'\0'*4)
        for frame,kind,arg in omitted_props:lose(f'timed_property_{kind:02x}',f'frame {frame} arg {arg}')
        t[9]=solo.flags(v[9])
        # v3 packs store these IDs directly; the runtime allocates the native
        # descriptor and evaluates the sweep from the animated skeleton.
        # Limb IDs are bone indices. 0..17 are shared with the PS1 skeleton;
        # 18+ are TTT1 accessory bones (Kunimitsu: 22), renumbered to the PS1
        # bone of the part that holds them (limb_map, from the model layout).
        limbs=bytearray(struct.pack('<I',v[10]));limbs_src=bytes(limbs)
        for k in range(4):
            if limbs[k]>=18:
                if limbs[k]==24:                      # TTT1 laser tip (Devil/Angel), runtime beam
                    limbs[k]=LASER_LIMB
                    solo.SFX_INDEXES.add(solo.LASER_SOUND)   # its sound, played by the runtime
                    if k==0:limbs[1]=LASER_TYPES.get(source,1)   # second byte: beam type
                elif limbs[k] in limb_map:limbs[k]=limb_map[limbs[k]]
                elif body==BLADE_BODY and limbs[k] in BLADE_LIMBS:limbs[k]=BLADE_LIMBS[limbs[k]]
                else:
                    # No mesh carries that bone (Kunimitsu 22): sweep the other
                    # limb from its previous position, and count it.
                    limbs[k]=0;lose('hit_limb_without_bone',limbs_src[k])
        t[10]=struct.unpack('<I',limbs)[0]
        t[11]=((v[11]&0xffff)<<8)|((v[11]>>16)&255)
        t[12]=(v[12]&65535)|(rx_map[hit[2]]<<16)
        t[13]=len(counter_blob)//4
        # TTT 800FB378..800FB3D0 uses hit[3] only inside hit[4] distance.
        # The native distance table has the same (reaction, threshold) pair.
        # Both its selector and its range-test base must be relocated.
        counter_blob.extend(struct.pack('<HH',rx_map[hit[3]] if hit[4] else rx_map[hit[2]],hit[4]))
        rp=32+len(raw)*16+i*56
        struct.pack_into('<14I',blob,rp,*t)
        relocs.extend((rp,rp+12,rp+28,rp+32))
        struct.pack_into('<4I',blob,32+i*16,source,addresses[i],rp,len(converted))
    reloc_offset=append(struct.pack(f'<{len(relocs)}I',*relocs))
    sequence_data=struct.pack('<I',len(patterns))
    for command,words in patterns.values():
        sequence_data+=struct.pack('<HH',command,len(words))+struct.pack(f'<{len(words)}H',*words)
    blob.extend(sequence_data)
    aliases,requirement=host_aliases,host_requirement
    neutral=indices[aliases[56]]
    struct.pack_into('<8I',blob,0,0x314d554a,4,len(blob),len(raw),neutral,reloc_offset,len(relocs),32+len(raw)*16)
    host_rx={idx for a,v in zip(addresses,raw) if a not in grafted for row in hit_rows(ram,v[5]&65535) for idx in row[2:4]}
    for idx in rx_ids:
        aliases=host_aliases if idx in host_rx else graft_aliases
        r=solo.reaction(ram,idx)
        fields=[]
        for k,value in enumerate(r[:7]):
            if k in (1,3,5,6) and value:
                if value not in push_offsets:
                    push_offsets[value]=len(push_blob)//2
                    push_blob.extend(ram[value&0x3fffff:(value&0x3fffff)+20])
                value=push_offsets[value]
            fields.append(value&65535)
        rx_blob.extend(struct.pack('<21H',*(required_target(a) for a in r[7:]),*fields))
    tables=bytearray(32)+rx_blob+push_blob+counter_blob
    def chunk(name,payload):
        tables.extend(name+struct.pack('<I',len(payload))+payload)
    aliases=host_aliases
    chunk(b'ALIA',b''.join(struct.pack('<HH',native,target(source)) for native,source in sorted(native_aliases.items())))
    chunk(b'SRCA',struct.pack('<5515I',*aliases))
    chunk(b'GRUP',b''.join(struct.pack('<HHI',source,native,len(clips))+struct.pack(f'<{len(clips)}I',*clips)
                         for source,(native,clips) in sorted(groups.items())))
    chunk(b'EVNT',b''.join(struct.pack('<II',i,len(events))+struct.pack(f'<{len(events)}I',*events)
                         for i,events in sorted(event_scripts.items())))
    chunk(b'DYNH',b''.join(struct.pack('<4I',*row) for row in dynamic_hits))
    # Only when there are some, so packs without such rules keep their layout.
    if opponent_rules:
        chunk(b'DYNC',b''.join(struct.pack('<HHI',*row) for row in opponent_rules))
    # The laser reaction moves of the characters SELF_MOVESET names: played
    # by the defender from this pack, their rules are the defender's.
    if self_context:
        chunk(b'DEFR',b''.join(struct.pack('<H',indices[a]) for a in sorted(self_context)))
    struct.pack_into('<8I',tables,0,0x3154534a,2,len(tables),len(rx_blob)//42,len(push_blob),len(counter_blob)//4,0,0)
    unresolved={kind:n for kind,n in skipped.items() if not allowed(kind)}
    if unresolved or omitted_conditions:
        raise ValueError(f'Incomplete solo conversion: {unresolved}, conditions {dict(omitted_conditions)}')
    report=dict(records=len(raw),clips=len(pose_offsets),cancel_entries=sum(struct.unpack_from('<I',blob,32+i*16+12)[0] for i in range(len(raw))),
                input_sequences=len(patterns),omitted_rules=dict(skipped),omitted_conditions=dict(omitted_conditions.most_common()),
                omitted_at={k:[(f'{a:08x}',d) for a,d in v] for k,v in omitted_at.items()},sha256=hashlib.sha256(blob).hexdigest(),
                status='Solo source graph converted',
                grafted_records=len(grafted),
                animation_event_scripts=len(event_scripts),opponent_specific_hit_records=len(dynamic_hits),
                opponent_specific_cancel_rules=len(opponent_rules),
                defender_specific_cancel_rules=self_rules[0],laser_reaction_moves=len(self_context),
                distance_specific_hit_records=len(distance_hits),
                native_entry_points=len(native_aliases),native_fallback_templates=[],
                source_default_reaction='8009374c' if 0x8009374c in indices else None,
                truncated_event_scripts=dict(solo.TRUNCATED_EVENTS),
                sound_indexes=sorted(solo.SFX_INDEXES | set(solo.ENGINE_SOUNDS)),
                limits=['Native fight camera replaces TTT1 camera scripts',
                        'Accessories keep a rigid attachment, without secondary physics'])
    return bytes(blob),bytes(tables),report
