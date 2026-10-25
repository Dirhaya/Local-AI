@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run Start-Windows.cmd once to install the app packages, then close it and run this check.
  pause
  exit /b 1
)
echo Installing test dependencies. These checks use mocked network calls, not your accounts.
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
if errorlevel 1 (
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pytest -q
pause
