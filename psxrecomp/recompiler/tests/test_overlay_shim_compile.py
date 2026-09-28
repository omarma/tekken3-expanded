#!/usr/bin/env python3
"""Compile the overlay callback shim against the public runtime headers."""

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[2]
INCLUDE = ROOT / "runtime" / "include"


def find_gcc() -> str:
    candidates = [
        os.environ.get("CC"),
        r"C:\msys64\mingw64\bin\gcc.exe" if os.name == "nt" else None,
        shutil.which("gcc"),
        shutil.which("cc"),
    ]
    for candidate in candidates:
        if candidate and pathlib.Path(candidate).is_file():
            return candidate
    raise SystemExit("gcc/cc is required for the overlay shim compile test")


def main() -> int:
    source = r'''#include "cpu_state.h"
#include "overlay_dispatch_preamble.c.inc"

void func_80010000(CPUState *cpu) {
    psx_cyc_bb_defer_begin();
    psx_cyc_charge(1u);
    psx_advance_cycles(1u);
    cpu->gpr[2] = psx_cyc_load_word(cpu, cpu->gpr[4], 2u, 0u);
    cpu->gpr[3] = psx_cyc_load_half(cpu, cpu->gpr[5], 3u, 0u);
    psx_cyc_bb_defer_flush();
    psx_cyc_bb_defer_end();
    if (psx_slice_block(cpu, 0x80010000u, 1u, 0)) return;
    debug_server_log_call_entry(0x80010000u);
}
static uint32_t test_full_angle(uint32_t vanilla) { return vanilla + 200u; }
#ifdef _WIN32
__declspec(dllexport)
#endif
int check_full_angle_bridge(void) {
    OverlayCallbacks callbacks = {0};
    overlay_init(&callbacks);
    if (psx_ws_full_angle_widen(600u) != 600u) return 0;
    callbacks.ws_full_angle_widen = test_full_angle;
    overlay_init(&callbacks);
    return psx_ws_full_angle_widen(600u) == 800u;
}
'''
    gcc = find_gcc()
    cpu_header = (INCLUDE / "cpu_state.h").read_text(encoding="utf-8")
    cycles_header = (INCLUDE / "psx_cycles.h").read_text(encoding="utf-8")
    for name, header in (("cpu_state.h", cpu_header),
                         ("psx_cycles.h", cycles_header)):
        if "__declspec(dllexport) void overlay_flush_cycles(void);" not in header:
            raise AssertionError(
                f"{name} must declare the Windows overlay flush export before "
                "the dispatch preamble defines it")
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = pathlib.Path(temp_dir)
        c_path = temp / "overlay_shim_contract.c"
        out_path = temp / ("overlay_shim_contract.dll" if os.name == "nt"
                           else "overlay_shim_contract.so")
        c_path.write_text(source, encoding="ascii")
        command = [
            gcc, "-shared", "-O2",
            "-DPSX_OVERLAY_DLL_BUILD",
            "-DPSX_NO_DEBUG_TOOLS",
            "-DPSX_ENABLE_BLOCK_CYCLES=1",
            "-DPSX_OVERLAY_FLAVOR=0",
        ]
        if os.name != "nt":
            command.append("-fPIC")
        command.extend([
            str(c_path), "-o", str(out_path), f"-I{INCLUDE}", "-lm",
        ])
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
            return result.returncode
        if not out_path.is_file():
            raise AssertionError("overlay compiler reported success without output")
        # Use a child process so Windows releases the DLL before temp cleanup.
        subprocess.run([
            sys.executable, "-c",
            "import ctypes, sys; dll = ctypes.CDLL(sys.argv[1]); "
            "assert dll.check_full_angle_bridge() == 1", str(out_path)
        ], check=True)
    print("PASS: overlay callback shim compiles against runtime headers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
