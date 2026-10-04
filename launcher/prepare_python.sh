# Sourced by Setup Tekken 3.command and Build Android APK.command (macOS):
# the tools the setup needs, then Python in .setup/venv with the import's
# packages. Sets $venv; returns non-zero after telling the player what to do.
missing=()
for tool in cmake ninja; do command -v "$tool" >/dev/null || missing+=("$tool"); done
if [ ${#missing[@]} -gt 0 ]; then
    echo "Missing: ${missing[*]}. Install them with Homebrew (https://brew.sh):"
    echo "    brew install cmake ninja sdl3"
    read -r -p "Press Return to close." _; return 1
fi
xcode-select -p >/dev/null 2>&1 || { echo "No compiler: run  xcode-select --install  then open this again."; read -r -p "Press Return to close." _; return 1; }

# Python 3.10 or later whose pip works (pip needs pyexpat).
venv=.setup/venv
if [ ! -x "$venv/bin/python" ] || ! "$venv/bin/python" -c 'import PIL, numpy' 2>/dev/null; then
    python=""
    for p in python3.13 python3.12 python3.11 python3.10 python3.14 python3; do
        if command -v "$p" >/dev/null && "$p" -c 'import sys, pyexpat, venv; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
            python=$p; break
        fi
    done
    if [ -z "$python" ]; then
        echo "Python 3.10 or later is needed:  brew install python@3.13"
        read -r -p "Press Return to close." _; return 1
    fi
    echo "Preparing Python ($("$python" --version)) in $venv..."
    rm -rf "$venv"
    # Exact versions, every file checked against its SHA-256, wheels only
    # (tools/update_requirements.py writes the lists).
    "$python" -m venv "$venv" \
        && "$venv/bin/python" -m pip install --quiet --require-hashes --only-binary=:all: -r tools/requirements-pip.txt \
        && "$venv/bin/python" -m pip install --quiet --require-hashes --only-binary=:all: -r tools/requirements-import.txt \
        || { echo "Could not install Pillow and numpy."; read -r -p "Press Return to close." _; return 1; }
fi
