#!/bin/bash
# Tekken 3 Expanded for Android, on macOS: your game files once, then the APK
# (Tekken3Expanded.apk) to install on an arm64 phone. Double-click it, or run
# it from Terminal. Game files stay on this Mac. With options (--install,
# -D...) it runs tools/android/make_apk.py in the terminal, for a game already
# prepared.
cd "$(dirname "$0")" || exit 1
. launcher/prepare_python.sh || exit 1
python=$venv/bin/python

if [ $# -gt 0 ]; then
    "$python" tools/android/make_apk.py "$@"
    status=$?
    [ -t 0 ] && read -r -p "Press Return to close." _
    exit $status
fi
# The window if Tk is there (brew install python-tk@3.13), else questions here.
if "$python" -c 'import tkinter' 2>/dev/null; then
    exec "$python" launcher/easy_launcher.py --android-only
fi
# A game already prepared here: its APK (updated first if needed); else the
# files, then the Android game alone.
if "$python" -c 'import sys; sys.path.insert(0, "launcher"); import setup_backend as b; sys.exit(not (b.ready() or b.android_ready() or b.load_json(b.STATE/"ready.json")))'; then
    args=(--text --android)
else
    echo "Tekken 3 Expanded for Android. Drag each file onto this window, then press Return."
    ask() { local answer; read -r -p "$1: " answer; answer=${answer%\'}; answer=${answer#\'}; answer=${answer%\ }; printf '%s' "${answer//\\ / }"; }
    disc=$(ask "Your Tekken 3 USA disc (.cue)")
    ttt1=$(ask "Your TTT1 arcade ROM (tektagt.zip)")
    tekken3=$(ask "Optional, your Tekken 3 arcade ROM (tekken3.zip) for the arcade difficulty levels; Return to skip")
    read -r -p "Add Jin's red lightning? [y/N] " jin
    args=(--text --android-only --disc "$disc" --ttt1 "$ttt1")
    [ -n "$tekken3" ] && args+=(--tekken3 "$tekken3")
    [[ "$jin" =~ ^[yYoO] ]] && args+=(--jin-red-lightning)
fi
"$python" launcher/setup_backend.py "${args[@]}"
status=$?
[ $status -ne 0 ] && read -r -p "Stopped (log: .setup/setup.log). Press Return to close." _
exit $status
