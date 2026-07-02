@echo off
rem Build the shippable MyWhisper.exe (folder build under dist\MyWhisper).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" ( echo Run setup.bat first & exit /b 1 )
echo Installing build tooling...
".venv\Scripts\python.exe" -m pip install --upgrade pyinstaller >nul
echo Building (this takes a few minutes and produces a large folder)...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean MyWhisper.spec
if errorlevel 1 ( echo BUILD FAILED & exit /b 1 )
echo.
echo Done.  Ship the folder:  dist\MyWhisper\
echo Run it with:            dist\MyWhisper\MyWhisper.exe
