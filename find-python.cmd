@echo off
REM ==========================================================================
REM Locates a working Python 3 interpreter on this machine and sets:
REM   PANOPRO_PY   = full path to python.exe   (console interpreter)
REM   PANOPRO_PYW  = full path to pythonw.exe  (windowless interpreter)
REM Both are left empty if no working Python is found.
REM
REM Candidates are validated by actually running them, so a real install
REM (including a Microsoft Store Python) is accepted while the "open the
REM Store" alias stub, which cannot run code, is rejected automatically.
REM
REM This file is CALLed by the Start/Debug launchers. Do not add "setlocal"
REM here or the variables will not survive back to the caller.
REM ==========================================================================

set "PANOPRO_PY="
set "PANOPRO_PYW="

REM --- 0) Repo-local .venv: install.bat / update.bat put PANO PRO's ----------
REM dependencies here, so this must win over any system Python (which may not
REM have fastapi/PySide6 installed). %~dp0 is this file's folder = repo root.
if exist "%~dp0.venv\Scripts\python.exe" call :consider "%~dp0.venv\Scripts\python.exe"
if defined PANOPRO_PY goto :done

REM --- 1) Python launcher (py -3): most reliable on python.org installs ------
for /f "delims=" %%i in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do call :consider "%%i"
if defined PANOPRO_PY goto :done

REM --- 2) python.exe entries on PATH (includes a working Store alias) --------
for /f "delims=" %%i in ('where python 2^>nul') do call :consider "%%i"
if defined PANOPRO_PY goto :done

REM --- 3) Common per-user / system install locations ------------------------
for %%p in (
  "%LocalAppData%\Programs\Python\Python313\python.exe"
  "%LocalAppData%\Programs\Python\Python312\python.exe"
  "%LocalAppData%\Programs\Python\Python311\python.exe"
  "%ProgramFiles%\Python313\python.exe"
  "%ProgramFiles%\Python312\python.exe"
  "%ProgramFiles%\Python311\python.exe"
  "C:\Python313\python.exe"
  "C:\Python312\python.exe"
  "C:\Python311\python.exe"
) do call :consider "%%~p"

goto :done

REM --- Accept the first candidate that exists and actually runs -------------
:consider
if defined PANOPRO_PY goto :eof
set "_cand=%~1"
if "%_cand%"=="" goto :eof
if not exist "%_cand%" goto :eof
"%_cand%" -c "import sys" >nul 2>nul
if errorlevel 1 goto :eof
set "PANOPRO_PY=%_cand%"
for %%i in ("%_cand%") do set "_dir=%%~dpi"
if exist "%_dir%pythonw.exe" set "PANOPRO_PYW=%_dir%pythonw.exe"
goto :eof

:done
set "_cand="
set "_dir="
exit /b 0
