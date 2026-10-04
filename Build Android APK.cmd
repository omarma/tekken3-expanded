@echo off
rem Tekken 3 Expanded for Android, on Windows: your game files once, then the
rem APK (Tekken3Expanded.apk) to install on an arm64 phone. Double-click it.
rem Needs Python 3.10 or later from python.org (with the py launcher and Tk).
rem With options (--install, -D...) it runs tools\android\make_apk.py in the
rem console, for a game already prepared.
cd /d "%~dp0"
if not exist ".setup\venv\Scripts\python.exe" (
    py -3 -m venv .setup\venv || (echo Install Python 3.12 from https://www.python.org, then run this again.& pause & exit /b 1)
)
rem Also after an install cut short (no network, window closed): the venv then exists without them.
.setup\venv\Scripts\python.exe -c "import PIL, numpy" 2>nul || (
    .setup\venv\Scripts\python.exe -m pip install --quiet --require-hashes --only-binary=:all: -r tools\requirements-pip.txt || (echo Could not install pip.& pause & exit /b 1)
    .setup\venv\Scripts\python.exe -m pip install --quiet --require-hashes --only-binary=:all: -r tools\requirements-import.txt || (echo Could not install Pillow and numpy.& pause & exit /b 1)
)
if "%~1"=="" (
    start "" ".setup\venv\Scripts\pythonw.exe" launcher\easy_launcher.py --android-only
    exit /b 0
)
".setup\venv\Scripts\python.exe" tools\android\make_apk.py %*
set status=%errorlevel%
pause
exit /b %status%
