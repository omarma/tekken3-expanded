#!/usr/bin/env python3
"""B165: a DR follow-up on the same animation must go on with it, not start it over.

    python tools/test_b165_dr_goes_on.py <catalogue> [--name Jin]

<catalogue> is a TTT1 catalogue the DR import wrote into (mods/ttt1 of an install, or dr_setup.py's
--roster). In <Name>-DR-combat.jmv, every record the DR import added (past <Name>-TTT1-combat.jmv's
records) is read: an entry (not the 0xC000 end) to a record whose clip is the same animation up to
the frame it is entered at, with a transition Tekken 3 starts at frame 1 (fighter_move_advance: 0, 6,
9-15), where Tekken 3 would let it go on (the frame not past the target's last active frame), is a
fault: Jin played his Spinning Flare Kick (4~3, Bmt_hasai -> Bmt_hasai_D on a fighter down) twice.
Also a record cut short on the animation whose end (0xC000) starts it over without an entry going
on before it (Co_s_tlk00 -> Co_s_tlk01). Exit 1 with the faults listed; dr_pack.goes_on() fixes both.
"""
import argparse, struct, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'ttt1'))
from pack_edit import Pack  # noqa: E402

BASE_ID = 8192
STARTING_OVER = (0, 6, 9, 10, 11, 12, 13, 14, 15)


def clip(p, k):
    off = p.word(k, 0) - p.data_at
    if off < 0: return None
    head = struct.unpack_from('<I', p.data, off)[0]
    if head & 0xffffff00 != 0x4a554e00: return None
    return [bytes(p.data[off + 8 + 114 * i:off + 8 + 114 * (i + 1)]) for i in range(head & 0xff)]


def faults(dr, first):
    out, clips = [], {}
    def c(k):
        if k not in clips: clips[k] = clip(dr, k)
        return clips[k]
    for k in range(first, len(dr.records)):
        a = c(k)
        if not a: continue
        entries = dr.cancels(k)
        for e in entries:
            d, at = e[3] - BASE_ID, e[7]
            if e[4] & 0x3f not in STARTING_OVER or d == k or not 0 <= d < len(dr.records): continue
            b = c(d)
            if not b: continue
            rec = dr.records[d]
            if e[0] == 0xc000:
                # A record cut short on the target's animation, its end starting it over, with no entry
                # going on before it (Co_s_tlk00 -> Co_s_tlk01).
                at = len(a) - 1
                if not 1 < len(a) < len(b) or b[:len(a)] != a or any(x[0] != 0xc000 and x[3] == e[3] for x in entries):
                    continue
            elif not 1 < at < min(len(a), len(b)) or a[:at + 1] != b[:at + 1]: continue
            if rec[45] and at > rec[46]: continue
            out.append((k, d, e))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('catalogue', type=Path)
    ap.add_argument('--name', default='Jin')
    a = ap.parse_args()
    dr = Pack((a.catalogue / f'{a.name}-DR-combat.jmv').read_bytes())
    first = len(Pack((a.catalogue / f'{a.name}-TTT1-combat.jmv').read_bytes()).records)
    bad = faults(dr, first)
    for k, d, e in bad:
        print(f'record {k} -> {d} at frame {e[7]}: transition {e[4] & 0x3f} starts the same animation over ({e})')
    print(f'{a.name}-DR: {len(dr.records) - first} records of the DR import, {len(bad)} starting their animation over')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
