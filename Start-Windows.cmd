@echo off
setlocal
cd /d "%~dp0"
title Sultan Local AI
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv 2>nul
  if errorlevel 1 py -3.11 -m venv .venv 2>nul
  if errorlevel 1 python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
  echo Install Python 3.12 from https://www.python.org/downloads/ and enable Add Python to PATH.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, cryptography, httpx, multipart, bs4, icalendar, recurring_ical_events, defusedxml, tzdata, pypdf" 2>nul
if errorlevel 1 (
  echo Installing app packages. Internet is needed for this first setup.
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Package installation failed. Check your connection and read the error above.
    pause
    exit /b 1
  )
)
set OLLAMA_NO_CLOUD=1
set HF_HUB_OFFLINE=1
set HF_HUB_DISABLE_TELEMETRY=1
set DO_NOT_TRACK=1
".venv\Scripts\python.exe" run.py
if errorlevel 1 pause
