@echo off
setlocal
cd /d "%~dp0"
title Sultan AI - automatic setup
if not exist "scripts\setup_windows.ps1" (
  echo Extract the whole ZIP first: right-click the ZIP and choose Extract All.
  pause
  exit /b 1
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_windows.ps1"
if errorlevel 1 (
  echo.
  echo Setup stopped. Send the error text above or a screenshot in your ChatGPT conversation.
  pause
)
