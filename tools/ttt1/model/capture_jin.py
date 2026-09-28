#!/usr/bin/env python3
"""Capture Jin PS1 natif en combat : RAM, scratchpad, VRAM entiere.

Lance le build debug sans assets d'invite (chemin 100 % natif), charge l'etat
du selecteur, parcourt la grille jusqu'a trouver le personnage dont le modele
porte l'empreinte de Jin (lignes 0/1/19 -> +0x620/+0x98c/+0x5714), puis capture.
Sorties sous workspace/native/capture/ (ignore par git).
"""
import os, socket, struct, subprocess, sys, time, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'psxrecomp/tools'))
import debug_client

BUILD = os.environ.get('CAP_BUILD', 'build-opt')
OUT = ROOT / 'workspace/native/capture'; OUT.mkdir(parents=True, exist_ok=True)
STATE, HILITE, SUB = 0x800ae204, 0x80118668, 0x800ae224
MODEL_P1 = 0x8009bd28
NONE = 0xffff
log_path = OUT / 'run.log'

def start():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
    args = [str(ROOT/BUILD/'Tekken_3_Recompiled'), '--game', str(ROOT/'game.toml'),
            '--disc', str(ROOT/'disc/Tekken 3 (USA).cue'), '--no-launcher',
            '--renderer', 'software', '--headless', '--debug-port', str(port),
            '--memcard-dir', str(ROOT/'workspace/fixtures/ps1-saves')]
    env = {k: v for k, v in os.environ.items() if not k.startswith(('TEKKEN3_JUN', 'TEKKEN3_GUEST'))}
    env['SDL_AUDIO_DRIVER'] = 'dummy'
    env['TEKKEN3_JUN_ASSETS'] = str(ROOT/'workspace/native/empty-jun')   # aucun invite : chemin natif
    p = subprocess.Popen(args, cwd=ROOT, stdout=log_path.open('w'), stderr=subprocess.STDOUT, env=env)
    end = time.monotonic() + 40
    while time.monotonic() < end:
        try:
            with socket.create_connection(('127.0.0.1', port), .2): break
        except OSError: time.sleep(.2)
    return p, port

p, port = start()
q = lambda r: debug_client.query('127.0.0.1', port, r)
ram = lambda a, n: bytes.fromhex(q(dict(cmd='read_ram', addr=f'{a:08x}', len=n))['hex'])
val = lambda a: struct.unpack('<I', ram(a, 4))[0]
def press(mask, hold=.16):
    q(dict(cmd='set_input', buttons=mask)); time.sleep(hold)
    q(dict(cmd='set_input', buttons=NONE)); time.sleep(hold)

def is_jin():
    base = val(MODEL_P1)
    if not (0x80000000 <= base < 0x80200000): return False, base
    w = lambda o: val(base + o)
    return (w(24) == base+0x620 and w(80) == base+0x98c and w(24+19*56) == base+0x5714), base

try:
    time.sleep(6)
    found = None
    for step in range(0, 24):
        print(f'essai {step}: chargement de l\'etat', flush=True)
        q(dict(cmd='savestate', op='load', slot=7)); time.sleep(2.5)
        for _ in range(step): press(0xff7f)          # droite
        h = val(HILITE)
        press(0x7fff)                                 # valider
        t = time.monotonic() + 40
        while time.monotonic() < t and val(STATE) != 8: time.sleep(.3)
        t = time.monotonic() + 60
        while time.monotonic() < t and val(SUB) < 6: time.sleep(.5)
        ok, base = is_jin()
        print(f'  case {step} (id {h}) : modele P1 {base:08X} {"JIN" if ok else ""}', flush=True)
        if ok: found = (step, h, base); break
    if not found:
        print('Jin introuvable'); sys.exit(1)
    time.sleep(3)
    q(dict(cmd='screenshot', path=str(OUT/'combat.png')))
    (OUT/'ram.bin').write_bytes(ram(0x80000000, 0x200000))
    (OUT/'scratch.bin').write_bytes(ram(0x1F800000, 0x400))
    vram = bytearray(1024*512*2)
    for y in range(0, 512, 128):
        for x in range(0, 1024, 128):
            r = q(dict(cmd='vram_peek', x=x, y=y, w=128, h=128))
            px = bytes.fromhex(r['hex'])
            for row in range(128):
                line = px[row*256:(row+1)*256]
                # hex was written as %04x of the u16 value: big-endian per pixel
                le = b''.join(line[i+1:i+2]+line[i:i+1] for i in range(0, 256, 2))
                o = ((y+row)*1024 + x)*2
                vram[o:o+256] = le
    (OUT/'vram.bin').write_bytes(bytes(vram))
    (OUT/'meta.json').write_text(json.dumps(dict(step=found[0], hilite=found[1], model_base=f'{found[2]:08X}')))
    print('capture ecrite dans', OUT)
finally:
    if p.poll() is None: p.terminate(); p.wait(timeout=15)
