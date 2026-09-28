"""Live regressions for skeleton changes, head contact and back-facing recovery.

Uses private assets and an isolated debug process. Inputs run at normal speed;
fixture transitions arrange a dummy/reaction, never synthesize hit results.
"""
import argparse
import json
import re
import struct
import time
from pathlib import Path
from test_ttt1_solo import Solo,P1,P2
from ttt1_live import Session,cabinet,idle,guest_id


class Recovery(Solo):
    def __init__(self,case):
        if case=='head':
            self.s=Session()
            try:
                cabinet(self.s,False,23)
                self.s.write(P2+0xc5,0,1);idle(self.s,1)   # Jin P1, the guest P2
            except BaseException:
                self.s.stop();raise
            self.source={};self.trace=[]
        else:
            super().__init__(mirror=case in ('mirror','back-p2'))
        self.rows=[]

    def snapshot(self):
        row=[]
        for actor in (P1,P2):
            b=self.s.read(actor,0x188c)
            record=struct.unpack_from('<I',b,0x54)[0]
            row.append(dict(record=record,clip=self.source.get(record,0),
                frame=struct.unpack_from('<H',b,0x58)[0],
                hp=struct.unpack_from('<I',b,0x3f4)[0]/65536,
                throw=struct.unpack_from('<h',b,0x74)[0],
                facing=struct.unpack_from('<6h',b,0x2a),
                bones=[struct.unpack_from('<3i',b,0x908+k*68) for k in (0,2,14,17)],
                joint_matrices=[struct.unpack_from('<9h',b,0x8f4+k*68) for k in (2,6,10,14,17)],
                contacts=[struct.unpack_from('<H',b,off+24)[0] for off in (0x13c,0x168)],
                guard=b[0xcf]))
        self.rows.append(row);return row

    @staticmethod
    def upright(actor):
        pelvis,head,left,right=actor['bones']
        assert head[1]<pelvis[1]-150,('Head below pelvis',actor)
        assert min(left[1],right[1])>pelvis[1]+450,('Feet above pelvis',actor)

    @staticmethod
    def standing_axes(actor,arcade=False):
        # Mesh orientation, not just the location of its joint. The head's
        # local +Z points up; native feet use +Y down, arcade feet use -Y.
        head,_,_,left,right=actor['joint_matrices']
        assert head[5]<-2000,('Inverted head during standing recovery',actor)
        sign=-1 if arcade else 1
        assert min(left[4]*sign,right[4]*sign)>2000,('Reversed feet during standing recovery',actor)

    def joints(self):
        self.approach()
        self.s.q(cmd='set_input',buttons=0xffdf);time.sleep(.5);self.s.q(cmd='clear_input')
        self.force(1,0xd67)
        self.s.q(cmd='press',buttons=0x7fff,frames=3)
        end=self.s.game_until(2.5);reaction=False;checked=0
        while end():
            a,b=self.snapshot()
            if b['hp']<130 and b['clip']==0x692f3c:
                if not reaction:self.s.shot('recovery-joints-hit')
                reaction=True
            if reaction and 0x80010000<b['record']<0x80200000 and 1<=b['frame']<=12:
                self.standing_axes(b);checked+=1
                if checked==1:self.s.shot('recovery-joints-idle')
            time.sleep(.008)
        assert reaction,'Original Jun jab reaction did not reach the stock opponent'
        assert checked,'Did not sample early return to native idle'
        assert min(b['hp'] for a,b in self.rows)==125,'Wrong jab damage'
        return dict(source_reaction='0x692f3c',damage=5,early_recovery_orientation_samples=checked)

    def throw_basis(self,mirror=False):
        self.approach();self.s.q(cmd='press',buttons=0x3fff,frames=3)
        checked=0;captured=False;end=self.s.game_until(5)
        while end():
            a,b=self.snapshot()
            if a['throw']>0 and b['throw']<0 and 2<=b['frame']<=8:
                self.upright(a);self.upright(b);checked+=1
                if not captured:self.s.shot('recovery-throw-'+('mirror' if mirror else 'stock'));captured=True
            time.sleep(.008)
        assert checked,'Did not sample the standing paired pose'
        assert min(b['hp'] for a,b in self.rows)==100,'Wrong throw damage'
        a,b=self.rows[-1]
        assert a['clip']==0x102b58 and not a['throw'] and not b['throw'],'Throw did not release'
        self.upright(a)
        return dict(standing_samples=checked,damage=30)

    def head(self):
        # Jun's standing victory cannot auto-guard. The stock Jin jab then
        # uses native collision, damage, shared hit reaction, and idle blend.
        # Sample up to three poses: the moving forearm can intercept a high
        # jab or the pose can leave its range. Require a real head contact.
        checked=0;recovered=0;head_contact=False;results=[]
        for delay in (0,.12,.3):
            self.approach()
            self.s.q(cmd='set_input',buttons=0xffdf);time.sleep(.5);self.s.q(cmd='clear_input')
            self.s.write(P2+0x3f4,130<<16)
            self.force(1,0xd67);time.sleep(delay)
            self.s.q(cmd='press',buttons=0x7fff,frames=1)
            start=len(self.rows);end=self.s.game_until(1.8)
            while end():
                a,b=self.snapshot()
                if b['hp']<130 and 0x80010000<b['record']<0x80200000:
                    self.upright(b);checked+=1
                    if 8 in b['contacts'] and not head_contact:
                        self.s.shot('recovery-head-hit');head_contact=True
                if b['hp']<130 and b['record']>=0x9f000000 and 1<=b['frame']<=12:
                    self.standing_axes(b,True);recovered+=1
                time.sleep(.008)
            hit=[b for a,b in self.rows[start:] if b['hp']<130]
            assert not any(b['guard'] for b in hit),'Fixture guarded the jab'
            if hit:self.upright(self.rows[-1][1])
            results.append(dict(delay=delay,damage=130-min((b['hp'] for b in hit),default=130),zones=sorted({z for b in hit for z in b['contacts'] if z})))
            if head_contact:break
        assert checked,'No shared native head-hit reaction reached'
        assert head_contact,'No strike contacted the head sphere'
        assert recovered,'Did not sample Jun returning from the native reaction'
        assert any(8 in r['zones'] and r['damage']==7 for r in results),'Wrong native head damage'
        return dict(head_contact=True,trials=results,native_reaction_samples=checked,early_recovery_orientation_samples=recovered)

    def turn(self,player=0):
        actor=(P1,P2)[player];results=[]
        for button in ((0xffdf,0xff7f) if player==0 else (None,)):
            # Arrange a back-facing stance, then use actual direction input.
            target=self.s.value(actor+0x2a,2)
            self.force(player,3,facing=(target+0x8000)&65535)
            if button is None:
                # The debug pad injects P1 only. P2 starts the same original
                # C1 turn through its own native transition queue.
                index=next(i for i in range(self.count) if self.source[self.base+i*56]==0x13e84c)
                self.force(player,guest_id(player,index))
            else:self.s.q(cmd='set_input',buttons=button)
            start=len(self.rows);end=self.s.game_until(2);turned=False
            while end():
                row=self.snapshot();a=row[player]
                if a['facing'][4]==0:
                    turned=True;self.s.q(cmd='clear_input');break
                time.sleep(.008)
            assert turned,('Back-facing movement never committed its turn',player,button)
            time.sleep(.8);a=self.snapshot()[player]
            assert a['facing'][4]==0,'Returned to idle facing backwards'
            self.upright(a)
            results.append(dict(button=button,samples=len(self.rows)-start,final_facing=a['facing']))
        self.s.shot('recovery-turn-p'+str(player+1))
        return results


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--case',choices=('throw','mirror','head','joints','back','back-p2'),required=True)
    case=p.parse_args().case;f=Recovery(case)
    try:
        result=f.joints() if case=='joints' else f.head() if case=='head' else f.turn(case=='back-p2') if case.startswith('back') else f.throw_basis(case=='mirror')
        f.finish('recovery-'+case,result)
    finally:
        (f.s.work/('recovery-test-'+case+'.json')).write_text(json.dumps(dict(session=f.s.info,rows=f.rows),indent=2))
        f.s.stop()
