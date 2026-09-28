# Native test-runtime for the cycle micro-benchmark ROM (ruler #2).
# Links the recompiled test EXE into the standard runtime so it boots the
# synthetic disc (disc/cyctest.cue) and runs the isolation loops with the real
# cost model. measure.py --port 4600 then reads per-iteration cycle costs to
# compare against the Beetle oracle (4382).
cmake_minimum_required(VERSION 3.20)
project(CycleTestROM C CXX)

set(CMAKE_C_STANDARD 99)
set(CMAKE_CXX_STANDARD 17)

# The psxrecomp worktree root is two levels up (tools/cycle_testrom -> worktree).
set(PSXRECOMP_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." CACHE PATH
    "Path to psxrecomp")

include("${PSXRECOMP_ROOT}/runtime/runtime.cmake")

set(GAME_GENERATED_FULL
    "${CMAKE_CURRENT_SOURCE_DIR}/generated/cycle_testrom.exe_full.c")
set(GAME_GENERATED_DISPATCH
    "${CMAKE_CURRENT_SOURCE_DIR}/generated/cycle_testrom.exe_dispatch.c")

psxrecomp_add_runtime_target(psx-cyctest
    GAME_GENERATED_FULL_C "${GAME_GENERATED_FULL}"
    GAME_GENERATED_DISPATCH_C "${GAME_GENERATED_DISPATCH}"
    DEBUG_PORT 4600
    WINDOW_TITLE "Cycle Test ROM"
    DEFAULT_BIOS_PATH "${PSXRECOMP_ROOT}/bios/SCPH1001.BIN"
    DEFAULT_GAME_CONFIG_PATH "game.toml"
)
