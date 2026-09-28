#!/usr/bin/env python3
"""Controle du rangement des textures : pour chaque coin de polygone, couleur lue
dans l'atlas TTT1 d'origine contre couleur lue dans l'atlas PS1 range, via les UV
du modele converti. Usage : check_texpack.py <ttt1.3dm> <ttt1.tex> <ps1.3dm> <ps1.tim>"""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fmt import *
import texpack

def vram(tims):
    V = {}
    for t in tims:
        for r in range(t['h']):
            for c in range(t['w']): V[(t['x'] + c, t['y'] + r)] = t['pix'][r * t['w'] + c]
        px, py, pw, ph, pd = t['pal']
        for c in range(pw): V[('p', px + c, py)] = pd[c]
    return V

def texel(V, mode, clut, X, sub, Y):
    hw = V.get((X, Y))
    if hw is None: return None
    idx = (hw >> (4 * sub)) & 15 if mode == 0 else (hw >> (8 * sub)) & 255
    c = V.get(('p', (clut & 63) * 16 + idx, clut >> 6))
    return None if c is None else ((c & 31) * 8, ((c >> 5) & 31) * 8, ((c >> 10) & 31) * 8)

def main(t3dm, ttex, p3dm, ptim):
    T, P = load(t3dm), load(p3dm)
    A, B = vram(texpack.read_tims(open(ttex, 'rb').read())), vram(texpack.read_tims(open(ptim, 'rb').read()))
    ta = [x for r in range(nrows(T)) if row(T, r)[2] > 2 for x in parse_c_ttt1(block(T, row(T, r)[2]))]
    pb = [x for r in range(nrows(P)) if row(P, r)[2] > 2 for x in parse_c_ps1(block(P, row(P, r)[2]))]
    if len(ta) != len(pb): print('nombre de polygones different', len(ta), len(pb))
    bad = n = 0; worst = 0
    for (k, mat, uv), (k2, pm, uv2) in zip(sorted(ta, key=lambda p: p[0]), sorted(pb, key=lambda p: p[0])):
        page, clut = mat >> 16, mat & 0xffff; mode = (page >> 7) & 3; ppw = 4 >> mode
        pmode = 1 if pm & 0x8000 else 0; pclut = pm & 0x7fff; pppw = 4 >> pmode
        for (u, v), (u2, v2) in zip(uv, uv2):
            a = texel(A, mode, clut, (page & 15) * 64 + u // ppw, u % ppw, v)
            X2 = u2 // pppw; Y2 = v2
            if Y2 >= 128: X2 += 64; Y2 -= 128                   # depli de la bande costume
            b = texel(B, pmode, pclut, X2, u2 % pppw, Y2)
            n += 1
            if a is None or b is None: bad += 1; continue
            d = max(abs(x - y) for x, y in zip(a, b)); worst = max(worst, d)
            if d > 64: bad += 1
    print(f'{n} coins, {bad} ecarts > 64 ou hors image, pire ecart {worst}')
    return bad

if __name__ == '__main__':
    sys.exit(1 if main(*sys.argv[1:5]) else 0)
