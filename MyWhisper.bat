@echo off
rem Start MyWhisper silently in the background (no console window).
rem Look for the mic icon in the system tray; logs in logs\mywhisper.log.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo venv not found - run setup.bat first.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0launch.pyw"
