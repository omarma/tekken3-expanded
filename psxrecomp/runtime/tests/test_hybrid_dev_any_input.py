#!/usr/bin/env python3
"""Guard Hybrid mode's explicitly opt-in dev-any routing."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "runtime" / "src" / "main.cpp").read_text(encoding="utf-8")

assert "strict single-device-per-port routing is the default" in MAIN
for truthy in ('"1"', '"true"', '"yes"', '"on"'):
    assert f"value == {truthy}" in MAIN
assert "e && (e[0] == '0'" not in MAIN, (
    "PSX_DEV_INPUT must not use the old default-on/explicit-disable predicate"
)

assert "hybrid_stick_active(const PlayerInput& p, const PadSources& src)" in MAIN
assert "hybrid_dpad_active(const PlayerInput& p, int player," in MAIN
assert "hybrid_stick_active(p, src)" in MAIN
assert "hybrid_dpad_active(p, player, src)" in MAIN

stick_body = MAIN.split(
    "static bool hybrid_stick_active(const PlayerInput& p, const PadSources& src)", 1
)[1].split("static bool hybrid_dpad_active", 1)[0]
dpad_body = MAIN.split(
    "static bool hybrid_dpad_active(const PlayerInput& p, int player,",
    1,
)[1].split("/* Sample each player's live device state", 1)[0]

for name, body, detector in (
    ("stick", stick_body, "controller_stick_active(handle, controller_deadzone)"),
    ("D-pad", dpad_body, "controller_dpad_active(handle)"),
):
    assert "SDL_NumJoysticks()" in body, (
        f"Hybrid {name} detection must inspect all dev-any controllers"
    )
    assert "SDL_GameControllerFromInstanceID" in body
    assert detector in body

print("Hybrid dev-any physical-controller guard passed")
