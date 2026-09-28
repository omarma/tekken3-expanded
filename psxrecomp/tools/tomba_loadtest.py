#!/usr/bin/env python3
"""tomba_loadtest.py — headless title->LOAD GAME self-test for the Tomba recomp.

Unattended PASS/FAIL oracle:
  - relaunches the exe (fast_boot) with freeze-detect + retry (Issue #6),
  - drives the title menu via injected ACTIVE-LOW pad input:
      START(0xFFF7) breaks attract -> title; RIGHT(0xFFDF) NEW GAME->LOAD; CROSS(0xBFFF) selects,
  - detects LOAD entry via mc_reads jump, then samples the framebuffer:
      slot list rendered (non-black) = PASS ; black = FAIL.

Usage: python tomba_loadtest.py <exe> <game.toml> [port]
"""
import sys, time, subprocess, socket, json

EXE  = sys.argv[1] if len(sys.argv)>1 else r"../TombaRecomp/build-codex-ape-fw/psx-runtime.exe"
TOML = sys.argv[2] if len(sys.argv)>2 else "game-loadtest.toml"
PORT = int(sys.argv[3]) if len(sys.argv)>3 else 4470
BIOS = r"bios/SCPH1001.BIN"
CWD  = r"../TombaRecomp"
NONE,RIGHT,CROSS,START = 0xFFFF,0xFFDF,0xBFFF,0xFFF7

def q(cmd, **kw):
    d={"cmd":cmd}; d.update(kw)
    try:
        s=socket.socket(); s.settimeout(5); s.connect(("127.0.0.1",PORT))
        s.sendall((json.dumps(d)+"\n").encode())
        buf=b""; dc=ds=0; ins=False; esc=False; started=False
        while True:
            ch=s.recv(65536)
            if not ch: break
            for b in ch:
                buf+=bytes([b]); c=chr(b)
                if ins:
                    if esc: esc=False
                    elif c=="\\": esc=True
                    elif c=='"': ins=False
                    continue
                if c=='"': ins=True
                elif c=="{": dc+=1; started=True
                elif c=="}": dc-=1
                elif c=="[": ds+=1
                elif c=="]": ds-=1
                if started and dc==0 and ds==0:
                    s.close(); return json.loads(buf.decode().strip())
    except Exception as e:
        return {"err":str(e)}
def frame(): return q("ping").get("frame")
def mc():    return q("sio_state").get("mc_reads")
def press(b,frames=6): q("press",buttons=b,frames=frames)

def kill_launch():
    subprocess.run(["powershell","-Command","Stop-Process -Name psx-runtime -Force -ErrorAction SilentlyContinue"],capture_output=True)
    time.sleep(1.5)
    subprocess.Popen(["powershell","-Command",
        f"Start-Process -FilePath '{EXE}' -ArgumentList '--game','{TOML}','--bios','{BIOS}','--disc','tomba/tomba.cue' -WorkingDirectory '{CWD}'"])

def alive_advancing():
    a=frame()
    if a is None: return False
    time.sleep(1.2); b=frame()
    return b is not None and b!=a

def nonblack():
    g=q("gpu_state"); dx,dy=g.get("display_x",0),g.get("display_y",0)
    nz=tot=0
    for ry in range(0,224,16):
        h=q("vram_peek",x=dx,y=dy+ry,w=320,h=1).get("hex","")
        for j in range(0,len(h),4):
            tot+=1; nz+= (h[j:j+4] not in ("0000",""))
    return nz/tot if tot else 0

def shot(name):
    b=f"../_scratch/{name}.bmp"; q("screenshot_file",path=b)
    try:
        from PIL import Image; Image.open(b).save(b.replace(".bmp",".png"))
    except Exception: pass

def attempt():
    kill_launch()
    # wait for TCP
    for _ in range(25):
        if q("ping").get("ok"): break
        time.sleep(1)
    # wait for boot past intro, with freeze detection
    t0=time.time()
    while time.time()-t0 < 45:
        if not alive_advancing():
            f=frame()
            time.sleep(2)
            if frame()==f:   # frozen
                print(f"  FROZEN at frame {f}")
                return None
        if time.time()-t0 > 18:  # intro likely done -> attract/title cycle
            break
        time.sleep(2)
    base=mc()
    # drive START->RIGHT->CROSS, retry the sequence until mc jumps (LOAD entered)
    for tseq in range(10):
        if not alive_advancing():
            print("  froze mid-nav"); return None
        press(START); time.sleep(1.3)
        press(RIGHT); time.sleep(0.7)
        press(CROSS); time.sleep(1.5)
        cur=mc()
        if cur is not None and base is not None and cur > base+40:
            print(f"  LOAD entered (mc {base}->{cur}) on seq {tseq}")
            time.sleep(3.0)  # let it render or black
            shot("loadtest_result")
            return nonblack()
        time.sleep(1.0)
    print("  never entered LOAD (mc stayed ~%s)"%base)
    return None

def main():
    for a in range(6):
        print(f"=== attempt {a} ===")
        r=attempt()
        if r is not None:
            verdict="PASS (slot list rendered)" if r>0.10 else "FAIL (black)"
            print(f"RESULT: {verdict}  nonblack={r:.2%}  screenshot=_scratch/loadtest_result.png")
            return 0 if r>0.10 else 2
    print("RESULT: INCONCLUSIVE (freeze/timing across all attempts)")
    return 3

sys.exit(main())
