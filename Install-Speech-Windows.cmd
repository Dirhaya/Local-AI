@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Open Start-Windows.cmd once to create the app environment, then close the app and run this file.
  pause
  exit /b 1
)
echo Installing local speech recognition and downloading the multilingual base model.
echo Internet is needed now. Audio transcription afterwards stays on this computer.
".venv\Scripts\python.exe" -m pip install -r requirements-speech.txt
if errorlevel 1 (
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\download_speech.py --model base
pause
