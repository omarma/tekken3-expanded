#!/bin/bash
# Tekken 3 Expanded on macOS: first setup, then play. Double-click it, or run it
# from Terminal. Game files stay on this Mac; only Python packages
# (tools/requirements-import.txt) are downloaded, into .setup/venv.
cd "$(dirname "$0")" || exit 1

missing=()
for tool in cmake ninja; do command -v "$tool" >/dev/null || missing+=("$tool"); done
command -v mame >/dev/null || [ -x /opt/homebrew/bin/mame ] || [ -x /usr/local/bin/mame ] || missing+=(mame)
if [ ${#missing[@]} -gt 0 ]; then
    echo "Missing: ${missing[*]}. Install them with Homebrew (https://brew.sh):"
    echo "    brew install cmake ninja sdl3 mame"
    read -r -p "Press Return to close." _; exit 1
fi
xcode-select -p >/dev/null 2>&1 || { echo "No compiler: run  xcode-select --install  then open this again."; read -r -p "Press Return to close." _; exit 1; }

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
        read -r -p "Press Return to close." _; exit 1
    fi
    echo "Preparing Python ($("$python" --version)) in $venv..."
    rm -rf "$venv"
    "$python" -m venv "$venv" && "$venv/bin/python" -m pip install --quiet --upgrade pip \
        && "$venv/bin/python" -m pip install --quiet -r tools/requirements-import.txt \
        || { echo "Could not install Pillow and numpy."; read -r -p "Press Return to close." _; exit 1; }
fi

# The window if Tk is there (brew install python-tk@3.13), else questions here.
if "$venv/bin/python" -c 'import tkinter' 2>/dev/null; then
    exec "$venv/bin/python" launcher/easy_launcher.py "$@"
fi
if "$venv/bin/python" -c 'import sys; sys.path.insert(0, "launcher"); import setup_backend as b; sys.exit(not b.ready())'; then
    exec "$venv/bin/python" -c 'import sys; sys.path.insert(0, "launcher"); import setup_backend as b; b.launch_game()'
fi
echo "Tekken 3 Expanded: first setup. Drag each file onto this window, then press Return."
ask() { local answer; read -r -p "$1: " answer; answer=${answer%\'}; answer=${answer#\'}; answer=${answer%\ }; printf '%s' "${answer//\\ / }"; }
disc=$(ask "Your Tekken 3 USA disc (.cue)")
ttt1=$(ask "Your TTT1 arcade ROM (tektagt.zip)")
tekken3=$(ask "Optional, your Tekken 3 arcade ROM (tekken3.zip) for the arcade difficulty levels; Return to skip")
read -r -p "Add Jin's red lightning? [y/N] " jin
args=(--text --play --disc "$disc" --ttt1 "$ttt1")
[ -n "$tekken3" ] && args+=(--tekken3 "$tekken3")
[[ "$jin" =~ ^[yYoO] ]] && args+=(--jin-red-lightning)
"$venv/bin/python" launcher/setup_backend.py "${args[@]}"
status=$?
[ $status -ne 0 ] && read -r -p "Setup stopped (log: .setup/setup.log). Press Return to close." _
exit $status
