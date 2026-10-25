@echo off
cd /d "%~dp0"
if exist "dist\SanLex\SanLex.exe" (
    start "" "dist\SanLex\SanLex.exe"
    exit /b
)
if not exist ".venv\Scripts\pythonw.exe" (
    echo Set up the Python environment first. See README.md.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m sanlex --home "%~dp0local-data"
