@echo off
rem MyWhisper one-time setup: create venv (Python 3.11) + install dependencies.
cd /d "%~dp0"
py -3.11 -m venv .venv || python -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
echo.
echo Setup done. Verify with:  run.bat --doctor
