#!/usr/bin/env python3
"""Check memory card file contents."""
import sys

def main():
    for fname in ['card1.mcd', 'card2.mcd']:
        try:
            data = open(fname, 'rb').read()
        except FileNotFoundError:
            print('%s: NOT FOUND' % fname)
            continue

        print('%s: %d bytes, header=%s' % (fname, len(data), data[0:2]))

        for i in range(1, 16):
            off = i * 128
            status = data[off]
            name_bytes = data[off+10:off+10+20]
            name = name_bytes.split(b'\x00')[0].decode('ascii', 'replace')
            if status != 0xA0:
                print('  Slot %2d: status=0x%02X name=%s (USED)' % (i, status, name))
            else:
                print('  Slot %2d: FREE' % i)

if __name__ == '__main__':
    main()
