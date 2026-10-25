#!/bin/bash
# Tekken 3 Expanded on Linux (experimental): first setup, then play. Run it
# from a terminal in this folder:  ./"Setup Tekken 3.sh"  (or  bash "Setup Tekken 3.sh").
# Game files stay on this computer; only Python packages
# (tools/requirements-import.txt) are downloaded, into .setup/venv. Once set
# up, "Tekken 3 Expanded" is in the applications menu.
cd "$(dirname "$(readlink -f "$0")")" || exit 1

. launcher/prepare_python.sh || exit 1

# The window if Tk is there (python3-tk, tk or python3-tkinter), else questions here.
if [ -n "${DISPLAY}${WAYLAND_DISPLAY}" ] && "$venv/bin/python" -c 'import tkinter; tkinter.Tk().destroy()' 2>/dev/null; then
    exec "$venv/bin/python" launcher/easy_launcher.py --setup "$@"
fi
# --settings: the game's launcher; otherwise always the setup (Tekken 3 Expanded.sh plays).
if [[ " $* " == *" --settings "* ]] && "$venv/bin/python" -c 'import sys; sys.path.insert(0, "launcher"); import setup_backend as b; sys.exit(not b.ready())'; then
    exec "$venv/bin/python" -c 'import sys; sys.path.insert(0, "launcher"); import setup_backend as b; b.launch_game(settings="--settings" in sys.argv)' "$@"
fi
# An earlier setup: an update, with the files it was set up with.
if [ -f .setup/ready.json ] && [ -f .setup/last-inputs.json ]; then
    echo "Tekken 3 Expanded: setup with the files you chose before."
    update=(--text --play --update)
    [[ " $* " == *" --settings "* ]] && update+=(--settings)
    "$venv/bin/python" launcher/setup_backend.py "${update[@]}" && exit 0
    echo "The update stopped (log: .setup/setup.log). If a file moved, give it again:"
fi
echo "Tekken 3 Expanded: first setup. Drag each file onto this window (or type its path), then press Return."
ask() { local answer; read -r -p "$1: " answer; answer=${answer%\'}; answer=${answer#\'}; answer=${answer%\ }; printf '%s' "${answer//\\ / }"; }
disc=$(ask "Your Tekken 3 USA disc (.cue)")
ttt1=$(ask "Your TTT1 arcade ROM (tektagt.zip)")
tekken3=$(ask "Optional, your Tekken 3 arcade ROM (tekken3.zip) for the arcade difficulty levels; Return to skip")
args=(--text --play --disc "$disc" --ttt1 "$ttt1")
[ -n "$tekken3" ] && args+=(--tekken3 "$tekken3")
[[ " $* " == *" --settings "* ]] && args+=(--settings)
"$venv/bin/python" launcher/setup_backend.py "${args[@]}"
status=$?
[ $status -ne 0 ] && read -r -p "Setup stopped (log: .setup/setup.log). Press Return to close." _
exit $status
