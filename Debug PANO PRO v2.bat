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

echo Using Python: %PANOPRO_PY%
echo.

REM Debug launcher intentionally uses console python.exe so any startup
REM errors and tracebacks stay visible in this window.
"%PANOPRO_PY%" -m pano_namer.desktop

echo.
echo PANO PRO v2 exited. If there was an error, it should be shown above.
pause
