import json, sys

with open(sys.argv[1]) as f:
    data = json.load(f)

if not data.get('ok'):
    print('Error:', data)
    sys.exit(1)

entries = data.get('entries', [])
print(f'Total writes: {data["total"]}, showing {len(entries)}')

for e in entries[-150:]:
    addr = e['addr']
    val = e.get('new', e.get('val', '?'))
    func = e.get('func', '?')
    ra = e.get('ra', '?')
    seq = e.get('seq', 0)
    label = ''
    if '7514' in addr: label = ' [STATE]'
    elif '7550' in addr: label = ' [BUF0]'
    elif '7554' in addr: label = ' [BUF1]'
    elif '7528' in addr: label = ' [HDL0]'
    elif '752C' in addr: label = ' [HDL1]'
    elif '7508' in addr: label = ' [SEC0]'
    elif '750C' in addr: label = ' [SEC1]'
    elif '7500' in addr: label = ' [PORT0]'
    elif '7504' in addr: label = ' [PORT1]'
    print(f'{seq:8d} {addr} = {val}{label}  func={func} ra={ra}')
