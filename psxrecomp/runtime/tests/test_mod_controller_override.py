#!/usr/bin/env python3
"""Guard the game-owned controller-mode override lifecycle."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "runtime" / "src" / "main.cpp").read_text(encoding="utf-8")
HEADER = (ROOT / "runtime" / "include" / "mod_plugins.h").read_text(
    encoding="utf-8"
)

for symbol in (
    "PSX_MOD_CONTROLLER_HYBRID",
    "PSX_MOD_CONTROLLER_ANALOG",
    "PSX_MOD_CONTROLLER_DIGITAL",
    "psx_mod_set_controller_mode_override",
):
    assert symbol in HEADER, f"missing trusted-plugin controller API: {symbol}"

reset0 = "g_mod_controller_mode_override[0] = -1;"
reset1 = "g_mod_controller_mode_override[1] = -1;"
activate = "mod_runtime_activate_plugins();"
apply0 = "player_mode[0] = g_mod_controller_mode_override[0];"
apply1 = "player_mode[1] = g_mod_controller_mode_override[1];"

for snippet in (reset0, reset1, activate, apply0, apply1):
    assert snippet in MAIN, f"missing controller override lifecycle step: {snippet}"

assert MAIN.index(reset0) < MAIN.index(activate) < MAIN.index(apply0)
assert MAIN.index(reset1) < MAIN.index(activate) < MAIN.index(apply1)

print("mod controller override lifecycle guard passed")
