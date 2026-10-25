@echo off
setlocal
title Local AI model setup
where ollama >nul 2>nul
if errorlevel 1 (
  echo Install Ollama from https://ollama.com/download/windows then run this file again.
  pause
  exit /b 1
)
echo This downloads qwen3.5:4b. Smaller alternative: ollama pull qwen3.5:2b
echo To disable cloud features, this sets OLLAMA_NO_CLOUD for your Windows user.
echo Quit Ollama from the taskbar and reopen it after this script finishes.
setx OLLAMA_NO_CLOUD 1 >nul
set OLLAMA_NO_CLOUD=1
ollama pull qwen3.5:4b
if errorlevel 1 echo Start the Ollama app and retry if its server is not running.
pause
