@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.11 or 3.12 from python.org first, then run this file again.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  py -3.12 -m venv .venv
  if errorlevel 1 py -3.11 -m venv .venv
  if errorlevel 1 (
    echo Python 3.11 or 3.12 is required.
    pause
    exit /b 1
  )
)
if not exist .env copy .env.example .env >nul
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed. Check the output above and your internet connection.
  pause
  exit /b 1
)
echo Open http://127.0.0.1:8000 in your browser. Keep this window open.
echo Make sure Ollama is running and you have run: ollama pull llama3.2:3b
.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
pause
