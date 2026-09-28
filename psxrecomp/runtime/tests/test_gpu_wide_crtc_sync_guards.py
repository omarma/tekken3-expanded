#!/usr/bin/env python3
"""Guard native-wide target resync on both GP1 horizontal-width changes.

Tekken-style menu/game transitions can change the CRTC width through GP1(06h)
or GP1(08h) without immediately reissuing the GP0 draw-area commands that also
resynchronise the wide renderer. This source-level regression test keeps those
two uncommon-but-critical hooks ordered after their state updates, and keeps
the 4:3/off path an explicit disable rather than a wide allocation.
"""

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
        cursor = start + len(signature)
        while cursor < len(source) and source[cursor].isspace():
            cursor += 1
        if cursor < len(source) and source[cursor] == "{":
            brace = cursor
            break
        # Skip forward declarations such as ws_nw_sync_target(void);.
        search_from = cursor + 1
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1:index]
    raise AssertionError(f"unterminated body: {signature}")


def require_order(body: str, earlier: str, later: str, message: str) -> None:
    early_at = body.find(earlier)
    late_at = body.find(later)
    if early_at < 0 or late_at < 0 or early_at >= late_at:
        raise AssertionError(message)


def main() -> int:
    source = (ROOT / "runtime/src/gpu.c").read_text(encoding="utf-8")
    h_range = function_body(
        source, "static void gp1_h_display_range(uint32_t val)")
    mode = function_body(source, "static void gp1_display_mode(uint32_t val)")
    sync = function_body(source, "static void ws_nw_sync_target(void)")

    require_order(
        h_range, "h_display_x2 =", "ws_nw_sync_target();",
        "GP1(06h) must resync after committing both horizontal-range fields")
    if h_range.count("ws_nw_sync_target();") != 1:
        raise AssertionError("GP1(06h) must perform exactly one wide resync")

    require_order(
        mode, "hres1 =", "ws_nw_sync_target();",
        "GP1(08h) must resync after committing hres1")
    require_order(
        mode, "hres2 =", "ws_nw_sync_target();",
        "GP1(08h) must resync after committing hres2")
    if mode.count("ws_nw_sync_target();") != 1:
        raise AssertionError("GP1(08h) must perform exactly one wide resync")

    gate = "if (!ws_native_wide_active()) { gr_wide_disable_target(); return; }"
    if gate not in sync:
        raise AssertionError(
            "wide resync lost its 4:3/off identity gate before configuration")
    require_order(
        sync, gate, "gr_wide_configure(",
        "4:3/off must return before native-wide target configuration")

    print("PASS: both GP1 width changes resync wide geometry; 4:3 stays identity")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
