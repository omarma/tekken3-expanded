"""TTT1 combat conversion checks. The first class is synthetic; the second
reads Jun's pack converted from the user's ROM (tools/ttt1_import.py jun) and
checks semantics, not unique move counts."""
import struct
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/ttt1'))
from moves import CONDITIONS,character_requirement
import combat_semantics as solo
from tools.build_ttt1_combat_hooks import generate_push

PACK=ROOT/'workspace/ttt1-import/jun/guest/Jun-TTT1-combat.jmv'
JUN_MOVESET,JUN_BODY=28,30

class ConditionMappingTests(unittest.TestCase):
    def test_source_only_transitions_keep_rotation_and_flags(self):
        self.assertEqual(solo.transition(0x21),45)
        self.assertEqual(solo.transition(0x22),46)
        self.assertEqual(solo.transition(0x8023),0x80|47)
        self.assertEqual(solo.transition(0x20),33)
        self.assertEqual(solo.transition(0x24),34)
        self.assertEqual(solo.transition(0x2e),44)
    def test_root_flags_do_not_become_attack_or_invulnerability_flags(self):
        self.assertEqual(solo.flags(0x580000),0x70000000)
        self.assertEqual(solo.flags(0x180001),0x30000100)
        self.assertEqual(solo.flags(0x480000),0x50000000)
    def test_jun_is_not_the_heihachi_kazuya_special_team(self):
        self.assertTrue(character_requirement(0xed,JUN_MOVESET,JUN_BODY))
        self.assertFalse(character_requirement(0xec,JUN_MOVESET,JUN_BODY))
        self.assertIsNone(character_requirement(0xeb,JUN_MOVESET,JUN_BODY))
    def test_rules_follow_the_character_keys(self):
        self.assertTrue(character_requirement(1+JUN_MOVESET,JUN_MOVESET,JUN_BODY))
        self.assertFalse(character_requirement(1+18,JUN_MOVESET,JUN_BODY))      # Kazuya's moveset
        self.assertTrue(character_requirement(0x85+JUN_BODY,JUN_MOVESET,JUN_BODY))
    def test_inserted_facing_tests_do_not_shift_posture_conditions(self):
        self.assertEqual(CONDITIONS[42],39)
        self.assertEqual(CONDITIONS[56],53)
        self.assertEqual(CONDITIONS[70],67)
        for tag_condition in (0x80,0xd4,0x58,0x5c):
            self.assertNotIn(tag_condition,CONDITIONS)

@unittest.skipUnless(PACK.is_file(),'requires Jun imported from the TTT1 ROM')
class JunExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=PACK.read_bytes()
        cls.h=struct.unpack_from('<8I',cls.p)
        cls.records={}
        for i in range(cls.h[3]):
            source,template,rp,n=struct.unpack_from('<4I',cls.p,32+i*16)
            cls.records.setdefault(source,[]).append((i,struct.unpack_from('<14I',cls.p,rp),n))

    def test_original_jab_damage_and_active_window(self):
        # Damage comes from ten-byte hit rows (800EC8BC), independently of
        # the limb IDs at record +0x28. The old adapter conflated them.
        for source,damage,start,end,frames in ((0x1a20b4,4,10,10,46),(0x1aac64,15,14,16,47),
                                             (0x1b96d0,7,18,18,62),(0x1c0fe8,20,10,10,44)):
            _,r,_=self.records[source][0]
            self.assertEqual(r[5]&65535,damage)
            self.assertEqual((r[11]>>8)&65535,start|(end<<8))
            self.assertEqual(r[6]&255,frames)
            self.assertEqual(self.p[r[0]],frames)

    def test_original_attacking_limbs_are_separate_from_damage(self):
        self.assertEqual(self.h[1],4)
        for source,limbs in ((0x1a20b4,0x0a),(0x1aac64,0x06),(0x1b96d0,0x11),(0x1c0fe8,0x0d0e000e)):
            self.assertEqual(self.records[source][0][1][10],limbs)

    def test_neutral_commands_reach_four_original_attacks(self):
        rp=self.h[7]+self.h[4]*56
        cp=struct.unpack_from('<I',self.p,rp+12)[0]
        n=struct.unpack_from('<I',self.p,32+self.h[4]*16+12)[0]
        targets=set()
        for k in range(n):
            target=struct.unpack_from('<H',self.p,cp+k*12+6)[0]
            if target>=8192:targets.add(struct.unpack_from('<I',self.p,32+(target-8192)*16)[0])
        self.assertTrue({0x1a20b4,0x1aac64,0x1b96d0,0x1c0fe8}<=targets)

    def test_all_next_moves_and_cancels_stay_in_export(self):
        valid=lambda x:x==3 or 8192<=x<8192+self.h[3]
        for values in self.records.values():
            for _,r,n in values:
                self.assertTrue(valid(r[4]&65535))
                self.assertEqual(struct.unpack_from('<H',self.p,r[3]+(n-1)*12)[0],0xc000)
                for k in range(n):
                    self.assertTrue(valid(struct.unpack_from('<H',self.p,r[3]+k*12+6)[0]))

    def test_recovery_keeps_the_arcade_facing_delta(self):
        # This donor move turns by half a revolution when it recovers.
        self.assertTrue(self.records[0x27b098])
        for _,record,_ in self.records[0x27b098]:
            self.assertEqual(record[4]>>16,0x7fff)

    def test_back_facing_recovery_commits_the_turn(self):
        # C1 turns the visible pose; its terminal 800B link commits a half
        # turn to gameplay facing before C2 returns to ordinary stance.
        for clip,kind,start in ((0x13e84c,0x8b,0),(0x13eaec,0x0b,7)):
            for _,record,n in self.records[clip]:
                row=struct.unpack_from('<4H4B',self.p,record[3]+(n-1)*12)
                self.assertEqual(row[0],0xc000)
                self.assertEqual(row[4:6],(kind,start))

    def test_hit_confirm_followup_uses_the_source_rotation_transition(self):
        rows=[struct.unpack_from('<4H4B',self.p,r[3]+i*12) for _,r,n in self.records[0x511148] for i in range(n)]
        self.assertTrue(any(row[4]==46 and struct.unpack_from('<I',self.p,32+(row[3]-8192)*16)[0]==0x511ea4 for row in rows))

    def test_both_solo_victories_and_timed_voices_are_present(self):
        for clip,script in ((0xae32dc,511),(0xae4b08,512)):
            _,r,_=self.records[clip][0]
            self.assertEqual(struct.unpack_from('<H',self.p,r[7])[0],0x8000|1024+script)

    def test_character_confirmation_keeps_its_expression_timing(self):
        _,r,_=self.records[0x9d2764][0]
        self.assertEqual(struct.unpack_from('<HH',self.p,r[8]+4),(15,0x4041))

    def test_original_throw_damage_is_timed_on_the_paired_animation(self):
        for clip,frame in ((0x757e64,145),(0x78ea44,90)):
            _,r,_=self.records[clip][0]
            props=[];at=r[8]
            while struct.unpack_from('<H',self.p,at)[0]:props.append(struct.unpack_from('<HH',self.p,at));at+=4
            self.assertIn((frame,0x0b00),props)
            self.assertEqual(r[5],30)

    def test_distance_reaction_is_not_a_counter_hit_index(self):
        t=PACK.with_name('Jun-TTT1-tables.jst').read_bytes()
        _,_,_,nr,np,nc,_,_=struct.unpack_from('<8I',t)
        at=32+nr*42+np
        # At close range the original get-up kick selects reaction 402;
        # outside 1160 units it selects 220. A jab has no range override.
        _,r,_=self.records[0x640570][0]
        alternative,distance=struct.unpack_from('<HH',t,at+(r[13]&65535)*4)
        self.assertEqual(distance,1160)
        self.assertNotEqual(alternative,r[12]>>16)
        self.assertLess(alternative,nr)
        _,jab,_=self.records[0x1a20b4][0]
        self.assertEqual(struct.unpack_from('<H',t,at+(jab[13]&65535)*4+2)[0],0)

    def test_pushback_variant_preserves_all_native_alias_bodies(self):
        root=ROOT
        source=(root/'generated/SLUS_004.02_full_04.c').read_text()
        generated=generate_push(root)
        prefix='#include <stdint.h>\nextern uint32_t tekken3_ttt1_push_base(void);\n'
        self.assertTrue(generated.startswith(prefix))
        self.assertEqual(generated.count('cpu->gpr[2] = tekken3_ttt1_push_base();'),6)
        restored=generated[len(prefix):].replace('\n    cpu->gpr[2] = tekken3_ttt1_push_base();','')
        self.assertEqual(restored,source)

if __name__=='__main__':unittest.main()
