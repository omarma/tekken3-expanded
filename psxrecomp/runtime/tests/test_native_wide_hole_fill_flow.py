#!/usr/bin/env python3
"""Source guard for the dormant GL synthetic-margin reconstruction path."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "src" / "gpu_gl_renderer.c").read_text(encoding="utf-8")


def require(fragment: str, reason: str) -> None:
    assert fragment in SRC, reason


require("gpu_ws_nw_backdrop_enabled()", "reconstruction must be title opt-in")
assert "wide_hole_fill_arm_current" not in SRC, (
    "framebuffer edge-copy reconstruction must remain disarmed"
)
require("hole_fill ? g_wide_off * s_scale : 0", "presentation must use per-surface arming")
require("(float)PSX_WS_HOLE_ALPHA / 255.0f", "margin clear needs impossible alpha")
require("if(c.a>0.49 && c.a<0.51)", "shader must classify sentinel explicitly")
require("return texelFetch(t,p,0);", "holes must use the exact same-row edge texel")
require("return texture(t,uv);", "covered geometry must retain configured filtering")
require("if(c.a<0.75) discard", "sentinel must never rebuild the PS1 mask stencil")
require("psx_ws_resolve_margin_holes_argb", "CPU capture/dump must match direct present")

print("native wide hole fill flow: PASS")
