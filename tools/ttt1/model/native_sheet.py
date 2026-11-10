#!/usr/bin/env python3
"""Planche des modeles TTT1 (borne Tag) des natifs de Tekken 3 (F32, etape E0).

Chaque emplacement TTT1 d'un natif est rendu hors jeu, tel quel (modele 3DMK et
textures de la ROM, sans conversion PS1), dans la premiere image de la garde
(animation d'attente) de son propre moveset TTT1, de face et de trois-quarts.

    python tools/ttt1/model/native_sheet.py [--out workspace/f32-e0] [--only 9]

Sorties (workspace/, ignore par git : donnees du jeu, ne rien publier) :
  <out>/slot-<emplacement>.png      face | trois-quarts
  <out>/<natif>.png                 une planche par natif, l'emplacement sous chaque image
  <out>/slots.json                  table des emplacements (index, variante, nom, archives)
"""
import argparse, json, math, struct, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'tools/ttt1/model'), str(ROOT / 'tools/ttt1'), str(ROOT / 'tools')]
import extract as E, rom_ram as R, motion as MO
import simulate as SM
from fmt import row, nrows, block, parse_b, prim_verts, parse_c_ttt1
from tex import vram_from_tims, page_image, PAL_Y
from convert import ttt1_part_row

# Natifs T3 presents dans TTT1 (index de personnage TTT1) ; Gon, Dr. B et les soldats n'y sont pas.
NATIVES = list(range(17)) + [18, 20]
PART_BONE = [0, 1, 11, 12, 13, 14, 15, 16, 17, 3, 4, 5, 6, 7, 8, 9, 10, 2]     # 0x8001A074, parties 0..17
MAIN_ROW = {ttt1_part_row(p): p for p in range(1, 18)}
# Seconds maillages : meme os que leur partie (torse 1, bassin 4, tete 21) ; leur mot 6 ne la donne pas.
SAME = {2: 1, 3: 1, 5: 4, 6: 4, 22: 21, 23: 21}


def rotation(angle, neg=True):
    """Meme formule que tools/ttt1/anim_model.rotation, en flottants."""
    s, c = [], []
    for i in range(3):
        a = int(angle[i]) & 0xffff
        if neg and i < 2: a = (-a) & 0xffff
        t = a / 65536 * 2 * math.pi; s.append(math.sin(t)); c.append(math.cos(t))
    a, b = c[0] * c[2], c[0] * s[2]; d, e = s[0] * c[2], s[0] * s[2]
    return np.array([[c[1] * c[2], d * s[1] - b, e + a * s[1]],
                     [c[1] * s[2], a + e * s[1], b * s[1] - d],
                     [-s[1], s[0] * c[1], c[0] * c[1]]])


# Le corps contre lequel butent les accessoires a ressort : toutes les lignes sauf la tete (21..23)
# et les accessoires (24..29), assemblees dans la pose. Le corps est ouvert au cou (tete exclue) :
# pas de tir de rayons ; un point est dedans s'il est derriere le triangle le plus proche (centre),
# normale orientee vers l'exterieur (signe majoritaire par rapport au centre du corps).
BODY_ROWS = range(1, 21)
DEBUG = False
SKIN = 4.0     # tolerance : un point pose sur la surface n'est pas dedans
TOUCH = 0.05   # part des points de l accessoire toleree dans le corps (racine contre la nuque)


def inside(tri):
    """tri : (n, 3, 3) triangles du corps -> fonction P (k, 3) -> booleens (k,)."""
    c = tri.mean(1); n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1), 1e-9)[:, None]
    if ((c - c.mean(0)) * n).sum(1).mean() < 0: n = -n
    def test(P):
        j = ((P[:, None, :] - c[None]) ** 2).sum(2).argmin(1)
        return ((P - c[j]) * n[j]).sum(1) < -SKIN
    return test


def hang(R, axis, k=1.0):
    """R suivi d'une rotation qui amene R @ axis vers le bas (y croissant), sur une part k de l'angle."""
    d = R @ axis; n = np.linalg.norm(d)
    if n < 1e-6: return R
    d = d / n; g = np.array([0., 1., 0.]); v = np.cross(d, g); s = np.linalg.norm(v)
    if s < 1e-9: return R
    u = v / s; t = k * math.atan2(s, float(d @ g))
    K = np.array([[0, -u[2], u[1]], [u[2], 0, -u[0]], [-u[1], u[0], 0]])
    return (np.eye(3) + math.sin(t) * K + (1 - math.cos(t)) * K @ K) @ R


def world(m, pose, swing=(), k=1.0):
    """{ligne TTT1: (R, T)} : parties 1..17 animees par la pose (57 canaux), les autres lignes
    (seconds maillages, os d'accessoires) rattachees a leur partie avec leur rotation de repos.
    Os d'accessoires a ressort (swing : os TTT1 18..23) : au repos, la borne les laisse pendre ;
    on les fait tomber vers le bas (axe = barycentre de leurs sommets) d'une part k de l'angle ;
    triangles() cherche le plus grand k ou ils ne traversent pas le corps."""
    def own(r):
        a = SM.vlist(m, r, True) if r < nrows(m) and row(m, r)[10] else None
        return np.array([v[:3] for v in a['verts']], float) if a and a['verts'] else None
    loc = {}
    for b in range(18):
        Rb = rotation(pose[3 + b * 3:6 + b * 3])
        if b == 0: Rb[1:, :] *= -1
        loc[b] = Rb
    W = {0: (loc[0], np.zeros(3))}
    def get(r):
        if r in W: return W[r]
        if r in SAME:
            W[r] = get(SAME[r]); return W[r]
        w = row(m, r); p = w[6] & 0xff if w[6] >= 0 else 0
        pr = ttt1_part_row(p)
        if pr == r or pr >= nrows(m): pr = 0
        Rp, Tp = get(pr)
        T = Tp + Rp @ np.array(w[3:6], float)
        Rl = loc[PART_BONE[MAIN_ROW[r]]] if r in MAIN_ROW else rotation(w[7:10], neg=False)
        Rw = Rp @ Rl
        if r - 6 in swing and k and own(r) is not None:
            Rw = hang(Rw, own(r).mean(0), k)
        W[r] = (Rw, T); return W[r]
    for r in range(nrows(m)): get(r)
    return W


def triangles(m, tex, pose, swing=()):
    order = [(r, None) for r in range(1, nrows(m)) if row(m, r)[10] and row(m, r - 1)[12] > 2]
    def build(W):
        return SM.assemble(order, m, ttt1=True, xform=lambda r: ((W[r][0] * 4096).tolist(), W[r][1].tolist(), 0, 0, 1))
    def tris_of(geo, rows):
        out = []
        for r, _ in order:
            if r not in rows or row(m, r)[1] <= 2: continue
            for k, fl in enumerate(parse_b(block(m, row(m, r)[1]))):
                for rec in fl:
                    P = [geo[r][s] for s in prim_verts(k, rec)]
                    for a, b, c in ([(0, 1, 2)] if k in (0, 2) else [(0, 1, 2), (1, 3, 2)]):
                        if None not in (P[a], P[b], P[c]): out.append((P[a], P[b], P[c]))
        return np.array(out, float).reshape(-1, 3, 3)
    geo = build(world(m, pose))
    rows = {b + 6 for b in swing}
    if rows and len(tris_of(geo, rows)):
        # Chute des accessoires a ressort : la plus grande part k ou leurs triangles (sommets, milieux
        # d'aretes, centres) n'entrent pas plus dans le corps qu'au repos.
        body = inside(tris_of(geo, BODY_ROWS))
        def probe(t):
            return np.concatenate([t.reshape(-1, 3), (t + t[:, [1, 2, 0]]).reshape(-1, 3) / 2, t.mean(1)])
        rest = int(body(probe(tris_of(geo, rows))).sum())
        for k in np.linspace(1, 0, 21)[:-1]:
            g = build(world(m, pose, swing, k))
            n_in = int(body(probe(tris_of(g, rows))).sum())
            if DEBUG: print("k", round(k, 2), n_in, "repos", rest, "sur", len(probe(tris_of(g, rows))))
            if n_in <= rest + TOUCH * len(probe(tris_of(g, rows))): geo = g; break
    vram = vram_from_tims(tex); texid = {}; tris = []
    for r, _ in order:
        w = row(m, r)
        if w[1] <= 2 or w[2] <= 2: continue
        cp = parse_c_ttt1(block(m, w[2])); j = 0
        for k, fl in enumerate(parse_b(block(m, w[1]))):
            for rec in fl:
                _, mat, uv = cp[j]; j += 1
                key = (mat >> 16, mat & 0xffff); texid.setdefault(key, len(texid))
                P = [geo[r][s] for s in prim_verts(k, rec)]
                for a, b, c in ([(0, 1, 2)] if k in (0, 2) else [(0, 1, 2), (1, 3, 2)]):
                    if None in (P[a], P[b], P[c]): continue
                    tris.append((texid[key], P[a], P[b], P[c], uv[a], uv[b], uv[c]))
    pages = [np.array(page_image(vram, pg, cl, PAL_Y)) for (pg, cl), _ in sorted(texid.items(), key=lambda x: x[1])]
    return tris, pages


def render(tris, pages, yaw, scale, size, center, ss=2):
    """Rendu logiciel z-buffer, textures, alpha 0 = trou ; yaw en degres autour de l'axe vertical."""
    Wd, Hd = size[0] * ss, size[1] * ss
    P = np.array([[t[1], t[2], t[3]] for t in tris], float) - center
    UV = np.array([[t[4], t[5], t[6]] for t in tris], float)
    a = math.radians(yaw); Ry = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
    P = P @ Ry.T
    X = P[:, :, 0] * scale * ss + Wd / 2; Y = P[:, :, 1] * scale * ss + Hd * 0.5; Z = P[:, :, 2]
    img = np.zeros((Hd, Wd, 4), np.uint8); zb = np.full((Hd, Wd), 1e18)
    for i, t in enumerate(tris):
        x, y, z = X[i], Y[i], Z[i]
        area = (x[1] - x[0]) * (y[2] - y[0]) - (x[2] - x[0]) * (y[1] - y[0])
        if abs(area) < 1e-9: continue
        x0, x1 = int(max(0, np.floor(x.min()))), int(min(Wd - 1, np.ceil(x.max())))
        y0, y1 = int(max(0, np.floor(y.min()))), int(min(Hd - 1, np.ceil(y.max())))
        if x1 < x0 or y1 < y0: continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + .5, np.arange(y0, y1 + 1) + .5)
        w0 = ((x[1] - gx) * (y[2] - gy) - (x[2] - gx) * (y[1] - gy)) / area
        w1 = ((x[2] - gx) * (y[0] - gy) - (x[0] - gx) * (y[2] - gy)) / area
        w2 = 1 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not inside.any(): continue
        zz = w0 * z[0] + w1 * z[1] + w2 * z[2]
        u = np.clip(w0 * UV[i, 0, 0] + w1 * UV[i, 1, 0] + w2 * UV[i, 2, 0], 0, 255).astype(int)
        v = np.clip(w0 * UV[i, 0, 1] + w1 * UV[i, 1, 1] + w2 * UV[i, 2, 1], 0, 255).astype(int)
        tx = pages[t[0]][v, u]
        ok = inside & (tx[..., 3] > 0) & (zz < zb[y0:y1 + 1, x0:x1 + 1])
        zb[y0:y1 + 1, x0:x1 + 1][ok] = zz[ok]
        img[y0:y1 + 1, x0:x1 + 1][ok] = tx[ok]
    im = Image.fromarray(img, 'RGBA')
    return im.resize(size, Image.LANCZOS) if ss > 1 else im


def swinging(boot, c, v, slot):
    """Os d'accessoires TTT1 (18..23) a ressort pour cet emplacement (tools/ttt1/accessories.py)."""
    import accessories
    return set(accessories.blocks(R.select(boot, c, v), slot))


def idle_pose(boot, bank, c, v):
    ram = R.select(boot, c, v)
    aliases = struct.unpack_from('<5515I', ram, MO.ALIASES)
    src = struct.unpack_from('<13I', ram, aliases[MO.IDLE_ALIAS] & 0x3FFFFF)[0]
    return MO.decode(bank, src, 0)


def font(n):
    for f in ('C:/Windows/Fonts/segoeuib.ttf', 'C:/Windows/Fonts/arialbd.ttf'):
        try: return ImageFont.truetype(f, n)
        except OSError: pass
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--regions', type=Path, default=Path('C:/TekkenProject/Tekken3Recompiled/workspace/ttt1-import/ttt1'),
                    help='regions ROM reconstruites (bankedroms.bin, maincpu_rom.bin)')
    ap.add_argument('--out', type=Path, default=ROOT / 'workspace/f32-e0')
    ap.add_argument('--only', type=int, nargs='*', help='index TTT1 des natifs a rendre')
    ap.add_argument('--size', type=int, nargs=2, default=(340, 480), help='taille d\'une vue')
    ap.add_argument('--ss', type=int, default=3, help='sur-echantillonnage')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    bank, main, game = R.load(a.regions); boot = R.boot(a.regions)
    rows = E.characters(game, {'table': bank[E.ANIM_TABLE:E.ANIM_TABLE + 8 * E.NANIM]})
    rows = [r for r in rows if r[0] in (a.only or NATIVES)]
    (a.out / 'slots.json').write_text(json.dumps([dict(index=r[0], variant=r[1], name=r[2], slot=r[3], tex=r[4],
                                                       model=r[5], moveset=r[6]) for r in rows], indent=1))
    rom = E.Rom(bank, main); files = {}
    for i, n, ad, sz in E.archives(game, rom):
        if i in (23, 24, 26, 27): files['%02d/%03d' % (i, n)] = (i, ad, sz)
    def get(key):
        i, ad, sz = files[key]; d = rom(ad, sz)
        return E.lz(d, 0) if i in E.PACKED and d else d
    done = {}; built = []
    for c, v, name, slot, tex, model, *_ in rows:
        m, t = get(model), get(tex)
        tris, pages = triangles(m, t, idle_pose(boot, bank, c, v), swinging(boot, c, v, slot))
        Q = np.array([p for tr in tris for p in tr[1:4]], float)
        built.append((c, v, name, slot, tris, pages, Q))
    # une echelle par natif (la meme pour tous ses emplacements) : son plus grand modele remplit la vue
    fit = {}
    for c, v, name, slot, tris, pages, Q in built:
        lo, hi = Q.min(0), Q.max(0); mid = (lo + hi) / 2
        rad = np.hypot(Q[:, 0] - mid[0], Q[:, 2] - mid[2]).max()
        s = min(0.9 * a.size[1] / (hi[1] - lo[1]), 0.47 * a.size[0] / rad)
        fit[c] = min(fit.get(c, s), s)
    for c, v, name, slot, tris, pages, Q in built:
        SCALE = fit[c]; lo, hi = Q.min(0), Q.max(0); center = (lo + hi) / 2
        center[1] = hi[1] - 0.45 * a.size[1] / SCALE                 # pieds sur la meme ligne
        views = [render(tris, pages, y, SCALE, tuple(a.size), center, a.ss) for y in (0, -45)]
        im = Image.new('RGBA', (a.size[0] * 2, a.size[1]), (0, 0, 0, 0))
        im.paste(views[0], (0, 0)); im.paste(views[1], (a.size[0], 0))
        im.save(a.out / f'slot-{slot:03d}.png')
        done.setdefault(c, []).append((v, name, slot, im, hi[1] - lo[1]))
        print(c, v, name, slot, len(tris), 'triangles, hauteur', int(hi[1] - lo[1]), flush=True)
    # planches : une par natif, deux vues par emplacement, l'emplacement dessous
    f1, f2 = font(26), font(20)
    for c, items in done.items():
        w1 = a.size[0] * 2; pad = 12
        sheet = Image.new('RGB', (len(items) * (w1 + pad) + pad, a.size[1] + 120), (34, 36, 40))
        d = ImageDraw.Draw(sheet)
        for k, (v, name, slot, im, h) in enumerate(items):
            x = pad + k * (w1 + pad)
            d.rectangle([x, 50, x + w1 - 1, 50 + a.size[1] - 1], fill=(58, 62, 70))
            sheet.paste(im, (x, 50), im)
            d.text((x + 6, 10), name, font=f1, fill=(240, 240, 240))
            lab = f'emplacement {slot}  (variante {v})'
            d.text((x + 6, 60 + a.size[1]), lab, font=f2, fill=(255, 210, 90))
        sheet.save(a.out / f'native-{c:02d}-{items[0][1].lower().replace(" ", "")}.png')


if __name__ == '__main__':
    main()
