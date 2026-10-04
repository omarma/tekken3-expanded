#!/usr/bin/env python3
"""Lance le jeu EN FENETRE (chemin natif, aucun invite) avec le serveur de
debogage ; l'utilisateur joue. Des que Jin est en combat (J1 ou J2), capture
RAM, scratchpad et VRAM, plusieurs fois, sous workspace/native/capture/NN/.
Le jeu reste ouvert apres les captures.
"""
import os, socket, struct, subprocess, sys, time, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'psxrecomp/tools'))
import debug_client

BUILD = os.environ.get('CAP_BUILD', 'build-debug-server-lite')
OUT = ROOT / 'workspace/native/capture'; OUT.mkdir(parents=True, exist_ok=True)
SHOTS, GAP = 4, 1.5

with socket.socket() as s:
    s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
env = {k: v for k, v in os.environ.items() if not k.startswith(('TEKKEN3_JUN', 'TEKKEN3_GUEST'))}
env['TEKKEN3_JUN_ASSETS'] = str(ROOT/'workspace/native/empty-jun')
args = [str(ROOT/BUILD/'Tekken_3_Expanded'), '--game', str(ROOT/'game.toml'),
        '--disc', str(ROOT/'disc/Tekken 3 (USA).cue'), '--debug-port', str(port)]
p = subprocess.Popen(args, cwd=ROOT, stdout=(OUT/'game.log').open('w'), stderr=subprocess.STDOUT, env=env)
print('jeu lance, port', port, flush=True)

q = lambda r: debug_client.query('127.0.0.1', port, r)
def ram(a, n): return bytes.fromhex(q(dict(cmd='read_ram', addr=f'{a:08x}', len=n))['hex'])
def val(a): return struct.unpack('<I', ram(a, 4))[0]

def models():
    """Modeles 3DMK a 27 lignes des deux joueurs : [(joueur, base)]."""
    out=[]
    for pl in (0, 1):
        base = val(0x8009bd28 + pl*4)
        if 0x80000000 <= base < 0x80200000 and val(base) == 27 and ram(base+8, 4) == b'3DMK':
            out.append((pl, base))
    return out

def vram():
    out = bytearray(1024*512*2)
    for y in range(0, 512, 128):
        for x in range(0, 1024, 128):
            px = bytes.fromhex(q(dict(cmd='vram_peek', x=x, y=y, w=128, h=128))['hex'])
            for row in range(128):
                line = px[row*256:(row+1)*256]
                le = b''.join(line[i+1:i+2]+line[i:i+1] for i in range(0, 256, 2))
                o = ((y+row)*1024 + x)*2
                out[o:o+256] = le
    return bytes(out)

try:
    while True:                                   # attendre le serveur
        if p.poll() is not None: print('jeu ferme'); sys.exit(1)
        try:
            with socket.create_connection(('127.0.0.1', port), .5): break
        except OSError: time.sleep(1)
    print('serveur de debogage pret ; en attente d un combat', flush=True)
    seen = 0; last = None; diag = (OUT/'diag.log').open('w')
    while seen < SHOTS:
        if p.poll() is not None: print('jeu ferme avant capture'); sys.exit(1)
        try:
            ms = models(); st = (val(0x800ae204), val(0x800ae224))
        except Exception as e:
            time.sleep(2); continue
        key = (st, tuple(ms))
        if key != last:
            diag.write(f'{time.strftime("%H:%M:%S")} etat={st} modeles={[(pl, hex(b)) for pl, b in ms]}\n'); diag.flush(); last = key
        if len(ms) < 2:
            time.sleep(2); continue
        time.sleep(4 if seen == 0 else GAP)       # laisser le combat demarrer
        d = OUT / f'{seen:02d}'; d.mkdir(exist_ok=True)
        (d/'ram.bin').write_bytes(ram(0x80000000, 0x200000))
        (d/'scratch.bin').write_bytes(ram(0x1F800000, 0x400))
        (d/'vram.bin').write_bytes(vram())
        (d/'meta.json').write_text(json.dumps(dict(models=[(pl, f'{b:08X}') for pl, b in ms], state=st, t=time.time())))
        print(f'capture {seen} : modeles {[(pl, hex(b)) for pl, b in ms]} etat {st}', flush=True)
        seen += 1
    print('CAPTURES TERMINEES — le jeu reste ouvert', flush=True)
    p.wait()
except KeyboardInterrupt:
    pass
