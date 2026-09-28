#!/usr/bin/env python3
"""Dump SIO trace from debug server."""
import json, sys, socket, time

def to_int(v):
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        return int(v, 0)
    return int(v)

def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 256
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(('localhost', 4370))
    s.sendall(('{"cmd":"sio_trace","count":%d}\n' % count).encode())
    time.sleep(1.0)
    buf = b''
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
        try:
            data = json.loads(buf)
            break
        except json.JSONDecodeError:
            continue
    s.close()
    for e in data.get('entries', []):
        abort = ' <<ABORT>>' if e.get('abort') or e.get('was_abort') else ''
        exc = 'EXC' if e.get('in_exc', 0) else '   '
        ctr = to_int(e.get('ctr', 0))
        func = to_int(e['func'])
        # Only show card bytes (func >= 0x5000) or bytes near them
        print('seq=%6d tx=0x%02X rx=0x%02X mc=%d->%d dev=%d->%d ctrl=0x%04X func=0x%08X ctr=%d %s%s' % (
            to_int(e['seq']), to_int(e['tx']), to_int(e['rx']),
            to_int(e['mc_pre']), to_int(e['mc_post']),
            to_int(e['dev_pre']), to_int(e['dev_post']),
            to_int(e['ctrl']), func,
            ctr, exc, abort))

if __name__ == '__main__':
    main()
