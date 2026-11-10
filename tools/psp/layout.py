#!/usr/bin/env python3
"""Carte de la RAM de Tekken : Dark Resurrection PSP (ULUS10139), adresses PSP.

Relevee sur la sauvegarde Practice Devil Jin contre Paul (2026-10-13), verifiee par
des ecritures en jeu (tools/psp/dr_moveset_probe.py, TIPS.md section DR). Le moveset
reprend les structures de Tekken 5 PS2 (tools/t5/t5_moveset.py), petit-boutiste ;
l'en-tete a 37 alias par table au lieu de 36, d'ou la table des listes a +0x188.
"""
import struct

RAM_BASE = 0x08800000                       # RAM utilisateur, 24 Mo

# Structure du joueur
P1 = 0x08B75930                             # joueur 1 ; joueur 2 = P1 + PSIZE
PSIZE = 0x8D0
MOTBIN = 0x50                               # adresse de l'en-tete du moveset (copies a +0x54, +0x58, +0xBC)
CUR_MOVE = 0xC0                             # coup en cours (adresse de son enregistrement ; copie a +0xC4)
MOVE_FRAME = 0xB0                           # image du coup, u32 = image x 4096 (copies non motrices : +0x96..+0xA4 u16, +0xA8/+0xAC float)

# En-tete du moveset
NAMES = 0x08                                # 4 pointeurs : personnage, auteur, date, date complete
N_ALIAS = 37                                # T5 PS2 : 36
ALIAS_ORIG = 0x18                           # alias d'origine (37 mots)
ALIAS = 0xAC                                # alias courants (37 mots), ceux que lit 0x8000 + n
TABLE = 0x188                               # (adresse, nombre) des 15 listes ; T5 PS2 : 0x180
LISTS = ['reactions', 'requirement', 'hitCondition', 'pushback', 'pushbackExtradata', 'cancel', 'groupCancel',
         'cancelExtradata', 'extraMoveProperty', 'moveBeginningProp', 'moveEndingProp', 'move', 'voiceclip',
         'inputSequence', 'input']

# Enregistrements (comme T5 PS2)
MOVE_SIZE = 76                              # +0 nom, +0x14 liste d'annulation, +0x24 duree, +0x44/+0x46 frappe
MOVE_CANCEL = 0x14
CANCEL_SIZE = 24                            # commande, conditions, destination (+8), fenetre...
CANCEL_DEST = 8
STANCE_ALIAS = 1                            # alias 1 = garde debout
REQ_SIZE = 4                                # condition u16, parametre u16
REQ_END = 330                               # fin d'une liste de conditions ; T5 PS2 : 321 (numeros decales de 9)
INPUT_SEQ_BASE = 0x8013                     # commande 0x8013 + i = sequence d'entrees i (comme T5 PS2)


class Moveset:
    """Lecture d'un moveset DR par une fonction read(adresse, taille) (PPSSPP en direct ou relevé de RAM)."""
    def __init__(s, read, player=0):
        s.read = read
        s.player = P1 + player * PSIZE
        s.hdr = s.u32(s.player + MOTBIN)
        s.name = s.cstr(s.u32(s.hdr + NAMES))
        s.lists = {n: struct.unpack('<II', read(s.hdr + TABLE + i * 8, 8)) for i, n in enumerate(LISTS)}
        s.aliases = list(struct.unpack(f'<{N_ALIAS}I', read(s.hdr + ALIAS, N_ALIAS * 4)))
        s.stance = s.aliases[STANCE_ALIAS]

    def u32(s, a): return struct.unpack('<I', s.read(a, 4))[0]
    def cstr(s, a, n=64):
        b = s.read(a, n); return b[:b.find(b'\0') if b'\0' in b else n].decode('latin1')
    def move(s, i): return s.lists['move'][0] + i * MOVE_SIZE
    def move_name(s, i): return s.cstr(s.u32(s.move(i)))
    def index(s, addr): return (addr - s.lists['move'][0]) // MOVE_SIZE
    def find(s, name):
        return next(i for i in range(s.lists['move'][1]) if s.move_name(i) == name)

    def recovery(s, i):
        """Adresse de l'entree 0x8000 (fin d'animation) de la liste d'annulation du coup i."""
        a = s.u32(s.move(i) + MOVE_CANCEL)
        for k in range(512):
            if s.u32(a + k * CANCEL_SIZE) == 0x8000: return a + k * CANCEL_SIZE
        raise ValueError(f'coup {i} : pas d entree 0x8000')


def ram_reader(path):
    """read() sur un relevé de RAM (ram.bin, 24 Mo depuis RAM_BASE)."""
    data = open(path, 'rb').read()
    return lambda a, n: data[a - RAM_BASE:a - RAM_BASE + n]
