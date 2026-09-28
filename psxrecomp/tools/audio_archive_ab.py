#!/usr/bin/env python3
"""audio_archive_ab.py - continuously archive both processes' always-on PCM
rings to disk with a screenshot timeline, so identical attract-demo tracks can
be paired offline. Ring holds ~95 s; dumping every ~75 s with absolute frame
indices yields a gapless per-side archive.

Usage: python audio_archive_ab.py <out_dir> <minutes>
"""
import json
import os
import socket
import struct
import sys
import time

SIDES = {"runtime": 4520, "beetle": 4382}

def call(port, p, timeout=30):
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        s.sendall((json.dumps(p) + "\n").encode())
        buf = b""
        while True:
            c = s.recv(1 << 16)
            if not c:
                break
            buf += c
            if buf.endswith(b"\n"):
                break
        return json.loads(buf.decode())
    finally:
        s.close()

def bmp_mean(path):
    try:
        with open(path, "rb") as f:
            d = f.read()
        off = struct.unpack("<I", d[10:14])[0]
        px = d[off::37]
        return sum(px) / max(1, len(px))
    except Exception:
        return -1

def main():
    out = sys.argv[1]
    minutes = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0
    if not (len(out) > 1 and out[1] == ":"):
        raise SystemExit("out dir must be a Windows-style path (F:/...) — "
                         "the game processes fopen() these paths themselves")
    os.makedirs(out, exist_ok=True)
    log = open(os.path.join(out, "timeline.jsonl"), "w")
    next_dump = {k: 0.0 for k in SIDES}
    dump_idx = {k: 0 for k in SIDES}
    last_total = {k: 0 for k in SIDES}
    t_end = time.time() + minutes * 60
    shot_i = 0
    while time.time() < t_end:
        now = time.time()
        for side, port in SIDES.items():
            try:
                st = call(port, {"id": 1, "cmd": "audio_stats"})
                tap0 = st["taps"][0]["frames"]
                sp = os.path.join(out, f"{side}_{shot_i:04d}.bmp").replace("\\", "/")
                call(port, {"id": 2, "cmd": "screenshot_file", "path": sp})
                rec = {"t": now, "side": side, "shot": shot_i, "tap0": tap0,
                       "bright": round(bmp_mean(sp), 1)}
                # dump the ring every ~75 s, from where the last dump ended
                if now >= next_dump[side]:
                    start = last_total[side]
                    avail_oldest = max(0, tap0 - 4194304)
                    if start < avail_oldest:
                        start = avail_oldest
                    count = tap0 - start
                    if count > 0:
                        wp = os.path.join(
                            out, f"{side}_arch{dump_idx[side]:02d}_{start}.wav"
                        ).replace("\\", "/")
                        r = call(port, {"id": 3, "cmd": "audio_wav", "tap": 0,
                                        "path": wp, "start": str(start),
                                        "count": str(count)}, timeout=60)
                        rec["dump"] = {"file": wp, "start": start,
                                       "count": count, "ok": r.get("ok")}
                        last_total[side] = tap0
                        dump_idx[side] += 1
                    next_dump[side] = now + 75.0
                log.write(json.dumps(rec) + "\n")
                log.flush()
            except Exception as e:
                log.write(json.dumps({"t": now, "side": side, "err": str(e)}) + "\n")
                log.flush()
        shot_i += 1
        time.sleep(10)
    log.close()
    print("archive complete")

if __name__ == "__main__":
    main()
