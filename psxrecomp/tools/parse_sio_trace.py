#!/usr/bin/env python3
"""Parse sio_trace JSON output and display human-readable table."""
import json
import sys

MC_NAMES = {
    0:'IDLE', 1:'CMD', 2:'ID1', 3:'ID2', 4:'ADDR_MSB', 5:'ADDR_LSB',
    6:'R_ACK1', 7:'R_ACK2', 8:'R_DATA', 9:'R_CHK', 10:'R_END',
    11:'W_DATA', 12:'W_CHK', 13:'W_ACK1', 14:'W_ACK2', 15:'W_END',
    16:'GID1', 17:'GID2', 18:'GID3', 19:'GID4'
}
DEV_NAMES = {0:'NONE', 1:'PAD', 2:'MC'}

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/sio_trace.json'
    filt = sys.argv[2] if len(sys.argv) > 2 else 'all'  # 'all', 'mc', 'abort'

    with open(path) as f:
        data = json.load(f)

    print(f"Total SIO bytes: {data['total']}, Showing: {data['count']}")
    print(f"{'SEQ':>7} {'TX':>4} {'RX':>4} {'DEV':>10} {'MC_STATE':>20} {'CTRL':>6} {'FUNC':>10} {'IRQ':>3} {'FLAGS'}")
    print("-" * 90)

    for e in data['entries']:
        # Handle both int and hex-string formats
        tx_val = int(e['tx'], 16) if isinstance(e['tx'], str) else e['tx']
        rx_val = int(e['rx'], 16) if isinstance(e['rx'], str) else e['rx']
        ctrl_val = int(e['ctrl'], 16) if isinstance(e['ctrl'], str) else e['ctrl']
        func_val = int(e['func'], 16) if isinstance(e['func'], str) else e['func']
        mc_pre = MC_NAMES.get(e['mc_pre'], str(e['mc_pre']))
        mc_post = MC_NAMES.get(e['mc_post'], str(e['mc_post']))
        dev_pre = DEV_NAMES.get(e['dev_pre'], str(e['dev_pre']))
        dev_post = DEV_NAMES.get(e['dev_post'], str(e['dev_post']))

        flags = []
        if e['abort']:
            flags.append('ABORT')
        if e['dev_pre'] != e['dev_post']:
            flags.append('DEV_CHG')
        if e['mc_pre'] != e['mc_post']:
            flags.append('MC_CHG')

        # Filter
        is_card = e['dev_post'] == 2 or e['dev_pre'] == 2 or tx_val == 0x81
        if filt == 'mc' and not is_card and not e['abort']:
            continue
        if filt == 'abort' and not e['abort']:
            continue

        flag_str = ' '.join(flags)
        dev_str = f"{dev_pre}->{dev_post}"
        mc_str = f"{mc_pre}->{mc_post}" if mc_pre != mc_post else mc_pre

        print(f"{e['seq']:7d} 0x{tx_val:02X} 0x{rx_val:02X} {dev_str:>10} {mc_str:>20} 0x{ctrl_val:04X} 0x{func_val:08X} {e['irq_cd']:>3} {flag_str}")

if __name__ == '__main__':
    main()
