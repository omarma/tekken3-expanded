#!/usr/bin/env python3
"""Reproduit seul l'injection native de l'invite, sans joueur.

Build optimise avec serveur de debogage (build-opt-dbg : Release +
PSX_DEBUG_TOOLS=ON), sauvegarde du selecteur cabinet (emplacement 7, voir
tools/ttt1/model/make_stock_fixture.py), puis : case de l'invite (cellule 10,
en haut a droite), validation, attente du combat. Le journal du renderer natif
(TEKKEN3_GUEST_NATIVE_LOG) dit ou le rendu s'arrete ; en cas de gel, l'etat du
CPU est releve par le serveur de debogage.

  python3 tools/ttt1/model/repro_native.py <dossier invite> [--keep]
"""
import json, os, shutil, socket, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'psxrecomp/tools'))
import debug_client

STATE = 0x800ae204
NONE = 0xffff
bit = lambda b: NONE & ~(1 << b)
START, CROSS, UP, RIGHT, DOWN, LEFT = bit(3), bit(14), bit(4), bit(5), bit(6), bit(7)

guest = Path(sys.argv[1]).resolve()
keep = '--keep' in sys.argv
extra_env = dict(a.split('=', 1) for a in sys.argv[2:] if '=' in a)
work = ROOT / 'workspace/native/repro'
if work.exists(): shutil.rmtree(work)
(work / 'saves').mkdir(parents=True)
shutil.copytree(ROOT / 'workspace/fixtures/ps1-saves', work / 'saves', dirs_exist_ok=True)
with socket.socket() as s:
    s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
args = [str(ROOT / 'build-opt-dbg/Tekken_3_Expanded'), '--game', str(ROOT / 'game.toml'),
        '--disc', str(ROOT / 'disc/Tekken 3 (USA).cue'), '--no-launcher', '--renderer', 'software',
        '--headless', '--debug-port', str(port), '--memcard-dir', str(work / 'saves')]
env = dict(os.environ, SDL_AUDIO_DRIVER='dummy', TEKKEN3_JUN_ASSETS=str(guest), TEKKEN3_JUN_ROSTER='1',
           TEKKEN3_GUEST_UNVERIFIED='1', TEKKEN3_GUEST_NATIVE='1', TEKKEN3_GUEST_NATIVE_LOG='1', **extra_env)
log_path = work / 'repro.log'
log = log_path.open('w')
p = subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=log, env=env)
q = lambda r, t=5: debug_client.query('127.0.0.1', port, r)

def word(a):
    r = q(dict(cmd='read_ram', addr=f'{a:08x}', len=4))
    return int.from_bytes(bytes.fromhex(r['hex']), 'little') if 'hex' in r else -1
def press(mask, hold=.2):
    q(dict(cmd='set_input', buttons=f'{mask:04x}')); time.sleep(hold)
    q(dict(cmd='set_input', buttons=f'{NONE:04x}')); time.sleep(hold)
def text(): return log_path.read_text(errors='replace')

try:
    end = time.monotonic() + 40
    while time.monotonic() < end:
        try:
            with socket.create_connection(('127.0.0.1', port), .2): break
        except OSError: time.sleep(.2)
    else: raise RuntimeError('serveur injoignable')
    print('chargement emplacement 7 :', q(dict(cmd='savestate', op='load', slot=7)))
    end = time.monotonic() + 30
    while time.monotonic() < end and word(STATE) != 9: time.sleep(.2)
    print('etat', word(STATE)); time.sleep(1.5)
    if '--select-only' in sys.argv:
        json.dump(dict(pid=p.pid,port=port),open(work/'session.json','w')); keep=True; raise SystemExit
    press(LEFT)                                  # cellule 0 -> cellule 10 (invite), la ligne boucle
    q(dict(cmd='screenshot_file', path=str(work / 'selecteur.png')))
    press(CROSS)
    end = time.monotonic() + 120; last = 0
    while time.monotonic() < end:
        if p.poll() is not None: print('le jeu s est arrete, code', p.returncode); break
        t = text()
        n = t.count('native log: ')
        if n != last: last = n; end = max(end, time.monotonic() + 20)
        if 'starvation_watchdog' in t: print('GEL detecte par le chien de garde'); break
        probe = extra_env.get('TEKKEN3_NATIVE_PROBE')
        if probe:
            if os.path.exists(probe + '.0.vram') and os.path.getsize(probe + '.0.vram') >= 1 << 20:
                print('sonde ecrite :', probe); break
            continue
        if 'native log: sortie ligne 26' in t or n >= 60: break
        time.sleep(.5)
    time.sleep(3)
    lines = [l for l in text().splitlines() if 'native log' in l]
    print('\n'.join(lines[-12:]))
    if lines and 'entree' in lines[-1]:
        print('GEL : releve du CPU')
        for c in ('get_registers', 'freeze_check', 'irq_state', 'get_registers'):
            print(c, json.dumps(q(dict(cmd=c)))[:1500]); time.sleep(.5)
finally:
    if not keep and p.poll() is None: p.terminate(); p.wait(timeout=15)
    if keep: json.dump(dict(pid=p.pid, port=port), open(work / 'session.json', 'w'))
    print('pid', p.pid, 'port', port, 'journal', log_path)
