@echo off
rem Tekken 3 Expanded on Windows: first setup, then play.
rem Needs Python 3.10 or later from python.org (with the py launcher and Tk).
cd /d "%~dp0"
if not exist ".setup\venv\Scripts\python.exe" (
    py -3 -m venv .setup\venv || (echo Install Python 3.12 from https://www.python.org, then run this again.& pause & exit /b 1)
)
rem Also after an install cut short (no network, window closed): the venv then exists without them.
.setup\venv\Scripts\python.exe -c "import PIL, numpy" 2>nul || (
    .setup\venv\Scripts\python.exe -m pip install --quiet -r tools\requirements-import.txt || (echo Could not install Pillow and numpy.& pause & exit /b 1)
)
start "" ".setup\venv\Scripts\pythonw.exe" launcher\easy_launcher.py %*
