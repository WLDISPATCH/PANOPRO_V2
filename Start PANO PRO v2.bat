@echo off
setlocal

cd /d "%~dp0"

call "%~dp0find-python.cmd"

if not defined PANOPRO_PY (
  echo Could not find a Python 3 installation on this computer.
  echo Please install Python 3.13 from https://www.python.org/downloads/
  echo and make sure "Add python.exe to PATH" or the py launcher is enabled.
  pause
  exit /b 1
)

REM Prefer pythonw.exe so the app runs without a backend console window.
set "LAUNCH_EXE=%PANOPRO_PYW%"
if not exist "%LAUNCH_EXE%" set "LAUNCH_EXE=%PANOPRO_PY%"

start "" "%LAUNCH_EXE%" -m pano_namer.desktop

exit /b 0
