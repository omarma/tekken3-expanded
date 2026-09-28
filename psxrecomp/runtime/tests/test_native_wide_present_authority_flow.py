#!/usr/bin/env python3
"""Guard bounded centre ownership across GL/SW native-wide presentation."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]


def function_body(source: str, signature: str) -> str:
    search_from = 0
    brace = -1
    while True:
        start = source.find(signature, search_from)
        if start < 0:
            raise AssertionError(f"missing function body: {signature}")
        brace = source.find("{", start + len(signature))
        semicolon = source.find(";", start + len(signature))
        if brace >= 0 and (semicolon < 0 or brace < semicolon):
            break
        search_from = start + len(signature)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1:index]
    raise AssertionError(f"unterminated function: {signature}")


def require_order(body: str, *needles: str) -> None:
    cursor = -1
    for needle in needles:
        found = body.find(needle, cursor + 1)
        if found < 0:
            raise AssertionError(f"missing ordered authority-flow token: {needle}")
        cursor = found


def main() -> int:
    header = (ROOT / "runtime/include/native_wide_present_authority.h").read_text(
        encoding="utf-8")
    gl = (ROOT / "runtime/src/gpu_gl_renderer.c").read_text(encoding="utf-8")
    sw = (ROOT / "runtime/src/gpu_sw_renderer.c").read_text(encoding="utf-8")
    runtime = (ROOT / "runtime/src/main.cpp").read_text(encoding="utf-8")

    if "(fast_center_mode && !sidecar_complete) || !mirror_authoritative" not in header:
        raise AssertionError("fast GL mode lost its bounded complete-sidecar contract")
    if "return !mirror_authoritative;" not in header:
        raise AssertionError("authoritative wide frames can enter duplicate-present skip")

    blit = function_body(gl, "static void wide_blit_center(")
    if "psx_ws_wide_center_splice_required(" not in blit:
        raise AssertionError("GL centre splice is not controlled by shared authority policy")
    for signature in (
        "static int glb_render_wide_display(",
        "static int glb_wide_dump_full(",
        "int gl_renderer_present_wide_fbo(",
    ):
        body = function_body(gl, signature)
        if "wide_blit_center(" not in body:
            raise AssertionError(f"{signature} bypasses the shared centre policy")

    direct = function_body(gl, "int gl_renderer_present_wide_fbo(")
    require_order(
        direct,
        "psx_ws_wide_duplicate_present_may_skip(",
        "s_last_present_path == GL_PRES_WIDE",
        "s_probe_skip++",
    )
    if direct.count("s_wide_mirror_authoritative = 0;") < 2:
        raise AssertionError("GL direct-wide failure paths retain stale authority")

    for signature in (
        "static void glb_wide_disable_target(",
        "void gl_renderer_shutdown(",
        "void gl_renderer_set_wide_fast(",
    ):
        if "s_wide_mirror_authoritative = 0;" not in function_body(gl, signature):
            raise AssertionError(f"{signature} does not close wide authority")

    if "s_wide_sidecar_complete" not in blit:
        raise AssertionError("GL centre splice ignores exact sidecar completeness")
    mirror_cull = function_body(gl, "static int mirror_x_center_only(")
    if "s_wide_sidecar_complete" not in mirror_cull:
        raise AssertionError("complete selector still loses centre-only GL batches")

    for signature in (
        "int sw_render_wide_display(",
        "int sw_wide_dump_full(",
    ):
        body = function_body(sw, signature)
        require_order(body, "psx_ws_wide_center_splice_required(",
                      "if (splice_center)", "wide_splice_canonical_row(")
    if "g_wide_mirror_authoritative = 0;" not in function_body(
            sw, "void sw_wide_disable_target("):
        raise AssertionError("software target disable retains stale authority")

    present = function_body(runtime,
                            "static NetplayVblankEpilogue sdl_vblank_present_body(")
    require_order(
        present,
        "gr_wide_set_mirror_authoritative(0);",
        "psx_ws_wide_mirror_authority_allowed(",
        "gr_wide_set_mirror_authoritative(",
        "gl_renderer_present_wide_fbo(",
    )
    if "wide_2d_edge_fill ? 1 : 0" not in present:
        raise AssertionError("GTE-quiet/upload-heavy 2D no longer revokes authority")
    if "gr_wide_set_sidecar_complete(" not in present:
        raise AssertionError("selector completeness is not propagated to presentation")
    if "wide_present && !selector_sidecar_authoritative" not in present:
        raise AssertionError("2D edge fill can overwrite a complete selector sidecar")

    print("PASS: full-mirror authority is bounded; GL/SW splice and skip agree")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
