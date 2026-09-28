"""Print first 16 bytes of each on-disk card image."""
for path in ('dummy.0.mcr', 'dummy.1.mcr', 'card1.mcd', 'card2.mcd'):
    try:
        d = open(path, 'rb').read()[:16]
        print(f'{path:>15}: ' + ' '.join(f'{b:02X}' for b in d))
    except Exception as ex:
        print(f'{path}: ERR {ex}')
