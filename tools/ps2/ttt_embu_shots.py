"""The TTT (PS2) Embu in PCSX2 (speed 0.1, this worktree's instance, tools/ps2/ttt_pcsx2.py): from the
save state of each sequence (slots 1-3, session F's seq0-2.p2s), a save state as the Embu clock
(s16 0x5F6C22) passes each frame of a list; OUT/<t>.png = its screenshot, t read in the state's own EE RAM.

    python tools/ps2/ttt_embu_shots.py OUT 520,600,...
"""
import struct, sys, time, zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/ps2'))
from pine import Pine, OP, ttt_slot
CLOCK = 0x5F6C22
SST = ROOT / 'workspace/ttt-ps2/pcsx2-data/PCSX2/sstates'
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
targets = sorted(int(v) for v in sys.argv[2].split(','))
clock = lambda p: struct.unpack('<h', struct.pack('<H', p.r32(CLOCK) & 0xffff))[0]
p = Pine(ttt_slot()); p.wait(120)
starts = {}
for slot in (1, 2, 3):
    p.call(bytes([OP['load'], slot])); time.sleep(2); starts[slot] = clock(p)
print('sequence starts', starts, flush=True)
for slot in (1, 2, 3):
    mine = [t for t in targets if t >= starts[slot] and (slot == 3 or t < starts[slot + 1])]
    if not mine: continue
    p.call(bytes([OP['load'], slot])); time.sleep(1)
    for target in mine:
        while clock(p) < target - 1: time.sleep(.02)
        before = {q: q.stat().st_mtime for q in SST.glob('*.09.p2s')}
        p.call(bytes([OP['save'], 9]))
        new = []
        for _ in range(400):
            new = [q for q in SST.glob('*.09.p2s') if q.stat().st_mtime != before.get(q)]
            if new: break
            time.sleep(.05)
        time.sleep(.5)
        with zipfile.ZipFile(new[0]) as z:
            names = z.namelist()
            ee = z.read(next(n for n in names if 'eeMemory' in n))
            exact = struct.unpack_from('<h', ee, CLOCK)[0]
            (out / f'{exact:04d}.png').write_bytes(z.read(next(n for n in names if n.lower().endswith('.png'))))
        print(target, '->', exact, flush=True)
print('done', flush=True)
