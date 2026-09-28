#!/usr/bin/env python3
"""Guard sidecar margin invalidation order and GL/SW backend parity."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]


def body(source: str, signature: str) -> str:
    start = source.find(signature)
    if start < 0:
        raise AssertionError(f"missing function: {signature}")
    brace = source.find("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1:index]
    raise AssertionError(f"unterminated function: {signature}")


def main() -> int:
    gpu = (ROOT / "runtime/src/gpu.c").read_text(encoding="utf-8")
    gl = (ROOT / "runtime/src/gpu_gl_renderer.c").read_text(encoding="utf-8")
    sw = (ROOT / "runtime/src/gpu_sw_renderer.c").read_text(encoding="utf-8")

    begin = body(gpu, "void gpu_ws_begin_linked_list(void)")
    if begin.find("ws_nw_sync_target();") > begin.find(
            "ws_refresh_current_reveal_margins();"):
        raise AssertionError("linked-list target must be selected before refresh")

    refresh = body(gpu, "static void ws_refresh_current_reveal_margins(void)")
    if "!ws_clear_reveal" not in refresh:
        raise AssertionError("per-frame margin refresh must remain title-opt-in")
    stamp = refresh.find("psx_ws_margin_refresh_once(")
    clear = refresh.find("gr_wide_clear_margins(")
    if stamp < 0 or clear < 0 or stamp >= clear:
        raise AssertionError("per-frame stamp must gate the backend clear")

    for signature in (
            "static void gp0_exec_draw_area_tl(void)",
            "static void gp0_exec_draw_area_br(void)"):
        draw_env = body(gpu, signature)
        if draw_env.find("ws_nw_sync_target();") > draw_env.find(
                "ws_refresh_current_reveal_margins();"):
            raise AssertionError(f"{signature} refreshes before selecting target")

    execute = body(gpu, "static void gp0_execute_command(void)")
    if "ws_refresh_current_reveal_margins();" not in execute:
        raise AssertionError("full sidecar must wait for the primitive draw environment")
    if "(int)draw_area_top" not in refresh or "draw_area_bottom + 1u" not in refresh:
        raise AssertionError("partial redraw must preserve untouched sidecar rows")
    if "gr_wide_restore_background" in gpu or "s_wide_bg_fbo" in gl:
        raise AssertionError("old-camera background reconstruction must not return")

    if "static void glb_wide_clear_margins(" not in gl:
        raise AssertionError("OpenGL margin clear backend missing")
    if "void sw_wide_clear_margins(" not in sw:
        raise AssertionError("software margin clear backend missing")

    print("PASS: native-wide margins refresh before draws with GL/SW parity")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
