@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [wisp_backend] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 goto :error
)

echo [wisp_backend] Checking dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

if not exist ".env" (
    copy ".env.example" ".env" > nul
    echo.
    echo [wisp_backend] Created .env from .env.example.
    echo Add your XAI_API_KEY to .env, then run start.bat again.
    pause
    exit /b 1
)

echo [wisp_backend] Starting on http://127.0.0.1:8000
".venv\Scripts\python.exe" main.py
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo [wisp_backend] Startup failed. See the error above.
pause
exit /b 1
