#!/usr/bin/env python3
"""audio_capture_ab.py - dump the always-on audio tap rings from psx-runtime
and psx-beetle (identical `audio_*` wire protocol, ports differ) and run the
drift-tolerant A/B comparison.

Both processes must already be sitting at the scene whose audio you want to
compare (drive them there first via `press` on their debug ports). The rings
are always-on: this tool dumps HISTORY (the last ~95 s of PCM already
captured), it never arms anything.

Usage:
  python tools/audio_capture_ab.py --runtime-port 4520 --beetle-port 4380 \
      --out F:/Projects/psxrecomp/_wt-audio-mmx5/_audio_captures/title \
      [--secs 30] [--analyze]

Outputs in --out:
  runtime_spu_out.wav   T1: recomp SPU render output (pre host fade)
  runtime_cd_in.wav     T2: recomp XA/CD-DA PCM pushed to the SPU CD bus
  runtime_host.wav      T3: exact bytes handed to SDL_QueueAudio
  beetle_spu_out.wav    oracle: Beetle's fully-mixed reference SPU output
  stats.json            audio_stats from both sides
"""
import argparse
import json
import os
import socket
import subprocess
import sys

def call(port, payload, timeout=30):
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        s.sendall((json.dumps(payload) + "\n").encode())
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

def dump_tap(port, tap, path, secs):
    """Dump the trailing `secs` seconds of a tap ring to `path`."""
    stats = call(port, {"id": 1, "cmd": "audio_stats"})
    total = stats["taps"][tap]["frames"]
    count = min(total, int(secs * 44100)) if secs > 0 else 0
    start = total - count if count else -1
    r = call(port, {"id": 2, "cmd": "audio_wav", "tap": tap,
                    "path": path.replace("\\", "/"),
                    "start": str(start), "count": str(count)})
    return r, stats

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime-port", type=int, default=4520)
    ap.add_argument("--beetle-port", type=int, default=4380)
    ap.add_argument("--out", required=True)
    ap.add_argument("--secs", type=float, default=30.0,
                    help="trailing window to dump (0 = whole ring)")
    ap.add_argument("--analyze", action="store_true",
                    help="run audio_ab_diff.py runtime_spu_out vs beetle_spu_out")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    out = lambda name: os.path.abspath(os.path.join(args.out, name))
    results = {"runtime": {}, "beetle": {}}

    for tap, name in ((0, "runtime_spu_out.wav"),
                      (1, "runtime_cd_in.wav"),
                      (2, "runtime_host.wav")):
        try:
            r, st = dump_tap(args.runtime_port, tap, out(name), args.secs)
            results["runtime"][name] = r
            results["runtime"]["stats"] = st
            print(f"[runtime] tap {tap} -> {name}: {r}")
        except Exception as e:
            print(f"[runtime] tap {tap} FAILED: {e}")

    try:
        r, st = dump_tap(args.beetle_port, 0, out("beetle_spu_out.wav"), args.secs)
        results["beetle"]["beetle_spu_out.wav"] = r
        results["beetle"]["stats"] = st
        print(f"[beetle] tap 0 -> beetle_spu_out.wav: {r}")
    except Exception as e:
        print(f"[beetle] tap 0 FAILED: {e}")

    with open(out("stats.json"), "w") as f:
        json.dump(results, f, indent=2)
    print(f"stats -> {out('stats.json')}")

    if args.analyze:
        here = os.path.dirname(os.path.abspath(__file__))
        cmd = [sys.executable, os.path.join(here, "audio_ab_diff.py"),
               "--ref", out("beetle_spu_out.wav"),
               "--test", out("runtime_spu_out.wav"),
               "--rate", "44100",
               "--json", out("ab_diff.json")]
        print("running:", " ".join(cmd))
        subprocess.run(cmd, check=False)

if __name__ == "__main__":
    main()
