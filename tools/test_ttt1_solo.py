"""Private live fixtures: original solo throws, input chains and round wins."""
import argparse
import json
import re
import struct
import time
from pathlib import Path
from ttt1_live import Session,cabinet,idle,guest_id

P1,P2=0x800a9228,0x800aaab4

class Solo:
    def __init__(self,visible=False,mirror=False):
        self.s=Session(visible)
        try:
            cabinet(self.s,opponent=23 if mirror else 9)
            self.s.write(P2+0xc5,0,1);idle(self.s)
        except BaseException:
            self.s.stop();raise
        p=(Path(self.s.info['assets'])/'Jun-TTT1-combat.jmv').read_bytes()
        self.pack=p;self.count=struct.unpack_from('<I',p,12)[0]
        log=Path(self.s.info['log']).read_text()
        self.base=int(re.findall(r'installed P1 alias table,.*records=([0-9A-F]+)',log)[-1],16)
        self.source={self.base+i*56:struct.unpack_from('<I',p,32+i*16)[0] for i in range(self.count)}
        self.trace=[]
    def state(self):
        rows=[]
        for a in (P1,P2):
            b=self.s.read(a,0x3f8);record=struct.unpack_from('<I',b,0x54)[0]
            rows.append(dict(record=record,clip=self.source.get(record,0),
                             frame=struct.unpack_from('<H',b,0x58)[0],
                             hp=struct.unpack_from('<I',b,0x3f4)[0]/65536,
                             throw=struct.unpack_from('<h',b,0x74)[0],
                             rotation=b[0xb9],position=struct.unpack_from('<3i',b)))
        self.trace.append(rows);return rows
    def align(self,distance=500):
        self.s.q(cmd='clear_input');self.s.write(P2+0xc5,0,1)
        # The debug interface writes bytes. Gate actor updates while setting
        # multi-byte positions so a partial coordinate cannot enter physics.
        for a in (P1,P2):self.s.write(a+0xc3,0,1)
        for a,x,facing in ((P1,-distance,0x4000),(P2,distance,0xc000)):
            for offset,value in ((0,x),(4,0),(8,0),(0xf68,x),(0xf6c,0),(0xf70,0),(0x3f4,130<<16)):
                self.s.write(a+offset,value)
            for offset in (0xe,0x2c):self.s.write(a+offset,facing,2)
        for a in (P1,P2):self.s.write(a+0xc3,1,1)
        time.sleep(.3)
    def sample(self,seconds):
        end=self.s.game_until(seconds);rows=[]
        while end():
            rows.append(self.state());time.sleep(.008)
        return rows
    def approach(self):
        self.s.q(cmd='set_input',buttons=0xffdf)
        deadline=self.s.game_until(6)
        while deadline():
            a,b=self.state()
            dx=a['position'][0]-b['position'][0];dz=a['position'][2]-b['position'][2]
            if dx*dx+dz*dz<1250**2:break
            time.sleep(.025)
        else:raise AssertionError('Could not walk into throw range')
        self.s.q(cmd='clear_input');time.sleep(.04)
    def force(self,player,alias,kind=6,facing=None):
        a=(P1,P2)[player];s=self.s
        table=s.value(s.value(0x800adc20+player*4)+12)
        s.write(a+0xc3,0,1)
        for offset,value in ((0x6e,0),(0x198,1),(0x19a,kind),(0x19c,0),(0x19e,0),(0x1a0,alias)):
            s.write(a+offset,value,2)
        s.write(a+0x1a4,s.value(table+alias*4));s.write(a+0xc3,1,1)
        time.sleep(.06)
        if facing is not None:
            s.write(a+0xc3,0,1)
            for offset in (0xe,0x2c):s.write(a+offset,facing,2)
            s.write(a+0xb9,0,1);s.write(a+0xc3,1,1)
    def angles(self,cases):
        results=[]
        for facing,expected in cases:
            self.approach()
            # Orient the dummy relative to the live opponent ray after
            # walking. Teleporting into overlap before approaching lets
            # body separation rotate that ray into a different throw sector.
            ray=self.s.value(P2+0x2a,2)
            self.force(1,3,facing=(ray+facing+0x4000)&65535)
            self.s.q(cmd='press',buttons=0x3fff,frames=3)
            rows=self.sample(5)
            paired=[(a,b) for a,b in rows if a['throw']>0 and b['throw']<0]
            assert paired,('No side/back throw',facing,sorted({hex(a['clip']) for a,b in rows}))
            assert paired[0][0]['clip']==expected,(facing,hex(paired[0][0]['clip']))
            assert min(b['hp'] for a,b in rows)<130,'Side/back throw did not damage'
            assert any(a['clip']==0x102b58 and not a['throw'] and not b['throw'] for a,b in rows),'Side/back throw did not release'
            results.append(dict(facing=facing,attacker=hex(expected),victim=hex(paired[0][1]['clip']),hp=min(b['hp'] for a,b in rows)))
        return results
    def facing_victories(self):
        results=[]
        for alias,clip in ((0xd67,0xae32dc),(0xd68,0xae4b08)):
            self.align(4000);self.force(0,alias)
            self.s.wait(lambda:self.state()[0]['clip']==clip and self.state()[0]['frame']>=60,
                        'Victory did not reach its middle pose',2)
            self.s.shot('solo-victory-'+hex(clip)[2:])
            rows=self.sample(3.5)
            frames=[a['frame'] for a,b in rows if a['clip']==clip]
            assert frames and max(frames)>=140,(hex(clip),frames)
            results.append(dict(alias=hex(alias),clip=hex(clip),last_frame=max(frames)))
        index=next(i for i in range(self.count) if self.source[self.base+i*56]==0x511ea4)
        self.force(0,guest_id(0,index),46)
        rows=self.sample(1.8)
        assert any(a['clip']==0x511ea4 and a['rotation']==12 for a,b in rows),'Source facing transition did not execute'
        assert any(a['clip']==0x102b58 for a,b in rows),'Source facing transition did not recover'
        return dict(victories=results,source_facing_transition=46)
    def command_throw(self,crouch=False):
        self.approach()
        if crouch:
            self.s.q(cmd='set_input',buttons=0xff9f)
            self.s.wait(lambda:self.state()[0]['clip']==0x139f1c,'Crouch-dash entry not reached',2)
        self.s.q(cmd='press',buttons=0xaf9f if crouch else 0x6f7f,frames=3)
        rows=self.sample(5)
        paired=[(a,b) for a,b in rows if a['throw']>0 and b['throw']<0]
        expected=0x93aa78 if crouch else 0x312da10
        assert paired and paired[0][0]['clip']==expected,('Command throw missing',sorted({hex(a['clip']) for a,b in rows}))
        assert min(b['hp'] for a,b in rows)<130,'Command throw damage missing'
        assert any(a['clip']==0x102b58 and not a['throw'] and not b['throw'] for a,b in rows),'Command throw did not release'
        return dict(attacker=hex(expected),victim=hex(paired[0][1]['clip']),hp=min(b['hp'] for a,b in rows))
    def throw(self,kind,victory=False):
        self.approach()
        self.s.q(cmd='press',buttons=0x3fff if kind=='13' else 0xcfff,frames=3)
        attacker,victim=(0x757e64,0x759d84) if kind=='13' else (0x78ea44,0x78faf4)
        weakened=False;captured=False;start=len(self.trace);end=self.s.game_until((20 if victory else 5))
        while end():
            row=self.state()
            if victory and not weakened and row[0]['clip']==attacker and row[0]['frame']>30:
                self.s.write(P2+0x3f4,1<<16);weakened=True
            if not captured and (row[0]['clip'] in (0xae32dc,0xae4b08) and row[0]['frame']>=60 if victory else row[0]['clip']==attacker and row[0]['frame']>=30):
                self.s.shot('solo-victory' if victory else 'solo-throw-'+kind);captured=True
            time.sleep(.008)
        rows=self.trace[start:]
        assert any(a['clip']==attacker and b['clip']==victim and a['throw']>0 and b['throw']<0 for a,b in rows),'Paired throw not reached'
        assert min(b['hp'] for a,b in rows)==(0 if victory else 100),'Wrong throw damage'
        assert any(a['clip']==0x102b58 and not a['throw'] and not b['throw'] for a,b in rows),'Throw did not release'
        if victory:assert any(a['clip'] in (0xae32dc,0xae4b08) for a,b in rows),'Original Jun solo victory not reached'
        assert captured,'Animation ended before its visual checkpoint'
        return dict(paired_clips=[hex(attacker),hex(victim)],damage=30,victory=sorted({hex(a['clip']) for a,b in rows if a['clip'] in (0xae32dc,0xae4b08)}))
    def combos(self):
        results={};input_frames={}
        for name,button,expected in (('1,1',0x7fff,0x500ac0),('1,2',0xefff,0x1a67b4),('1,3',0xbfff,0x504d8c)):
            self.align(4000)
            self.s.q(cmd='press',buttons=0x7fff,frames=1)
            # The source gate is exactly frame 10, and pad delivery takes
            # another 2-3 frames. A 60 ms poll of both actors can miss it.
            end=self.s.game_until(2)
            while end():
                record,frame=struct.unpack('<IH',self.s.read(P1+0x54,6))
                if self.source.get(record)==0x1a20b4 and frame>=4:break
                time.sleep(.002)
            else:raise AssertionError('Jun jab did not start')
            assert frame<=6,('Fixture missed early input window',name,frame)
            input_frames[name]=frame
            # Keep the button held through the gate as well.
            self.s.q(cmd='press',buttons=button,frames=10)
            rows=self.sample(1.8)
            assert any(a['clip']==expected for a,b in rows),(name,[hex(a['clip']) for a,b in rows])
            results[name]=hex(expected)
        return dict(chains=results,input_frames=input_frames)
    def reversal(self):
        s=self.s
        base2=int(re.findall(r'installed P2 alias table,.*records=([0-9A-F]+)',Path(s.info['log']).read_text())[-1],16)
        for i in range(self.count):self.source[base2+i*56]=struct.unpack_from('<I',self.pack,32+i*16)[0]
        jab=next(i for i in range(self.count) if self.source[self.base+i*56]==0x1a20b4)
        observed=[]
        for delay in (1,3,5,7):
            self.force(0,3);self.force(1,3)
            self.approach()
            s.q(cmd='set_input',buttons=0xffdf);time.sleep(.35);s.q(cmd='clear_input')
            # Fixture opponent starts an ordinary source jab. Jun's reversal
            # itself is entered through actual b+1+3 input and native contact.
            s.write(P2+0xc3,0,1)
            for offset,value in ((0x6e,0),(0x198,1),(0x19a,14),(0x1a0,guest_id(1,jab))):
                s.write(P2+offset,value,2)
            s.write(P2+0x1a4,base2+jab*56)
            s.write(P2+0xc3,1,1)
            deadline=self.s.game_until(1)
            while deadline():
                row=self.state()
                if row[1]['clip']==0x1a20b4 and row[1]['frame']>=delay:break
            s.q(cmd='press',buttons=0x3f7f,frames=3)
            rows=self.sample(2.2);observed.extend(rows)
            paired=[(a,b) for a,b in rows if a['throw']>0 and b['throw']<0]
            if paired:
                self.s.shot('solo-reversal')
                return dict(attacker=hex(paired[0][0]['clip']),victim=hex(paired[0][1]['clip']),delay=delay,
                            opponent_hp=min(b['hp'] for a,b in rows))
        raise AssertionError(('Reversal did not catch jab',sorted({(hex(a['clip']),hex(b['clip'])) for a,b in observed})))
    def hit_followup(self):
        self.align(600)
        # Start the dummy's native ki charge, whose recovery cannot guard.
        s=self.s;table=s.value(s.value(0x800adc24)+12)
        s.write(P2+0xc3,0,1)
        for offset,value in ((0x6e,0),(0x198,1),(0x19a,6),(0x1a0,6)):s.write(P2+offset,value,2)
        s.write(P2+0x1a4,s.value(table+6*4));s.write(P2+0xc3,1,1)
        self.s.q(cmd='press',buttons=0x6fdf,frames=3)  # f+1+2
        rows=self.sample(3)
        seen={a['clip'] for a,b in rows}
        assert 0x245450 in seen,('Original attack missing',[hex(x) for x in seen])
        assert min(b['hp'] for a,b in rows)<130,'Follow-up did not hit'
        victim={b['clip'] for a,b in rows if b['hp']<130}
        assert 0x6a8048 in victim,('Original hit reaction missing',[hex(x) for x in victim])
        assert 0x102b58 not in victim,'Opponent entered Jun idle instead of a hit reaction'
        return dict(clips=[hex(x) for x in sorted(seen)],victim_clips=[hex(x) for x in sorted(victim)],opponent_hp=min(b['hp'] for a,b in rows))
    def finish(self,case,result):
        log=Path(self.s.info['log']).read_text()
        assert 'unmapped native entry' not in log,'Native entry mapping was missing; inspect preview log'
        self.s.fonts();self.s.effects()
        out=self.s.work/('solo-test-'+case+'.json')
        out.write_text(json.dumps(dict(result=result,trace=self.trace,session=self.s.info),indent=2)+'\n')
        print('PASS',case,result,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--case',choices=['13','24','combos','victory','reversal','hit-followup','left','right','back','facing-victories','command','crouch-command'],required=True)
    p.add_argument('--visible',action='store_true');a=p.parse_args()
    fixture=Solo(a.visible,a.case=='reversal')
    try:
        # Each angle starts in a fresh match. A completed side throw changes
        # camera/input orientation, so reusing that scene changes the next test.
        methods={'hit-followup':fixture.hit_followup,'reversal':fixture.reversal,'combos':fixture.combos,'left':lambda:fixture.angles(((0,0x7dd9a4),)),'right':lambda:fixture.angles(((0x8000,0x84a334),)),'back':lambda:fixture.angles(((0x4000,0x8e188c),)),'facing-victories':fixture.facing_victories}
        methods.update(command=fixture.command_throw,**{'crouch-command':lambda:fixture.command_throw(True)})
        result=methods[a.case]() if a.case in methods else fixture.throw('13' if a.case=='victory' else a.case,a.case=='victory')
        fixture.finish(a.case,result)
    finally:
        (fixture.s.work/('solo-trace-'+a.case+'.json')).write_text(json.dumps(fixture.trace,indent=2))
        fixture.s.stop()
