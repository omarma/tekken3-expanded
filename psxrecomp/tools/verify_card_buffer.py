#!/usr/bin/env python3
"""Pull all 128 KiB of cards[slot].data via card_buffer_dump and sha256-compare to disk.

Usage: python tools/verify_card_buffer.py
"""
import socket
import json
import hashlib
import sys

PORT = 4370
HOST = "127.0.0.1"
CHUNK = 0x4000  # 16 KiB per request
SIZE = 0x20000  # 128 KiB

def send_cmd(req):
    s = socket.socket(); s.settimeout(5.0); s.connect((HOST, PORT))
    s.sendall((json.dumps(req) + "\n").encode())
    buf = b""
    while True:
        chunk = s.recv(65536)
        if not chunk: break
        buf += chunk
        if buf.rstrip().endswith(b"}"):
            try:
                obj = json.loads(buf.decode().strip())
                s.close()
                return obj
            except json.JSONDecodeError:
                pass
    s.close()
    return json.loads(buf.decode().strip())

def fetch_card(slot):
    h = hashlib.sha256()
    raw = bytearray()
    off = 0
    while off < SIZE:
        n = min(CHUNK, SIZE - off)
        resp = send_cmd({"id": 1, "cmd": "card_buffer_dump",
                         "slot": slot, "offset": off, "len": n})
        if not resp.get("ok"):
            print(f"slot {slot} offset {off}: ERROR {resp}")
            return None
        chunk = bytes.fromhex(resp["hex"])
        if len(chunk) != n:
            print(f"slot {slot} offset {off}: short read {len(chunk)} != {n}")
        raw.extend(chunk); h.update(chunk); off += len(chunk)
        if len(chunk) == 0:
            break
    return bytes(raw), h.hexdigest()

def disk_sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

if __name__ == "__main__":
    paths = ["card1.mcd", "card2.mcd"]
    for slot, path in enumerate(paths):
        runtime_data, runtime_sha = fetch_card(slot) or (b"", None)
        disk = disk_sha(path)
        match = "MATCH" if runtime_sha == disk else "DIFFER"
        print(f"slot {slot} ({path}):")
        print(f"  disk    sha256: {disk}")
        print(f"  runtime sha256: {runtime_sha}")
        print(f"  -> {match}")
