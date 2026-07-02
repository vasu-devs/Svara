@echo off
rem MyWhisper launcher — activates the venv and starts the app.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo venv not found — run setup.bat first.
    exit /b 1
)
".venv\Scripts\python.exe" -m mywhisper %*
