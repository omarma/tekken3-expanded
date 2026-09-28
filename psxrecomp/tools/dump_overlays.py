#!/usr/bin/env python3
"""
dump_overlays.py — Extract executed overlay regions from a live runtime.

Queries overlay_dump (dirty_ram bitmap scan) and cd_read_log (CD DMA
transfer ring) to produce overlay_map.jsonl entries with:
  crc32      — CRC32 of the RAM bytes (for verification)
  load_addr  — physical RAM address where the overlay lives
  size       — byte count of the region
  start_lba  — disc LBA of the first sector of this overlay file

The start_lba lets extract_overlays.py seek directly to the correct disc
position without brute-force scanning the whole disc image.

Usage:
  python3 tools/dump_overlays.py [--port PORT] [--lo PHYS] [--dir DIR] [--out JSONL]

Defaults:
  port  4470
  lo    0x98000   (above main EXE text)
  dir   logs/SCUS-94236/overlays  (relative to cwd)
  out   logs/SCUS-94236/overlay_map.jsonl
"""

import socket, json, sys, os, argparse

def send_cmd(port, cmd, **kwargs):
    payload = {'id': 1, 'cmd': cmd}
    payload.update(kwargs)
    s = socket.create_connection(('127.0.0.1', port), timeout=10)
    s.sendall(json.dumps(payload).encode() + b'\n')
    data = b''
    s.settimeout(30.0)
    while True:
        chunk = s.recv(65536)
        if not chunk: break
        data += chunk
        try:
            json.loads(data.decode())
            break
        except Exception:
            pass
    s.close()
    return json.loads(data.decode())

def find_lba_for_region(cd_log, phys_addr, size):
    """Return the disc start_lba for an overlay region if known, else -1.

    Groups consecutive CD DMA entries (same setloc_lba, dest advancing by
    sector size) and returns the lba of the group whose dest range covers
    phys_addr for at least `size` bytes.
    """
    SECTOR = 2048
    entries = cd_log.get('entries', [])
    if not entries:
        return -1

    # Build file-load groups: consecutive entries where dest advances by 2048
    # and lba is the same (all sectors of one file share the SetLoc LBA).
    groups = []
    cur = None
    for e in entries:
        dest = int(e['dest'], 16)
        lba  = e['lba']
        sz   = e['size']
        if cur and cur['lba'] == lba and dest == cur['end']:
            cur['end']   += sz
            cur['total'] += sz
        else:
            if cur:
                groups.append(cur)
            cur = {'lba': lba, 'start': dest, 'end': dest + sz, 'total': sz}
    if cur:
        groups.append(cur)

    # Find a group whose start <= phys_addr and end >= phys_addr + size
    for g in groups:
        if g['start'] <= phys_addr and g['end'] >= phys_addr + size:
            # LBA offset for the exact start of the overlay within this file
            offset_sectors = (phys_addr - g['start']) // SECTOR
            return g['lba'] + offset_sectors
        # Partial overlap — return the group start LBA as best guess
        if g['start'] <= phys_addr < g['end']:
            offset_sectors = (phys_addr - g['start']) // SECTOR
            return g['lba'] + offset_sectors
    return -1

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', type=int, default=4470)
    ap.add_argument('--lo',   default='0x98000')
    ap.add_argument('--dir',  default='logs/SCUS-94236/overlays')
    ap.add_argument('--out',  default='logs/SCUS-94236/overlay_map.jsonl')
    args = ap.parse_args()

    os.makedirs(args.dir, exist_ok=True)
    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)

    print('Querying overlay_dump...')
    result = send_cmd(args.port, 'overlay_dump', lo=args.lo, dir=args.dir)
    if not result.get('ok'):
        print(f'ERROR: {result.get("error")}'); sys.exit(1)
    regions = result.get('regions', [])

    print('Querying cd_read_log...')
    cd_log = send_cmd(args.port, 'cd_read_log', tail=4096)

    print(f'Found {len(regions)} overlay region(s), {cd_log.get("total", 0)} CD DMA entries')

    # Load existing manifest to avoid duplicates
    existing = set()
    if os.path.exists(args.out):
        with open(args.out, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                    existing.add((e.get('crc32'), e.get('load_addr')))
                except Exception:
                    pass

    new_count = 0
    with open(args.out, 'a', encoding='utf-8') as f:
        for r in regions:
            key = (r['crc32'], r['addr'])
            phys_addr = int(r['addr'], 16)

            lba = find_lba_for_region(cd_log, phys_addr, r['size'])
            lba_str = f'0x{lba:X}' if lba >= 0 else 'unknown'

            if key in existing:
                print(f'  skip  {r["addr"]}  {r["size"]:>8} bytes  lba={lba_str}  (already logged)')
                continue

            entry = {
                'crc32':      r['crc32'],
                'load_addr':  r['addr'],
                'size':       r['size'],
                'start_lba':  lba_str,
            }
            f.write(json.dumps(entry) + '\n')
            existing.add(key)
            new_count += 1
            print(f'  new   {r["addr"]}  {r["size"]:>8} bytes  lba={lba_str}  crc32={r["crc32"]}')

    print(f'\n{new_count} new overlay(s) appended to {args.out}')

if __name__ == '__main__':
    main()
