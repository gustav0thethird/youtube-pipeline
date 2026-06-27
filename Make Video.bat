@echo off
setlocal enabledelayedexpansion
REM Launches the Faceless YouTube Studio window.
cd /d "%~dp0"

call :findpy
if not defined PY (
  echo Could not find Python. Run setup.bat first.
  pause
  exit /b 1
)

REM Prefer the windowless interpreter (pythonw / pyw) so no console lingers.
set "PYW=!PY!"
if /i "!PY!"=="py" set "PYW=pyw"
if /i "!PY!"=="python" set "PYW=pythonw"
if /i "!PY!"=="python3" set "PYW=pythonw"
if /i "!PY:~-10!"=="python.exe" set "PYW=!PY:python.exe=pythonw.exe!"

start "" "!PYW!" studio.pyw
exit /b 0

:findpy
set "PY="
REM Pinned interpreter (written by setup_rvc.bat) wins, so RVC's Python 3.12 is used.
if exist "python_path.txt" (
  set /p PY=<python_path.txt
  "!PY!" -c "import sys" >nul 2>nul || set "PY="
)
if defined PY exit /b 0
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
