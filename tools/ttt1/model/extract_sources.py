#!/usr/bin/env python3
"""Regenere les donnees sources de l'etude sous workspace/native/ (ignore par git).

- Jin PS1 costumes 1 et 2 : enregistrements BNS 143 et 147 du disque US.
- Jin, Kazuya et Jun TTT1 : modele, textures et table de relocalisation, lus
  dans la banque TTT1 (repertoire a 0x302238 d'une capture RAM de selection).
  Les relocalisations viennent de la comparaison banque / modele vivant a
  0x354108 dans une capture RAM ou le personnage est affiche.

Donnees du jeu : rien de ce qui est ecrit ici ne doit etre commite.
Usage : python3 tools/ttt1/model/extract_sources.py (depuis la racine).
"""
import hashlib, struct, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'workspace/native'; OUT.mkdir(parents=True, exist_ok=True)
TRACK1 = ROOT / 'disc/Tekken 3 (USA) (Track 1).bin'
EXE = ROOT / 'disc/SLUS_004.02'
BANK = ROOT / 'workspace/ttt1-analysis/ttt1/bankedroms.bin'
DIR_RAM = ROOT / 'workspace/kazuya-import/capture/kazuya-select-ram.bin'
LIVE = {'jun': ROOT/'workspace/ttt1-import/captures/jun-select-ram.bin',
        'jin': ROOT/'workspace/fixtures/jin-select-ram.bin',
        'kazuya': ROOT/'workspace/kazuya-import/capture/kazuya-select-ram.bin'}
SLOTS = {'kazuya': 64, 'jun': 46, 'jin': 88}      # emplacement = 2 x index d'asset
BNS_LBA, LIVE_BASE, DIR = 250156, 0x354108, 0x302238

def cooked_sector_reader(path):
    f = open(path, 'rb')
    def read(lba, n):
        out = bytearray()
        while len(out) < n:
            f.seek(lba * 2352 + 24); out += f.read(2048); lba += 1
        return bytes(out[:n])
    return read

def bns_records():
    exe = EXE.read_bytes(); read = cooked_sector_reader(TRACK1)
    recs = [struct.unpack_from('<2I', exe, 0x14c00 + i * 8) for i in range(303)]
    for rid in (143, 147):
        sec, size = recs[rid]
        data = read(BNS_LBA + sec, size)
        assert data[8:12] == b'3DMK', rid
        (OUT / f'rec{rid:03d}.bin').write_bytes(data)
        print(f'BNS {rid}: {size} o')

def ttt1_assets():
    bank = BANK.read_bytes(); d = DIR_RAM.read_bytes()
    entry = lambda i: struct.unpack_from('<II', d, DIR + i * 8)
    for name, slot in SLOTS.items():
        mo, mn = entry(109 + slot); to, tn = entry(slot)
        model, tex = bank[mo:mo + mn], bank[to:to + tn]
        live = LIVE[name].read_bytes()[LIVE_BASE:LIVE_BASE + mn]
        rel = [p for p in range(0, mn - 3, 4)
               if model[p:p + 4] != live[p:p + 4]
               and 0 < struct.unpack_from('<I', model, p)[0] < mn
               and 0x80000000 + LIVE_BASE <= struct.unpack_from('<I', live, p)[0] < 0x80000000 + LIVE_BASE + mn]
        (OUT / f'{name}-ttt1.3dm').write_bytes(model)
        (OUT / f'{name}-ttt1.tex').write_bytes(tex)
        # La capture de Kazuya ne contient pas son modele complet a 0x354108 :
        # on reprend alors la table de l'import existant, validee en jeu (187).
        known = ROOT / 'workspace/kazuya-import/kazuya/Kazuya-TTT1-arcade-P1.relocs'
        if name == 'kazuya' and known.exists():
            rel = list(struct.unpack(f'<{known.stat().st_size // 4}I', known.read_bytes()))
        (OUT / f'{name}-ttt1.relocs').write_bytes(struct.pack(f'<{len(rel)}I', *rel))
        print(f'{name} TTT1: modele {mn} o ({hashlib.sha256(model).hexdigest()[:12]}), '
              f'textures {tn} o, {len(rel)} relocalisations')

if __name__ == '__main__':
    bns_records(); ttt1_assets()
