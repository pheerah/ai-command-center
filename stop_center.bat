@echo off
title Stop AI Dev Command Center
cd /d "%~dp0"

echo ===========================================================
echo       Stopping AI Dev Command Center Background Tasks
echo ===========================================================
echo.

:: Signal scheduler stop
echo Stopping scheduler...
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe backend\smart_router.py stop >nul 2>nul
)

:: Terminate running node server on port 3939 if any
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":3939" ^| findstr "LISTENING"') do (
    echo Terminating Dashboard process PID: %%a
    taskkill /f /pid %%a >nul 2>nul
)

echo Center stopped cleanly.
timeout /t 2 /nobreak >nul
