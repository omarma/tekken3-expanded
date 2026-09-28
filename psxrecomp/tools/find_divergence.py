#!/usr/bin/env python3
"""
find_divergence.py — Golden-oracle RAM comparison for PSX recomp v4

Reads RAM from both the native runtime (port 4370) and DuckStation oracle
(port 4371), diffs them byte-by-byte, and reports the first N divergences.

Usage:
    python find_divergence.py                          # scan 0x80060000-0x80080000 (128KB)
    python find_divergence.py --lo 0x80000000 --hi 0x80080000  # wider range
    python find_divergence.py --max 50                 # report up to 50 diffs
    python find_divergence.py --exclude 0x80079D9C:4   # exclude VSync counter (4 bytes)

Uses persistent TCP connections to avoid overwhelming DuckStation's event loop.
"""

import socket
import json
import sys
import argparse
import time


class DebugClient:
    """Persistent TCP connection to a debug server."""

    def __init__(self, host, port, timeout=10.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self.buf = b''

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.host, self.port))
        self.buf = b''

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None

    def send(self, cmd):
        """Send a JSON command and return the parsed response.
        Reconnects automatically if the connection drops."""
        for attempt in range(3):
            try:
                if self.sock is None:
                    self.connect()
                self.sock.sendall((json.dumps(cmd) + '\n').encode())
                # Read until we get a complete JSON line
                while b'\n' not in self.buf:
                    chunk = self.sock.recv(8192)
                    if not chunk:
                        raise ConnectionError("connection closed")
                    self.buf += chunk
                line, self.buf = self.buf.split(b'\n', 1)
                return json.loads(line.decode().strip())
            except (ConnectionError, socket.error, OSError) as e:
                self.close()
                if attempt == 2:
                    raise RuntimeError(f"Failed after 3 attempts on port {self.port}: {e}")
                time.sleep(0.1)

    def read_ram(self, addr, length):
        """Read up to 16KB."""
        resp = self.send({"cmd": "read_ram", "addr": hex(addr), "len": length})
        if not resp.get('ok'):
            raise RuntimeError(f"read_ram failed at 0x{addr:08X}: {resp}")
        data = bytes.fromhex(resp['hex'])
        if len(data) != length:
            raise RuntimeError(f"read_ram at 0x{addr:08X}: requested {length}, got {len(data)}")
        return data


CHUNK_SIZE = 4096  # 4KB per request — fits in both servers' buffers

def read_ram_range(client, lo, hi, label=""):
    """Read a full RAM range in CHUNK_SIZE-byte chunks using a persistent connection."""
    result = bytearray()
    total = hi - lo
    done = 0
    for addr in range(lo, hi, CHUNK_SIZE):
        chunk_len = min(CHUNK_SIZE, hi - addr)
        chunk = client.read_ram(addr, chunk_len)
        result.extend(chunk)
        done += chunk_len
        if done % 8192 == 0 or done == total:
            pct = done * 100 // total
            print(f"\r  [{label}] {done}/{total} bytes ({pct}%)", end='', flush=True)
    print()
    return bytes(result)


def find_divergences(recomp_data, oracle_data, base_addr, excludes, max_results=20):
    """Compare two RAM buffers and return (divergences_list, total_diff_bytes, total_compared).

    Never silently truncates: always returns full counts even when
    max_results limits the detailed list."""
    divergences = []
    total_diff_bytes = 0
    total_compared = 0
    i = 0
    while i < len(recomp_data) and i < len(oracle_data):
        addr = base_addr + i
        # Check exclusion
        excluded = False
        for ex_addr, ex_len in excludes:
            if ex_addr <= addr < ex_addr + ex_len:
                i = ex_addr + ex_len - base_addr
                excluded = True
                break
        if excluded:
            continue

        total_compared += 1
        if recomp_data[i] != oracle_data[i]:
            total_diff_bytes += 1
            # Collect the full divergent run (no length cap)
            run_start = i
            while (i < len(recomp_data) and i < len(oracle_data) and
                   recomp_data[i] != oracle_data[i]):
                if i > run_start:
                    total_compared += 1
                    total_diff_bytes += 1
                i += 1
            run_end = i

            if len(divergences) < max_results:
                divergences.append({
                    'addr': base_addr + run_start,
                    'len': run_end - run_start,
                    'recomp': recomp_data[run_start:run_end],
                    'oracle': oracle_data[run_start:run_end],
                })
        else:
            i += 1

    return divergences, total_diff_bytes, total_compared


def format_divergence(d):
    """Format a single divergence for display."""
    import struct
    addr = d['addr']
    length = d['len']
    recomp_hex = d['recomp'].hex()
    oracle_hex = d['oracle'].hex()

    words = ""
    if addr % 4 == 0 and length >= 4:
        n_words = length // 4
        for w in range(min(n_words, 4)):
            off = w * 4
            rv = struct.unpack_from('<I', d['recomp'], off)[0]
            ov = struct.unpack_from('<I', d['oracle'], off)[0]
            words += f"\n    word+{off}: recomp=0x{rv:08X} oracle=0x{ov:08X}"

    return (f"  0x{addr:08X} ({length} bytes):\n"
            f"    recomp: {recomp_hex}\n"
            f"    oracle: {oracle_hex}{words}")


def main():
    parser = argparse.ArgumentParser(description='Find first RAM divergence between recomp and oracle')
    parser.add_argument('--lo', type=lambda x: int(x, 0), default=0x80060000,
                        help='Start address (default: 0x80060000)')
    parser.add_argument('--hi', type=lambda x: int(x, 0), default=0x80080000,
                        help='End address (default: 0x80080000 = 128KB)')
    parser.add_argument('--max', type=int, default=20,
                        help='Max divergences to report (default: 20)')
    parser.add_argument('--exclude', type=str, action='append', default=[],
                        help='Exclude range as addr:len (e.g., 0x80079D9C:4)')
    parser.add_argument('--recomp-port', type=int, default=4370)
    parser.add_argument('--oracle-port', type=int, default=4371)
    parser.add_argument('--no-pause', action='store_true',
                        help='Skip pause/continue (read live)')
    args = parser.parse_args()

    # Parse exclusions — nothing excluded by default.
    # Use --exclude 0x80079D9C:4 to exclude VSync counter if needed.
    excludes = []
    for ex in args.exclude:
        parts = ex.split(':')
        ex_addr = int(parts[0], 0)
        ex_len = int(parts[1]) if len(parts) > 1 else 4
        excludes.append((ex_addr, ex_len))

    print(f"=== PSX Golden-Oracle RAM Divergence Finder ===")
    print(f"  Range: 0x{args.lo:08X} - 0x{args.hi:08X} ({(args.hi - args.lo) // 1024}KB)")
    print(f"  Exclusions: {len(excludes)} ranges")
    print(f"  Max results: {args.max}")
    print()

    recomp = DebugClient('127.0.0.1', args.recomp_port)
    oracle = DebugClient('127.0.0.1', args.oracle_port)

    # Verify both servers are up
    try:
        r1 = recomp.send({"cmd": "ping"})
        print(f"  Recomp (:{args.recomp_port}): frame {r1.get('frame', '?')}")
    except Exception as e:
        print(f"  ERROR: Cannot connect to recomp: {e}")
        sys.exit(1)

    try:
        r2 = oracle.send({"cmd": "ping"})
        print(f"  Oracle (:{args.oracle_port}): frame {r2.get('frame', '?')}")
    except Exception as e:
        print(f"  ERROR: Cannot connect to oracle: {e}")
        sys.exit(1)

    print()

    # Pause both if requested
    if not args.no_pause:
        print("Pausing both...")
        try:
            recomp.send({"cmd": "pause"})
        except:
            pass
        try:
            oracle.send({"cmd": "pause"})
        except:
            pass

    # Read RAM from both
    print("Reading RAM...")
    t0 = time.time()
    recomp_ram = read_ram_range(recomp, args.lo, args.hi, "recomp")
    oracle_ram = read_ram_range(oracle, args.lo, args.hi, "oracle")
    t1 = time.time()
    print(f"  Read {len(recomp_ram) + len(oracle_ram)} bytes in {t1-t0:.1f}s")
    print()

    # Resume both if we paused
    if not args.no_pause:
        print("Resuming both...")
        try:
            recomp.send({"cmd": "continue"})
        except:
            pass
        try:
            oracle.send({"cmd": "continue"})
        except:
            pass
        print()

    # Close connections
    recomp.close()
    oracle.close()

    # Find divergences
    divs, total_diff, total_compared = find_divergences(
        recomp_ram, oracle_ram, args.lo, excludes, args.max)

    print(f"SUMMARY: {total_diff} bytes differ out of {total_compared} compared "
          f"({total_diff*100/max(total_compared,1):.2f}%)")
    print(f"  Showing {len(divs)} divergent region(s)" +
          (f" (capped at --max {args.max}; there may be more)" if len(divs) >= args.max else ""))
    print()

    if not divs:
        print("NO DIVERGENCES FOUND in scanned range.")
    else:
        for i, d in enumerate(divs):
            print(f"#{i+1}: {format_divergence(d)}")
            print()

        print(f"--- FIRST DIVERGENCE: 0x{divs[0]['addr']:08X} ---")
        print(f"  Investigate with:")
        print(f"    read_ram 0x{divs[0]['addr']:08X} on both ports")
        print(f"    wtrace_add 0x{divs[0]['addr']:08X} on recomp to find who writes it")


if __name__ == '__main__':
    main()
