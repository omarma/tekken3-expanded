#!/usr/bin/env python3
"""Guard the OpenGL/software parity path for native-wide 2D edge fill."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    source = (ROOT / "runtime/src/main.cpp").read_text(encoding="utf-8")
    gl_start = source.find(
        "if (g_gl_active && g_gl_fbo_present && !di.depth24) {")
    gl_end = source.find(
        "if (g_gl_active && !di.depth24) gl_renderer_sync_cpu();", gl_start)
    if gl_start < 0 or gl_end < 0:
        raise AssertionError("missing OpenGL 15-bit presentation block")
    gl_block = source[gl_start:gl_end]

    if "if (wide_present && !wide_2d_edge_fill)" not in gl_block:
        raise AssertionError(
            "direct wide-FBO present must be bypassed for the 2D fill")
    if "else if (!wide_2d_edge_fill)" not in gl_block:
        raise AssertionError(
            "2D fill must not fall into canonical gl_renderer_present_vram")

    cpu_start = source.find("if (wide_present) {", gl_end)
    cpu_end = source.find("/* depth24", cpu_start)
    if cpu_start < 0 or cpu_end < 0:
        raise AssertionError("missing shared CPU native-wide compositor block")
    cpu_block = source[cpu_start:cpu_end]
    read_at = cpu_block.find("gr_render_wide_display(")
    gate_at = cpu_block.find("if (wide_2d_edge_fill)")
    fill_at = cpu_block.find("psx_ws_fill_2d_edges_argb(")
    if not (0 <= read_at < gate_at < fill_at):
        raise AssertionError(
            "edge fill must run after the backend's complete wide-surface read")

    print("PASS: 2D fill shares the CPU compositor and cannot bleed canonical VRAM")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
