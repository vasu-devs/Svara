@echo off
rem Make MyWhisper start automatically when you log in to Windows.
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v MyWhisper /t REG_SZ ^
    /d "\"%~dp0.venv\Scripts\pythonw.exe\" \"%~dp0launch.pyw\"" /f
if %errorlevel%==0 (
    echo MyWhisper will now start automatically at login.
) else (
    echo Failed to write the registry entry.
)
pause
