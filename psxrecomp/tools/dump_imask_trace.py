#!/usr/bin/env python3
"""Dump I_MASK bit 7 trace from debug server."""
import json, sys, socket, time

def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 64
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(('localhost', 4370))
    s.sendall(('{"cmd":"imask_trace","count":%d}\n' % count).encode())
    time.sleep(0.5)
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

    print('bit7_sets=%d  bit7_clears=%d  total_writes=%d' % (
        data['bit7_sets'], data['bit7_clears'], data['total']))
    print()
    for e in data['entries']:
        b7s = ' +SIO' if e['b7s'] else ''
        b7c = ' -SIO' if e['b7c'] else ''
        exc = 'EXC' if e['exc'] else '   '
        old_v = int(e['old'], 0) if isinstance(e['old'], str) else e['old']
        new_v = int(e['new'], 0) if isinstance(e['new'], str) else e['new']
        func_v = int(e['func'], 0) if isinstance(e['func'], str) else e['func']
        print('old=0x%03X new=0x%03X func=0x%08X w=%d %s%s%s' % (
            old_v, new_v, func_v, e['w'], exc, b7s, b7c))

if __name__ == '__main__':
    main()
