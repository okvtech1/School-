@echo off
REM Builds SchoolSystemSetup.exe on a Windows PC. Run from the kit folder:  build\windows\build_windows.bat
REM Needs once: Python 3.8 (32-bit) from python.org and Inno Setup 6 from jrsoftware.org. Customers need neither.
cd /d "%~dp0\..\.."
where py >nul 2>nul || (echo Python launcher "py" not found. Install Python 3.8 32-bit from python.org first. & pause & exit /b 1)
py -3.8-32 -m pip install --upgrade pip pyinstaller==5.13.2 || goto :fail
if exist dist rmdir /s /q dist
if exist build\pyi rmdir /s /q build\pyi
py -3.8-32 -m PyInstaller --noconfirm --clean --onedir --windowed --name SchoolSystem --icon assets\icon.ico ^
  --add-data "manuals;manuals" --add-data "config.json;." --workpath build\pyi --specpath build\pyi school_system.py || goto :fail
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (echo Inno Setup 6 not found. Install it from jrsoftware.org and run this again. & pause & exit /b 1)
%ISCC% build\windows\installer.iss || goto :fail
echo.
echo DONE: output\SchoolSystemSetup.exe
pause
exit /b 0
:fail
echo BUILD FAILED. Read the messages above.
pause
exit /b 1
