#!/usr/bin/env sh
# Bootstrap a source checkout for local PSXRecomp development on Linux/macOS.
#
# This builds the CLI/recompiler tools from source. If bios/SCPH1001.BIN is
# present, it also refreshes generated BIOS C before building the BIOS-only
# runtime target. Game projects should be generated with the CLI; this script
# intentionally does not patch runtime/CMakeLists.txt with per-game targets.

set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BUILD_TYPE=${BUILD_TYPE:-Release}
CLI_BUILD_DIR=${CLI_BUILD_DIR:-recompiler/build-cli}
RUNTIME_BUILD_DIR=${RUNTIME_BUILD_DIR:-runtime/build-dev}

cd "$ROOT"

missing=""

need_cmd() {
    if command -v "$1" >/dev/null 2>&1; then
        printf '  [ok]      %s\n' "$1"
    else
        printf '  [missing] %s\n' "$1"
        missing="$missing $1"
    fi
}

printf '%s\n' '== Checking host tools =='
need_cmd cmake
need_cmd python3

if command -v ninja >/dev/null 2>&1; then
    printf '%s\n' '  [ok]      ninja'
else
    printf '%s\n' '  [warn]    ninja not found; CMake will use its default generator'
fi

if command -v cc >/dev/null 2>&1 || command -v gcc >/dev/null 2>&1 || command -v clang >/dev/null 2>&1; then
    printf '%s\n' '  [ok]      C compiler'
else
    printf '%s\n' '  [missing] C compiler'
    missing="$missing c-compiler"
fi

if command -v c++ >/dev/null 2>&1 || command -v g++ >/dev/null 2>&1 || command -v clang++ >/dev/null 2>&1; then
    printf '%s\n' '  [ok]      C++ compiler'
else
    printf '%s\n' '  [missing] C++ compiler'
    missing="$missing cxx-compiler"
fi

if [ -n "$missing" ]; then
    cat <<EOF

Missing prerequisites:$missing

Debian/Ubuntu:
  sudo apt install build-essential cmake ninja-build python3

Fedora:
  sudo dnf install gcc gcc-c++ cmake ninja-build python3

macOS/Homebrew:
  brew install cmake ninja python3
EOF
    exit 1
fi

printf '\n%s\n' '== Building CLI/recompiler tools =='
python3 tools/build_cli.py release --build-dir "$CLI_BUILD_DIR"

can_build_runtime=0

if [ -f bios/SCPH1001.BIN ]; then
    printf '\n%s\n' '== Regenerating BIOS C =='
    sh tools/regen_bios.sh
    can_build_runtime=1
elif [ -f generated/SCPH1001_full.c ] && [ -f generated/SCPH1001_dispatch.c ]; then
    printf '\n%s\n' '== Using existing generated BIOS C =='
    printf '%s\n' 'bios/SCPH1001.BIN was not found; building with existing generated/SCPH1001_*.c.'
    can_build_runtime=1
else
    printf '\n%s\n' '== Skipping BIOS regeneration =='
    printf '%s\n' 'bios/SCPH1001.BIN and generated/SCPH1001_*.c were not found.'
    printf '%s\n' 'The CLI/recompiler tools are ready; add the BIOS and rerun to build psx-runtime.'
fi

if [ "$can_build_runtime" -eq 1 ]; then
    printf '\n%s\n' '== Building BIOS-only runtime =='
    generator_args=""
    if command -v ninja >/dev/null 2>&1; then
        generator_args="-G Ninja"
    fi

    # shellcheck disable=SC2086
    cmake -S runtime -B "$RUNTIME_BUILD_DIR" $generator_args -DCMAKE_BUILD_TYPE="$BUILD_TYPE"
    cmake --build "$RUNTIME_BUILD_DIR" --target psx-runtime --parallel
fi

cat <<EOF

Setup complete.

CLI package:
  dist/psxrecomp-cli-*

BIOS runtime:
  $RUNTIME_BUILD_DIR/psx-runtime
  (built only when bios/SCPH1001.BIN or generated/SCPH1001_*.c is present)

Generate a game project with the CLI, then build the generated project's build.sh
on Linux/macOS.
EOF
