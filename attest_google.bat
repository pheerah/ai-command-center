@echo off
title Google Subscription Attestation
cd /d "%~dp0"

echo ===========================================================
echo         AI Dev Command Center - Google Attestation
echo ===========================================================
echo.
echo To ensure no accidental paid API fees occur, the Center requires
echo your confirmation that Google uses your personal subscription.
echo.
echo When prompted, please copy and paste or type this exact phrase:
echo.
echo   I CONFIRM GOOGLE USES MY PERSONAL SUBSCRIPTION, NOT A PAID API KEY
echo.
echo ===========================================================
echo.

.venv\Scripts\python.exe smart_router.py provider attest --plan "Antigravity Personal" google

echo.
pause
