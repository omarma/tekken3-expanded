#!/usr/bin/env python3
"""load_probe.py — E0 load-window decomposition (LOAD_TIME_ZERO L1.0).

Passive ring-buffer consumer: samples always-on counters while the game
free-runs, then locates completed CD load bursts (cdrom_bursts ring) inside
the monitored span and reports, per burst window:

  guest side: cycles, effective Mcyc/s + multiplier vs 1x (33.8688 Mcyc/s),
              sectors delivered, sector rate, disc divisor, frames
  host side:  phase_profile shares (interp / native-overlay / static / gpu /
              host-other / exception) over the covering seconds,
              phase_hot top overlay funcs (delta), dirty_ram per_pc top (delta)

No arming, no pausing, no stepping — everything read from rings after the
fact. Usage:

  python tools/load_probe.py --port 4470 run --secs 90
      Monitor for N seconds (trigger loads by playing / TCP input in
      parallel), then report every burst that completed in the span.

  python tools/load_probe.py --port 4470 snap
      One-shot dump of the counters this probe uses (sanity check).
"""
import argparse, json, socket, sys, time

X1_MCYC_PER_S = 33.8688  # NTSC PSX CPU clock, guest Mcyc per real second at 1x


class Client:
    """One-shot connection per command (the server aborts a second request
    on the same socket — matches debug_client.py's connect/send/close)."""

    def __init__(self, host, port, timeout=8.0):
        self.host, self.port, self.timeout = host, port, timeout
        self.next_id = 1

    def cmd(self, name, **params):
        req = {"cmd": name, "id": self.next_id}
        req.update(params)
        self.next_id += 1
        self.sock = socket.create_connection((self.host, self.port),
                                             timeout=self.timeout)
        self.buf = b""
        self.sock.sendall((json.dumps(req) + "\n").encode())
        # Responses may span multiple lines (e.g. cdrom_bursts emits one
        # record per line): accumulate until the buffer parses as one JSON
        # object, not until the first newline.
        while True:
            text = self.buf.decode(errors="replace").strip()
            if text:
                try:
                    obj, _end = json.JSONDecoder().raw_decode(text)
                    self.sock.close()
                    return obj
                except json.JSONDecodeError:
                    pass
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("server closed")
            self.buf += chunk


def phot_map(resp):
    return {e["addr"]: e["samples"] for e in resp.get("top", [])}


def perpc_map(resp):
    return {e["pc"]: e["insns"] for e in resp.get("per_pc", [])}


def delta_top(before, after, k=10):
    d = {a: after[a] - before.get(a, 0) for a in after}
    items = [(a, v) for a, v in d.items() if v > 0]
    items.sort(key=lambda kv: -kv[1])
    return items[:k]


def snap(c, retries=3):
    # freeze_check occasionally returns a short/err response; retry rather
    # than kill a long monitoring run over one bad sample.
    for attempt in range(retries):
        try:
            fz = c.cmd("freeze_check", window=1)
            return {
                "t": time.monotonic(),
                "wall": time.time(),
                "cycles": int(fz["psx_cycle_count"]),
                "frame": int(fz["frame_count"]),
                "dirty_insns": int(fz["dirty_ram_insns"]),
            }
        except (KeyError, ValueError, json.JSONDecodeError):
            if attempt == retries - 1:
                raise
            time.sleep(0.1)


def run(c, secs, tick, out):
    print(f"[load_probe] monitoring {secs}s (tick {tick}s) — trigger loads now",
          flush=True)
    t0 = time.monotonic()
    bursts0 = c.cmd("cdrom_bursts", count=1).get("total", 0)
    phot0 = phot_map(c.cmd("phase_hot", top=64))
    stat0 = phot_map(c.cmd("phase_hot", set="static", top=64))
    perpc0 = perpc_map(c.cmd("dirty_ram_stats"))
    series = [snap(c)]
    while time.monotonic() - t0 < secs:
        time.sleep(tick)
        series.append(snap(c))
    phot1 = phot_map(c.cmd("phase_hot", top=64))
    stat1 = phot_map(c.cmd("phase_hot", set="static", top=64))
    perpc1 = perpc_map(c.cmd("dirty_ram_stats"))
    bursts = c.cmd("cdrom_bursts", count=64)
    span_s = series[-1]["t"] - series[0]["t"]

    # Whole-span summary (context for the per-burst numbers).
    dcyc = series[-1]["cycles"] - series[0]["cycles"]
    rate = dcyc / span_s / 1e6
    print(f"\n=== span: {span_s:.1f}s  guest {dcyc/1e6:.0f} Mcyc  "
          f"{rate:.1f} Mcyc/s  ({rate / X1_MCYC_PER_S:.2f}x)  "
          f"new bursts: {bursts.get('total', 0) - bursts0}")

    # Frame -> monotonic time mapping from the series (piecewise linear).
    def frame_to_t(fr):
        for a, b in zip(series, series[1:]):
            if a["frame"] <= fr <= b["frame"]:
                if b["frame"] == a["frame"]:
                    return a["t"]
                f = (fr - a["frame"]) / (b["frame"] - a["frame"])
                return a["t"] + f * (b["t"] - a["t"])
        return None

    def series_at(tm):  # nearest-sample counters at monotonic time tm
        return min(series, key=lambda s: abs(s["t"] - tm))

    report = {"span_s": span_s, "span_mcyc_per_s": rate,
              "bursts": [], "phot_delta": delta_top(phot0, phot1),
              "static_delta": delta_top(stat0, stat1, 15),
              "perpc_delta": delta_top(perpc0, perpc1)}

    now_t = time.monotonic()
    for b in bursts.get("bursts", []):
        ta, tb = frame_to_t(b["start_frame"]), frame_to_t(b["end_frame"])
        if ta is None or tb is None:
            continue  # burst outside the monitored span
        sa, sb = series_at(ta), series_at(tb)
        wall = tb - ta
        gcyc = sb["cycles"] - sa["cycles"]
        gint = sb["dirty_insns"] - sa["dirty_insns"]
        eff = gcyc / wall / 1e6 if wall > 0 else 0.0
        # phase_profile ring is per-second, 64s deep: query the window of
        # seconds that covers this burst, measured back from "now".
        back_end = int(now_t - tb)
        need = int(wall) + 2
        ph = c.cmd("phase_profile", window=min(back_end + need, 62))
        rec = {
            "frames": b["frames"], "sectors": b["sectors"],
            "rate_sps": b["rate"], "divisor": b["divisor"],
            "wall_s": round(wall, 2),
            "guest_mcyc": round(gcyc / 1e6, 1),
            "eff_mcyc_per_s": round(eff, 1),
            "multiplier_vs_1x": round(eff / X1_MCYC_PER_S, 2),
            "guest_s_at_1x": round(gcyc / (X1_MCYC_PER_S * 1e6), 2),
            "interp_insns": gint,
            "phase_window": ph,
        }
        report["bursts"].append(rec)
        print(f"\n--- burst: {b['sectors']} sectors, {b['frames']} frames, "
              f"{wall:.2f}s wall")
        print(f"    guest {gcyc/1e6:.0f} Mcyc = {rec['guest_s_at_1x']}s at 1x"
              f" -> {rec['multiplier_vs_1x']}x effective")
        print(f"    interp insns in window: {gint}")
        shares = {k.replace("_share", ""): v for k, v in ph.items()
                  if k.endswith("_share")}
        print(f"    phase shares (covering secs, approximate): {shares}")

    if report["static_delta"]:
        tot = sum(v for _, v in report["static_delta"]) or 1
        print("\ntop STATIC funcs by wall samples (span delta):")
        for a, v in report["static_delta"]:
            print(f"    {a}  {v}  ({100.0*v/tot:.1f}% of top)")
    if report["phot_delta"]:
        print("\ntop native-overlay funcs by wall samples (span delta):")
        for a, v in report["phot_delta"]:
            print(f"    {a}  {v}")
    if report["perpc_delta"]:
        print("\ntop interp PCs by insns (span delta):")
        for a, v in report["perpc_delta"]:
            print(f"    {a}  {v}")

    if out:
        with open(out, "w") as f:
            json.dump(report, f, indent=1)
        print(f"\n[load_probe] report -> {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4470)
    sub = ap.add_subparsers(dest="mode", required=True)
    r = sub.add_parser("run")
    r.add_argument("--secs", type=float, default=90)
    r.add_argument("--tick", type=float, default=0.25)
    r.add_argument("--out", default=None)
    sub.add_parser("snap")
    args = ap.parse_args()

    c = Client(args.host, args.port)
    if args.mode == "snap":
        for cmd, kw in (("freeze_check", {"window": 1}),
                        ("cdrom_bursts", {"count": 4}),
                        ("phase_profile", {"window": 10}),
                        ("phase_hot", {"top": 10})):
            resp = c.cmd(cmd, **kw)
            print(f"== {cmd}: {json.dumps(resp)[:600]}")
    else:
        run(c, args.secs, args.tick, args.out)


if __name__ == "__main__":
    main()
