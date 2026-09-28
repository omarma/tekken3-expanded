"""Decode CTRL/TX_DATA writes around a byte_seq window. Args: bs_min bs_max."""
import sys, json, re

if len(sys.argv) != 3:
    print('usage: decode_ctrl_window.py BS_MIN BS_MAX', file=sys.stderr); sys.exit(1)
bs_min, bs_max = int(sys.argv[1]), int(sys.argv[2])

txt = sys.stdin.read()
m = re.search(r'\{.*\}', txt, re.S)
if not m:
    print('parse fail'); sys.exit(1)
j = json.loads(m.group(0))
ents = j.get('entries', [])
hits = [e for e in ents if bs_min <= e.get('byte_seq', 0) <= bs_max]
print(f'(found {len(hits)} of {len(ents)} entries with byte_seq in [{bs_min},{bs_max}])')
print('  seq    pc         func       reg       value       byte_seq')
for e in hits:
    val = int(e['value'], 16)
    a = e['addr']
    if a.endswith('1040'):
        kind, meaning = 'TX_DATA', f'tx={val:#04x}'
    elif a.endswith('104A'):
        kind = 'CTRL'
        bits = []
        if val & 0x1:    bits.append('TX_EN')
        if val & 0x2:    bits.append('SELECT')
        if val & 0x4:    bits.append('RX_EN')
        if val & 0x10:   bits.append('ACK')
        if val & 0x40:   bits.append('RESET')
        if val & 0x1000: bits.append('ACK_IRQ_EN')
        if val & 0x2000: bits.append('SLOT')
        meaning = f'{val:#06x} = {"|".join(bits) if bits else "NONE"}'
    else:
        kind, meaning = a[-4:], e['value']
    print(f"  {e['seq']:>5} {e['pc']} {e['func']} {kind:>7} {meaning:30s} bs={e['byte_seq']}")
