#!/usr/bin/env python
"""window_capture.py -- capture the ACTUAL on-screen content of a top-level
window (SDL/GL/software, any runtime) via PrintWindow(PW_RENDERFULLCONTENT).

This is the window-liveness ground truth. The debug-server `screenshot` /
`screenshot_file` commands render from GPU/VRAM display state and say NOTHING
about whether the SDL window is presenting -- they lied about the Tomba2
Whoopee-logo freeze (2026-07-02). This tool reads what the user's monitor
shows.

Requires a Windows-native python (C:/msys64/mingw64/bin/python.exe -- the
MSYS/devkitPro pythons have no ctypes.windll).

Usage:
  window_capture.py --title "Tomba! 2 Recompiled" --out shot.bmp
  window_capture.py --title "Tomba! 2 Recompiled" --series 10 --interval 1.0 \
      --out-dir _wincap
    -> saves _wincap/cap_00.bmp .. cap_09.bmp, prints per-pair changed-pixel
       counts and a LIVE/FROZEN verdict (FROZEN = every consecutive pair
       differs in < --min-changed pixels).

Exit codes: 0 = captured (series: LIVE), 2 = window not found,
            3 = series verdict FROZEN, 4 = capture failed.
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import os
import struct
import sys
import time

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

PW_RENDERFULLCONTENT = 0x00000002
SRCCOPY = 0x00CC0020
BI_RGB = 0
DIB_RGB_COLORS = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wt.WORD),
        ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


def find_window(title_substr):
    """Return (hwnd, title) of the first visible top-level window whose title
    contains title_substr (case-insensitive)."""
    matches = []
    needle = title_substr.lower()

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if needle in buf.value.lower():
            matches.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cb, 0)
    return matches[0] if matches else (None, None)


def capture(hwnd):
    """PrintWindow the client area; return (width, height, bgra_bytes)."""
    rc = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    w, h = rc.right - rc.left, rc.bottom - rc.top
    if w <= 0 or h <= 0:
        return None

    hdc_win = user32.GetDC(hwnd)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    gdi32.SelectObject(hdc_mem, hbmp)

    ok = user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)
    if not ok:
        # Fallback: BitBlt from the window DC (fails if occluded, but better
        # than nothing for windows that reject PrintWindow).
        ok = gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_win, 0, 0, SRCCOPY)

    data = None
    if ok:
        bih = BITMAPINFOHEADER()
        bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bih.biWidth = w
        bih.biHeight = -h          # top-down
        bih.biPlanes = 1
        bih.biBitCount = 32
        bih.biCompression = BI_RGB
        buf = ctypes.create_string_buffer(w * h * 4)
        got = gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf,
                              ctypes.byref(bih), DIB_RGB_COLORS)
        if got == h:
            data = buf.raw

    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(hwnd, hdc_win)
    return (w, h, data) if data else None


def save_bmp(path, w, h, bgra):
    """Write a 32bpp top-down BMP."""
    img_size = w * h * 4
    hdr = struct.pack("<2sIHHI", b"BM", 14 + 40 + img_size, 0, 0, 14 + 40)
    dib = struct.pack("<IiiHHIIiiII", 40, w, -h, 1, 32, 0, img_size,
                      2835, 2835, 0, 0)
    with open(path, "wb") as f:
        f.write(hdr)
        f.write(dib)
        f.write(bgra)


def diff_pixels(a, b):
    """Count differing 4-byte pixels between two equal-length BGRA buffers."""
    if len(a) != len(b):
        return -1
    n = 0
    # Compare in 4-byte strides; memoryview slicing keeps this tolerable.
    ma, mb = memoryview(a), memoryview(b)
    step = 4096  # bytes per chunk
    changed = 0
    for off in range(0, len(a), step):
        ca, cb = ma[off:off + step], mb[off:off + step]
        if ca == cb:
            continue
        for p in range(0, len(ca), 4):
            if ca[p:p + 4] != cb[p:p + 4]:
                changed += 1
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True,
                    help="window title substring (case-insensitive)")
    ap.add_argument("--out", help="single-shot output BMP path")
    ap.add_argument("--series", type=int, default=0,
                    help="capture N shots and judge LIVE/FROZEN")
    ap.add_argument("--interval", type=float, default=1.0,
                    help="seconds between series shots")
    ap.add_argument("--out-dir", default="_wincap",
                    help="series output directory")
    ap.add_argument("--min-changed", type=int, default=200,
                    help="pixels that must change between consecutive shots "
                         "for the pair to count as motion")
    args = ap.parse_args()

    hwnd, title = find_window(args.title)
    if not hwnd:
        print("WINDOW-NOT-FOUND: no visible window matching %r" % args.title)
        sys.exit(2)
    print("window: hwnd=0x%X title=%r" % (hwnd, title))

    if args.series <= 0:
        shot = capture(hwnd)
        if not shot:
            print("CAPTURE-FAILED")
            sys.exit(4)
        w, h, data = shot
        out = args.out or "wincap.bmp"
        save_bmp(out, w, h, data)
        print("saved %s (%dx%d)" % (out, w, h))
        sys.exit(0)

    os.makedirs(args.out_dir, exist_ok=True)
    shots = []
    for i in range(args.series):
        s = capture(hwnd)
        if not s:
            print("CAPTURE-FAILED at shot %d" % i)
            sys.exit(4)
        w, h, data = s
        p = os.path.join(args.out_dir, "cap_%02d.bmp" % i)
        save_bmp(p, w, h, data)
        shots.append(data)
        print("shot %02d saved (%dx%d)" % (i, w, h))
        if i + 1 < args.series:
            time.sleep(args.interval)

    moving_pairs = 0
    for i in range(1, len(shots)):
        d = diff_pixels(shots[i - 1], shots[i])
        moving = d >= args.min_changed
        moving_pairs += moving
        print("pair %02d->%02d: %d px changed %s"
              % (i - 1, i, d, "(MOTION)" if moving else ""))

    if moving_pairs == 0:
        print("VERDICT: FROZEN (0/%d pairs show motion)" % (len(shots) - 1))
        sys.exit(3)
    print("VERDICT: LIVE (%d/%d pairs show motion)"
          % (moving_pairs, len(shots) - 1))
    sys.exit(0)


if __name__ == "__main__":
    main()
