#!/usr/bin/env python3
"""host_thread_probe.py — where is every host thread of a (wedged) runtime?

Suspends each thread of the target process just long enough to capture RIP/RSP,
reads a slice of its stack, and reports, per thread:
  - thread id + SetThreadDescription name (if any)
  - RIP (resolved through addr2line when it lands in the main exe)
  - a poor-man's backtrace: stack-scanned return addresses inside the main exe

Usage:
  python tools/host_thread_probe.py --pid 12092 [--exe path\\to\\psx-runtime.exe]
                                    [--stack-words 4096]

The exe path is only needed for addr2line symbolization (RelWithDebInfo/DWARF).
addr2line must be on PATH (mingw binutils). Safe on a live process: threads are
resumed immediately after context capture.
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import subprocess
import sys

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

TH32CS_SNAPTHREAD = 0x4
THREAD_ALL = 0x1FFFFF
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
CONTEXT_FULL_AMD64 = 0x10000B


class THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ThreadID", wt.DWORD),
        ("th32OwnerProcessID", wt.DWORD),
        ("tpBasePri", wt.LONG),
        ("tpDeltaPri", wt.LONG),
        ("dwFlags", wt.DWORD),
    ]


class M128A(ctypes.Structure):
    _fields_ = [("Low", ctypes.c_ulonglong), ("High", ctypes.c_longlong)]


class CONTEXT64(ctypes.Structure):
    _align_ = 16
    _fields_ = [
        ("P1Home", ctypes.c_ulonglong), ("P2Home", ctypes.c_ulonglong),
        ("P3Home", ctypes.c_ulonglong), ("P4Home", ctypes.c_ulonglong),
        ("P5Home", ctypes.c_ulonglong), ("P6Home", ctypes.c_ulonglong),
        ("ContextFlags", wt.DWORD), ("MxCsr", wt.DWORD),
        ("SegCs", wt.WORD), ("SegDs", wt.WORD), ("SegEs", wt.WORD),
        ("SegFs", wt.WORD), ("SegGs", wt.WORD), ("SegSs", wt.WORD),
        ("EFlags", wt.DWORD),
        ("Dr0", ctypes.c_ulonglong), ("Dr1", ctypes.c_ulonglong),
        ("Dr2", ctypes.c_ulonglong), ("Dr3", ctypes.c_ulonglong),
        ("Dr6", ctypes.c_ulonglong), ("Dr7", ctypes.c_ulonglong),
        ("Rax", ctypes.c_ulonglong), ("Rcx", ctypes.c_ulonglong),
        ("Rdx", ctypes.c_ulonglong), ("Rbx", ctypes.c_ulonglong),
        ("Rsp", ctypes.c_ulonglong), ("Rbp", ctypes.c_ulonglong),
        ("Rsi", ctypes.c_ulonglong), ("Rdi", ctypes.c_ulonglong),
        ("R8", ctypes.c_ulonglong), ("R9", ctypes.c_ulonglong),
        ("R10", ctypes.c_ulonglong), ("R11", ctypes.c_ulonglong),
        ("R12", ctypes.c_ulonglong), ("R13", ctypes.c_ulonglong),
        ("R14", ctypes.c_ulonglong), ("R15", ctypes.c_ulonglong),
        ("Rip", ctypes.c_ulonglong),
        ("FltSave", ctypes.c_byte * 512),
        ("VectorRegister", M128A * 26),
        ("VectorControl", ctypes.c_ulonglong),
        ("DebugControl", ctypes.c_ulonglong),
        ("LastBranchToRip", ctypes.c_ulonglong),
        ("LastBranchFromRip", ctypes.c_ulonglong),
        ("LastExceptionToRip", ctypes.c_ulonglong),
        ("LastExceptionFromRip", ctypes.c_ulonglong),
    ]


def thread_ids(pid):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    te = THREADENTRY32()
    te.dwSize = ctypes.sizeof(THREADENTRY32)
    tids = []
    if k32.Thread32First(snap, ctypes.byref(te)):
        while True:
            if te.th32OwnerProcessID == pid:
                tids.append(te.th32ThreadID)
            if not k32.Thread32Next(snap, ctypes.byref(te)):
                break
    k32.CloseHandle(snap)
    return tids


def thread_name(h):
    GetThreadDescription = getattr(k32, "GetThreadDescription", None)
    if not GetThreadDescription:
        return ""
    pstr = ctypes.c_wchar_p()
    if GetThreadDescription(h, ctypes.byref(pstr)) >= 0 and pstr.value:
        name = pstr.value
        k32.LocalFree(pstr)
        return name
    return ""


def main_module_range(hproc):
    mods = (ctypes.c_void_p * 1024)()
    needed = wt.DWORD()
    if not psapi.EnumProcessModules(hproc, mods, ctypes.sizeof(mods),
                                    ctypes.byref(needed)):
        return None, None, ""

    class MODULEINFO(ctypes.Structure):
        _fields_ = [("lpBaseOfDll", ctypes.c_void_p),
                    ("SizeOfImage", wt.DWORD),
                    ("EntryPoint", ctypes.c_void_p)]

    mi = MODULEINFO()
    psapi.GetModuleInformation.argtypes = [wt.HANDLE, ctypes.c_void_p,
                                           ctypes.c_void_p, wt.DWORD]
    psapi.GetModuleFileNameExW.argtypes = [wt.HANDLE, ctypes.c_void_p,
                                           ctypes.c_wchar_p, wt.DWORD]
    psapi.GetModuleInformation(hproc, mods[0], ctypes.byref(mi),
                               ctypes.sizeof(mi))
    namebuf = ctypes.create_unicode_buffer(1024)
    psapi.GetModuleFileNameExW(hproc, mods[0], namebuf, 1024)
    return mi.lpBaseOfDll, mi.SizeOfImage, namebuf.value


def read_mem(hproc, addr, size):
    buf = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t()
    if not k32.ReadProcessMemory(hproc, ctypes.c_void_p(addr), buf, size,
                                 ctypes.byref(got)):
        return b""
    return buf.raw[: got.value]


def addr2line(exe, image_base, addrs, link_base=0x140000000):
    """Map runtime VAs to source lines. link_base = PE default for exes."""
    if not addrs:
        return {}
    rebased = [hex(a - image_base + link_base) for a in addrs]
    try:
        out = subprocess.run(
            ["addr2line", "-f", "-C", "-e", exe] + rebased,
            capture_output=True, text=True, timeout=60).stdout.splitlines()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}
    res = {}
    for i, a in enumerate(addrs):
        fn = out[2 * i] if 2 * i < len(out) else "?"
        loc = out[2 * i + 1] if 2 * i + 1 < len(out) else "?"
        res[a] = f"{fn} [{loc}]"
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--exe", default="", help="exe path for addr2line")
    ap.add_argument("--stack-words", type=int, default=4096)
    args = ap.parse_args()

    hproc = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ,
                            False, args.pid)
    if not hproc:
        sys.exit(f"OpenProcess failed (err {ctypes.get_last_error()})")
    base, size, mainmod = main_module_range(hproc)
    base = base or 0
    print(f"main module: {mainmod} base=0x{base:X} size=0x{size or 0:X}")
    exe = args.exe or mainmod

    reports = []
    for tid in thread_ids(args.pid):
        h = k32.OpenThread(THREAD_ALL, False, tid)
        if not h:
            continue
        name = thread_name(h)
        ctx = CONTEXT64()
        ctx.ContextFlags = CONTEXT_FULL_AMD64
        rip = rsp = 0
        if k32.SuspendThread(h) != wt.DWORD(-1).value:
            if k32.GetThreadContext(h, ctypes.byref(ctx)):
                rip, rsp = ctx.Rip, ctx.Rsp
            k32.ResumeThread(h)
        k32.CloseHandle(h)

        frames = []
        stack_read = 0
        if rsp:
            raw = read_mem(hproc, rsp, args.stack_words * 8)
            if not raw:
                # straddled an unreadable page boundary: retry in 4K chunks
                chunks = []
                for pg in range(0, args.stack_words * 8, 4096):
                    c = read_mem(hproc, rsp + pg, 4096)
                    if not c:
                        break
                    chunks.append(c)
                raw = b"".join(chunks)
            stack_read = len(raw)
            for off in range(0, len(raw) - 7, 8):
                (val,) = struct.unpack_from("<Q", raw, off)
                if base <= val < base + (size or 0):
                    frames.append(val)
        reports.append((tid, name, rip, rsp, frames, stack_read))

    want = set()
    for _, _, rip, _, frames, _ in reports:
        if base <= rip < base + (size or 0):
            want.add(rip)
        want.update(frames[:40])
    sym = addr2line(exe, base, sorted(want)) if exe else {}

    for tid, name, rip, rsp, frames, stack_read in reports:
        in_exe = base <= rip < base + (size or 0)
        riploc = sym.get(rip, "") if in_exe else "(outside main exe)"
        print(f"\n== tid {tid} {name!r} RIP=0x{rip:X} RSP=0x{rsp:X} "
              f"stack_read={stack_read} {riploc}")
        seen = set()
        shown = 0
        for f in frames:
            s = sym.get(f, hex(f))
            if s in seen:
                continue
            seen.add(s)
            print(f"    {hex(f)}  {s}")
            shown += 1
            if shown >= 25:
                break

    k32.CloseHandle(hproc)


if __name__ == "__main__":
    main()
