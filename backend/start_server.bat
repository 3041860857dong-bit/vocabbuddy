@echo off
REM VocabBuddy backend launcher — double-click to start the local server.
REM Auto-frees port 8000 if a previous instance is still running.
chcp 65001 >nul 2>&1

set "PORT=8000"
set "VENV_PY=C:\Users\30418\.workbuddy\binaries\python\envs\default\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo ERROR: Python venv not found at %VENV_PY%
    echo        Please create it first, then double-click this file again:
    echo        python -m venv "%VENV_PY%" ^&^& "%VENV_PY%" -m pip install -r backend/requirements.txt
    pause
    exit /b 1
)

REM cd to the project root (parent of this backend\ folder) so "backend.app" is importable
cd /d "%~dp0.."

REM --- Auto-free the port if a previous instance is still listening ---
set "FOUND_PID="
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr /i ":%PORT% " ^| findstr "LISTENING"') do (
    set "FOUND_PID=%%a"
)
if defined FOUND_PID (
    echo [INFO] Port %PORT% occupied by PID %FOUND_PID% -- stopping it so we can rebind...
    taskkill /f /pid %FOUND_PID% >nul 2>&1
    timeout /t 1 >nul
)

echo Starting VocabBuddy backend at http://localhost:%PORT% ...
echo (keep this window open; press Ctrl+C to stop the server)
echo (logs -> backend/logs/vocabbuddy.log  console + daily rotating)
"%VENV_PY%" -m uvicorn backend.app:app --host 127.0.0.1 --port %PORT% --log-config backend/logging.json

echo.
echo Server stopped. Press any key to close this window.
pause >nul
