@echo off
REM One-click updater for PANO PRO. Close the app first, then double-click this.
REM Downloads the latest code and re-installs dependencies, keeping your data.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\update.ps1"
echo.
pause
