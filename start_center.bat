@echo off
title AI Dev Command Center
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ===========================================================
echo         AI Dev Command Center - One-Click Launcher
echo ===========================================================
echo.

:: 1. Check Python virtual environment
set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo [ERROR] Python virtual environment not found at .venv\Scripts\python.exe
    pause
    exit /b 1
)

:: 2. Check Node.js
where node >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Node.js is required to run the Dashboard server.
    pause
    exit /b 1
)

:: 3. Start Scheduler Daemon in background
echo [1/3] Starting AI Multi-Provider Scheduler Daemon (Live mode)...
start "AI Command Center - Scheduler" /min "%PYTHON%" backend\smart_router.py serve --mode live

:: 4. Start Dashboard and API Server in background
echo [2/3] Starting Web Dashboard & API Server on port 3939...
start "AI Command Center - Web Dashboard" /min node server.js

:: 5. Wait 2 seconds and open browser
echo [3/3] Opening Dashboard at http://127.0.0.1:3939 ...
timeout /t 2 /nobreak >nul
start http://127.0.0.1:3939

echo.
echo ===========================================================
echo   AI Dev Command Center is now LIVE!
echo   Dashboard URL: http://127.0.0.1:3939
echo   All connected projects can now submit tasks via connector.py
echo   To stop the center, run stop_center.bat
echo ===========================================================
echo.
pause
