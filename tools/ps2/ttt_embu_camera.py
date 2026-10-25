"""The TTT (PS2) Embu's camera at every frame: the frame's view x projection (0x4333C0, as
tools/ps2/ttt_capture.py's "view"), which the Embu capture lacks (its "vp" is actor 0's, stale
while actor 0 is hidden). From the save state of each sequence (slots 1-3) to the next one's
start. OUT.json: {"t": [16 floats]} by Embu clock (s16 0x5F6C22).

    python tools/ps2/ttt_embu_camera.py OUT.json [SLOTS, e.g. 1,3: added to OUT.json]
"""
import json, struct, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/ps2'))
from pine import Pine, OP, ttt_slot
VIEW, EMBU = 0x4333C0, 0x5F6C20
p = Pine(ttt_slot()); p.wait(60)
cam = {}
ends = {1: 1045, 2: 2069, 3: 2289}
old = json.loads(Path(sys.argv[1]).read_text()) if Path(sys.argv[1]).is_file() else {}
cam.update({int(k): v for k, v in old.items()})
for slot in [int(v) for v in sys.argv[2].split(',')] if len(sys.argv) > 2 else (1, 2, 3):
    p.call(bytes([OP['load'], slot])); time.sleep(1)
    last, since = None, time.monotonic()
    while True:
        w = p.many([EMBU] + [VIEW + 8 * k for k in range(8)])
        t = struct.unpack('<h', struct.pack('<H', (w[0] >> 16) & 0xFFFF))[0]
        if w[0] & 0xFFFF != 3: t = None                 # 2: the countdown before the scene runs
        if t is not None and t != last:
            cam.setdefault(t, list(struct.unpack('<16f', struct.pack('<8Q', *w[1:9])))); last, since = t, time.monotonic()
            if t >= ends[slot]: break
        elif time.monotonic() - since > 10: break      # the scene is over
    print('sequence', slot, 'to', last, len(cam), 'frames', flush=True)
Path(sys.argv[1]).write_text(json.dumps({str(k): v for k, v in sorted(cam.items())}))
print(sys.argv[1], len(cam), 'frames, missing', [t for t in range(0, 2290) if t not in cam][:30])
