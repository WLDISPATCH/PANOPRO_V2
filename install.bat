@echo off
REM One-click installer for PANO PRO. Double-click this file on a new machine.
REM It hands off to scripts\install.ps1, which installs Python (if needed),
REM sets up a local environment, and creates a desktop shortcut.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1"
echo.
pause
