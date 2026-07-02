@echo off
rem Remove MyWhisper from Windows startup.
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v MyWhisper /f
echo MyWhisper autostart removed.
pause
