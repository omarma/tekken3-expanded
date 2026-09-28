#!/usr/bin/env bash
# Build duckstation-qt.exe (Release x64). Requires tools/duckstation/setup.sh to
# have succeeded first (submodule initialized, deps extracted, patch applied).
#
# Uses the CMake that ships with Visual Studio 2022 (the system mingw64 cmake
# does not know the VS generator) and the MSBuild from the same toolchain.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DUCK="$REPO_ROOT/duckstation"
CMAKE="/c/Program Files/Microsoft Visual Studio/2022/Community/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe"
MSBUILD="/c/Program Files/Microsoft Visual Studio/2022/Community/MSBuild/Current/Bin/MSBuild.exe"

if [ ! -x "$CMAKE" ]; then
    echo "ERROR: VS-bundled CMake not found at $CMAKE"
    echo "  install Visual Studio 2022 Community with 'Desktop development with C++' workload"
    exit 1
fi
if [ ! -x "$MSBUILD" ]; then
    echo "ERROR: MSBuild not found at $MSBUILD"
    exit 1
fi

cd "$DUCK"
if [ ! -f build/duckstation.sln ]; then
    echo "[duckstation-build] configuring CMake (Visual Studio 17 2022, x64, Release)..."
    "$CMAKE" -S . -B build -G "Visual Studio 17 2022" -A x64 -DCMAKE_BUILD_TYPE=Release
fi

echo "[duckstation-build] compiling duckstation-qt + duckstation-qt-rcc (Release|x64)..."
# Build both targets — duckstation-qt-rcc compiles data/resources into
# build/bin/resources/duckstation-qt.rcc which the binary loads at startup.
# Without it the binary shows "duckstation-qt.rcc could not be loaded" and exits.
"$MSBUILD" build/duckstation.sln \
    -p:Configuration=Release \
    -p:Platform=x64 \
    -t:duckstation-qt\;duckstation-qt-rcc \
    -m \
    -verbosity:minimal \
    -nologo

# MSBuild lands the exe in build/bin/Release/ but the DLLs live at build/bin/.
# Copy the exe up so it can find its Qt / SDL3 / etc. runtime.
if [ -f "$DUCK/build/bin/Release/duckstation-qt.exe" ]; then
    cp -f "$DUCK/build/bin/Release/duckstation-qt.exe" "$DUCK/build/bin/duckstation-qt.exe"
fi

# Headless-launch provisioning: portable marker, BIOS image, minimal settings.ini
# (idempotent — only writes if missing).
touch "$DUCK/build/bin/portable.txt"

if [ ! -f "$DUCK/build/bin/bios/SCPH1001.BIN" ] && [ -f "$REPO_ROOT/bios/SCPH1001.BIN" ]; then
    mkdir -p "$DUCK/build/bin/bios"
    cp "$REPO_ROOT/bios/SCPH1001.BIN" "$DUCK/build/bin/bios/"
    echo "[duckstation-build] copied SCPH1001.BIN into $DUCK/build/bin/bios/"
fi

# settings.ini with BIOS config + setup-wizard bypass. First launch creates a
# default; we post-process it to set the headless-friendly fields. Idempotent.
SETTINGS="$DUCK/build/bin/settings.ini"
if [ ! -f "$SETTINGS" ]; then
    # Let DS generate a default by running briefly (it writes settings.ini on first
    # launch and exits if no autoboot target is present). We then patch it.
    timeout 3 "$DUCK/build/bin/duckstation-qt.exe" -nogui 2>/dev/null || true
fi
if [ -f "$SETTINGS" ]; then
    python3 "$REPO_ROOT/tools/add_ds_bios_paths.py" "$SETTINGS" 2>/dev/null || true
    python3 "$REPO_ROOT/tools/add_ds_setup_bypass.py" "$SETTINGS" 2>/dev/null || true
fi

echo "[duckstation-build] done. binary at: $DUCK/build/bin/duckstation-qt.exe"
