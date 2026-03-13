@echo off
REM ──────────────────────────────────────────────────────────────────────────
REM  Start both FastAPI backend (port 3001) and React frontend (port 3000).
REM  Usage:  scripts\start_dev.bat
REM  Stop:   Close this window, or press Ctrl+C twice.
REM ──────────────────────────────────────────────────────────────────────────

setlocal
set ROOT=%~dp0..
set SERVER_DIR=%ROOT%\server
set CLIENT_DIR=%ROOT%\client\medscribe
set VENV_PYTHON=%SERVER_DIR%\.venv\Scripts\python.exe

REM ── Preflight ──────────────────────────────────────────────────────────────
if not exist "%VENV_PYTHON%" (
    echo [ERROR] Python venv not found at %VENV_PYTHON%
    echo   Run:  cd server ^&^& python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    exit /b 1
)

where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] npm not found in PATH
    exit /b 1
)

if not exist "%CLIENT_DIR%\node_modules" (
    echo [INFO] Installing frontend dependencies...
    pushd "%CLIENT_DIR%"
    call npm install
    popd
)

REM ── Launch backend in a new window ─────────────────────────────────────────
echo === Starting Backend  (FastAPI :3001) ===
start "MedScribe-Backend" cmd /k "cd /d "%SERVER_DIR%" && "%VENV_PYTHON%" -m uvicorn main:app --reload --host 127.0.0.1 --port 3001"

REM ── Launch frontend in a new window ────────────────────────────────────────
echo === Starting Frontend (React  :3000) ===
start "MedScribe-Frontend" cmd /k "cd /d "%CLIENT_DIR%" && set BROWSER=none && npm start"

echo.
echo Both servers starting:
echo   Backend  -^> http://localhost:3001
echo   Frontend -^> http://localhost:3000
echo.
echo Close the spawned windows to stop each server.
