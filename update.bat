@echo off
REM Portable PANO PRO updater. Copy THIS ONE FILE into an existing PANO PRO
REM folder and double-click it. It downloads the latest code from GitHub into
REM this folder, keeping your data (.pano_namer_data) and environment (.venv).
REM Close the app first.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:PANOPRO_UPDATE_DIR = '%~dp0'.TrimEnd('\'); irm https://raw.githubusercontent.com/WLDISPATCH/PANOPRO_V2/main/scripts/update.ps1 | iex"
echo.
pause
