@echo off
setlocal enabledelayedexpansion
REM ===========================================================
REM  One-time setup for the Faceless YouTube Studio.
REM  Double-click this once. It finds Python, installs
REM  everything, and downloads the voice model.
REM ===========================================================
cd /d "%~dp0"
echo.
echo === Faceless YouTube Studio - setup ===
echo.

call :findpy
if not defined PY (
  echo [X] Could not find a working Python.
  echo     Install it from https://www.python.org/downloads/ ^(tick "Add to PATH"^),
  echo     then run this file again.
  pause
  exit /b 1
)
echo Using Python: !PY!
echo.

echo [1/3] Installing Python packages ^(this can take a few minutes^)...
"!PY!" -m pip install --upgrade pip
"!PY!" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [X] Package install failed. Read the messages above.
  pause
  exit /b 1
)

echo.
echo [2/3] Downloading the Kokoro voice model ^(~340 MB, one time^)...
"!PY!" -c "import youtube_pipeline as p; p.ensure_models()"
if errorlevel 1 (
  echo [X] Model download failed. Check your internet connection and re-run.
  pause
  exit /b 1
)

echo.
echo [3/3] Checking FFmpeg...
"!PY!" -c "import youtube_pipeline as p; print('   ffmpeg:', p.FFMPEG)"

echo.
echo === All set! ===
echo Now double-click "Make Video.bat" to open the studio.
echo.
pause
exit /b 0

REM ---- locate a real Python (skips the Windows Store stub) ----
:findpy
set "PY="
for %%C in (py python python3) do (
  if not defined PY (
    %%C -c "import sys" >nul 2>nul && set "PY=%%C"
  )
)
if not defined PY (
  for /d %%D in ("%LOCALAPPDATA%\Python\pythoncore-*") do (
    if not defined PY if exist "%%D\python.exe" set "PY=%%D\python.exe"
  )
)
if not defined PY (
  for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if not defined PY if exist "%%D\python.exe" set "PY=%%D\python.exe"
  )
)
exit /b 0
