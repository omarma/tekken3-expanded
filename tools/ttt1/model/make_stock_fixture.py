#!/usr/bin/env python3
"""Fabrique les DEUX fixtures manquantes, depuis un seul run D'ORIGINE :

  ps1-saves/openbios/state_80079C70_slot07.pst  etat au selecteur cabinet
  ps1-slot7-vram.bin                            VRAM de reference au meme instant

Elles doivent venir du meme run sans Jun : la reference sert justement a
verifier que Jun ne touche pas l'atlas de police (x=896..943) ni la palette de
l'etincelle de garde (ligne 503). Un etat sauvegarde avec le roster actif
porterait deja les icones de Jun, et la comparaison ne voudrait plus rien dire.
"""
import os, socket, struct, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'psxrecomp/tools'))
import debug_client

STATE = 0x800ae204
NONE = 0xffff
START = NONE & ~(1 << 3)
CROSS = NONE & ~(1 << 14)
VRAM_W, VRAM_H = 1024, 512

saves = ROOT / 'workspace/fixtures/ps1-saves'
saves.mkdir(parents=True, exist_ok=True)
work = ROOT / 'workspace/kazuya-import/fixture'; work.mkdir(parents=True, exist_ok=True)
log_path = work / 'stock.log'
with socket.socket() as s:
    s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
args = [str(ROOT / 'build-debug-server-lite/Tekken_3_Recompiled'),
        '--game', str(ROOT / 'game.toml'),
        '--disc', str(ROOT / 'disc/Tekken 3 (USA).cue'),
        '--no-launcher', '--renderer', 'software', '--headless',
        '--debug-port', str(port), '--memcard-dir', str(saves)]
env = dict(os.environ, TEKKEN3_JUN_ROSTER='0', SDL_AUDIO_DRIVER='dummy')
env.pop('TEKKEN3_JUN_ASSETS', None)
with log_path.open('w') as log:
    p = subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=log, env=env)
q = lambda r: debug_client.query('127.0.0.1', port, r)
try:
    end = time.monotonic() + 40
    while time.monotonic() < end:
        try:
            with socket.create_connection(('127.0.0.1', port), .2): break
        except OSError: time.sleep(.2)
    else: raise RuntimeError('serveur injoignable')
    def state():
        r = q(dict(cmd='read_ram', addr=f'{STATE:08x}', len=4))
        return int.from_bytes(bytes.fromhex(r['hex']), 'little') if 'hex' in r else -1
    def press(mask, hold=.18):
        q(dict(cmd='set_input', buttons=mask)); time.sleep(hold)
        q(dict(cmd='set_input', buttons=NONE)); time.sleep(hold)
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline and state() != 9:
        press(START); press(CROSS)
    if state() != 9: raise RuntimeError('selecteur non atteint')
    print('  selecteur atteint (run d origine, sans roster)')
    time.sleep(1.0)
    q(dict(cmd='clear_input')); time.sleep(.3)
    print('  savestate slot 7 :', q(dict(cmd='savestate', op='save', slot=7)))
    time.sleep(1.5)
    # dump VRAM complet, par tranches de 8 lignes
    buf = bytearray(VRAM_W * VRAM_H * 2)
    # vram_peek borne w et h a 128 chacun (voir handle_vram_peek) et rend la
    # tuile ligne par ligne : on balaie donc en tuiles de 128x128, soit 32
    # requetes pour la VRAM entiere.
    TILE = 128
    for ty in range(0, VRAM_H, TILE):
        for tx in range(0, VRAM_W, TILE):
            h = q(dict(cmd='vram_peek', x=tx, y=ty, w=TILE, h=TILE)).get('hex', '')
            if len(h) != TILE * TILE * 4:
                raise RuntimeError(f'tuile ({tx},{ty}): {len(h)} caracteres')
            for row in range(TILE):
                for col in range(TILE):
                    k = row * TILE + col
                    struct.pack_into('<H', buf, (ty+row)*VRAM_W*2 + (tx+col)*2,
                                     int(h[k*4:k*4+4], 16))
        print(f'    VRAM {ty+TILE}/{VRAM_H}', flush=True)
    out = ROOT / 'workspace/fixtures/ps1-slot7-vram.bin'
    out.write_bytes(bytes(buf))
    print('  VRAM ecrite :', out.relative_to(ROOT), len(buf), 'octets')
finally:
    if p.poll() is None: p.terminate(); p.wait(timeout=15)
for f in sorted(saves.rglob('*')):
    if f.is_file(): print('   ', f.relative_to(ROOT), f.stat().st_size)
