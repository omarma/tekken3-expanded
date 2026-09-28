#!/usr/bin/env python3
"""IRQ-chain step audit: per-step probe of the SIO IRQ delivery chain.

Each function probes one step and prints PASS/FAIL with evidence. No
state mutation — pure observation of always-on rings.
"""
import socket, json, sys, time

PORT = 4370


def send(cmd, **kw):
    req = {"id": 1, "cmd": cmd, **kw}
    s = socket.socket(); s.settimeout(8.0); s.connect(("127.0.0.1", PORT))
    s.sendall((json.dumps(req) + "\n").encode())
    buf = b""
    depth_c = depth_s = 0
    in_str = esc = False
    started = False
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        for b in chunk:
            buf += bytes([b])
            ch = chr(b)
            if in_str:
                if esc: esc = False
                elif ch == "\\": esc = True
                elif ch == '"': in_str = False
                continue
            if ch == '"': in_str = True
            elif ch == "{": depth_c += 1; started = True
            elif ch == "}": depth_c -= 1
            elif ch == "[": depth_s += 1
            elif ch == "]": depth_s -= 1
            if started and depth_c == 0 and depth_s == 0:
                s.close()
                return json.loads(buf.decode().strip())
    s.close()
    return json.loads(buf.decode().strip())


def fz():
    return send("freeze_check")


def header(label):
    print()
    print("=" * 70)
    print(label)
    print("=" * 70)


if __name__ == "__main__":
    fz1 = fz()
    print(f"frame={fz1.get('total_checks','?')} mc_max_state={fz1.get('mc_max_state')}"
          f" sio_irq_total={fz1.get('sio_irq_total')} tx_writes={fz1.get('tx_writes')}"
          f" mc_aborts={fz1.get('mc_aborts')} mc_read_done={fz1.get('mc_read_done')}"
          f" i_stat={fz1.get('i_stat')} i_mask={fz1.get('i_mask')}")

    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"

    if cmd in ("step12", "all"):
        header("Step 1-2: TX -> sio_process_byte -> DEV_MEMCARD")
        # sio_trace dumps recent SIO bytes. Filter for card cmd bytes.
        r = send("sio_trace", count=200)
        ents = r.get("entries", [])
        cards = [e for e in ents if e.get("dev_pre") == "card" or e.get("dev_post") == "card"
                 or e.get("mc_state_pre", 0) > 0 or e.get("mc_state_post", 0) > 0]
        cmds_seen = [e for e in cards if e.get("tx") in ("0x52", "0x57", "0x53") or e.get("tx_byte") in (0x52, 0x57, 0x53)]
        print(f"sio_trace returned {len(ents)} entries, {len(cards)} card-related, {len(cmds_seen)} CMD bytes")
        if cards:
            print("first 3 card-related entries:")
            for e in cards[:3]:
                print(" ", json.dumps(e))
        # sio_state for current device
        st = send("sio_state")
        print(f"sio_state: mc_max_state={st.get('mc_max_state')} tx_writes={st.get('tx_writes')}"
              f" mc_probes={st.get('mc_probes')} mc_cmds={st.get('mc_cmds')} mc_acks={st.get('mc_acks')}")

    if cmd in ("step3456", "all"):
        header("Step 3-4-5-6: arm + countdown + tick decrement to 0")
        # Use sio_irq_dump src=1 (CARD) over wide window
        r = send("sio_irq_dump", count=200000, src=1)
        cards = r.get("entries", [])
        print(f"sio_irq ring: total={r.get('total')} shown={r.get('shown')} card_emitted={r.get('emitted')}")
        if cards:
            print("first card-IRQ entry:", json.dumps(cards[0]))
        # Compare: total card IRQ-arm vs IRQ-fire — would need extra probe.
        # Aggregate: any card IRQ ever fired?
        if r.get("emitted", 0) == 0:
            print("FAIL: zero card-source IRQ fires in entire ring")
        # freeze_check exposes current sio_irq_pending and countdown
        print(f"freeze_check sio_irq_pending={fz1.get('sio_irq_pending')}"
              f" sio_irq_countdown={fz1.get('sio_irq_countdown')}")

    if cmd in ("step7", "all"):
        header("Step 7: i_stat bit 7 (SIO0) ever raised by sio_tick path")
        # i_stat history exists? Check via wtrace target on i_stat MMIO addr.
        # Look at sio_irq dump again — when an IRQ fires, i_stat_after has bit 7.
        r = send("sio_irq_dump", count=200000, src=1)
        cards = r.get("entries", [])
        if cards:
            with_bit7 = [e for e in cards if int(e.get("i_stat_after","0x0"),16) & 0x80]
            print(f"card IRQ entries with i_stat_after bit7 set: {len(with_bit7)} / {len(cards)}")
        else:
            print("FAIL: no card IRQ entries to inspect")

    if cmd in ("step89", "all"):
        header("Step 8-9: BIOS exception entry and chain dispatch")
        f = fz1
        print(f"exception_entries={f.get('exception_entries')}"
              f" exception_reentry_blocks={f.get('exception_reentry_blocks')}"
              f" dirty_ram_aborts={f.get('dirty_ram_aborts')}"
              f" sio_byte_seq={f.get('sio_byte_seq')}"
              f" sio_irq_total={f.get('sio_irq_total')}")
        # i_mask history (already proven bit 7 toggles)
        r = send("imask_trace", count=4)
        print(f"imask_trace: bit7_sets={r.get('bit7_sets')} bit7_clears={r.get('bit7_clears')} total={r.get('total')}")

    if cmd in ("step1012", "all"):
        header("Step 10-11-12: dirty-RAM 0x641C / 0xCF0 + [0x72F0] increment")
        r = send("dirty_ram_stats")
        per = r.get("per_pc", [])
        for entry in per:
            pc = entry.get("pc")
            if pc in ("0x000000CF0", "0x00000CF0", "0x0000641C", "0x00006594"):
                print(f"  {pc}: hits={entry.get('hits')} insns={entry.get('insns')}")
        print(f"blocks_run={r.get('blocks_run')} insns_run={r.get('insns_run')} aborts={r.get('aborts')}")
        # current [0x72F0]
        rr = send("read_ram", addr="0x800072F0", len=4)
        print(f"[0x72F0] now: hex={rr.get('hex')}")
        # wtrace history for [0x72F0]
        wt = send("wtrace_dump")
        # check what slots exist
        print(f"wtrace_dump keys: {list(wt.keys())[:6]}")
        # filter for any addr in [0x72F0..0x72F3]
        all_entries = wt.get("entries", []) if isinstance(wt.get("entries"), list) else []
        if all_entries:
            target = [e for e in all_entries if 0x72F0 <= int(e.get("addr","0"),16) & 0xFFFF <= 0x72F3]
            print(f"wtrace entries targeting [0x72F0..0x72F3]: {len(target)}")
            if target:
                print(f"first 5: {target[:5]}")
