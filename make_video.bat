@echo off
REM ============================================================
REM  One-click runner for the faceless YouTube pipeline (Windows)
REM  Usage:  make_video.bat my_script.txt
REM ============================================================

REM --- put your free Pexels API key here (https://www.pexels.com/api/) ---
set PEXELS_API_KEY=bRQXjZEw6ZJhs9U3ibSAsstL16RqUS4ungaBjj5loIuym4kXbK3NlG4Y

REM --- which Kokoro voice to use (see voice list in SETUP_WINDOWS.md) ---
set VOICE=af_heart

REM --- caption model size: tiny / base / small (base is a good balance) ---
set WHISPER_SIZE=base

if "%~1"=="" (
  echo Usage: make_video.bat path\to\script.txt  [optional_music.mp3]
  exit /b 1
)

if "%~2"=="" (
  python youtube_pipeline.py "%~1" --voice %VOICE%
) else (
  python youtube_pipeline.py "%~1" --voice %VOICE% --music "%~2"
)

echo.
echo Finished. Look in the "output" folder for your MP4.
pause
