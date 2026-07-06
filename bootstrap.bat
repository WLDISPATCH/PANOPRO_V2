@echo off
REM PANO PRO standalone bootstrap - copy THIS ONE FILE to any computer and run it.
REM Downloads and installs the whole app from GitHub (no other files needed).
REM Re-running updates in place and keeps your data.
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/WLDISPATCH/PANOPRO_V2/main/scripts/bootstrap.ps1 | iex"
echo.
pause
