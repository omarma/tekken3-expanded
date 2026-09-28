"""Launch duckstation-qt.exe so it survives the parent shell exiting.

Uses CREATE_NEW_PROCESS_GROUP (no DETACHED_PROCESS) so the GUI window stays
visible — important for the one-time setup-wizard walkthrough.

Usage:
    python3 tools/duckstation/launch.py                          # GUI (first run / wizard)
    python3 tools/duckstation/launch.py -bios -nogui -fastboot   # headless oracle
"""
import subprocess, os, sys, pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BIN = REPO_ROOT / "duckstation" / "build" / "bin"
EXE = BIN / "duckstation-qt.exe"

if not EXE.exists():
    sys.stderr.write(f"not found: {EXE}\nrun tools/duckstation/build.sh first\n")
    sys.exit(1)

args = [str(EXE)] + sys.argv[1:]
CREATE_NEW_PROCESS_GROUP = 0x200
subprocess.Popen(args, cwd=str(BIN), creationflags=CREATE_NEW_PROCESS_GROUP, close_fds=True)
print(f"spawned: {' '.join(args)}")
