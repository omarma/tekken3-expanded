#!/usr/bin/env python3
"""Watch a game the user plays (build with PSX_DEBUG_TOOLS, --debug-port):
each time player 1 plays one of the given records of the guest's pack, log
per active frame how far its hitting capsules pass from player 2's spheres,
player 2's record and height, and whether damage was dealt.

  python3 tools/ttt1/watch_moves.py <guest> <port> <game log> <record,...> [--out file.jsonl]

The records are pack numbers (Kazuya: 268 Electric, 276..278 Spinning
Demon). The game log gives where the guest's records are (installed P1
alias table ... records=...). Stop with Ctrl-C.
"""
import json, re, struct, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import moveset_check as M
sys.path.insert(0, str(M.ROOT / 'psxrecomp/tools'))
import debug_client

PRACTICE_DAMAGE = 0x800b8ba2                     # damage applied by the last hit


def main():
    a = sys.argv[1:]
    out = Path(a[a.index('--out') + 1]) if '--out' in a else M.OUT / f'{a[0]}-watch.jsonl'
    guest, port, log = a[0], int(a[1]), Path(a[2])
    watched = [int(x) for x in a[3].split(',')]
    pack = M.guest_pack(guest)
    q = lambda r: debug_client.query('127.0.0.1', port, r)
    rd = lambda addr, n: bytes.fromhex(q(dict(cmd='read_ram', addr=f'{addr:08x}', len=n))['hex'])
    u32 = lambda addr: int.from_bytes(rd(addr, 4), 'little')
    at = lambda f, addr, n: (lambda r: bytes.fromhex(r['hex']) if r.get('ok') else None)(
        q(dict(cmd='read_frame_ram', frame=int(f), addr=f'{addr:08x}', len=n)))
    records = None
    print('waiting for the guest in a fight...', flush=True)
    while records is None:
        m = re.findall(r'installed P1 alias table.*records=([0-9A-F]+)', log.read_text(errors='replace'))
        if m: records = int(m[-1], 16)
        else: time.sleep(1)
    name = lambda v: (v - records) // 56 if records <= v < records + 56 * pack.count and (v - records) % 56 == 0 else f'{v:08x}'
    for slot, addr in enumerate((M.ACTOR[0], M.ACTOR[0] + M.CAPSULES, M.ACTOR[1] + M.SPHERES, M.ACTOR[1] + M.SPHERES + 128)):
        q(dict(cmd='set_snapshot', slot=slot, addr=f'{addr:08x}'))
    print(f'watching records {watched} (pack at {records:08x}) -> {out}', flush=True)
    last, p2_by_frame, start, electric = None, {}, None, None
    facings = []                                  # (frame, facing, p1 record, p2 record)
    with out.open('a') as log_out:
        while True:
            try:
                f = q(dict(cmd='frame'))['frame']
                p1 = name(u32(M.ACTOR[0] + M.RECORD))
                p2 = u32(M.ACTOR[1] + M.RECORD)
                x2, y2, z2 = struct.unpack('<3i', rd(M.ACTOR[1], 12))
                p2_by_frame[f] = (name(p2) if isinstance(name(p2), int) else f'{p2:08x}', y2, (x2, z2))
            except (ConnectionError, OSError, KeyError):
                print('game closed', flush=True); return
            # Player 1 turning fast (over 30 degrees within 8 frames): which
            # moves were playing (the user saw the guest spin on some moves).
            face = int.from_bytes(rd(M.ACTOR[0] + 0x2c, 2), 'little')
            facings.append((f, face, p1, p2_by_frame[f][0]))
            facings = [x for x in facings if f - x[0] <= 8]
            turn = ((face - facings[0][1] + 0x8000) & 0xffff) - 0x8000
            if abs(turn) > 0x1555 and f - facings[0][0] >= 1:
                moves = sorted({str(x[2]) for x in facings}); theirs = sorted({str(x[3]) for x in facings})
                line = f"{time.strftime('%H:%M:%S')} ROTATION de {turn * 360 / 65536:+.0f}° en {f - facings[0][0]} images | J1 {'/'.join(moves)} | J2 {'/'.join(theirs)}"
                print(line, flush=True); log_out.write(json.dumps(dict(turn=line)) + '\n'); log_out.flush()
                facings = [facings[-1]]
            if p1 != last:
                if p1 == 268: electric = f
                if p1 in watched and start is None: start = (f, p1)
                if start and p1 not in watched:
                    report(start, f, electric, pack, records, at, p2_by_frame, name, log_out, rd)
                    start = None
                last = p1
            if len(p2_by_frame) > 2000: p2_by_frame = dict(list(p2_by_frame.items())[-600:])
            time.sleep(.004)


def report(start, end, electric, pack, records, at, p2_by_frame, name, log_out, rd):
    """The frames of one run of watched moves, read back from the RAM ring."""
    rows = []
    for f in range(start[0] - 2, end + 1):
        a = at(f, M.ACTOR[0], 0x5c)
        if a is None: continue
        rec = name(struct.unpack_from('<I', a, M.RECORD)[0])
        n = struct.unpack_from('<H', a, M.FRAME)[0]
        if not isinstance(rec, int): continue
        r = pack.records[rec]
        raw = rd(records + rec * 56, 56)
        first, last = raw[45], raw[46]
        cap = at(f, M.ACTOR[0] + M.CAPSULES, 48) or b''
        sph = (at(f, M.ACTOR[1] + M.SPHERES, 128) or b'') + (at(f, M.ACTOR[1] + M.SPHERES + 128, 128) or b'')
        best = None
        if first <= n <= last and len(cap) == 48:
            for k in range(2):
                seg = struct.unpack_from('<6i', cap, k * 24)
                if seg == (0,) * 6: continue
                for j in range(len(sph) // 20):
                    c = struct.unpack_from('<3i', sph, j * 20)
                    rad = struct.unpack_from('<h', sph, j * 20 + 12)[0]
                    gap = round(M.segment_distance(seg[:3], seg[3:], c) - rad)
                    if best is None or gap < best[0]: best = (gap, k, j, c[1])
        p2 = p2_by_frame.get(f) or p2_by_frame.get(f - 1) or ('?', None, None)
        x1, _, z1 = struct.unpack_from('<3i', a, 0)
        dist = round(((p2[2][0] - x1) ** 2 + (p2[2][1] - z1) ** 2) ** .5) if p2[2] else None
        rows.append(dict(frame=f, record=rec, move_frame=n, active=first <= n <= last,
                         closest=best, p2=p2[0], p2_y=p2[1], distance=dist,
                         sweep=round(sum((struct.unpack_from('<6i', cap, 0)[m] - struct.unpack_from('<6i', cap, 0)[m + 3]) ** 2
                                         for m in range(3)) ** .5) if len(cap) == 48 else None))
    active = [x for x in rows if x['active']]
    gaps = [x['closest'][0] for x in active if x['closest']]
    entry = dict(time=time.strftime('%H:%M:%S'), first=start[1], since_electric=start[0] - electric if electric else None,
                 records=sorted({x['record'] for x in rows}), closest=min(gaps) if gaps else None,
                 hit=any(g <= 0 for g in gaps), frames=rows)
    log_out.write(json.dumps(entry) + '\n'); log_out.flush()
    by_rec = {}
    for x in active:
        if x['closest']: by_rec.setdefault(x['record'], []).append(x['closest'][0])
    p2 = [x['p2'] for x in rows]
    print(f"{entry['time']} {entry['records']} {start[0] - electric if electric else '-':>4} images après l'Electric | "
          + ' '.join(f"{k}: plus près {min(v):+d}" for k, v in sorted(by_rec.items()))
          + f" | J2 {p2[0]}→{p2[-1]} | distance au départ {rows[0]['distance'] if rows else '?'}", flush=True)


if __name__ == '__main__':
    main()
