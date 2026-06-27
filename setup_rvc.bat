@echo off
setlocal enabledelayedexpansion
REM ===========================================================
REM  Optional: enable RVC voice conversion (GPU).
REM  Uses Python 3.11 -- rvc-python pins an old NumPy that only
REM  has prebuilt wheels up to 3.11, so 3.12+ tries (and fails)
REM  to compile it. 3.11 = everything installs from wheels.
REM ===========================================================
cd /d "%~dp0"
echo.
echo === RVC voice setup (Python 3.11 + CUDA PyTorch) ===
echo.

REM ---- find Python 3.11 ----
set "PY="
py -3.11 -c "import sys" >nul 2>nul && set "PY=py -3.11"
if not defined PY (
  for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python311*") do (
    if not defined PY if exist "%%D\python.exe" set "PY=%%D\python.exe"
  )
)
if not defined PY (
  echo [X] Python 3.11 was not found.
  echo     The RVC libraries need 3.11 -- not 3.12 or 3.14. Install it from:
  echo     https://www.python.org/downloads/release/python-3119/   then tick "Add to PATH"
  echo     and run this file again.
  pause
  exit /b 1
)
echo Using: !PY!
echo.

echo [1/5] Build tools...
!PY! -m pip install --upgrade pip setuptools wheel

echo.
echo [2/5] Base packages (Kokoro, Whisper, ffmpeg)...
!PY! -m pip install -r requirements.txt || (echo [X] base install failed & pause & exit /b 1)

echo.
echo [3/5] PyTorch with CUDA 12.1 (large download, ~2.5 GB)...
!PY! -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121 || (echo [X] torch install failed & pause & exit /b 1)

echo.
echo [4/5] RVC (rvc-python)...
!PY! -m pip install rvc-python || (echo [X] rvc-python install failed & pause & exit /b 1)

echo.
echo [5/5] Kokoro model + GPU check...
!PY! -c "import youtube_pipeline as p; p.ensure_models()"
!PY! -c "import torch; print('   CUDA available:', torch.cuda.is_available()); print('   GPU:', (torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU only'))"

REM ---- pin this interpreter (full path) so Make Video.bat uses 3.11 ----
for /f "delims=" %%e in ('!PY! -c "import sys;print(sys.executable)"') do set "PYEXE=%%e"
> python_path.txt echo !PYEXE!

echo.
echo === RVC ready. ===
echo Launch "Make Video.bat", click "+ Add RVC voice", pick your .pth and .index,
echo name it, then choose it in the Voice list.
echo.
pause
